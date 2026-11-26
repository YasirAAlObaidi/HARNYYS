"""The API process: `uvicorn yyai.main:app`.

`app` is built the first time something asks for it (which is what uvicorn does
on startup), not when this module is imported. That keeps `import yyai.main`
free of config files, environment variables and database connections, so tests
and tools can import it safely. A bad config still fails loudly at startup.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from yyai.core.config import load_config
from yyai.core.logging import configure_logging

if TYPE_CHECKING:
    from fastapi import FastAPI

_app: FastAPI | None = None


def create() -> FastAPI:
    """Read the config, wire everything up and return the FastAPI app (built once)."""
    global _app
    if _app is None:
        from yyai.bootstrap import build
        from yyai.entry.api.app import create_app

        configure_logging()
        config = load_config()
        _app = create_app(build(config), session_max_age_s=int(config.auth.session_hours * 3600))
    return _app


def __getattr__(name: str) -> Any:
    if name == "app":
        return create()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
