"""Enum lookup tables — move hard-coded enums/constants to DB.

Creates 14 lookup tables, seeds them with initial values, and adds
foreign key constraints from existing columns to the new tables.

Revision ID: 006
Revises: 005
Create Date: 2026-03-22
"""

import json
import os

from alembic import op
import sqlalchemy as sa

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None

SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")

# All 14 enum table names in creation order
ENUM_TABLES = [
    "run_statuses",
    "event_types",
    "bridge_types",
    "bridge_orientations",
    "clause_types",
    "rule_types",
    "theme_types",
    "proposal_levels",
    "link_types",
    "codelet_families",
    "codelet_phases",
    "posting_directions",
    "param_value_types",
    "demo_modes",
]

# Foreign key mappings: (existing_table, existing_column, enum_table)
FK_MAPPINGS = [
    ("runs", "status", "run_statuses"),
    ("trace_events", "event_type", "event_types"),
    ("slipnet_link_defs", "link_type", "link_types"),
    ("codelet_type_defs", "family", "codelet_families"),
    ("codelet_type_defs", "phase", "codelet_phases"),
    ("posting_rules", "direction", "posting_directions"),
    ("engine_params", "value_type", "param_value_types"),
    ("demo_problems", "mode", "demo_modes"),
]


def upgrade() -> None:
    # 1. Create all 14 lookup tables with the same schema
    for table_name in ENUM_TABLES:
        op.create_table(
            table_name,
            sa.Column("name", sa.String(32), primary_key=True),
            sa.Column("display_label", sa.String(64), nullable=False),
            sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
            sa.Column("description", sa.Text, server_default=""),
        )

    # 2. Seed from enums.json
    enums_file = os.path.join(SEED_DIR, "enums.json")
    with open(enums_file) as f:
        enums_data = json.load(f)

    enum_table = sa.table(
        "placeholder",
        sa.column("name", sa.String),
        sa.column("display_label", sa.String),
        sa.column("sort_order", sa.Integer),
        sa.column("description", sa.Text),
    )

    for table_name in ENUM_TABLES:
        rows = enums_data.get(table_name, [])
        if rows:
            enum_table.name = table_name
            op.bulk_insert(enum_table, rows)

    # 3. Add foreign key constraints from existing columns to enum tables
    for existing_table, existing_column, enum_table_name in FK_MAPPINGS:
        op.create_foreign_key(
            f"fk_{existing_table}_{existing_column}_{enum_table_name}",
            existing_table,
            enum_table_name,
            [existing_column],
            ["name"],
        )


def downgrade() -> None:
    # Drop FK constraints first (reverse order)
    for existing_table, existing_column, enum_table_name in reversed(FK_MAPPINGS):
        op.drop_constraint(
            f"fk_{existing_table}_{existing_column}_{enum_table_name}",
            existing_table,
            type_="foreignkey",
        )

    # Drop enum tables (reverse order)
    for table_name in reversed(ENUM_TABLES):
        op.drop_table(table_name)
