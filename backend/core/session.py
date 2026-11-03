from sqlalchemy.ext.asyncio import (
    AsyncSession,
    create_async_engine,
    async_sessionmaker,
)
from core.config import settings
from typing import AsyncGenerator


DEV_DB = settings.DATABASE_URL_DEV

engine = create_async_engine(
    DEV_DB,
    echo=True
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