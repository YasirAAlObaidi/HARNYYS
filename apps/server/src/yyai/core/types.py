"""Data types shared by every layer.

These are our own shapes. Vendor formats (Meta's JSON, Al Ameen's rows, a model
server's response) are converted into these inside the handlers and never leak
upward.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

# --- Messaging -------------------------------------------------------------


class MediaRef(BaseModel):
    kind: Literal["image", "audio", "video", "document", "sticker", "other"]
    provider_id: str
    mime_type: str | None = None
    caption: str | None = None


class InboundMessage(BaseModel):
    channel: str
    source_id: str = Field(description="The provider's own message ID, used to drop duplicates")
    sender_id: str = Field(description="The provider's ID for the customer (phone number or user ID)")
    sender_name: str | None = None
    text: str
    received_at: datetime
    media: list[MediaRef] = []


class SendResult(BaseModel):
    provider_message_id: str


# --- Catalogue and inventory ------------------------------------------------


class CatalogueItem(BaseModel):
    code: str
    name_en: str
    name_ar: str | None = None
    category: str | None = None
    description: str | None = None
    price: Decimal | None = None
    currency: str = "AED"
    vat_included: bool = True
    url: str | None = None
    image_url: str | None = None
    attributes: dict[str, Any] = {}


class CatalogueMatch(BaseModel):
    item: CatalogueItem
    score: float


class ProductGroup(BaseModel):
    """One base product with all its variants (colours, group counts). A plain product is a group of one."""

    base_key: str
    name_en: str
    name_ar: str | None = None
    category: str | None = None
    items: list[CatalogueItem]
    score: float = 0.0

    @property
    def has_variants(self) -> bool:
        return len(self.items) > 1


class ItemPrice(BaseModel):
    code: str
    price: Decimal
    currency: str
    vat_included: bool


class StockLevel(BaseModel):
    code: str
    in_stock: bool
    quantity: Decimal | None = None


# --- Model ------------------------------------------------------------------


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any] = {}
    raw_arguments: str | None = None


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_calls: list[ToolCall] = []
    tool_call_id: str | None = None
    name: str | None = None


class ToolSpec(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]


class ModelReply(BaseModel):
    text: str | None = None
    tool_calls: list[ToolCall] = []
    finish_reason: str | None = None
    usage: dict[str, Any] = {}


# --- Conversations, turns, outbox --------------------------------------------


class Direction(StrEnum):
    INBOUND = "in"
    OUTBOUND = "out"


class StoredMessage(BaseModel):
    id: int
    direction: Direction
    text: str
    created_at: datetime


class ConversationSummary(BaseModel):
    id: int
    channel: str
    external_user_id: str
    customer_name: str | None
    last_inbound_at: datetime | None
    created_at: datetime


class TurnRecord(BaseModel):
    """A turn the worker has claimed. Our code fills it; the model never can."""

    id: int
    conversation_id: int
    channel: str
    external_user_id: str
    customer_name: str | None
    attempts: int


class OutboundImage(BaseModel):
    """An image to send after the text reply. Chosen by our code, never by the model."""

    url: str
    caption: str


class PresentedProduct(BaseModel):
    """A product a tool showed the model this turn. Used afterwards to queue its image."""

    key: str = Field(description="Base product key; a later, more specific entry replaces an earlier one")
    name: str
    price: Decimal | None = None
    price_from: bool = False
    currency: str = "AED"
    image_url: str | None = None
    specific: bool = Field(False, description="True when it came from quote_price/product_details")


class OutboxRecord(BaseModel):
    id: int
    conversation_id: int
    turn_id: int | None
    channel: str
    to: str
    text: str
    kind: Literal["text", "image"] = "text"
    image_url: str | None = None
    attempts: int
    last_inbound_at: datetime | None


class RunContext(BaseModel):
    """Facts about a turn that our code sets. Tools read these; the model cannot change them."""

    turn_id: int
    conversation_id: int
    channel: str
    customer_id: str
    customer_name: str | None
    client_name: str
    currency: str
    auto_send: bool
    presented: list[PresentedProduct] = Field(default_factory=list)
