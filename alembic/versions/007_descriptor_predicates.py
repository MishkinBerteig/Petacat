"""Carry each Slipnet node's descriptor predicate alongside the node.

In the reference Scheme a descriptor predicate is a lambda attached to the node
itself — ``(tell plato-leftmost 'define-descriptor-predicate ...)``
(slipnet.ss:508-610) — so it is knowledge about a concept, not mechanism.  It now
travels with the node in ``seed_data/slipnet_nodes.json`` as a small DSL
expression over ``obj``, compiled at startup the same way a codelet's
``execute_body`` is, and this column mirrors it in the database so the admin API
sees the same thing the engine runs.

Revision ID: 007
Revises: 006
Create Date: 2026-07-26
"""

import json
import os

import sqlalchemy as sa
from alembic import op

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None

SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")


def upgrade() -> None:
    op.add_column(
        "slipnet_node_defs",
        sa.Column("descriptor_predicate", sa.Text, nullable=True),
    )

    # Backfill from the seed data so an existing database matches the JSON
    # without needing the volume to be discarded.
    path = os.path.join(SEED_DIR, "slipnet_nodes.json")
    if not os.path.exists(path):
        return
    with open(path) as f:
        nodes = json.load(f)
    if isinstance(nodes, dict):
        nodes = nodes.get("nodes", [])

    connection = op.get_bind()
    for node in nodes:
        predicate = node.get("descriptor_predicate")
        if not predicate:
            continue
        connection.execute(
            sa.text(
                "UPDATE slipnet_node_defs SET descriptor_predicate = :predicate "
                "WHERE name = :name"
            ),
            {"predicate": predicate, "name": node["name"]},
        )


def downgrade() -> None:
    op.drop_column("slipnet_node_defs", "descriptor_predicate")
