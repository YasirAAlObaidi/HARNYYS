"""The catalogue: our searchable copy of the client's items.

The inventory job (the ERP, or a file for demos) is the source. This service
copies it into our database with normalised search text so that Arabic and
English queries can be matched to an exact item code. Live prices and stock are
the pricing service's job, not this one's.
"""

from __future__ import annotations

import logging

from yyai.core.text import normalize_for_search
from yyai.core.types import CatalogueItem, CatalogueMatch, ProductGroup
from yyai.core.variants import base_key, explicit_key, group_matches
from yyai.handlers.persistence.catalogue import CatalogueStore
from yyai.handlers.ports import InventoryPort

logger = logging.getLogger(__name__)

# The store cuts its answer at `limit`, and many items can tie at a perfect score, so ask for more and
# choose here. Otherwise the item whose NAME matches could be cut off by one whose description only mentions it.
CANDIDATES_PER_RESULT = 5
MIN_CANDIDATES = 25


class CatalogueService:
    def __init__(self, inventory: InventoryPort, store: CatalogueStore) -> None:
        self._inventory = inventory
        self._store = store

    async def sync(self) -> int:
        """Copy every item from the inventory job into our database. Returns how many were stored."""
        items = await self._inventory.list_items()
        if not items:
            # An empty answer is far more likely to be a broken export than a client with no products.
            # Replacing the copy with nothing would silently take the agent's catalogue away.
            logger.warning("Inventory returned no items; keeping the existing catalogue copy")
            return 0
        pairs = [(item, _search_text(item)) for item in items]
        return await self._store.replace_all(pairs)

    async def search(self, query: str, limit: int) -> list[CatalogueMatch]:
        return (await self._ranked(query, limit))[:limit]

    async def _ranked(self, query: str, limit: int) -> list[CatalogueMatch]:
        normalized = normalize_for_search(query)
        if not normalized:
            return []
        candidates = await self._store.search(normalized, max(limit * CANDIDATES_PER_RESULT, MIN_CANDIDATES))
        # "moka pot" means the moka pot, not the coffee whose description says it is ground for a moka pot.
        # An item whose name contains the query always scores 1.0, so this only reorders ties; the sort is stable.
        candidates.sort(key=lambda match: not _name_contains(match.item, normalized))
        return candidates

    async def search_products(self, query: str, limit: int) -> list[ProductGroup]:
        """Matches grouped by base product: a grinder sold in three colours is one result, with all its variants."""
        groups = group_matches(await self._ranked(query, limit))[:limit]
        await self._complete(groups)
        return groups

    async def group_for(self, item: CatalogueItem) -> ProductGroup:
        """The base product an item belongs to, with all its variants."""
        group = group_matches([CatalogueMatch(item=item, score=1.0)])[0]
        await self._complete([group])
        return group

    async def group_by_key(self, key: str) -> ProductGroup | None:
        """A base product by its key (what search_products returns as `code` for a product with options)."""
        siblings = await self._store.variants_of([key])
        if not siblings:
            return None
        group = group_matches([CatalogueMatch(item=siblings[0], score=1.0)])[0]
        group.items = siblings
        return group

    async def _complete(self, groups: list[ProductGroup]) -> None:
        """Search only returns the variants that matched; fill in the rest so the options are complete."""
        keys = [g.base_key for g in groups if any(explicit_key(i) for i in g.items)]
        by_key: dict[str, list[CatalogueItem]] = {}
        for item in await self._store.variants_of(keys):
            by_key.setdefault(base_key(item), []).append(item)
        for group in groups:
            if group.base_key in by_key:
                group.items = by_key[group.base_key]

    async def get(self, code: str) -> CatalogueItem | None:
        return await self._store.get(code)

    async def categories(self) -> list[tuple[str, int]]:
        return await self._store.categories()


def _name_contains(item: CatalogueItem, normalized_query: str) -> bool:
    names = (item.name_en, item.name_ar)
    return any(name and normalized_query in normalize_for_search(name) for name in names)


def _search_text(item: CatalogueItem) -> str:
    parts = [item.name_en, item.name_ar, item.category, item.description]
    parts.extend(value for value in item.attributes.values() if isinstance(value, str))
    return normalize_for_search(" ".join(part for part in parts if part))
