"""Metadata schema — tables for domain knowledge.

Revision ID: 001
Revises: None
Create Date: 2026-03-21
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "slipnet_node_defs",
        sa.Column("name", sa.String(64), primary_key=True),
        sa.Column("short_name", sa.String(16), nullable=False),
        sa.Column("conceptual_depth", sa.Integer, nullable=False),
        sa.Column("description", sa.Text, server_default=""),
    )
    op.create_table(
        "slipnet_link_defs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("from_node", sa.String(64), nullable=False),
        sa.Column("to_node", sa.String(64), nullable=False),
        sa.Column("link_type", sa.String(32), nullable=False),
        sa.Column("label_node", sa.String(64), nullable=True),
        sa.Column("link_length", sa.Integer, nullable=True),
        sa.Column("fixed_length", sa.Boolean, server_default="true"),
    )
    op.create_index("ix_slipnet_link_defs_from", "slipnet_link_defs", ["from_node"])
    op.create_index("ix_slipnet_link_defs_to", "slipnet_link_defs", ["to_node"])

    op.create_table(
        "codelet_type_defs",
        sa.Column("name", sa.String(64), primary_key=True),
        sa.Column("family", sa.String(32), nullable=False),
        sa.Column("phase", sa.String(32), nullable=False),
        sa.Column("default_urgency", sa.Integer, nullable=True),
        sa.Column("description", sa.Text, server_default=""),
        sa.Column("source_file", sa.String(64), server_default=""),
        sa.Column("source_line", sa.Integer, server_default="0"),
        sa.Column("execute_body", sa.Text, server_default=""),
    )
    op.create_table(
        "engine_params",
        sa.Column("name", sa.String(64), primary_key=True),
        sa.Column("value", sa.Text, nullable=False),
        sa.Column("value_type", sa.String(16), server_default="string"),
    )
    op.create_table(
        "urgency_levels",
        sa.Column("name", sa.String(32), primary_key=True),
        sa.Column("value", sa.Integer, nullable=False),
    )
    op.create_table(
        "formula_coefficients",
        sa.Column("name", sa.String(64), primary_key=True),
        sa.Column("value", sa.Float, nullable=False),
    )
    op.create_table(
        "posting_rules",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("codelet_type", sa.String(64), nullable=False),
        sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("urgency_when_posted", sa.Integer, nullable=True),
        sa.Column("urgency_formula", sa.String(128), nullable=True),
        sa.Column("posting_formula", sa.String(256), server_default=""),
        sa.Column("count_formula", sa.String(128), server_default=""),
        sa.Column("count_values", JSONB, nullable=True),
        sa.Column("condition", sa.String(128), server_default="always"),
        sa.Column("triggering_slipnodes", JSONB, nullable=True),
    )
    op.create_index("ix_posting_rules_type", "posting_rules", ["codelet_type"])

    op.create_table(
        "commentary_templates",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("template_key", sa.String(64), nullable=False),
        sa.Column("template_data", JSONB, nullable=False),
    )
    op.create_index("ix_commentary_key", "commentary_templates", ["template_key"])

    op.create_table(
        "demo_problems",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(64), nullable=False, unique=True),
        sa.Column("section", sa.String(16), server_default=""),
        sa.Column("initial", sa.String(32), nullable=False),
        sa.Column("modified", sa.String(32), nullable=False),
        sa.Column("target", sa.String(32), nullable=False),
        sa.Column("answer", sa.String(32), nullable=True),
        sa.Column("seed", sa.BigInteger, nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("description", sa.Text, server_default=""),
    )
    op.create_table(
        "theme_dimension_defs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("slipnet_node", sa.String(64), nullable=False),
        sa.Column("valid_relations", JSONB, nullable=False),
    )
    op.create_table(
        "slipnet_layout",
        sa.Column("node_name", sa.String(64), primary_key=True),
        sa.Column("grid_row", sa.Integer, nullable=False),
        sa.Column("grid_col", sa.Integer, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("slipnet_layout")
    op.drop_table("theme_dimension_defs")
    op.drop_table("demo_problems")
    op.drop_table("commentary_templates")
    op.drop_table("posting_rules")
    op.drop_table("formula_coefficients")
    op.drop_table("urgency_levels")
    op.drop_table("engine_params")
    op.drop_table("codelet_type_defs")
    op.drop_table("slipnet_link_defs")
    op.drop_table("slipnet_node_defs")
