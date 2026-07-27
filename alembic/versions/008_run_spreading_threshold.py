"""Record each run's spreading activation threshold on the run itself.

The threshold decides which Slipnet nodes are allowed to spread activation, and
it materially changes what a run does — the same problem at the same seed takes a
different number of codelets and can reach a different answer. That makes it part
of the run's identity, not a transient UI preference: a run at anything other than
100 is not comparable with the dissertation's results, and the run list has to be
able to say so.

Previously it lived only on the in-memory runner, so it vanished on restart and
was invisible to anything reading the database.

Revision ID: 008
Revises: 007
Create Date: 2026-07-26
"""

import sqlalchemy as sa
from alembic import op

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # server_default backfills existing rows with the original's behaviour, which
    # is what they in fact ran at — there was no way to set anything else.
    op.add_column(
        "runs",
        sa.Column(
            "spreading_threshold",
            sa.Integer(),
            nullable=False,
            server_default="100",
        ),
    )


def downgrade() -> None:
    op.drop_column("runs", "spreading_threshold")
