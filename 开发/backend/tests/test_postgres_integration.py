from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import BudgetAccount, BudgetPolicy, Workspace


def _postgres_test_urls() -> tuple[str, str]:
    business_url = os.getenv("AI_CS_POSTGRES_TEST_URL")
    journal_url = os.getenv("AI_CS_POSTGRES_JOURNAL_TEST_URL")
    if not business_url or not journal_url:
        pytest.skip("set dedicated AI_CS_POSTGRES_TEST_URL and AI_CS_POSTGRES_JOURNAL_TEST_URL")
    if not business_url.startswith("postgresql+asyncpg://") or not journal_url.startswith(
        "postgresql+asyncpg://"
    ):
        pytest.fail("PostgreSQL integration URLs must use postgresql+asyncpg")
    return business_url, journal_url


def _upgrade(url_name: str, url: str, ini: str) -> None:
    environment = os.environ.copy()
    environment[url_name] = url
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", ini, "upgrade", "head"],
        check=True,
        env=environment,
    )


def test_postgresql_migrations_and_budget_row_locks() -> None:
    business_url, journal_url = _postgres_test_urls()
    _upgrade("AI_CS_DATABASE_URL", business_url, "migrations/business/alembic.ini")
    _upgrade("AI_CS_JOURNAL_DATABASE_URL", journal_url, "migrations/journal/alembic.ini")

    async def verify() -> None:
        business_engine = create_async_engine(business_url)
        journal_engine = create_async_engine(journal_url)
        session_factory = async_sessionmaker(business_engine, class_=AsyncSession, expire_on_commit=False)
        workspace_id = str(uuid4())
        policy_id = str(uuid4())
        account_id = str(uuid4())
        try:
            async with business_engine.connect() as connection:
                assert (
                    await connection.execute(text("select version_num from alembic_version"))
                ).scalar_one() == "b003_provider_assistants_billing"
            async with journal_engine.connect() as connection:
                assert (
                    await connection.execute(text("select version_num from alembic_version"))
                ).scalar_one() == "j001_deletion_journal"

            async with session_factory() as session:
                workspace = Workspace(id=workspace_id, name="postgres-test", timezone="UTC")
                policy = BudgetPolicy(
                    id=policy_id,
                    workspace_id=workspace_id,
                    version=1,
                    currency="USD",
                    workspace_daily_limit=Decimal("10"),
                    workspace_monthly_limit=Decimal("10"),
                    conversation_limit=Decimal("10"),
                    turn_limit=Decimal("10"),
                    max_attempts_per_turn=3,
                    max_input_tokens=1000,
                    max_output_tokens=100,
                    is_current=True,
                    reason="PostgreSQL lock verification",
                )
                account = BudgetAccount(
                    id=account_id,
                    workspace_id=workspace_id,
                    policy_id=policy_id,
                    scope="workspace_daily",
                    subject_id=workspace_id,
                    period_type="daily",
                    period_start=datetime(2026, 1, 1, tzinfo=UTC),
                    currency="USD",
                    limit_amount=Decimal("10"),
                    spent_amount=Decimal("0"),
                    held_amount=Decimal("0"),
                )
                session.add_all([workspace, policy, account])
                await session.commit()

            async with session_factory() as first:
                async with first.begin():
                    locked = (
                        await first.execute(
                            select(BudgetAccount)
                            .where(BudgetAccount.id == account_id)
                            .with_for_update()
                        )
                    ).scalar_one()
                    assert locked.id == account_id
                    async with session_factory() as second:
                        with pytest.raises(OperationalError):
                            await second.execute(
                                select(BudgetAccount)
                                .where(BudgetAccount.id == account_id)
                                .with_for_update(nowait=True)
                            )
        finally:
            await business_engine.dispose()
            await journal_engine.dispose()

    asyncio.run(verify())
