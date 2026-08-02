"""Persist the parts of an answer description a restart used to throw away.

§4.7.1 gives an answer description four theme-patterns, not one: the vertical pattern
that indexes it in memory, the top and bottom patterns taken from the two rules, and an
unjustified pattern for the slippages the program never came to terms with. Only the
vertical one had a column. The rules' abstractness and the description's activation had
none either, and neither did the structural clause keys that say whether two answers are
the same episode.

The effect was silent rather than visible. After a restart ``top_rule_abstractness`` read
0, which makes ``is_coherent`` short-circuit to True; two of the five components of
``calculate-answer-distance`` dropped out; ``_classify_unjustified`` could return nothing,
so the snag-justified distinction vanished; and two of the preference criteria in an
answer comparison became unreachable. The comparison still returned an answer — just not
the one the dissertation describes.

``theme_abstractness`` is stored rather than recomputed because it needs the Slipnet's
conceptual depths, which a stored description no longer has access to.

All columns are nullable with a zero/empty default: rows written before this migration
genuinely do not have these values, and inventing them from a re-derivation would be a
fabrication.

Revision ID: 011
Revises: 010
Create Date: 2026-07-30
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None

_JSON_COLUMNS = ("top_themes", "bottom_themes", "unjustified_themes")
_FLOAT_COLUMNS = (
    "top_rule_abstractness",
    "bottom_rule_abstractness",
    "theme_abstractness",
    "activation",
)
_SIGNATURE_COLUMNS = ("top_rule_signature", "bottom_rule_signature")


def upgrade() -> None:
    for name in _JSON_COLUMNS:
        op.add_column(
            "answer_descriptions",
            sa.Column(name, JSONB(), nullable=True, server_default="{}"),
        )
    for name in _FLOAT_COLUMNS:
        op.add_column(
            "answer_descriptions",
            sa.Column(name, sa.Float(), nullable=True, server_default="0"),
        )
    for name in _SIGNATURE_COLUMNS:
        op.add_column(
            "answer_descriptions", sa.Column(name, JSONB(), nullable=True)
        )


def downgrade() -> None:
    for name in _SIGNATURE_COLUMNS + _FLOAT_COLUMNS + _JSON_COLUMNS:
        op.drop_column("answer_descriptions", name)
