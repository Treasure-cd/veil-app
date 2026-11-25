from sqlalchemy.ext.asyncio import (
    AsyncSession,
    create_async_engine,
    async_sessionmaker,
)
from core.config import settings
from typing import AsyncGenerator


def get_database_url() -> str:
    """Normalize Neon/Postgres URLs for SQLAlchemy's asyncpg driver."""
    url = settings.DATABASE_URL
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


DATABASE_URL = get_database_url()

engine = create_async_engine(
    DATABASE_URL,
    echo=settings.SQL_ECHO,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    class_=AsyncSession
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency to get an async database session."""

    async with AsyncSessionLocal() as session:
        yield session
