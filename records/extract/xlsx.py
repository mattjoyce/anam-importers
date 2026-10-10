"""The first sheet of a simple .xlsx workbook, read with the standard library.

Fitbit's Google Takeout workbooks are one sheet of plain cells, so this reads the
shared strings and the sheet's XML directly rather than needing openpyxl.
"""

from __future__ import annotations

import re
import zipfile
from typing import Dict, Iterator


def rows(z: zipfile.ZipFile) -> Iterator[Dict[str, str]]:
    """Each row of sheet1 as {column letter: cell text}, in sheet order. A cell with no
    value is left out."""
    try:
        ss = z.read("xl/sharedStrings.xml").decode()
    except KeyError:
        ss = ""
    strings = [re.sub(r"<[^>]+>", "", m) for m in re.findall(r"<si>(.*?)</si>", ss, re.S)]
    sheet = z.read("xl/worksheets/sheet1.xml").decode()
    for row in re.findall(r"<row[^>]*>(.*?)</row>", sheet, re.S):
        out = {}
        for col, attrs, v in re.findall(r'<c r="([A-Z]+)\d+"([^>]*)>(?:<v>([^<]*)</v>)?', row):
            out[col] = strings[int(v)] if 't="s"' in attrs else v
        yield out
