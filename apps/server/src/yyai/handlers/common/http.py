"""Shared HTTP helper for handlers. Knows nothing about any product."""

from __future__ import annotations

import httpx

from yyai.core.errors import IntegrationError

USER_AGENT = "yyai/0.1"


def make_client(*, base_url: str = "", headers: dict[str, str] | None = None, timeout_s: float = 30.0) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=base_url,
        headers={"User-Agent": USER_AGENT, **(headers or {})},
        timeout=httpx.Timeout(timeout_s, connect=10.0),
    )


def raise_for_status(response: httpx.Response, what: str) -> None:
    """Turn an HTTP error into an IntegrationError, marking which ones are worth retrying."""
    if response.is_success:
        return
    retryable = response.status_code == 429 or response.status_code >= 500
    body = response.text[:500]
    raise IntegrationError(f"{what} failed with HTTP {response.status_code}: {body}", retryable=retryable)
