"""POST /api/v1/export/xlsx and the stdlib xlsx writer."""

from __future__ import annotations

import io
import zipfile
import xml.etree.ElementTree as ET

from sociallens.export_xlsx import _col, build_xlsx

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def _cells(data: bytes) -> dict[str, tuple[str | None, str]]:
    """ref -> (cell type, text) from the sheet."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert z.testzip() is None
        root = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
        ET.fromstring(z.read("xl/workbook.xml"))  # well-formed
    out = {}
    for c in root.iter(f"{{{NS['m']}}}c"):
        t = c.get("t")
        text = c.findtext("m:is/m:t", namespaces=NS) if t == "inlineStr" else c.findtext("m:v", namespaces=NS)
        out[c.get("r")] = (t, text, c.get("s"))
    return out


def test_column_letters():
    assert [_col(i) for i in (0, 25, 26, 51, 701, 702)] == ["A", "Z", "AA", "AZ", "ZZ", "AAA"]


def test_ids_stay_text_numbers_stay_numbers():
    rows = [
        {"id": "2092792609576190459", "author_id": "5204110145805978", "title": '=HYPERLINK("x") <b>&', "likes": 3300, "views": 27.5, "tags": None},
        {"id": "BV1rpWjevEip", "likes": 0, "extra": True, "huge": 12345678901234567890},
    ]
    c = _cells(build_xlsx(rows, "posts"))
    assert c["A1"] == ("inlineStr", "id", "1")  # bold header
    assert c["A2"] == ("inlineStr", "2092792609576190459", None)  # every digit kept
    assert c["B2"][:2] == ("inlineStr", "5204110145805978")
    assert c["C2"][:2] == ("inlineStr", '=HYPERLINK("x") <b>&')  # text, not a formula
    assert c["D2"][:2] == (None, "3300") and c["E2"][:2] == (None, "27.5")
    assert "F2" not in c  # None -> empty cell
    assert c["D3"][:2] == (None, "0")
    assert c["G3"][:2] == ("inlineStr", "true")  # header order: first-seen keys
    assert c["H3"][:2] == ("inlineStr", "12345678901234567890")  # too big for a double: text


def test_control_characters_are_dropped():
    c = _cells(build_xlsx([{"content": "a\x00b\x07c\nd\te"}]))
    assert c["A2"][1] == "abc\nd\te"


def test_endpoint_returns_a_download(client):
    r = client.post("/api/v1/export/xlsx", json={"name": "小红书 搜索/露营", "rows": [{"id": "123456789012345678901", "likes": 5}]})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    assert "filename*=UTF-8''" in r.headers["content-disposition"] and "%2F" not in r.headers["content-disposition"]
    assert _cells(r.content)["A2"][:2] == ("inlineStr", "123456789012345678901")


def test_endpoint_rejects_empty(client):
    r = client.post("/api/v1/export/xlsx", json={"rows": []})
    assert r.status_code == 400
