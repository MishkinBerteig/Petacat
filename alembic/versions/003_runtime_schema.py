"""Runtime schema — tables for per-run state.

Revision ID: 003
Revises: 002
Create Date: 2026-03-21
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("initial_string", sa.String(64), nullable=False),
        sa.Column("modified_string", sa.String(64), nullable=False),
        sa.Column("target_string", sa.String(64), nullable=False),
        sa.Column("answer_string", sa.String(64), nullable=True),
        sa.Column("seed", sa.BigInteger, nullable=False),
        sa.Column("status", sa.String(16), server_default="initialized"),
        sa.Column("justify_mode", sa.Boolean, server_default="false"),
        sa.Column("self_watching", sa.Boolean, server_default="true"),
        sa.Column("codelet_count", sa.Integer, server_default="0"),
        sa.Column("temperature", sa.Float, server_default="100"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_table(
        "cycle_snapshots",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.Integer, nullable=False),
        sa.Column("codelet_count", sa.Integer, nullable=False),
        sa.Column("temperature", sa.Float, nullable=False),
        sa.Column("rng_state", JSONB, nullable=False),
        sa.Column("workspace_state", JSONB, nullable=False),
        sa.Column("slipnet_state", JSONB, nullable=False),
        sa.Column("coderack_state", JSONB, nullable=False),
        sa.Column("themespace_state", JSONB, nullable=False),
        sa.Column("trace_state", JSONB, nullable=False),
        sa.Column("runner_state", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("ix_cycle_snapshots_run", "cycle_snapshots", ["run_id"])

    op.create_table(
        "trace_events",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.Integer, nullable=False),
        sa.Column("event_number", sa.Integer, nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("codelet_count", sa.Integer, nullable=False),
        sa.Column("temperature", sa.Float, nullable=False),
        sa.Column("description", sa.Text, server_default=""),
        sa.Column("structures", JSONB, nullable=True),
        sa.Column("theme_pattern", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("ix_trace_events_run", "trace_events", ["run_id"])

    op.create_table(
        "answer_descriptions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.Integer, nullable=True),
        sa.Column("problem", JSONB, nullable=False),
        sa.Column("top_rule_description", sa.Text, server_default=""),
        sa.Column("bottom_rule_description", sa.Text, server_default=""),
        sa.Column("top_rule_quality", sa.Float, server_default="0"),
        sa.Column("bottom_rule_quality", sa.Float, server_default="0"),
        sa.Column("quality", sa.Float, server_default="0"),
        sa.Column("temperature", sa.Float, server_default="0"),
        sa.Column("themes", JSONB, nullable=True),
        sa.Column("unjustified_slippages", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_table(
        "snag_descriptions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.Integer, nullable=True),
        sa.Column("problem", JSONB, nullable=False),
        sa.Column("codelet_count", sa.Integer, server_default="0"),
        sa.Column("temperature", sa.Float, server_default="0"),
        sa.Column("theme_pattern", JSONB, nullable=True),
        sa.Column("description", sa.Text, server_default=""),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("snag_descriptions")
    op.drop_table("answer_descriptions")
    op.drop_table("trace_events")
    op.drop_table("cycle_snapshots")
    op.drop_table("runs")
