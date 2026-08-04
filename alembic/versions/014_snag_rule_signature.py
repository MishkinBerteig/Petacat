"""Record a snag description's rule clause lists on the row.

``memory.ss:289-291`` gives ``make-snag-description`` both the rule's clause list and
the translated rule's, and ``equal?`` (``memory.ss:336-340``) compares the first of them
structurally — the three problem strings plus ``rule-clause-lists-equal?``. Petacat
compared the rule's English transcription instead, which collides two ways: two
structurally different rules can transcribe to the same prose, and every rule that fails
to transcribe reads "Unknown transformation" and so matched every other such rule.

Nullable, and left null for rows written before this migration: their rules' clause
lists were never recorded and cannot be recovered. ``SnagDescription.equal`` treats a
null signature as "unknown", so such a snag never matches — the same reservation
``_answers_equal`` makes for an answer whose rule was not captured.

Revision ID: 014
Revises: 013
Create Date: 2026-08-04
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "snag_descriptions", sa.Column("rule_signature", JSONB(), nullable=True)
    )
    op.add_column(
        "snag_descriptions",
        sa.Column("translated_rule_signature", JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("snag_descriptions", "translated_rule_signature")
    op.drop_column("snag_descriptions", "rule_signature")
