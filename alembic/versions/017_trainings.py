"""Trainings: named, long-lived episodes of many problems over many seeds.

Four runtime tables, all ON DELETE CASCADE from ``trainings``: the Training, its problems,
their per-seed runs, and the log of memory merges that makes a shared episode memory
rebuildable.  Written only at milestones, so ``training_runs`` holds the runs committed by
a finished problem's write (plus any other problem's runs completed since the last write).

Revision ID: 017
Revises: 016
Create Date: 2026-10-30
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trainings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("memory", sa.String(16), nullable=False),
        sa.Column("seeds_per_problem", sa.Integer(), nullable=False),
        sa.Column("seed_start", sa.Integer(), nullable=False),
        sa.Column("max_codelets", sa.Integer(), nullable=False),
        sa.Column("parameters", postgresql.JSONB(), nullable=True),
        sa.Column("backend", sa.String(32), nullable=False),
        sa.Column("policy", postgresql.JSONB(), nullable=False),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("finished_count", sa.Integer(), nullable=False),
        sa.Column("last_event", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("status IN ('open','paused','closed','cancelled')", name="ck_trainings_status"),
        sa.CheckConstraint("memory IN ('shared','independent')", name="ck_trainings_memory"),
    )
    op.create_table(
        "training_problems",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("training_id", sa.Integer(), sa.ForeignKey("trainings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("initial", sa.String(64), nullable=False),
        sa.Column("modified", sa.String(64), nullable=False),
        sa.Column("target", sa.String(64), nullable=False),
        sa.Column("answer", sa.String(64), nullable=True),
        sa.Column("seeds", sa.Integer(), nullable=False),
        sa.Column("seed_start", sa.Integer(), nullable=False),
        sa.Column("tag", postgresql.JSONB(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("runs_done", sa.Integer(), nullable=False),
        sa.Column("errors", sa.Integer(), nullable=False),
        sa.Column("capped", sa.Integer(), nullable=False),
        sa.Column("retries", sa.Integer(), nullable=False),
        sa.Column("codelets_total", sa.BigInteger(), nullable=False),
        sa.Column("mean_codelets", sa.Float(), nullable=True),
        sa.Column("top_answer", sa.Text(), nullable=True),
        sa.Column("top_fraction", sa.Float(), nullable=True),
        sa.Column("none_fraction", sa.Float(), nullable=True),
        sa.Column("distinct_answers", sa.Integer(), nullable=False),
        sa.Column("distribution", postgresql.JSONB(), nullable=True),
        sa.Column("statuses", postgresql.JSONB(), nullable=True),
        sa.Column("first_error", sa.Text(), nullable=True),
        sa.Column("finished_seq", sa.Integer(), nullable=True),
        sa.Column("added_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("status IN ('queued','finished','cancelled')", name="ck_training_problems_status"),
    )
    op.create_index("ix_training_problems_training_id", "training_problems", ["training_id"])
    op.create_index("ix_training_problems_training_status", "training_problems", ["training_id", "status"])
    op.create_index("ix_training_problems_training_seq", "training_problems", ["training_id", "finished_seq"])
    op.create_table(
        "training_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("training_id", sa.Integer(), sa.ForeignKey("trainings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("problem_id", sa.Integer(), sa.ForeignKey("training_problems.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("answers", postgresql.JSONB(), nullable=True),
        sa.Column("codelets", sa.Integer(), nullable=False),
        sa.Column("seconds", sa.Float(), nullable=False),
        sa.Column("temperature", sa.Float(), nullable=False),
        sa.Column("answer_quality", sa.Float(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=True),
        sa.Column("memory_version", sa.Integer(), nullable=True),
        sa.Column("added_answers", sa.Integer(), nullable=True),
        sa.Column("added_snags", sa.Integer(), nullable=True),
        sa.UniqueConstraint("problem_id", "seed", name="uq_training_runs_problem_seed"),
    )
    op.create_index("ix_training_runs_training_id", "training_runs", ["training_id"])
    op.create_index("ix_training_runs_training_seq", "training_runs", ["training_id", "seq"])
    op.create_table(
        "training_memory_merges",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("training_id", sa.Integer(), sa.ForeignKey("trainings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("problem_id", sa.Integer(), nullable=True),
        sa.Column("seed", sa.Integer(), nullable=True),
        sa.Column("answers", postgresql.JSONB(), nullable=True),
        sa.Column("snags", postgresql.JSONB(), nullable=True),
        sa.UniqueConstraint("training_id", "seq", name="uq_training_merges_seq"),
    )
    op.create_index("ix_training_memory_merges_training_id", "training_memory_merges", ["training_id"])


def downgrade() -> None:
    op.drop_table("training_memory_merges")
    op.drop_table("training_runs")
    op.drop_table("training_problems")
    op.drop_table("trainings")
