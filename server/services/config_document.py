"""``ConfigDocument``: a configuration as an immutable, copy-on-write set of tables (S0).

A Training Mode Session's configuration changes over time, and every version has to be
cheap to make, to hash and to turn into the ``MetadataProvider`` a run executes under.
This module is the one pure type all of that is done on:

* ``ConfigDocument`` holds the configuration's tables (keyed by the registry's table names),
  each an ordered ``natural key -> row`` mapping.  A document is never mutated; a change
  makes a new document that shares every table it did not touch.
* ``apply_resolved(cfg, ops)`` is the pure applier of *resolved* ops (config plan 3.12.0):
  generic ``insert`` / ``update`` / ``delete`` with absolute values.  It validates nothing;
  validation and the expansion of convenience ops belong to ``resolve``.
* ``provider(cfg, previous=None)`` builds the ``MetadataProvider``.  The row-to-provider
  conversion is ``metadata_service.provider_from_tables``, the same code the database path
  runs, so there is one implementation.  The rebuild is per provider field: a field whose
  tables are untouched is shared, by reference, with the document it came from.
* ``config_hash(cfg)`` equals ``server.engine.hashing.config_hash(provider(cfg))`` and is
  computed incrementally from cached per-field digests.
* ``diff(a, b)`` returns the resolved ops that turn ``a`` into ``b``.
* The codecs turn a document into and from JSON-compatible data, and read one from the
  database tables or from the Metacat Standard Configuration files.

The core is pure: no database and no file is touched, except by the two codec functions
whose job it is (``document_from_db``, ``document_from_standard_files``).

Rows are plain dicts of column name to JSON-compatible value (a rational stays its ``"n/m"``
text; ``int`` and ``float`` keep their types).  The surrogate ``id`` is not part of a row: it
is not stable across configurations, and the natural key replaces it.  Rows and tables are
shared between documents, so nothing may mutate them.

Order is behaviour for the nodes, links, codelet types, parameters and posting rules.  A
table with order columns is kept sorted by them (stable: a row that ties goes after the
rows already there); any other table keeps insertion order.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, fields
from types import MappingProxyType
from typing import Any

from server.engine.hashing import HASH_EXCLUDED_FIELDS, _field_digest, combine
from server.engine.metadata import MetadataProvider
from server.services.metadata_service import (
    ENUM_TABLE_MODELS,
    PROVIDER_FIELD_TABLES,
    build_provider_field,
    load_rows_from_db,
)

Row = Mapping[str, Any]
Table = Mapping[tuple, Row]
Op = dict[str, Any]


class ConfigDocumentError(ValueError):
    """An op that cannot be applied to the document (an unknown table, a missing or duplicate key)."""


# ---------------------------------------------------------------------------
# Tables: natural key and order
# ---------------------------------------------------------------------------

# Every table's natural key and order columns come from ``config_registry._NATURAL_KEYS``
# (see ``_build_specs``); the engine depends on this order (the role tables sort by
# ``(role, ordinal)`` in byte order, for example).
def _build_specs() -> dict[str, tuple[tuple[str, ...], tuple[str, ...]]]:
    """Each table's ``(key, order)``, read from the one declaration, ``config_registry._NATURAL_KEYS``.

    The enum tables are not in that declaration (the change API does not address them): their
    key is ``name`` and their order ``sort_order``.
    """
    from server.services.config_registry import _NATURAL_KEYS

    specs: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = dict(_NATURAL_KEYS)
    for name in ENUM_TABLE_MODELS:
        specs[name] = (("name",), ("sort_order",))
    return specs


_SPECS = _build_specs()

#: Every table a document holds, in a fixed order.
TABLE_NAMES: tuple[str, ...] = tuple(_SPECS)

#: The provider field each table feeds.
_TABLE_FIELDS: dict[str, tuple[str, ...]] = {}
for _field_name, _tables in PROVIDER_FIELD_TABLES.items():
    for _t in _tables:
        _TABLE_FIELDS.setdefault(_t, ())
        _TABLE_FIELDS[_t] += (_field_name,)

#: The provider fields the configuration hash covers.
HASHED_FIELDS: tuple[str, ...] = tuple(
    f.name for f in fields(MetadataProvider) if f.name not in HASH_EXCLUDED_FIELDS
)


def key_columns(table: str) -> tuple[str, ...]:
    return _SPECS[table][0]


def order_columns(table: str) -> tuple[str, ...]:
    """The declared order columns (``sort_order``, ``ordinal``) of *table*."""
    return _SPECS[table][1]


def total_order_columns(table: str) -> tuple[str, ...]:
    """The table's one total order: the declared columns, then the rest of the natural key."""
    from server.services.config_registry import total_order

    key, order = _SPECS[table]
    return total_order(key, order)


def _key_of(row: Row, cols: tuple[str, ...]) -> tuple:
    """The natural key of a row; a NULL part is read as ``''`` (a link with no label)."""
    return tuple("" if row.get(c) is None else row[c] for c in cols)


def _key_dict(table: str, key: tuple) -> dict[str, Any]:
    return dict(zip(key_columns(table), key))


def _sorted_items(table: str, items: Iterable[tuple[tuple, Row]]) -> list[tuple[tuple, Row]]:
    order = total_order_columns(table)
    items = list(items)
    if order:
        items.sort(key=lambda kv: tuple("" if kv[1].get(c) is None else kv[1][c] for c in order))
    return items


def _freeze(table: str, items: Iterable[tuple[tuple, Row]], *, sort: bool) -> Table:
    pairs = _sorted_items(table, items) if sort else list(items)
    return MappingProxyType(dict(pairs))


# ---------------------------------------------------------------------------
# The document
# ---------------------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class ConfigDocument:
    """A configuration: its tables, a version and cached per-field digests.

    ``version`` is the episode version of the last entry that changed anything (the caller
    supplies it; ``apply_resolved`` adds one when it is not told).  ``digests`` caches, per
    hashed provider field, the digest of that field.  The two cache members (``digests`` and
    the built provider fields) fill lazily and are carried to a new document for every field
    whose tables the change did not touch.

    Equality is by identity; ``content_equals`` compares two documents' tables, order included.
    """

    tables: Mapping[str, Table]
    version: int = 0
    digests: dict[str, str] = field(default_factory=dict)
    _built: dict[str, Any] = field(default_factory=dict, repr=False)
    _memo: dict[str, Any] = field(default_factory=dict, repr=False)

    def content_equals(self, other: ConfigDocument) -> bool:
        """Same tables, same rows, same order (the version and the caches are not compared)."""
        if self.tables.keys() != other.tables.keys():
            return False
        return all(
            self.tables[t] is other.tables[t] or list(self.tables[t].items()) == list(other.tables[t].items())
            for t in self.tables
        )


def from_rows(rows: Mapping[str, Iterable[Row]], version: int = 0) -> ConfigDocument:
    """A document from ``{table: rows}``.  A missing table is empty; an unknown one is an error.

    A table with order columns is sorted by them; any other keeps the rows' order.  A row
    without an ``id`` key is taken as it is; one with an ``id`` loses it.
    """
    unknown = set(rows) - set(TABLE_NAMES)
    if unknown:
        raise ConfigDocumentError(f"unknown tables: {sorted(unknown)}")
    tables: dict[str, Table] = {}
    for name in TABLE_NAMES:
        cols = key_columns(name)
        items: list[tuple[tuple, Row]] = []
        seen: set[tuple] = set()
        for r in rows.get(name, ()):
            row = {k: v for k, v in r.items() if k != "id"}
            key = _key_of(row, cols)
            if key in seen:
                raise ConfigDocumentError(f"{name}: duplicate key {key!r}")
            seen.add(key)
            items.append((key, row))
        tables[name] = _freeze(name, items, sort=True)
    return ConfigDocument(tables=MappingProxyType(tables), version=version)


# ---------------------------------------------------------------------------
# apply_resolved
# ---------------------------------------------------------------------------


def _apply_to_table(table: str, current: Table, ops: Sequence[Op]) -> Table:
    """The table after *ops* (all on this table), in order."""
    cols = key_columns(table)
    order = set(total_order_columns(table))
    rows: dict[tuple, Row] = dict(current)
    resort = False
    for op in ops:
        kind = op["op"]
        if kind == "insert":
            row = dict(op["row"])
            for c, v in (op.get("key") or {}).items():
                row.setdefault(c, v)
            key = _key_of(row, cols)
            if key in rows:
                raise ConfigDocumentError(f"{table}: insert of existing key {key!r}")
            rows[key] = row
            resort = resort or bool(order)
        elif kind == "update":
            key = _key_of(op["key"], cols)
            old = rows.get(key)
            if old is None:
                raise ConfigDocumentError(f"{table}: update of missing key {key!r}")
            new = {**old, **op["set"]}
            new_key = _key_of(new, cols)
            if new_key != key:  # re-keyed: the row keeps its place until the order is re-applied
                if new_key in rows:
                    raise ConfigDocumentError(f"{table}: re-key onto existing key {new_key!r}")
                rows = {(new_key if k == key else k): (new if k == key else v) for k, v in rows.items()}
                resort = resort or bool(order)
            else:
                rows[key] = new
            resort = resort or bool(order & op["set"].keys())
        elif kind == "delete":
            key = _key_of(op["key"], cols)
            if key not in rows:
                raise ConfigDocumentError(f"{table}: delete of missing key {key!r}")
            del rows[key]
        else:
            raise ConfigDocumentError(f"unknown op {kind!r}")
    return _freeze(table, rows.items(), sort=resort)


def apply_resolved(cfg: ConfigDocument, ops: Sequence[Op], version: int | None = None) -> ConfigDocument:
    """The document after the resolved *ops*, applied in order.  Pure; no validation.

    Only the tables the ops name are copied; every other table is the same object in the
    result.  Cached digests and built provider fields are carried over for every provider
    field none of whose tables changed.  *version* is the result's version; when omitted it
    is ``cfg.version + 1`` if there are ops and ``cfg.version`` if there are none.
    """
    by_table: dict[str, list[Op]] = {}
    for op in ops:
        t = op["table"]
        if t not in cfg.tables:
            raise ConfigDocumentError(f"unknown table {t!r}")
        by_table.setdefault(t, []).append(op)
    if version is None:
        version = cfg.version + 1 if ops else cfg.version
    if not by_table:
        return ConfigDocument(
            tables=cfg.tables, version=version, digests=dict(cfg.digests), _built=dict(cfg._built)
        )
    tables = dict(cfg.tables)
    for t, t_ops in by_table.items():
        tables[t] = _apply_to_table(t, cfg.tables[t], t_ops)
    touched = {f for t in by_table for f in _TABLE_FIELDS.get(t, ())}
    return ConfigDocument(
        tables=MappingProxyType(tables),
        version=version,
        digests={f: d for f, d in cfg.digests.items() if f not in touched},
        _built={f: v for f, v in cfg._built.items() if f not in touched},
    )


# ---------------------------------------------------------------------------
# provider and config_hash
# ---------------------------------------------------------------------------


def _field_value(cfg: ConfigDocument, name: str, previous: ConfigDocument | None = None) -> Any:
    """One provider field of *cfg*: cached, shared with *previous*, or built."""
    built = cfg._built
    if name in built:
        return built[name]
    deps = PROVIDER_FIELD_TABLES[name]
    if previous is not None and previous is not cfg and all(cfg.tables[t] is previous.tables[t] for t in deps):
        value = _field_value(previous, name)
        if name in previous.digests:
            cfg.digests.setdefault(name, previous.digests[name])
    else:
        value = build_provider_field(name, cfg.tables)
    built[name] = value
    return value


def provider(cfg: ConfigDocument, previous: ConfigDocument | None = None) -> MetadataProvider:
    """The ``MetadataProvider`` for *cfg*.

    Built with the database path's own conversion (``metadata_service``), one provider field
    at a time.  A field is reused from the document's cache; failing that, from *previous*
    (the document this one was made from) when the tables it depends on are the same objects
    in both; failing that, it is rebuilt.  Nothing is compiled here.
    """
    cached = cfg._memo.get("provider")
    if cached is not None:
        return cached
    meta = MetadataProvider(**{name: _field_value(cfg, name, previous) for name in PROVIDER_FIELD_TABLES})
    cfg._memo["provider"] = meta
    return meta


def field_digests(cfg: ConfigDocument, previous: ConfigDocument | None = None) -> dict[str, str]:
    """``{hashed provider field: digest}``; only fields without a cached digest are computed."""
    for name in HASHED_FIELDS:
        if name not in cfg.digests:
            value = _field_value(cfg, name, previous)
            if name not in cfg.digests:  # _field_value may have carried one over
                cfg.digests[name] = _field_digest(value)
    return {name: cfg.digests[name] for name in HASHED_FIELDS}


def config_hash(cfg: ConfigDocument, previous: ConfigDocument | None = None) -> str:
    """``server.engine.hashing.config_hash(provider(cfg))``, from the cached per-field digests."""
    return combine(field_digests(cfg, previous))


# ---------------------------------------------------------------------------
# diff
# ---------------------------------------------------------------------------


def _insert_op(table: str, key: tuple, row: Row) -> Op:
    return {"op": "insert", "table": table, "key": _key_dict(table, key), "row": dict(row)}


def _plan_simple(table: str, a: Table, b: Table) -> list[Op]:
    ops: list[Op] = []
    for key in a:
        if key not in b:
            ops.append({"op": "delete", "table": table, "key": _key_dict(table, key)})
    for key, row in b.items():
        old = a.get(key)
        if old is not None and old != row:
            changed = {c: v for c, v in row.items() if c not in old or old[c] != v}
            changed.update({c: None for c in old if c not in row})
            ops.append({"op": "update", "table": table, "key": _key_dict(table, key), "set": changed})
    for key, row in b.items():
        if key not in a:
            ops.append(_insert_op(table, key, row))
    return ops


def _plan_prefix(table: str, a: Table, b: Table) -> list[Op]:
    """Keep the longest common prefix of the surviving rows in place; re-insert the rest in b's order."""
    kb = list(b)
    common = [k for k in a if k in b]
    i = 0
    while i < len(common) and i < len(kb) and common[i] == kb[i]:
        i += 1
    redo = set(common[i:])
    ops: list[Op] = []
    for key in a:
        if key not in b or key in redo:
            ops.append({"op": "delete", "table": table, "key": _key_dict(table, key)})
    for key in kb[:i]:
        old, row = a[key], b[key]
        if old != row:
            changed = {c: v for c, v in row.items() if c not in old or old[c] != v}
            changed.update({c: None for c in old if c not in row})
            ops.append({"op": "update", "table": table, "key": _key_dict(table, key), "set": changed})
    for key in kb[i:]:
        ops.append(_insert_op(table, key, b[key]))
    return ops


def _plan_replace(table: str, a: Table, b: Table) -> list[Op]:
    ops: list[Op] = [{"op": "delete", "table": table, "key": _key_dict(table, k)} for k in a]
    ops.extend(_insert_op(table, k, r) for k, r in b.items())
    return ops


def diff(a: ConfigDocument, b: ConfigDocument) -> list[Op]:
    """The resolved ops that turn *a* into *b* (``apply_resolved(a, diff(a, b))`` has b's tables).

    Per table: delete the rows only *a* has, update the rows that differ (only the changed
    columns), insert the rows only *b* has.  If that would not give *b*'s order (a table
    without order columns appends, so a moved row needs a delete and an insert), the plan
    keeps the common prefix and re-inserts the rest; as a last resort the table is replaced.
    Each plan is checked by applying it.
    """
    ops: list[Op] = []
    for table in TABLE_NAMES:
        ta, tb = a.tables[table], b.tables[table]
        if ta is tb:
            continue
        for plan in (_plan_simple, _plan_prefix, _plan_replace):
            t_ops = plan(table, ta, tb)
            if list(_apply_to_table(table, ta, t_ops).items()) == list(tb.items()):
                ops.extend(t_ops)
                break
    return ops


# ---------------------------------------------------------------------------
# Codecs
# ---------------------------------------------------------------------------


def to_data(cfg: ConfigDocument) -> dict[str, Any]:
    """JSON-compatible data: ``{"version": n, "tables": {table: [row, ...]}}``, rows in order.

    Rationals are the ``"n/m"`` text the rows hold; ``int`` and ``float`` stay as they are, and
    ``json`` keeps ``5`` apart from ``5.0``.
    """
    return {
        "version": cfg.version,
        "tables": {t: [dict(r) for r in cfg.tables[t].values()] for t in TABLE_NAMES},
    }


def from_data(data: Mapping[str, Any]) -> ConfigDocument:
    """The inverse of :func:`to_data`."""
    return from_rows(data["tables"], version=data.get("version", 0))


def to_json(cfg: ConfigDocument) -> str:
    return json.dumps(to_data(cfg), separators=(",", ":"))


def from_json(text: str) -> ConfigDocument:
    return from_data(json.loads(text))


async def document_from_db(session: Any, version: int = 0) -> ConfigDocument:
    """The global configuration as held in the database tables."""
    return from_rows(await load_rows_from_db(session), version=version)


def rows_from_standard_files(seed_dir: str) -> dict[str, list[dict[str, Any]]]:
    """The Metacat Standard Configuration files as rows, with the columns the loader writes.

    The same rows the start-up load (``standard_configuration.seed_metadata_from_json``)
    writes to the database, so a document from the files equals one from a freshly loaded
    database.
    """
    from server.services.standard_configuration import _coefficient_columns, _param_columns

    def load(filename: str) -> Any:
        with open(os.path.join(seed_dir, filename)) as f:
            return json.load(f)

    rows: dict[str, list[dict[str, Any]]] = {}
    enums = load("enums.json")
    for name in ENUM_TABLE_MODELS:
        rows[name] = [
            {
                "name": r["name"],
                "display_label": r["display_label"],
                "sort_order": r["sort_order"],
                "description": r.get("description", ""),
            }
            for r in enums.get(name, [])
        ]
    rows["slipnet_node_defs"] = [
        {
            "name": n["name"],
            "sort_order": pos,
            "short_name": n["short_name"],
            "conceptual_depth": n["conceptual_depth"],
            "description": n.get("description", ""),
            "descriptor_predicate": n.get("descriptor_predicate"),
            "plain_name": n.get("plain_name"),
            "glyph": n.get("glyph"),
            "numeric_value": n.get("numeric_value"),
            "full_name": n.get("full_name"),
            "cm_short_name": n.get("cm_short_name"),
            "article_an": n.get("article_an"),
        }
        for pos, n in enumerate(load("slipnet_nodes.json"))
    ]
    rows["slipnet_link_defs"] = [
        {
            "sort_order": pos,
            "from_node": lk["from_node"],
            "to_node": lk["to_node"],
            "link_type": lk["link_type"],
            "label_node": lk.get("label_node"),
            "link_length": lk.get("link_length"),
            "fixed_length": lk["fixed_length"],
        }
        for pos, lk in enumerate(load("slipnet_links.json"))
    ]
    rows["codelet_type_defs"] = [
        {
            "name": c["name"],
            "sort_order": pos,
            "family": c["family"],
            "phase": c["phase"],
            "description": c.get("description", ""),
            "source_file": c.get("source_file", ""),
            "source_line": c.get("source_line", 0),
            "execute_body": c.get("execute_body", ""),
        }
        for pos, c in enumerate(load("codelet_types.json"))
    ]
    rows["engine_params"] = [
        {"name": k, "sort_order": pos, **_param_columns(v)}
        for pos, (k, v) in enumerate(load("engine_params.json").items())
    ]
    rows["urgency_levels"] = [
        {"name": k, "value": v, "sort_order": pos} for pos, (k, v) in enumerate(load("urgency_levels.json").items())
    ]
    rows["formula_coefficients"] = [
        {"name": k, "sort_order": pos, **_coefficient_columns(v)}
        for pos, (k, v) in enumerate(load("formula_coefficients.json").items())
    ]
    rows["demo_problems"] = [
        {
            "name": d["name"],
            "section": d.get("section", ""),
            "initial": d["initial"],
            "modified": d["modified"],
            "target": d["target"],
            "answer": d.get("answer"),
            "seed": d["seed"],
            "description": d.get("description", ""),
        }
        for d in load("demo_problems.json")
    ]
    posting = load("posting_rules.json")
    rows["posting_rules"] = [
        {
            "rule_key": pr.get("rule_key", pr["codelet_type"]),
            "sort_order": pos,
            "codelet_type": pr["codelet_type"],
            "direction": pr["direction"],
            "urgency_level": pr.get("urgency_level"),
            "urgency_formula": pr.get("urgency_formula"),
            "posting_formula": pr["posting_formula"],
            "count_formula": pr["count_formula"],
            "count_values": pr.get("count_values"),
            "condition": pr["condition"],
            "triggering_slipnodes": pr.get("triggering_slipnodes"),
        }
        for pos, pr in enumerate(posting.get("posting_rules", []))
    ]
    patterns: list[dict[str, Any]] = []
    for pattern_name, entries in posting.get("codelet_patterns", {}).items():
        for codelet_type, urgency_level in entries:
            patterns.append(
                {
                    "ordinal": len(patterns),
                    "pattern_name": pattern_name,
                    "codelet_type": codelet_type,
                    "urgency_level": urgency_level,
                }
            )
    rows["codelet_pattern_defs"] = patterns
    rows["theme_dimension_defs"] = [
        {"slipnet_node": td["slipnet_node"], "valid_relations": td["valid_relations"]}
        for td in load("theme_dimensions.json").get("dimensions", [])
    ]
    rows["slipnet_layout"] = [
        {"node_name": name, "grid_row": p[0], "grid_col": p[1], "sort_order": pos}
        for pos, (name, p) in enumerate(load("slipnet_layout.json").get("node_positions", {}).items())
    ]
    roles = load("roles.json")
    rows["slipnet_node_roles"] = [
        {"role": r["role"], "ordinal": r["ordinal"], "node_name": r["node_name"]}
        for r in roles.get("node_roles", [])
    ]
    rows["codelet_type_roles"] = [
        {"role": r["role"], "ordinal": r["ordinal"], "codelet_type": r["codelet_type"]}
        for r in roles.get("codelet_roles", [])
    ]
    rows["theme_relations"] = [
        {
            "name": r["name"],
            "ordinal": r["ordinal"],
            "node_name": r.get("node_name"),
            "abstractness": r.get("abstractness"),
            "description": r.get("description", ""),
        }
        for r in load("theme_relations.json")
    ]
    rows["commentary_templates"] = [{"template_key": "all", "template_data": load("commentary_templates.json")}]
    return rows


def document_from_standard_files(seed_dir: str, version: int = 0) -> ConfigDocument:
    """The Metacat Standard Configuration files as a document."""
    return from_rows(rows_from_standard_files(seed_dir), version=version)
