"""`yyai demo seed` / `yyai demo clear`: fake chats only, never mixed with real ones."""

from __future__ import annotations

from decimal import Decimal

import psycopg
import pytest

from yyai.core.types import ProductRecord
from yyai.handlers.persistence.db import Database
from yyai.handlers.persistence.demo import DemoStore

pytestmark = pytest.mark.db

PRODUCTS = [
    ProductRecord(code="F64", name_en="Fiorenzato F64 EVO", name_ar="فيورنزاتو F64", price=Decimal(5200)),
    ProductRecord(code="NIC", name_en="Nicaragua Coffee", price=None),
]


async def test_seed_writes_labelled_demo_chats_with_ai_replies(db: Database, sql: psycopg.Connection) -> None:
    summary = await DemoStore(db).seed(PRODUCTS, chats=8, days=5)

    assert summary.chats == 8
    users = [r["external_user_id"] for r in sql.execute("SELECT external_user_id FROM conversations")]
    assert len(users) == 8 and all(u.startswith("demo-") for u in users)
    names = {r["customer_name"] for r in sql.execute("SELECT customer_name FROM conversations")}
    assert all(n.startswith("Demo customer ") for n in names)
    # every reply belongs to a turn (shown as AI) and every turn has a quote_price lookup for Insights
    assert (
        sql.execute(
            "SELECT count(*) AS n FROM messages WHERE direction = 'out' AND turn_id IS NULL"
        ).fetchone()["n"]
        == 0
    )
    turns = sql.execute("SELECT count(*) AS n FROM turns").fetchone()["n"]
    calls = sql.execute("SELECT count(*) AS n FROM audit_log WHERE name = 'quote_price'").fetchone()["n"]
    assert turns == calls > 0
    # only priced products are quoted
    assert "Nicaragua" not in " ".join(r["text"] for r in sql.execute("SELECT text FROM messages"))


async def test_real_chats_are_detected_and_clear_only_removes_demo_ones(
    db: Database, sql: psycopg.Connection
) -> None:
    store = DemoStore(db)
    await store.seed(PRODUCTS, chats=3, days=2)
    assert await store.has_real_chats() is False

    sql.execute("INSERT INTO conversations (channel, external_user_id) VALUES ('whatsapp', '971500000001')")
    assert await store.has_real_chats() is True

    assert await store.clear() == 3
    assert [r["external_user_id"] for r in sql.execute("SELECT external_user_id FROM conversations")] == [
        "971500000001"
    ]


async def test_seed_needs_priced_products(db: Database) -> None:
    with pytest.raises(ValueError, match="no priced products"):
        await DemoStore(db).seed([PRODUCTS[1]], chats=2, days=2)
