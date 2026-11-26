"""Data types shared by every layer.

These are our own shapes. Vendor formats (Meta's JSON, Al Ameen's rows, a model
server's response) are converted into these inside the handlers and never leak
upward.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

# --- Messaging -------------------------------------------------------------

STAFF_CHANNEL = "staff"
"""The built-in channel of the staff Assistant page. Every conversation on it is internal (see `internal`)."""


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
    internal: bool = Field(
        False,
        description="True for staff chats: kept off the Chats page and out of Insights, and never a real lead",
    )


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


Author = Literal["customer", "ai", "staff"]


class ConversationSummary(BaseModel):
    id: int
    channel: str
    external_user_id: str
    customer_name: str | None
    last_inbound_at: datetime | None
    created_at: datetime
    internal: bool = False
    # The newest message, for the chat list. None when the conversation has no messages yet.
    last_message_at: datetime | None = None
    last_message_text: str | None = None
    last_message_author: Author | None = None
    message_count: int = 0


class TranscriptMessage(BaseModel):
    """One message as staff see it in a chat. `author` tells customer, AI and staff messages apart."""

    id: int
    direction: Direction
    author: Author
    text: str
    media: list[str] = Field([], description="Media kinds sent with the message, e.g. ['audio'] for a voice note")
    created_at: datetime
    delivery: str | None = Field(None, description="Outbox status of a reply: pending, sending, sent, failed ...")


class TurnRecord(BaseModel):
    """A turn the worker has claimed. Our code fills it; the model never can."""

    id: int
    conversation_id: int
    channel: str
    external_user_id: str
    customer_name: str | None
    attempts: int
    internal: bool = False


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
    # True for staff chats (the Assistant page). A tool that records something real, such as a quote request,
    # must check this and do nothing real when it is set.
    internal: bool = False

    @model_validator(mode="after")
    def _staff_chats_are_internal(self) -> RunContext:
        if self.channel == STAFF_CHANNEL:
            self.internal = True
        return self


# --- Staff users and sessions ---------------------------------------------------


class StaffRole(StrEnum):
    ADMIN = "admin"
    SALES = "sales"
    VIEWER = "viewer"


class StaffUser(BaseModel):
    """A member of staff who can log in to the web app. Never carries the password hash or the 2FA secret."""

    id: int
    username: str
    display_name: str | None = None
    role: StaffRole
    active: bool = True
    created_at: datetime
    last_login_at: datetime | None = None


class StaffCredentials(BaseModel):
    """What the login check needs. Stays inside the staff service and its store."""

    user: StaffUser
    password_hash: str
    totp_secret: str
    totp_last_step: int | None = None


class StaffSession(BaseModel):
    user: StaffUser
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime


class LoginOutcome(BaseModel):
    """The result of one login attempt. `token` is set only on success and goes into the session cookie."""

    ok: bool
    user: StaffUser | None = None
    token: str | None = None
    expires_at: datetime | None = None
    retry_after_s: int | None = Field(None, description="Set when login is throttled: seconds until it may be tried")


class NewStaffUser(BaseModel):
    """A user just created or reset: the 2FA secret is shown once, to enrol an authenticator app."""

    user: StaffUser
    totp_secret: str
    totp_uri: str


# --- Insights ------------------------------------------------------------------


class InsightSnapshot(BaseModel):
    id: int
    computed_at: datetime
    data: dict[str, Any]


# The raw rows an insight snapshot is computed from. Plain dataclasses, not pydantic models, because a month
# of messages can be tens of thousands of rows. All of them come from customer chats only, never internal ones.


@dataclass(frozen=True, slots=True)
class CustomerMessageRow:
    conversation_id: int
    created_at: datetime
    text: str
    media: tuple[str, ...] = ()  # media kinds, e.g. ("audio",) for a voice note


@dataclass(frozen=True, slots=True)
class ContactRow:
    conversation_id: int
    first_at: datetime  # when this customer first wrote, ever


@dataclass(frozen=True, slots=True)
class ToolCallRow:
    conversation_id: int
    name: str
    args: dict[str, Any]
    result: str  # the tool's JSON answer as the audit log keeps it (cut at 2000 characters)
    created_at: datetime
