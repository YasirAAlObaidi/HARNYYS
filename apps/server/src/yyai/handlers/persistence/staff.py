"""Staff users, their sessions and login attempts, for the web app login (docs/decisions/0014).

Sessions are stored by the SHA-256 of their token, never the token itself. Rules (how long a session lasts,
how many failures lock a login) live in the staff service; this store only reads and writes rows. Times come
from the service's clock, never the database's, so every comparison uses one clock.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from yyai.core.errors import Conflict
from yyai.core.types import StaffCredentials, StaffRole, StaffSession, StaffUser
from yyai.handlers.persistence.db import Database

_USER_COLUMNS = "u.id, u.username, u.display_name, u.role, u.active, u.created_at, u.last_login_at"


class StaffStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    # --- users -------------------------------------------------------------

    async def create_user(
        self, username: str, display_name: str | None, role: StaffRole, password_hash: str, totp_secret: str
    ) -> StaffUser:
        try:
            async with self._db.engine.begin() as conn:
                row = (
                    await conn.execute(
                        text(
                            f"""
                            INSERT INTO staff_users AS u (username, display_name, role, password_hash, totp_secret)
                            VALUES (:username, :display_name, :role, :password_hash, :totp_secret)
                            RETURNING {_USER_COLUMNS}
                            """
                        ),
                        {
                            "username": username,
                            "display_name": display_name,
                            "role": role.value,
                            "password_hash": password_hash,
                            "totp_secret": totp_secret,
                        },
                    )
                ).one()
        except IntegrityError as exc:
            raise Conflict(f"A staff user called '{username}' already exists") from exc
        return _user(row._asdict())

    async def credentials(self, username: str) -> StaffCredentials | None:
        async with self._db.engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        f"""
                        SELECT {_USER_COLUMNS}, u.password_hash, u.totp_secret, u.totp_last_step
                        FROM staff_users u WHERE u.username = :username
                        """
                    ),
                    {"username": username},
                )
            ).first()
        if row is None:
            return None
        data = row._asdict()
        return StaffCredentials(
            user=_user(data),
            password_hash=data["password_hash"],
            totp_secret=data["totp_secret"],
            totp_last_step=data["totp_last_step"],
        )

    async def list_users(self) -> list[StaffUser]:
        async with self._db.engine.connect() as conn:
            rows = (await conn.execute(text(f"SELECT {_USER_COLUMNS} FROM staff_users u ORDER BY u.username"))).all()
        return [_user(row._asdict()) for row in rows]

    async def set_active(self, username: str, active: bool) -> bool:
        """Switch a user on or off. Switching off also ends every session they have."""
        async with self._db.engine.begin() as conn:
            user_id = (
                await conn.execute(
                    text("UPDATE staff_users SET active = :active WHERE username = :username RETURNING id"),
                    {"username": username, "active": active},
                )
            ).scalar_one_or_none()
            if user_id is not None and not active:
                await conn.execute(text("DELETE FROM staff_sessions WHERE user_id = :id"), {"id": user_id})
        return user_id is not None

    async def reset_credentials(self, username: str, password_hash: str, totp_secret: str) -> StaffUser | None:
        """New password and 2FA secret. Ends every session the user has."""
        async with self._db.engine.begin() as conn:
            row = (
                await conn.execute(
                    text(
                        f"""
                        UPDATE staff_users AS u
                        SET password_hash = :password_hash, totp_secret = :totp_secret, totp_last_step = NULL
                        WHERE u.username = :username
                        RETURNING {_USER_COLUMNS}
                        """
                    ),
                    {"username": username, "password_hash": password_hash, "totp_secret": totp_secret},
                )
            ).first()
            if row is None:
                return None
            await conn.execute(text("DELETE FROM staff_sessions WHERE user_id = :id"), {"id": row.id})
        return _user(row._asdict())

    async def use_totp_step(self, user_id: int, step: int, now: datetime) -> bool:
        """Accept a 2FA code once: True only if `step` is newer than the last code this user used."""
        async with self._db.engine.begin() as conn:
            updated = (
                await conn.execute(
                    text(
                        """
                        UPDATE staff_users SET totp_last_step = :step, last_login_at = :now
                        WHERE id = :id AND (totp_last_step IS NULL OR totp_last_step < :step)
                        RETURNING id
                        """
                    ),
                    {"id": user_id, "step": step, "now": now},
                )
            ).scalar_one_or_none()
        return updated is not None

    async def update_password_hash(self, user_id: int, password_hash: str) -> None:
        """Store a re-hashed password (after the argon2 settings change). The password itself is unchanged."""
        async with self._db.engine.begin() as conn:
            await conn.execute(
                text("UPDATE staff_users SET password_hash = :hash WHERE id = :id"),
                {"id": user_id, "hash": password_hash},
            )

    # --- login attempts ----------------------------------------------------

    async def record_attempt(
        self, username: str, ip: str | None, success: bool, reason: str | None, now: datetime
    ) -> None:
        async with self._db.engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO login_attempts (username, ip, success, reason, at)"
                    " VALUES (:username, :ip, :success, :reason, :now)"
                ),
                {"username": username[:200], "ip": ip, "success": success, "reason": reason, "now": now},
            )

    async def recent_failures(
        self, username: str, ip: str | None, since: datetime, limit: int
    ) -> tuple[list[datetime], list[datetime]]:
        """Failed attempts since `since`, newest first: (for this username, from this address).

        Failures for a username stop counting once that username logs in successfully. Attempts refused
        because of the throttle itself do not count, so waiting out the lock always works.
        """
        async with self._db.engine.connect() as conn:
            by_user = (
                await conn.execute(
                    text(
                        """
                        SELECT at FROM login_attempts
                        WHERE username = :username AND NOT success AND reason IS DISTINCT FROM 'throttled'
                          AND at >= :since
                          AND at > COALESCE(
                            (SELECT max(at) FROM login_attempts WHERE username = :username AND success),
                            '-infinity')
                        ORDER BY at DESC LIMIT :limit
                        """
                    ),
                    {"username": username, "since": since, "limit": limit},
                )
            ).scalars().all()
            by_ip: list[datetime] = []
            if ip:
                by_ip = list(
                    (
                        await conn.execute(
                            text(
                                """
                                SELECT at FROM login_attempts
                                WHERE ip = :ip AND NOT success AND reason IS DISTINCT FROM 'throttled'
                                  AND at >= :since
                                ORDER BY at DESC LIMIT :limit
                                """
                            ),
                            {"ip": ip, "since": since, "limit": limit},
                        )
                    ).scalars().all()
                )
        return list(by_user), by_ip

    # --- sessions ----------------------------------------------------------

    async def create_session(
        self,
        token_hash: str,
        user_id: int,
        *,
        now: datetime,
        expires_at: datetime,
        ip: str | None,
        user_agent: str | None,
    ) -> None:
        async with self._db.engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO staff_sessions
                      (token_hash, user_id, created_at, last_seen_at, expires_at, ip, user_agent)
                    VALUES (:token_hash, :user_id, :now, :now, :expires_at, :ip, :user_agent)
                    """
                ),
                {
                    "token_hash": token_hash,
                    "user_id": user_id,
                    "now": now,
                    "expires_at": expires_at,
                    "ip": ip,
                    "user_agent": (user_agent or "")[:300] or None,
                },
            )

    async def session(self, token_hash: str) -> StaffSession | None:
        """The session and its user, if the session exists and the user is still active."""
        async with self._db.engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        f"""
                        SELECT {_USER_COLUMNS},
                               s.created_at AS session_created_at, s.last_seen_at, s.expires_at
                        FROM staff_sessions s JOIN staff_users u ON u.id = s.user_id
                        WHERE s.token_hash = :token_hash AND u.active
                        """
                    ),
                    {"token_hash": token_hash},
                )
            ).first()
        if row is None:
            return None
        data = row._asdict()
        return StaffSession(
            user=_user(data),
            created_at=data["session_created_at"],
            last_seen_at=data["last_seen_at"],
            expires_at=data["expires_at"],
        )

    async def touch_session(self, token_hash: str, now: datetime) -> None:
        async with self._db.engine.begin() as conn:
            await conn.execute(
                text("UPDATE staff_sessions SET last_seen_at = :now WHERE token_hash = :token_hash"),
                {"token_hash": token_hash, "now": now},
            )

    async def delete_session(self, token_hash: str) -> None:
        async with self._db.engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM staff_sessions WHERE token_hash = :token_hash"), {"token_hash": token_hash}
            )

    async def prune(self, now: datetime, idle_before: datetime, attempts_before: datetime) -> None:
        """Delete expired and idle sessions, and login attempts older than the retention period."""
        async with self._db.engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM staff_sessions WHERE expires_at < :now OR last_seen_at < :idle"),
                {"now": now, "idle": idle_before},
            )
            await conn.execute(text("DELETE FROM login_attempts WHERE at < :before"), {"before": attempts_before})

    # --- audit ---------------------------------------------------------------

    async def audit(self, user_id: int | None, action: str, data: dict[str, Any]) -> None:
        """Write a staff action to the shared audit log (kind 'staff')."""
        async with self._db.engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO audit_log (kind, name, data, staff_user_id)"
                    " VALUES ('staff', :name, CAST(:data AS jsonb), :user_id)"
                ),
                {"name": action, "data": json.dumps(data, ensure_ascii=False, default=str), "user_id": user_id},
            )


def _user(data: dict[str, Any]) -> StaffUser:
    return StaffUser(
        id=data["id"],
        username=data["username"],
        display_name=data["display_name"],
        role=StaffRole(data["role"]),
        active=data["active"],
        created_at=data["created_at"],
        last_login_at=data["last_login_at"],
    )
