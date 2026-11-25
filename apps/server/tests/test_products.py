"""The product sheet: Excel in, product table out, and back out as Excel.

The first half needs no database: it checks how a sheet is read and what counts as a problem. The second half
loads sheets into Postgres and checks what the agent then sees (prices, stock, search).
"""

from __future__ import annotations

from decimal import Decimal
from io import BytesIO
from typing import Any

import psycopg
import pytest
from openpyxl import Workbook, load_workbook

from yyai.cli import format_report
from yyai.core.errors import InvalidFile
from yyai.core.types import ProductRecord
from yyai.handlers.persistence.catalogue import CatalogueStore
from yyai.handlers.persistence.db import Database
from yyai.handlers.persistence.products import ProductStore
from yyai.services.catalogue import CatalogueService
from yyai.services.pricing import PricingService
from yyai.services.products import EXPORT_FIELDS, ProductService
from yyai.workflows.products import ProductSheetWorkflow

HEADINGS = ["code", "name_en", "name_ar", "category", "unit", "price", "in_stock", "quantity"]


def xlsx(
    *rows: list[Any], title: str = "products", extra_sheets: dict[str, list[list[Any]]] | None = None
) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = title
    for row in rows:
        sheet.append(row)
    for name, extra_rows in (extra_sheets or {}).items():
        extra = workbook.create_sheet(name)
        for row in extra_rows:
            extra.append(row)
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def roaster(code: str = "CBR-301", price: Any = 3500, **overrides: Any) -> list[Any]:
    row = {
        "code": code,
        "name_en": f"Gene Cafe {code} roaster",
        "name_ar": f"محمصة جين كافيه {code}",
        "category": "Coffee roasters",
        "unit": "piece",
        "price": price,
        "in_stock": "yes",
        "quantity": 4,
    } | overrides
    return [row[heading] for heading in HEADINGS]


class EmptyStore:
    """Stands in for the product table when only the reading of a sheet is under test."""

    async def active_products(self) -> list[ProductRecord]:
        return []


@pytest.fixture
def reader() -> ProductService:
    return ProductService(EmptyStore())  # type: ignore[arg-type]


async def read(service: ProductService, data: bytes):
    return await service.check(data, "test.xlsx")


# --- reading a sheet (no database) ------------------------------------------------------------------------------


async def test_a_clean_sheet_is_read_into_records(reader: ProductService) -> None:
    report, records = await read(reader, xlsx(HEADINGS, roaster("CBR-301"), roaster("CBR-1200", 15750)))
    assert report.issues == []
    assert [r.code for r in records] == ["CBR-301", "CBR-1200"]
    first = records[0]
    assert first.price == Decimal("3500.00")
    assert (first.in_stock, first.quantity, first.unit) == (True, Decimal(4), "piece")
    assert first.name_ar == "محمصة جين كافيه CBR-301"
    assert report.added == ["CBR-301", "CBR-1200"]


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        (1890, Decimal("1890.00")),
        (48.5, Decimal("48.50")),
        ("1,890", Decimal("1890.00")),
        ("AED 1,890", Decimal("1890.00")),
        ("1890 درهم", Decimal("1890.00")),
        ("٤٨", Decimal("48.00")),  # Eastern Arabic digits
        ("12.345", Decimal("12.35")),  # rounded to fils, as the table stores it
        (None, None),
        ("", None),
        ("-", None),
        ("price on request", None),
        ("عند الطلب", None),
        (0, None),  # 0 means "not priced": the agent must never quote AED 0
    ],
)
async def test_price_cells(reader: ProductService, cell: Any, expected: Decimal | None) -> None:
    report, records = await read(reader, xlsx(HEADINGS, roaster(price=cell)))
    assert report.issues == []
    assert records[0].price == expected


@pytest.mark.parametrize(
    ("in_stock", "quantity", "expected"),
    [
        ("yes", 4, (True, Decimal(4))),
        ("نعم", None, (True, None)),
        ("no", 0, (False, Decimal(0))),
        ("غير متوفر", None, (False, None)),
        (True, None, (True, None)),  # an Excel TRUE cell
        (None, 7, (None, Decimal(7))),  # stock follows the quantity
        (None, None, (None, None)),  # unknown: staff must confirm
    ],
)
async def test_stock_cells(
    reader: ProductService, in_stock: Any, quantity: Any, expected: tuple[bool | None, Decimal | None]
) -> None:
    report, records = await read(reader, xlsx(HEADINGS, roaster(in_stock=in_stock, quantity=quantity)))
    assert report.issues == []
    assert (records[0].in_stock, records[0].quantity) == expected


async def test_codes_typed_as_numbers_keep_no_decimal_point(reader: ProductService) -> None:
    _, records = await read(reader, xlsx(HEADINGS, roaster(code=1001), roaster(code=1002.0)))
    assert [r.code for r in records] == ["1001", "1002"]


async def test_arabic_headings_and_a_title_row_above_the_table(reader: ProductService) -> None:
    data = xlsx(
        ["قائمة أسعار قهرمان - نوفمبر 2026"],
        [],
        ["الرمز", "الاسم", "السعر", "الكمية"],
        ["B-1", "قهوة إثيوبية محمصة 1 كجم", "١٣٥", "٢٠"],
    )
    report, records = await read(reader, data)
    assert report.issues == []
    record = records[0]
    assert (record.code, record.price, record.quantity) == ("B-1", Decimal("135.00"), Decimal(20))
    assert record.name_ar == "قهوة إثيوبية محمصة 1 كجم"
    assert record.name_en == record.name_ar  # no English name: the Arabic one stands in


async def test_unknown_columns_are_kept_as_product_details(reader: ProductService) -> None:
    data = xlsx([*HEADINGS, "Origin", "Cup notes"], [*roaster(), "Ethiopia", "jasmine, peach"])
    _, records = await read(reader, data)
    assert records[0].attributes == {"Origin": "Ethiopia", "Cup notes": "jasmine, peach"}


async def test_headings_match_regardless_of_case_spaces_and_brackets(reader: ProductService) -> None:
    data = xlsx(
        ["Item Code", "Product Name", "Price (AED)", "In Stock", "Qty"], ["X1", "Moka pot", 95, "Yes", 3]
    )
    report, records = await read(reader, data)
    assert report.issues == []
    assert (records[0].code, records[0].name_en, records[0].price) == ("X1", "Moka pot", Decimal("95.00"))


async def test_a_sheet_named_products_is_preferred_over_the_first_sheet(reader: ProductService) -> None:
    data = xlsx(["notes"], ["ignore me"], title="Readme", extra_sheets={"Products": [HEADINGS, roaster()]})
    report, records = await read(reader, data)
    assert report.issues == []
    assert [r.code for r in records] == ["CBR-301"]


async def test_every_problem_is_reported_with_its_row_and_nothing_is_loaded(reader: ProductService) -> None:
    data = xlsx(
        HEADINGS,
        roaster("A"),  # row 2: fine
        roaster(None),  # row 3: no code
        roaster("C", price="abc"),  # row 4
        roaster("D", price=-5),  # row 5
        roaster("E", quantity="lots"),  # row 6
        roaster("F", in_stock="maybe"),  # row 7
        roaster("G", in_stock="yes", quantity=0),  # row 8: contradicts itself
        roaster("A"),  # row 9: duplicate of row 2
        ["H", None, None, None, None, 10, None, None],  # row 10: no name at all
    )
    report, records = await read(reader, data)
    assert records == []
    found = {(issue.row, issue.column) for issue in report.issues}
    assert found == {
        (3, "code"),
        (4, "price"),
        (5, "price"),
        (6, "quantity"),
        (7, "in_stock"),
        (8, "in_stock"),
        (9, "code"),
        (10, "name"),
    }
    duplicate = next(issue for issue in report.issues if issue.row == 9)
    assert "row 2" in duplicate.message


@pytest.mark.parametrize(
    ("rows", "fragment"),
    [
        ([], "empty"),
        ([["price", "stock"], [10, 2]], "heading row"),
        ([HEADINGS], "no products"),
        ([["code", "name", "price", "Price (AED)"], ["A", "x", 1, 2]], "mean the same thing"),
    ],
)
async def test_sheet_level_problems(reader: ProductService, rows: list[list[Any]], fragment: str) -> None:
    report, records = await read(reader, xlsx(*rows))
    assert records == []
    assert any(fragment in issue.message for issue in report.issues), report.issues


async def test_a_file_that_is_not_a_spreadsheet_is_refused(reader: ProductService) -> None:
    with pytest.raises(InvalidFile):
        await read(reader, b"code,name,price\nA,Moka pot,95\n")


def test_the_report_text_says_nothing_changed_when_there_are_problems() -> None:
    from yyai.core.types import ProductImportReport, SheetIssue

    text = format_report(
        ProductImportReport(source="p.xlsx", issues=[SheetIssue(row=4, column="price", message="bad")])
    )
    assert "Nothing was changed" in text
    assert "row 4, price: bad" in text
    preview = format_report(ProductImportReport(source="p.xlsx", rows=2, added=["A", "B"]))
    assert "Preview only" in preview and "New:" in preview


# --- loading into the table (database) ---------------------------------------------------------------------------


@pytest.fixture
def store(db: Database) -> ProductStore:
    return ProductStore(db)


@pytest.fixture
def workflow(db: Database, store: ProductStore) -> ProductSheetWorkflow:
    return ProductSheetWorkflow(ProductService(store), CatalogueService(store, CatalogueStore(db)))


@pytest.mark.db
async def test_import_then_reimport_tracks_what_changed(
    workflow: ProductSheetWorkflow, store: ProductStore, sql: psycopg.Connection
) -> None:
    first = await workflow.import_sheet(
        xlsx(HEADINGS, roaster("A"), roaster("B"), roaster("C")),
        source="v1.xlsx",
        apply=True,
        imported_by="sara",
    )
    assert (first.applied, first.added) == (True, ["A", "B", "C"])

    same = await workflow.import_sheet(
        xlsx(HEADINGS, roaster("A"), roaster("B"), roaster("C")), source="v1.xlsx", apply=True
    )
    assert (same.added, same.updated, same.deactivated, same.unchanged) == ([], [], [], 3)

    changed = await workflow.import_sheet(
        xlsx(HEADINGS, roaster("A", price=3600), roaster("B")), source="v2.xlsx", apply=True
    )
    assert (changed.updated, changed.deactivated, changed.unchanged) == (["A"], ["C"], 1)
    assert [r.code for r in await store.active_products()] == ["A", "B"]
    assert sql.execute("SELECT active FROM products WHERE code = 'C'").fetchone()["active"] is False

    back = await workflow.import_sheet(
        xlsx(HEADINGS, roaster("A", price=3600), roaster("B"), roaster("C")), source="v3.xlsx", apply=True
    )
    assert back.added == ["C"]  # switched back on

    log = sql.execute(
        "SELECT source, imported_by, rows, added, updated, deactivated FROM product_imports ORDER BY id"
    )
    assert [tuple(row.values()) for row in log.fetchall()] == [
        ("v1.xlsx", "sara", 3, 3, 0, 0),
        ("v1.xlsx", None, 3, 0, 0, 0),
        ("v2.xlsx", None, 2, 0, 1, 1),
        ("v3.xlsx", None, 3, 1, 0, 0),
    ]


@pytest.mark.db
async def test_a_preview_or_a_sheet_with_problems_changes_nothing(
    workflow: ProductSheetWorkflow, store: ProductStore, sql: psycopg.Connection
) -> None:
    await workflow.import_sheet(xlsx(HEADINGS, roaster("A")), source="v1.xlsx", apply=True)

    preview = await workflow.import_sheet(xlsx(HEADINGS, roaster("A", price=1)), source="v2.xlsx")
    assert (preview.applied, preview.updated) == (False, ["A"])

    broken = await workflow.import_sheet(
        xlsx(HEADINGS, roaster("A", price=1), roaster("B", price="??")), source="v3.xlsx", apply=True
    )
    assert broken.applied is False and broken.issues

    assert (await store.active_products())[0].price == Decimal("3500.00")
    assert sql.execute("SELECT count(*) AS n FROM product_imports").fetchone()["n"] == 1


@pytest.mark.db
async def test_switching_off_most_of_the_table_needs_confirmation(
    workflow: ProductSheetWorkflow, store: ProductStore
) -> None:
    await workflow.import_sheet(
        xlsx(HEADINGS, *(roaster(f"P{n}") for n in range(12))), source="all", apply=True
    )

    partial = xlsx(HEADINGS, roaster("P0"), roaster("P1"), roaster("P2"))
    refused = await workflow.import_sheet(partial, source="part", apply=True)
    assert refused.applied is False
    assert "switch off 9 of the 12" in refused.issues[0].message
    assert len(await store.active_products()) == 12

    allowed = await workflow.import_sheet(partial, source="part", apply=True, allow_mass_deactivation=True)
    assert allowed.applied is True
    assert len(await store.active_products()) == 3


@pytest.mark.db
async def test_prices_and_stock_the_agent_sees(workflow: ProductSheetWorkflow, store: ProductStore) -> None:
    await workflow.import_sheet(
        xlsx(
            HEADINGS,
            roaster("PRICED"),
            roaster("NOPRICE", price=None),
            roaster("EMPTY", in_stock="no", quantity=0),
            roaster("UNKNOWN", in_stock=None, quantity=None),
            roaster("COUNTED", in_stock=None, quantity=2),
            roaster("GONE"),
        ),
        source="v1",
        apply=True,
    )
    await workflow.import_sheet(  # GONE leaves the sheet: it must stop being quoted
        xlsx(
            HEADINGS,
            roaster("PRICED"),
            roaster("NOPRICE", price=None),
            roaster("EMPTY", in_stock="no", quantity=0),
            roaster("UNKNOWN", in_stock=None, quantity=None),
            roaster("COUNTED", in_stock=None, quantity=2),
        ),
        source="v2",
        apply=True,
    )
    pricing = PricingService(store)
    all_codes = ["PRICED", "NOPRICE", "EMPTY", "UNKNOWN", "COUNTED", "GONE"]

    prices = await store.get_prices(all_codes)
    assert set(prices) == {
        "PRICED",
        "EMPTY",
        "UNKNOWN",
        "COUNTED",
    }  # no price and switched-off items are absent
    assert (prices["PRICED"].price, prices["PRICED"].currency, prices["PRICED"].vat_included) == (
        Decimal("3500.00"),
        "AED",
        True,
    )
    assert await pricing.get_price("GONE") is None

    stock = await store.get_stock(all_codes)
    assert set(stock) == {"PRICED", "NOPRICE", "EMPTY", "COUNTED"}  # UNKNOWN: staff must confirm
    assert stock["EMPTY"].in_stock is False
    assert (stock["COUNTED"].in_stock, stock["COUNTED"].quantity) == (True, Decimal("2.000"))

    items = {item.code: item for item in await store.list_items()}
    assert "GONE" not in items
    assert items["PRICED"].attributes["unit"] == "piece"


@pytest.mark.db
async def test_an_import_refreshes_search_at_once(workflow: ProductSheetWorkflow, db: Database) -> None:
    search = CatalogueService(ProductStore(db), CatalogueStore(db))
    await workflow.import_sheet(xlsx(HEADINGS, roaster("CBR-301")), source="v1", apply=True)
    matches = await search.search("CBR 301", 3)
    assert matches and matches[0].item.code == "CBR-301"


@pytest.mark.db
async def test_export_then_import_changes_nothing(workflow: ProductSheetWorkflow) -> None:
    sheet = xlsx(
        [*HEADINGS, "description", "Origin"],
        [*roaster("A"), "Roasts 300 g", "Korea"],
        [*roaster("B", price=None, in_stock=None, quantity=None), None, None],
        [*roaster("C", price="48.5", in_stock="no", quantity=0), None, "Ethiopia"],
    )
    await workflow.import_sheet(sheet, source="v1", apply=True)

    exported = await workflow.export_sheet()
    headings = [cell.value for cell in load_workbook(BytesIO(exported)).active[1]]
    assert headings[: len(EXPORT_FIELDS)] == list(EXPORT_FIELDS)
    assert "Origin" in headings

    again = await workflow.import_sheet(exported, source="export.xlsx", apply=True)
    assert again.issues == []
    assert (again.added, again.updated, again.deactivated, again.unchanged) == ([], [], [], 3)
