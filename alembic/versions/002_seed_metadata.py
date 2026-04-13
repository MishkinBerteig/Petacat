"""Seed metadata from seed_data/ JSON files.

Revision ID: 002
Revises: 001
Create Date: 2026-03-21
"""

import json
import os

from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None

SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")


def _load(filename):
    with open(os.path.join(SEED_DIR, filename)) as f:
        return json.load(f)


def upgrade() -> None:
    # Slipnet nodes
    nodes = _load("slipnet_nodes.json")
    if nodes:
        op.bulk_insert(
            sa.table(
                "slipnet_node_defs",
                sa.column("name", sa.String),
                sa.column("short_name", sa.String),
                sa.column("conceptual_depth", sa.Integer),
            ),
            [{"name": n["name"], "short_name": n["short_name"],
              "conceptual_depth": n["conceptual_depth"]} for n in nodes],
        )

    # Slipnet links
    links = _load("slipnet_links.json")
    if links:
        op.bulk_insert(
            sa.table(
                "slipnet_link_defs",
                sa.column("from_node", sa.String),
                sa.column("to_node", sa.String),
                sa.column("link_type", sa.String),
                sa.column("label_node", sa.String),
                sa.column("link_length", sa.Integer),
                sa.column("fixed_length", sa.Boolean),
            ),
            [{"from_node": lk["from_node"], "to_node": lk["to_node"],
              "link_type": lk["link_type"],
              "label_node": lk.get("label_node"),
              "link_length": lk.get("link_length"),
              "fixed_length": lk.get("link_length") is not None
                              if "fixed_length" not in lk
                              else lk["fixed_length"]}
             for lk in links],
        )

    # Codelet types
    codelets = _load("codelet_types.json")
    if codelets:
        op.bulk_insert(
            sa.table(
                "codelet_type_defs",
                sa.column("name", sa.String),
                sa.column("family", sa.String),
                sa.column("phase", sa.String),
                sa.column("default_urgency", sa.Integer),
                sa.column("description", sa.Text),
                sa.column("source_file", sa.String),
                sa.column("source_line", sa.Integer),
                sa.column("execute_body", sa.Text),
            ),
            [{"name": c["name"], "family": c["family"], "phase": c["phase"],
              "default_urgency": c.get("default_urgency"),
              "description": c.get("description", ""),
              "source_file": c.get("source_file", ""),
              "source_line": c.get("source_line", 0),
              "execute_body": c.get("execute_body", "")}
             for c in codelets],
        )

    # Engine params (flatten nested structures to key-value)
    params = _load("engine_params.json")
    param_rows = []
    for k, v in params.items():
        if isinstance(v, (list, dict)):
            param_rows.append({"name": k, "value": json.dumps(v), "value_type": "json"})
        elif isinstance(v, bool):
            param_rows.append({"name": k, "value": str(v).lower(), "value_type": "bool"})
        elif isinstance(v, int):
            param_rows.append({"name": k, "value": str(v), "value_type": "int"})
        elif isinstance(v, float):
            param_rows.append({"name": k, "value": str(v), "value_type": "float"})
        else:
            param_rows.append({"name": k, "value": str(v), "value_type": "string"})
    if param_rows:
        op.bulk_insert(
            sa.table(
                "engine_params",
                sa.column("name", sa.String),
                sa.column("value", sa.Text),
                sa.column("value_type", sa.String),
            ),
            param_rows,
        )

    # Urgency levels
    urgency = _load("urgency_levels.json")
    if urgency:
        op.bulk_insert(
            sa.table(
                "urgency_levels",
                sa.column("name", sa.String),
                sa.column("value", sa.Integer),
            ),
            [{"name": k, "value": v} for k, v in urgency.items()],
        )

    # Formula coefficients
    formulas = _load("formula_coefficients.json")
    if formulas:
        op.bulk_insert(
            sa.table(
                "formula_coefficients",
                sa.column("name", sa.String),
                sa.column("value", sa.Float),
            ),
            [{"name": k, "value": v} for k, v in formulas.items()],
        )

    # Posting rules
    posting = _load("posting_rules.json")
    rules = posting.get("posting_rules", [])
    if rules:
        op.bulk_insert(
            sa.table(
                "posting_rules",
                sa.column("codelet_type", sa.String),
                sa.column("direction", sa.String),
                sa.column("urgency_when_posted", sa.Integer),
                sa.column("urgency_formula", sa.String),
                sa.column("posting_formula", sa.String),
                sa.column("count_formula", sa.String),
                sa.column("condition", sa.String),
            ),
            [{"codelet_type": r["codelet_type"], "direction": r["direction"],
              "urgency_when_posted": r.get("urgency_when_posted"),
              "urgency_formula": r.get("urgency_formula"),
              "posting_formula": r.get("posting_formula", ""),
              "count_formula": r.get("count_formula", ""),
              "condition": r.get("condition", "always")}
             for r in rules],
        )

    # Demo problems
    demos = _load("demo_problems.json")
    if demos:
        op.bulk_insert(
            sa.table(
                "demo_problems",
                sa.column("name", sa.String),
                sa.column("section", sa.String),
                sa.column("initial", sa.String),
                sa.column("modified", sa.String),
                sa.column("target", sa.String),
                sa.column("answer", sa.String),
                sa.column("seed", sa.BigInteger),
                sa.column("mode", sa.String),
                sa.column("description", sa.Text),
            ),
            [{"name": d["name"], "section": d.get("section", ""),
              "initial": d["initial"], "modified": d["modified"],
              "target": d["target"], "answer": d.get("answer"),
              "seed": d["seed"], "mode": d["mode"],
              "description": d.get("description", "")}
             for d in demos],
        )

    # Theme dimensions
    themes = _load("theme_dimensions.json")
    dims = themes.get("dimensions", [])
    if dims:
        op.bulk_insert(
            sa.table(
                "theme_dimension_defs",
                sa.column("slipnet_node", sa.String),
                sa.column("valid_relations", sa.JSON),
            ),
            [{"slipnet_node": d["slipnet_node"],
              "valid_relations": d["valid_relations"]}
             for d in dims],
        )

    # Slipnet layout
    layout = _load("slipnet_layout.json")
    positions = layout.get("node_positions", {})
    if positions:
        op.bulk_insert(
            sa.table(
                "slipnet_layout",
                sa.column("node_name", sa.String),
                sa.column("grid_row", sa.Integer),
                sa.column("grid_col", sa.Integer),
            ),
            [{"node_name": name, "grid_row": pos[0], "grid_col": pos[1]}
             for name, pos in positions.items()],
        )

    # Commentary templates (store as single JSON blob)
    commentary = _load("commentary_templates.json")
    if commentary:
        op.bulk_insert(
            sa.table(
                "commentary_templates",
                sa.column("template_key", sa.String),
                sa.column("template_data", sa.JSON),
            ),
            [{"template_key": "all", "template_data": commentary}],
        )


def downgrade() -> None:
    conn = op.get_bind()
    for table in ["slipnet_layout", "theme_dimension_defs", "demo_problems",
                   "commentary_templates", "posting_rules", "formula_coefficients",
                   "urgency_levels", "engine_params", "codelet_type_defs",
                   "slipnet_link_defs", "slipnet_node_defs"]:
        conn.execute(sa.text(f"DELETE FROM {table}"))
