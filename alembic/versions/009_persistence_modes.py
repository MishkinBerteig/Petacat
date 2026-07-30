"""Training Sessions, persistence modes, boundary state captures and the audit log.

Phase 0 Stage 3. Four changes that arrive together because they are one idea: a Run
becomes something that can be *reviewed* afterwards.

- ``training_sessions`` gives a name to a concept that already existed and already
  worked. Episodic Memory has always been carried across Run boundaries by injection,
  and a memory clear has always been the boundary between one session and the next;
  what was missing was any way to group Runs or to say which session one belonged to.
  No cognition changes here.

- ``runs.mode`` records which of the three persistence modes a Run executed under.
  Mode is a property of a *Run* rather than a global setting, because later phases want
  a Fast corpus-training population and a Normal live dialogue in the same process.

- ``runs.config_hash`` and ``runs.memory_hash`` name the two inputs a Run's behaviour
  depends on that ``(problem, seed)`` does not capture. This is close to bookkeeping
  today; it stops being bookkeeping in Phase 1, which puts the concept vocabulary into
  Episodic Memory, after which the memory a Run inherited is the largest single
  determinant of what it could think.

- ``run_state_captures`` replaces ``cycle_snapshots`` as the record of engine state.
  The old table was written every fifteenth codelet — 1 to 6 MB per run — and **no code
  path could read it back**: the four ``restore_*`` functions were called from nowhere,
  ``prune_old_snapshots`` was never called, and there was no coderack or workspace
  restore at all. One production database held 230 MB of it for ten runs. The new table
  holds two rows per Run, at the boundaries, in a format complete enough to re-execute
  the Run from.

- ``audit_actions`` is Audit mode's forward log: every state-changing action, with a
  dense ``sequence`` giving replay order, and a ``before`` field carrying enough prior
  state to invert an action later. Phase 0 ships forward stepping only, but backwards
  scrubbing constrains the *format* rather than only the UI, so the format admits it now.

``cycle_snapshots`` is left in place and simply unused. Dropping it would discard the
history in existing databases for no gain; nothing writes to it any more.

Revision ID: 009
Revises: 008
Create Date: 2026-07-29
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "training_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        # Set when the memory is cleared, which is what ends a session.
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
    )

    # Nullable so Runs recorded before sessions existed still read back rather than
    # having to be assigned to a session that never happened.
    op.add_column("runs", sa.Column("session_id", sa.Integer(), nullable=True))
    op.create_index("ix_runs_session_id", "runs", ["session_id"])

    # server_default backfills existing rows with "normal", which is what they in fact
    # ran as — every Run before this migration persisted its trace and its answers.
    op.add_column(
        "runs",
        sa.Column("mode", sa.String(8), nullable=False, server_default="normal"),
    )
    op.add_column("runs", sa.Column("config_hash", sa.String(64), nullable=True))
    op.add_column("runs", sa.Column("memory_hash", sa.String(64), nullable=True))

    op.create_table(
        "run_state_captures",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("boundary", sa.String(8), nullable=False),
        sa.Column("codelet_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("state", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_run_state_captures_run_id", "run_state_captures", ["run_id"])
    op.create_index(
        "ix_run_state_captures_run_boundary",
        "run_state_captures",
        ["run_id", "boundary"],
    )

    op.create_table(
        "audit_actions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("codelet_count", sa.Integer(), nullable=False),
        sa.Column("action_type", sa.String(32), nullable=False),
        sa.Column("temperature", sa.Float(), nullable=False, server_default="0"),
        sa.Column("payload", JSONB(), nullable=True),
        sa.Column("before", JSONB(), nullable=True),
    )
    op.create_index("ix_audit_actions_run_id", "audit_actions", ["run_id"])
    # The replay order, and the index every audit read is driven by.
    op.create_index(
        "ix_audit_actions_run_sequence", "audit_actions", ["run_id", "sequence"]
    )


def downgrade() -> None:
    op.drop_index("ix_audit_actions_run_sequence", table_name="audit_actions")
    op.drop_index("ix_audit_actions_run_id", table_name="audit_actions")
    op.drop_table("audit_actions")

    op.drop_index("ix_run_state_captures_run_boundary", table_name="run_state_captures")
    op.drop_index("ix_run_state_captures_run_id", table_name="run_state_captures")
    op.drop_table("run_state_captures")

    op.drop_column("runs", "memory_hash")
    op.drop_column("runs", "config_hash")
    op.drop_column("runs", "mode")
    op.drop_index("ix_runs_session_id", table_name="runs")
    op.drop_column("runs", "session_id")

    op.drop_table("training_sessions")
