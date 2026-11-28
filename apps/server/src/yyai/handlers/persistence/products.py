"""The product table: the client's items, prices and stock, loaded from their Excel sheet.

It fills the inventory job (`InventoryPort`, brand `sql_products` in the client config), so the catalogue copy
used for search and the prices the agent quotes both come from here. Rows that leave the sheet are switched
off (`active = false`), never deleted.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from sqlalchemy import text

from yyai.core.types import CatalogueItem, ItemPrice, ProductImportReport, ProductRecord, StockLevel
from yyai.handlers.persistence.db import Database

_COLUMNS = (
    "code, name_en, name_ar, category, description, unit, price, currency, vat_included, in_stock, quantity, "
    "url, image_url, attributes"
)


class ProductStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    # --- the table ---------------------------------------------------------

    async def active_products(self) -> list[ProductRecord]:
        async with self._db.engine.connect() as conn:
            rows = (
                await conn.execute(text(f"SELECT {_COLUMNS} FROM products WHERE active ORDER BY code"))
            ).all()
        return [_to_record(row._asdict()) for row in rows]

    async def inactive_codes(self) -> set[str]:
        async with self._db.engine.connect() as conn:
            rows = (await conn.execute(text("SELECT code FROM products WHERE NOT active"))).all()
        return {row.code for row in rows}

    async def apply_import(
        self,
        upserts: Sequence[ProductRecord],
        deactivate: Sequence[str],
        report: ProductImportReport,
        imported_by: str | None,
    ) -> None:
        """Write a checked sheet: upsert its rows, switch off the ones it dropped, log the import. One transaction."""
        async with self._db.engine.begin() as conn:
            for record in upserts:
                await conn.execute(
                    text(
                        f"""
                        INSERT INTO products ({_COLUMNS}, active, updated_at)
                        VALUES (:code, :name_en, :name_ar, :category, :description, :unit, :price, :currency,
                                :vat_included, :in_stock, :quantity, :url, :image_url,
                                CAST(:attributes AS jsonb), true, now())
                        ON CONFLICT (code) DO UPDATE SET
                          name_en = EXCLUDED.name_en, name_ar = EXCLUDED.name_ar, category = EXCLUDED.category,
                          description = EXCLUDED.description, unit = EXCLUDED.unit, price = EXCLUDED.price,
                          currency = EXCLUDED.currency, vat_included = EXCLUDED.vat_included,
                          in_stock = EXCLUDED.in_stock, quantity = EXCLUDED.quantity, url = EXCLUDED.url,
                          image_url = EXCLUDED.image_url, attributes = EXCLUDED.attributes,
                          active = true, updated_at = now()
                        """
                    ),
                    {
                        **record.model_dump(exclude={"attributes"}),
                        "attributes": json.dumps(record.attributes, ensure_ascii=False, default=str),
                    },
                )
            if deactivate:
                await conn.execute(
                    text("UPDATE products SET active = false, updated_at = now() WHERE code = ANY(:codes)"),
                    {"codes": list(deactivate)},
                )
            await conn.execute(
                text(
                    """
                    INSERT INTO product_imports (source, imported_by, rows, added, updated, deactivated, unchanged)
                    VALUES (:source, :by, :rows, :added, :updated, :deactivated, :unchanged)
                    """
                ),
                {
                    "source": report.source,
                    "by": imported_by,
                    "rows": report.rows,
                    "added": len(report.added),
                    "updated": len(report.updated),
                    "deactivated": len(report.deactivated),
                    "unchanged": report.unchanged,
                },
            )

    # --- the inventory job (InventoryPort) ------------------------------------

    async def list_items(self) -> list[CatalogueItem]:
        return [_to_catalogue_item(record) for record in await self.active_products()]

    async def get_prices(self, codes: Sequence[str]) -> dict[str, ItemPrice]:
        rows = await self._active_rows(codes, "price IS NOT NULL")
        return {
            row["code"]: ItemPrice(
                code=row["code"],
                price=row["price"],
                currency=row["currency"],
                vat_included=row["vat_included"],
            )
            for row in rows
        }

    async def get_stock(self, codes: Sequence[str]) -> dict[str, StockLevel]:
        """Only items whose stock the sheet states. An item left out means "unknown": staff must confirm it."""
        rows = await self._active_rows(codes, "(in_stock IS NOT NULL OR quantity IS NOT NULL)")
        return {
            row["code"]: StockLevel(
                code=row["code"],
                in_stock=row["in_stock"] if row["in_stock"] is not None else row["quantity"] > 0,
                quantity=row["quantity"],
            )
            for row in rows
        }

    async def _active_rows(self, codes: Sequence[str], condition: str) -> list[dict[str, Any]]:
        if not codes:
            return []
        async with self._db.engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        f"SELECT {_COLUMNS} FROM products WHERE active AND code = ANY(:codes) AND {condition}"
                    ),
                    {"codes": list(codes)},
                )
            ).all()
        return [row._asdict() for row in rows]


def _to_record(row: dict[str, Any]) -> ProductRecord:
    return ProductRecord.model_validate(row)


def _to_catalogue_item(record: ProductRecord) -> CatalogueItem:
    attributes = dict(record.attributes)
    if record.unit:
        attributes.setdefault("unit", record.unit)  # searchable, and shown by product_details
    return CatalogueItem(
        code=record.code,
        name_en=record.name_en,
        name_ar=record.name_ar,
        category=record.category,
        description=record.description,
        price=record.price,
        currency=record.currency,
        vat_included=record.vat_included,
        url=record.url,
        image_url=record.image_url,
        attributes=attributes,
    )
