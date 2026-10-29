"""Keep a Trace event's print name and picture, and an answer's and snag's picture.

Metacat names every Temporal Trace event (``print-name``, ``trace.ss``) and can redisplay
it: clicking an event, an answer or a snag redraws the Workspace as it was, with the
event's structures highlighted (``trace.ss:405-1250``, ``memory.ss:268-283, 380-395``).
Petacat kept a prose description and nothing to redraw.  The picture is captured when the
event, answer or snag is recorded -- the Workspace will have moved on by the time anyone
clicks -- as JSON (:mod:`server.engine.trace_display`).

Nullable, and left null for rows written before this migration: the Workspace they came
from is gone and cannot be recovered.  Such a row shows its description, and clicking it
imposes only its theme pattern, as before.

Revision ID: 016
Revises: 015
Create Date: 2026-10-29
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("trace_events", sa.Column("print_name", sa.String(255), nullable=True))
    op.add_column("trace_events", sa.Column("picture", postgresql.JSONB(), nullable=True))
    op.add_column("answer_descriptions", sa.Column("picture", postgresql.JSONB(), nullable=True))
    op.add_column("snag_descriptions", sa.Column("picture", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("snag_descriptions", "picture")
    op.drop_column("answer_descriptions", "picture")
    op.drop_column("trace_events", "picture")
    op.drop_column("trace_events", "print_name")
