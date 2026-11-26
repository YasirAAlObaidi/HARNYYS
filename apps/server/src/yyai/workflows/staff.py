"""Staff logins and the user list: the web app's login, its session check, and the `yyai users` command."""

from __future__ import annotations

from typing import Any

from yyai.core.types import LoginOutcome, NewStaffUser, StaffRole, StaffSession, StaffUser
from yyai.services.staff import StaffService


class StaffWorkflow:
    def __init__(self, staff: StaffService) -> None:
        self._staff = staff

    # --- the web app -----------------------------------------------------------

    async def login(
        self, username: str, password: str, code: str, *, ip: str | None, user_agent: str | None
    ) -> LoginOutcome:
        return await self._staff.login(username, password, code, ip=ip, user_agent=user_agent)

    async def session(self, token: str | None) -> StaffSession | None:
        return await self._staff.session(token) if token else None

    async def logout(self, token: str | None) -> None:
        if token:
            await self._staff.logout(token)

    def permissions(self, user: StaffUser) -> list[str]:
        return sorted(self._staff.permissions(user))

    def can(self, user: StaffUser, permission: str) -> bool:
        return self._staff.can(user, permission)

    async def audit(self, user: StaffUser | None, action: str, data: dict[str, Any] | None = None) -> None:
        """Record a staff action (who, what) in the audit log."""
        await self._staff.audit(user, action, data or {})

    # --- the `yyai users` command ----------------------------------------------

    async def add_user(
        self, username: str, role: StaffRole, password: str, display_name: str | None = None
    ) -> NewStaffUser:
        return await self._staff.add_user(username, role, password, display_name)

    async def reset_user(self, username: str, password: str) -> NewStaffUser | None:
        return await self._staff.reset_user(username, password)

    async def set_active(self, username: str, active: bool) -> bool:
        return await self._staff.set_active(username, active)

    async def list_users(self) -> list[StaffUser]:
        return await self._staff.list_users()
