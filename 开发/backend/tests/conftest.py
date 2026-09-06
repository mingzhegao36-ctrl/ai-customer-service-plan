from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest

test_root = Path(tempfile.gettempdir()) / f"ai-cs-backend-tests-{uuid4()}"
test_root.mkdir()
os.environ.update(
    {
        "AI_CS_APP_ENV": "development",
        "AI_CS_DATABASE_URL": f"sqlite+aiosqlite:///{test_root / 'business.db'}",
        "AI_CS_JOURNAL_DATABASE_URL": f"sqlite+aiosqlite:///{test_root / 'journal.db'}",
        "AI_CS_SECRET_KEY": "test-secret-at-least-thirty-two-characters",
        "AI_CS_AUTO_CREATE_SCHEMA": "true",
        "AI_CS_BOOTSTRAP_ENABLED": "true",
        "AI_CS_BOOTSTRAP_ADMIN_PASSWORD": "test-admin-password",
    }
)

from app.core.db import engine  # noqa: E402
from app.core.journal_db import journal_engine  # noqa: E402
from app.journal_models import JournalBase  # noqa: E402
from app.models import Base  # noqa: E402


@pytest.fixture(autouse=True)
def reset_local_databases() -> None:
    async def reset() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
            await connection.run_sync(Base.metadata.create_all)
        async with journal_engine.begin() as connection:
            await connection.run_sync(JournalBase.metadata.drop_all)
            await connection.run_sync(JournalBase.metadata.create_all)

    asyncio.run(reset())
