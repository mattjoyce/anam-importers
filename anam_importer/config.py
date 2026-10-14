"""A plugin's config: a key overrides an opinionated default (anam card 151).

Each plugin reads its keys once, at the start of a command, into values it passes
down; nothing deeper reads config. A value of the wrong kind or out of its range
fails the command there, before it reads a source or calls Anam, with a message
that names the key.
"""

from __future__ import annotations

import urllib.parse
from typing import Any, Dict, Optional, Union

from .ductile import Failure

Number = Union[int, float]


def bad(key: str, why: str) -> Failure:
    """A config value that cannot be used. Retrying will not help until someone
    changes the config."""
    return Failure(f"config {key}: {why}", retry=False)


def integer(config: Dict[str, Any], key: str, default: int, low: int, high: int) -> int:
    """config[key] as a whole number in low..high, or default when it is not set."""
    v = config.get(key, default)
    try:
        n = int(v) if not isinstance(v, float) or v.is_integer() else None
    except (TypeError, ValueError):
        n = None
    if isinstance(v, bool) or n is None:
        raise bad(key, f"{v!r} is not a whole number")
    if not low <= n <= high:
        raise bad(key, f"{n} is outside {low}..{high}")
    return n


def number(config: Dict[str, Any], key: str, default: Number, low: Number, high: Number,
           low_open: bool = False) -> float:
    """config[key] as a number in low..high, or default when it is not set. With
    low_open, low itself is refused: a timeout or a window of 0 is no timeout."""
    v = config.get(key, default)
    try:
        n: Optional[float] = None if isinstance(v, bool) else float(v)
    except (TypeError, ValueError):
        n = None
    if n is None or n != n:  # NaN is not a number anyone means
        raise bad(key, f"{v!r} is not a number")
    if n < low or n > high or (low_open and n == low):
        raise bad(key, f"{n:g} is outside {'more than ' if low_open else ''}{low}..{high}")
    return n


def text(config: Dict[str, Any], key: str, default: str) -> str:
    """config[key] as non-empty text, or default when it is not set."""
    v = config.get(key, default)
    if not isinstance(v, str) or not v:
        raise bad(key, f"{v!r} is not text")
    return v


def url(config: Dict[str, Any], key: str, default: str) -> str:
    """config[key] as an http or https origin with a host and no query, fragment
    or credentials: a token sent there goes nowhere else."""
    v = text(config, key, default)
    parts = urllib.parse.urlsplit(v)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise bad(key, f"{v!r}: want http:// or https:// and a host")
    if parts.query or parts.fragment or parts.username:
        raise bad(key, f"{v!r}: want no query, fragment or credentials")
    return v
