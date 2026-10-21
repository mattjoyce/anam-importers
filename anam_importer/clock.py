"""Reading a source's clock (anam card 197).

Every fact keeps its fact time as Anam derives it, one UTC instant, and beside it
`source_time`: the value as the source supplied it, the zone that value is read
in, and the basis for that zone. These helpers build that object and
read a wall clock in a zone without guessing across a daylight-saving change.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# BASES are the three answers to "who decided the zone". source: the source supplied
# it with the value, or the value is UTC by the source's own definition.
# configuration: a setting a person made names the zone for this source.
# assumption: neither did, and the importer chose it and logged that it did.
# Not configurable: they are the Definition's vocabulary.
BASES = ("source", "configuration", "assumption")


# OFFSET is a fixed offset as source_time writes one, +HH:MM or -HH:MM, within the
# +14:00 no zone exceeds. Not configurable: it is the Definition's shape.
OFFSET = re.compile(r"^[+-](0\d|1[0-3]):[0-5]\d$|^[+-]14:00$")


class ClockError(ValueError):
    """A wall clock that names no single instant in its zone."""


def check_zone(zone: str) -> None:
    """zone is an IANA zone this host knows or a fixed offset, and not "Local". The
    gate refuses any other, and refuses the whole batch with it, so an importer
    checks before it sends."""
    if OFFSET.match(zone):
        return
    if not zone or zone == "Local" or zone[0] in "+-":
        raise ValueError(f"zone {zone!r} is no zone")
    try:
        ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"zone {zone!r} is not an IANA zone") from exc


def source_time(value: str, zone: str, basis: str) -> Dict[str, Any]:
    """The source_time object: value as supplied, the zone that reads it, and why
    that zone."""
    if basis not in BASES:
        raise ValueError(f"basis {basis!r} is not one of {', '.join(BASES)}")
    if not value:
        raise ValueError("source_time needs a value")
    check_zone(zone)
    return {"value": value, "zone": zone, "basis": basis}


# WRITTEN_OFFSET is the offset at the end of an RFC 3339 instant as a source writes
# one. Not configurable: it is RFC 3339's.
WRITTEN_OFFSET = re.compile(r"([+-]\d\d:\d\d)$")


def zone_written(text: str) -> str:
    """The zone an RFC 3339 instant is written in, as source_time names it: UTC for
    one written with Z, else its own offset, +HH:MM. One with neither is a
    ValueError: it is a wall clock, and its zone is not in it."""
    if text.endswith(("Z", "z")):
        return "UTC"
    m = WRITTEN_OFFSET.search(text)
    if not m:
        raise ValueError(f"{text!r} carries no offset")
    check_zone(m.group(1))
    return m.group(1)


def offset_text(offset: timedelta) -> str:
    """A UTC offset as RFC 3339 writes one: +11:00, -03:30, +00:00."""
    minutes = int(offset.total_seconds()) // 60
    sign = "-" if minutes < 0 else "+"
    h, m = divmod(abs(minutes), 60)
    return f"{sign}{h:02d}:{m:02d}"


def utc_text(t: datetime) -> str:
    """An instant as RFC 3339 in UTC: 2026-10-20T09:00:00Z."""
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def at_offset(t: datetime, offset: timedelta) -> str:
    """An instant as RFC 3339 on the wall clock at offset: 2026-10-20T20:00:00+11:00."""
    return t.astimezone(timezone(offset)).strftime("%Y-%m-%dT%H:%M:%S") + offset_text(offset)


def local_instant(wall: datetime, zone: str) -> datetime:
    """The one instant a naive wall clock names in an IANA zone. A wall clock in a
    daylight-saving gap names none, and one in an overlap names two; both are a
    ClockError, never a silent pick of one side."""
    if wall.tzinfo is not None:
        raise ValueError(f"{wall.isoformat()} already carries an offset")
    tz = ZoneInfo(zone)
    early, late = wall.replace(tzinfo=tz, fold=0), wall.replace(tzinfo=tz, fold=1)
    if early.utcoffset() != late.utcoffset():
        # zoneinfo gives the two sides of a gap different offsets too; a gap's wall
        # clock does not survive a trip to UTC and back.
        if early.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None) != wall:
            raise ClockError(f"{wall.isoformat(sep=' ')} does not exist in {zone}: the clocks skip it (daylight saving)")
        raise ClockError(f"{wall.isoformat(sep=' ')} happens twice in {zone}: the clocks repeat it (daylight saving)")
    return early
