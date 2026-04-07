"""Async SQLAlchemy engine and session helpers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from apps.api.app.core.config import get_settings


@lru_cache
def get_engine(database_url: str | None = None) -> AsyncEngine:
    """Return a cached async engine for the configured database."""

    resolved_url = database_url or get_settings().database_url
    engine = create_async_engine(resolved_url, pool_pre_ping=True)

    if resolved_url.startswith("sqlite"):
        @event.listens_for(engine.sync_engine, "connect")
        def _set_sqlite_pragma(dbapi_connection: object, connection_record: object) -> None:
            del connection_record
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


@lru_cache
def get_session_factory(database_url: str | None = None) -> async_sessionmaker[AsyncSession]:
    """Return a cached async session factory."""

    return async_sessionmaker(get_engine(database_url), expire_on_commit=False)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that yields an async database session."""

    session_factory = get_session_factory()
    async with session_factory() as session:
        yield session
