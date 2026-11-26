"""Model numbers decide the product: "CBR 300" must not quote the CBR 301, "gene cafe 1200" must find the CBR-1200.

Uses tests/fixtures/model_numbers_catalogue.json: the nine Gene Cafe items from the Kahraman catalogue, whose
names differ mostly by model number (CBR-101, CBC-101, CBR 301, CBR-1200, VR-P500).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from yyai.core.text import normalize_for_search
from yyai.core.types import CatalogueItem
from yyai.handlers.integrations.file_catalogue.handler import FileCatalogue
from yyai.handlers.persistence.catalogue import CatalogueStore
from yyai.handlers.persistence.db import Database
from yyai.services.catalogue import (
    CatalogueService,
    code_agreement,
    model_codes,
    model_numbers,
    number_agreement,
    same_product,
)
from yyai.workflows.agent.tools import WEAK_MATCH_SCORE

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "model_numbers_catalogue.json"

CBR_101 = "gene-cafe-cbr-101-coffee-roasting-machine-250g-with-temperature-and-cooling-control-black"
CBR_301 = "gene-cafe-cbr-301-coffee-roaster-white"
CBR_1200 = "gene-cafe-roaster-cbr-1200-black"
VR_P500 = "gene-cafe-roaster-vr-p500-brown"


# --- pure functions ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("cbr-1200", {"1200"}),
        ("cbr 301 – coffee roaster", {"301"}),
        ("cbr1200", {"1200"}),
        ("vr-p500", {"500"}),
        ("cbr-101 coffee roasting machine 250g", {"101", "250"}),
        ("1,000 g", {"1000"}),
        ("2 moka pots", set()),  # a quantity, not a model
        ("espresso machine 15 bar", set()),
        ("2.5 kg", set()),  # decimals are sizes we do not compare
        ("moka pot", set()),
    ],
)
def test_model_numbers(text: str, expected: set[str]) -> None:
    assert model_numbers(text) == expected


def test_model_numbers_reads_eastern_arabic_digits_after_normalising() -> None:
    assert model_numbers(normalize_for_search("محمصة جين كافيه ٣٠١")) == {"301"}


@pytest.mark.parametrize(
    ("wanted", "offered", "expected"),
    [
        ({"301"}, {"301"}, True),
        ({"101", "250"}, {"250"}, True),  # one shared number is enough: the other may be a size or a quantity
        ({"300"}, {"301"}, False),
        ({"1200"}, {"101", "250"}, False),
        (set(), {"301"}, None),  # the customer gave no number
        ({"301"}, set(), None),  # the item has none
    ],
)
def test_number_agreement(wanted: set[str], offered: set[str], expected: bool | None) -> None:
    assert number_agreement(wanted, offered) is expected


# --- search -----------------------------------------------------------------------------------------------------


@pytest.fixture
async def gene_cafe(db: Database) -> CatalogueService:
    service = CatalogueService(FileCatalogue(path=FIXTURE), CatalogueStore(db))
    await service.sync()
    return service


def _model(code: str) -> str:
    return re.sub(r"-(red|black|white|brown)$", "", code)


async def _top(service: CatalogueService, query: str) -> tuple[str, float]:
    matches = await service.search(query, 3)
    assert matches, f"no match for {query!r}"
    return matches[0].item.code, matches[0].score


@pytest.mark.db
@pytest.mark.parametrize(
    ("query", "code"),
    [
        ("CBR 101", CBR_101),
        ("cbr-101 black", CBR_101),
        ("CBR 301", CBR_301),
        ("cbr-301", CBR_301),
        ("CBR-1200", CBR_1200),
        ("cbr1200", CBR_1200),
        ("gene cafe 1200", CBR_1200),
        ("Gene Cafe roaster 1200 black", CBR_1200),
        ("جين كافيه ١٢٠٠", CBR_1200),
        ("محمصة جين كافيه 301", CBR_301),
        ("VR P500", VR_P500),
    ],
)
async def test_the_customers_model_number_wins(gene_cafe: CatalogueService, query: str, code: str) -> None:
    top_code, score = await _top(gene_cafe, query)
    assert _model(top_code) == _model(code)  # either colour of the right model will do
    assert score >= WEAK_MATCH_SCORE


@pytest.mark.db
@pytest.mark.parametrize("query", ["CBR 300", "CBR 1300", "gene cafe 999", "محمصة جين كافيه ٤٠٠"])
async def test_a_model_number_we_do_not_sell_is_only_a_weak_match(
    gene_cafe: CatalogueService, query: str
) -> None:
    # Offering look-alikes is fine; quoting one as if it were what the customer asked for is not.
    matches = await gene_cafe.search(query, 3)
    assert all(match.score < WEAK_MATCH_SCORE for match in matches), [
        (m.item.name_en, round(m.score, 2)) for m in matches
    ]


@pytest.mark.db
async def test_no_number_in_the_query_changes_nothing(gene_cafe: CatalogueService) -> None:
    matches = await gene_cafe.search("gene cafe roaster", 9)
    assert len(matches) >= 5
    assert all(match.score >= WEAK_MATCH_SCORE for match in matches[:5])


@pytest.mark.db
async def test_scores_stay_sorted_after_reranking(gene_cafe: CatalogueService) -> None:
    for query in ["CBR 300", "gene cafe 1200", "CBR 101"]:
        scores = [match.score for match in await gene_cafe.search(query, 9)]
        assert scores == sorted(scores, reverse=True)


# --- short model codes ("F5", "F64", "V60") and colours ----------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "codes"),
    [
        ("مطاحن f5", {"f5"}),
        ("f64 evo", {"f64"}),
        ("hario v60 dripper", {"v60"}),
        ("cbr101", {"cbr101"}),
        ("hb-600 grams", set()),  # "600" is a model number, handled by model_numbers
        ("ethiopia 1kg and 250g", set()),  # sizes are not codes
        ("15bar pump 1350w", set()),
    ],
)
def test_model_codes(text: str, codes: set[str]) -> None:
    assert model_codes(text) == codes


def test_an_item_without_the_customers_code_does_not_agree() -> None:
    assert code_agreement({"f5"}, set()) is False  # "F5 grinder" never means a grinder cleaner
    assert code_agreement({"f5"}, {"f5"}) is True
    assert code_agreement(set(), {"f5"}) is None


def test_same_product_ignores_colour_only() -> None:
    def named(name: str) -> CatalogueItem:
        return CatalogueItem(code=name, name_en=name)

    assert same_product(
        named("Fiorenzato F4 A Coffee Grinder (Black)"), named("Fiorenzato F4 A Coffee Grinder (Red)")
    )
    assert not same_product(
        named("VBM Audrey Espresso Machine (Grey, 1 Group)"),
        named("VBM Audrey Espresso Machine (Grey, 2 Groups)"),
    )


@pytest.mark.db
async def test_a_code_written_joined_finds_the_product(gene_cafe: CatalogueService) -> None:
    top_code, _ = await _top(gene_cafe, "CBR301")
    assert "301" in top_code, top_code
