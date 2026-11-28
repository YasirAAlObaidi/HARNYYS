"""Which product pictures go out after a reply. Chosen by our code from what the tools showed, never by the model."""

from __future__ import annotations

import math
import re
from decimal import Decimal
from urllib.parse import urlparse

from yyai.core.text import normalize_for_search
from yyai.core.types import OutboundImage, PresentedProduct

# WhatsApp only takes JPEG and PNG. A link with another file type would fail on Meta's side, so skip it.
_UNSUPPORTED = {".webp", ".gif", ".svg", ".avif", ".bmp", ".tif", ".tiff"}


_TOKEN = re.compile(r"[^\W_]+")
_BRACKET = re.compile(r"\([^()]*\)")
# Words every product name has: they do not tell one product from another.
_GENERIC = frozenset(
    {"coffee", "grinder", "machine", "maker", "the", "and", "for", "with", "kg", "قهوه", "مطحنه", "ماكينه", "محمصه", "خضراء"}
)


def pick_images(
    presented: list[PresentedProduct], max_images: int, reply: str | None = None
) -> list[OutboundImage]:
    """At most `max_images` pictures, one per product. Products the customer asked about by name
    (quote_price, product_details) win over the top results of a search.

    When the reply text is given, a product that only appeared in a search gets a picture only if the reply
    names it. A search run for a greeting or a thank-you shows the model products, but the customer should not
    get photos for them. A product the customer named (quote_price, product_details) always qualifies."""
    if max_images <= 0:
        return []
    if reply is not None:
        presented = [p for p in presented if p.specific or mentioned(p, reply)]
    chosen = [p for p in presented if p.specific] or presented
    images: list[OutboundImage] = []
    for product in chosen:
        if not product.image_url or not _sendable(product.image_url):
            continue
        images.append(OutboundImage(url=product.image_url, caption=caption(product)))
        if len(images) == max_images:
            break
    return images


def mentioned(product: PresentedProduct, reply: str) -> bool:
    """Whether the reply names this product: its model numbers, and at least half of its distinctive words."""
    reply_words = set(_TOKEN.findall(normalize_for_search(reply)))
    for name in (product.name, product.name_ar):
        if not name:
            continue
        words = _TOKEN.findall(normalize_for_search(_BRACKET.sub(" ", name)))
        distinctive = [w for w in words if w not in _GENERIC] or words
        if not distinctive:
            continue
        numbered = [w for w in distinctive if any(c.isdigit() for c in w)]
        found = [w for w in distinctive if w in reply_words]
        if all(w in reply_words for w in numbered) and len(found) >= math.ceil(len(distinctive) / 2):
            return True
    return False


def caption(product: PresentedProduct) -> str:
    lines = [f"*{product.name.replace('*', '')}*"]
    if product.price is not None:
        lines.append(f"{'from ' if product.price_from else ''}{product.currency} {_money(product.price)}")
    return "\n".join(lines)


def _money(value: Decimal) -> str:
    return f"{value:,.0f}" if value == value.to_integral_value() else f"{value:,.2f}"


def _sendable(url: str) -> bool:
    path = urlparse(url).path.lower()
    return url.startswith(("http://", "https://")) and not any(path.endswith(ext) for ext in _UNSUPPORTED)
