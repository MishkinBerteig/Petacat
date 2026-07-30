"""Record each Run's resolved run parameters on the Run itself.

Twenty-five entries in ``engine_params.json`` are read by the engine while it thinks —
thresholds, periods, capacities, the update cadence — and every one of them was global:
editable only in the Admin panel, applying to every Run at once, and present in a Run's
row only indirectly, through the config hash. A past Run could therefore not be
interpreted without knowing what the global configuration happened to be when it ran.

The column holds the **resolved** set rather than only the overrides. Storing overrides
alone would mean reading them against whatever the defaults are at the time of reading,
so a Run's record would quietly change meaning whenever the configuration did. Nullable
because Runs recorded before this migration have no such record and inventing one from
today's defaults would be a fabrication — a null says "not recorded", which is true.

Written for Normal and Audit Runs. A Fast Run has no row at all, by design.

Revision ID: 010
Revises: 009
Create Date: 2026-07-30
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("parameters", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("runs", "parameters")
