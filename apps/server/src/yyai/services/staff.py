"""Staff logins for the web app: passwords, two-factor codes, sessions, throttling and roles (docs/decisions/0014).

- Passwords are hashed with argon2id. A wrong username costs the same time as a wrong password, so the reply
  time does not reveal which usernames exist.
- The second factor is a 6-digit TOTP code from an authenticator app (RFC 6238, 30-second steps). A code is
  accepted once only, and one step either side of now is allowed for clock drift.
- A session is a random token in an HttpOnly cookie. Only its SHA-256 is stored. It ends `session_hours` after
  login, or after `idle_minutes` without a request, whichever comes first.
- Too many failures for one username, or from one address, lock logins for the rest of the window.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import re
import secrets
import unicodedata
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from yyai.core.config import AuthConfig
from yyai.core.text import western_digits
from yyai.core.types import LoginOutcome, NewStaffUser, StaffRole, StaffSession, StaffUser
from yyai.handlers.persistence.staff import StaffStore

logger = logging.getLogger(__name__)

# What each role may do. The web app hides what a role cannot use; the API refuses it.
PERMISSIONS: dict[StaffRole, frozenset[str]] = {
    StaffRole.VIEWER: frozenset({"chats", "insights"}),
    StaffRole.SALES: frozenset({"chats", "insights", "assistant", "approve"}),
    StaffRole.ADMIN: frozenset({"chats", "insights", "assistant", "approve", "admin"}),
}

USERNAME = re.compile(r"^[a-z0-9][a-z0-9._-]{1,31}$")
MIN_PASSWORD_CHARS = 12
MAX_PASSWORD_CHARS = 256
TOTP_STEP_S = 30
TOTP_DRIFT_STEPS = 1
TOUCH_EVERY = timedelta(seconds=60)  # how often a busy session's "last seen" is written
KEEP_ATTEMPTS = timedelta(days=30)
LOGIN_FAILED = "Wrong username, password or code"


class StaffService:
    def __init__(
        self,
        store: StaffStore,
        auth: AuthConfig,
        *,
        issuer: str,
        clock: Callable[[], datetime] | None = None,
        hasher: PasswordHasher | None = None,
    ) -> None:
        self._store = store
        self._auth = auth
        self._issuer = issuer
        self._clock = clock or (lambda: datetime.now(UTC))
        self._hasher = hasher or PasswordHasher()
        self._dummy_hash: str | None = None

    # --- roles -------------------------------------------------------------

    @staticmethod
    def permissions(user: StaffUser) -> frozenset[str]:
        return PERMISSIONS.get(user.role, frozenset())

    def can(self, user: StaffUser, permission: str) -> bool:
        return permission in self.permissions(user)

    # --- users (the `yyai users` command) ------------------------------------

    @staticmethod
    def clean_username(username: str) -> str:
        """Lower case, 2-32 characters: letters, digits, dot, dash or underscore. Raises ValueError otherwise."""
        name = unicodedata.normalize("NFKC", username).strip().lower()
        if not USERNAME.match(name):
            raise ValueError(
                "A username is 2 to 32 characters: English letters, digits, dot, dash or underscore, "
                "starting with a letter or digit"
            )
        return name

    @staticmethod
    def check_password(password: str) -> None:
        if len(password) < MIN_PASSWORD_CHARS:
            raise ValueError(f"The password must be at least {MIN_PASSWORD_CHARS} characters")
        if len(password) > MAX_PASSWORD_CHARS:
            raise ValueError(f"The password must be at most {MAX_PASSWORD_CHARS} characters")

    async def add_user(
        self, username: str, role: StaffRole, password: str, display_name: str | None = None
    ) -> NewStaffUser:
        """Create a user. Raises ValueError (bad username or password) or Conflict (the name is taken)."""
        name = self.clean_username(username)
        self.check_password(password)
        secret = pyotp.random_base32()
        password_hash = await asyncio.to_thread(self._hasher.hash, password)
        user = await self._store.create_user(name, (display_name or "").strip() or None, role, password_hash, secret)
        return NewStaffUser(user=user, totp_secret=secret, totp_uri=self.totp_uri(user.username, secret))

    async def reset_user(self, username: str, password: str) -> NewStaffUser | None:
        """New password and new 2FA secret (the old authenticator entry stops working). None if no such user."""
        name = self.clean_username(username)
        self.check_password(password)
        secret = pyotp.random_base32()
        password_hash = await asyncio.to_thread(self._hasher.hash, password)
        user = await self._store.reset_credentials(name, password_hash, secret)
        if user is None:
            return None
        return NewStaffUser(user=user, totp_secret=secret, totp_uri=self.totp_uri(user.username, secret))

    async def set_active(self, username: str, active: bool) -> bool:
        return await self._store.set_active(self.clean_username(username), active)

    async def list_users(self) -> list[StaffUser]:
        return await self._store.list_users()

    def totp_uri(self, username: str, secret: str) -> str:
        """The otpauth:// link an authenticator app reads (usually as a QR code)."""
        return pyotp.TOTP(secret, interval=TOTP_STEP_S).provisioning_uri(name=username, issuer_name=self._issuer)

    # --- login ---------------------------------------------------------------

    async def login(
        self, username: str, password: str, code: str, *, ip: str | None, user_agent: str | None
    ) -> LoginOutcome:
        now = self._clock()
        try:
            name = self.clean_username(username)
        except ValueError:
            name = unicodedata.normalize("NFKC", username).strip().lower()[:64] or "-"

        retry_after = await self._throttled(name, ip, now)
        if retry_after is not None:
            await self._store.record_attempt(name, ip, False, "throttled", now)
            logger.warning("Login throttled for %r from %s (%ss left)", name, ip, retry_after)
            return LoginOutcome(ok=False, retry_after_s=retry_after)

        creds = await self._store.credentials(name)
        if creds is None or not creds.user.active:
            await asyncio.to_thread(self._burn_time, password)
            return await self._fail(name, ip, "unknown_user" if creds is None else "inactive", now)
        if not await asyncio.to_thread(self._password_ok, creds.password_hash, password):
            return await self._fail(name, ip, "password", now)
        step = self._totp_step(creds.totp_secret, code, now)
        if step is None:
            return await self._fail(name, ip, "code", now)
        if not await self._store.use_totp_step(creds.user.id, step, now):
            return await self._fail(name, ip, "code_reused", now)

        if self._hasher.check_needs_rehash(creds.password_hash):
            await self._store.update_password_hash(
                creds.user.id, await asyncio.to_thread(self._hasher.hash, password)
            )
        token = secrets.token_urlsafe(32)
        expires_at = now + timedelta(hours=self._auth.session_hours)
        await self._store.create_session(
            _hash_token(token), creds.user.id, now=now, expires_at=expires_at, ip=ip, user_agent=user_agent
        )
        await self._store.record_attempt(name, ip, True, None, now)
        await self._store.prune(now, now - timedelta(minutes=self._auth.idle_minutes), now - KEEP_ATTEMPTS)
        user = creds.user.model_copy(update={"last_login_at": now})
        logger.info("Staff login: %s (%s) from %s", user.username, user.role.value, ip)
        return LoginOutcome(ok=True, user=user, token=token, expires_at=expires_at)

    async def session(self, token: str) -> StaffSession | None:
        """The session behind a cookie value, if it is still valid. Ends it if it has expired or gone idle."""
        if not token or len(token) > 200:
            return None
        token_hash = _hash_token(token)
        found = await self._store.session(token_hash)
        if found is None:
            return None
        now = self._clock()
        idle = timedelta(minutes=self._auth.idle_minutes)
        if now >= found.expires_at or now - found.last_seen_at >= idle:
            await self._store.delete_session(token_hash)
            return None
        if now - found.last_seen_at >= TOUCH_EVERY:
            await self._store.touch_session(token_hash, now)
        return found

    async def logout(self, token: str) -> None:
        if token:
            await self._store.delete_session(_hash_token(token))

    async def audit(self, user: StaffUser | None, action: str, data: dict[str, Any]) -> None:
        await self._store.audit(user.id if user else None, action, {"username": user.username if user else None, **data})

    # --- helpers -------------------------------------------------------------

    async def _throttled(self, name: str, ip: str | None, now: datetime) -> int | None:
        """Seconds until a login may be tried again, or None when it may be tried now."""
        window = timedelta(minutes=self._auth.failure_window_minutes)
        limit = max(self._auth.max_failures_per_user, self._auth.max_failures_per_ip)
        by_user, by_ip = await self._store.recent_failures(name, ip, now - window, limit)
        unlock: list[datetime] = []
        # With N failures allowed, the lock lifts when the Nth newest failure leaves the window.
        for failures, allowed in ((by_user, self._auth.max_failures_per_user), (by_ip, self._auth.max_failures_per_ip)):
            if len(failures) >= allowed:
                unlock.append(failures[allowed - 1] + window)
        if not unlock:
            return None
        return max(1, int((max(unlock) - now).total_seconds()) + 1)

    async def _fail(self, name: str, ip: str | None, reason: str, now: datetime) -> LoginOutcome:
        await self._store.record_attempt(name, ip, False, reason, now)
        logger.info("Staff login failed for %r from %s: %s", name, ip, reason)
        return LoginOutcome(ok=False)

    def _password_ok(self, password_hash: str, password: str) -> bool:
        try:
            return self._hasher.verify(password_hash, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    def _burn_time(self, password: str) -> None:
        """Spend as long as a real password check, so a missing user is not faster to reject."""
        if self._dummy_hash is None:
            self._dummy_hash = self._hasher.hash(secrets.token_hex(16))
        self._password_ok(self._dummy_hash, password)

    @staticmethod
    def _totp_step(secret: str, code: str, now: datetime) -> int | None:
        """The 30-second step `code` belongs to (now, or one step either side), or None if it matches none."""
        digits = re.sub(r"\s", "", western_digits(code or ""))
        if not (len(digits) == 6 and digits.isascii() and digits.isdigit()):
            return None
        totp = pyotp.TOTP(secret, interval=TOTP_STEP_S)
        current = int(now.timestamp()) // TOTP_STEP_S
        for step in range(current - TOTP_DRIFT_STEPS, current + TOTP_DRIFT_STEPS + 1):
            if hmac.compare_digest(totp.generate_otp(step), digits):
                return step
        return None


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
