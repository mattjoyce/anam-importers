"""purchase_gate (anam card 242): a model's proposal is filed only as far as the page text
proves it. Every page and proposal here is synthetic; the two mistakes the gemma-3-4b
trial made on real invoices are reproduced on invented ones and must be held.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from tests.helpers import REPO, run_plugin

PLUGIN = REPO / "purchase_gate" / "run.py"
RECORDS = REPO / "records" / "run.py"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gate = load(PLUGIN, "purchase_gate_run")

# A page laid out like a Yubico invoice, including the line that tripped the model: a
# tax converted into another currency, with no dollar sign, below the real tax.
KEYS_PAGE = """\
                              Yubico Singapore Pte. Ltd.         ABN number: 00 000 000 000
                              1 Example Avenue                   orders@example.invalid


INVOICE
Invoice: INV-TEST-0001                              Customer Reference: A. Customer
Yubico Order: ORD-TEST-0002                         Yubico Reference: Web Store
Invoice Date: Oct 24, 2026


Order Details
Qty    SKU                   AN             Product Description                      Price                   Subtotal

2      0000000000001         100001         YubiKey - Test Offer                     $34.00                      $68.00


                                                                                      Subtotal:                  $68.00
                                                                         Shipping and Handling:                  $10.00
                                                                                      Tax 10%:                    $7.80
                                                                                          Tax 10%:          11.13 AUD
                                                                                     Grand Total:                $85.80
"""

ROW = "2      0000000000001         100001         YubiKey - Test Offer                     $34.00                      $68.00"

KEYS = {
    "merchant": "Yubico",
    "merchant_legal_entity": "Yubico Singapore Pte. Ltd.",
    "invoice_ref": "INV-TEST-0001",
    "order_ref": "ORD-TEST-0002",
    "date": "2026-10-24",
    "items": [{"name": "YubiKey - Test Offer", "quantity": 2, "unit_price": 34.0, "line_total": 68.0,
               "evidence": {"name": ROW, "quantity": ROW, "unit_price": ROW, "line_total": ROW}}],
    "subtotal": 68.0, "shipping": 10.0, "tax": 7.8, "tax_label": "Tax", "total": 85.8, "currency": "USD",
    "evidence": {
        "merchant_legal_entity": "Yubico Singapore Pte. Ltd.",
        "invoice_ref": "Invoice: INV-TEST-0001",
        "order_ref": "Yubico Order: ORD-TEST-0002",
        "date": "Invoice Date: Oct 24, 2026",
        "subtotal": "Subtotal:                  $68.00",
        "shipping": "Shipping and Handling:                  $10.00",
        "tax": "Tax 10%:                    $7.80",
        "tax_label": "Tax 10%:                    $7.80",
        "total": "Grand Total:                $85.80",
        "currency": "Grand Total:                $85.80",
    },
}

# An Anthropic-shaped receipt: the dollar amount carries its code, and the page has an
# invoice number and a different receipt number on separate lines.
SAAS_PAGE = """\
Receipt from Anthropic, PBC
Invoice number   TEST-0001
Receipt number   1111-2222-3333
Date paid        October 1, 2026

Description                 Qty   Unit price     Amount
Test plan                   1     $100.00        $100.00

Subtotal                                         $100.00
Tax (GST 10%)                                     $10.00
Total                                            $110.00
Amount paid                                      $110.00 USD
"""

SAAS = {
    "merchant": "anthropic",
    "invoice_ref": "TEST-0001",
    "receipt_ref": "1111-2222-3333",
    "date": "2026-10-01",
    "items": [{"name": "Test plan", "quantity": 1, "unit_price": 100.0, "line_total": 100.0,
               "evidence": {k: "Test plan                   1     $100.00        $100.00"
                            for k in ("name", "quantity", "unit_price", "line_total")}}],
    "subtotal": 100.0, "tax": 10.0, "tax_label": "GST", "total": 110.0, "currency": "USD",
    "evidence": {
        "invoice_ref": "Invoice number   TEST-0001",
        "receipt_ref": "Receipt number   1111-2222-3333",
        "date": "Date paid        October 1, 2026",
        "subtotal": "Subtotal                                         $100.00",
        "tax": "Tax (GST 10%)                                     $10.00",
        "tax_label": "Tax (GST 10%)                                     $10.00",
        "total": "Amount paid                                      $110.00 USD",
        "currency": "Amount paid                                      $110.00 USD",
    },
}

MERCHANTS = gate.DEFAULT_MERCHANTS


def edited(base: Dict[str, Any], **changes) -> Dict[str, Any]:
    """A copy of a proposal with fields replaced; a value of ... removes the field."""
    out = copy.deepcopy(base)
    for k, v in changes.items():
        if v is ...:
            out.pop(k, None)
        else:
            out[k] = v
    return out


def with_evidence(base: Dict[str, Any], **changes) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in changes.items():
        if v is ...:
            out["evidence"].pop(k, None)
        else:
            out["evidence"][k] = v
    return out


def judge(proposal, page=KEYS_PAGE, merchants=MERCHANTS):
    return gate.judge(proposal, page, merchants)


class JudgeTest(unittest.TestCase):
    def assertHeld(self, proposal, needle, page=KEYS_PAGE, merchants=MERCHANTS):
        out = judge(proposal, page, merchants)
        both = out.reasons + out.dropped
        self.assertTrue(any(needle in r for r in both), f"want a reason with {needle!r}, got {both}")
        return out

    def assertMissing(self, proposal, needle, page=KEYS_PAGE, merchants=MERCHANTS):
        """A required value failed: there is no purchase record."""
        out = judge(proposal, page, merchants)
        self.assertTrue(any(needle in r for r in out.reasons), f"want a required reason with {needle!r}, got {out.reasons}")
        return out

    def assertDropped(self, proposal, needle, page=KEYS_PAGE, merchants=MERCHANTS):
        """An optional value failed: it is left out and the rest stands."""
        out = judge(proposal, page, merchants)
        self.assertEqual(out.reasons, [])
        self.assertTrue(any(needle in r for r in out.dropped), f"want a dropped reason with {needle!r}, got {out.dropped}")
        return out

    def test_good_proposals_pass(self):
        out = judge(KEYS)
        self.assertEqual(out.reasons, [])
        self.assertEqual(out.merchant, "yubico")
        self.assertEqual(out.fields["currency"], "USD")
        self.assertEqual(out.amounts["total"][0], "85.80")
        self.assertEqual(judge(SAAS, SAAS_PAGE).reasons, [])

    def test_the_currency_from_a_tax_conversion_line_is_held(self):
        # gemma's mistake on a real invoice: it said AUD, from the "11.13 AUD" line.
        wrong = edited(KEYS, currency="AUD")
        wrong["evidence"]["currency"] = "Tax 10%:          11.13 AUD"
        out = self.assertHeld(wrong, "currency")
        self.assertNotIn("currency", out.fields)
        # even with honest evidence the gate reads the total's own line
        self.assertHeld(edited(KEYS, currency="AUD"), "the total line prints USD")

    def test_a_currency_the_total_line_does_not_print_is_held(self):
        no_symbols = {"yubico": {"issuer": MERCHANTS["yubico"]["issuer"], "symbols": {}}}
        self.assertHeld(KEYS, "no currency is printed beside the total", merchants=no_symbols)
        # no code to read and no symbol meaning: nothing to file a currency from
        self.assertHeld(edited(KEYS, currency=...), "no currency is printed", merchants=no_symbols)
        # the model may leave it out when the gate can read it from the total line
        out = judge(edited(KEYS, currency=...))
        self.assertEqual((out.reasons, out.fields["currency"]), ([], "USD"))
        # or name something that is not a code
        self.assertHeld(edited(KEYS, currency="dollars"), "not a three-letter code")

    def test_an_invoice_number_given_as_the_receipt_number_is_held(self):
        # gemma's mistake on a real receipt: the invoice number in the receipt field.
        wrong = edited(SAAS, receipt_ref="TEST-0001")
        wrong["evidence"]["receipt_ref"] = "Invoice number   TEST-0001"
        self.assertHeld(wrong, "sits on a line labelled 'invoice', not 'receipt'", SAAS_PAGE)
        # and an order number on an invoice line, and the reverse
        self.assertHeld(edited(KEYS, order_ref="INV-TEST-0001", evidence=dict(KEYS["evidence"], order_ref="Invoice: INV-TEST-0001")),
                        "not 'order'")
        self.assertHeld(edited(SAAS, invoice_ref="1111-2222-3333", evidence=dict(SAAS["evidence"], invoice_ref="Receipt number   1111-2222-3333")),
                        "not 'invoice'", SAAS_PAGE)

    def test_a_ref_with_no_label_is_held(self):
        page = KEYS_PAGE.replace("Invoice: INV-TEST-0001", "INV-TEST-0001")
        self.assertHeld(with_evidence(KEYS, invoice_ref="INV-TEST-0001"), "has no label", page)

    def test_every_value_needs_evidence_on_the_page(self):
        self.assertHeld(with_evidence(KEYS, total=...), "total: no evidence given")
        self.assertHeld(with_evidence(KEYS, total="Grand Total:  $99.99"), "not on one line of the page")
        self.assertHeld(with_evidence(KEYS, total="Subtotal:                  $68.00\nShipping and Handling:                  $10.00"),
                        "not on one line")
        self.assertHeld(with_evidence(KEYS, date="Invoice Date: Oct 25, 2026"), "not on one line")

    def test_a_value_must_be_what_the_evidence_says(self):
        self.assertHeld(edited(KEYS, total=85.81), "85.81 is not a number printed")
        self.assertHeld(edited(KEYS, date="2026-10-23"), "not a date printed")
        self.assertHeld(edited(KEYS, invoice_ref="INV-TEST-0009"), "is not printed in the evidence")
        self.assertHeld(edited(KEYS, tax_label="GST"), "tax_label")
        # a percentage in a line is not the amount
        self.assertHeld(edited(KEYS, tax=10), "tax: 10 is not a number printed")

    def test_the_legal_entity_comes_from_the_allow_list(self):
        page = SAAS_PAGE.replace("Receipt from Anthropic, PBC", "Receipt from Anthropic, PBC @anthropic")
        # the model copies the clutter; the filed value is the allow-list's spelling
        out = judge(edited(SAAS, merchant_legal_entity="Anthropic, PBC @anthropic"), page)
        self.assertEqual(out.reasons, [])
        self.assertEqual(out.fields["merchant_legal_entity"], "Anthropic, PBC")
        # the model giving none, or a wrong one, changes nothing
        self.assertEqual(judge(SAAS, SAAS_PAGE).fields["merchant_legal_entity"], "Anthropic, PBC")
        self.assertEqual(judge(edited(KEYS, merchant_legal_entity="Nonsense Inc")).fields["merchant_legal_entity"],
                         "Yubico Singapore Pte. Ltd.")
        # the entity is left out when the page does not print that spelling
        other = SAAS_PAGE.replace("Anthropic, PBC", "Anthropic Ireland")
        self.assertNotIn("merchant_legal_entity", judge(SAAS, other).fields)

    def test_a_text_value_needs_no_evidence_but_must_be_on_the_page(self):
        no_evidence = with_evidence(KEYS, merchant_legal_entity=..., tax_label=...)
        self.assertEqual(judge(no_evidence).reasons, [])
        self.assertHeld(with_evidence(edited(KEYS, tax_label="Shipping"), tax_label=...), "tax_label")

    def test_the_wrong_line_for_the_kind_is_held(self):
        # the subtotal given for the total, the tax for the shipping
        self.assertHeld(edited(KEYS, total=68.0, evidence=dict(KEYS["evidence"], total=KEYS["evidence"]["subtotal"])),
                        "not labelled total")
        self.assertHeld(edited(KEYS, shipping=7.8, evidence=dict(KEYS["evidence"], shipping=KEYS["evidence"]["tax"])),
                        "not labelled shipping")

    def test_numbers_are_compared_as_decimals(self):
        page = KEYS_PAGE.replace(ROW, "3      0000000000001         100001         YubiKey - Test Offer                     $0.10                      $0.30")
        row = "3      0000000000001         100001         YubiKey - Test Offer                     $0.10                      $0.30"
        # 3 * 0.1 is 0.30000000000000004 as floats
        p = edited(KEYS, items=[{"name": "YubiKey - Test Offer", "quantity": 3, "unit_price": 0.1, "line_total": 0.3,
                                 "evidence": dict.fromkeys(("name", "quantity", "unit_price", "line_total"), row)}],
                   subtotal=0.3, shipping=10.0, tax=7.8, total=18.1)
        p["evidence"] = dict(KEYS["evidence"], subtotal="Subtotal:                  $68.00")
        page = page.replace("$68.00\n                                                                         Shipping", "$0.30\n                                                                         Shipping")
        page = page.replace("Subtotal:                  $68.00", "Subtotal:                  $0.30").replace("$85.80", "$18.10")
        p["evidence"].update(subtotal="Subtotal:                  $0.30", total="Grand Total:                $18.10",
                             currency="Grand Total:                $18.10")
        self.assertEqual(judge(p, page).reasons, [])
        self.assertEqual(float(0.1) * 3 == 0.3, False)

    def test_an_item_may_carry_its_row_as_one_evidence_string(self):
        p = copy.deepcopy(KEYS)
        p["items"][0]["evidence"] = ROW
        self.assertEqual(judge(p).reasons, [])
        p["items"][0]["evidence"] = "Qty    SKU                   AN             Product Description                      Price                   Subtotal"
        self.assertHeld(p, "is not in the evidence")

    def test_arithmetic_is_checked(self):
        page = KEYS_PAGE.replace("$85.80", "$85.70")
        wrong_total = with_evidence(edited(KEYS, total=85.7), total="Grand Total:                $85.70",
                                    currency="Grand Total:                $85.70")
        self.assertHeld(wrong_total, "add to 85.8, but the total is 85.7", page)
        page = KEYS_PAGE.replace("$34.00", "$35.00")
        row = ROW.replace("$34.00", "$35.00")
        bad = copy.deepcopy(KEYS)
        bad["items"][0].update(unit_price=35.0)
        bad["items"][0]["evidence"] = dict.fromkeys(("name", "quantity", "unit_price", "line_total"), row)
        self.assertHeld(bad, "2 x 35.0 is 70.0, but the line total is 68.0", page)

    def test_the_tax_conversion_line_cannot_stand_in_for_the_tax(self):
        wrong = edited(KEYS, tax=11.13, evidence=dict(KEYS["evidence"], tax="Tax 10%:          11.13 AUD"))
        self.assertHeld(wrong, "add to 89.13")

    def test_the_merchant_is_read_from_the_page(self):
        self.assertHeld(edited(KEYS, merchant="openai"), "the page's issuer is 'yubico'")
        # the item name mentions another merchant; the issuer line decides
        page = KEYS_PAGE.replace("Test Offer", "OpenAI Offer")
        self.assertEqual(judge(edited(KEYS), page).merchant, "yubico")
        unknown = KEYS_PAGE.replace("Yubico Singapore Pte. Ltd.", "Elsewhere Pty Ltd")
        self.assertHeld(KEYS, "no allow-listed issuer", unknown)
        two = KEYS_PAGE + "\nOpenAI, LLC\n"
        self.assertHeld(KEYS, "more than one allow-listed issuer", two)

    def test_required_fields_are_never_filled_in(self):
        for field in ("date", "total"):
            self.assertHeld(edited(KEYS, **{field: ...}), f"{field} is missing")
        both = edited(KEYS, invoice_ref=..., order_ref=...)
        self.assertHeld(both, "an invoice_ref or receipt_ref")
        for blank in (None, ""):
            self.assertHeld(edited(KEYS, date=blank), "date is missing")
        self.assertHeld({"merchant": "yubico"}, "no evidence map")
        # null and "N/A" are a small model's way of leaving a field out
        self.assertEqual(judge(edited(KEYS, order_ref="N/A", receipt_ref=None)).reasons, [])
        # a figure left out does not hide that the rest no longer adds up
        self.assertHeld(edited(KEYS, shipping=None), "add to 75.8, but the total is 85.8")
        # the merchant may be given as the legal name
        self.assertEqual(judge(edited(KEYS, merchant="Yubico Singapore Pte. Ltd.")).reasons, [])
        self.assertHeld(["not", "an object"], "not a JSON object")

    def test_every_reason_is_reported(self):
        out = judge(edited(KEYS, date="2026-01-01", total=1.0, currency="AUD"))
        self.assertGreaterEqual(len(out.reasons), 3)


# The 2024 Anthropic receipt: the issuer is a bare name above the "Bill to" column, and
# the only currency mark is a "$".
OLD_PAGE = """\
Anthropic                                  Bill to
                                           Person A
Receipt
Invoice number   TESTINV-0001
Date paid        March 3, 2024

Description                 Qty   Unit price     Amount
Test plan                   1     $22.00         $22.00

Total   $22.00
"""

OLD = {
    "merchant": "anthropic",
    "invoice_ref": "TESTINV-0001",
    "date": "2024-03-03",
    "total": 22.0,
    "evidence": {
        "invoice_ref": "Invoice number   TESTINV-0001",
        "date": "Date paid        March 3, 2024",
        "total": "Total   $22.00",
    },
}

# A receipt number that the page's table wraps over two lines, with the invoice number whole.
WRAPPED_PAGE = SAAS_PAGE.replace("Receipt number   1111-2222-3333\n", "").replace(
    "Subtotal  ", "Payment history\nPayment method   Date   Receipt number\nCard   Oct 1, 2026   1234-5678-\n9012\n\nSubtotal  ")
WRAPPED = edited(SAAS, receipt_ref="1234-5678-9012")
WRAPPED["evidence"]["receipt_ref"] = "Card   Oct 1, 2026   1234-5678-"


class FileEveryMailJudgeTest(unittest.TestCase):
    def test_the_2024_issuer_line_and_a_bare_dollar_file_as_usd(self):
        out = judge(OLD, OLD_PAGE)
        self.assertEqual((out.reasons, out.dropped), ([], []))
        self.assertEqual((out.merchant, out.fields["currency"], out.amounts["total"][0]), ("anthropic", "USD", "22.00"))

    def test_the_bare_issuer_name_is_not_accepted_inside_prose_or_other_words(self):
        for page in (OLD_PAGE.replace("Anthropic   ", "Not Anthropic   "), OLD_PAGE.replace("Anthropic   ", "Anthropically   "),
                     OLD_PAGE.replace("Anthropic                                  Bill to", "Anthropic thanks you for paying"),
                     OLD_PAGE.replace("Anthropic   ", "Anthropic Pty")):
            out = judge(OLD, page)
            self.assertTrue(any("no allow-listed issuer" in r for r in out.reasons), page[:40])

    def test_a_wrapped_receipt_number_is_dropped_and_the_invoice_number_stands(self):
        out = judge(WRAPPED, WRAPPED_PAGE)
        self.assertEqual(out.reasons, [])
        self.assertNotIn("receipt_ref", out.fields)
        self.assertEqual(out.fields["invoice_ref"], "TEST-0001")
        self.assertTrue(any(r.startswith("receipt_ref") for r in out.dropped), out.dropped)
        # a dropped receipt number names neither the file nor the id
        self.assertEqual(gate.file_name(out), "2026-10-01_anthropic_invoice_TEST-0001")
        self.assertEqual(gate.purchase_id(out), "records:purchase/anthropic/TEST-0001")
        self.assertNotIn("1234-5678", gate.purchase_yaml(out, "x.pdf", "0" * 64, "<m>", "m"))

    def test_a_tax_without_evidence_is_dropped_and_the_arithmetic_is_skipped(self):
        p = with_evidence(SAAS, tax=...)
        out = judge(p, SAAS_PAGE)
        self.assertEqual(out.reasons, [])
        self.assertNotIn("tax", out.amounts)
        self.assertNotIn("tax_label", out.fields)
        self.assertTrue(any(r.startswith("tax: no evidence") for r in out.dropped), out.dropped)
        # subtotal 100 and no tax is not 110, but nothing is said or dropped for it
        self.assertEqual(out.amounts["subtotal"][0], "100.00")
        self.assertEqual(len(out.items), 1)
        self.assertFalse(any("add to" in r for r in out.dropped))

    def test_sums_that_do_not_agree_drop_the_parts_and_keep_the_total(self):
        page = SAAS_PAGE.replace("$110.00", "$115.00")
        p = edited(SAAS, total=115.0)
        p["evidence"].update(total="Amount paid                                      $115.00 USD",
                             currency="Amount paid                                      $115.00 USD")
        out = judge(p, page)
        self.assertEqual(out.reasons, [])
        self.assertEqual(sorted(out.amounts), ["total"])
        self.assertEqual((out.items, out.fields.get("tax_label")), ([], None))
        self.assertTrue(any("the total stands" in r for r in out.dropped), out.dropped)

    def test_one_bad_item_drops_all_the_items(self):
        p = copy.deepcopy(SAAS)
        p["items"][0]["evidence"] = dict.fromkeys(("name", "quantity", "unit_price", "line_total"), "Nothing like it")
        out = judge(p, SAAS_PAGE)
        self.assertEqual((out.reasons, out.items), ([], []))
        self.assertEqual(out.amounts["total"][0], "110.00")

    def test_a_failed_required_value_is_not_a_drop(self):
        out = judge(edited(SAAS, date="2026-10-02"), SAAS_PAGE)
        self.assertTrue(any(r.startswith("date") for r in out.reasons))
        out = judge(edited(OLD, invoice_ref="NOPE-1"), OLD_PAGE)
        self.assertTrue(any("required: an invoice_ref or receipt_ref" in r for r in out.reasons))
        self.assertTrue(any(r.startswith("invoice_ref") for r in out.reasons))

    def test_garbage_proposals_leave_reasons_not_exceptions(self):
        for junk in (None, "text", [], {}, {"evidence": 3}, {"merchant": "anthropic", "evidence": {}, "total": "lots"}):
            self.assertTrue(judge(junk, OLD_PAGE).reasons, junk)


TODAY = datetime.now(timezone.utc).date().isoformat()


def spool_with(spool: Path, page: str, key="0123456789abcdef", message_id="<m1@example.invalid>", received_at=None,
               subject="Test mail", name="1-invoice.pdf", body=b"%PDF-1.4 a synthetic invoice") -> Dict[str, str]:
    d = spool / key
    (d / "attachments").mkdir(parents=True, exist_ok=True)
    meta = {"message_id": message_id, "from": "x@example.invalid", "subject": subject}
    if received_at:
        meta["received_at"] = received_at
    (d / "message.json").write_text(json.dumps(meta))
    pdf = d / "attachments" / name
    pdf.write_bytes(body)
    txt = d / "attachments" / (name + ".txt")
    txt.write_text(page, encoding="utf-8")
    return {"payload_dir": str(d), "pdf": str(pdf), "input_file": str(txt)}


def snapshot(root: Path) -> Dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


class HandleTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.spool, self.library = self.root / "spool", self.root / "library"
        self.spool.mkdir()
        (self.library / "documents").mkdir(parents=True)
        (self.library / "records").mkdir()

    def run_gate(self, paths, data, **extra):
        config = {"library": str(self.library), "mail_spool": str(self.spool), **extra}
        payload = {**paths, "data": data, "model": "test-model", "pattern": "extract_purchase"}
        return run_plugin(PLUGIN, {"command": "handle", "config": config, "event": {"type": "fabric.completed", "payload": payload}})

    def test_a_pass_files_the_pdf_its_sidecar_and_the_records(self):
        paths = spool_with(self.spool, KEYS_PAGE)
        before = snapshot(self.spool)
        resp = self.run_gate(paths, KEYS)
        self.assertEqual(resp["status"], "ok", resp)
        self.assertTrue(resp["result"].startswith("filed"), resp)
        base = "2026-10-24_yubico_invoice_INV-TEST-0001"
        docs = sorted(p.name for p in (self.library / "documents").iterdir())
        self.assertEqual(docs, [f"{base}.pdf", f"{base}.pdf.meta.yaml"])
        self.assertEqual((self.library / "documents" / f"{base}.pdf").read_bytes(), b"%PDF-1.4 a synthetic invoice")
        self.assertEqual([p.name for p in (self.library / "records").iterdir()], [f"{base}.yaml"])
        # the payload folder gained the PDF's result file and nothing else changed
        after = snapshot(self.spool)
        self.assertEqual(set(after) - set(before), {"0123456789abcdef/attachments/1-invoice.pdf.result.json"})
        self.assertEqual({k: v for k, v in after.items() if k in before}, before)
        result = json.loads(after["0123456789abcdef/attachments/1-invoice.pdf.result.json"])
        self.assertEqual(result["status"], "filed")
        self.assertEqual(len(result["files"]), 3)
        self.assertEqual((result["dropped"], result["missing"], result["gate"]), ([], [], gate.GATE_VERSION))

    def test_filing_subdir_files_under_documents_and_records_of_that_name(self):
        (self.library / "documents" / "mail").mkdir()
        (self.library / "records" / "mail").mkdir()
        resp = self.run_gate(spool_with(self.spool, KEYS_PAGE), KEYS, filing_subdir="mail")
        self.assertEqual(resp["status"], "ok", resp)
        base = "2026-10-24_yubico_invoice_INV-TEST-0001"
        self.assertEqual(sorted(p.name for p in (self.library / "documents" / "mail").iterdir()),
                         [f"{base}.pdf", f"{base}.pdf.meta.yaml"])
        self.assertEqual([p.name for p in (self.library / "records" / "mail").iterdir()], [f"{base}.yaml"])
        self.assertEqual(sorted(p.name for p in (self.library / "records").iterdir()), ["mail"])

    def test_a_purchase_already_in_records_is_not_filed_again_under_the_subdir(self):
        self.run_gate(spool_with(self.spool, KEYS_PAGE), KEYS)  # files into records/ itself
        (self.library / "documents" / "mail").mkdir()
        (self.library / "records" / "mail").mkdir()
        resp = self.run_gate(spool_with(self.spool, KEYS_PAGE, key="fedcba9876543210"), KEYS, filing_subdir="mail")
        self.assertEqual(resp["status"], "ok", resp)
        self.assertEqual(list((self.library / "records" / "mail").iterdir()), [])

    def test_a_filing_subdir_that_is_a_path_is_refused(self):
        for i, bad in enumerate(("../x", "a/b", ".hidden", "..")):
            with self.subTest(bad):
                resp = self.run_gate(spool_with(self.spool, KEYS_PAGE, key=f"{i:016x}"), KEYS, filing_subdir=bad)
                self.assertEqual(resp["status"], "error", resp)
                self.assertEqual(snapshot(self.library), {})

    def test_the_records_importer_reads_what_was_filed(self):
        self.run_gate(spool_with(self.spool, KEYS_PAGE), KEYS)
        records = load(RECORDS, "anam_records_run_for_gate")
        path = self.library / "records" / "2026-10-24_yubico_invoice_INV-TEST-0001.yaml"
        recs = records.records_file(path)
        self.assertEqual(len(recs), 1)
        env = records.envelope(recs[0], "person-a", "test")
        self.assertEqual(env["type"], "money.purchase")
        p = env["payload"]
        self.assertEqual(p["id"], "records:purchase/yubico/ORD-TEST-0002")
        self.assertEqual((p["date"], p["merchant"], p["currency"], p["total"]), ("2026-10-24", "yubico", "USD", 85.8))
        self.assertEqual(p["invoice_ref"], "INV-TEST-0001")
        self.assertEqual(p["items"], [{"name": "YubiKey - Test Offer", "quantity": 2, "unit_price": 34, "line_total": 68}])
        self.assertIn("<m1@example.invalid>", p["basis"])
        self.assertIn("test-model", p["basis"])
        self.assertIn("purchase_gate " + gate.GATE_VERSION, p["basis"])
        records.check_file(path)
        # the documents importer takes the sidecar
        documents = load(REPO / "documents" / "run.py", "anam_documents_run_for_gate")
        side = documents.sidecar(self.library / "documents" / "2026-10-24_yubico_invoice_INV-TEST-0001.pdf")
        self.assertEqual(side["date"], "2026-10-24")
        self.validate_against_definition(p)

    def validate_against_definition(self, payload):
        """The payload passes the money.purchase Definition, where the anam checkout is
        at hand (ANAM_SRC, or ../anam)."""
        src = Path(os.environ.get("ANAM_SRC") or REPO.parent / "anam")
        manifest = src / "internal" / "def" / "manifests" / "money.purchase.json"
        if not manifest.is_file():
            self.skipTest("no anam checkout for the money.purchase Definition")
        from jsonschema import Draft202012Validator
        schema = json.loads(manifest.read_text())["schema"]
        errors = [e.message for e in Draft202012Validator(schema).iter_errors(payload)]
        self.assertEqual(errors, [])

    def test_a_receipt_with_both_numbers_passes_the_definition_too(self):
        resp = self.run_gate(spool_with(self.spool, SAAS_PAGE), SAAS)
        self.assertTrue(resp["result"].startswith("filed"), resp)
        records = load(RECORDS, "anam_records_run_for_gate2")
        path = self.library / "records" / "2026-10-01_anthropic_receipt_1111-2222-3333.yaml"
        p = records.envelope(records.records_file(path)[0], "person-a", "t")["payload"]
        self.assertEqual(p["id"], "records:purchase/anthropic/TEST-0001")
        self.assertIn("1111-2222-3333", p["source_note"])
        self.validate_against_definition(p)

    def test_a_failed_required_value_files_the_pdf_as_a_document_only(self):
        paths = spool_with(self.spool, KEYS_PAGE)
        before = snapshot(self.spool)
        wrong = edited(KEYS, currency="AUD", total=1.0)
        resp = self.run_gate(paths, wrong)
        self.assertEqual(resp["status"], "ok")
        self.assertTrue(resp["result"].startswith("document_only"), resp)
        # no purchase record, and the PDF is named from the mail
        self.assertEqual(snapshot(self.library / "records"), {})
        name = f"{TODAY}_mail_0123456789abcdef_1-invoice"
        self.assertEqual(sorted(snapshot(self.library)),
                         [f"documents/{name}.pdf", f"documents/{name}.pdf.meta.yaml"])
        after = snapshot(self.spool)
        self.assertEqual(set(after) - set(before), {"0123456789abcdef/attachments/1-invoice.pdf.result.json"})
        self.assertEqual({k: v for k, v in after.items() if k in before}, before)
        result = json.loads(after["0123456789abcdef/attachments/1-invoice.pdf.result.json"])
        self.assertEqual(result["status"], "document_only")
        self.assertGreaterEqual(len(result["missing"]), 2)
        self.assertEqual(result["message_id"], "<m1@example.invalid>")
        self.assertNotIn("hold.json", " ".join(after))

    def test_a_document_only_pdf_is_dated_and_titled_from_the_mail(self):
        paths = spool_with(self.spool, KEYS_PAGE, received_at="2026-09-03T01:02:03.000Z", subject="  Fwd:  Your   receipt  ")
        resp = self.run_gate(paths, {})
        self.assertTrue(resp["result"].startswith("document_only"), resp)
        pdf = self.library / "documents" / "2026-09-03_mail_0123456789abcdef_1-invoice.pdf"
        self.assertTrue(pdf.is_file())
        side = load(REPO / "documents" / "run.py", "anam_documents_run_for_gate_doc").sidecar(pdf)
        self.assertEqual(side["date"], "2026-09-03")
        self.assertEqual(side["title"], "Fwd: Your receipt")
        self.assertIn("could not check a purchase", side["note"])
        self.assertIn("proposal", side["note"])

    def test_it_never_overwrites(self):
        paths = spool_with(self.spool, KEYS_PAGE)
        self.run_gate(paths, KEYS)
        first = snapshot(self.library)
        # the same mail again is a no-op
        again = self.run_gate(paths, KEYS)
        self.assertTrue(again["result"].startswith("already_filed"), again)
        self.assertEqual(snapshot(self.library), first)
        # a record a person edited stays as it is; the purchase is still filed
        rec = self.library / "records" / "2026-10-24_yubico_invoice_INV-TEST-0001.yaml"
        rec.write_text(rec.read_text() + "# edited by a person\n")
        edited_state = snapshot(self.library)
        again = self.run_gate(paths, KEYS)
        self.assertTrue(again["result"].startswith("already_filed"), again)
        self.assertEqual(snapshot(self.library), edited_state)
        # a different PDF under the same name is the same purchase, already filed
        rec.write_bytes(first[str(rec.relative_to(self.library))])
        pdf = self.spool / "0123456789abcdef" / "attachments" / "1-invoice.pdf"
        pdf.write_bytes(b"%PDF-1.4 another")
        again = self.run_gate(paths, KEYS)
        self.assertTrue(again["result"].startswith("already_filed"), again)
        self.assertEqual(snapshot(self.library), first)

    def test_the_same_invoice_in_two_mails_with_other_bytes_is_already_filed(self):
        self.run_gate(spool_with(self.spool, KEYS_PAGE), KEYS)
        first = snapshot(self.library)
        second = spool_with(self.spool, KEYS_PAGE, key="fedcba9876543210", body=b"%PDF-1.4 the same invoice, printed again")
        resp = self.run_gate(second, KEYS)
        self.assertTrue(resp["result"].startswith("already_filed"), resp)
        self.assertEqual(snapshot(self.library), first)
        result = json.loads((self.spool / "fedcba9876543210" / "attachments" / "1-invoice.pdf.result.json").read_text())
        self.assertEqual(result["status"], "already_filed")

    def test_a_document_only_name_taken_by_other_bytes_gets_a_suffix(self):
        a = spool_with(self.spool, "", received_at="2026-09-03T00:00:00Z")
        self.run_gate(a, {})
        self.run_gate(a, {})  # the same bytes again: nothing new
        Path(a["pdf"]).write_bytes(b"%PDF-1.4 other")
        resp = self.run_gate(a, {})
        self.assertTrue(resp["result"].startswith("document_only"), resp)
        pdfs = sorted(p.name for p in (self.library / "documents").glob("*.pdf"))
        self.assertEqual(len(pdfs), 2)
        sha = __import__("hashlib").sha256(b"%PDF-1.4 other").hexdigest()[:8]
        self.assertIn(f"2026-09-03_mail_0123456789abcdef_1-invoice-{sha}.pdf", pdfs)

    def test_a_second_document_for_one_purchase_adds_the_document_only(self):
        self.run_gate(spool_with(self.spool, KEYS_PAGE), KEYS)
        records_before = snapshot(self.library / "records")
        # the same order's receipt: another document, the same purchase
        page = KEYS_PAGE.replace("Invoice: INV-TEST-0001", "Receipt: RCT-TEST-0007\nInvoice: INV-TEST-0001")
        again = edited(KEYS, receipt_ref="RCT-TEST-0007",
                       evidence=dict(KEYS["evidence"], receipt_ref="Receipt: RCT-TEST-0007"))
        resp = self.run_gate(spool_with(self.spool, page, key="fedcba9876543210", body=b"%PDF-1.4 a synthetic receipt"), again)
        self.assertTrue(resp["result"].startswith("filed"), resp)
        self.assertEqual(snapshot(self.library / "records"), records_before)
        self.assertIn("2026-10-24_yubico_receipt_RCT-TEST-0007.pdf", [p.name for p in (self.library / "documents").iterdir()])

    def test_a_second_document_files_when_other_records_sort_after_its_purchase(self):
        # live 2026-10-27: an IndexError once the matching record was not the last file
        self.run_gate(spool_with(self.spool, KEYS_PAGE), KEYS)
        (self.library / "records" / "zz-another-purchase.yaml").write_text("records: []\n", encoding="utf-8")
        page = KEYS_PAGE.replace("Invoice: INV-TEST-0001", "Receipt: RCT-TEST-0007\nInvoice: INV-TEST-0001")
        again = edited(KEYS, receipt_ref="RCT-TEST-0007",
                       evidence=dict(KEYS["evidence"], receipt_ref="Receipt: RCT-TEST-0007"))
        resp = self.run_gate(spool_with(self.spool, page, key="fedcba9876543210", body=b"%PDF-1.4 a synthetic receipt"), again)
        self.assertTrue(resp["result"].startswith("filed"), resp)

    def test_a_second_document_with_other_figures_is_filed_as_a_document_only(self):
        self.run_gate(spool_with(self.spool, KEYS_PAGE), KEYS)
        before = snapshot(self.library)
        page = KEYS_PAGE.replace("INV-TEST-0001", "INV-TEST-0007").replace("$85.80", "$95.80").replace("$10.00", "$20.00")
        again = edited(KEYS, invoice_ref="INV-TEST-0007", shipping=20.0, total=95.8,
                       evidence=dict(KEYS["evidence"], invoice_ref="Invoice: INV-TEST-0007",
                                     shipping="Shipping and Handling:                  $20.00",
                                     total="Grand Total:                $95.80", currency="Grand Total:                $95.80"))
        resp = self.run_gate(spool_with(self.spool, page, key="fedcba9876543210", body=b"%PDF-1.4 a synthetic receipt"), again)
        self.assertTrue(resp["result"].startswith("document_only"), resp)
        self.assertIn("with other figures", resp["result"])
        # the records are untouched; the PDF is filed as a document under the mail's name
        self.assertEqual(snapshot(self.library / "records"), {k[len("records/"):]: v for k, v in before.items() if k.startswith("records/")})
        self.assertEqual(len(list((self.library / "documents").glob("*_mail_fedcba9876543210_*.pdf"))), 1)

    def test_a_unit_price_with_more_places_than_the_line_total_passes(self):
        # the Anthropic shape: $10.064091 for a line of $10.06
        page = SAAS_PAGE.replace("$100.00        $100.00", "$10.064091     $10.06").replace("$100.00", "$10.06").replace(
            "$10.00", "$1.01").replace("$110.00", "$11.07")
        row = "Test plan                   1     $10.064091     $10.06"
        p = edited(SAAS, items=[{"name": "Test plan", "quantity": 1, "unit_price": 10.064091, "line_total": 10.06,
                                 "evidence": dict.fromkeys(("name", "quantity", "unit_price", "line_total"), row)}],
                   subtotal=10.06, tax=1.01, total=11.07)
        p["evidence"].update(subtotal="Subtotal                                         $10.06",
                             tax="Tax (GST 10%)                                     $1.01",
                             tax_label="Tax (GST 10%)                                     $1.01",
                             total="Amount paid                                      $11.07 USD",
                             currency="Amount paid                                      $11.07 USD")
        self.assertEqual(judge(p, page).reasons, [])

    def test_paths_outside_the_spool_are_refused(self):
        paths = spool_with(self.spool, KEYS_PAGE)
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "x.pdf").write_bytes(b"%PDF-1.4")
        (outside / "x.pdf.txt").write_text(KEYS_PAGE)
        for bad in ({"pdf": str(outside / "x.pdf")}, {"input_file": str(outside / "x.pdf.txt")},
                    {"payload_dir": str(outside)}, {"input_file": str(self.spool / ".." / "outside" / "x.pdf.txt")}):
            resp = self.run_gate({**paths, **bad}, KEYS)
            self.assertEqual(resp["status"], "error", bad)
            self.assertFalse(resp["retry"])
            self.assertIn("outside mail_spool", resp["error"])
        self.assertEqual(snapshot(self.library), {})
        self.assertEqual(sorted(p.name for p in outside.iterdir()), ["x.pdf", "x.pdf.txt"])

    def test_a_symlink_out_of_the_spool_is_refused(self):
        paths = spool_with(self.spool, KEYS_PAGE)
        secret = self.root / "secret.txt"
        secret.write_text(KEYS_PAGE)
        txt = Path(paths["input_file"])
        txt.unlink()
        txt.symlink_to(secret)
        resp = self.run_gate(paths, KEYS)
        self.assertEqual(resp["status"], "error")
        self.assertIn("outside mail_spool", resp["error"])

    def test_the_event_may_carry_only_the_input_file(self):
        # fabric forwards input_file; the payload folder and PDF follow from it
        paths = spool_with(self.spool, KEYS_PAGE)
        resp = self.run_gate({"input_file": paths["input_file"]}, KEYS)
        self.assertTrue(resp["result"].startswith("filed"), resp)

    def test_a_pdf_or_payload_dir_that_disagrees_with_input_file_is_refused(self):
        paths = spool_with(self.spool, KEYS_PAGE)
        other = spool_with(self.spool, KEYS_PAGE, key="fedcba9876543210")
        for bad in ({"pdf": other["pdf"]}, {"payload_dir": other["payload_dir"]}):
            resp = self.run_gate({**paths, **bad}, KEYS)
            self.assertEqual(resp["status"], "error", bad)
            self.assertIn("does not agree", resp["error"])
        self.assertEqual(snapshot(self.library), {})

    def test_a_missing_message_id_is_noted_and_the_mail_is_still_filed(self):
        paths = spool_with(self.spool, KEYS_PAGE)
        (self.spool / "0123456789abcdef" / "message.json").unlink()
        resp = self.run_gate(paths, KEYS)
        self.assertTrue(resp["result"].startswith("filed"), resp)
        result = json.loads((self.spool / "0123456789abcdef" / "attachments" / "1-invoice.pdf.result.json").read_text())
        self.assertTrue(any("message.json" in d for d in result["dropped"]), result)

    def test_the_2024_receipt_files_as_usd_through_handle(self):
        resp = self.run_gate(spool_with(self.spool, OLD_PAGE), OLD)
        self.assertTrue(resp["result"].startswith("filed"), resp)
        rec = self.library / "records" / "2024-03-03_anthropic_invoice_TESTINV-0001.yaml"
        self.assertIn("currency: USD", rec.read_text())

    def test_a_wrapped_receipt_number_files_with_the_invoice_number_through_handle(self):
        resp = self.run_gate(spool_with(self.spool, WRAPPED_PAGE), WRAPPED)
        self.assertTrue(resp["result"].startswith("filed"), resp)
        self.assertEqual([p.name for p in (self.library / "records").iterdir()], ["2026-10-01_anthropic_invoice_TEST-0001.yaml"])
        result = json.loads((self.spool / "0123456789abcdef" / "attachments" / "1-invoice.pdf.result.json").read_text())
        self.assertTrue(any(d.startswith("receipt_ref") for d in result["dropped"]), result)

    def test_a_filed_purchase_without_its_tax_still_passes_the_definition(self):
        resp = self.run_gate(spool_with(self.spool, SAAS_PAGE), with_evidence(SAAS, tax=...))
        self.assertTrue(resp["result"].startswith("filed"), resp)
        records = load(RECORDS, "anam_records_run_for_gate3")
        path = self.library / "records" / "2026-10-01_anthropic_receipt_1111-2222-3333.yaml"
        p = records.envelope(records.records_file(path)[0], "person-a", "t")["payload"]
        self.assertNotIn("tax", p)
        self.validate_against_definition(p)

    def test_an_empty_proposal_is_a_document_only_the_documents_importer_accepts(self):
        for i, junk in enumerate((None, "", {}, {"evidence": {}}, "not json at all")):
            with self.subTest(junk):
                key = f"{i:016x}"
                resp = self.run_gate(spool_with(self.spool, "", key=key, received_at="2026-08-09T10:00:00Z", body=b"%PDF-1.4 junk " + str(i).encode()), junk)
                self.assertTrue(resp["result"].startswith("document_only"), resp)
                pdf = self.library / "documents" / f"2026-08-09_mail_{key}_1-invoice.pdf"
                side = load(REPO / "documents" / "run.py", f"anam_documents_run_for_gate_{i}").sidecar(pdf)
                self.assertEqual(side["date"], "2026-08-09")
        self.assertEqual(snapshot(self.library / "records"), {})

    def test_a_pdf_already_filed_by_an_earlier_gate_is_already_filed(self):
        # live 2026-10-27: 0.1.0's sidecar note differs from 0.2.0's, and a replay filed a
        # second copy under a mail name. The same bytes in the Library are the same document.
        self.run_gate(spool_with(self.spool, KEYS_PAGE), KEYS)
        for side in (self.library / "documents").glob("*.meta.yaml"):
            side.write_text(side.read_text(encoding="utf-8").replace("purchase_gate", "an earlier purchase_gate"), encoding="utf-8")
        before = snapshot(self.library)
        resp = self.run_gate(spool_with(self.spool, KEYS_PAGE), KEYS)
        self.assertTrue(resp["result"].startswith("already_filed"), resp)
        self.assertEqual(snapshot(self.library), before)
        # and when this run's checks would only file it as a document
        resp = self.run_gate(spool_with(self.spool, ""), None)
        self.assertTrue(resp["result"].startswith("already_filed"), resp)
        self.assertEqual(snapshot(self.library), before)

    def test_two_pdfs_in_one_message_each_get_a_result_file(self):
        a = spool_with(self.spool, KEYS_PAGE, name="1-first.pdf", body=b"%PDF-1.4 first")
        b = spool_with(self.spool, "", name="2-second.pdf", body=b"%PDF-1.4 second")
        self.run_gate(a, KEYS)
        self.run_gate(b, {})
        att = self.spool / "0123456789abcdef" / "attachments"
        first = json.loads((att / "1-first.pdf.result.json").read_text())
        second = json.loads((att / "2-second.pdf.result.json").read_text())
        self.assertEqual((first["status"], second["status"]), ("filed", "document_only"))
        self.assertFalse((self.spool / "0123456789abcdef" / "result.json").exists())

    def test_a_non_pdf_attachment_is_filed_as_a_document_only_with_the_reason(self):
        resp = self.run_gate(spool_with(self.spool, KEYS_PAGE, body=b"not a pdf"), KEYS)
        self.assertTrue(resp["result"].startswith("document_only"), resp)
        self.assertIn("%PDF", resp["result"])

    def test_health(self):
        config = {"library": str(self.library), "mail_spool": str(self.spool)}
        self.assertEqual(run_plugin(PLUGIN, {"command": "health", "config": config})["status"], "ok")
        bad = run_plugin(PLUGIN, {"command": "health", "config": {**config, "merchants": {"x": {"issuer": "("}}}})
        self.assertEqual(bad["status"], "error")


if __name__ == "__main__":
    unittest.main()
