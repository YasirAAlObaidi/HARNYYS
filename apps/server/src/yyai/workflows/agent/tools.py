"""The product tools the agent can call. All are read-only.

The descriptions below are prompts: the model reads them to decide when and how
to call each tool, so they say what to do and what never to do.

Prices and stock come only from the pricing service, which reads the client's product
table (or ERP). The catalogue copy is used to find products, never for a price. A weak
match gives no price, so the model asks which product is meant. A clear match with no
price says `handover: true`, so the chat goes to staff instead of the model guessing.
"""

from __future__ import annotations

import asyncio
import logging
import re
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from yyai.core.errors import IntegrationError
from yyai.core.types import CatalogueItem, CatalogueMatch, ItemPrice, RunContext, StockLevel
from yyai.services.catalogue import CatalogueService, same_product
from yyai.services.pricing import PricingService
from yyai.workflows.agent.registry import Tool

logger = logging.getLogger(__name__)

# Below this catalogue match score, quote_price gives no price: the item may be a different product.
WEAK_MATCH_SCORE = 0.5
# A different product scoring within this much of the best one makes the question ambiguous ("Lebrew" matches
# two LeBrew analysers equally well), so the customer is asked which one. Colours of one product do not count.
TIE_MARGIN = 0.05

# Product details whose name looks like a price are never shown to the model: only the price column is a price.
_PRICE_LIKE = re.compile(r"price|cost|\baed\b|\bdhs?\b|سعر|اسعار|أسعار|تكلفة|درهم", re.IGNORECASE)

NOT_FOUND_NOTE = (
    "No product matched. Ask the customer once for the product name, brand or size. If it still is not "
    "found, do not guess: call handover_to_staff with reason unclear_item."
)
UNCLEAR_NOTE = (
    "Weak match: this may be a different product from the one the customer asked for, so no price is "
    "given. Ask which product they mean, naming this one and other_matches. Never quote a price for it. "
    "If it is still unclear after that, call handover_to_staff with reason unclear_item."
)
MISSING_PRICE_NOTE = (
    "There is no price for this item. Do not state, estimate or recall any price. Call handover_to_staff "
    "with reason missing_price, then tell the customer a colleague will reply with the price shortly."
)
AMBIGUOUS_NOTE = (
    "Several different products match equally well. Ask the customer which one they mean, naming the options. "
    "You may say an option's price only if it is not null, exactly as shown. Then call quote_price again with "
    "the exact product name."
)
UNKNOWN_STOCK_NOTE = (
    "Stock is not known for this item. Never say it is in or out of stock. If the customer asks, say a "
    "colleague will confirm."
)


class SearchProductsArgs(BaseModel):
    query: str = Field(
        min_length=1,
        max_length=200,
        description="What to look for, in English or Arabic: a product name, type, brand or use.",
    )
    limit: int = Field(5, ge=1, le=10, description="How many matches to return (1 to 10).")


class QuotePriceArgs(BaseModel):
    query: str = Field(
        min_length=1,
        max_length=200,
        description="The product the customer asked about, in their own words (English or Arabic).",
    )


class ProductDetailsArgs(BaseModel):
    code: str = Field(
        min_length=1,
        max_length=200,  # codes can be web slugs (the demo catalogue has 94 characters), not only short SKUs
        description="The exact item code, copied from search_products or quote_price.",
    )


class NoArgs(BaseModel):
    pass


def build_product_tools(catalogue: CatalogueService, pricing: PricingService) -> list[Tool]:
    async def search_products(ctx: RunContext, args: SearchProductsArgs) -> list[dict[str, Any]]:
        matches = await catalogue.search(args.query, args.limit)
        return [
            {
                "code": match.item.code,
                "name_en": match.item.name_en,
                "name_ar": match.item.name_ar,
                "category": match.item.category,
            }
            for match in matches
        ]

    async def quote_price(ctx: RunContext, args: QuotePriceArgs) -> dict[str, Any]:
        matches = await catalogue.search(args.query, 8)
        if not matches:
            return {"found": False, "handover": False, "note": NOT_FOUND_NOTE}
        best, score = matches[0].item, matches[0].score
        others = _distinct(matches)[1:]  # other products, not the same product in another colour
        result: dict[str, Any] = {
            "found": True,
            "code": best.code,
            "name_en": best.name_en,
            "name_ar": best.name_ar,
            "url": best.url,
            "match_score": round(score, 2),
            "clear_match": score >= WEAK_MATCH_SCORE,
            "other_matches": [_short(match) for match in others[:2]],
        }
        if score < WEAK_MATCH_SCORE:
            # The store keeps loose matches (score from 0.25) so that browsing works. For one quoted price a loose
            # match is usually a different product that shares a word or a weight with what the customer asked for.
            # No handover yet: the customer is asked which product they mean first.
            return {**result, "handover": False, "note": UNCLEAR_NOTE}
        rivals = [m for m in others if m.score >= max(score - TIE_MARGIN, WEAK_MATCH_SCORE)][:2]
        if rivals:
            options = [await _option(pricing, match.item) for match in [matches[0], *rivals]]
            return {
                "found": True,
                "clear_match": False,
                "handover": False,
                "options": options,
                "note": AMBIGUOUS_NOTE,
            }
        price, stock = await _live(pricing, best.code)
        result["in_stock"] = stock.in_stock if stock else None
        if price is None:
            # The product is clear but has no price: only staff can answer, so the turn hands over (see turn.py).
            return {**result, "price": None, "handover": True, "handover_reason": "missing_price",
                    "note": MISSING_PRICE_NOTE}  # fmt: skip
        result.update(price=_num(price.price), currency=price.currency, vat_included=price.vat_included)
        result["handover"] = False
        if stock is None:
            result["note"] = UNKNOWN_STOCK_NOTE
        return result

    async def product_details(ctx: RunContext, args: ProductDetailsArgs) -> dict[str, Any]:
        item = await catalogue.get(args.code)
        if item is None:
            return {
                "found": False,
                "note": "Unknown code. Only use codes returned by search_products or quote_price.",
            }
        price, stock = await _live(pricing, item.code)
        result: dict[str, Any] = {
            "found": True,
            "code": item.code,
            "name_en": item.name_en,
            "name_ar": item.name_ar,
            "category": item.category,
            "description": item.description,
            "attributes": _safe_attributes(item),
            "price": _num(price.price) if price else None,
            "in_stock": stock.in_stock if stock else None,
            "url": item.url,
            "image_url": item.image_url,
        }
        notes = []
        if price is not None:
            result.update(currency=price.currency, vat_included=price.vat_included)
        else:
            notes.append(MISSING_PRICE_NOTE)
        if stock is None:
            notes.append(UNKNOWN_STOCK_NOTE)
        if notes:
            result["note"] = " ".join(notes)
        return result

    async def list_categories(ctx: RunContext, args: NoArgs) -> list[dict[str, Any]]:
        return [{"category": name, "count": count} for name, count in await catalogue.categories()]

    return [
        Tool(
            name="search_products",
            description=(
                "Search the product catalogue by name, type, brand or use, in English or Arabic. "
                "Use it to browse or when the customer has not named one specific product "
                "(for example 'do you have coffee machines?'). Returns up to `limit` matches with "
                "item codes and no prices: call quote_price for any price. An empty list means "
                "nothing matched: try simpler words or the other language before telling the "
                "customer we do not have it."
            ),
            args_model=SearchProductsArgs,
            risk="read",
            fn=search_products,
        ),
        Tool(
            name="quote_price",
            description=(
                "Get the current price and stock status of ONE product the customer asks about. "
                "Pass the customer's own words, in English or Arabic, for example 'Ethiopia "
                "Yirgacheffe 1 kg'. ALWAYS call this before stating any price or whether something "
                "is in stock. Never guess, estimate or invent a price, and never reuse a price from "
                "earlier in the conversation. If handover is true there is no price you may give: "
                "follow the note, and never state a price for that product. vat_included says "
                "whether VAT is already in the price. in_stock null means stock is not known."
            ),
            args_model=QuotePriceArgs,
            risk="read",
            fn=quote_price,
        ),
        Tool(
            name="product_details",
            description=(
                "Get the full details of one product by its exact item code: description, "
                "category, specifications, link, current price and stock. Use it when the customer "
                "wants more than a price, after search_products or quote_price has given you the "
                "code. Only use codes returned by those tools; never invent a code. If found is "
                "false, the code is wrong. If price is null, there is no price you may give."
            ),
            args_model=ProductDetailsArgs,
            risk="read",
            fn=product_details,
        ),
        Tool(
            name="list_categories",
            description=(
                "List the product categories with the number of items in each. Use it when the "
                "customer asks what we sell or wants to browse, then use search_products to look "
                "inside a category."
            ),
            args_model=NoArgs,
            risk="read",
            fn=list_categories,
        ),
    ]


def _distinct(matches: list[CatalogueMatch]) -> list[CatalogueMatch]:
    """The matches with other colours of an earlier product left out, best first."""
    kept: list[CatalogueMatch] = []
    for match in matches:
        if not any(same_product(match.item, earlier.item) for earlier in kept):
            kept.append(match)
    return kept


async def _option(pricing: PricingService, item: CatalogueItem) -> dict[str, Any]:
    price, stock = await _live(pricing, item.code)
    option: dict[str, Any] = {
        "code": item.code,
        "name_en": item.name_en,
        "name_ar": item.name_ar,
        "price": _num(price.price) if price else None,
        "in_stock": stock.in_stock if stock else None,
    }
    if price is not None:
        option.update(currency=price.currency, vat_included=price.vat_included)
    return option


def _short(match: CatalogueMatch) -> dict[str, Any]:
    return {"code": match.item.code, "name_en": match.item.name_en, "name_ar": match.item.name_ar}


def _safe_attributes(item: CatalogueItem) -> dict[str, Any]:
    """The item's details without any that look like a price (a "Trade price" column, say)."""
    return {key: value for key, value in item.attributes.items() if not _PRICE_LIKE.search(str(key))}


async def _live(pricing: PricingService, code: str) -> tuple[ItemPrice | None, StockLevel | None]:
    """Read the price and stock together. A source that is down gives None, not a crash."""
    price, stock = await asyncio.gather(
        pricing.get_price(code), pricing.get_stock(code), return_exceptions=True
    )
    for outcome in (price, stock):
        if isinstance(outcome, BaseException) and not isinstance(outcome, IntegrationError):
            raise outcome
    if isinstance(price, BaseException):
        logger.warning("Price lookup failed for %s: %s", code, price)
        price = None
    if isinstance(stock, BaseException):
        logger.warning("Stock lookup failed for %s: %s", code, stock)
        stock = None
    return price, stock


def _num(value: Decimal | None) -> int | float | None:
    """Prices as plain JSON numbers: 20 stays 20, 12.5 stays 12.5."""
    if value is None:
        return None
    return int(value) if value == value.to_integral_value() else float(value)
