"""The shared base every Anam importer builds on (docs/IMPORTERS.md §8 in the anam repo).

An importer reads one source and shapes its data to Definitions it carries in its
own folder; this package does the rest the same way for every importer: load and
validate against those Definitions, batch, publish the Definitions, submit.
"""

from .client import AnamError, Client, Refused
from .definitions import Definition, ensure_published, load, parse
from .envelopes import MAX_BATCH, Invalid, batches, check, envelope

__all__ = [
    "MAX_BATCH",
    "AnamError",
    "Client",
    "Definition",
    "Invalid",
    "Refused",
    "batches",
    "check",
    "ensure_published",
    "envelope",
    "load",
    "parse",
]
