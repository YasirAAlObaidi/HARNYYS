"""Insights: the numbers on the Insights page, computed once an hour into a snapshot.

Honesty rule: every number is computed from what the database really stores. A metric with no data source yet
is sent as {"status": "not_tracked", "needs": ...} and the page shows "Not tracked yet", never a zero.
Statuses:
- "live": counted exactly from stored rows.
- "estimate": computed from stored rows with a rule of thumb (keywords). The page labels it as an estimate.
- "not_tracked": nothing stores this yet. `needs` names what is missing (see NOT_TRACKED).

Sources (customer chats only; internal staff chats are filtered out by the store):
- customer messages: `messages` with direction 'in' (time, text, media kinds);
- when each customer first wrote: the oldest of their messages;
- what the agent looked up: `audit_log` rows of kind 'tool_call' (quote_price, product_details, search_products).

All days and hours are in the client's timezone (Asia/Dubai for Kahraman).
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from yyai.core.config import WEEKDAYS, WorkingHours
from yyai.core.errors import ConfigError
from yyai.core.text import normalize_for_search
from yyai.core.types import ContactRow, CustomerMessageRow, InsightSnapshot, ToolCallRow
from yyai.handlers.persistence.insights import InsightStore

logger = logging.getLogger(__name__)

SNAPSHOT_VERSION = 2  # 2: each period has `previous` (the numbers for the change on KPI cards)
KEEP_SNAPSHOTS = timedelta(days=30)
TOP_N = 10

# What each "not tracked yet" metric is waiting for. The web app shows its own text for each key.
NOT_TRACKED: dict[str, str] = {
    "quote_requests": "A quote-request record: a tool or staff action that saves each request (customer, items, time).",
    "quotes_sent": "A quote record with a 'sent' status and time, written when staff send a quote.",
    "lead_outcomes": "A lead status per chat (asked, priced, quote requested, quote sent, won or lost) and the step "
    "where it was lost, set by staff or by a rule.",
    "working_hours": "Opening hours in the client config (client.working_hours).",
}

PERIODS = ("today", "7d", "30d", "month")

# --- price and stock questions: keywords (an estimate) --------------------------------------------------------
# Matched on normalize_for_search(text): lower case, Eastern Arabic digits as 0-9, alef/yaa/taa marbuta folded
# (so "أسعار" is written "اسعار" and "متوفرة" is "متوفره" here).
_PRICE_WORDS_EN = re.compile(r"\b(price|prices|pricing|priced|cost|costs|how much|quote|quotation|aed|dhs?|dirhams?)\b")
_PRICE_WORDS_AR = ("سعر", "اسعار", "بكم", "كم حق", "تكلفه", "تكلف", "ثمن", "درهم")
_STOCK_WORDS_EN = re.compile(r"\b(stock|available|availability|do you have|have you got|sold out)\b")
_STOCK_WORDS_AR = ("متوفر", "توفر", "موجود", "عندكم", "مخزون", "كميه", "نفذ", "نفد")

_PLACEHOLDER = re.compile(r"^\[[a-z ]+(: [a-z_]+)?\]$")  # what the WhatsApp brand stores for media: "[audio]"
_ARABIC = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]")
_LATIN = re.compile(r"[A-Za-z]")


@dataclass(frozen=True)
class Period:
    key: str
    first_day: date
    last_day: date

    def covers(self, day: date) -> bool:
        return self.first_day <= day <= self.last_day

    def days(self) -> list[date]:
        return [self.first_day + timedelta(days=n) for n in range((self.last_day - self.first_day).days + 1)]


def periods_for(today: date) -> list[Period]:
    """Today, the last 7 and 30 days (today included) and this calendar month, as local dates."""
    return [
        Period("today", today, today),
        Period("7d", today - timedelta(days=6), today),
        Period("30d", today - timedelta(days=29), today),
        Period("month", today.replace(day=1), today),
    ]


def previous_of(period: Period) -> Period:
    """What a period is compared with: today against the same weekday last week, 7 and 30 days against the
    7 and 30 days before them, and this month to date against the same days of last month."""
    if period.key == "today":
        day = period.first_day - timedelta(days=7)
        return Period("today", day, day)
    if period.key == "month":
        last_month_end = period.first_day - timedelta(days=1)
        start = last_month_end.replace(day=1)
        return Period("month", start, min(last_month_end, start.replace(day=1) + (period.last_day - period.first_day)))
    length = (period.last_day - period.first_day).days + 1
    return Period(period.key, period.first_day - timedelta(days=length), period.first_day - timedelta(days=1))


def next_top_of_hour(moment: datetime, tz: ZoneInfo) -> datetime:
    """The next full hour after `moment`, in `tz` (14:00:00 exactly gives 15:00)."""
    local = moment.astimezone(tz)
    return local.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)


class InsightService:
    def __init__(
        self,
        store: InsightStore,
        *,
        timezone: str,
        working_hours: WorkingHours | None,
        weak_match_score: float,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        try:
            self._tz = ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ConfigError(f"client.timezone: unknown timezone {timezone!r}") from exc
        self._working_hours = working_hours
        self._weak = weak_match_score
        self._clock = clock or (lambda: datetime.now(UTC))

    @property
    def timezone(self) -> ZoneInfo:
        return self._tz

    def now(self) -> datetime:
        return self._clock()

    def next_refresh_at(self, after: datetime | None = None) -> datetime:
        return next_top_of_hour(after or self._clock(), self._tz)

    async def latest(self) -> InsightSnapshot | None:
        return await self._store.latest_snapshot()

    def is_stale(self, snapshot: InsightSnapshot | None, max_age: timedelta) -> bool:
        if snapshot is None or snapshot.data.get("version") != SNAPSHOT_VERSION:
            return True
        return self._clock() - snapshot.computed_at >= max_age

    async def refresh(self) -> InsightSnapshot:
        """Compute a snapshot from the database now and save it. Old snapshots are deleted after 30 days."""
        now = self._clock()
        local_today = now.astimezone(self._tz).date()
        periods = periods_for(local_today)
        first_day = min(min(p.first_day, previous_of(p).first_day) for p in periods)
        since = datetime.combine(first_day, time(0), tzinfo=self._tz)
        messages = await self._store.customer_messages(since)
        contacts = await self._store.contacts_active_since(since)
        calls = await self._store.tool_calls(since)
        earliest = await self._store.earliest_customer_message()
        data = compute_snapshot(
            now,
            self._tz,
            messages,
            contacts,
            calls,
            working_hours=self._working_hours,
            weak_match_score=self._weak,
            history_from=earliest.astimezone(self._tz).date() if earliest else None,
        )
        snapshot = await self._store.save_snapshot(now, data)
        await self._store.prune_snapshots(now - KEEP_SNAPSHOTS)
        return snapshot


# --- the maths (pure functions) ----------------------------------------------------------------------------------


def compute_snapshot(
    now: datetime,
    tz: ZoneInfo,
    messages: Sequence[CustomerMessageRow],
    contacts: Sequence[ContactRow],
    calls: Sequence[ToolCallRow],
    *,
    working_hours: WorkingHours | None,
    weak_match_score: float,
    history_from: date | None = None,
) -> dict[str, Any]:
    """Every number on the Insights page, for each period. Only customer chats should be passed in.

    Each period also carries `previous`: the same few numbers for the period before it (see previous_of),
    for the "change" on the KPI cards. It is None when stored data does not reach back to the start of that
    earlier period (`history_from` is the day of the first customer message), because then a 0 would be
    a gap in the data, not a real zero.
    """
    local_now = now.astimezone(tz)
    periods = periods_for(local_now.date())

    local_messages = [(m, m.created_at.astimezone(tz)) for m in messages]
    first_day = {c.conversation_id: c.first_at.astimezone(tz).date() for c in contacts}
    local_calls = [(c, c.created_at.astimezone(tz).date()) for c in calls]

    result: dict[str, Any] = {}
    for period in periods:
        in_period = [(m, at) for m, at in local_messages if period.covers(at.date())]
        calls_in_period = [c for c, day in local_calls if period.covers(day)]
        before = previous_of(period)
        covered = history_from is not None and history_from <= before.first_day
        result[period.key] = {
            "first_day": period.first_day.isoformat(),
            "last_day": period.last_day.isoformat(),
            "leads": _leads(period, in_period, first_day),
            "demand": _demand(in_period, calls_in_period, weak_match_score),
            "busy": _busy(period, in_period, working_hours),
            "previous": _key_numbers(before, local_messages, first_day, working_hours) if covered else None,
        }
    return {
        "version": SNAPSHOT_VERSION,
        "computed_at": local_now.isoformat(),
        "next_at": next_top_of_hour(now, tz).isoformat(),
        "timezone": str(tz.key),
        "working_hours": (
            {"confirmed": working_hours.confirmed, **{d: getattr(working_hours, d) for d in WEEKDAYS}}
            if working_hours
            else None
        ),
        "periods": result,
        "not_tracked": NOT_TRACKED,
    }


def _not_tracked(needs: str) -> dict[str, Any]:
    return {"status": "not_tracked", "needs": needs}


def _key_numbers(
    period: Period,
    local_messages: list[tuple[CustomerMessageRow, datetime]],
    first_day: dict[int, date],
    working_hours: WorkingHours | None,
) -> dict[str, Any]:
    """The KPI-card numbers for one period, to compare the current period with."""
    in_period = [(m, at) for m, at in local_messages if period.covers(at.date())]
    active = {m.conversation_id for m, _ in in_period}
    return {
        "first_day": period.first_day.isoformat(),
        "last_day": period.last_day.isoformat(),
        "new_contacts": sum(1 for cid in active if cid in first_day and period.covers(first_day[cid])),
        "active_contacts": len(active),
        "messages": len(in_period),
        "voice_notes": sum(1 for m, _ in in_period if "audio" in m.media),
        "after_hours": (
            sum(1 for _, at in in_period if not within_hours(at, working_hours)) if working_hours is not None else None
        ),
    }


def _leads(
    period: Period, messages: list[tuple[CustomerMessageRow, datetime]], first_day: dict[int, date]
) -> dict[str, Any]:
    active = {m.conversation_id for m, _ in messages}
    new = {cid for cid in active if cid in first_day and period.covers(first_day[cid])}
    new_by_day = Counter(first_day[cid] for cid in new)
    return {
        "new_contacts": {"status": "live", "value": len(new)},
        "active_contacts": {"status": "live", "value": len(active)},
        "new_vs_returning": {"status": "live", "new": len(new), "returning": len(active - new)},
        "new_contacts_daily": {
            "status": "live",
            "series": [{"date": day.isoformat(), "value": new_by_day.get(day, 0)} for day in period.days()],
        },
        "quote_requests": _not_tracked("quote_requests"),
        "quotes_sent": _not_tracked("quotes_sent"),
        "lost_leads": _not_tracked("lead_outcomes"),
        "lost_at_step": _not_tracked("lead_outcomes"),
    }


def _demand(
    messages: list[tuple[CustomerMessageRow, datetime]], calls: list[ToolCallRow], weak_match_score: float
) -> dict[str, Any]:
    texts = [m.text for m, _ in messages if has_words(m)]
    price = stock = both = 0
    languages = Counter({"arabic": 0, "english": 0, "other": 0})
    for m, _ in messages:
        languages[language_of(m) or "other"] += 1
    for message_text in texts:
        topic = question_topic(message_text)
        price += topic in ("price", "both")
        stock += topic in ("stock", "both")
        both += topic == "both"
    voice = [m for m, _ in messages if "audio" in m.media]
    return {
        "top_products": _top_products(calls, weak_match_score),
        "price_vs_stock": {
            "status": "estimate",
            "price": price,
            "stock": stock,
            "both": both,
            "messages": len(texts),
        },
        "not_found": _not_found(calls, weak_match_score),
        "languages": {"status": "live", **languages, "messages": len(messages)},
        "voice_notes": {
            "status": "live",
            "count": len(voice),
            "chats": len({m.conversation_id for m in voice}),
            "messages": len(messages),
        },
    }


def _busy(
    period: Period, messages: list[tuple[CustomerMessageRow, datetime]], working_hours: WorkingHours | None
) -> dict[str, Any]:
    cells = [[0] * 24 for _ in range(7)]  # rows Monday..Sunday, columns 00..23
    chats_by_day: dict[date, set[int]] = defaultdict(set)
    messages_by_day: Counter[date] = Counter()
    after_hours = 0
    for m, at in messages:
        cells[at.weekday()][at.hour] += 1
        chats_by_day[at.date()].add(m.conversation_id)
        messages_by_day[at.date()] += 1
        if working_hours is not None and not within_hours(at, working_hours):
            after_hours += 1
    if working_hours is None:
        after = _not_tracked("working_hours")
    else:
        after = {
            "status": "live",
            "after_hours": after_hours,
            "messages": len(messages),
            "hours_confirmed": working_hours.confirmed,
        }
    return {
        "heatmap": {"status": "live", "cells": cells, "max": max((max(row) for row in cells), default=0)},
        "chats_daily": {
            "status": "live",
            "series": [
                {"date": day.isoformat(), "chats": len(chats_by_day.get(day, ())), "messages": messages_by_day[day]}
                for day in period.days()
            ],
        },
        "after_hours": after,
        "lost_leads_heatmap": _not_tracked("lead_outcomes"),
    }


# --- message helpers ---------------------------------------------------------------------------------------------


def has_words(message: CustomerMessageRow) -> bool:
    """False for empty text and for the "[audio]" style placeholders stored for media without a caption."""
    text = message.text.strip()
    return bool(text) and not _PLACEHOLDER.match(text)


def language_of(message: CustomerMessageRow) -> str | None:
    """"arabic" or "english" by which script has more letters, or None (no letters, or a media placeholder).

    Arabic typed in Latin letters ("Arabizi") counts as English here.
    """
    if not has_words(message):
        return None
    arabic = len(_ARABIC.findall(message.text))
    latin = len(_LATIN.findall(message.text))
    if arabic == 0 and latin == 0:
        return None
    return "arabic" if arabic > latin else "english"


def question_topic(text: str) -> str | None:
    """"price", "stock", "both" or None, from keywords in English, Arabic and Gulf dialect."""
    folded = normalize_for_search(text)
    is_price = bool(_PRICE_WORDS_EN.search(folded)) or any(word in folded for word in _PRICE_WORDS_AR)
    is_stock = bool(_STOCK_WORDS_EN.search(folded)) or any(word in folded for word in _STOCK_WORDS_AR)
    if is_price and is_stock:
        return "both"
    return "price" if is_price else "stock" if is_stock else None


def within_hours(local: datetime, hours: WorkingHours) -> bool:
    """True when `local` (already in the client's timezone) falls inside that day's opening hours."""
    day = getattr(hours, WEEKDAYS[local.weekday()])
    if day == "closed":
        return False
    start, end = day.split("-")
    return start <= f"{local.hour:02d}:{local.minute:02d}" < end


# --- tool-call helpers -------------------------------------------------------------------------------------------

_FOUND = re.compile(r'"found":\s*(true|false)')
_STRING_FIELD = r'"{}":\s*"((?:[^"\\]|\\.)*)"'
_SCORE = re.compile(r'"match_score":\s*([0-9.]+)')


def parse_result(result: str) -> Any:
    """A tool result as JSON. The audit log cuts long results at 2000 characters, which breaks the JSON; then
    the leading fields (found, code, names, match_score) are read with patterns, since they come first."""
    try:
        return json.loads(result)
    except (json.JSONDecodeError, TypeError):
        pass
    found = _FOUND.search(result or "")
    if not found:
        return None
    parsed: dict[str, Any] = {"found": found.group(1) == "true"}
    for key in ("code", "name_en", "name_ar"):
        match = re.search(_STRING_FIELD.format(key), result)
        if match:
            try:
                parsed[key] = json.loads(f'"{match.group(1)}"')
            except json.JSONDecodeError:
                parsed[key] = match.group(1)
    score = _SCORE.search(result)
    if score:
        parsed["match_score"] = float(score.group(1))
    return parsed


def _found_products(calls: Iterable[ToolCallRow], weak_match_score: float) -> Iterable[tuple[ToolCallRow, dict[str, Any]]]:
    """(call, product) for every lookup that found a product the agent could talk about."""
    for call in calls:
        if call.name not in ("quote_price", "product_details"):
            continue
        result = parse_result(call.result)
        if not isinstance(result, dict) or result.get("found") is not True or not result.get("code"):
            continue
        score = result.get("match_score")
        if call.name == "quote_price" and isinstance(score, int | float) and score < weak_match_score:
            continue  # a weak match is probably a different product: it counts under "not found" instead
        yield call, result


def _top_products(calls: list[ToolCallRow], weak_match_score: float) -> dict[str, Any]:
    chats: dict[str, set[int]] = defaultdict(set)
    asks: Counter[str] = Counter()
    names: dict[str, dict[str, Any]] = {}
    for call, product in _found_products(calls, weak_match_score):
        code = str(product["code"])
        chats[code].add(call.conversation_id)
        asks[code] += 1
        names.setdefault(code, {"name_en": product.get("name_en"), "name_ar": product.get("name_ar")})
    ranked = sorted(chats, key=lambda code: (-len(chats[code]), -asks[code], code))[:TOP_N]
    return {
        "status": "live",
        "lookups": sum(asks.values()),
        "items": [{"code": code, **names[code], "chats": len(chats[code]), "asks": asks[code]} for code in ranked],
    }


def _not_found(calls: list[ToolCallRow], weak_match_score: float) -> dict[str, Any]:
    """Product searches with no match, or only a weak one, from quote_price and search_products."""
    searches = no_match = weak = 0
    misses: dict[str, Counter[str]] = defaultdict(Counter)  # folded query -> how it was written
    kinds: dict[str, Counter[str]] = defaultdict(Counter)
    for call in calls:
        if call.name not in ("quote_price", "search_products"):
            continue
        query = str(call.args.get("query") or "").strip()
        result = parse_result(call.result)
        if result is None or (isinstance(result, dict) and "error" in result):
            continue  # the tool failed: that says nothing about the catalogue
        searches += 1
        kind = None
        if call.name == "search_products":
            if isinstance(result, list) and not result:
                kind = "none"
        elif isinstance(result, dict):
            score = result.get("match_score")
            if result.get("found") is False:
                kind = "none"
            elif isinstance(score, int | float) and score < weak_match_score:
                kind = "weak"
        if kind is None:
            continue
        no_match += kind == "none"
        weak += kind == "weak"
        if query:
            key = normalize_for_search(query)
            misses[key][query] += 1
            kinds[key][kind] += 1
    ranked = sorted(misses, key=lambda key: (-sum(misses[key].values()), key))[:TOP_N]
    return {
        "status": "live",
        "searches": searches,
        "no_match": no_match,
        "weak_match": weak,
        "top": [
            {
                "query": misses[key].most_common(1)[0][0],
                "count": sum(misses[key].values()),
                "kind": kinds[key].most_common(1)[0][0],
            }
            for key in ranked
        ],
    }
