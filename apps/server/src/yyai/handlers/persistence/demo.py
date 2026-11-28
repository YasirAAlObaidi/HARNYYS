"""Fake demo chats for development and demos: `yyai demo seed` and `yyai demo clear`.

Every demo customer is named "Demo customer N" with the id "demo-N", so demo rows can never be mistaken for, or
mixed with, real ones. Seeding refuses to run on a database that holds real customer chats.

What is written, so every page of the web app has something to show:
- chats spread over the last `days` days, mostly in Dubai working hours, in English and Arabic, some voice notes;
- for each customer question, an agent turn, a `quote_price` tool call in the audit log (Insights reads these)
  and an AI reply that was "sent", so the Chats page shows AI bubbles with delivery ticks;
- some lookups that found nothing or only a weak match, some quote requests and some handovers.
Prices in the replies come from the product table, like the real agent's.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from yyai.core.types import ProductRecord
from yyai.handlers.persistence.db import Database

DEMO_PREFIX = "demo-"
DUBAI_OFFSET = timedelta(hours=4)
# Hours customers write, Dubai time, weighted towards the working day with a late-evening tail.
_HOURS = [7, 8, 9, 9, 10, 10, 11, 11, 12, 13, 14, 14, 15, 16, 16, 17, 18, 19, 20, 21, 22, 23, 0]

_ASK_EN = [
    "How much is the {name}?",
    "Price for {name} please",
    "Do you have {name} in stock?",
    "Hi, {name} price?",
]
_ASK_AR = ["كم سعر {name}؟", "بكم {name}؟", "عندكم {name}؟ وكم سعرها", "السلام عليكم، ابي سعر {name}"]
_REPLY_EN = "{name} is {price:,} AED including VAT."
_REPLY_AR = "سعر {name} هو {price:,} درهم شامل الضريبة."
_NOT_FOUND_EN = [
    "Do you sell cold brew bottles?",
    "Do you have oat milk?",
    "Price of a La Pavoni lever machine?",
]
_NOT_FOUND_AR = ["عندكم كاسات ورقية؟", "تبيعون شاي أخضر؟"]
_NO_MATCH_REPLY = (
    "I could not find that in our list. Could you tell me the brand or size? A colleague can also help."
)


@dataclass
class DemoSummary:
    chats: int
    messages: int
    quote_requests: int
    handovers: int


class DemoStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def has_real_chats(self) -> bool:
        async with self._db.engine.connect() as conn:
            found = await conn.execute(
                text(
                    "SELECT 1 FROM conversations WHERE NOT internal AND external_user_id NOT LIKE :p LIMIT 1"
                ),
                {"p": DEMO_PREFIX + "%"},
            )
            return found.first() is not None

    async def clear(self) -> int:
        """Delete every demo chat and everything hanging off it. Returns how many chats were removed."""
        async with self._db.engine.begin() as conn:
            ids = [
                r.id
                for r in await conn.execute(
                    text("SELECT id FROM conversations WHERE external_user_id LIKE :p"),
                    {"p": DEMO_PREFIX + "%"},
                )
            ]
            if not ids:
                return 0
            params = {"ids": ids}
            for sql in (
                "DELETE FROM quote_requests WHERE conversation_id = ANY(:ids)",
                "DELETE FROM handovers WHERE conversation_id = ANY(:ids)",
                "DELETE FROM outbox WHERE conversation_id = ANY(:ids)",
                "DELETE FROM audit_log WHERE turn_id IN (SELECT id FROM turns WHERE conversation_id = ANY(:ids))",
                "DELETE FROM messages WHERE conversation_id = ANY(:ids)",
                "DELETE FROM turns WHERE conversation_id = ANY(:ids)",
                "DELETE FROM conversations WHERE id = ANY(:ids)",
            ):
                await conn.execute(text(sql), params)
            return len(ids)

    async def seed(
        self, products: list[ProductRecord], *, chats: int = 60, days: int = 30, seed: int = 1990
    ) -> DemoSummary:
        priced = [p for p in products if p.price is not None]
        if not priced:
            raise ValueError("The product table has no priced products. Load the product sheet first.")
        rnd = random.Random(seed)
        now = datetime.now(UTC)
        summary = DemoSummary(0, 0, 0, 0)
        async with self._db.engine.begin() as conn:
            for n in range(1, chats + 1):
                arabic = rnd.random() < 0.45
                first = _moment(rnd, now, rnd.randint(0, days - 1))
                conversation_id = (
                    await conn.execute(
                        text(
                            "INSERT INTO conversations (channel, external_user_id, customer_name, created_at) "
                            "VALUES ('whatsapp', :uid, :name, :at) RETURNING id"
                        ),
                        {"uid": f"{DEMO_PREFIX}{n}", "name": f"Demo customer {n}", "at": first},
                    )
                ).scalar_one()
                summary.chats += 1
                # Most chats are one question; some customers come back on a later day (returning customers).
                visits = [first]
                if rnd.random() < 0.3:
                    later = (now - first).days
                    if later > 0:
                        visits.append(_moment(rnd, now, rnd.randint(0, later - 1)))
                last_in = first
                for visit in visits:
                    for step in range(rnd.choice([1, 1, 2])):
                        at = visit + timedelta(minutes=4 * step)
                        if at > now:
                            continue
                        last_in = max(last_in, at)
                        added = await _exchange(conn, rnd, conversation_id, at, arabic, priced, summary)
                        summary.messages += added
                await conn.execute(
                    text("UPDATE conversations SET last_inbound_at = :at WHERE id = :id"),
                    {"at": last_in, "id": conversation_id},
                )
        return summary


def _moment(rnd: random.Random, now: datetime, days_ago: int) -> datetime:
    """A time on the given day, at an hour customers tend to write, in Dubai time, never in the future."""
    local_day = (now + DUBAI_OFFSET - timedelta(days=days_ago)).date()
    hour = rnd.choice(_HOURS)
    local = datetime(local_day.year, local_day.month, local_day.day, hour, rnd.randint(0, 59), tzinfo=UTC)
    moment = local - DUBAI_OFFSET
    return min(moment, now - timedelta(minutes=rnd.randint(5, 90)))


async def _exchange(
    conn: Any,
    rnd: random.Random,
    conversation_id: int,
    at: datetime,
    arabic: bool,
    priced: list[ProductRecord],
    summary: DemoSummary,
) -> int:
    """One customer question and the AI's answer: message, turn, tool call, reply, outbox. Returns messages added."""
    roll = rnd.random()
    product = rnd.choice(priced)
    name = (product.name_ar if arabic and product.name_ar else product.name_en) or product.code
    voice = rnd.random() < 0.08
    if roll < 0.12:  # nothing found
        question = rnd.choice(_NOT_FOUND_AR if arabic else _NOT_FOUND_EN)
        result: dict[str, Any] = {"found": False, "handover": False}
        reply = _NO_MATCH_REPLY
    else:
        question = rnd.choice(_ASK_AR if arabic else _ASK_EN).format(name=name)
        weak = roll < 0.2
        price = (
            int(product.price or 0) if product.price == int(product.price or 0) else float(product.price or 0)
        )
        result = {
            "found": True,
            "code": product.code,
            "name_en": product.name_en,
            "name_ar": product.name_ar,
            "match_score": round(rnd.uniform(0.3, 0.48) if weak else rnd.uniform(0.6, 1.0), 2),
            "clear_match": not weak,
        }
        if weak:
            reply = "Did you mean the " + product.name_en + "? Or something else?"
        else:
            result.update(
                price=price, currency=product.currency, vat_included=product.vat_included, handover=False
            )
            reply = (_REPLY_AR if arabic else _REPLY_EN).format(name=name, price=price)
    media = [{"kind": "audio", "id": "demo"}] if voice else []
    await conn.execute(
        text(
            "INSERT INTO messages (conversation_id, direction, text, media, created_at) "
            "VALUES (:c, 'in', :t, CAST(:m AS jsonb), :at)"
        ),
        {"c": conversation_id, "t": "[audio]" if voice else question, "m": json.dumps(media), "at": at},
    )
    answered = at + timedelta(seconds=rnd.randint(6, 40))
    turn_id = (
        await conn.execute(
            text(
                "INSERT INTO turns (conversation_id, state, attempts, steps, created_at, started_at, finished_at) "
                "VALUES (:c, 'sent', 1, 2, :at, :at, :done) RETURNING id"
            ),
            {"c": conversation_id, "at": at, "done": answered},
        )
    ).scalar_one()
    await conn.execute(
        text(
            "INSERT INTO audit_log (turn_id, kind, name, data, created_at) "
            "VALUES (:t, 'tool_call', 'quote_price', CAST(:d AS jsonb), :at)"
        ),
        {
            "t": turn_id,
            "d": json.dumps(
                {"step": 1, "args": {"query": question}, "result": json.dumps(result, ensure_ascii=False)}
            ),
            "at": at + timedelta(seconds=3),
        },
    )
    message_id = (
        await conn.execute(
            text(
                "INSERT INTO messages (conversation_id, direction, text, turn_id, created_at) "
                "VALUES (:c, 'out', :t, :turn, :at) RETURNING id"
            ),
            {"c": conversation_id, "t": reply, "turn": turn_id, "at": answered},
        )
    ).scalar_one()
    await conn.execute(
        text(
            "INSERT INTO outbox (conversation_id, turn_id, message_id, text, status, attempts, created_at, sent_at) "
            "VALUES (:c, :turn, :m, :t, 'sent', 1, :at, :at)"
        ),
        {"c": conversation_id, "turn": turn_id, "m": message_id, "t": reply, "at": answered},
    )
    if result.get("found") and result.get("clear_match") and rnd.random() < 0.2:
        quantity = Decimal(rnd.choice([1, 2, 3, 5, 10, 20]))
        await conn.execute(
            text(
                "INSERT INTO quote_requests (conversation_id, turn_id, code, product_name, quantity, area, created_at) "
                "VALUES (:c, :turn, :code, :name, :q, :area, :at) "
                "ON CONFLICT (conversation_id, code) WHERE status = 'open' DO NOTHING"
            ),
            {
                "c": conversation_id,
                "turn": turn_id,
                "code": product.code,
                "name": product.name_en,
                "q": quantity,
                "area": rnd.choice(["Al Quoz", "Deira", "Business Bay", "Sharjah", None]),
                "at": answered,
            },
        )
        summary.quote_requests += 1
    elif rnd.random() < 0.08:
        await conn.execute(
            text(
                "INSERT INTO handovers (conversation_id, turn_id, reason, summary, source, created_at) "
                "VALUES (:c, :turn, :reason, 'Demo: customer wants a person.', 'tool', :at) "
                "ON CONFLICT (conversation_id) WHERE status = 'open' DO NOTHING"
            ),
            {
                "c": conversation_id,
                "turn": turn_id,
                "reason": rnd.choice(["asked_for_human", "large_order"]),
                "at": at,
            },
        )
        summary.handovers += 1
    return 2
