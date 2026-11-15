"""Spreadsheet export for the console (see export_xlsx.py for why not CSV)."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..export_xlsx import build_xlsx
from ..models.errors import ErrorCode, SocialLensError

router = APIRouter(tags=["export"])

MAX_ROWS = 100_000
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class XlsxBody(BaseModel):
    rows: list[dict[str, Any]] = Field(description="one dict per row; keys become the header row")
    name: str = "sociallens"  # file name, without extension
    sheet: str | None = None


@router.post("/export/xlsx", response_class=Response, responses={200: {"content": {XLSX: {}}}})
async def export_xlsx(body: XlsxBody):
    """Rows -> an .xlsx file. Strings (ids included) stay text, numbers stay numbers, so long
    numeric ids keep every digit in Excel, unlike a CSV."""
    if not body.rows:
        raise SocialLensError(ErrorCode.BAD_REQUEST, "rows is empty")
    if len(body.rows) > MAX_ROWS:
        raise SocialLensError(ErrorCode.BAD_REQUEST, f"at most {MAX_ROWS} rows")
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", body.name).strip() or "sociallens"
    data = build_xlsx(body.rows, body.sheet or name)
    return Response(data, media_type=XLSX, headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}.xlsx"})
