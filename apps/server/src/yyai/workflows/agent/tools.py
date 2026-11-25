"""The product tools the agent can call. All are read-only.

The descriptions below are prompts: the model reads them to decide when and how
to call each tool, so they say what to do and what never to do. Prices and stock
always come from the pricing service (the ERP), never from the model's memory or
from the catalogue copy.
"""

from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from yyai.core.errors import IntegrationError
from yyai.core.types import ItemPrice, RunContext, StockLevel
from yyai.services.catalogue import CatalogueService
from yyai.services.pricing import PricingService
from yyai.workflows.agent.registry import Tool

logger = logging.getLogger(__name__)

# Below this catalogue match score, quote_price warns the model that the item may be the wrong product.
WEAK_MATCH_SCORE = 0.5


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
                "catalogue_price": _num(match.item.price),
                "currency": match.item.currency,
            }
            for match in matches
        ]

    async def quote_price(ctx: RunContext, args: QuotePriceArgs) -> dict[str, Any]:
        matches = await catalogue.search(args.query, 3)
        if not matches:
            return {"found": False}
        best = matches[0].item
        match_score = matches[0].score
        live_price, stock = await _live(pricing, best.code)
        if live_price is not None:
            price, source = _num(live_price.price), "live"
            currency, vat_included = live_price.currency, live_price.vat_included
        elif best.price is not None:
            price, source = _num(best.price), "catalogue"
            currency, vat_included = best.currency, best.vat_included
        else:
            price, source = None, None
            currency, vat_included = best.currency, best.vat_included
        result: dict[str, Any] = {
            "found": True,
            "code": best.code,
            "name_en": best.name_en,
            "name_ar": best.name_ar,
            "price": price,
            "price_source": source,
            "currency": currency,
            "vat_included": vat_included,
            "in_stock": stock.in_stock if stock else None,
            "url": best.url,
            "match_score": round(match_score, 2),
            "other_matches": [{"code": m.item.code, "name_en": m.item.name_en} for m in matches[1:]],
        }
        notes = []
        if match_score < WEAK_MATCH_SCORE:
            # The store keeps loose matches (score from 0.25) so that browsing works. For one quoted price a loose
            # match is usually a different product that shares a word or a weight with what the customer asked for.
            notes.append(
                "Weak match: the product below may not be what the customer asked for. If name_en/name_ar is not "
                "that product, say you could not find it, do not quote this price, and offer other_matches."
            )
        if source != "live":
            notes.append("Live price not available. Do not state a price as final; say staff will confirm it.")
        if notes:
            result["note"] = " ".join(notes)
        return result

    async def product_details(ctx: RunContext, args: ProductDetailsArgs) -> dict[str, Any]:
        item = await catalogue.get(args.code)
        if item is None:
            return {"found": False}
        live_price, stock = await _live(pricing, item.code)
        if live_price is not None:
            price, source = _num(live_price.price), "live"
            currency, vat_included = live_price.currency, live_price.vat_included
        else:
            price, source = _num(item.price), "catalogue" if item.price is not None else None
            currency, vat_included = item.currency, item.vat_included
        return {
            "found": True,
            "code": item.code,
            "name_en": item.name_en,
            "name_ar": item.name_ar,
            "category": item.category,
            "description": item.description,
            "attributes": item.attributes,
            "price": price,
            "price_source": source,
            "currency": currency,
            "vat_included": vat_included,
            "in_stock": stock.in_stock if stock else None,
            "url": item.url,
            "image_url": item.image_url,
        }

    async def list_categories(ctx: RunContext, args: NoArgs) -> list[dict[str, Any]]:
        return [{"category": name, "count": count} for name, count in await catalogue.categories()]

    return [
        Tool(
            name="search_products",
            description=(
                "Search the product catalogue by name, type, brand or use, in English or Arabic. "
                "Use it to browse or when the customer has not named one specific product "
                "(for example 'do you have coffee machines?'). Returns up to `limit` matches with "
                "item codes. catalogue_price is only a rough guide and may be out of date: NEVER "
                "state a price from this tool, call quote_price for any price. An empty list means "
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
                "Pass the customer's own words, in English or Arabic, for example '20 litre water "
                "bottle'. ALWAYS call this before stating any price or whether something is in "
                "stock. Never guess, estimate or invent a price, and never reuse a price from "
                "earlier in the conversation or from search_products. If found is false, say you "
                "could not find that product and ask for more detail. If the customer's words were "
                "vague and other_matches is not empty, mention those alternatives or ask which one "
                "they mean. vat_included says whether VAT is already in the price. If price_source "
                "is not 'live', tell the customer staff will confirm the price."
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
                "false, the code is wrong."
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


async def _live(pricing: PricingService, code: str) -> tuple[ItemPrice | None, StockLevel | None]:
    """Ask the ERP for the live price and stock together. An ERP that is down gives None, not a crash."""
    price, stock = await asyncio.gather(
        pricing.get_price(code), pricing.get_stock(code), return_exceptions=True
    )
    for outcome in (price, stock):
        if isinstance(outcome, BaseException) and not isinstance(outcome, IntegrationError):
            raise outcome
    if isinstance(price, BaseException):
        logger.warning("Live price lookup failed for %s: %s", code, price)
        price = None
    if isinstance(stock, BaseException):
        logger.warning("Live stock lookup failed for %s: %s", code, stock)
        stock = None
    return price, stock


def _num(value: Decimal | None) -> int | float | None:
    """Prices as plain JSON numbers: 20 stays 20, 12.5 stays 12.5."""
    if value is None:
        return None
    return int(value) if value == value.to_integral_value() else float(value)
