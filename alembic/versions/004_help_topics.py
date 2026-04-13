"""Help topics table for context-sensitive documentation.

Revision ID: 004
Revises: 003
Create Date: 2026-03-21
"""

import json
import os

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None

SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")


def upgrade() -> None:
    op.create_table(
        "help_topics",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("topic_type", sa.String(32), nullable=False),
        sa.Column("topic_key", sa.String(64), nullable=False, unique=True),
        sa.Column("title", sa.String(128), nullable=False),
        sa.Column("short_desc", sa.Text, server_default=""),
        sa.Column("full_desc", sa.Text, server_default=""),
        sa.Column("metadata", JSONB, nullable=True),
    )
    op.create_index("ix_help_topics_type", "help_topics", ["topic_type"])
    op.create_index("ix_help_topics_key", "help_topics", ["topic_key"])

    # Seed help topics if the file exists
    help_file = os.path.join(SEED_DIR, "help_topics.json")
    if os.path.exists(help_file):
        with open(help_file) as f:
            topics = json.load(f)
        if topics:
            op.bulk_insert(
                sa.table(
                    "help_topics",
                    sa.column("topic_type", sa.String),
                    sa.column("topic_key", sa.String),
                    sa.column("title", sa.String),
                    sa.column("short_desc", sa.Text),
                    sa.column("full_desc", sa.Text),
                    sa.column("metadata", sa.JSON),
                ),
                [
                    {
                        "topic_type": t["topic_type"],
                        "topic_key": t["topic_key"],
                        "title": t["title"],
                        "short_desc": t.get("short_desc", ""),
                        "full_desc": t.get("full_desc", ""),
                        "metadata": t.get("metadata", {}),
                    }
                    for t in topics
                ],
            )


def downgrade() -> None:
    op.drop_table("help_topics")
