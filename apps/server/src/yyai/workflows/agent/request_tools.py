"""The tools that record something for staff: a quote request, or a handover of the chat.

Both are `write` tools (docs/decisions/0008): they write to our own database, never to the ERP, and send
nothing to the customer themselves. They run only when the client's config sets their approval rule to
`auto` (agent.approvals); otherwise the model never sees them.

Guards:
- Which chat it is comes only from RunContext. No argument names a customer, phone number or chat.
- The product must be in the catalogue copy, which holds only products that are on sale.
- Quantity, unit, area and note are bounded. At most one open quote request per chat and product, and one
  open handover per chat, so repeated calls update instead of piling up.
- Staff test chats (the web app's assistant page) record nothing.

Staff alerts (a WhatsApp ping to the right person) come with the staff list and routing rules. Until then,
staff find open quote requests and handovers in the database and, later, in the web app.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from yyai.core.types import HandoverReason, RunContext
from yyai.services.catalogue import CatalogueService
from yyai.services.requests import MAX_QUANTITY, RequestRejected, RequestService
from yyai.workflows.agent.registry import Tool

# Channels where staff talk to the agent to try it out. Nothing they "request" is real.
INTERNAL_CHANNELS = frozenset({"staff"})

TEST_ONLY = {"ok": True, "saved": False, "note": "Staff test chat: nothing was saved and nobody was alerted."}


class CreateQuoteRequestArgs(BaseModel):
    code: str = Field(
        min_length=1,
        max_length=200,
        description="The exact item code from quote_price or search_products. Never invent one.",
    )
    quantity: float = Field(
        gt=0, le=float(MAX_QUANTITY), description="How many units the customer wants, as a number."
    )
    unit: str | None = Field(
        None, max_length=20, description="The unit the customer used, for example 'kg', 'bag' or 'piece'."
    )
    area: str | None = Field(
        None, max_length=100, description="The delivery area or city the customer gave, if any."
    )
    note: str | None = Field(
        None, max_length=200, description="Anything else staff need for the quote, in a few words."
    )


class HandoverArgs(BaseModel):
    reason: HandoverReason = Field(description="Why staff must take over.")
    summary: str = Field(
        min_length=1,
        max_length=200,
        description="One or two sentences for staff: what the customer wants and what is missing.",
    )


def build_request_tools(catalogue: CatalogueService, requests: RequestService) -> list[Tool]:
    async def create_quote_request(ctx: RunContext, args: CreateQuoteRequestArgs) -> dict[str, Any]:
        if ctx.channel in INTERNAL_CHANNELS:
            return dict(TEST_ONLY)
        item = await catalogue.get(args.code)
        if item is None:
            return {"ok": False, "error": "unknown item code: get it from quote_price or search_products"}
        unit = args.unit or _text(item.attributes.get("unit"))
        try:
            record = await requests.request_quote(
                conversation_id=ctx.conversation_id,
                turn_id=ctx.turn_id,
                code=item.code,
                product_name=item.name_en,
                quantity=Decimal(str(args.quantity)),
                unit=unit,
                area=args.area,
                note=args.note,
            )
        except RequestRejected as exc:
            return {"ok": False, "error": str(exc)}
        return {
            "ok": True,
            "saved": True,
            "updated_existing": not record.created,
            "product": record.product_name,
            "quantity": _num(record.quantity),
            "unit": record.unit,
            "area": record.area,
            "note": (
                "Tell the customer their request is with the team and a colleague will send the formal quote "
                "shortly. Do not give a total, a discount or a delivery date."
            ),
        }

    async def handover_to_staff(ctx: RunContext, args: HandoverArgs) -> dict[str, Any]:
        if ctx.channel in INTERNAL_CHANNELS:
            return dict(TEST_ONLY)
        record = await requests.hand_over(
            conversation_id=ctx.conversation_id, turn_id=ctx.turn_id, reason=args.reason, summary=args.summary
        )
        return {
            "ok": True,
            "already_with_staff": not record.created,
            "note": "Tell the customer a colleague will reply shortly. Do not promise a time.",
        }

    return [
        Tool(
            name="create_quote_request",
            description=(
                "Record that the customer wants a formal quote. Use it once you know the exact product "
                "(its code from quote_price or search_products) and the quantity; ask for the delivery "
                "area if they have not said it. You never send quotes yourself: staff do. Calling it "
                "again for the same product updates the request."
            ),
            args_model=CreateQuoteRequestArgs,
            risk="write",
            fn=create_quote_request,
        ),
        Tool(
            name="handover_to_staff",
            description=(
                "Hand the chat to a member of staff. Use it when quote_price says handover is true, when "
                "the customer asks for a person, complains, wants a large or unusual order, or when a "
                "product is still unclear after you asked once. Write a short summary for staff. "
                "After it, tell the customer a colleague will reply shortly."
            ),
            args_model=HandoverArgs,
            risk="write",
            fn=handover_to_staff,
        ),
    ]


def _text(value: Any) -> str | None:
    return str(value) if value not in (None, "") else None


def _num(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral_value() else float(value)
