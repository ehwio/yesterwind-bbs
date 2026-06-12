"""
Async SQLAlchemy engine and session factory.

The DATABASE_URL environment variable controls the backend:
  SQLite (default): sqlite+aiosqlite:///data/bbs.db
  PostgreSQL:       postgresql+asyncpg://user:pass@host/bbs
  MySQL:            mysql+aiomysql://user:pass@host/bbs

No other code changes are needed to switch backends.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from yesterwind_bbs import config

engine = create_async_engine(
    config.DATABASE_URL,
    echo=False,
    # SQLite needs this for proper async behaviour; ignored by other backends
    connect_args={"check_same_thread": False} if "sqlite" in config.DATABASE_URL else {},
)

_session_factory = async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a transactional async session, rolling back on error."""
    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Create all tables if they don't exist. Safe to call on every startup."""
    from yesterwind_bbs.db.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
