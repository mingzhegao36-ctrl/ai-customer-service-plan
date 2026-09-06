from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.journal_models import JournalBase

journal_engine = create_async_engine(settings.journal_database_url, echo=settings.debug)
JournalSessionFactory = async_sessionmaker(
    bind=journal_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def ensure_journal_schema() -> None:
    if not settings.auto_create_schema:
        return
    async with journal_engine.begin() as connection:
        await connection.run_sync(JournalBase.metadata.create_all)
