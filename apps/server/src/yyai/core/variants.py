"""Variants: one catalogue item per colour or size, grouped under a base product.

Pure functions, no I/O. The grouping uses generic signals so it works for any inventory source:
`attributes.base_code` (explicit, preferred) or `attributes.variant_of` names the base product, and
`attributes.variant_label` names the option. Without a label, a trailing "(Red)" in the item name is
the label, then the colour/groups attributes.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from yyai.core.text import normalize_for_search
from yyai.core.types import CatalogueItem, CatalogueMatch, ProductGroup

_TRAILING_PAREN = re.compile(r"\s*\(([^()]*)\)\s*$")


def explicit_key(item: CatalogueItem) -> str | None:
    for name in ("base_code", "variant_of"):
        value = item.attributes.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def base_key(item: CatalogueItem) -> str:
    return explicit_key(item) or item.code


def base_name(name: str | None, item: CatalogueItem) -> str | None:
    """The product name without the option in brackets, but only for items that are variants."""
    if name is None or explicit_key(item) is None:
        return name
    return _TRAILING_PAREN.sub("", name).strip() or name


def variant_label(item: CatalogueItem) -> str | None:
    label = item.attributes.get("variant_label")
    if isinstance(label, str) and label.strip():
        return label.strip()
    if explicit_key(item) is None:
        return None
    match = _TRAILING_PAREN.search(item.name_en)
    if match and match.group(1).strip():
        return match.group(1).strip()
    parts = [str(item.attributes[k]) for k in ("color", "groups", "group") if item.attributes.get(k)]
    return ", ".join(parts) or None


def group_matches(matches: Iterable[CatalogueMatch]) -> list[ProductGroup]:
    """Group ranked matches by base product, keeping the order of the best match in each group."""
    groups: dict[str, ProductGroup] = {}
    for match in matches:
        item = match.item
        key = base_key(item)
        group = groups.get(key)
        if group is None:
            groups[key] = ProductGroup(
                base_key=key,
                name_en=base_name(item.name_en, item) or item.name_en,
                name_ar=base_name(item.name_ar, item),
                category=item.category,
                items=[item],
                score=match.score,
            )
        elif all(existing.code != item.code for existing in group.items):
            group.items.append(item)
    return list(groups.values())


def _tokens(text: str) -> set[str]:
    """Comparable words: no punctuation, no plural "s" ("2 groups" ~ "1 Group") and no Arabic "al-" prefix."""
    words = set()
    for word in re.findall(r"\w+", normalize_for_search(text)):
        if word.startswith("ال") and len(word) > 4:
            word = word[2:]
        words.add(word[:-1] if len(word) > 3 and word.endswith("s") else word)
    return words


def chosen_variants(items: list[CatalogueItem], query: str) -> list[CatalogueItem]:
    """The variants the customer's words point at: those whose whole label is in the query, otherwise
    those sharing the most label words with it (so "black" narrows "Black, 2 Groups" and "Black, 3 Groups")."""
    wanted = _tokens(query)
    scored = []
    for item in items:
        labels = [variant_label(item)]
        if explicit_key(item) is not None and item.name_ar:
            arabic = _TRAILING_PAREN.search(item.name_ar)
            labels.append(arabic.group(1) if arabic else None)
        best = (0, False)
        for label in labels:
            words = _tokens(label) if label else set()
            if words:
                best = max(best, (len(words & wanted), words <= wanted))
        scored.append((best, item))
    full = [item for (overlap, whole), item in scored if whole and overlap]
    if full:
        return full
    top = max((best[0] for best, _ in scored), default=0)
    return [item for best, item in scored if top and best[0] == top]
