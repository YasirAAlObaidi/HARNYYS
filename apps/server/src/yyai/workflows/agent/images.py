"""Which product pictures go out after a reply. Chosen by our code from what the tools showed, never by the model."""

from __future__ import annotations

from decimal import Decimal
from urllib.parse import urlparse

from yyai.core.types import OutboundImage, PresentedProduct

# WhatsApp only takes JPEG and PNG. A link with another file type would fail on Meta's side, so skip it.
_UNSUPPORTED = {".webp", ".gif", ".svg", ".avif", ".bmp", ".tif", ".tiff"}


def pick_images(presented: list[PresentedProduct], max_images: int) -> list[OutboundImage]:
    """At most `max_images` pictures, one per product. Products the customer asked about by name
    (quote_price, product_details) win over the top results of a search."""
    if max_images <= 0:
        return []
    chosen = [p for p in presented if p.specific] or presented
    images: list[OutboundImage] = []
    for product in chosen:
        if not product.image_url or not _sendable(product.image_url):
            continue
        images.append(OutboundImage(url=product.image_url, caption=caption(product)))
        if len(images) == max_images:
            break
    return images


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
