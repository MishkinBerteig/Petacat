"""Add performance indexes to runtime and metadata tables.

Revision ID: 005
Revises: 004
Create Date: 2026-03-22
"""

from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # runs: filter by status, sort by creation time
    op.create_index("ix_runs_status", "runs", ["status"])
    op.create_index("ix_runs_created_at", "runs", ["created_at"])

    # cycle_snapshots: look up snapshot at a specific step within a run
    op.create_index(
        "ix_cycle_snapshots_run_step",
        "cycle_snapshots",
        ["run_id", "codelet_count"],
    )

    # trace_events: sequential lookup, type filtering, step correlation
    op.create_index(
        "ix_trace_events_run_number",
        "trace_events",
        ["run_id", "event_number"],
    )
    op.create_index(
        "ix_trace_events_run_type",
        "trace_events",
        ["run_id", "event_type"],
    )
    op.create_index(
        "ix_trace_events_run_step",
        "trace_events",
        ["run_id", "codelet_count"],
    )

    # answer_descriptions / snag_descriptions: find by run
    op.create_index("ix_answer_descriptions_run", "answer_descriptions", ["run_id"])
    op.create_index("ix_snag_descriptions_run", "snag_descriptions", ["run_id"])

    # demo_problems: filter by mode (discovery / justification)
    op.create_index("ix_demo_problems_mode", "demo_problems", ["mode"])


def downgrade() -> None:
    op.drop_index("ix_demo_problems_mode", table_name="demo_problems")
    op.drop_index("ix_snag_descriptions_run", table_name="snag_descriptions")
    op.drop_index("ix_answer_descriptions_run", table_name="answer_descriptions")
    op.drop_index("ix_trace_events_run_step", table_name="trace_events")
    op.drop_index("ix_trace_events_run_type", table_name="trace_events")
    op.drop_index("ix_trace_events_run_number", table_name="trace_events")
    op.drop_index("ix_cycle_snapshots_run_step", table_name="cycle_snapshots")
    op.drop_index("ix_runs_created_at", table_name="runs")
    op.drop_index("ix_runs_status", table_name="runs")
