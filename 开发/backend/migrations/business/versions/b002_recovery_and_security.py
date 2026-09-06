"""Add deletion recovery state and durable login rate limits.

Revision ID: b002_recovery_and_security
Revises: b001_core
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b002_recovery_and_security"
down_revision: str | None = "b001_core"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("assistant_id", sa.String(36), nullable=True))
    op.add_column(
        "conversations",
        sa.Column("current_assistant_version_id", sa.String(36), nullable=True),
    )
    op.add_column(
        "jobs",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.create_table(
        "deletion_intents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("operation_id", sa.String(36), nullable=False),
        sa.Column("resource_type", sa.String(32), nullable=False),
        sa.Column("resource_id", sa.String(36), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("job_id", sa.String(36), nullable=False),
        sa.Column("journal_seq", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "operation_id", name="uq_deletion_intent_operation"),
        sa.UniqueConstraint("job_id", name="uq_deletion_intent_job"),
    )
    op.create_index("ix_deletion_intents_workspace_id", "deletion_intents", ["workspace_id"])
    op.create_table(
        "journal_projections",
        sa.Column("workspace_id", sa.String(36), primary_key=True),
        sa.Column("applied_seq", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "login_rate_limits",
        sa.Column("key_hash", sa.String(64), primary_key=True),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("login_rate_limits")
    op.drop_table("journal_projections")
    op.drop_index("ix_deletion_intents_workspace_id", table_name="deletion_intents")
    op.drop_table("deletion_intents")
    op.drop_column("jobs", "attempt_count")
    op.drop_column("conversations", "current_assistant_version_id")
    op.drop_column("conversations", "assistant_id")
