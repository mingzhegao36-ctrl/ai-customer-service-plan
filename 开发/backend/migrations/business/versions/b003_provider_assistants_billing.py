"""Add provider configuration, assistant versions, and budget accounting.

Revision ID: b003_provider_assistants_billing
Revises: b002_recovery_and_security
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b003_provider_assistants_billing"
down_revision: str | None = "b002_recovery_and_security"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("assistant_version_id", sa.String(36), nullable=True))
    op.create_index("ix_runs_assistant_version_id", "runs", ["assistant_version_id"])

    op.create_table(
        "provider_connections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("base_url", sa.String(512), nullable=False),
        sa.Column("secret_ciphertext", sa.Text(), nullable=True),
        sa.Column("secret_hint", sa.String(24), nullable=True),
        sa.Column("capabilities_json", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "name", name="uq_provider_connection_workspace_name"),
    )
    op.create_index("ix_provider_connections_workspace_id", "provider_connections", ["workspace_id"])

    op.create_table(
        "model_deployments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column(
            "provider_connection_id",
            sa.String(36),
            sa.ForeignKey("provider_connections.id"),
            nullable=False,
        ),
        sa.Column("model_id", sa.String(256), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("input_price_per_million", sa.Numeric(24, 8), nullable=False),
        sa.Column("output_price_per_million", sa.Numeric(24, 8), nullable=False),
        sa.Column("max_input_tokens", sa.Integer(), nullable=False),
        sa.Column("max_output_tokens", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "provider_connection_id",
            "model_id",
            "revision",
            name="uq_deployment_connection_model_revision",
        ),
    )
    op.create_index("ix_model_deployments_workspace_id", "model_deployments", ["workspace_id"])
    op.create_index(
        "ix_model_deployments_provider_connection_id",
        "model_deployments",
        ["provider_connection_id"],
    )

    op.create_table(
        "assistants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.String(1000), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("default_version_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "name", name="uq_assistant_workspace_name"),
    )
    op.create_index("ix_assistants_workspace_id", "assistants", ["workspace_id"])

    op.create_table(
        "assistant_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("assistant_id", sa.String(36), sa.ForeignKey("assistants.id"), nullable=False),
        sa.Column("deployment_id", sa.String(36), sa.ForeignKey("model_deployments.id"), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("authorization_epoch", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("assistant_id", "revision", name="uq_assistant_version_revision"),
    )
    op.create_index("ix_assistant_versions_workspace_id", "assistant_versions", ["workspace_id"])
    op.create_index("ix_assistant_versions_assistant_id", "assistant_versions", ["assistant_id"])
    op.create_index("ix_assistant_versions_deployment_id", "assistant_versions", ["deployment_id"])

    op.create_table(
        "budget_policies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("workspace_daily_limit", sa.Numeric(24, 8), nullable=False),
        sa.Column("workspace_monthly_limit", sa.Numeric(24, 8), nullable=False),
        sa.Column("conversation_limit", sa.Numeric(24, 8), nullable=False),
        sa.Column("turn_limit", sa.Numeric(24, 8), nullable=False),
        sa.Column("max_attempts_per_turn", sa.Integer(), nullable=False),
        sa.Column("max_input_tokens", sa.Integer(), nullable=False),
        sa.Column("max_output_tokens", sa.Integer(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "version", name="uq_budget_policy_workspace_version"),
    )
    op.create_index("ix_budget_policies_workspace_id", "budget_policies", ["workspace_id"])
    op.create_index(
        "uq_budget_policy_workspace_current",
        "budget_policies",
        ["workspace_id"],
        unique=True,
        postgresql_where=sa.text("is_current"),
        sqlite_where=sa.text("is_current = 1"),
    )

    op.create_table(
        "budget_accounts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("policy_id", sa.String(36), sa.ForeignKey("budget_policies.id"), nullable=False),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("subject_id", sa.String(36), nullable=False),
        sa.Column("period_type", sa.String(16), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("limit_amount", sa.Numeric(24, 8), nullable=False),
        sa.Column("spent_amount", sa.Numeric(24, 8), nullable=False),
        sa.Column("held_amount", sa.Numeric(24, 8), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "workspace_id",
            "policy_id",
            "scope",
            "subject_id",
            "period_type",
            "period_start",
            "currency",
            name="uq_budget_account_scope_period",
        ),
    )
    op.create_index("ix_budget_accounts_workspace_id", "budget_accounts", ["workspace_id"])
    op.create_index("ix_budget_accounts_policy_id", "budget_accounts", ["policy_id"])

    op.create_table(
        "operations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id"), nullable=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id"), nullable=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_operations_workspace_id", "operations", ["workspace_id"])
    op.create_index("ix_operations_actor_id", "operations", ["actor_id"])
    op.create_index("ix_operations_run_id", "operations", ["run_id"])
    op.create_index("ix_operations_job_id", "operations", ["job_id"])

    op.create_table(
        "operation_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("operation_id", sa.String(36), sa.ForeignKey("operations.id"), nullable=False),
        sa.Column("deployment_id", sa.String(36), sa.ForeignKey("model_deployments.id"), nullable=False),
        sa.Column(
            "provider_connection_id",
            sa.String(36),
            sa.ForeignKey("provider_connections.id"),
            nullable=False,
        ),
        sa.Column("connection_revision", sa.Integer(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("provider_request_id", sa.String(256), nullable=True),
        sa.Column("usage_json", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("operation_id", "number", name="uq_operation_attempt_number"),
    )
    op.create_index("ix_operation_attempts_workspace_id", "operation_attempts", ["workspace_id"])
    op.create_index("ix_operation_attempts_operation_id", "operation_attempts", ["operation_id"])
    op.create_index("ix_operation_attempts_deployment_id", "operation_attempts", ["deployment_id"])
    op.create_index(
        "ix_operation_attempts_provider_connection_id",
        "operation_attempts",
        ["provider_connection_id"],
    )

    op.create_table(
        "budget_reservations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("attempt_id", sa.String(36), sa.ForeignKey("operation_attempts.id"), nullable=False),
        sa.Column("account_id", sa.String(36), sa.ForeignKey("budget_accounts.id"), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("reserved_amount", sa.Numeric(24, 8), nullable=False),
        sa.Column("actual_amount", sa.Numeric(24, 8), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("attempt_id", "account_id", name="uq_budget_reservation_attempt_account"),
    )
    op.create_index("ix_budget_reservations_workspace_id", "budget_reservations", ["workspace_id"])
    op.create_index("ix_budget_reservations_attempt_id", "budget_reservations", ["attempt_id"])
    op.create_index("ix_budget_reservations_account_id", "budget_reservations", ["account_id"])

    op.create_table(
        "budget_ledger",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("account_id", sa.String(36), sa.ForeignKey("budget_accounts.id"), nullable=False),
        sa.Column("attempt_id", sa.String(36), sa.ForeignKey("operation_attempts.id"), nullable=False),
        sa.Column("event_key", sa.String(160), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("spent_delta", sa.Numeric(24, 8), nullable=False),
        sa.Column("held_delta", sa.Numeric(24, 8), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("account_id", "event_key", name="uq_budget_ledger_event"),
    )
    op.create_index("ix_budget_ledger_workspace_id", "budget_ledger", ["workspace_id"])
    op.create_index("ix_budget_ledger_account_id", "budget_ledger", ["account_id"])
    op.create_index("ix_budget_ledger_attempt_id", "budget_ledger", ["attempt_id"])

    op.create_table(
        "provider_connection_tests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column(
            "provider_connection_id",
            sa.String(36),
            sa.ForeignKey("provider_connections.id"),
            nullable=False,
        ),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("expected_revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("job_id", name="uq_provider_connection_test_job"),
    )
    op.create_index("ix_provider_connection_tests_workspace_id", "provider_connection_tests", ["workspace_id"])
    op.create_index(
        "ix_provider_connection_tests_provider_connection_id",
        "provider_connection_tests",
        ["provider_connection_id"],
    )


def downgrade() -> None:
    op.drop_table("provider_connection_tests")
    op.drop_table("budget_ledger")
    op.drop_table("budget_reservations")
    op.drop_table("operation_attempts")
    op.drop_table("operations")
    op.drop_table("budget_accounts")
    op.drop_index("uq_budget_policy_workspace_current", table_name="budget_policies")
    op.drop_table("budget_policies")
    op.drop_table("assistant_versions")
    op.drop_table("assistants")
    op.drop_table("model_deployments")
    op.drop_table("provider_connections")
    op.drop_index("ix_runs_assistant_version_id", table_name="runs")
    op.drop_column("runs", "assistant_version_id")
