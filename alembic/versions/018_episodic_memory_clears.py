"""Episodic Memory clears replace Training Sessions.

Metacat Mode has no sessions: its runs are episodic runs, each inheriting the Episodic Memory
the runs before it left, and clearing that memory is an *event*.  This drops
``training_sessions`` and ``runs.session_id`` and records each clear as an
``episodic_memory_clears`` row.

The data conversion is lossless and lives in ``server/services/episodic_clears_migration.py``,
which startup reconciliation shares (the development database has no ``alembic_version``).
See that module for the mapping.  The downgrade rebuilds sessions and ``runs.session_id`` from
the clears.

Revision ID: 018
Revises: 017
Create Date: 2026-10-30
"""

from alembic import op

from server.services.episodic_clears_migration import (
    convert_clears_to_sessions,
    convert_sessions_to_clears,
)

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    convert_sessions_to_clears(op.get_bind())


def downgrade() -> None:
    convert_clears_to_sessions(op.get_bind())
