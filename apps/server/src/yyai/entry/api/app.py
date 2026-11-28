"""The HTTP API: webhooks, the staff web app's routes and admin actions.

Routes only translate HTTP to workflow calls and back. They hold no business
rules and never wait on a model: a webhook saves the message, queues the turn
and answers at once (docs/decisions/0007).

Every route needs a logged-in staff session, except the few in PUBLIC_ROUTES
(docs/decisions/0014). The check runs for all routes by default, so a new route
is locked until someone deliberately adds it to that list.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from yyai.core.errors import IntegrationError, NotFound, SignatureError
from yyai.core.types import StaffUser
from yyai.workflows.container import Workflows

logger = logging.getLogger(__name__)

SESSION_COOKIE = "yyai_session"
# (method, route template) pairs that work without a login. Webhooks check their own signatures, and only
# signed channels (WhatsApp) are reachable through them (workflows/inbound.py).
PUBLIC_ROUTES = frozenset(
    {
        ("GET", "/api/health"),
        ("GET", "/api/webhooks/{channel}"),
        ("POST", "/api/webhooks/{channel}"),
        ("POST", "/api/auth/login"),
        ("POST", "/api/auth/logout"),
    }
)
LOGIN_FAILED = "Wrong username, password or code"


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)
    code: str = Field(min_length=1, max_length=16, description="The 6-digit code from the authenticator app")


class AssistantBody(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    client_id: str | None = Field(None, max_length=64, description="Random id from the browser, so a retry is safe")


async def staff_guard(request: Request) -> None:
    """Runs before every route. Public routes pass; all others need a valid session cookie."""
    route = request.scope.get("route")
    if (request.method, getattr(route, "path", None)) in PUBLIC_ROUTES:
        return
    workflows: Workflows = request.app.state.workflows
    session = await workflows.staff.session(request.cookies.get(SESSION_COOKIE))
    if session is None:
        raise HTTPException(status_code=401, detail="Log in first")
    request.state.staff = session.user


def require(permission: str) -> Callable[[Request], Awaitable[StaffUser]]:
    """A dependency that gives the logged-in user, and refuses with 403 when their role lacks `permission`."""

    async def check(request: Request) -> StaffUser:
        user: StaffUser | None = getattr(request.state, "staff", None)
        if user is None:
            raise HTTPException(status_code=401, detail="Log in first")
        if not request.app.state.workflows.staff.can(user, permission):
            raise HTTPException(status_code=403, detail="Your role cannot do this")
        return user

    return check


# The logged-in user, checked for one permission (see PERMISSIONS in services/staff.py).
ChatsUser = Annotated[StaffUser, Depends(require("chats"))]
ApproverUser = Annotated[StaffUser, Depends(require("approve"))]
AssistantUser = Annotated[StaffUser, Depends(require("assistant"))]
InsightsUser = Annotated[StaffUser, Depends(require("insights"))]
AdminUser = Annotated[StaffUser, Depends(require("admin"))]


def create_app(workflows: Workflows, *, session_max_age_s: int = 12 * 3600) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await workflows.aclose()

    # No /docs or /openapi.json: the API is private, and its schema would only help someone probing it.
    app = FastAPI(
        title="yyai",
        lifespan=lifespan,
        dependencies=[Depends(staff_guard)],
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.workflows = workflows

    @app.middleware("http")
    async def no_caching(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        response = await call_next(request)
        # Chats and numbers are private: browsers and proxies must not keep copies.
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.exception_handler(IntegrationError)
    async def integration_error(request: Request, exc: IntegrationError) -> JSONResponse:
        logger.warning("Outside system failed during %s %s: %s", request.method, request.url.path, exc)
        return JSONResponse(status_code=502, content={"detail": str(exc)})

    # --- health ----------------------------------------------------------

    @app.get("/api/health")
    async def health() -> JSONResponse:
        report = await workflows.maintenance.health()
        return JSONResponse(status_code=200 if report.get("status") == "ok" else 503, content=report)

    # --- webhooks --------------------------------------------------------

    @app.get("/api/webhooks/{channel}")
    async def verify_webhook(channel: str, request: Request) -> PlainTextResponse:
        try:
            challenge = workflows.inbound.verify(channel, dict(request.query_params))
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if challenge is None:
            raise HTTPException(status_code=403, detail="Verification failed")
        return PlainTextResponse(challenge)

    @app.post("/api/webhooks/{channel}")
    async def receive_webhook(channel: str, request: Request) -> dict[str, int]:
        body = await request.body()
        try:
            return await workflows.inbound.accept(channel, dict(request.headers), body)
        except SignatureError as exc:
            raise HTTPException(status_code=401, detail="Invalid signature") from exc
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            # Bad JSON, a payload that does not validate, or the workflow's InvalidPayload.
            logger.warning("Rejected %s webhook: %s", channel, exc)
            raise HTTPException(status_code=400, detail="Could not read the request body") from exc

    # --- staff login -------------------------------------------------------

    def user_json(user: StaffUser) -> dict[str, Any]:
        return {
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "role": user.role.value,
            "permissions": workflows.staff.permissions(user),
        }

    @app.post("/api/auth/login")
    async def login(body: LoginBody, request: Request, response: Response) -> dict[str, Any]:
        outcome = await workflows.staff.login(
            body.username,
            body.password,
            body.code,
            ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        if outcome.retry_after_s is not None:
            raise HTTPException(
                status_code=429,
                detail="Too many failed logins. Wait a few minutes, then try again.",
                headers={"Retry-After": str(outcome.retry_after_s)},
            )
        if not outcome.ok or outcome.user is None or outcome.token is None:
            raise HTTPException(status_code=401, detail=LOGIN_FAILED)
        response.set_cookie(
            SESSION_COOKIE,
            outcome.token,
            max_age=session_max_age_s,
            path="/",
            secure=True,
            httponly=True,
            samesite="strict",
        )
        return {"user": user_json(outcome.user)}

    @app.post("/api/auth/logout")
    async def logout(request: Request, response: Response) -> dict[str, bool]:
        await workflows.staff.logout(request.cookies.get(SESSION_COOKIE))
        response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="strict")
        return {"logged_out": True}

    @app.get("/api/auth/me")
    async def me(request: Request) -> dict[str, Any]:
        return {"user": user_json(request.state.staff)}

    # --- page 1: chats (read-only) -------------------------------------------

    @app.get("/api/conversations")
    async def list_conversations(
        user: ChatsUser,
        limit: int = Query(50, ge=1, le=500),
        q: str | None = Query(None, max_length=200, description="Name, number or words in the chat"),
    ) -> list[dict[str, Any]]:
        conversations = await workflows.queries.list_conversations(limit, q)
        return [c.model_dump(mode="json", exclude={"internal"}) for c in conversations]

    @app.get("/api/conversations/{conversation_id}")
    async def conversation(conversation_id: int, user: ChatsUser) -> dict[str, Any]:
        try:
            found = await workflows.queries.conversation(conversation_id)
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return found.model_dump(mode="json", exclude={"internal"})

    @app.get("/api/conversations/{conversation_id}/messages")
    async def conversation_messages(
        conversation_id: int,
        user: ChatsUser,
        limit: int = Query(100, ge=1, le=1000),
        after_id: int | None = Query(None, ge=0),
    ) -> list[dict[str, Any]]:
        try:
            messages = await workflows.queries.messages(conversation_id, limit, after_id)
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return [m.model_dump(mode="json") for m in messages]

    @app.post("/api/outbox/{outbox_id}/approve")
    async def approve_outbox(outbox_id: int, user: ApproverUser) -> dict[str, Any]:
        if not await workflows.queries.approve(outbox_id):
            raise HTTPException(status_code=404, detail="No reply is awaiting approval with that id")
        await workflows.staff.audit(user, "approve_reply", {"outbox_id": outbox_id})
        return {"approved": True, "id": outbox_id}

    # --- page 2: the staff assistant -----------------------------------------

    @app.get("/api/assistant/messages")
    async def assistant_messages(user: AssistantUser, after_id: int | None = Query(None, ge=0)) -> dict[str, Any]:
        return await workflows.assistant.history(user, after_id)

    @app.post("/api/assistant/messages")
    async def assistant_send(body: AssistantBody, user: AssistantUser) -> dict[str, Any]:
        try:
            return await workflows.assistant.send(user, body.text, body.client_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    # --- page 3: insights ------------------------------------------------------

    @app.get("/api/insights")
    async def insights(user: InsightsUser) -> dict[str, Any]:
        return {"snapshot": await workflows.insights.latest()}

    # --- admin -----------------------------------------------------------

    @app.post("/api/admin/catalogue/sync")
    async def sync_catalogue(user: AdminUser) -> dict[str, int]:
        synced = await workflows.catalogue_sync.run()
        await workflows.staff.audit(user, "catalogue_sync", {"synced": synced})
        return {"synced": synced}

    return app
