"""Live prices and stock. The ERP (through the inventory job) is the source of truth."""

from __future__ import annotations

from yyai.core.types import ItemPrice, StockLevel
from yyai.handlers.ports import InventoryPort


class PricingService:
    def __init__(self, inventory: InventoryPort) -> None:
        self._inventory = inventory

    async def get_price(self, code: str) -> ItemPrice | None:
        return (await self._inventory.get_prices([code])).get(code)

    async def get_stock(self, code: str) -> StockLevel | None:
        return (await self._inventory.get_stock([code])).get(code)
