"""Create append-only deletion journal tables.

Revision ID: j001_deletion_journal
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "j001_deletion_journal"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "journal_heads",
        sa.Column("workspace_id", sa.String(36), primary_key=True),
        sa.Column("head_seq", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "deletion_journal",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("operation_id", sa.String(36), nullable=False),
        sa.Column("resource_type", sa.String(32), nullable=False),
        sa.Column("resource_id", sa.String(36), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("instance_id", sa.String(128), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "workspace_id",
            "seq",
            name="uq_deletion_journal_workspace_seq",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "operation_id",
            name="uq_deletion_journal_operation",
        ),
    )
    op.create_index("ix_deletion_journal_workspace_id", "deletion_journal", ["workspace_id"])


def downgrade() -> None:
    op.drop_table("deletion_journal")
    op.drop_table("journal_heads")
