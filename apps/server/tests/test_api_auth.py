"""The API's login wall: every route needs a session except a short public list, plus the login routes over HTTP."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pyotp
import pytest
import yaml
from fastapi.routing import APIRoute

from yyai.bootstrap import build
from yyai.core.config import load_config
from yyai.core.types import StaffRole
from yyai.entry.api.app import PUBLIC_ROUTES, SESSION_COOKIE, create_app
from yyai.workflows.container import Workflows

PASSWORD = "a long enough password"


# --- every route is locked unless it is on the public list (no database needed) ------------------------------------


class NoSessions:
    async def session(self, token: str | None) -> None:
        return None


def locked_app() -> Any:
    workflows = SimpleNamespace(staff=NoSessions(), aclose=_nothing)
    return create_app(workflows)  # type: ignore[arg-type]


async def _nothing() -> None:
    return None


def test_the_public_routes_are_exactly_health_webhooks_and_login() -> None:
    assert PUBLIC_ROUTES == {
        ("GET", "/api/health"),
        ("GET", "/api/webhooks/{channel}"),
        ("POST", "/api/webhooks/{channel}"),
        ("POST", "/api/auth/login"),
        ("POST", "/api/auth/logout"),
    }


async def test_every_other_route_answers_401_without_a_session() -> None:
    app = locked_app()
    routes = [(method, route.path) for route in app.routes if isinstance(route, APIRoute) for method in route.methods]
    locked = [(method, path) for method, path in routes if (method, path) not in PUBLIC_ROUTES]
    # The routes that were open before the web app, and the new ones, are all in the locked list.
    for must_be_locked in [
        ("GET", "/api/conversations"),
        ("GET", "/api/conversations/{conversation_id}/messages"),
        ("POST", "/api/outbox/{outbox_id}/approve"),
        ("POST", "/api/admin/catalogue/sync"),
        ("GET", "/api/assistant/messages"),
        ("POST", "/api/assistant/messages"),
        ("GET", "/api/insights"),
        ("GET", "/api/auth/me"),
    ]:
        assert must_be_locked in locked

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test", cookies={SESSION_COOKIE: "forged"}
    ) as http:
        for method, path in locked:
            url = re.sub(r"\{[^}]+\}", "1", path)
            response = await http.request(method, url, json={})
            assert response.status_code == 401, f"{method} {path} answered {response.status_code}"
            assert response.json() == {"detail": "Log in first"}


async def test_api_docs_are_switched_off() -> None:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=locked_app()), base_url="https://test") as http:
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert (await http.get(path)).status_code == 404


# --- logging in over HTTP (needs the dev Postgres) ----------------------------------------------------------------


@pytest.fixture
async def api(clean_database: str, tmp_path: Path, kahraman_dir: Path) -> AsyncIterator[tuple[httpx.AsyncClient, Workflows]]:
    raw = yaml.safe_load((kahraman_dir / "config.yaml").read_text(encoding="utf-8"))
    raw["database_url"] = clean_database
    raw["models"]["chat.default"].update(base_url="https://model.test/v1", api_key="k", external=False)
    raw["channels"]["whatsapp"]["settings"].update(
        phone_number_id="1", access_token="t", app_secret="s", verify_token="v"
    )
    raw["auth"] = {"max_failures_per_user": 2}
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    workflows = build(load_config(path))
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(workflows)), base_url="https://test")
    try:
        yield http, workflows
    finally:
        await http.aclose()
        await workflows.aclose()


async def add_user(workflows: Workflows, name: str = "sara", role: StaffRole = StaffRole.SALES) -> str:
    """Create a user and return their 2FA secret."""
    return (await workflows.staff.add_user(name, role, PASSWORD)).totp_secret


@pytest.mark.db
async def test_login_sets_a_strict_secure_httponly_cookie_and_me_works(api) -> None:
    http, workflows = api
    secret = await add_user(workflows)

    response = await http.post(
        "/api/auth/login", json={"username": "sara", "password": PASSWORD, "code": pyotp.TOTP(secret).now()}
    )

    assert response.status_code == 200
    assert response.json() == {
        "user": {
            "id": 1,
            "username": "sara",
            "display_name": None,
            "role": "sales",
            "permissions": ["approve", "assistant", "chats", "insights"],
        }
    }
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{SESSION_COOKIE}=")
    for flag in ("HttpOnly", "Secure", "SameSite=strict", "Path=/", "Max-Age=43200"):
        assert flag.lower() in cookie.lower()
    assert response.headers["cache-control"] == "no-store"
    me = await http.get("/api/auth/me")
    assert (me.status_code, me.json()["user"]["username"]) == (200, "sara")


@pytest.mark.db
async def test_a_failed_login_is_a_plain_401_and_never_says_which_part_was_wrong(api) -> None:
    http, workflows = api
    await add_user(workflows)

    for body in (
        {"username": "sara", "password": "wrong password!", "code": "123456"},
        {"username": "nobody", "password": PASSWORD, "code": "123456"},
    ):
        response = await http.post("/api/auth/login", json=body)
        assert (response.status_code, response.json()) == (401, {"detail": "Wrong username, password or code"})
        assert "set-cookie" not in response.headers


@pytest.mark.db
async def test_too_many_failures_answer_429_with_retry_after(api) -> None:
    http, workflows = api
    secret = await add_user(workflows)
    for _ in range(2):  # max_failures_per_user is 2 in this config
        await http.post("/api/auth/login", json={"username": "sara", "password": "wrong password!", "code": "1"})

    response = await http.post(
        "/api/auth/login", json={"username": "sara", "password": PASSWORD, "code": pyotp.TOTP(secret).now()}
    )

    assert response.status_code == 429
    assert 0 < int(response.headers["retry-after"]) <= 15 * 60 + 1


@pytest.mark.db
async def test_logout_ends_the_session_and_clears_the_cookie(api) -> None:
    http, workflows = api
    secret = await add_user(workflows)
    await http.post("/api/auth/login", json={"username": "sara", "password": PASSWORD, "code": pyotp.TOTP(secret).now()})
    token = http.cookies[SESSION_COOKIE]

    response = await http.post("/api/auth/logout")

    assert response.status_code == 200
    assert 'yyai_session=""' in response.headers["set-cookie"] or "Max-Age=0" in response.headers["set-cookie"]
    replay = httpx.AsyncClient(transport=http._transport, base_url="https://test", cookies={SESSION_COOKIE: token})
    async with replay:
        assert (await replay.get("/api/auth/me")).status_code == 401  # the old cookie no longer works


@pytest.mark.db
async def test_the_cookie_is_not_sent_over_plain_http(api) -> None:
    """A Secure cookie stays on https, which is why Caddy serves the app over HTTPS (docs/decisions/0014)."""
    http, workflows = api
    secret = await add_user(workflows)
    await http.post("/api/auth/login", json={"username": "sara", "password": PASSWORD, "code": pyotp.TOTP(secret).now()})

    plain = httpx.AsyncClient(transport=http._transport, base_url="http://test", cookies=http.cookies)
    async with plain:
        assert (await plain.get("/api/auth/me")).status_code == 401
