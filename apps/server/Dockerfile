# yyai core image: one image for every client, used by the API server, the
# worker and the migration job (see deploy/compose.yaml). The model server is
# never part of this image.
#
# Build from this folder:  docker build -t yyai-server:dev apps/server

# --- uv, pinned (copied as a binary, never installed into the final image) ---
FROM ghcr.io/astral-sh/uv:0.11.17 AS uv

# --- builder: resolve and install dependencies, then the project itself ------
FROM python:3.12-slim AS builder
COPY --from=uv /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    UV_PYTHON_DOWNLOADS=0 \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Dependencies first, so this layer is reused until pyproject.toml or uv.lock change.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --no-editable

# Then our own code. --no-editable installs yyai into the venv, so src/ is not needed at runtime.
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

# --- runtime ----------------------------------------------------------------
FROM python:3.12-slim

ENV LANG=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/app/.venv/bin:$PATH

RUN groupadd --system --gid 10001 yyai \
    && useradd --system --uid 10001 --gid yyai --home-dir /app --no-create-home --shell /usr/sbin/nologin yyai

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
# Alembic runs from /app: `alembic upgrade head` reads alembic.ini and migrations/.
COPY alembic.ini ./
COPY migrations ./migrations

USER yyai
EXPOSE 8000

CMD ["uvicorn", "yyai.main:app", "--host", "0.0.0.0", "--port", "8000"]
