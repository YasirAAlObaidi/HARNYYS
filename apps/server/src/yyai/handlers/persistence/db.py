"""Connection to our own Postgres. Only the persistence handler touches it."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


class Database:
    def __init__(self, url: str) -> None:
        self.engine: AsyncEngine = create_async_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)

    async def ping(self) -> bool:
        async with self.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True

    async def aclose(self) -> None:
        await self.engine.dispose()
