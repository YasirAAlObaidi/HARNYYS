"""The HTTP API: webhooks, staff views and admin actions.

Routes only translate HTTP to workflow calls and back. They hold no business
rules and never wait on a model: a webhook saves the message, queues the turn
and answers at once (docs/decisions/0007).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from yyai.core.errors import IntegrationError, NotFound, SignatureError
from yyai.workflows.container import Workflows

logger = logging.getLogger(__name__)


def create_app(workflows: Workflows) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await workflows.aclose()

    app = FastAPI(title="yyai", lifespan=lifespan)

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

    # --- staff views -----------------------------------------------------

    @app.get("/api/conversations")
    async def list_conversations(limit: int = Query(50, ge=1, le=500)) -> list[dict[str, Any]]:
        conversations = await workflows.queries.list_conversations(limit)
        return [c.model_dump(mode="json") for c in conversations]

    @app.get("/api/conversations/{conversation_id}/messages")
    async def conversation_messages(
        conversation_id: int, limit: int = Query(100, ge=1, le=1000)
    ) -> list[dict[str, Any]]:
        messages = await workflows.queries.messages(conversation_id, limit)
        return [m.model_dump(mode="json") for m in messages]

    @app.post("/api/outbox/{outbox_id}/approve")
    async def approve_outbox(outbox_id: int) -> dict[str, Any]:
        if not await workflows.queries.approve(outbox_id):
            raise HTTPException(status_code=404, detail="No reply is awaiting approval with that id")
        return {"approved": True, "id": outbox_id}

    # --- admin -----------------------------------------------------------

    @app.post("/api/admin/catalogue/sync")
    async def sync_catalogue() -> dict[str, int]:
        return {"synced": await workflows.catalogue_sync.run()}

    return app
