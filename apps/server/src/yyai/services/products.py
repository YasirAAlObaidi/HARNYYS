"""The product sheet: the client's Excel file in, the product table out, and the table back out as Excel.

The rules live here: which column means what, what counts as a price or a stock level, and when an import is
too risky to apply. Nothing is written while any row has a problem: the client fixes the sheet and uploads it
again. That keeps the table the agent quotes from always in a state someone checked.
"""

from __future__ import annotations

import re
from collections import Counter
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from yyai.core.text import normalize_for_search
from yyai.core.types import ProductImportReport, ProductRecord, SheetIssue
from yyai.handlers.persistence.products import ProductStore
from yyai.handlers.spreadsheets.xlsx import Sheet, read_rows, write_workbook

SHEET_NAME = "products"
MAX_ROWS = 20_000
# Look this far down for the header row, so a title line above the table ("Kahraman stock, Nov 2026") is fine.
HEADER_SEARCH_ROWS = 10
# An import that would switch off more than this share of the active products is almost always the wrong file.
MASS_DEACTIVATION_SHARE = 0.5
MASS_DEACTIVATION_MIN_ACTIVE = 10

# Our field -> the column headings that mean it, in English and Arabic. Matching ignores case, spaces, "_", "-"
# and brackets, so "Price (AED)" and "price_aed" both match "price aed". Columns not listed here are kept as
# product details (attributes): they are searchable and shown by product_details, but never used as a price.
COLUMNS: dict[str, tuple[str, ...]] = {
    "code": ("code", "sku", "item code", "item no", "product code", "رمز", "الرمز", "كود", "رمز الصنف"),
    "name_en": ("name en", "name", "english name", "product", "product name", "item", "item name"),
    "name_ar": ("name ar", "arabic name", "الاسم", "اسم الصنف", "الاسم بالعربي", "الاسم العربي"),
    "category": ("category", "group", "الفئة", "التصنيف", "المجموعة"),
    "description": ("description", "details", "الوصف"),
    "unit": ("unit", "uom", "الوحدة"),
    "price": ("price", "price aed", "selling price", "unit price", "السعر", "سعر البيع"),
    "currency": ("currency", "العملة"),
    "vat_included": ("vat included", "incl vat", "price includes vat", "شامل الضريبة"),
    "in_stock": ("in stock", "available", "availability", "stock status", "متوفر", "التوفر"),
    "quantity": ("quantity", "qty", "stock", "stock qty", "stock quantity", "on hand", "الكمية", "المخزون"),
    "url": ("url", "link", "الرابط"),
    "image_url": ("image url", "image", "photo", "الصورة"),
}
# The order columns are written in when the table is exported. Exporting, editing and importing again changes
# only what was edited.
EXPORT_FIELDS = (
    "code", "name_en", "name_ar", "category", "unit", "price", "currency", "vat_included", "in_stock", "quantity",
    "description", "url", "image_url",
)  # fmt: skip

# A price cell holding one of these, or empty, or 0, means "no price": the agent hands the chat to staff.
NO_PRICE = {"", "-", "–", "—", "n/a", "na", "on request", "price on request", "عند الطلب", "حسب الطلب"}
YES = {"yes", "y", "true", "1", "in stock", "available", "نعم", "متوفر", "موجود"}
NO = {
    "no",
    "n",
    "false",
    "0",
    "out of stock",
    "not available",
    "unavailable",
    "لا",
    "غير متوفر",
    "نفذ",
    "نفد",
}
_CURRENCY_WORDS = re.compile(r"\b(aed|dhs|dh)\b|درهم", re.IGNORECASE)
_CURRENCY_CODE = re.compile(r"^[A-Z]{3}$")
_CENTS = Decimal("0.01")
_THOUSANDTHS = Decimal("0.001")


def _heading(text: Any) -> str:
    folded = normalize_for_search(str(text or ""))
    return " ".join(re.sub(r"[_\-()\[\]/.:]", " ", folded).split())


_FIELD_BY_HEADING = {_heading(alias): name for name, aliases in COLUMNS.items() for alias in (name, *aliases)}


class ProductService:
    def __init__(self, store: ProductStore, *, currency: str = "AED", vat_included: bool = True) -> None:
        self._store = store
        self._currency = currency
        self._vat_included = vat_included

    async def check(
        self, data: bytes, source: str, *, allow_mass_deactivation: bool = False
    ) -> tuple[ProductImportReport, list[ProductRecord]]:
        """Read a sheet and compare it with the table. Changes nothing.

        Raises InvalidFile when the file is not a spreadsheet at all. Every other problem is listed in
        `report.issues`, with the Excel row number, so the client can fix them all in one go.
        """
        rows = read_rows(data, SHEET_NAME)
        records, issues = self._parse(rows)
        report = ProductImportReport(source=source, rows=len(records), issues=issues)
        if issues:
            return report, []

        current = {record.code: record for record in await self._store.active_products()}
        for record in records:
            before = current.get(record.code)
            if before is None:
                report.added.append(record.code)
            elif before != record:
                report.updated.append(record.code)
            else:
                report.unchanged += 1
        seen = {record.code for record in records}
        report.deactivated = sorted(code for code in current if code not in seen)

        too_many = len(report.deactivated) > len(current) * MASS_DEACTIVATION_SHARE
        if too_many and len(current) >= MASS_DEACTIVATION_MIN_ACTIVE and not allow_mass_deactivation:
            report.issues.append(
                SheetIssue(
                    message=(
                        f"This sheet would switch off {len(report.deactivated)} of the {len(current)} products now "
                        "on sale. That usually means the wrong file or a missing part of the sheet. If it is "
                        "really what you want, import it again and confirm that many products may be switched off."
                    )
                )
            )
            return report, []
        return report, records

    async def apply(
        self, report: ProductImportReport, records: list[ProductRecord], imported_by: str | None
    ) -> ProductImportReport:
        """Write a sheet that `check` passed. One transaction: the agent sees either the old table or the new one."""
        if report.issues:
            raise ValueError("A sheet with problems cannot be imported; fix them and check it again")
        changed = set(report.added) | set(report.updated)
        upserts = [record for record in records if record.code in changed]
        await self._store.apply_import(upserts, report.deactivated, report, imported_by)
        return report.model_copy(update={"applied": True})

    async def export(self) -> bytes:
        """The active product table as an .xlsx file in the import layout, ready to edit and upload again."""
        records = await self._store.active_products()
        extra = _attribute_columns(records)
        rows = []
        for record in records:
            values = record.model_dump()
            row: list[Any] = []
            for field in EXPORT_FIELDS:
                value = values[field]
                if field in ("in_stock", "vat_included"):
                    value = "" if value is None else ("yes" if value else "no")
                row.append(value)
            row.extend(record.attributes.get(key) for key in extra)
            rows.append(row)
        return write_workbook([Sheet(title=SHEET_NAME, headers=[*EXPORT_FIELDS, *extra], rows=rows)])

    # --- reading a sheet --------------------------------------------------------------------------------

    def _parse(self, rows: list[tuple[int, list[Any]]]) -> tuple[list[ProductRecord], list[SheetIssue]]:
        if not rows:
            return [], [SheetIssue(message="The sheet is empty.")]
        header_at = next(
            (i for i, (_, cells) in enumerate(rows[:HEADER_SEARCH_ROWS]) if _looks_like_header(cells)), None
        )
        if header_at is None:
            return [], [
                SheetIssue(
                    message="Could not find the heading row. It needs a 'code' column and a 'name' column "
                    "(or 'name_ar' for Arabic names)."
                )
            ]
        header_row, headings = rows[header_at]
        columns, issues = _map_columns(headings, header_row)
        body = rows[header_at + 1 :]
        if not body:
            issues.append(SheetIssue(message="The sheet has headings but no products under them."))
        if len(body) > MAX_ROWS:
            issues.append(SheetIssue(message=f"The sheet has {len(body)} rows; the limit is {MAX_ROWS}."))
        if issues:
            return [], issues

        records: list[ProductRecord] = []
        first_seen: dict[str, int] = {}
        for number, cells in body:
            record, row_issues = self._parse_row(number, cells, columns)
            issues.extend(row_issues)
            if record is None:
                continue
            if record.code in first_seen:
                issues.append(
                    SheetIssue(
                        row=number,
                        column="code",
                        message=f"Code {record.code} is also on row {first_seen[record.code]}. Each code once.",
                    )
                )
                continue
            first_seen[record.code] = number
            records.append(record)
        return records, issues

    def _parse_row(
        self, number: int, cells: list[Any], columns: dict[int, str]
    ) -> tuple[ProductRecord | None, list[SheetIssue]]:
        issues: list[SheetIssue] = []

        def problem(column: str, message: str) -> None:
            issues.append(SheetIssue(row=number, column=column, message=message))

        fields: dict[str, Any] = {}
        attributes: dict[str, str] = {}
        for index, value in enumerate(cells):
            target = columns.get(index)
            if target is None:
                continue
            if target.startswith("attribute:"):
                text = _text(value)
                if text is not None:
                    attributes[target.removeprefix("attribute:")] = text
            else:
                fields[target] = value

        code = _text(fields.get("code"))
        name_en = _text(fields.get("name_en"))
        name_ar = _text(fields.get("name_ar"))
        if code is None:
            problem("code", "The code is empty.")
        if name_en is None and name_ar is None:
            problem("name", "The product has no name.")

        price = None
        raw_price = fields.get("price")
        if not _is_blank_price(raw_price):
            price = _number(raw_price)
            if price is None:
                problem(
                    "price",
                    f"'{raw_price}' is not a price. Use a number, or leave it empty if there is none.",
                )
            elif price < 0:
                problem("price", "The price cannot be negative.")
            elif price == 0:
                price = None  # sheets often hold 0 for "not priced"; the agent must never quote AED 0
            else:
                price = price.quantize(_CENTS, rounding=ROUND_HALF_UP)

        quantity = None
        if _text(fields.get("quantity")) is not None:
            quantity = _number(fields.get("quantity"))
            if quantity is None:
                problem("quantity", f"'{fields.get('quantity')}' is not a quantity. Use a number.")
            elif quantity < 0:
                problem("quantity", "The quantity cannot be negative.")
            else:
                quantity = quantity.quantize(_THOUSANDTHS, rounding=ROUND_HALF_UP)

        in_stock = None
        if _text(fields.get("in_stock")) is not None:
            in_stock = _yes_no(fields.get("in_stock"))
            if in_stock is None:
                problem("in_stock", f"'{fields.get('in_stock')}' is not yes or no.")
        if in_stock is True and quantity == 0:
            problem("in_stock", "It says in stock, but the quantity is 0.")
        if in_stock is False and quantity is not None and quantity > 0:
            problem("in_stock", f"It says out of stock, but the quantity is {quantity}.")

        vat_included = self._vat_included
        if _text(fields.get("vat_included")) is not None:
            parsed = _yes_no(fields.get("vat_included"))
            if parsed is None:
                problem("vat_included", f"'{fields.get('vat_included')}' is not yes or no.")
            else:
                vat_included = parsed

        currency = (_text(fields.get("currency")) or self._currency).upper()
        if not _CURRENCY_CODE.match(currency):
            problem("currency", f"'{currency}' is not a currency code such as AED.")

        if issues or code is None:
            return None, issues
        return (
            ProductRecord(
                code=code,
                name_en=name_en or name_ar or code,
                name_ar=name_ar,
                category=_text(fields.get("category")),
                description=_text(fields.get("description")),
                unit=_text(fields.get("unit")),
                price=price,
                currency=currency,
                vat_included=vat_included,
                in_stock=in_stock,
                quantity=quantity,
                url=_text(fields.get("url")),
                image_url=_text(fields.get("image_url")),
                attributes=attributes,
            ),
            [],
        )


def _looks_like_header(cells: list[Any]) -> bool:
    found = {_FIELD_BY_HEADING.get(_heading(cell)) for cell in cells if cell is not None}
    return "code" in found and bool(found & {"name_en", "name_ar"})


def _map_columns(headings: list[Any], header_row: int) -> tuple[dict[int, str], list[SheetIssue]]:
    """Column position -> our field, or "attribute:<heading>" for a column we keep as a product detail."""
    columns: dict[int, str] = {}
    where: dict[str, str] = {}
    issues: list[SheetIssue] = []
    for index, heading in enumerate(headings):
        label = _text(heading)
        if label is None:
            continue
        field = _FIELD_BY_HEADING.get(_heading(label))
        if field is None:
            columns[index] = f"attribute:{label}"
            continue
        if field in where:
            issues.append(
                SheetIssue(
                    row=header_row,
                    column=label,
                    message=f"Columns '{where[field]}' and '{label}' mean the same thing. Keep one of them.",
                )
            )
            continue
        where[field] = label
        columns[index] = field
    return columns, issues


def _text(value: Any) -> str | None:
    """Cell text, trimmed. Whole numbers lose Excel's ".0" (a code typed as 1001 is "1001", not "1001.0")."""
    if value is None or isinstance(value, bool):
        return None if value is None else ("yes" if value else "no")
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = " ".join(str(value).split())
    return text or None


def _is_blank_price(value: Any) -> bool:
    text = _text(value)
    return text is None or text.lower() in NO_PRICE


def _number(value: Any) -> Decimal | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float | Decimal):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None
    text = normalize_for_search(str(value))  # Eastern Arabic digits become 0-9, "٫" becomes "."
    text = _CURRENCY_WORDS.sub("", text).replace(",", "").replace(" ", "")
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def _yes_no(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    text = (_text(value) or "").lower()
    if text in YES:
        return True
    if text in NO:
        return False
    return None


def _attribute_columns(records: list[ProductRecord]) -> list[str]:
    """Detail columns for the export: the most common first, so the sheet reads well."""
    counts = Counter(key for record in records for key in record.attributes)
    return [key for key, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]
