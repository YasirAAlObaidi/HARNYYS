"""Shared test setup.

Unit tests need nothing. Tests marked `db` use a real Postgres: the dev server at 127.0.0.1:55432, started with
`docker compose -f deploy/compose.dev.yaml up -d --wait` (or `scripts/setup-mac.sh`). They run
in their own database, `yyai_test`, which is created if missing, migrated with Alembic and emptied before
every test, so they never touch the dev data in the `yyai` database. Set YYAI_TEST_DB_NAME to use another
database name, so two test runs on the same Postgres never empty each other's tables. When Postgres cannot
be reached the `db` tests are skipped with a reason instead of failing.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import psycopg
import pytest
import respx
from alembic import command
from alembic.config import Config as AlembicConfig
from psycopg.rows import dict_row

from yyai.handlers.persistence.db import Database

SERVER_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = SERVER_DIR.parent.parent
KAHRAMAN_DIR = REPO_DIR / "deploy" / "clients" / "kahraman"
# The 12-item sample catalogue the tests search. Kept apart from the real client data in KAHRAMAN_DIR.
SAMPLE_CATALOGUE = Path(__file__).resolve().parent / "fixtures" / "sample_catalogue.json"

PG_HOST = "127.0.0.1"
PG_PORT = 55432
PG_USER = "yyai"
PG_PASSWORD = "yyai-dev"
# Override with YYAI_TEST_DB_NAME when two test runs share the dev Postgres, so they never empty each other's
# tables mid-test. Example: YYAI_TEST_DB_NAME=yyai_test_web uv run pytest -q
TEST_DB_NAME = os.environ.get("YYAI_TEST_DB_NAME") or "yyai_test"
if not TEST_DB_NAME.replace("_", "").isalnum():
    raise RuntimeError(f"YYAI_TEST_DB_NAME must be letters, digits and underscores, not {TEST_DB_NAME!r}")

# psycopg connection string to the dev database, used only to CREATE DATABASE.
ADMIN_CONNINFO = (
    f"host={PG_HOST} port={PG_PORT} user={PG_USER} password={PG_PASSWORD} dbname=yyai connect_timeout=3"
)
TEST_CONNINFO = f"host={PG_HOST} port={PG_PORT} user={PG_USER} password={PG_PASSWORD} dbname={TEST_DB_NAME}"
# SQLAlchemy URL for the app code and for Alembic.
TEST_DATABASE_URL = f"postgresql+psycopg://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{TEST_DB_NAME}"


@pytest.fixture(scope="session")
def test_database() -> str:
    """Create `yyai_test` if needed and migrate it to head. Skips the test when Postgres is unreachable."""
    try:
        with psycopg.connect(ADMIN_CONNINFO, autocommit=True) as admin:
            exists = admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB_NAME,)).fetchone()
            if not exists:
                admin.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')
    except psycopg.OperationalError as exc:
        pytest.skip(f"dev Postgres not reachable at {PG_HOST}:{PG_PORT} ({exc})")

    alembic_cfg = AlembicConfig(str(SERVER_DIR / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(SERVER_DIR / "migrations"))
    previous = os.environ.get("YYAI_DATABASE_URL")
    os.environ["YYAI_DATABASE_URL"] = TEST_DATABASE_URL  # read by migrations/env.py
    try:
        command.upgrade(alembic_cfg, "head")
    finally:
        if previous is None:
            os.environ.pop("YYAI_DATABASE_URL", None)
        else:
            os.environ["YYAI_DATABASE_URL"] = previous
    return TEST_DATABASE_URL


@pytest.fixture
def clean_database(test_database: str) -> str:
    """Empty every table (ids restart at 1) and return the test database URL."""
    with psycopg.connect(TEST_CONNINFO, autocommit=True) as conn:
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
            ).fetchall()
        ]
        if tables:
            names = ", ".join(f'"{name}"' for name in tables)
            conn.execute(f"TRUNCATE {names} RESTART IDENTITY CASCADE")
    return test_database


@pytest.fixture
async def db(clean_database: str) -> AsyncIterator[Database]:
    database = Database(clean_database)
    try:
        yield database
    finally:
        await database.aclose()


@pytest.fixture
def sql(clean_database: str) -> Iterator[psycopg.Connection]:
    """A plain synchronous connection to the test database, for asserting on rows and for setting up state."""
    with psycopg.connect(TEST_CONNINFO, autocommit=True, row_factory=dict_row) as conn:
        yield conn


@pytest.fixture
def mock_http() -> Iterator[respx.MockRouter]:
    """Intercepts every httpx request that goes to the network. Anything not routed fails the test."""
    with respx.mock(assert_all_called=False, assert_all_mocked=True) as router:
        yield router


@pytest.fixture(scope="session")
def server_dir() -> Path:
    return SERVER_DIR


@pytest.fixture(scope="session")
def kahraman_dir() -> Path:
    return KAHRAMAN_DIR


@pytest.fixture(scope="session")
def sample_catalogue() -> Path:
    return SAMPLE_CATALOGUE


@pytest.fixture(scope="session")
def variant_catalogue() -> Path:
    return SERVER_DIR / "tests" / "fixtures" / "variant_catalogue.json"
