"""Record a snag description's explanation and its translated rule's English.

``abstract-snag-description`` (``memory.ss:468-477``) hands ``make-snag-description`` the
snag event's explanation -- the sentence ``get-explanation`` writes from the failure
result (``trace.ss:1097-1125``) -- and the translated rule's English transcription, and
the description exposes them as ``get-explanation`` and ``get-translated-rule-phrases``
(``memory.ss:331-332``).  Petacat kept neither: it built an invented sentence from the
rule and the target string wherever the explanation was wanted.

Nullable, and left null for rows written before this migration: the failure result is
gone and cannot be recovered.  The explanation then falls back to that older sentence
(``snag_explanation.snag_explanation_text``), and the translated rule's English is
simply absent.

Revision ID: 015
Revises: 014
Create Date: 2026-10-29
"""

import sqlalchemy as sa
from alembic import op

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("snag_descriptions", sa.Column("explanation", sa.Text(), nullable=True))
    op.add_column(
        "snag_descriptions",
        sa.Column("translated_rule_description", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("snag_descriptions", "translated_rule_description")
    op.drop_column("snag_descriptions", "explanation")
