"""Record the Episodic Memory's own answer identifier on the row.

Every API that names an answer — compare, display, forget — resolves it against
``EpisodicMemory``, whose identifiers come from its own counter. The listing served it
the row's primary key instead, and the two only agreed by coincidence: a memory clear
deletes rows without resetting the Postgres sequence, so afterwards an id from the
listing resolved to a *different* answer, silently.

Making a Fast Run contribute to the Training Session settles which of the two is
authoritative. A Fast Run writes no rows by definition, so its answers have no primary
key to borrow — but they are in the session and can be compared and displayed like any
other. The memory's counter is therefore the only identifier that covers every answer,
and the row records it rather than supplying one of its own.

Nullable, and left null for rows written before this migration: their answer's identity
was whatever the counter happened to hold at the time, which is not recoverable now, and
inventing one would be a fabrication. ``rehydrate_memory`` falls back to assigning fresh
identifiers in row order for those.

Revision ID: 012
Revises: 011
Create Date: 2026-07-31
"""

import sqlalchemy as sa
from alembic import op

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "answer_descriptions", sa.Column("answer_id", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("answer_descriptions", "answer_id")
