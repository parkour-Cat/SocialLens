"""Minimal .xlsx writer (stdlib only) for the console's "Export Excel".

Why not CSV for Excel users: Excel parses long digit strings in a CSV as numbers, so a 19-digit
post or user id (X, Douyin, Toutiao, Bilibili mids) turns into 2.09E+18 and loses its last
digits for good. Here every string is written as an inline string cell, so ids stay exact, and
real numbers (likes, views ...) stay numeric for sorting and sums. Inline strings are never
evaluated as formulas, so "=..." content is harmless too.
"""

from __future__ import annotations

import io
import re
import zipfile
from typing import Any
from xml.sax.saxutils import escape

MAX_CELL = 32767  # Excel's limit per cell
_BAD_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>"""

_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

_WORKBOOK_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

# style 0: default, style 1: bold header
_STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>
<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>
<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>"""


def _col(i: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _text(v: Any) -> str:
    s = _BAD_XML.sub("", str(v))
    return escape(s[:MAX_CELL])


def _cell(ref: str, v: Any, style: int = 0) -> str:
    st = f' s="{style}"' if style else ""
    if v is None or v == "":
        return ""
    if isinstance(v, bool):
        return f'<c r="{ref}" t="inlineStr"{st}><is><t>{"true" if v else "false"}</t></is></c>'
    if isinstance(v, (int, float)) and abs(v) < 1e15:  # beyond that Excel loses digits: keep as text
        return f'<c r="{ref}"{st}><v>{v}</v></c>'
    return f'<c r="{ref}" t="inlineStr"{st}><is><t xml:space="preserve">{_text(v)}</t></is></c>'


def build_xlsx(rows: list[dict[str, Any]], sheet: str = "Sheet1") -> bytes:
    """One sheet: a bold, frozen, filterable header row (keys of the rows, first-seen order)."""
    cols: list[str] = []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    lines = [f'<row r="1">{"".join(_cell(f"{_col(i)}1", c, 1) for i, c in enumerate(cols))}</row>']
    for n, r in enumerate(rows, start=2):
        lines.append(f'<row r="{n}">{"".join(_cell(f"{_col(i)}{n}", r.get(c)) for i, c in enumerate(cols))}</row>')
    last = f"{_col(max(len(cols) - 1, 0))}{len(rows) + 1}"
    widths = "".join(f'<col min="{i + 1}" max="{i + 1}" width="{min(60, max(10, len(c) + 4))}" customWidth="1"/>' for i, c in enumerate(cols))
    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
        + (f"<cols>{widths}</cols>" if cols else "")
        + f'<sheetData>{"".join(lines)}</sheetData>'
        + (f'<autoFilter ref="A1:{last}"/>' if cols else "")
        + "</worksheet>"
    )
    name = _text(re.sub(r"[\[\]:*?/\\]", "_", sheet)[:31] or "Sheet1")
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="{name}" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("xl/workbook.xml", workbook)
        z.writestr("xl/_rels/workbook.xml.rels", _WORKBOOK_RELS)
        z.writestr("xl/styles.xml", _STYLES)
        z.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return buf.getvalue()
