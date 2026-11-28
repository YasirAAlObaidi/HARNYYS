"""Excel (.xlsx) files in and out, through openpyxl. Knows rows and cells, nothing about what they mean.

openpyxl reads XML; with defusedxml installed (a dependency) it refuses entity tricks such as billion-laughs
files, so an uploaded sheet cannot exhaust the box.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any
from zipfile import BadZipFile

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from openpyxl.utils.exceptions import InvalidFileException

from yyai.core.errors import InvalidFile

MAX_COLUMN_WIDTH = 60


@dataclass
class Sheet:
    """One worksheet to write: a header row, then the rows."""

    title: str
    headers: Sequence[str]
    rows: Sequence[Sequence[Any]]
    column_widths: dict[str, int] = field(default_factory=dict)  # by header; otherwise sized to the content


def read_rows(data: bytes, sheet: str | None = None) -> list[tuple[int, list[Any]]]:
    """The rows of the named sheet (or the first one) as (Excel row number, cell values).

    Formulas give the value Excel last calculated. Rows with no value in any cell are left out, so the row
    numbers can have gaps: they are kept so that problems can be reported as "row 14", as the client sees it.
    """
    try:
        workbook = load_workbook(BytesIO(data), data_only=True)
    except (InvalidFileException, BadZipFile, KeyError, OSError, ValueError, TypeError) as exc:
        raise InvalidFile(f"This is not a readable Excel (.xlsx) file: {exc}") from exc
    try:
        by_name = {name.strip().lower(): name for name in workbook.sheetnames}
        chosen = by_name.get(sheet.strip().lower()) if sheet else None
        worksheet = workbook[chosen] if chosen else workbook.worksheets[0]
        rows: list[tuple[int, list[Any]]] = []
        for number, values in enumerate(worksheet.iter_rows(min_row=1, values_only=True), start=1):
            cells = list(values)
            if any(_has_value(cell) for cell in cells):
                rows.append((number, cells))
        return rows
    finally:
        workbook.close()


def write_workbook(sheets: Sequence[Sheet]) -> bytes:
    """An .xlsx file with one worksheet per Sheet: bold header row, frozen at the top, with filters on."""
    if not sheets:
        raise ValueError("write_workbook needs at least one sheet")
    workbook = Workbook()
    workbook.remove(workbook.active)
    for spec in sheets:
        worksheet = workbook.create_sheet(title=spec.title[:31])  # Excel's limit for sheet names
        worksheet.append(list(spec.headers))
        for cell in worksheet[1]:
            cell.font = Font(bold=True)
        for row in spec.rows:
            worksheet.append([_cell(value) for value in row])
        worksheet.freeze_panes = "A2"
        if spec.headers:
            worksheet.auto_filter.ref = worksheet.dimensions
        for index, header in enumerate(spec.headers, start=1):
            width = spec.column_widths.get(header) or _content_width(header, spec.rows, index - 1)
            worksheet.column_dimensions[get_column_letter(index)].width = width
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _has_value(cell: Any) -> bool:
    return cell is not None and not (isinstance(cell, str) and not cell.strip())


def _cell(value: Any) -> Any:
    """Values openpyxl can store. Lists and dicts become text; everything else is written as it is."""
    if isinstance(value, list | tuple | set):
        return ", ".join(str(item) for item in value)
    if isinstance(value, dict):
        return ", ".join(f"{key}: {item}" for key, item in value.items())
    return value


def _content_width(header: str, rows: Sequence[Sequence[Any]], column: int) -> int:
    longest = len(header)
    for row in rows[:500]:  # enough to size a column; no need to scan a huge export
        if column < len(row) and row[column] is not None:
            longest = max(longest, len(str(_cell(row[column]))))
    return min(longest + 2, MAX_COLUMN_WIDTH)
