"""Catalogue sync and fuzzy search, using the sample catalogue shipped with the Kahraman demo config."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest

from yyai.handlers.integrations.file_catalogue.handler import FileCatalogue
from yyai.handlers.persistence.catalogue import CatalogueStore
from yyai.handlers.persistence.db import Database
from yyai.services.catalogue import CatalogueService
from yyai.services.pricing import PricingService

pytestmark = pytest.mark.db


@pytest.fixture
def inventory(kahraman_dir: Path) -> FileCatalogue:
    return FileCatalogue(path=kahraman_dir / "catalogue.json")


@pytest.fixture
def catalogue(db: Database, inventory: FileCatalogue) -> CatalogueService:
    return CatalogueService(inventory, CatalogueStore(db))


@pytest.fixture
async def synced(catalogue: CatalogueService) -> CatalogueService:
    await catalogue.sync()
    return catalogue


async def top_code(catalogue: CatalogueService, query: str) -> str | None:
    matches = await catalogue.search(query, 3)
    return matches[0].item.code if matches else None


# --- sync -------------------------------------------------------------------------------------------


async def test_sync_copies_every_item(
    catalogue: CatalogueService, inventory: FileCatalogue, sql: psycopg.Connection
) -> None:
    expected = len(await inventory.list_items())
    assert expected >= 10

    assert await catalogue.sync() == expected

    assert sql.execute("SELECT count(*) AS n FROM catalogue_items").fetchone()["n"] == expected
    row = sql.execute("SELECT * FROM catalogue_items WHERE code = 'SAMPLE-002'").fetchone()
    assert row["name_en"] == "Colombia Supremo Whole Beans 1kg (sample)"
    assert row["price"] == Decimal("135.00")
    assert row["currency"] == "AED"
    assert row["attributes"]["origin"] == "Colombia"
    assert "1 كجم" in row["search_text"]  # Arabic digits and letters are stored in their folded form


async def test_sync_twice_does_not_duplicate(catalogue: CatalogueService, sql: psycopg.Connection) -> None:
    first = await catalogue.sync()
    second = await catalogue.sync()
    assert first == second
    assert sql.execute("SELECT count(*) AS n FROM catalogue_items").fetchone()["n"] == first


async def test_sync_removes_items_that_left_the_source_and_updates_changed_ones(
    db: Database, tmp_path: Path, kahraman_dir: Path, sql: psycopg.Connection
) -> None:
    data = json.loads((kahraman_dir / "catalogue.json").read_text(encoding="utf-8"))
    path = tmp_path / "catalogue.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    service = CatalogueService(FileCatalogue(path=path), CatalogueStore(db))
    await service.sync()

    data["items"] = [item for item in data["items"] if item["code"] != "SAMPLE-006"]
    next(item for item in data["items"] if item["code"] == "SAMPLE-002")["price"] = 140.5
    path.write_text(json.dumps(data), encoding="utf-8")
    await service.sync()

    codes = {row["code"] for row in sql.execute("SELECT code FROM catalogue_items").fetchall()}
    assert "SAMPLE-006" not in codes
    assert (await service.get("SAMPLE-002")).price == Decimal("140.50")  # type: ignore[union-attr]
    assert await service.get("SAMPLE-006") is None


async def test_an_empty_inventory_never_wipes_the_existing_copy(
    db: Database, tmp_path: Path, kahraman_dir: Path, sql: psycopg.Connection
) -> None:
    path = tmp_path / "catalogue.json"
    path.write_text((kahraman_dir / "catalogue.json").read_text(encoding="utf-8"), encoding="utf-8")
    service = CatalogueService(FileCatalogue(path=path), CatalogueStore(db))
    stored = await service.sync()

    path.write_text(json.dumps({"currency": "AED", "items": []}), encoding="utf-8")

    assert await service.sync() == 0
    assert sql.execute("SELECT count(*) AS n FROM catalogue_items").fetchone()["n"] == stored


# --- search ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("query", "code"),
    [
        ("Ethiopia Yirgacheffe", "SAMPLE-001"),
        ("colombia supremo", "SAMPLE-002"),
        ("BRAZIL SANTOS GROUND", "SAMPLE-003"),
        ("moka pot", "SAMPLE-011"),
        ("descaling solution", "SAMPLE-012"),
        ("Manual Hand Coffee Grinder", "SAMPLE-010"),
        ("bean-to-cup", "SAMPLE-008"),
    ],
)
async def test_search_finds_items_by_english_name(synced: CatalogueService, query: str, code: str) -> None:
    assert await top_code(synced, query) == code


@pytest.mark.parametrize(
    ("query", "code"),
    [
        ("قهوة إثيوبية يرغاشيف", "SAMPLE-001"),
        ("قهوة كولومبية سوبريمو", "SAMPLE-002"),
        ("قهوة برازيلية سانتوس", "SAMPLE-003"),
        ("إبريق موكا", "SAMPLE-011"),
        ("محلول إزالة الكلس", "SAMPLE-012"),
        ("مطحنة قهوة يدوية", "SAMPLE-010"),
        ("ماكينة قهوة أوتوماتيكية", "SAMPLE-008"),
    ],
)
async def test_search_finds_items_by_arabic_name(synced: CatalogueService, query: str, code: str) -> None:
    assert await top_code(synced, query) == code


@pytest.mark.parametrize(
    ("query", "code"),
    [
        ("قهوه اثيوبيه يرغاشيف", "SAMPLE-001"),  # taa marbuta typed as haa, bare alef
        ("قهوة اثيوبية يرغاشيف", "SAMPLE-001"),  # bare alef instead of hamza-below
        ("قهوه كولومبيه سوبريمو", "SAMPLE-002"),
        ("ابريق موكا", "SAMPLE-011"),  # alef without hamza
        ("إبريق موكا من الستانلس", "SAMPLE-011"),
        ("أبريق موكا", "SAMPLE-011"),  # alef with hamza above
        ("ماكينه اسبريسو منزليه", "SAMPLE-007"),
        ("محلول ازالة الكلس لماكينات القهوة", "SAMPLE-012"),
    ],
)
async def test_search_tolerates_alef_and_taa_marbuta_variants(
    synced: CatalogueService, query: str, code: str
) -> None:
    assert await top_code(synced, query) == code


@pytest.mark.parametrize(
    ("query", "code"),
    [
        ("قهوة كولومبية سوبريمو ١ كجم", "SAMPLE-002"),
        ("قهوة إثيوبية ٢٥٠ جم", "SAMPLE-001"),
        ("قهوة كينية AA ٢٥٠ جم", "SAMPLE-006"),
        ("ماكينة إسبريسو منزلية ١٥ بار", "SAMPLE-007"),
        ("إبريق موكا ٦ أكواب", "SAMPLE-011"),
        ("محلول إزالة الكلس ٥٠٠ مل", "SAMPLE-012"),
    ],
)
async def test_search_understands_eastern_arabic_digits(
    synced: CatalogueService, query: str, code: str
) -> None:
    assert await top_code(synced, query) == code


async def test_eastern_arabic_digits_pick_the_right_size_among_similar_items(
    synced: CatalogueService,
) -> None:
    # Two Arabic-coffee style items differ mostly by weight; the digits decide.
    assert await top_code(synced, "قهوة عربية بالهيل ٥٠٠ جم") == "SAMPLE-004"
    assert await top_code(synced, "خلطة إسبريسو ١ كجم") == "SAMPLE-005"


@pytest.mark.parametrize(
    ("query", "code"),
    [
        ("Ethiopa Yirgachefe", "SAMPLE-001"),
        ("Colmbia Supremo", "SAMPLE-002"),
        ("brasil santos", "SAMPLE-003"),
        ("espreso machine", "SAMPLE-007"),
        ("grinder conical", "SAMPLE-009"),
        ("descalling solution", "SAMPLE-012"),
    ],
)
async def test_search_finds_items_despite_a_misspelling(
    synced: CatalogueService, query: str, code: str
) -> None:
    assert await top_code(synced, query) == code


async def test_search_finds_arabic_items_despite_a_misspelling(synced: CatalogueService) -> None:
    assert await top_code(synced, "قهوة كولمبية سوبريمو") == "SAMPLE-002"  # missing yaa
    assert await top_code(synced, "قهوه برازيليه سنتوس") == "SAMPLE-003"  # missing alef


async def test_a_name_match_beats_a_description_mention(synced: CatalogueService) -> None:
    # SAMPLE-003's description says "Ground for moka pot", SAMPLE-011 IS the moka pot. Quoting the wrong one
    # would give the customer the price of a coffee instead of the pot.
    assert await top_code(synced, "moka pot") == "SAMPLE-011"
    assert await top_code(synced, "ابريق موكا") == "SAMPLE-011"


async def test_search_matches_on_category_and_attributes(synced: CatalogueService) -> None:
    grinders = {m.item.code for m in await synced.search("grinders", 10)}
    assert {"SAMPLE-009", "SAMPLE-010"} <= grinders
    assert await top_code(synced, "cardamom") == "SAMPLE-004"  # also in its attributes


async def test_search_respects_the_limit_and_orders_best_first(synced: CatalogueService) -> None:
    matches = await synced.search("coffee", 4)
    assert 1 <= len(matches) <= 4
    scores = [m.score for m in matches]
    assert scores == sorted(scores, reverse=True)


async def test_search_with_no_resemblance_returns_nothing(synced: CatalogueService) -> None:
    assert await synced.search("quantum chromodynamics lagrangian", 5) == []


@pytest.mark.parametrize("query", ["", "   ", "\n"])
async def test_blank_query_returns_nothing(synced: CatalogueService, query: str) -> None:
    assert await synced.search(query, 5) == []


async def test_search_with_sql_wildcards_and_quotes_is_harmless(synced: CatalogueService) -> None:
    for query in ["100%", "_ _ _", "'; DROP TABLE catalogue_items; --", 'say "hello"']:
        await synced.search(query, 5)
    assert len(await synced.search("moka pot", 5)) >= 1  # the table is still there


async def test_get_and_categories(synced: CatalogueService) -> None:
    item = await synced.get("SAMPLE-007")
    assert item is not None
    assert item.name_ar == "ماكينة إسبريسو منزلية 15 بار (عينة)"
    assert item.price == Decimal("899.00")
    assert await synced.get("NOPE") is None

    categories = dict(await synced.categories())
    assert categories["Coffee Beans"] == 4
    assert categories["Coffee Machines"] == 2
    assert sum(categories.values()) == 12


# --- live prices come from the inventory, not from the copy ------------------------------------------------------


async def test_pricing_reads_the_inventory_live(db: Database, tmp_path: Path, kahraman_dir: Path) -> None:
    data = json.loads((kahraman_dir / "catalogue.json").read_text(encoding="utf-8"))
    path = tmp_path / "catalogue.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    inventory = FileCatalogue(path=path)
    service = CatalogueService(inventory, CatalogueStore(db))
    await service.sync()

    next(item for item in data["items"] if item["code"] == "SAMPLE-002")["price"] = 150.25
    next(item for item in data["items"] if item["code"] == "SAMPLE-006")["in_stock"] = True
    path.write_text(json.dumps(data), encoding="utf-8")

    pricing = PricingService(inventory)
    price = await pricing.get_price("SAMPLE-002")
    assert price is not None
    assert (price.price, price.currency, price.vat_included) == (Decimal("150.25"), "AED", True)
    assert (await service.get("SAMPLE-002")).price == Decimal("135.00")  # type: ignore[union-attr]  # the copy is stale
    stock = await pricing.get_stock("SAMPLE-006")
    assert stock is not None and stock.in_stock is True
    assert await pricing.get_price("NOPE") is None
