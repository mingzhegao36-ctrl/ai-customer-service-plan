from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.db import engine
from app.core.errors import AppError
from app.core.journal_db import journal_engine
from app.core.request_id import get_request_id
from app.deletion_recovery import deletion_recovery_is_current
from app.journal_models import JournalHead
from app.models import Workspace

router = APIRouter()
BUSINESS_MIGRATION_HEAD = "b003_provider_assistants_billing"
JOURNAL_MIGRATION_HEAD = "j001_deletion_journal"


@router.get("/health")
async def health_check():
    return {"status": "ok", "request_id": get_request_id()}


@router.get("/health/ready")
async def readiness() -> dict[str, object]:
    business_version = None
    journal_version = None
    async with engine.connect() as conn:
        await conn.execute(text("select 1"))
        await conn.execute(select(Workspace.id).limit(1))
        try:
            business_version = (
                await conn.execute(text("select version_num from alembic_version"))
            ).scalar_one_or_none()
        except SQLAlchemyError:
            pass
    async with journal_engine.connect() as conn:
        await conn.execute(text("select 1"))
        await conn.execute(select(JournalHead.workspace_id).limit(1))
        try:
            journal_version = (
                await conn.execute(text("select version_num from alembic_version"))
            ).scalar_one_or_none()
        except SQLAlchemyError:
            pass
    if business_version != BUSINESS_MIGRATION_HEAD or journal_version != JOURNAL_MIGRATION_HEAD:
        raise AppError(
            status_code=503,
            code="migration_pending",
            message="database migrations are not at the required revision",
            retryable=True,
        )
    if not await deletion_recovery_is_current():
        raise AppError(
            status_code=503,
            code="deletion_recovery_pending",
            message="deletion journal recovery is not current",
            retryable=True,
        )
    return {
        "status": "ready",
        "dependencies": {
            "business_database": "ready",
            "deletion_journal": "ready",
            "migrations": "ready",
            "deletion_recovery": "ready",
        },
        "request_id": get_request_id(),
    }
