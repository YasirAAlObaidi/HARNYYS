"""The catalogue: our searchable copy of the client's items.

The inventory job (the ERP, or a file for demos) is the source. This service
copies it into our database with normalised search text so that Arabic and
English queries can be matched to an exact item code. Live prices and stock are
the pricing service's job, not this one's.
"""

from __future__ import annotations

import logging
import re

from yyai.core.text import normalize_for_search
from yyai.core.types import CatalogueItem, CatalogueMatch
from yyai.handlers.persistence.catalogue import CatalogueStore
from yyai.handlers.ports import InventoryPort

logger = logging.getLogger(__name__)

# The store cuts its answer at `limit`, and many items can tie at a perfect score, so ask for more and
# choose here. Otherwise the item whose NAME matches could be cut off by one whose description only mentions it.
CANDIDATES_PER_RESULT = 5
MIN_CANDIDATES = 25

# Model numbers and pack sizes ("CBR 301", "CBR-1200", "500 g") decide which product the customer means, but
# trigram similarity treats "300" and "301" as nearly the same. A number counts when it has at least this many
# digits: quantities ("2 pots") and small specs ("15 bar") are too often about the order, not the product.
MODEL_NUMBER_MIN_DIGITS = 3
# Score multiplier for an item whose name carries model numbers, none of which the customer gave. It pushes a
# look-alike well below tools.WEAK_MATCH_SCORE, so it is offered as an alternative but never quoted.
NUMBER_MISMATCH_FACTOR = 0.4
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


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
        normalized = normalize_for_search(query)
        if not normalized:
            return []
        candidates = await self._store.search(normalized, max(limit * CANDIDATES_PER_RESULT, MIN_CANDIDATES))
        wanted = model_numbers(normalized)
        ranked: list[tuple[CatalogueMatch, bool, bool]] = []
        for match in candidates:
            agreement = number_agreement(wanted, _name_numbers(match.item))
            if agreement is False:
                match = match.model_copy(update={"score": match.score * NUMBER_MISMATCH_FACTOR})
            ranked.append((match, agreement is True, _name_contains(match.item, normalized)))
        # Best score first. Among equal scores, an item with the customer's model number comes first, then one
        # whose NAME contains the query: "moka pot" means the moka pot, not the coffee whose description says it
        # is ground for a moka pot. The sort is stable, so the store's order breaks any remaining ties.
        ranked.sort(key=lambda entry: (-entry[0].score, not entry[1], not entry[2]))
        return [match for match, _, _ in ranked[:limit]]

    async def get(self, code: str) -> CatalogueItem | None:
        return await self._store.get(code)

    async def categories(self) -> list[tuple[str, int]]:
        return await self._store.categories()


def model_numbers(normalized_text: str) -> set[str]:
    """The whole numbers in a text that are long enough to name a model or a pack size.

    "cbr-1200" gives {"1200"}, "1,000 g" gives {"1000"}. Decimals ("2.5 kg") and short numbers are left out.
    """
    numbers = set()
    for raw in _NUMBER.findall(normalized_text):
        if "." in raw:
            continue
        digits = raw.replace(",", "")
        if len(digits) >= MODEL_NUMBER_MIN_DIGITS:
            numbers.add(digits)
    return numbers


def number_agreement(wanted: set[str], offered: set[str]) -> bool | None:
    """True if the item carries one of the customer's model numbers, False if it carries only other ones,
    None if either side names none (then numbers say nothing about the match)."""
    if not wanted or not offered:
        return None
    return bool(wanted & offered)


def _name_numbers(item: CatalogueItem) -> set[str]:
    names = " ".join(name for name in (item.name_en, item.name_ar) if name)
    return model_numbers(normalize_for_search(names))


def _name_contains(item: CatalogueItem, normalized_query: str) -> bool:
    names = (item.name_en, item.name_ar)
    return any(name and normalized_query in normalize_for_search(name) for name in names)


def _search_text(item: CatalogueItem) -> str:
    parts = [item.name_en, item.name_ar, item.category, item.description]
    parts.extend(value for value in item.attributes.values() if isinstance(value, str))
    return normalize_for_search(" ".join(part for part in parts if part))
