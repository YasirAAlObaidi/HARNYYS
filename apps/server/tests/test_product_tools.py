"""The product tools give prices only from the pricing service (the product table), never from the catalogue copy.

When there is no sure price, quote_price says `handover: true` and gives no price at all. No database is needed:
the catalogue and pricing services are replaced by small fakes.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest

from yyai.core.errors import IntegrationError
from yyai.core.types import CatalogueItem, CatalogueMatch, ItemPrice, ProductGroup, RunContext, StockLevel
from yyai.core.variants import group_matches
from yyai.workflows.agent.registry import Tool
from yyai.workflows.agent.tools import WEAK_MATCH_SCORE, build_product_tools

CTX = RunContext(
    turn_id=1,
    conversation_id=1,
    channel="webchat",
    customer_id="demo-1",
    customer_name="Demo",
    client_name="Kahraman",
    currency="AED",
    auto_send=True,
)

# The copy says 135. The product table says 139.5. Only 139.5 may ever reach the model.
COPY_PRICE = Decimal("135.00")
TABLE_PRICE = Decimal("139.50")


NAMES = {
    "ETH-1KG": ("Ethiopia Yirgacheffe 1 kg", "إثيوبيا يرغاتشيفي ١ كجم"),
    "ETH-250G": ("Ethiopia Yirgacheffe 250 g", "إثيوبيا يرغاتشيفي ٢٥٠ غ"),
    "C1": ("LeBrew RoastSee C1 – Coffee Roast Degree Analyzer", None),
    "AQUA": ("LeBrew RoastSee AquaGauge – Water Activity Analyzer", None),
    "F4-BLACK": ("Fiorenzato F4 A Coffee Grinder (Black)", None),
    "F4-RED": ("Fiorenzato F4 A Coffee Grinder (Red)", None),
}


def item(code: str = "ETH-1KG", price: Decimal | None = COPY_PRICE, **attributes: Any) -> CatalogueItem:
    name_en, name_ar = NAMES.get(code, (code, None))
    return CatalogueItem(
        code=code,
        name_en=name_en,
        name_ar=name_ar,
        category="Coffee",
        price=price,
        attributes=attributes,
    )


class FakeCatalogue:
    def __init__(self, matches: list[CatalogueMatch]) -> None:
        self.matches = matches

    async def search(self, query: str, limit: int) -> list[CatalogueMatch]:
        return self.matches[:limit]

    async def search_products(self, query: str, limit: int) -> list[ProductGroup]:
        return group_matches(self.matches[:limit])[:limit]

    async def group_for(self, item: CatalogueItem) -> ProductGroup:
        return group_matches([CatalogueMatch(item=item, score=1.0)])[0]

    async def group_by_key(self, key: str) -> ProductGroup | None:
        return None

    async def get(self, code: str) -> CatalogueItem | None:
        return next((m.item for m in self.matches if m.item.code == code), None)

    async def categories(self) -> list[tuple[str, int]]:
        return [("Coffee", len(self.matches))]


class FakePricing:
    def __init__(
        self,
        prices: dict[str, Decimal] | None = None,
        stock: dict[str, bool] | None = None,
        *,
        down: bool = False,
    ) -> None:
        self.prices = prices or {}
        self.stock = stock or {}
        self.down = down
        self.calls = 0

    async def get_price(self, code: str) -> ItemPrice | None:
        self.calls += 1
        if self.down:
            raise IntegrationError("product table unreachable", retryable=True)
        if code not in self.prices:
            return None
        return ItemPrice(code=code, price=self.prices[code], currency="AED", vat_included=True)

    async def get_stock(self, code: str) -> StockLevel | None:
        if self.down:
            raise IntegrationError("product table unreachable", retryable=True)
        if code not in self.stock:
            return None
        return StockLevel(code=code, in_stock=self.stock[code])


def tools(catalogue: FakeCatalogue, pricing: FakePricing) -> dict[str, Tool]:
    return {tool.name: tool for tool in build_product_tools(catalogue, pricing)}  # type: ignore[arg-type]


async def call(tool: Tool, **args: Any) -> Any:
    result = await tool.fn(CTX, tool.args_model(**args))
    json.dumps(result)  # every result must be JSON for the model
    return result


def mentions(result: Any, value: Decimal) -> bool:
    """Whether a price appears anywhere in the result, as 135, 135.0 or "135.00"."""
    text = json.dumps(result)
    return any(form in text for form in {str(value), str(float(value)), str(int(value))})


# --- quote_price -------------------------------------------------------------------------------------------------


async def test_the_price_comes_from_the_product_table_not_the_copy() -> None:
    pricing = FakePricing({"ETH-1KG": TABLE_PRICE}, {"ETH-1KG": True})
    result = await call(tools(FakeCatalogue([CatalogueMatch(item=item(), score=0.9)]), pricing)["quote_price"],
                        query="ethiopia 1kg")  # fmt: skip

    assert result["price"] == 139.5
    assert (result["currency"], result["vat_included"], result["in_stock"]) == ("AED", True, True)
    assert result["handover"] is False
    assert "note" not in result
    assert not mentions(result, COPY_PRICE)


async def test_no_price_in_the_table_hands_over_even_when_the_copy_has_one() -> None:
    pricing = FakePricing(prices={}, stock={"ETH-1KG": True})
    result = await call(tools(FakeCatalogue([CatalogueMatch(item=item(), score=0.9)]), pricing)["quote_price"],
                        query="ethiopia 1kg")  # fmt: skip

    assert result["price"] is None
    assert (result["handover"], result["handover_reason"]) == (True, "missing_price")
    assert "colleague" in result["note"]
    assert "currency" not in result
    assert not mentions(result, COPY_PRICE)


async def test_a_weak_match_gives_no_price_and_asks_which_product() -> None:
    weak = WEAK_MATCH_SCORE - 0.1
    other = CatalogueMatch(item=item("ETH-250G"), score=weak - 0.05)
    pricing = FakePricing({"ETH-1KG": TABLE_PRICE}, {"ETH-1KG": True})
    result = await call(
        tools(FakeCatalogue([CatalogueMatch(item=item(), score=weak), other]), pricing)["quote_price"],
        query="something vague",
    )

    assert (result["clear_match"], result["handover"]) == (
        False,
        False,
    )  # ask first, hand over only if still unclear
    assert "price" not in result
    assert "handover_to_staff" in result["note"]
    assert result["other_matches"] == [
        {"code": "ETH-250G", "name_en": other.item.name_en, "name_ar": other.item.name_ar}
    ]
    assert pricing.calls == 0  # a price we may not give is not even read
    assert not mentions(result, TABLE_PRICE)
    assert not mentions(result, COPY_PRICE)


async def test_nothing_found_asks_for_more_detail() -> None:
    result = await call(tools(FakeCatalogue([]), FakePricing())["quote_price"], query="unicorn beans")

    assert (result["found"], result["handover"]) == (False, False)
    assert "price" not in result
    assert "handover_to_staff" in result["note"]


async def test_a_product_table_that_is_down_hands_over_instead_of_crashing() -> None:
    pricing = FakePricing(down=True)
    result = await call(tools(FakeCatalogue([CatalogueMatch(item=item(), score=0.9)]), pricing)["quote_price"],
                        query="ethiopia 1kg")  # fmt: skip

    assert (result["handover"], result["handover_reason"], result["price"]) == (True, "missing_price", None)
    assert result["in_stock"] is None
    assert not mentions(result, COPY_PRICE)


async def test_unknown_stock_is_flagged_not_guessed() -> None:
    pricing = FakePricing({"ETH-1KG": TABLE_PRICE}, stock={})
    result = await call(tools(FakeCatalogue([CatalogueMatch(item=item(), score=0.9)]), pricing)["quote_price"],
                        query="ethiopia 1kg")  # fmt: skip

    assert result["price"] == 139.5
    assert result["in_stock"] is None
    assert result["handover"] is False
    assert "Stock is not known" in result["note"]


async def test_other_errors_are_not_swallowed() -> None:
    class Broken(FakePricing):
        async def get_price(self, code: str) -> ItemPrice | None:
            raise RuntimeError("bug")

    with pytest.raises(RuntimeError):
        await call(
            tools(FakeCatalogue([CatalogueMatch(item=item(), score=0.9)]), Broken())["quote_price"], query="x"
        )


# --- search_products and product_details -------------------------------------------------------------------------


async def test_search_results_carry_no_prices() -> None:
    matches = [CatalogueMatch(item=item(), score=0.9), CatalogueMatch(item=item("ETH-250G"), score=0.7)]
    results = await call(tools(FakeCatalogue(matches), FakePricing())["search_products"], query="ethiopia")

    assert [r["code"] for r in results] == ["ETH-1KG", "ETH-250G"]
    assert all(set(r) == {"code", "name_en", "name_ar", "category", "has_variants"} for r in results)
    assert not mentions(results, COPY_PRICE)


async def test_details_drop_price_like_columns_and_never_fall_back_to_the_copy() -> None:
    detailed = item(
        origin="Ethiopia", roast="Light", **{"Trade price": "120", "سعر الجملة": "120", "cost": "90"}
    )
    pricing = FakePricing(prices={}, stock={"ETH-1KG": False})
    result = await call(
        tools(FakeCatalogue([CatalogueMatch(item=detailed, score=0.9)]), pricing)["product_details"],
        code="ETH-1KG",
    )

    assert result["attributes"] == {"origin": "Ethiopia", "roast": "Light"}
    assert result["price"] is None
    assert result["in_stock"] is False
    assert "no price" in result["note"]
    assert "120" not in json.dumps(result, ensure_ascii=False)
    assert not mentions(result, COPY_PRICE)


async def test_details_with_a_table_price() -> None:
    pricing = FakePricing({"ETH-1KG": TABLE_PRICE}, {"ETH-1KG": True})
    result = await call(
        tools(FakeCatalogue([CatalogueMatch(item=item(), score=0.9)]), pricing)["product_details"],
        code="ETH-1KG",
    )

    assert (result["price"], result["currency"], result["vat_included"], result["in_stock"]) == (
        139.5,
        "AED",
        True,
        True,
    )
    assert "note" not in result


async def test_details_for_an_unknown_code() -> None:
    result = await call(tools(FakeCatalogue([]), FakePricing())["product_details"], code="MADE-UP")

    assert result["found"] is False


# --- several products match equally well ------------------------------------------------------------------------


async def test_two_different_products_that_match_equally_are_offered_as_a_choice() -> None:
    matches = [CatalogueMatch(item=item("AQUA"), score=1.0), CatalogueMatch(item=item("C1"), score=0.98)]
    pricing = FakePricing({"AQUA": Decimal(1400), "C1": Decimal(1300)}, {"AQUA": True})
    result = await call(tools(FakeCatalogue(matches), pricing)["quote_price"], query="lebrew")

    assert (result["clear_match"], result["handover"]) == (False, False)
    assert "price" not in result  # no single price: the customer is asked which one
    assert [(o["code"], o["price"], o["in_stock"]) for o in result["options"]] == [
        ("AQUA", 1400, True),
        ("C1", 1300, None),
    ]
    assert "which one" in result["note"]
    assert not mentions(result, COPY_PRICE)


async def test_colours_of_one_product_are_not_a_choice() -> None:
    matches = [
        CatalogueMatch(item=item("F4-BLACK"), score=1.0),
        CatalogueMatch(item=item("F4-RED"), score=1.0),
    ]
    pricing = FakePricing({"F4-BLACK": Decimal(1300)}, {"F4-BLACK": True})
    result = await call(tools(FakeCatalogue(matches), pricing)["quote_price"], query="f4")

    assert (result["clear_match"], result["price"], result["handover"]) == (True, 1300, False)
    assert result["other_matches"] == []


async def test_a_weak_second_match_does_not_make_a_clear_one_ambiguous() -> None:
    matches = [CatalogueMatch(item=item(), score=0.52), CatalogueMatch(item=item("C1"), score=0.49)]
    pricing = FakePricing({"ETH-1KG": TABLE_PRICE}, {"ETH-1KG": True})
    result = await call(tools(FakeCatalogue(matches), pricing)["quote_price"], query="ethiopia")

    assert (result["clear_match"], result["price"]) == (True, 139.5)
