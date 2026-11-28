"""Our copy of the client's item catalogue, used for fuzzy product matching.

The ERP stays the source of truth for live prices and stock. This copy exists so
that "قارورة ٢٠ لتر" or "barista machine" can be matched to an exact item code.
See docs/decisions/0010.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from sqlalchemy import text

from yyai.core.types import CatalogueItem, CatalogueMatch
from yyai.handlers.persistence.db import Database

_COLUMNS = "code, name_en, name_ar, category, description, price, currency, vat_included, url, image_url, attributes"


class CatalogueStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def replace_all(self, items: Sequence[tuple[CatalogueItem, str]]) -> int:
        """Store (item, search_text) pairs and drop items no longer in the source. One transaction."""
        async with self._db.engine.begin() as conn:
            for item, search_text in items:
                await conn.execute(
                    text(
                        f"""
                        INSERT INTO catalogue_items ({_COLUMNS}, search_text, synced_at)
                        VALUES (:code, :name_en, :name_ar, :category, :description, :price, :currency,
                                :vat_included, :url, :image_url, CAST(:attributes AS jsonb), :search_text, now())
                        ON CONFLICT (code) DO UPDATE SET
                          name_en = EXCLUDED.name_en, name_ar = EXCLUDED.name_ar, category = EXCLUDED.category,
                          description = EXCLUDED.description, price = EXCLUDED.price, currency = EXCLUDED.currency,
                          vat_included = EXCLUDED.vat_included, url = EXCLUDED.url, image_url = EXCLUDED.image_url,
                          attributes = EXCLUDED.attributes, search_text = EXCLUDED.search_text, synced_at = now()
                        """
                    ),
                    {
                        **item.model_dump(exclude={"attributes"}),
                        "attributes": json.dumps(item.attributes, ensure_ascii=False),
                        "search_text": search_text,
                    },
                )
            codes = [item.code for item, _ in items]
            await conn.execute(text("DELETE FROM catalogue_items WHERE NOT (code = ANY(:codes))"), {"codes": codes})
        return len(items)

    async def search(self, normalized_query: str, limit: int, min_score: float = 0.25) -> list[CatalogueMatch]:
        async with self._db.engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        f"""
                        SELECT {_COLUMNS},
                               GREATEST(word_similarity(:q, search_text),
                                        CASE WHEN search_text LIKE '%' || :q || '%' THEN 1.0 ELSE 0 END) AS score
                        FROM catalogue_items
                        WHERE word_similarity(:q, search_text) >= :min OR search_text LIKE '%' || :q || '%'
                        ORDER BY score DESC, name_en
                        LIMIT :limit
                        """
                    ),
                    {"q": normalized_query, "limit": limit, "min": min_score},
                )
            ).all()
        return [CatalogueMatch(item=_row_to_item(r._asdict()), score=float(r.score)) for r in rows]

    async def get(self, code: str) -> CatalogueItem | None:
        async with self._db.engine.connect() as conn:
            row = (
                await conn.execute(text(f"SELECT {_COLUMNS} FROM catalogue_items WHERE code = :code"), {"code": code})
            ).first()
        return _row_to_item(row._asdict()) if row else None

    async def variants_of(self, keys: Sequence[str]) -> list[CatalogueItem]:
        """Every item that names one of these base products (attributes.base_code or variant_of)."""
        if not keys:
            return []
        async with self._db.engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        f"""
                        SELECT {_COLUMNS} FROM catalogue_items
                        WHERE attributes->>'base_code' = ANY(:keys) OR attributes->>'variant_of' = ANY(:keys)
                        ORDER BY name_en
                        """
                    ),
                    {"keys": list(keys)},
                )
            ).all()
        return [_row_to_item(r._asdict()) for r in rows]

    async def categories(self) -> list[tuple[str, int]]:
        async with self._db.engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT COALESCE(category, 'Other') AS category, count(*) AS n "
                        "FROM catalogue_items GROUP BY 1 ORDER BY 1"
                    )
                )
            ).all()
        return [(r.category, r.n) for r in rows]


def _row_to_item(row: dict) -> CatalogueItem:
    row.pop("score", None)
    return CatalogueItem.model_validate(row)
