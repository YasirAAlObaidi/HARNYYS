"""Insights: the snapshot maths (pure functions), and that internal staff chats never reach the numbers."""

from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import psycopg
import pytest

from yyai.core.config import WorkingHours
from yyai.core.types import ContactRow, CustomerMessageRow, ToolCallRow
from yyai.handlers.persistence.db import Database
from yyai.handlers.persistence.insights import InsightStore
from yyai.services.insights import (
    SNAPSHOT_VERSION,
    InsightService,
    compute_snapshot,
    language_of,
    next_top_of_hour,
    parse_result,
    periods_for,
    previous_of,
    question_topic,
)
from yyai.workflows.insights import InsightsWorkflow

DUBAI = ZoneInfo("Asia/Dubai")
# Thursday 26 Nov 2026, 14:00:05 in Dubai (10:00:05 UTC).
NOW = datetime(2026, 11, 26, 10, 0, 5, tzinfo=UTC)
WEAK = 0.5
HOURS = WorkingHours(
    confirmed=False,
    mon="09:00-18:00",
    tue="09:00-18:00",
    wed="09:00-18:00",
    thu="09:00-18:00",
    fri="09:00-18:00",
    sat="09:00-18:00",
    sun="closed",
)


def dubai(day: int, hour: int, minute: int = 0, month: int = 11) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=DUBAI)


def msg(cid: int, at: datetime, text: str = "hello", media: tuple[str, ...] = ()) -> CustomerMessageRow:
    return CustomerMessageRow(cid, at, text, media)


def call(cid: int, name: str, args: dict[str, Any], result: Any, at: datetime | None = None) -> ToolCallRow:
    text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
    return ToolCallRow(cid, name, args, text, at or dubai(26, 11))


def snapshot(
    messages: list[CustomerMessageRow],
    contacts: list[ContactRow] | None = None,
    calls: list[ToolCallRow] | None = None,
    hours: WorkingHours | None = HOURS,
) -> dict[str, Any]:
    if contacts is None:
        firsts: dict[int, datetime] = {}
        for m in messages:
            firsts[m.conversation_id] = min(firsts.get(m.conversation_id, m.created_at), m.created_at)
        contacts = [ContactRow(cid, at) for cid, at in firsts.items()]
    return compute_snapshot(
        NOW, DUBAI, messages, contacts, calls or [], working_hours=hours, weak_match_score=WEAK
    )


# --- periods and the hour ------------------------------------------------------------------------------------------


def test_periods_are_local_calendar_days_including_today() -> None:
    periods = {p.key: (p.first_day, p.last_day) for p in periods_for(date(2026, 11, 26))}
    assert periods == {
        "today": (date(2026, 11, 26), date(2026, 11, 26)),
        "7d": (date(2026, 11, 20), date(2026, 11, 26)),
        "30d": (date(2026, 10, 28), date(2026, 11, 26)),
        "month": (date(2026, 11, 1), date(2026, 11, 26)),
    }


def test_the_next_refresh_is_the_next_full_hour_in_dubai() -> None:
    assert next_top_of_hour(dubai(26, 14, 0), DUBAI) == dubai(26, 15)
    assert next_top_of_hour(datetime(2026, 11, 26, 10, 59, 59, tzinfo=UTC), DUBAI) == dubai(26, 15)
    assert next_top_of_hour(dubai(26, 23, 30), DUBAI) == dubai(27, 0)


def test_a_message_after_8pm_utc_is_already_tomorrow_in_dubai() -> None:
    late = datetime(2026, 11, 25, 20, 30, tzinfo=UTC)  # 00:30 on Thursday the 26th in Dubai
    data = snapshot([msg(1, late)])
    today = data["periods"]["today"]
    assert today["leads"]["active_contacts"]["value"] == 1
    assert today["busy"]["heatmap"]["cells"][3][0] == 1  # Thursday (row 3, Monday is 0), 00:00-01:00


# --- leads --------------------------------------------------------------------------------------------------------


def test_new_and_returning_customers() -> None:
    messages = [
        msg(1, dubai(26, 9)),  # new today
        msg(2, dubai(26, 10)),  # wrote before, in October: returning
        msg(3, dubai(22, 12)),  # new on the 22nd: new in 7 days, not active today
        msg(3, dubai(26, 11)),  # ...and back today: returning today
    ]
    contacts = [ContactRow(1, dubai(26, 9)), ContactRow(2, dubai(1, 9, month=10)), ContactRow(3, dubai(22, 12))]

    periods = snapshot(messages, contacts)["periods"]

    assert periods["today"]["leads"]["new_vs_returning"] == {"status": "live", "new": 1, "returning": 2}
    assert periods["today"]["leads"]["new_contacts"] == {"status": "live", "value": 1}
    assert periods["7d"]["leads"]["new_vs_returning"] == {"status": "live", "new": 2, "returning": 1}
    assert periods["30d"]["leads"]["new_contacts"]["value"] == 2
    daily = {d["date"]: d["value"] for d in periods["7d"]["leads"]["new_contacts_daily"]["series"]}
    assert len(daily) == 7
    assert (daily["2026-11-22"], daily["2026-11-26"], daily["2026-11-23"]) == (1, 1, 0)


def test_metrics_with_no_data_source_are_not_tracked_never_zero() -> None:
    data = snapshot([msg(1, dubai(26, 9))])
    for period in data["periods"].values():
        for card in ("quote_requests", "quotes_sent", "lost_leads", "lost_at_step"):
            assert period["leads"][card]["status"] == "not_tracked"
            assert "value" not in period["leads"][card]
            assert period["leads"][card]["needs"] in data["not_tracked"]
        assert period["busy"]["lost_leads_heatmap"]["status"] == "not_tracked"
    assert data["version"] == SNAPSHOT_VERSION
    assert data["computed_at"] == "2026-11-26T14:00:05+04:00"
    assert data["next_at"] == "2026-11-26T15:00:00+04:00"


# --- customer demand ------------------------------------------------------------------------------------------------


def test_language_and_voice_notes() -> None:
    messages = [
        msg(1, dubai(26, 9), "كم سعر الكولومبي؟"),
        msg(1, dubai(26, 9), "Price of the CBR-101 please"),
        msg(2, dubai(26, 10), "شو عندكم من مطاحن؟ grinder"),  # mostly Arabic letters
        msg(2, dubai(26, 10), "[audio]", ("audio",)),
        msg(3, dubai(26, 11), "👍"),
    ]
    demand = snapshot(messages)["periods"]["today"]["demand"]

    assert demand["languages"] == {"status": "live", "arabic": 2, "english": 1, "other": 2, "messages": 5}
    assert demand["voice_notes"] == {"status": "live", "count": 1, "chats": 1, "messages": 5}
    assert language_of(msg(1, NOW, "[audio]", ("audio",))) is None


@pytest.mark.parametrize(
    ("text", "topic"),
    [
        ("كم سعر قهوة كولومبيا؟", "price"),
        ("بكم الكيلو", "price"),
        ("كم حقه؟", "price"),
        ("How much is the 1kg bag?", "price"),
        ("أسعار المطاحن", "price"),
        ("هل هو متوفرة؟", "stock"),
        ("عندكم حبوب اثيوبية؟", "stock"),
        ("Do you have the Fiorenzato in stock?", "stock"),
        ("عندكم CBR 101 وبكم؟", "both"),
        ("Is it available and what's the price?", "both"),
        ("Thanks!", None),
        ("السلام عليكم", None),
    ],
)
def test_price_and_stock_questions_by_keyword(text: str, topic: str | None) -> None:
    assert question_topic(text) == topic


def test_price_vs_stock_is_an_estimate_over_messages_with_words() -> None:
    messages = [
        msg(1, dubai(26, 9), "كم سعر الكولومبي؟"),
        msg(1, dubai(26, 9), "متوفر؟"),
        msg(2, dubai(26, 9), "do you have it and how much"),
        msg(2, dubai(26, 9), "[image]", ("image",)),
        msg(3, dubai(26, 9), "hello"),
    ]
    card = snapshot(messages)["periods"]["today"]["demand"]["price_vs_stock"]
    assert card == {"status": "estimate", "price": 2, "stock": 2, "both": 1, "messages": 4}


def quote(code: str, score: float, name: str = "Product", found: bool = True) -> dict[str, Any]:
    if not found:
        return {"found": False}
    return {"found": True, "code": code, "name_en": name, "name_ar": "منتج", "price": 10, "match_score": score}


def test_most_asked_products_count_chats_and_skip_weak_matches() -> None:
    calls = [
        call(1, "quote_price", {"query": "colombia 1kg"}, quote("COL-1", 0.9, "Colombia 1kg")),
        call(1, "quote_price", {"query": "colombia"}, quote("COL-1", 0.8, "Colombia 1kg")),
        call(2, "product_details", {"code": "COL-1"}, quote("COL-1", 1.0, "Colombia 1kg")),
        call(2, "quote_price", {"query": "ethiopia"}, quote("ETH-1", 0.7, "Ethiopia")),
        call(3, "quote_price", {"query": "blue mountain"}, quote("COL-1", 0.3)),  # weak: not this product
        call(3, "search_products", {"query": "grinder"}, [{"code": "G-1"}]),  # a list, not one product
    ]
    top = snapshot([msg(1, dubai(26, 9))], calls=calls)["periods"]["today"]["demand"]["top_products"]

    assert top["lookups"] == 4
    assert [(i["code"], i["chats"], i["asks"], i["name_en"]) for i in top["items"]] == [
        ("COL-1", 2, 3, "Colombia 1kg"),
        ("ETH-1", 1, 1, "Ethiopia"),
    ]


def test_items_not_found_counts_no_match_and_weak_match() -> None:
    calls = [
        call(1, "quote_price", {"query": "Blue Mountain"}, {"found": False}),
        call(2, "quote_price", {"query": "blue mountain "}, {"found": False}),
        call(2, "quote_price", {"query": "كوب ورقي"}, quote("CUP-9", 0.3)),
        call(3, "search_products", {"query": "chemex"}, []),
        call(3, "search_products", {"query": "grinder"}, [{"code": "G-1"}]),
        call(3, "quote_price", {"query": "colombia"}, quote("COL-1", 0.9)),
        call(3, "quote_price", {"query": "x"}, {"error": "tool 'quote_price' timed out"}),  # says nothing
        call(3, "product_details", {"code": "NOPE"}, {"found": False}),  # the model's mistake, not a miss
    ]
    card = snapshot([msg(1, dubai(26, 9))], calls=calls)["periods"]["today"]["demand"]["not_found"]

    assert (card["searches"], card["no_match"], card["weak_match"]) == (6, 3, 1)
    assert card["top"] == [
        {"query": "Blue Mountain", "count": 2, "kind": "none"},
        {"query": "chemex", "count": 1, "kind": "none"},
        {"query": "كوب ورقي", "count": 1, "kind": "weak"},
    ]


def test_a_result_cut_at_2000_characters_still_reads() -> None:
    full = json.dumps(
        {"found": True, "code": "LONG-1", "name_en": "Long \"quoted\" name", "name_ar": "اسم", "description": "x" * 3000},
        ensure_ascii=False,
    )
    assert parse_result(full[:2000]) == {"found": True, "code": "LONG-1", "name_en": 'Long "quoted" name', "name_ar": "اسم"}
    assert parse_result("not json at all") is None
    assert parse_result("[]") == []


# --- busy times ---------------------------------------------------------------------------------------------------


def test_heatmap_chats_per_day_and_after_hours() -> None:
    messages = [
        msg(1, dubai(26, 9, 0)),  # Thursday 09:00: open
        msg(1, dubai(26, 17, 59)),  # 17:59: open
        msg(2, dubai(26, 18, 0)),  # 18:00: closed
        msg(2, dubai(26, 8, 59)),  # 08:59: closed
        msg(3, dubai(22, 12)),  # Sunday: closed all day
    ]
    periods = snapshot(messages)["periods"]

    busy = periods["7d"]["busy"]
    assert busy["heatmap"]["cells"][3][9] == 1 and busy["heatmap"]["cells"][3][18] == 1
    assert busy["heatmap"]["cells"][6][12] == 1  # Sunday is row 6
    assert busy["heatmap"]["max"] == 1
    assert busy["after_hours"] == {"status": "live", "after_hours": 3, "messages": 5, "hours_confirmed": False}
    days = {d["date"]: (d["chats"], d["messages"]) for d in busy["chats_daily"]["series"]}
    assert days["2026-11-26"] == (2, 4) and days["2026-11-22"] == (1, 1) and days["2026-11-24"] == (0, 0)
    assert periods["today"]["busy"]["after_hours"]["after_hours"] == 2


def test_after_hours_is_not_tracked_without_working_hours() -> None:
    busy = snapshot([msg(1, dubai(26, 9))], hours=None)["periods"]["today"]["busy"]
    assert busy["after_hours"] == {"status": "not_tracked", "needs": "working_hours"}


def test_working_hours_must_be_well_formed() -> None:
    assert WorkingHours(mon=" 08:30-17:00 ", tue="CLOSED").tue == "closed"
    for bad in ("9-18", "18:00-09:00", "25:00-26:00", "always"):
        with pytest.raises(ValueError):
            WorkingHours(mon=bad)


# --- against the database: internal chats never count ---------------------------------------------------------------


def add_chat(sql: psycopg.Connection, user: str, *, internal: bool, channel: str = "whatsapp") -> int:
    return sql.execute(
        "INSERT INTO conversations (channel, external_user_id, internal) VALUES (%s, %s, %s) RETURNING id",
        (channel, user, internal),
    ).fetchone()["id"]


def add_message(sql: psycopg.Connection, cid: int, text: str, at: datetime, media: str = "[]") -> None:
    sql.execute(
        "INSERT INTO messages (conversation_id, direction, text, media, created_at) VALUES (%s, 'in', %s, %s, %s)",
        (cid, text, media, at),
    )


def add_tool_call(sql: psycopg.Connection, cid: int, name: str, args: dict[str, Any], result: Any, at: datetime) -> None:
    turn = sql.execute(
        "INSERT INTO turns (conversation_id, state) VALUES (%s, 'sent') RETURNING id", (cid,)
    ).fetchone()["id"]
    data = {"step": 1, "args": args, "result": json.dumps(result, ensure_ascii=False)}
    sql.execute(
        "INSERT INTO audit_log (turn_id, kind, name, data, created_at) VALUES (%s, 'tool_call', %s, %s, %s)",
        (turn, name, json.dumps(data, ensure_ascii=False), at),
    )


@pytest.fixture
def service(db: Database) -> InsightService:
    return InsightService(
        InsightStore(db), timezone="Asia/Dubai", working_hours=HOURS, weak_match_score=WEAK, clock=lambda: NOW
    )


@pytest.mark.db
async def test_staff_chats_never_reach_the_numbers(service: InsightService, sql: psycopg.Connection) -> None:
    customer = add_chat(sql, "971500000001", internal=False)
    staff = add_chat(sql, "staff-1", internal=True, channel="staff")
    for cid in (customer, staff):
        add_message(sql, cid, "كم سعر الكولومبي؟", dubai(26, 10))
        add_message(sql, cid, "[audio]", dubai(26, 11), '[{"kind": "audio", "provider_id": "m1"}]')
        add_tool_call(sql, cid, "quote_price", {"query": "colombia"}, quote("COL-1", 0.9, "Colombia"), dubai(26, 10))
        add_tool_call(sql, cid, "quote_price", {"query": "unicorn beans"}, {"found": False}, dubai(26, 10))

    snap = await service.refresh()

    today = snap.data["periods"]["today"]
    assert today["leads"]["active_contacts"]["value"] == 1
    assert today["leads"]["new_contacts"]["value"] == 1
    assert today["demand"]["languages"]["messages"] == 2
    assert today["demand"]["voice_notes"]["count"] == 1
    assert today["demand"]["top_products"]["items"][0]["chats"] == 1
    assert today["demand"]["top_products"]["lookups"] == 1
    assert today["demand"]["not_found"]["no_match"] == 1
    assert sum(map(sum, today["busy"]["heatmap"]["cells"])) == 2


@pytest.mark.db
async def test_snapshots_are_saved_served_and_pruned(service: InsightService, db: Database, sql: psycopg.Connection) -> None:
    workflow = InsightsWorkflow(service)
    assert await workflow.latest() is None
    assert await workflow.refresh_if_stale() is True  # nothing yet: compute now

    latest = await workflow.latest()
    assert latest is not None
    assert (latest["computed_at"], latest["next_at"]) == ("2026-11-26T14:00:05+04:00", "2026-11-26T15:00:00+04:00")
    assert await workflow.refresh_if_stale() is False  # less than an hour old
    assert workflow.seconds_until_next_refresh() == pytest.approx(3600 - 5 + 1)

    sql.execute("UPDATE insight_snapshots SET computed_at = computed_at - interval '61 minutes'")
    assert await workflow.refresh_if_stale() is True
    sql.execute("UPDATE insight_snapshots SET data = jsonb_set(data, '{version}', '0')")
    assert await workflow.refresh_if_stale() is True  # a snapshot from an older format is replaced at once

    sql.execute("UPDATE insight_snapshots SET computed_at = computed_at - interval '40 days'")
    assert await InsightStore(db).prune_snapshots(NOW - timedelta(days=30)) == 2
    assert sql.execute("SELECT count(*) AS n FROM insight_snapshots").fetchone()["n"] == 1  # the newest stays


# --- the web app's test fixture is a real snapshot ---------------------------------------------------------------

WEB_FIXTURE = Path(__file__).resolve().parents[2] / "web" / "src" / "test" / "insights-snapshot.json"


def fixture_snapshot() -> dict[str, Any]:
    messages = [
        msg(1, dubai(26, 9), "كم سعر قهوة كولومبيا 1 كجم؟"),
        msg(1, dubai(26, 9, 5), "متوفر؟"),
        msg(2, dubai(25, 20), "Do you have the Fiorenzato grinder in stock?"),
        msg(2, dubai(25, 20, 2), "[audio]", ("audio",)),
        msg(3, dubai(22, 11), "How much is the Chemex?"),
        msg(4, dubai(26, 7), "السلام عليكم"),
    ]
    contacts = [
        ContactRow(1, dubai(26, 9)),
        ContactRow(2, dubai(2, 10, month=10)),
        ContactRow(3, dubai(22, 11)),
        ContactRow(4, dubai(26, 7)),
    ]
    calls = [
        call(1, "quote_price", {"query": "كولومبيا 1 كجم"}, quote("COL-1KG", 0.92, "Colombia Supremo 1 kg")),
        call(2, "quote_price", {"query": "fiorenzato grinder"}, quote("FIO-F64", 0.81, "Fiorenzato F64 EVO")),
        call(3, "quote_price", {"query": "chemex"}, {"found": False}),
        call(3, "search_products", {"query": "chemex"}, []),
    ]
    data = compute_snapshot(
        NOW, DUBAI, messages, contacts, calls, working_hours=HOURS, weak_match_score=WEAK, history_from=date(2026, 10, 1)
    )
    return {**data, "id": 1}  # the API adds the snapshot id when it serves it (workflows/insights.py)


def test_the_web_apps_fixture_is_what_the_server_sends() -> None:
    """apps/web tests render this file. If the snapshot format changes, regenerate it with:
    YYAI_WRITE_WEB_FIXTURE=1 uv run pytest tests/test_insights.py -k fixture"""
    expected = fixture_snapshot()
    if os.environ.get("YYAI_WRITE_WEB_FIXTURE"):
        WEB_FIXTURE.write_text(json.dumps(expected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    assert json.loads(WEB_FIXTURE.read_text(encoding="utf-8")) == expected


@pytest.mark.db
async def test_an_hour_missed_while_the_machine_slept_is_made_at_once(db: Database) -> None:
    now = [NOW]  # 14:00:05 Dubai
    service = InsightService(
        InsightStore(db), timezone="Asia/Dubai", working_hours=HOURS, weak_match_score=WEAK, clock=lambda: now[0]
    )
    workflow = InsightsWorkflow(service)
    await workflow.refresh_if_stale()
    now[0] = NOW + timedelta(minutes=30)
    assert workflow.seconds_until_next_refresh() == pytest.approx(30 * 60 - 5 + 1)  # due at 15:00

    now[0] = NOW + timedelta(hours=5)  # the box slept through 15:00, 16:00, 17:00 and 18:00
    assert workflow.seconds_until_next_refresh() == pytest.approx(1)  # overdue: run now
    await workflow.refresh()
    assert workflow.seconds_until_next_refresh() == pytest.approx(3600 - 5 + 1)  # then back on the hour


# --- the change against the previous period -----------------------------------------------------------------------


def test_each_period_is_compared_with_the_one_before_it() -> None:
    periods = {p.key: previous_of(p) for p in periods_for(date(2026, 11, 26))}
    assert (periods["today"].first_day, periods["today"].last_day) == (date(2026, 11, 19), date(2026, 11, 19))
    assert (periods["7d"].first_day, periods["7d"].last_day) == (date(2026, 11, 13), date(2026, 11, 19))
    assert (periods["30d"].first_day, periods["30d"].last_day) == (date(2026, 9, 28), date(2026, 10, 27))
    assert (periods["month"].first_day, periods["month"].last_day) == (date(2026, 10, 1), date(2026, 10, 26))
    # 31 March is compared with the whole of February, never with days February does not have.
    march = previous_of(periods_for(date(2027, 3, 31))[3])
    assert (march.first_day, march.last_day) == (date(2027, 2, 1), date(2027, 2, 28))


def test_previous_numbers_only_when_the_data_reaches_back_that_far() -> None:
    messages = [
        msg(1, dubai(26, 9), "hi"),
        msg(2, dubai(15, 22), "[audio]", ("audio",)),  # in the 7 days before the current 7
        msg(2, dubai(16, 10), "price?"),
    ]
    contacts = [ContactRow(1, dubai(26, 9)), ContactRow(2, dubai(15, 22))]

    covered = compute_snapshot(
        NOW, DUBAI, messages, contacts, [], working_hours=HOURS, weak_match_score=WEAK, history_from=date(2026, 11, 1)
    )["periods"]
    assert covered["7d"]["previous"] == {
        "first_day": "2026-11-13",
        "last_day": "2026-11-19",
        "new_contacts": 1,
        "active_contacts": 1,
        "messages": 2,
        "voice_notes": 1,
        "after_hours": 1,
    }
    assert covered["30d"]["previous"] is None  # data starts 1 Nov; the earlier 30 days began 28 Sep

    no_history = compute_snapshot(NOW, DUBAI, messages, contacts, [], working_hours=HOURS, weak_match_score=WEAK)
    assert all(period["previous"] is None for period in no_history["periods"].values())
