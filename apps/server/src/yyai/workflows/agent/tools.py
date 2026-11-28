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
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from yyai.core.errors import IntegrationError
from yyai.core.types import CatalogueItem, ItemPrice, PresentedProduct, ProductGroup, RunContext, StockLevel
from yyai.core.variants import chosen_variants, variant_label
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
UNKNOWN_CODE_NOTE = "Unknown code. Only use codes returned by search_products or quote_price."
CHOICE_NOTE = (
    "The customer has not said which option they want. If this is a first, general question, give the product "
    "name and the price (say 'from' when price_from is true) and do NOT list the options. Once the customer has "
    "picked this product, list the options (label) and ask which one, then call quote_price again with the "
    "product name and the chosen option."
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
        groups = await catalogue.search_products(args.query, args.limit)
        results = []
        for group in groups:
            # Search finds products; it never carries a price. Prices come from quote_price (the product table).
            _present(ctx, group, await _priced_items(pricing, group.items), specific=False)
            results.append(
                {
                    # With options, `code` is the product's key: pass it to product_details to see the options.
                    "code": _code(group),
                    "name_en": group.name_en,
                    "name_ar": group.name_ar,
                    "category": group.category,
                    "has_variants": group.has_variants,
                }
            )
        return results

    async def quote_price(ctx: RunContext, args: QuotePriceArgs) -> dict[str, Any]:
        groups = await catalogue.search_products(args.query, 8)
        if not groups:
            return {"found": False, "handover": False, "note": NOT_FOUND_NOTE}
        group, score = groups[0], groups[0].score
        # Other colours of the same product (named alike, no shared base code) are not other products.
        groups = [group] + [g for g in groups[1:] if not same_product(g.items[0], group.items[0])]
        others = [_short(g) for g in groups[1:3]]
        if score < WEAK_MATCH_SCORE:
            # The store keeps loose matches (score from 0.25) so that browsing works. For one quoted price a loose
            # match is usually a different product that shares a word or a weight with what the customer asked for.
            # No handover yet: the customer is asked which product they mean first.
            return {
                "found": True,
                "code": _code(group),
                "name_en": group.name_en,
                "name_ar": group.name_ar,
                "match_score": round(score, 2),
                "clear_match": False,
                "other_matches": others,
                "handover": False,
                "note": UNCLEAR_NOTE,
            }
        rivals = [g for g in groups[1:] if g.score >= max(score - TIE_MARGIN, WEAK_MATCH_SCORE)][:2]
        if rivals:
            options = []
            for rival in [group, *rivals]:
                priced = await _priced_items(pricing, rival.items)
                options.append({"code": _code(rival), "name_en": rival.name_en, "name_ar": rival.name_ar, **_summary(priced)})
            return {"found": True, "clear_match": False, "handover": False, "options": options, "note": AMBIGUOUS_NOTE}
        if group.has_variants:
            named = chosen_variants(group.items, args.query)
            if len(named) == 1:
                return await _quote_item(ctx, pricing, group, named[0], score, others)
            priced = await _priced_items(pricing, named or group.items)
            result: dict[str, Any] = {
                "found": True,
                "needs_choice": True,
                "clear_match": True,
                "code": group.base_key,
                "name_en": group.name_en,
                "name_ar": group.name_ar,
                **_summary(priced),
                "options": [_option(entry) for entry in priced],
                "match_score": round(score, 2),
                "other_matches": others,
                "handover": False,
                "note": CHOICE_NOTE,
            }
            _present(ctx, group, priced, specific=True)
            if all(entry.price is None for entry in priced):
                return {**result, "handover": True, "handover_reason": "missing_price", "note": MISSING_PRICE_NOTE}
            return result
        return await _quote_item(ctx, pricing, group, group.items[0], score, others)

    async def product_details(ctx: RunContext, args: ProductDetailsArgs) -> dict[str, Any]:
        item = await catalogue.get(args.code)
        if item is None:
            group = await catalogue.group_by_key(args.code)
            if group is None:
                return {"found": False, "note": UNKNOWN_CODE_NOTE}
            if group.has_variants:
                return await _base_details(ctx, pricing, group)
            item = group.items[0]
        group = await catalogue.group_for(item)
        priced = await _priced_items(pricing, [item])
        entry = priced[0]
        _present(ctx, group, priced, specific=True)
        result: dict[str, Any] = {
            "found": True,
            "code": item.code,
            "name_en": item.name_en,
            "name_ar": item.name_ar,
            "category": item.category,
            "description": item.description,
            "attributes": _safe_attributes(item),
            "price": _num(entry.price),
            "in_stock": entry.in_stock,
            "url": item.url,
            "image_url": item.image_url,
        }
        notes = []
        if entry.price is not None:
            result.update(currency=entry.currency, vat_included=entry.vat_included)
        else:
            notes.append(MISSING_PRICE_NOTE)
        if entry.in_stock is None:
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
                "(for example 'how much is a coffee grinder?'). Returns up to `limit` PRODUCTS, one entry per "
                "product, with item codes and NO prices: call quote_price for any price. In a general listing, name "
                "each product once. NEVER list or mention colours, sizes or other options in a listing, even if "
                "you know them. Once the customer has picked a product that comes in options, call "
                "product_details with its code to get them. "
                "An empty list means nothing matched: try simpler words or the other language before telling "
                "the customer we do not have it."
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
                "Yirgacheffe 1 kg', and include the option they chose (colour, size) when they named one. "
                "ALWAYS call this before stating any price or whether something is in stock. Never guess, "
                "estimate or invent a price, and never reuse a price from earlier in the conversation. If "
                "handover is true there is no price you may give: follow the note, and never state a price "
                "for that product. If needs_choice is true the product comes in options and the customer has "
                "not chosen: follow the note in the result. vat_included says whether VAT is already in the "
                "price. in_stock null means stock is not known."
            ),
            args_model=QuotePriceArgs,
            risk="read",
            fn=quote_price,
        ),
        Tool(
            name="product_details",
            description=(
                "Get the full details of one product by its exact item code: description, category, "
                "specifications, link, current price and stock. Use it when the customer wants more than a "
                "price, or has picked a product that has_variants: the result then has `options` (label, "
                "price, in_stock): tell the customer these options and ask which one they want, then call "
                "quote_price for the one they choose. Only use codes returned by search_products or "
                "quote_price; never invent a code. If found is false, the code is wrong. If price is null, "
                "there is no price you may give."
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


def _code(group: ProductGroup) -> str:
    return group.items[0].code if not group.has_variants else group.base_key


def _short(group: ProductGroup) -> dict[str, Any]:
    return {"code": _code(group), "name_en": group.name_en, "name_ar": group.name_ar}


def _safe_attributes(item: CatalogueItem) -> dict[str, Any]:
    """The item's details without internal fields or any that look like a price (a "Trade price" column)."""
    return {
        key: value
        for key, value in item.attributes.items()
        if key not in _INTERNAL_ATTRIBUTES and not _PRICE_LIKE.search(str(key))
    }


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


# --- grouped products, prices and the list of pictures to send ------------------------------------------

_INTERNAL_ATTRIBUTES = {"site_product_id", "site_categories", "name_ar_source", "variant_of", "base_code", "variant_label"}
_OPTION_ATTRIBUTES = {"color", "colors", "groups", "group"}


@dataclass
class _Priced:
    item: CatalogueItem
    price: Decimal | None
    currency: str
    vat_included: bool
    in_stock: bool | None


async def _priced_items(pricing: PricingService, items: list[CatalogueItem]) -> list[_Priced]:
    """Price and stock for each item from the pricing service (the product table). The catalogue copy is never a
    price source: with no table price the price is None."""
    lives = await asyncio.gather(*(_live(pricing, item.code) for item in items))
    priced = []
    for item, (price, stock) in zip(items, lives, strict=True):
        currency = price.currency if price else item.currency
        vat = price.vat_included if price else item.vat_included
        priced.append(
            _Priced(item, price.price if price else None, currency, vat, stock.in_stock if stock else None)
        )
    return priced


def _summary(priced: list[_Priced]) -> dict[str, Any]:
    """One price for the whole product: the lowest, and price_from=true when the options cost different amounts."""
    prices = [p.price for p in priced if p.price is not None]
    stocks = [p.in_stock for p in priced if p.in_stock is not None]
    return {
        "price": _num(min(prices)) if prices else None,
        "price_from": len(set(prices)) > 1,
        "currency": priced[0].currency,
        "vat_included": priced[0].vat_included,
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
    _present(ctx, group, priced, specific=True)
    result: dict[str, Any] = {
        "found": True,
        "code": best.code,
        "name_en": best.name_en,
        "name_ar": best.name_ar,
        "url": best.url,
        "match_score": round(match_score, 2),
        "clear_match": True,
        "other_matches": others,
        "in_stock": entry.in_stock,
    }
    if entry.price is None:
        # The product is clear but has no price: only staff can answer, so the turn hands over (see turn.py).
        return {**result, "price": None, "handover": True, "handover_reason": "missing_price", "note": MISSING_PRICE_NOTE}
    result.update(price=_num(entry.price), currency=entry.currency, vat_included=entry.vat_included, handover=False)
    if entry.in_stock is None:
        result["note"] = UNKNOWN_STOCK_NOTE
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
        "attributes": {k: v for k, v in _safe_attributes(first).items() if k not in _OPTION_ATTRIBUTES},
        **_summary(priced),
        "has_variants": True,
        "options": [_option(entry) for entry in priced],
        "image_url": first.image_url,
        "note": (
            "The customer has now picked this product: tell them the options (label) and ask which one they want. "
            "Quote an exact option with quote_price only after they choose."
        ),
    }
