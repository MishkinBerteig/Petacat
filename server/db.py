"""Database engine and session factory."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.config import DATABASE_URL

engine = create_async_engine(DATABASE_URL, echo=False)
async_session_factory = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def get_session():
    """Yield an async session for dependency injection."""
    session = async_session_factory()
    try:
        yield session
    finally:
        await session.close()
