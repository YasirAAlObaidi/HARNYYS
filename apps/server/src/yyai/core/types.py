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


class ItemPrice(BaseModel):
    code: str
    price: Decimal
    currency: str
    vat_included: bool


class StockLevel(BaseModel):
    code: str
    in_stock: bool
    quantity: Decimal | None = None


# --- Product table (the client's sheet) ---------------------------------------


class ProductRecord(BaseModel):
    """One product as the client's sheet gives it. The only source of prices and stock the agent may quote."""

    code: str
    name_en: str
    name_ar: str | None = None
    category: str | None = None
    description: str | None = None
    unit: str | None = None
    price: Decimal | None = Field(None, description="None: no price, so the agent hands the chat to staff")
    currency: str = "AED"
    vat_included: bool = True
    in_stock: bool | None = Field(None, description="None: stock unknown, so staff confirm it")
    quantity: Decimal | None = None
    url: str | None = None
    image_url: str | None = None
    attributes: dict[str, Any] = {}


class SheetIssue(BaseModel):
    """One problem in an uploaded sheet. `row` is the Excel row number the client sees, if it is about a row."""

    row: int | None = None
    column: str | None = None
    message: str


class ProductImportReport(BaseModel):
    """What an import did, or would do. Nothing is changed while `issues` is not empty."""

    source: str
    rows: int = 0
    added: list[str] = []
    updated: list[str] = []
    deactivated: list[str] = []
    unchanged: int = 0
    issues: list[SheetIssue] = []
    applied: bool = False


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


class OutboxRecord(BaseModel):
    id: int
    conversation_id: int
    turn_id: int | None
    channel: str
    to: str
    text: str
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


# --- What the agent records for staff ------------------------------------------

# Why a chat is handed to staff. The database table checks the same list.
HandoverReason = Literal[
    "missing_price", "unclear_item", "asked_for_human", "complaint", "large_order", "other"
]
HandoverSource = Literal["tool", "safety_net"]


class QuoteRequestRecord(BaseModel):
    """A customer asking for a formal quote. Staff send the quote; the agent never does."""

    id: int
    conversation_id: int
    code: str
    product_name: str
    quantity: Decimal
    unit: str | None
    area: str | None
    note: str | None
    status: str
    created: bool  # False when an open request for the same product was updated instead


class HandoverRecord(BaseModel):
    """A chat that staff must answer. At most one is open per chat."""

    id: int
    conversation_id: int
    reason: HandoverReason
    summary: str | None
    source: HandoverSource
    created: bool  # False when the chat already had an open handover
