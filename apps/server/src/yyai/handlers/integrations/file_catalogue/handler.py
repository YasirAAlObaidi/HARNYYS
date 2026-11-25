"""File catalogue brand: fills the inventory job from a JSON file.

Used for demos and for clients without an ERP yet. Swapping it for Al Ameen is a
one-line change in the client's config (`inventory.brand`), with no other code
changes. File shape: {"currency": "AED", "vat_included": true, "items": [...]},
each item matching CatalogueItem plus optional "in_stock" and "quantity".
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

from yyai.core.errors import IntegrationError
from yyai.core.types import CatalogueItem, ItemPrice, StockLevel


class FileCatalogue:
    def __init__(self, *, path: Path) -> None:
        self._path = path

    def _load(self) -> dict[str, Any]:
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise IntegrationError(f"Cannot read catalogue file {self._path}: {exc}") from exc

    def _raw_items(self) -> list[dict[str, Any]]:
        data = self._load()
        defaults = {"currency": data.get("currency", "AED"), "vat_included": data.get("vat_included", True)}
        return [{**defaults, **item} for item in data.get("items", [])]

    async def list_items(self) -> list[CatalogueItem]:
        return [CatalogueItem.model_validate(_item_fields(raw)) for raw in self._raw_items()]

    async def get_prices(self, codes: Sequence[str]) -> dict[str, ItemPrice]:
        wanted = set(codes)
        prices: dict[str, ItemPrice] = {}
        for raw in self._raw_items():
            if raw.get("code") in wanted and raw.get("price") is not None:
                prices[raw["code"]] = ItemPrice(
                    code=raw["code"],
                    price=Decimal(str(raw["price"])),
                    currency=raw["currency"],
                    vat_included=raw["vat_included"],
                )
        return prices

    async def get_stock(self, codes: Sequence[str]) -> dict[str, StockLevel]:
        wanted = set(codes)
        stock: dict[str, StockLevel] = {}
        for raw in self._raw_items():
            if raw.get("code") in wanted:
                quantity = raw.get("quantity")
                stock[raw["code"]] = StockLevel(
                    code=raw["code"],
                    in_stock=bool(raw.get("in_stock", True)),
                    quantity=Decimal(str(quantity)) if quantity is not None else None,
                )
        return stock


def _item_fields(raw: dict[str, Any]) -> dict[str, Any]:
    allowed = set(CatalogueItem.model_fields)
    return {key: value for key, value in raw.items() if key in allowed}
