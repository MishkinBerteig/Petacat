"""Record the Episodic Memory's own snag identifier on the row.

A snag description is identified by the id ``EpisodicMemory`` stamps on it
(``memory.py:store_snag``), and that is the id the review comparison matches
``added_snags`` on and the Memory panel keys a snag by. The memory's counter is the
only identifier that covers every snag — a Fast Run contributes snags to the Training
Session and writes no rows at all — so the row records it, and both the row-backed and
the live projection report the same value for the same snag.

Nullable, and left null for rows written before this migration: their snag's identity
was whatever the counter happened to hold at the time, which is not recoverable now.
``rehydrate_memory`` assigns fresh identifiers in row order for those.

Revision ID: 013
Revises: 012
Create Date: 2026-07-31
"""

import sqlalchemy as sa
from alembic import op

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "snag_descriptions", sa.Column("snag_id", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("snag_descriptions", "snag_id")
