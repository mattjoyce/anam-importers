"""The shared base every Anam importer builds on (docs/IMPORTERS.md §8 in the anam repo).

An importer reads one source and shapes its data to Definitions it carries in its
own folder; this package does the rest the same way for every importer: load and
validate against those Definitions, batch, publish the Definitions, submit.
"""

from pathlib import Path

from .client import AnamError, Client, Refused
from .definitions import Definition, Definitions, ensure_published, load, parse
from .envelopes import MAX_BATCH, Invalid, batches, check, envelope, snapshot_parts

# __version__ is the repo's version (VERSION): the base, anam_submit and every importer
# release together, and each plugin manifest carries the same number.
__version__ = (Path(__file__).resolve().parent.parent / "VERSION").read_text().strip()

__all__ = [
    "MAX_BATCH",
    "__version__",
    "AnamError",
    "Client",
    "Definition",
    "Definitions",
    "Invalid",
    "Refused",
    "batches",
    "check",
    "ensure_published",
    "envelope",
    "load",
    "snapshot_parts",
    "parse",
]
