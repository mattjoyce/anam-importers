#!/usr/bin/env python3
"""purchase_gate (anam card 242): a model proposes a purchase, this decides.

The pipeline reads an invoice or receipt PDF's text through fabric (pattern
extract_purchase), which hands the model's proposal to `handle` as a fabric.completed
event. The model is a scribe and may be wrong, so the proposal is believed only as far
as the page text proves it:

- every value comes with the exact text it was read from, which must be on one line of
  the page, and the value must be what that text says (numbers as decimals, never floats)
- the currency is the one printed beside the grand total, never one from another line
- a ref sits after a word for its own kind (an invoice number after "invoice")
- line totals are quantity times unit price, and subtotal + shipping + tax is the total
- the merchant is on the allow-list, matched from the page's issuer line, not from the mail
- a required value that is missing is a hold; the gate never fills one in

A proposal that passes is filed in the Library: the PDF and its .meta.yaml under
documents/ and one money.purchase under records/, for the anam_documents and anam_records
importers to send. One that fails is held: hold.json in the payload folder says every
reason, and nothing reaches the Library. The payload folder is never edited apart from
adding result.json or hold.json. A file is never overwritten: identical bytes are a
no-op, different bytes are a hold.

Commands:
- handle : judge one fabric.completed event
- health : library has documents/ and records/, mail_spool is a folder, the allow-list reads
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import date as Date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from anam_importer import config as cfg  # noqa: E402
from anam_importer import ductile  # noqa: E402

# GATE_VERSION is written into every filed record's basis. Not configurable: it is this
# file's version, and it is the manifest's.
GATE_VERSION = "0.1.0"

# DEFAULT_MERCHANTS is the allow-list: merchant slug (the Definition's spelling) to the
# pattern that finds its legal entity on the issuer line, and what a bare "$" means in
# that merchant's invoices. The issuer pattern is deliberately not the bare name: a
# Yubico invoice lists "YubiKey - OpenAI Offer" and is not an OpenAI invoice.
DEFAULT_MERCHANTS: Dict[str, Dict[str, Any]] = {
    "anthropic": {"issuer": r"Anthropic,? (PBC|Ireland|Inc|Limited|Ltd)", "symbols": {"$": "USD"}},
    "openai": {"issuer": r"OpenAI,? (LLC|OpCo|Ireland|Inc|Limited|Ltd|Pte)", "symbols": {"$": "USD"}},
    "yubico": {"issuer": r"Yubico( [A-Za-z]+)? Pte|Yubico (AB|Inc|Limited|Ltd)", "symbols": {"$": "USD"}},
}

# Not configurable: the Definition's vocabulary and the file layout the importers read.
SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
SAFE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
ISO_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
ISO_CURRENCY = re.compile(r"^[A-Z]{3}$")

# Codes the gate recognises on a total line. A code outside the set is not a currency
# the gate can vouch for, so the invoice is held. Not configurable: ISO 4217 codes.
CURRENCIES = frozenset("AUD USD EUR GBP NZD CAD SGD JPY CHF CNY HKD INR SEK NOK DKK ZAR KRW".split())
# Symbols whose meaning does not depend on the merchant, and prefixed dollars.
SYMBOLS = {"€": "EUR", "£": "GBP", "US$": "USD", "AU$": "AUD", "A$": "AUD", "NZ$": "NZD",
           "CA$": "CAD", "C$": "CAD", "S$": "SGD", "HK$": "HKD"}
SYMBOL = re.compile(r"(?<![A-Za-z])(US\$|AU\$|A\$|NZ\$|CA\$|C\$|S\$|HK\$|[$€£])")

# The word a line must carry for each amount, so a figure from the wrong line cannot be
# passed off as another. "total" must not be the end of "subtotal".
KIND_WORDS = {
    "subtotal": re.compile(r"sub[\s-]?total", re.I),
    "shipping": re.compile(r"ship|deliver|postage|freight|handling", re.I),
    "tax": re.compile(r"tax|gst|vat", re.I),
    "total": re.compile(r"(?<!sub)(?<!sub-)(?<!sub )total|amount\s+(due|paid)", re.I),
}
REF_WORDS = {"invoice_ref": "invoice", "receipt_ref": "receipt", "order_ref": "order"}
REF_LABEL = re.compile(r"invoice|receipt|order", re.I)

MONTHS = {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), start=1)}

DEFAULT_MAX_TEXT_BYTES = 1_000_000
DEFAULT_MAX_PDF_BYTES = 20 * 1024 * 1024
# Not configurable: how many bytes of a snippet is a line of a page and not the page.
MAX_SNIPPET = 400


class Refusal(ductile.Failure):
    """A request the gate will not act on: a path outside the spool, a folder that is
    not a payload. Nothing is written, since there is no payload folder to trust."""

    def __init__(self, message: str):
        super().__init__(message, retry=False)


# ---------------------------------------------------------------- reading the page

def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def page_lines(page: str) -> List[str]:
    """The page's lines with runs of space collapsed, since pdftotext -layout pads
    columns with spaces, and blank lines dropped."""
    return [n for n in (norm(line) for line in page.splitlines()) if n]


def find_line(lines: List[str], snippet: Any) -> Optional[str]:
    """The first line of the page that holds snippet, or None. A snippet is one line's
    worth of text; one spread over lines or longer than a line is not found."""
    if not isinstance(snippet, str):
        return None
    s = norm(snippet)
    if not s or len(s) > MAX_SNIPPET:
        return None
    for line in lines:
        if s in line:
            return line
    return None


def decimal_of(v: Any) -> Optional[Decimal]:
    """v as an exact decimal. A float is read by its shortest text, which is what the
    JSON parser was given, so 7.8 is 7.8 and not 7.79999..."""
    if isinstance(v, bool) or v is None:
        return None
    try:
        if isinstance(v, float):
            if v != v or v in (float("inf"), float("-inf")):
                return None
            return Decimal(repr(v))
        if isinstance(v, int):
            return Decimal(v)
        if isinstance(v, str):
            return Decimal(v.strip().replace(",", "")) if v.strip() else None
    except InvalidOperation:
        return None
    return None


NUMBER = re.compile(r"(?<![\w.])\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w.])\d+(?:\.\d+)?")


def numbers_in(snippet: str, money: bool) -> List[Tuple[str, Decimal]]:
    """The numbers printed in snippet, as (text, value). A percentage is not one. For
    money, a figure with a decimal point is the amount and a bare integer (a quantity,
    a code) is not, unless the snippet has no decimal figure at all."""
    found = []
    for m in NUMBER.finditer(snippet):
        if snippet[m.end():].lstrip().startswith("%"):
            continue
        text = m.group(0).replace(",", "")
        found.append((text, Decimal(text)))
    if money and any("." in t for t, _ in found):
        found = [(t, d) for t, d in found if "." in t]
    return found


def printed(snippet: str, value: Decimal, money: bool) -> Optional[str]:
    """The text of the number in snippet whose value is value, or None."""
    for text, d in numbers_in(snippet, money):
        if d == value:
            return text
    return None


def dates_in(snippet: str) -> List[Date]:
    """The calendar dates printed in snippet: 2026-10-24, Oct 24, 2026, 24 October 2026
    and 24/10/2026 (day first, as an Australian page prints it)."""
    out: List[Date] = []

    def add(y: str, m: int, d: str) -> None:
        try:
            out.append(Date(int(y), m, int(d)))
        except ValueError:
            pass

    for m in re.finditer(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)", snippet):
        add(m.group(1), int(m.group(2)), m.group(3))
    for m in re.finditer(r"\b([A-Za-z]{3,9})\.? (\d{1,2})(?:st|nd|rd|th)?,? (\d{4})\b", snippet):
        if m.group(1)[:3].lower() in MONTHS:
            add(m.group(3), MONTHS[m.group(1)[:3].lower()], m.group(2))
    for m in re.finditer(r"\b(\d{1,2})(?:st|nd|rd|th)? ([A-Za-z]{3,9})\.?,? (\d{4})\b", snippet):
        if m.group(2)[:3].lower() in MONTHS:
            add(m.group(3), MONTHS[m.group(2)[:3].lower()], m.group(1))
    for m in re.finditer(r"(?<![\d/])(\d{1,2})/(\d{1,2})/(\d{4})(?![\d/])", snippet):
        add(m.group(3), int(m.group(2)), m.group(1))
    return out


# What a small model writes for a field it did not find, instead of leaving it out.
ABSENT = frozenset(["", "null", "none", "n/a", "na", "nil", "unknown", "-"])


def present(proposal: Dict[str, Any], key: str) -> bool:
    """A field the model gave. null and "" are how a small model says it did not
    read one, so they count as left out."""
    v = proposal.get(key)
    return v is not None and not (isinstance(v, str) and v.strip().lower() in ABSENT)


# ---------------------------------------------------------------- the checks

class Checked:
    """What the gate has proved about a proposal: the values it will file, and every
    reason it will not."""

    def __init__(self) -> None:
        self.reasons: List[str] = []
        self.merchant = ""
        self.fields: Dict[str, Any] = {}      # text fields, as filed
        self.amounts: Dict[str, Tuple[str, Decimal]] = {}   # printed text and value
        self.items: List[Dict[str, Any]] = []

    def hold(self, reason: str) -> None:
        self.reasons.append(reason)


def evidence_line(lines: List[str], ev: Dict[str, Any], field: str, out: Checked, where: str = "") -> Optional[str]:
    """The page line the model says it read field from, or a reason it cannot be used."""
    name = where + field
    if field not in ev or not isinstance(ev[field], str):
        out.hold(f"{name}: no evidence given")
        return None
    line = find_line(lines, ev[field])
    if line is None:
        out.hold(f"{name}: the evidence {str(ev[field])[:80]!r} is not on one line of the page")
    return line


def check_amount(lines, ev, proposal, field, out: Checked, kind: Optional[str] = None,
                 where: str = "", money: bool = True, positive: bool = False) -> Optional[Tuple[str, Decimal]]:
    """field's value, proved by its evidence line: the number is printed there, and (for
    a kind of amount) the line carries that kind's word."""
    if not present(proposal, field):
        return None
    value = decimal_of(proposal[field])
    name = where + field
    if value is None:
        out.hold(f"{name}: {proposal[field]!r} is not a number")
        return None
    line = evidence_line(lines, ev, field, out, where)
    if line is None:
        return None
    text = printed(norm(ev[field]), value, money)
    if text is None:
        out.hold(f"{name}: {value} is not a number printed in {norm(ev[field])[:80]!r}")
        return None
    if kind and not KIND_WORDS[kind].search(line):
        out.hold(f"{name}: the line {line[:80]!r} is not labelled {kind}")
        return None
    if positive and value <= 0:
        out.hold(f"{name}: {value} is not more than zero")
        return None
    if field in ("shipping", "tax") and value < 0:
        out.hold(f"{name}: {value} is negative")
        return None
    return text, value


def check_ref(lines, ev, proposal, field, out: Checked) -> None:
    """A ref is printed in its snippet, and on that line the nearest label before it is
    the word for its own kind. The invoice number given as the receipt number fails here."""
    if not present(proposal, field):
        return
    value = proposal[field]
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        out.hold(f"{field}: {value!r} is not text")
        return
    value = str(value).strip()
    line = evidence_line(lines, ev, field, out)
    if line is None:
        return
    spot = re.search(r"(?<![A-Za-z0-9])" + re.escape(value) + r"(?![A-Za-z0-9])", line)
    if not spot or value not in norm(ev[field]):
        out.hold(f"{field}: {value!r} is not printed in the evidence {norm(ev[field])[:80]!r}")
        return
    labels = REF_LABEL.findall(line[:spot.start()])
    want = REF_WORDS[field]
    if not labels:
        out.hold(f"{field}: {value!r} has no label before it on its line {line[:80]!r}")
    elif labels[-1].lower() != want:
        out.hold(f"{field}: {value!r} sits on a line labelled {labels[-1].lower()!r}, not {want!r}: {line[:80]!r}")
    elif not SAFE_REF.match(value):
        out.hold(f"{field}: {value!r} is not usable in a file name")
    else:
        out.fields[field] = value


def verbatim(lines, ev, proposal, field, out: Checked, line_of: Optional[str] = None) -> None:
    """A text value that must be printed exactly. Its evidence line is the proof when
    given; the value is text and can be searched for, so a missing evidence entry is
    not a hold, but a value found nowhere is. line_of limits the search to one line."""
    if not present(proposal, field):
        return
    value = proposal[field]
    if not isinstance(value, str):
        out.hold(f"{field}: {value!r} is not text")
        return
    if isinstance(ev.get(field), str) and ev[field].strip():
        line = evidence_line(lines, ev, field, out)
        if line is None:
            return
        found = norm(value) in norm(ev[field])
    else:
        found = norm(value) in (line_of if line_of is not None else "\n".join(lines))
    if not found:
        out.hold(f"{field}: {value!r} is not printed" + (f" in {line_of[:80]!r}" if line_of else " on the page"))
        return
    out.fields[field] = norm(value)


def issuer(lines: List[str], merchants: Dict[str, Dict[str, Any]], out: Checked) -> Optional[str]:
    """The one allow-listed merchant whose issuer line is on the page."""
    hits = [slug for slug, m in merchants.items() if any(re.search(m["issuer"], line) for line in lines)]
    if not hits:
        out.hold("merchant: no allow-listed issuer is named on the page")
        return None
    if len(hits) > 1:
        out.hold(f"merchant: the page names more than one allow-listed issuer: {', '.join(sorted(hits))}")
        return None
    return hits[0]


def currency_beside(line: str, symbols: Dict[str, str]) -> Optional[str]:
    """The currency a total line prints: its one ISO code, else its one symbol read the
    way the merchant's invoices use it. None when it prints neither or says two things."""
    codes = {c for c in re.findall(r"\b[A-Z]{3}\b", line) if c in CURRENCIES}
    if len(codes) == 1:
        return next(iter(codes))
    if codes:
        return None
    marks = {SYMBOLS.get(s) or symbols.get(s) for s in SYMBOL.findall(line)}
    return next(iter(marks)) if len(marks) == 1 and None not in marks else None


def judge(proposal: Any, page: str, merchants: Dict[str, Dict[str, Any]]) -> Checked:
    """Every check, collecting every reason. The result files only if it holds none."""
    out = Checked()
    if not isinstance(proposal, dict):
        out.hold("the model's proposal is not a JSON object")
        return out
    ev = proposal.get("evidence")
    if not isinstance(ev, dict):
        out.hold("the proposal has no evidence map")
        ev = {}
    lines = page_lines(page)
    if not lines:
        out.hold("the page text is empty")
        return out

    slug = issuer(lines, merchants, out)
    claimed = proposal.get("merchant")
    if slug and isinstance(claimed, str) and claimed.strip():
        spelled = re.sub(r"[^a-z0-9]+", "-", claimed.lower()).strip("-")
        if spelled != slug and not spelled.startswith(slug + "-"):
            out.hold(f"merchant: the model said {claimed!r} but the page's issuer is {slug!r}")
    elif slug and present(proposal, "merchant"):
        out.hold(f"merchant: {claimed!r} is not text")
    if slug:
        out.merchant = slug
    verbatim(lines, ev, proposal, "merchant_legal_entity", out)

    for field in ("invoice_ref", "receipt_ref", "order_ref"):
        check_ref(lines, ev, proposal, field, out)
    if "invoice_ref" not in out.fields and "receipt_ref" not in out.fields:
        out.hold("required: an invoice_ref or receipt_ref that passed its checks")

    # date
    if not present(proposal, "date"):
        out.hold("required: date is missing")
    else:
        d = proposal["date"]
        line = evidence_line(lines, ev, "date", out)
        if not isinstance(d, str) or not ISO_DATE.match(d):
            out.hold(f"date: {d!r} is not YYYY-MM-DD")
        elif line is not None:
            if d not in {x.isoformat() for x in dates_in(norm(ev["date"]))}:
                out.hold(f"date: {d} is not a date printed in {norm(ev['date'])[:80]!r}")
            else:
                out.fields["date"] = d

    # amounts
    for field, kind in (("subtotal", "subtotal"), ("shipping", "shipping"), ("tax", "tax"), ("total", "total")):
        got = check_amount(lines, ev, proposal, field, out, kind)
        if got:
            out.amounts[field] = got
    if "total" not in out.amounts and not present(proposal, "total"):
        out.hold("required: total is missing")
    tax_line = find_line(lines, ev.get("tax")) if "tax" in out.amounts else None
    verbatim(lines, ev, proposal, "tax_label", out, line_of=tax_line or "")
    if "tax_label" in out.fields and tax_line is not None and out.fields["tax_label"] not in tax_line:
        out.hold(f"tax_label: {out.fields['tax_label']!r} is not on the tax line {tax_line[:80]!r}")
        del out.fields["tax_label"]

    # currency: the gate reads it from the total's own line (an ISO code, else the symbol
    # as the merchant's invoices use it). The model may name it, and then must agree;
    # a page that prints only "$" gives the model nothing to read, so it may leave it out.
    if "total" in out.amounts:
        total_line = find_line(lines, ev.get("total")) or ""
        printed_cur = currency_beside(total_line, merchants[slug]["symbols"] if slug else {})
        said = proposal.get("currency") if present(proposal, "currency") else None
        if printed_cur is None:
            out.hold(f"currency: no currency is printed beside the total on {total_line[:80]!r}")
        elif said is None:
            out.fields["currency"] = printed_cur
        elif not isinstance(said, str) or not ISO_CURRENCY.match(said):
            out.hold(f"currency: {said!r} is not a three-letter code")
        elif printed_cur != said:
            out.hold(f"currency: the model said {said} but the total line prints {printed_cur}: {total_line[:80]!r}")
        else:
            out.fields["currency"] = said
    elif present(proposal, "currency"):
        out.hold("currency: not checked, because the total did not pass")
    else:
        out.hold("required: currency is missing")

    check_items(lines, proposal, out)
    check_arithmetic(out)
    return out


def check_items(lines, proposal, out: Checked) -> None:
    raw = proposal.get("items")
    if raw is None:
        return
    if not isinstance(raw, list):
        out.hold("items: not a list")
        return
    for i, item in enumerate(raw):
        where = f"items[{i}]."
        if not isinstance(item, dict) or not present(item, "name") or not isinstance(item["name"], str):
            out.hold(f"items[{i}]: no name")
            continue
        # An item's evidence is its row, one line proving every field, or a map of
        # field to line.
        iev = item.get("evidence")
        if isinstance(iev, str):
            iev = dict.fromkeys(("name", "quantity", "unit_price", "line_total"), iev)
        elif not isinstance(iev, dict):
            iev = {}
        line = evidence_line(lines, iev, "name", out, where)
        if line is None:
            continue
        if norm(item["name"]) not in norm(iev["name"]):
            out.hold(f"{where}name: {item['name']!r} is not in the evidence {norm(iev['name'])[:80]!r}")
            continue
        entry: Dict[str, Any] = {"name": norm(item["name"])}
        for field, money in (("quantity", False), ("unit_price", True), ("line_total", True)):
            got = check_amount(lines, iev, item, field, out, where=where, money=money, positive=field == "quantity")
            if got:
                entry[field] = got
        out.items.append(entry)


def check_arithmetic(out: Checked) -> None:
    """Exact decimal sums, where the page printed the parts. A page that prints a
    discount or a tax-inclusive total fails here and is held for a person."""
    for i, it in enumerate(out.items):
        if all(k in it for k in ("quantity", "unit_price", "line_total")):
            q, u, t = it["quantity"][1], it["unit_price"][1], it["line_total"][1]
            # A unit price may print more places than the money does ($10.064091 for a
            # line of $10.06), so the product is rounded to the line total's own places.
            if q * u != t and (q * u).quantize(t, rounding=ROUND_HALF_UP) != t:
                out.hold(f"items[{i}]: {q} x {u} is {q * u}, but the line total is {t}")
    line_totals = [it["line_total"][1] for it in out.items if "line_total" in it]
    have_all = bool(out.items) and len(line_totals) == len(out.items)
    sub = out.amounts.get("subtotal")
    if sub and have_all and sum(line_totals) != sub[1]:
        out.hold(f"subtotal: the lines add to {sum(line_totals)}, but the subtotal is {sub[1]}")
    total = out.amounts.get("total")
    base = sub[1] if sub else (sum(line_totals) if have_all else None)
    if total and base is not None:
        got = base + (out.amounts["shipping"][1] if "shipping" in out.amounts else 0) \
            + (out.amounts["tax"][1] if "tax" in out.amounts else 0)
        if got != total[1]:
            out.hold(f"total: subtotal, shipping and tax add to {got}, but the total is {total[1]}")


# ---------------------------------------------------------------- what is filed

def q(s: str) -> str:
    """s as a YAML double-quoted scalar, which the records reader reads as text."""
    return json.dumps(s, ensure_ascii=False)


def month_day(d: str) -> str:
    y, m, day = d.split("-")
    return f"{int(day)} {list(MONTHS)[int(m) - 1].capitalize()} {y}"


def identity_ref(c: Checked) -> str:
    f = c.fields
    return f.get("order_ref") or f.get("invoice_ref") or f["receipt_ref"]


def purchase_id(c: Checked) -> str:
    return f"records:purchase/{c.merchant}/{identity_ref(c)}"


def purchase_yaml(c: Checked, pdf_name: str, pdf_sha: str, message_id: str, model: str) -> str:
    f, a = c.fields, c.amounts
    ref = identity_ref(c)
    rows = [
        "# Written by purchase_gate " + GATE_VERSION + " (anam card 242) from an emailed invoice or receipt:",
        "# the model proposed, the gate checked each value against the page text.",
        "document:", f"  name: {q(pdf_name)}", f"  sha256: {q(pdf_sha)}",
        "extracted:", "  method: purchase_gate", f"  version: {q(GATE_VERSION)}",
        "records:",
        "  - type: money.purchase",
        f"    id: {q(purchase_id(c))}",
        f"    date: {q(f['date'])}",
        f"    merchant: {c.merchant}",
    ]
    if "merchant_legal_entity" in f:
        rows.append(f"    merchant_legal_entity: {q(f['merchant_legal_entity'])}")
    rows.append(f"    order_ref: {q(ref)}")
    # The Definition has one slot for "the invoice or receipt number"; a second number
    # goes in source_note.
    other = ""
    if "invoice_ref" in f:
        rows.append(f"    invoice_ref: {q(f['invoice_ref'])}")
        if "receipt_ref" in f:
            other = f"receipt number {f['receipt_ref']}"
    else:
        rows.append(f"    invoice_ref: {q(f['receipt_ref'])}")
        other = "the number in invoice_ref is the receipt number"
    if c.items:
        rows.append("    items:")
        for it in c.items:
            parts = [f"name: {q(it['name'])}"] + [f"{k}: {it[k][0]}" for k in ("quantity", "unit_price", "line_total") if k in it]
            rows.append("      - {" + ", ".join(parts) + "}")
    for k in ("subtotal", "shipping", "tax"):
        if k in a:
            rows.append(f"    {k}: {a[k][0]}")
    if "tax_label" in f:
        rows.append(f"    tax_label: {q(f['tax_label'])}")
    rows.append(f"    total: {a['total'][0]}")
    rows.append(f"    currency: {f['currency']}")
    reader = model or "an unnamed model"
    basis = f"mail {message_id}, read by {reader}, checked by purchase_gate {GATE_VERSION}"
    rows.append(f"    basis: {q(basis)}")
    if other:
        rows.append(f"    source_note: {q(other)}")
    return "\n".join(rows) + "\n"


def document_kind(c: Checked) -> str:
    """A receipt carries a receipt number; anything else is filed as an invoice."""
    return "receipt" if "receipt_ref" in c.fields else "invoice"


def sidecar_yaml(c: Checked, message_id: str) -> str:
    f, a = c.fields, c.amounts
    kind = document_kind(c)
    ref = f[f"{kind}_ref"]
    title = f"{c.merchant.capitalize()} {kind} {ref}, {month_day(f['date'])}"
    note = (f"{c.merchant.capitalize()} {kind} {ref}, {f['currency']} {a['total'][0]}; emailed as message {message_id}, "
            f"filed by purchase_gate {GATE_VERSION} after checking the figures against the page text.")
    return f"date: {q(f['date'])}\ntitle: {q(title)}\nnote: {q(note)}\n"


def file_name(c: Checked) -> str:
    f, kind = c.fields, document_kind(c)
    return f"{f['date']}_{c.merchant}_{kind}_{f[kind + '_ref']}"


def put(path: Path, body: bytes) -> str:
    """Write body at path unless it is there. 'new' when written, 'same' when the file
    already holds exactly these bytes, 'differs' when it holds others (and is untouched).
    The write is a hard link from a temporary file, so a reader never sees half a file
    and an existing file is never replaced."""
    if path.exists():
        return "same" if path.read_bytes() == body else "differs"
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".gate-")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(body)
        os.chmod(tmp, 0o644)  # the importers may run as another user
        try:
            os.link(tmp, path)
        except FileExistsError:
            return "same" if path.read_bytes() == body else "differs"
    finally:
        os.unlink(tmp)
    return "new"


def file_it(library: Path, c: Checked, pdf: bytes, message_id: str, model: str) -> Tuple[List[str], List[str]]:
    """Plan the three files, refuse if any would overwrite, then write. Returns the
    files' paths and the reasons it did not."""
    base = file_name(c)
    docs, recs = library / "documents", library / "records"
    sha = hashlib.sha256(pdf).hexdigest()
    plan = [
        (docs / f"{base}.pdf", pdf),
        (docs / f"{base}.pdf.meta.yaml", sidecar_yaml(c, message_id).encode()),
        (recs / f"{base}.yaml", purchase_yaml(c, f"{base}.pdf", sha, message_id, model).encode()),
    ]
    id_line = f"    id: {q(purchase_id(c))}\n"
    problems = []
    for other in sorted(recs.glob("*.y*ml")):
        if other.name == plan[2][0].name:
            continue
        text = other.read_text(encoding="utf-8", errors="replace")
        if id_line not in text:
            continue
        # The purchase is filed already, from another document (an invoice and its
        # receipt describe one purchase). The records file stays as it is when it agrees
        # on the figures, and only this document is added; otherwise it is a hold.
        facts = [f"    date: {q(c.fields['date'])}\n", f"    total: {c.amounts['total'][0]}\n",
                 f"    currency: {c.fields['currency']}\n", f"    merchant: {c.merchant}\n"]
        if all(line in text for line in facts):
            plan = plan[:2]
        else:
            problems.append(f"the purchase is already in {other.name} with other figures, and two records files may not claim one id")
    for path, body in plan:
        if path.exists() and path.read_bytes() != body:
            problems.append(f"{path.name} already exists with different bytes; the gate does not overwrite")
    if problems:
        return [], problems
    for path, body in plan:
        if put(path, body) == "differs":  # lost a race since the check
            return [], [f"{path.name} appeared with different bytes; the gate does not overwrite"]
    return [str(p) for p, _ in plan], []


# ---------------------------------------------------------------- the command

def inside(spool: Path, value: Any, what: str) -> Path:
    """value (absolute, or relative to the spool) resolved through symlinks, which must
    sit under the spool."""
    if not isinstance(value, str) or not value:
        raise Refusal(f"{what} is missing from the event")
    p = Path(value)
    p = (p if p.is_absolute() else spool / p).resolve()
    if not p.is_relative_to(spool):
        raise Refusal(f"{what} {value!r} is outside mail_spool")
    return p


def merchants_of(config: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    raw = config.get("merchants", DEFAULT_MERCHANTS)
    if not isinstance(raw, dict) or not raw:
        raise cfg.bad("merchants", "want a map of merchant to {issuer, symbols}")
    out = {}
    for slug, m in raw.items():
        if not isinstance(slug, str) or not SLUG.match(slug) or not isinstance(m, dict) or not isinstance(m.get("issuer"), str):
            raise cfg.bad("merchants", f"{slug!r}: want a slug with an issuer pattern")
        try:
            re.compile(m["issuer"])
        except re.error as exc:
            raise cfg.bad("merchants", f"{slug}: issuer pattern: {exc}") from exc
        symbols = m.get("symbols", {})
        if not isinstance(symbols, dict) or not all(isinstance(k, str) and isinstance(v, str) and ISO_CURRENCY.match(v) for k, v in symbols.items()):
            raise cfg.bad("merchants", f"{slug}: symbols want a map of symbol to ISO code")
        out[slug] = {"issuer": m["issuer"], "symbols": symbols}
    return out


def folders(config: Dict[str, Any]) -> Tuple[Path, Path]:
    for key in ("library", "mail_spool"):
        if not isinstance(config.get(key), str) or not config[key]:
            raise cfg.bad(key, "is required")
    library, spool = Path(config["library"]).expanduser().resolve(), Path(config["mail_spool"]).expanduser().resolve()
    return library, spool


def write_json(path: Path, body: Dict[str, Any]) -> None:
    """Add path beside the payload; an earlier result or hold from a rerun is replaced."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".gate-")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(body, fh, indent=2, sort_keys=True, ensure_ascii=False)
        fh.write("\n")
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def handle(request: Dict[str, Any]) -> Dict[str, Any]:
    config = request.get("config") or {}
    library, spool = folders(config)
    merchants = merchants_of(config)
    max_text = cfg.integer(config, "max_text_bytes", DEFAULT_MAX_TEXT_BYTES, 1, 64 * 1024 * 1024)
    max_pdf = cfg.integer(config, "max_pdf_bytes", DEFAULT_MAX_PDF_BYTES, 1, 1024 * 1024 * 1024)
    p = ductile.payload_of(request)

    txt = inside(spool, p.get("input_file"), "input_file")
    pdf_path = inside(spool, p.get("pdf") or p.get("file_path") or (str(txt)[:-4] if str(txt).endswith(".txt") else None), "pdf")
    payload_dir = inside(spool, p.get("payload_dir") or p.get("folder") or str(pdf_path.parent.parent), "payload_dir")
    if payload_dir.parent != spool or not payload_dir.is_dir():
        raise Refusal(f"payload_dir {payload_dir} is not a folder directly under mail_spool")
    if pdf_path.parent != payload_dir / "attachments" or txt != pdf_path.with_name(pdf_path.name + ".txt"):
        raise Refusal("pdf and input_file are not an attachment and its .txt in the payload folder")
    if not (library / "documents").is_dir() or not (library / "records").is_dir():
        raise cfg.bad("library", f"{library} has no documents/ and records/")

    reasons: List[str] = []
    message_id = ""
    try:
        meta = json.loads((payload_dir / "message.json").read_text(encoding="utf-8"))
        message_id = str(meta["message_id"])
    except (OSError, ValueError, KeyError, TypeError):
        reasons.append("message.json is missing or has no message_id, so the filing cannot name its mail")
    if not txt.is_file() or txt.stat().st_size > max_text:
        raise Refusal(f"{txt.name} is not a text file of at most {max_text} bytes")
    if not pdf_path.is_file() or pdf_path.stat().st_size > max_pdf:
        raise Refusal(f"{pdf_path.name} is not a file of at most {max_pdf} bytes")
    pdf = pdf_path.read_bytes()
    if not pdf.startswith(b"%PDF"):
        reasons.append("the attachment does not start with %PDF")

    model = str(p.get("model") or "")
    proposal = p.get("data")
    checked = judge(proposal, txt.read_text(encoding="utf-8", errors="replace"), merchants)
    reasons += checked.reasons

    files: List[str] = []
    if not reasons:
        files, problems = file_it(library, checked, pdf, message_id, model)
        reasons += problems
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if reasons:
        write_json(payload_dir / "hold.json", {"status": "held", "reasons": reasons, "message_id": message_id,
                                               "gate": GATE_VERSION, "model": model, "at": now, "proposal": proposal})
        return ductile.ok(f"held, {len(reasons)} reason(s): {'; '.join(reasons)[:600]}")
    write_json(payload_dir / "result.json", {"status": "filed", "files": files, "message_id": message_id,
                                             "gate": GATE_VERSION, "model": model, "at": now})
    return ductile.ok(f"filed {Path(files[0]).stem}")


def health(request: Dict[str, Any]) -> Dict[str, Any]:
    config = request.get("config") or {}
    library, spool = folders(config)
    merchants_of(config)
    for sub in ("documents", "records"):
        if not (library / sub).is_dir():
            raise cfg.bad("library", f"{library / sub} is not a folder")
    if not spool.is_dir():
        raise cfg.bad("mail_spool", f"{spool} is not a folder")
    return ductile.ok("library and mail_spool are folders and the merchants read")


if __name__ == "__main__":
    ductile.run({"handle": handle, "health": health})
