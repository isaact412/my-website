"""Async database connection (SQLite via aiosqlite)."""
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{path}")

        @event.listens_for(self.engine.sync_engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")    # readers don't block the writer
            cur.execute("PRAGMA busy_timeout=5000")   # wait up to 5s instead of "database is locked"
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

        self._sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Use as:  async with db.session() as s: ...   (commits on success, rolls back on error)"""
        async with self._sessions() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    async def close(self) -> None:
        await self.engine.dispose()
