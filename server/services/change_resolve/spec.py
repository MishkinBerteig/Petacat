"""What the change API knows about the tables: columns, references, code, uniqueness.

Built once from C6's ``config_registry.REGISTRY`` (keys, order, code and JSON columns) and the
models' columns.  Three things are declared here because they are facts of the engine's
schema, not of any one configuration:

* ``REFERENCES``: which columns name a row of another table (or a name in the engine's
  role vocabulary) -- the 422 ``unknown_reference`` check;
* ``UNIQUE_EXTRA``: the unique constraints that are not the natural key;
* the node-keyed and codelet-type-keyed engine parameters the cascades rewrite.

``schema(registry)`` is the data ``GET /api/configurations/{id}/schema`` returns (3.12.2).
It lists configuration tables only; a session's Episodic Memory is never in the registry
(3.15).
"""

from __future__ import annotations

from typing import Any, Mapping

from sqlalchemy import Boolean, Float, Integer
from sqlalchemy.dialects.postgresql import JSON, JSONB

from server.engine.roles import CODELET_TYPE, NODE, ORDERED, ROLES
from server.services.config_registry import ENUM_REGISTRY, REGISTRY, TableSpec as RegistrySpec
from server.services.change_resolve.vocabulary import roles_by_table
from server.services.configuration_input import (
    VALUE_TYPES,
    ColumnSpec,
    Reference,
    TableSpec as InputSpec,
)

#: ``(table, column) -> (target, many)``.  A *target* is a table name (the referenced value is
#: that table's single key column) or ``"role.node"`` / ``"role.codelet_type"``, the role names
#: the engine declares for that kind of target.
REFERENCES: dict[tuple[str, str], tuple[str, bool]] = {
    ("slipnet_link_defs", "from_node"): ("slipnet_node_defs", False),
    ("slipnet_link_defs", "to_node"): ("slipnet_node_defs", False),
    ("slipnet_link_defs", "label_node"): ("slipnet_node_defs", False),
    ("slipnet_link_defs", "link_type"): ("link_types", False),
    ("slipnet_layout", "node_name"): ("slipnet_node_defs", False),
    ("theme_dimension_defs", "slipnet_node"): ("slipnet_node_defs", False),
    ("theme_relations", "node_name"): ("slipnet_node_defs", False),
    ("slipnet_node_roles", "role"): ("role.node", False),
    ("slipnet_node_roles", "node_name"): ("slipnet_node_defs", False),
    ("initial_description_rules", "dimension_role"): ("role.node", False),
    ("initial_description_rules", "descriptor_role"): ("role.node", False),
    ("initial_activation_rules", "node_role"): ("role.node", False),
    ("codelet_type_roles", "role"): ("role.codelet_type", False),
    ("codelet_type_roles", "codelet_type"): ("codelet_type_defs", False),
    ("codelet_type_defs", "family"): ("codelet_families", False),
    ("codelet_type_defs", "phase"): ("codelet_phases", False),
    ("posting_rules", "codelet_type"): ("codelet_type_defs", False),
    ("posting_rules", "direction"): ("posting_directions", False),
    ("posting_rules", "triggering_slipnodes"): ("slipnet_node_defs", True),
    ("posting_rules", "urgency_level"): ("urgency_levels", False),
    ("codelet_pattern_defs", "codelet_type"): ("codelet_type_defs", False),
    ("codelet_pattern_defs", "urgency_level"): ("urgency_levels", False),
    ("engine_params", "value_type"): ("param_value_types", False),
    ("formula_coefficients", "value_type"): ("param_value_types", False),
    # Columns of the enum tables that name another table's row.  ``rename_enum_value`` and the
    # reference check read them; the change API's schema lists only the addressable tables.
    # (``clamp_types.codelet_background_level`` names an urgency level and is, like a posting
    # rule's ``urgency_level``, rewritten on a level rename and reported, never deleted, when
    # the level is removed: it is in ``ENUM_COLUMN_REFERENCES``, not here.)
    # The four-string frame: which strings a bridge type joins, its orientation, the theme type it
    # feeds, and the bridge type a rule type describes (``server/engine/frame.py``).
    ("bridge_types", "from_string_kind"): ("string_kinds", False),
    ("bridge_types", "to_string_kind"): ("string_kinds", False),
    ("bridge_types", "orientation"): ("bridge_orientations", False),
    ("bridge_types", "theme_type"): ("theme_types", False),
    ("rule_types", "bridge_type"): ("bridge_types", False),
    ("clamp_types", "progress_focus"): ("progress_focuses", False),
    ("progress_focuses", "event_types"): ("event_types", True),
}

#: A column of an enum table that names an urgency level: the Admin enum editor checks it on a
#: write, and a level rename rewrites it (a level removal lists it as dangling).
ENUM_COLUMN_REFERENCES: dict[tuple[str, str], tuple[str, bool]] = {
    ("clamp_types", "codelet_background_level"): ("urgency_levels", False),
}

#: Columns that hold a name of another table's row and are rewritten when that row is renamed,
#: but are not checked as references (a theme dimension's valid relations are not required to
#: exist).
ENUM_RENAME_EXTRA: dict[tuple[str, str], tuple[str, bool]] = {
    ("theme_dimension_defs", "valid_relations"): ("theme_relations", True),
}

#: Unique constraints other than the natural key: ``table -> [column tuples]``.  A NULL part
#: never collides.
UNIQUE_EXTRA: dict[str, list[tuple[str, ...]]] = {
    "slipnet_node_defs": [("glyph",), ("numeric_value",)],
    "slipnet_node_roles": [("node_name", "role")],
    "codelet_type_roles": [("codelet_type", "role")],
}

#: What an ``engine_params.refers_to`` may say (NULL: the value names nothing).  The change API
#: reads the column of the configuration it resolves against to find the parameters a node, a
#: codelet type or an urgency level is named in; no list of parameter names lives in code.
REFERS_TO_KINDS = (
    "node_list", "trigger_node_list", "node_map", "codelet_type_list", "urgency_level",
    "clampable_pattern_map", "clampable_pattern_list",
)


def _standard_refers_to() -> dict[str, str]:
    """The Metacat Standard Configuration's declaration (``seed_data/engine_param_refs.json``)."""
    import json
    import os

    from server.config import SEED_DATA_DIR

    with open(os.path.join(SEED_DATA_DIR, "engine_param_refs.json"), encoding="utf-8") as f:
        return json.load(f)


def _standard_params(*kinds: str) -> tuple[str, ...]:
    return tuple(n for n, k in _standard_refers_to().items() if k in kinds)


#: The Standard Configuration's parameters holding a list of node names, maps keyed by node
#: name and a list of codelet type names -- derived from the ``refers_to`` declaration, for
#: tests and tools that ask about the Standard Configuration (the resolver itself reads the
#: configuration's own column).
NODE_LIST_PARAMS = _standard_params("node_list", "trigger_node_list")
NODE_MAP_PARAMS = _standard_params("node_map")
CODELET_TYPE_LIST_PARAMS = _standard_params("codelet_type_list")

#: The tables ``rename_enum_value`` renames a row of: every enum table (not addressable by the
#: generic ops) and ``theme_relations``, whose rows the engine's vocabulary binds as well.
RENAMEABLE_TABLES = (*sorted(ENUM_REGISTRY), "theme_relations")

#: Tables whose ``value`` column is parameter text typed by ``value_type``.
PARAM_TABLES = ("engine_params", "formula_coefficients")

#: The role vocabulary by target kind.
ROLE_NAMES: dict[str, dict[str, str]] = {
    NODE: {r.name: r.cardinality for r in ROLES if r.target_kind == NODE},
    CODELET_TYPE: {r.name: r.cardinality for r in ROLES if r.target_kind == CODELET_TYPE},
}
ORDERED_ROLES = frozenset(r.name for r in ROLES if r.cardinality == ORDERED)


def _column_type(column: Any, code: bool, name: str) -> str:
    if code:
        return "code_exec" if name == "execute_body" else "code_eval"
    t = column.type
    if isinstance(t, (JSON, JSONB)):
        return "json"
    if isinstance(t, Boolean):
        return "bool"
    if isinstance(t, Float):
        return "float"
    if isinstance(t, Integer):
        return "int"
    return "str"


def _required(column: Any) -> bool:
    return not column.nullable and column.default is None and column.server_default is None


def _build_input() -> dict[str, InputSpec]:
    out: dict[str, InputSpec] = {}
    for tname, spec in REGISTRY.items():
        columns: dict[str, ColumnSpec] = {}
        for cname in spec.stored_columns:
            column = spec.table.columns[cname]
            ref = REFERENCES.get((tname, cname))
            columns[cname] = ColumnSpec(
                type=_column_type(column, cname in spec.code_columns, cname),
                nullable=bool(column.nullable),
                required=_required(column),
                reference=Reference(ref[0], ref[1]) if ref else None,
                value_type_column="value_type" if tname in PARAM_TABLES and cname == "value" else None,
            )
        out[tname] = InputSpec(tname, tuple(spec.key), columns)
    return out


#: The configuration-input checks' view of the addressable tables (C0's ``TableSpec``).
INPUT_TABLES: dict[str, InputSpec] = _build_input()


def column_defaults(spec: RegistrySpec) -> dict[str, Any]:
    """``column -> default`` for the columns a row may omit: a Python value, the marker
    ``"$next"`` (one past the largest value in the table: the ordinals) or ``"$codelet_type"``
    (the posting rule's key defaults to its codelet type)."""
    out: dict[str, Any] = {}
    for cname in spec.stored_columns:
        column = spec.table.columns[cname]
        d = column.default
        if d is None:
            out[cname] = None
        elif getattr(d, "is_scalar", False):
            out[cname] = d.arg
        elif getattr(d, "is_callable", False):
            out[cname] = "$codelet_type" if cname == "rule_key" else None
        else:  # a clause element: the ``_next_after_last`` scalar subquery
            out[cname] = "$next"
    return out


def language_of(table: str, column: str) -> str | None:
    """``codelet_body``, ``expression`` or ``None`` for a column that is not code."""
    spec = REGISTRY[table]
    if column not in spec.code_columns:
        return None
    return "codelet_body" if column == "execute_body" else "expression"


# ---------------------------------------------------------------------------
# GET /api/configurations/{id}/schema
# ---------------------------------------------------------------------------

GENERIC_OPS = ("insert", "update", "delete")
CONVENIENCE_OPS = (
    "add_node", "remove_node", "rename_node", "merge_nodes", "add_link", "remove_link",
    "add_param", "set_param", "adjust_param", "set_coefficient", "adjust_coefficient", "set_urgency_level",
    "adjust", "list_add", "list_remove", "reorder", "move_layout", "add_trigger",
    "remove_trigger", "rebind_role", "unbind_role", "add_codelet_type", "remove_codelet_type",
    "set_codelet_body", "set_predicate", "set_formula", "set_template", "add_posting_rule",
    "remove_posting_rule", "add_demo_problem", "rename_enum_value",
)


def schema(registry: Mapping[str, RegistrySpec] | None = None) -> dict[str, Any]:
    """The table registry as JSON-compatible data: tables, columns, keys, which columns are
    code or JSON, and the vocabularies and ops a client needs to build a batch."""
    registry = REGISTRY if registry is None else registry
    tables = []
    for name in sorted(registry):
        spec = registry[name]
        columns = []
        for cname in spec.stored_columns:
            column = spec.table.columns[cname]
            is_code = cname in spec.code_columns
            ref = REFERENCES.get((name, cname))
            columns.append(
                {
                    "name": cname,
                    "type": _column_type(column, is_code, cname),
                    "nullable": bool(column.nullable),
                    "required": _required(column),
                    "key": cname in spec.key,
                    "order": cname in spec.order,
                    "code": is_code,
                    "language": language_of(name, cname) if name in REGISTRY else None,
                    "json": cname in spec.json_columns,
                    "reference": {"target": ref[0], "many": ref[1]} if ref else None,
                    "value_type_column": "value_type" if name in PARAM_TABLES and cname == "value" else None,
                }
            )
        tables.append(
            {
                "name": name,
                "key": list(spec.key),
                "order": list(spec.order),
                "unique": [list(u) for u in UNIQUE_EXTRA.get(name, [])],
                "columns": columns,
            }
        )
    return {
        "tables": tables,
        "ops": {"generic": list(GENERIC_OPS), "convenience": list(CONVENIENCE_OPS)},
        "roles": {kind: dict(names) for kind, names in ROLE_NAMES.items()},
        "value_types": list(VALUE_TYPES),
        # The vocabulary tables ``rename_enum_value`` renames a row of, with the column that
        # binds a row to the engine's vocabulary and the names it may hold; and what an
        # ``engine_params.refers_to`` may say.
        "vocabulary": {"tables": list(RENAMEABLE_TABLES), "roles": roles_by_table()},
        "refers_to": list(REFERS_TO_KINDS),
    }
