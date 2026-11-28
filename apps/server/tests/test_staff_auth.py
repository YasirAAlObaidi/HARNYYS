"""Staff login: argon2 passwords, TOTP codes, sessions, throttling and roles, against a real Postgres."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import psycopg
import pyotp
import pytest
from argon2 import PasswordHasher

from yyai.core.config import AuthConfig
from yyai.core.errors import Conflict
from yyai.core.types import LoginOutcome, NewStaffUser, StaffRole
from yyai.handlers.persistence.db import Database
from yyai.handlers.persistence.staff import StaffStore
from yyai.services.staff import StaffService

pytestmark = pytest.mark.db

PASSWORD = "a long enough password"
IP = "192.168.1.20"
START = datetime(2026, 11, 26, 10, 0, 0, tzinfo=UTC)


class Clock:
    def __init__(self, now: datetime = START) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def staff(db: Database, clock: Clock) -> StaffService:
    # Cheap argon2 settings keep the tests fast; production uses the library defaults (argon2id, 64 MiB).
    fast = PasswordHasher(time_cost=1, memory_cost=64, parallelism=1)
    return StaffService(StaffStore(db), AuthConfig(), issuer="Kahraman yyai", clock=clock, hasher=fast)


def code_at(created: NewStaffUser, moment: datetime, steps: int = 0) -> str:
    return pyotp.TOTP(created.totp_secret).at(moment, counter_offset=steps)


async def login(
    staff: StaffService,
    created: NewStaffUser,
    clock: Clock,
    *,
    password: str = PASSWORD,
    code: str | None = None,
    username: str | None = None,
    ip: str = IP,
) -> LoginOutcome:
    return await staff.login(
        username or created.user.username,
        password,
        code if code is not None else code_at(created, clock.now),
        ip=ip,
        user_agent="pytest",
    )


# --- creating users ----------------------------------------------------------------------------------------------


async def test_a_new_user_gets_an_argon2_hash_and_an_authenticator_link(
    staff: StaffService, sql: psycopg.Connection
) -> None:
    created = await staff.add_user("Yasir", StaffRole.ADMIN, PASSWORD, "Yasir A.")

    assert (created.user.username, created.user.role, created.user.display_name) == ("yasir", "admin", "Yasir A.")
    assert created.totp_uri.startswith("otpauth://totp/Kahraman%20yyai:yasir?secret=")
    assert "issuer=Kahraman%20yyai" in created.totp_uri
    row = sql.execute("SELECT password_hash, totp_secret FROM staff_users").fetchone()
    assert row["password_hash"].startswith("$argon2id$")
    assert PASSWORD not in row["password_hash"]
    assert row["totp_secret"] == created.totp_secret


async def test_usernames_are_lower_case_unique_and_checked(staff: StaffService) -> None:
    await staff.add_user("sara", StaffRole.SALES, PASSWORD)
    with pytest.raises(Conflict):
        await staff.add_user("SARA", StaffRole.VIEWER, PASSWORD)
    for bad in ("", "a", "has space", "سارة", "x" * 40, "-dash-first"):
        with pytest.raises(ValueError, match="username"):
            await staff.add_user(bad, StaffRole.SALES, PASSWORD)
    with pytest.raises(ValueError, match="at least 12"):
        await staff.add_user("omar", StaffRole.SALES, "short")


# --- logging in ----------------------------------------------------------------------------------------------------


async def test_password_and_code_log_in_and_the_session_is_stored_hashed(
    staff: StaffService, clock: Clock, sql: psycopg.Connection
) -> None:
    created = await staff.add_user("yasir", StaffRole.ADMIN, PASSWORD)

    outcome = await login(staff, created, clock, username="  YASIR ")

    assert outcome.ok and outcome.token and outcome.user
    assert outcome.user.username == "yasir"
    assert outcome.expires_at == START + timedelta(hours=12)
    stored = sql.execute("SELECT token_hash, ip, user_agent FROM staff_sessions").fetchone()
    assert stored["token_hash"] != outcome.token and len(stored["token_hash"]) == 64
    assert (stored["ip"], stored["user_agent"]) == (IP, "pytest")
    session = await staff.session(outcome.token)
    assert session is not None and session.user.username == "yasir"
    assert await staff.session("not-a-real-token") is None
    attempt = sql.execute("SELECT username, ip, success FROM login_attempts").fetchone()
    assert (attempt["username"], attempt["ip"], attempt["success"]) == ("yasir", IP, True)


async def test_every_kind_of_failure_looks_the_same(staff: StaffService, clock: Clock, sql: psycopg.Connection) -> None:
    created = await staff.add_user("yasir", StaffRole.ADMIN, PASSWORD)
    wrong_code = str((int(code_at(created, clock.now)) + 1) % 1_000_000).zfill(6)

    outcomes = [
        await login(staff, created, clock, password="wrong password!"),
        await login(staff, created, clock, code=wrong_code),
        await login(staff, created, clock, code="12345"),
        await login(staff, created, clock, username="nobody"),
    ]

    assert all(outcome == LoginOutcome(ok=False) for outcome in outcomes)
    reasons = [r["reason"] for r in sql.execute("SELECT reason FROM login_attempts ORDER BY id").fetchall()]
    assert reasons == ["password", "code", "code", "unknown_user"]
    assert sql.execute("SELECT count(*) AS n FROM staff_sessions").fetchone()["n"] == 0


async def test_eastern_arabic_digits_and_spaces_in_the_code_are_accepted(staff: StaffService, clock: Clock) -> None:
    created = await staff.add_user("sara", StaffRole.SALES, PASSWORD)
    code = code_at(created, clock.now)
    arabic = code.translate(str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩"))

    outcome = await login(staff, created, clock, code=f"{arabic[:3]} {arabic[3:]}")

    assert outcome.ok


async def test_a_code_works_once_only(staff: StaffService, clock: Clock, sql: psycopg.Connection) -> None:
    created = await staff.add_user("sara", StaffRole.SALES, PASSWORD)
    code = code_at(created, clock.now)

    assert (await login(staff, created, clock, code=code)).ok
    assert not (await login(staff, created, clock, code=code)).ok
    assert sql.execute("SELECT reason FROM login_attempts ORDER BY id DESC LIMIT 1").fetchone()["reason"] == "code_reused"
    clock.advance(seconds=30)
    assert (await login(staff, created, clock)).ok  # the next code is fine


async def test_one_step_of_clock_drift_is_allowed_but_not_two(staff: StaffService, clock: Clock) -> None:
    created = await staff.add_user("sara", StaffRole.SALES, PASSWORD)

    assert not (await login(staff, created, clock, code=code_at(created, clock.now, steps=-2))).ok
    assert not (await login(staff, created, clock, code=code_at(created, clock.now, steps=2))).ok
    assert (await login(staff, created, clock, code=code_at(created, clock.now, steps=-1))).ok


async def test_a_disabled_user_cannot_log_in_and_loses_their_sessions(staff: StaffService, clock: Clock) -> None:
    created = await staff.add_user("sara", StaffRole.SALES, PASSWORD)
    outcome = await login(staff, created, clock)
    assert outcome.token

    assert await staff.set_active("sara", False)

    assert await staff.session(outcome.token) is None
    clock.advance(seconds=30)
    assert not (await login(staff, created, clock)).ok
    assert await staff.set_active("sara", True)
    assert (await login(staff, created, clock)).ok
    assert not await staff.set_active("nobody", False)


async def test_reset_gives_a_new_password_and_secret_and_ends_sessions(staff: StaffService, clock: Clock) -> None:
    created = await staff.add_user("sara", StaffRole.SALES, PASSWORD)
    old_session = await login(staff, created, clock)

    renewed = await staff.reset_user("sara", "a brand new password")

    assert renewed is not None and renewed.totp_secret != created.totp_secret
    assert await staff.session(old_session.token or "") is None
    clock.advance(seconds=30)
    assert not (await login(staff, created, clock)).ok  # old password and old secret
    assert (await login(staff, renewed, clock, password="a brand new password")).ok
    assert await staff.reset_user("nobody", "a brand new password") is None


# --- sessions ------------------------------------------------------------------------------------------------------


async def test_a_session_ends_after_twelve_hours_even_when_used(staff: StaffService, clock: Clock) -> None:
    created = await staff.add_user("sara", StaffRole.SALES, PASSWORD)
    token = (await login(staff, created, clock)).token or ""

    for _ in range(11):
        clock.advance(hours=1)
        assert await staff.session(token) is not None
    clock.advance(hours=1)
    assert await staff.session(token) is None


async def test_a_session_ends_after_two_idle_hours(staff: StaffService, clock: Clock) -> None:
    created = await staff.add_user("sara", StaffRole.SALES, PASSWORD)
    token = (await login(staff, created, clock)).token or ""

    clock.advance(minutes=119)
    assert await staff.session(token) is not None  # used just in time: the idle clock starts again
    clock.advance(minutes=119)
    assert await staff.session(token) is not None
    clock.advance(minutes=120)
    assert await staff.session(token) is None
    assert await staff.session(token) is None  # and it was deleted, not just refused


async def test_logout_ends_the_session(staff: StaffService, clock: Clock) -> None:
    created = await staff.add_user("sara", StaffRole.SALES, PASSWORD)
    token = (await login(staff, created, clock)).token or ""

    await staff.logout(token)

    assert await staff.session(token) is None


# --- throttling ----------------------------------------------------------------------------------------------------


async def test_five_failures_lock_the_username_for_the_rest_of_the_window(staff: StaffService, clock: Clock) -> None:
    created = await staff.add_user("sara", StaffRole.SALES, PASSWORD)
    for _ in range(5):
        assert (await login(staff, created, clock, password="wrong password!")).retry_after_s is None
        clock.advance(seconds=10)

    locked = await login(staff, created, clock)  # even the right password and code

    assert not locked.ok
    # The oldest of the five failures was at 10:00:00 and leaves the 15-minute window at 10:15:00; now is 10:00:50.
    assert locked.retry_after_s == 15 * 60 - 50 + 1
    clock.advance(minutes=5)
    assert (await login(staff, created, clock)).retry_after_s is not None  # throttled tries do not reset the wait
    clock.advance(minutes=10)
    assert (await login(staff, created, clock)).ok


async def test_a_success_clears_earlier_failures(staff: StaffService, clock: Clock) -> None:
    created = await staff.add_user("sara", StaffRole.SALES, PASSWORD)
    for _ in range(4):
        await login(staff, created, clock, password="wrong password!")
    assert (await login(staff, created, clock)).ok

    clock.advance(seconds=30)
    await login(staff, created, clock, password="wrong password!")
    clock.advance(seconds=30)
    assert (await login(staff, created, clock)).ok  # one failure since the success, not five


async def test_many_failures_from_one_address_lock_every_username_there(db: Database, clock: Clock) -> None:
    fast = PasswordHasher(time_cost=1, memory_cost=64, parallelism=1)
    staff = StaffService(
        StaffStore(db), AuthConfig(max_failures_per_ip=3), issuer="Kahraman yyai", clock=clock, hasher=fast
    )
    created = await staff.add_user("sara", StaffRole.SALES, PASSWORD)
    for name in ("a1", "b2", "c3"):
        await staff.login(name, PASSWORD, "000000", ip=IP, user_agent=None)

    assert (await login(staff, created, clock)).retry_after_s is not None
    assert (await login(staff, created, clock, ip="192.168.1.99")).ok  # another address is not affected


# --- roles -------------------------------------------------------------------------------------------------------


async def test_roles(staff: StaffService) -> None:
    viewer = (await staff.add_user("v1", StaffRole.VIEWER, PASSWORD)).user
    sales = (await staff.add_user("s1", StaffRole.SALES, PASSWORD)).user
    admin = (await staff.add_user("a1", StaffRole.ADMIN, PASSWORD)).user

    assert staff.permissions(viewer) == {"chats", "insights"}
    assert staff.permissions(sales) == {"chats", "insights", "assistant", "approve"}
    assert staff.permissions(admin) == {"chats", "insights", "assistant", "approve", "admin"}
    assert not staff.can(viewer, "assistant") and staff.can(sales, "assistant") and not staff.can(sales, "admin")
