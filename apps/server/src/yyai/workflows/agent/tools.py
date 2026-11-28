"""The product tools the agent can call. All are read-only.

The descriptions below are prompts: the model reads them to decide when and how
to call each tool, so they say what to do and what never to do. Prices and stock
always come from the pricing service (the ERP), never from the model's memory or
from the catalogue copy.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from yyai.core.errors import IntegrationError
from yyai.core.types import CatalogueItem, ItemPrice, PresentedProduct, ProductGroup, RunContext, StockLevel
from yyai.core.variants import chosen_variants, variant_label
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
        groups = await catalogue.search_products(args.query, args.limit)
        results = []
        for group in groups:
            priced = await _priced_items(pricing, group.items)
            summary = _summary(group, priced)
            _present(ctx, group, priced, specific=False)
            results.append(
                {
                    # With options, `code` is the product's key: pass it to product_details to see the options.
                    "code": group.items[0].code if not group.has_variants else group.base_key,
                    "name_en": group.name_en,
                    "name_ar": group.name_ar,
                    "category": group.category,
                    **summary,
                    "has_variants": group.has_variants,
                }
            )
        return results

    async def quote_price(ctx: RunContext, args: QuotePriceArgs) -> dict[str, Any]:
        groups = await catalogue.search_products(args.query, 3)
        if not groups:
            return {"found": False}
        group = groups[0]
        match_score = group.score
        others = [
            {"code": g.items[0].code if not g.has_variants else g.base_key, "name_en": g.name_en}
            for g in groups[1:]
        ]
        if group.has_variants:
            named = chosen_variants(group.items, args.query)
            if len(named) == 1:
                return await _quote_item(ctx, pricing, group, named[0], match_score, others)
            options = named or group.items
            priced = await _priced_items(pricing, options)
            result = {
                "found": True,
                "needs_choice": True,
                "code": group.base_key,
                "name_en": group.name_en,
                "name_ar": group.name_ar,
                **_summary(group, priced),
                "options": [_option(entry) for entry in priced],
                "match_score": round(match_score, 2),
                "other_matches": others,
                "note": (
                    "The customer has not said which option they want. If this is a first, general question, "
                    "give the product name and the price (say 'from' when price_from is true) and do NOT list "
                    "the options. Once the customer has picked this product, list the options (label) and ask "
                    "which one, then call quote_price again with the product name and the chosen option."
                ),
            }
            if match_score >= WEAK_MATCH_SCORE:
                _present(ctx, group, priced, specific=True)
            return result
        return await _quote_item(ctx, pricing, group, group.items[0], match_score, others)

    async def product_details(ctx: RunContext, args: ProductDetailsArgs) -> dict[str, Any]:
        item = await catalogue.get(args.code)
        if item is None:
            group = await catalogue.group_by_key(args.code)
            if group is None:
                return {"found": False}
            if group.has_variants:
                return await _base_details(ctx, pricing, group)
            item = group.items[0]
        group = await catalogue.group_for(item)
        priced = await _priced_items(pricing, [item])
        entry = priced[0]
        _present(ctx, group, priced, specific=True)
        attributes = {k: v for k, v in item.attributes.items() if k not in _INTERNAL_ATTRIBUTES}
        return {
            "found": True,
            "code": item.code,
            "name_en": item.name_en,
            "name_ar": item.name_ar,
            "category": item.category,
            "description": item.description,
            "attributes": attributes,
            "price": _num(entry.price),
            "price_source": entry.source,
            "currency": entry.currency,
            "vat_included": entry.vat_included,
            "in_stock": entry.in_stock,
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
                "(for example 'how much is a coffee grinder?'). Returns up to `limit` PRODUCTS, one entry per "
                "product, with price (the lowest option's price; price_from is true when the options cost "
                "different amounts, so say 'from AED X'), in_stock and has_variants. In a general listing, "
                "name each product once with its price. NEVER list or mention colours, sizes or other "
                "options in a listing, even if you know them. If has_variants is true, the options are "
                "offered only AFTER the customer has picked that product: then call product_details with "
                "its code to get them. An empty list means nothing matched: try simpler words or the other "
                "language before telling the customer we do not have it."
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
                "bottle', and include the option they chose (colour, size) when they named one. ALWAYS call "
                "this before stating the price of a specific product or whether it is in stock. Never guess, "
                "estimate or invent a price, and never reuse a price from earlier in the conversation. If "
                "found is false, say you could not find that product and ask for more detail. If the words "
                "were vague and other_matches is not empty, mention those alternatives or ask which one "
                "they mean. If needs_choice is true the product comes in options and the customer has not "
                "chosen: follow the note in the result (do not list options in a general listing; once they "
                "picked the product, list the options and ask which one). vat_included says whether VAT is "
                "already in the price. If price_source is not 'live', tell the customer staff will confirm "
                "the price."
            ),
            args_model=QuotePriceArgs,
            risk="read",
            fn=quote_price,
        ),
        Tool(
            name="product_details",
            description=(
                "Get the full details of one product by its code: description, category, specifications, "
                "link, current price and stock. Use it when the customer wants more than a price, or has "
                "picked a product that has_variants: the result then has `options` (label, price, "
                "in_stock): tell the customer these options and ask which one they want, then call "
                "quote_price for the one they choose. Only use codes returned by search_products or "
                "quote_price; never invent a code. If found is false, the code is wrong."
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


# --- grouped products, prices and the list of pictures to send ------------------------------------------

_INTERNAL_ATTRIBUTES = {"site_product_id", "site_categories", "name_ar_source", "variant_of", "base_code", "variant_label"}
_OPTION_ATTRIBUTES = {"color", "colors", "groups", "group"}


@dataclass
class _Priced:
    item: CatalogueItem
    price: Decimal | None
    source: str | None
    currency: str
    vat_included: bool
    in_stock: bool | None


async def _priced_items(pricing: PricingService, items: list[CatalogueItem]) -> list[_Priced]:
    """Live price and stock for each item; the catalogue copy only where the ERP gave nothing."""
    lives = await asyncio.gather(*(_live(pricing, item.code) for item in items))
    priced = []
    for item, (live_price, stock) in zip(items, lives, strict=True):
        if live_price is not None:
            price, source, currency, vat = live_price.price, "live", live_price.currency, live_price.vat_included
        else:
            price = item.price
            source = "catalogue" if item.price is not None else None
            currency, vat = item.currency, item.vat_included
        priced.append(_Priced(item, price, source, currency, vat, stock.in_stock if stock else None))
    return priced


def _summary(group: ProductGroup, priced: list[_Priced]) -> dict[str, Any]:
    """One price for the whole product: the lowest, and price_from=true when the options cost different amounts."""
    prices = [p.price for p in priced if p.price is not None]
    first = priced[0]
    stocks = [p.in_stock for p in priced if p.in_stock is not None]
    live = bool(priced) and all(p.source == "live" for p in priced if p.price is not None) and bool(prices)
    return {
        "price": _num(min(prices)) if prices else None,
        "price_from": len(set(prices)) > 1,
        "price_source": ("live" if live else "catalogue") if prices else None,
        "currency": first.currency,
        "vat_included": first.vat_included,
        "in_stock": any(stocks) if stocks else None,
    }


def _option(entry: _Priced) -> dict[str, Any]:
    return {
        "code": entry.item.code,
        "label": variant_label(entry.item) or entry.item.name_en,
        "price": _num(entry.price),
        "in_stock": entry.in_stock,
    }


def _present(ctx: RunContext, group: ProductGroup, priced: list[_Priced], *, specific: bool) -> None:
    """Remember that this product was shown, so our code can queue its picture after the reply.
    A base product uses its first variant's picture; one chosen variant uses its own."""
    prices = [p.price for p in priced if p.price is not None]
    image = next((p.item.image_url for p in priced if p.item.image_url), None)
    name = priced[0].item.name_en if len(priced) == 1 else group.name_en  # one chosen variant keeps its own name
    entry = PresentedProduct(
        key=group.base_key,
        name=name,
        price=min(prices) if prices else None,
        price_from=len(set(prices)) > 1,
        currency=priced[0].currency,
        image_url=image,
        specific=specific,
    )
    ctx.presented[:] = [p for p in ctx.presented if p.key != entry.key] + [entry]


async def _quote_item(
    ctx: RunContext,
    pricing: PricingService,
    group: ProductGroup,
    best: CatalogueItem,
    match_score: float,
    others: list[dict[str, Any]],
) -> dict[str, Any]:
    priced = await _priced_items(pricing, [best])
    entry = priced[0]
    result: dict[str, Any] = {
        "found": True,
        "code": best.code,
        "name_en": best.name_en,
        "name_ar": best.name_ar,
        "price": _num(entry.price),
        "price_source": entry.source,
        "currency": entry.currency,
        "vat_included": entry.vat_included,
        "in_stock": entry.in_stock,
        "url": best.url,
        "match_score": round(match_score, 2),
        "other_matches": others,
    }
    notes = []
    if match_score < WEAK_MATCH_SCORE:
        # The store keeps loose matches (score from 0.25) so that browsing works. For one quoted price a loose
        # match is usually a different product that shares a word or a weight with what the customer asked for.
        notes.append(
            "Weak match: the product below may not be what the customer asked for. If name_en/name_ar is not "
            "that product, say you could not find it, do not quote this price, and offer other_matches."
        )
    else:
        _present(ctx, group, priced, specific=True)
    if entry.source != "live":
        notes.append("Live price not available. Do not state a price as final; say staff will confirm it.")
    if notes:
        result["note"] = " ".join(notes)
    return result


async def _base_details(ctx: RunContext, pricing: PricingService, group: ProductGroup) -> dict[str, Any]:
    """Details of a product that comes in options: shared facts, the lowest price, and the options to choose from."""
    priced = await _priced_items(pricing, group.items)
    first = group.items[0]
    _present(ctx, group, priced, specific=True)
    return {
        "found": True,
        "code": group.base_key,
        "name_en": group.name_en,
        "name_ar": group.name_ar,
        "category": group.category,
        "description": first.description,
        "attributes": {
            k: v for k, v in first.attributes.items() if k not in _INTERNAL_ATTRIBUTES | _OPTION_ATTRIBUTES
        },
        **_summary(group, priced),
        "has_variants": True,
        "options": [_option(entry) for entry in priced],
        "image_url": first.image_url,
        "note": (
            "The customer has now picked this product: tell them the options (label) and ask which one they want. "
            "Quote an exact option with quote_price only after they choose."
        ),
    }
