"""``resolve(cfg, batch) -> (resolved_ops, report)``: the change API's pure core (3.12).

``cfg`` is a ``ConfigDocument`` (S0); ``batch`` is the change batch of 3.12.1 as plain data.
The batch is admitted already (C5 did the compare-and-set on ``base_version``, so this module
neither reads nor checks it).  The function is deterministic and has no side effects; it
never touches a database, a file or ``cfg``.

How it works
------------
* ``check_shape`` reads the whole batch (400 ``malformed``).
* Each op is then processed in order on a working document (``apply_resolved`` one resolved
  op at a time, so what an op sees is what the earlier ops produced).  A convenience op
  expands into generic ops; a removal cascades (3.12.5); a relative op reads the current
  value and emits an absolute one.  Every emitted op is a plain insert / update / delete
  (``config_document`` documents the three shapes).
* An op that cannot be applied raises an internal failure: under ``abort`` the batch is
  refused (:class:`ChangeRefused`, nothing is returned); under ``skip`` that op's work is
  rolled back, it is listed in ``skipped``, and the next op runs.
* After the last op, every row the batch wrote is checked for references to something that
  does not exist in the *resulting* state (422 ``unknown_reference``), so a node and its
  links may be inserted in either order.  Under ``skip`` the op that wrote a dangling row is
  skipped and the batch is run again.

There is no check of *what* a change does (3.4(a)): any node, role, letter or coefficient may
be removed, renamed or merged, including one a session's Episodic Memory names.

Episodic Memory and the names it holds
--------------------------------------
A session's Episodic Memory persists names: nodes and theme relations in theme patterns, theme
types in theme patterns, rule and clause types in rule signatures.  The rule is one for all of
them, a node or a vocabulary row (``rename_enum_value``) alike: the change API **neither refuses
nor rewrites**.  The rename, removal or merge is carried out on the configuration, and the
memory keeps the names it stored (``test_a_node_that_memory_names_can_be_removed_renamed_or_merged``
and ``test_a_name_that_memory_holds_can_be_renamed_by_every_source`` pin it).  What became of an
old name is the journal's story (``GET /api/journal/where-did-name-go``).

Vocabulary rows (``rename_enum_value``)
---------------------------------------
Renaming a row of an enum table (or of ``theme_relations``) rewrites every column that names
it (``REFERENCES`` and ``ENUM_RENAME_EXTRA`` in ``spec.py``), keeps the row's ``role`` (its
``behaviour``, for ``link_types``) and its place, and rewrites the commentary sections keyed by
the table's names (``TEMPLATE_KEYED_BY``).  Bodies, predicates, formulas, parameters and
templates that still spell the old name are listed as ``dangling``, exactly as ``rename_node``
lists code.  The enum tables are not addressed by the generic ops (``schema`` does not list them);
the Admin enum editor's creates, updates and deletes follow the rules of ``vocabulary.py`` (a
role is a name of the table's vocabulary and held by one row; a bound row is not deleted:
``422 role_bound``).

Parameters that name things
---------------------------
``engine_params.refers_to`` declares what a parameter's value names (``spec.REFERS_TO_KINDS``):
the cascades read it from the configuration they resolve against, so no parameter name is
written in this module.  **A rule-trigger edit (``add_trigger``, ``remove_trigger``) also
changes the parameter whose ``refers_to`` is ``trigger_node_list``** (``top_down_slipnodes`` in
the Metacat Standard Configuration): a node added as a trigger is added to its list, and one
removed from a rule is removed from it only when no rule still triggers it.  A configuration
that declares no such parameter leaves every parameter alone.  The clampable codelet patterns are
named by the keys of the ``clampable_pattern_map`` parameter, and no operation renames one: a batch
that edits the menu so that a ``clampable_pattern_list`` parameter still names a pattern it no longer
offers lists that parameter as ``dangling``.

The report
----------
``{"ok": True, "applied", "skipped", "cascaded", "dangling", "affected", "effects",
"advisories"}``.  C5 adds ``configuration_id``, ``version_before``, ``version_after``,
``episode_version`` and ``batch_id``.  See ``resolve`` for each list.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Callable, Mapping

from server.engine.parameters import RUN_PARAMETERS
from server.engine.start_check import (
    REQUIRED_ENGINE_PARAMETERS,
    REQUIRED_FORMULA_COEFFICIENTS,
    urgency_levels_read_by_bodies,
)
from server.services.change_resolve import checks, vocabulary
from server.services.change_resolve.errors import ChangeRefused
from server.services.change_resolve.patch import PatchError, apply_patch, parse_pointer
from server.services.change_resolve.spec import (
    INPUT_TABLES,
    ORDERED_ROLES,
    PARAM_TABLES,
    ENUM_RENAME_EXTRA,
    REFERENCES,
    REFERS_TO_KINDS,
    RENAMEABLE_TABLES,
    ROLE_NAMES,
    UNIQUE_EXTRA,
    column_defaults,
    language_of,
)
from server.services.config_document import ConfigDocument, apply_resolved
from server.services.config_registry import LAYER_REGISTRY, REGISTRY
from server.services.configuration_input import (
    KEY_EXISTS,
    MALFORMED,
    STALE,
    UNKNOWN_REFERENCE,
    InputProblem,
    check_param_value,
    parse_param_value,
)

NODES = "slipnet_node_defs"
LINKS = "slipnet_link_defs"
LAYOUT = "slipnet_layout"
THEME_DIMS = "theme_dimension_defs"
THEME_RELS = "theme_relations"
NODE_ROLES = "slipnet_node_roles"
CODELETS = "codelet_type_defs"
CODELET_ROLES = "codelet_type_roles"
RULES = "posting_rules"
PATTERNS = "codelet_pattern_defs"
PARAMS = "engine_params"
COEFFS = "formula_coefficients"
LEVELS = "urgency_levels"
DEMOS = "demo_problems"
TEMPLATES = "commentary_templates"
CLAMP_TYPES = "clamp_types"

_RULE_CODE_COLUMNS = ("urgency_formula", "posting_formula", "count_formula", "condition")
_LINK_SHORT = {"from": "from_node", "to": "to_node", "type": "link_type", "label": "label_node",
               "length": "link_length", "fixed": "fixed_length"}
_READ_PARAMS = frozenset(n for n, _ in REQUIRED_ENGINE_PARAMETERS)
_READ_COEFFS = frozenset(n for n, _ in REQUIRED_FORMULA_COEFFICIENTS)
_RANGES = {p.name: (p.minimum, p.maximum) for p in RUN_PARAMETERS
           if p.minimum is not None or p.maximum is not None}


class _Fail(Exception):
    """An op that cannot be applied (internal; refused or skipped by the caller)."""

    def __init__(self, problem: InputProblem):
        super().__init__(problem.message)
        self.problem = problem


def _same(a: Any, b: Any) -> bool:
    """Equal in value and in JSON number type (``5`` is not ``5.0``)."""
    if isinstance(a, bool) != isinstance(b, bool):
        return False
    if isinstance(a, float) != isinstance(b, float):
        return False
    return a == b


def _word(name: str) -> re.Pattern:
    return re.compile(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])")


def _quoted(name: str) -> re.Pattern:
    return re.compile(r"""['"]""" + re.escape(name) + r"""['"]""")


@dataclass
class _Snapshot:
    doc: ConfigDocument
    sizes: tuple[int, ...]
    written: dict


class _Run:
    """One pass over the batch's ops on a working document."""

    def __init__(self, cfg: ConfigDocument, ops: list, skip: bool, excluded: Mapping[int, InputProblem]):
        self.cfg = cfg
        self.doc = cfg
        self.ops = ops
        self.skip = skip
        self.excluded = dict(excluded)
        self.resolved: list[dict] = []
        self.applied: list[dict] = []
        self.cascaded: list[dict] = []
        self.dangling: list[dict] = []
        self.affected: list[dict] = []
        #: advisories raised while resolving (the others are computed from the final document)
        self.advisories_extra: list[dict] = []
        self.failed: dict[int, InputProblem] = {}
        #: (table, key tuple) -> index of the batch op that last wrote the row
        self.written: dict[tuple[str, tuple], int] = {}

    # -- reading ---------------------------------------------------------------

    def rows(self, table: str):
        return self.doc.tables[table]

    def row(self, table: str, key: Mapping[str, Any]) -> dict | None:
        return self.doc.tables[table].get(LAYER_REGISTRY[table].key_tuple(key))

    def key_dict(self, table: str, row: Mapping[str, Any]) -> dict:
        return LAYER_REGISTRY[table].key_of(row)

    def key_tuple_of(self, table: str, row: Mapping[str, Any]) -> tuple:
        spec = LAYER_REGISTRY[table]
        return spec.key_tuple(spec.key_of(row))

    # -- failures ---------------------------------------------------------------

    def fail(self, kind: str, message: str, i: int, field: str | None = None,
             table: str | None = None, key: Any = None) -> _Fail:
        return _Fail(InputProblem(kind, message, i, field, table, key))

    def missing(self, i: int, table: str, key: Mapping[str, Any], field: str = "key") -> _Fail:
        return self.fail(UNKNOWN_REFERENCE, f"{table} has no row with key {list(key.values())}",
                         i, field, table, list(key.values()))

    # -- snapshots (for ``skip``) -------------------------------------------------

    def snapshot(self) -> _Snapshot:
        return _Snapshot(
            self.doc,
            (len(self.resolved), len(self.applied), len(self.cascaded), len(self.dangling),
             len(self.affected)),
            dict(self.written),
        )

    def restore(self, snap: _Snapshot) -> None:
        self.doc = snap.doc
        for lst, n in zip((self.resolved, self.applied, self.cascaded, self.dangling, self.affected),
                          snap.sizes):
            del lst[n:]
        self.written = snap.written

    # -- emitting ------------------------------------------------------------------

    def emit(self, i: int, op: dict, reason: str | None = None, report_as: str | None = None) -> None:
        """Apply one resolved op to the working document and record it.

        *reason* makes it a cascaded row (``cascaded`` entry with that cause); *report_as*
        names the effect the report states when it differs from the op (a rename that is
        carried out as a delete and an insert is reported as an update)."""
        table = op["table"]
        spec = LAYER_REGISTRY[table]
        kind = op["op"]
        before = after = None
        if kind == "update":
            old = self.row(table, op["key"])
            changed = {c: v for c, v in op["set"].items() if c not in old or not _same(old[c], v)}
            if not changed:
                return
            op = {**op, "set": changed}
            before, after = dict(old), {**old, **changed}
        elif kind == "delete":
            before = dict(self.row(table, op["key"]))
        else:
            after = dict(op["row"])
        self.doc = apply_resolved(self.doc, [op], version=self.cfg.version)
        # Only the batch's own writes are reference-checked; a cascade's are not (it may touch a
        # row that already held a reference to something absent, and the batch is not to blame).
        track = reason is None
        if kind == "insert":
            if track:
                self.written[(table, spec.key_tuple(spec.key_of(after)))] = i
        elif kind == "update":
            if (table, spec.key_tuple(op["key"])) in self.written:
                self.written.pop((table, spec.key_tuple(op["key"])))
                track = True
            if track:
                self.written[(table, spec.key_tuple(spec.key_of(after)))] = i
        else:
            self.written.pop((table, spec.key_tuple(op["key"])), None)
        self.resolved.append(op)
        self.applied.append({"op_index": i, "op": op, "before": before, "after": after})
        if reason is not None:
            self.cascaded.append(
                {"cause_op": i, "table": table, "key": dict(op["key"]) if kind != "insert" else spec.key_of(after),
                 "op": report_as or kind, "reason": reason}
            )

    def e_insert(self, i, table, row, **kw):
        self.emit(i, {"op": "insert", "table": table, "key": LAYER_REGISTRY[table].key_of(row), "row": row}, **kw)

    def e_update(self, i, table, key, set_, **kw):
        self.emit(i, {"op": "update", "table": table, "key": dict(key), "set": dict(set_)}, **kw)

    def e_delete(self, i, table, key, **kw):
        self.emit(i, {"op": "delete", "table": table, "key": dict(key)}, **kw)

    # -- validation of one write ---------------------------------------------------

    def shape(self, i: int, op: dict) -> None:
        problems = checks._generic_problems(i, op)
        if problems:
            raise _Fail(problems[0])

    def normalise(self, table: str, row: dict) -> dict:
        """A NULL part of a key is stored as NULL, not ``''``."""
        spec = LAYER_REGISTRY[table]
        for c in spec.key:
            if row.get(c) == "" and spec.table.columns[c].nullable:
                row[c] = None
        return row

    def complete(self, table: str, row: dict) -> dict:
        spec = LAYER_REGISTRY[table]
        defaults = column_defaults(spec)
        if len(spec.order) == 1:  # a new row goes last: order is behaviour (the RNG's)
            defaults[spec.order[0]] = "$next"
        out = {}
        for c, d in defaults.items():
            if c in row:
                out[c] = row[c]
            elif d == "$next":
                values = [r[c] for r in self.rows(table).values() if r.get(c) is not None]
                out[c] = (max(values) + 1) if values else 0
            elif d == "$codelet_type":
                out[c] = row.get("codelet_type")
            else:
                out[c] = d
        return out

    def check_unique(self, i: int, table: str, row: Mapping, exclude: tuple | None) -> None:
        spec = LAYER_REGISTRY[table]
        for cols in UNIQUE_EXTRA.get(table, ()):
            vals = tuple(row.get(c) for c in cols)
            if any(v is None for v in vals):
                continue
            for k, other in self.rows(table).items():
                if k != exclude and tuple(other.get(c) for c in cols) == vals:
                    raise self.fail(KEY_EXISTS, f"{table}: {', '.join(cols)} {list(vals)} is already used",
                                    i, cols[0], table, list(spec.key_tuple(spec.key_of(row))))

    def check_role(self, i: int, table: str, row: Mapping, exclude: tuple | None) -> None:
        """A row of a vocabulary table (``theme_relations``) holds a name of the engine's
        vocabulary for that table, and one no other row holds."""
        spec = LAYER_REGISTRY[table]
        others = (o for k, o in self.rows(table).items() if k != exclude)
        problem = vocabulary.role_problem(
            table, row, others, op_index=i, key=list(spec.key_tuple(spec.key_of(row))))
        if problem is not None:
            raise _Fail(problem)

    def check_code(self, i: int, table: str, row: Mapping, columns) -> None:
        spec = LAYER_REGISTRY[table]
        key = list(spec.key_tuple(spec.key_of(row)))
        for c in columns:
            language = language_of(table, c)
            if language is None or row.get(c) is None:
                continue
            name = str(key[0]) if table != RULES else str(row.get("rule_key") or row.get("codelet_type"))
            found = checks.compile_problem(table, c, row[c], name)
            if found:
                raise _Fail(checks.does_not_compile(i, table, c, key, language, found))

    def check_typed(self, i: int, table: str, row: Mapping) -> None:
        if table == PARAMS and row.get("refers_to") is not None and row["refers_to"] not in REFERS_TO_KINDS:
            raise self.fail(MALFORMED, f"refers_to must be one of {list(REFERS_TO_KINDS)} or null", i,
                            "refers_to", table, [row.get("name")])
        if table in PARAM_TABLES:
            p = check_param_value(row.get("value"), row.get("value_type"), op_index=i, table=table)
            if p is not None:
                raise _Fail(p)

    # -- the generic writes -----------------------------------------------------------

    def do_insert(self, i: int, table: str, row: dict, reason: str | None = None) -> None:
        row = self.normalise(table, dict(row))
        self.shape(i, {"op": "insert", "table": table, "row": row})
        row = self.complete(table, row)
        key = self.key_tuple_of(table, row)
        if key in self.rows(table):
            raise self.fail(KEY_EXISTS, f"{table} already has key {list(key)}", i, "row", table, list(key))
        self.check_unique(i, table, row, None)
        self.check_role(i, table, row, None)
        self.check_code(i, table, row, LAYER_REGISTRY[table].code_columns)
        self.check_typed(i, table, row)
        self.e_insert(i, table, row, reason=reason)

    def do_update(self, i: int, table: str, key: Mapping, fields: Mapping, *, expect: Mapping | None = None,
                  patch: Mapping | None = None, reason: str | None = None) -> None:
        spec = LAYER_REGISTRY[table]
        old = self.row(table, key)
        if old is None:
            raise self.missing(i, table, dict(key))
        if expect is not None and not all(c in old and _same(old[c], v) for c, v in expect.items()):
            raise self.fail(STALE, f"{table} row {list(key.values())} differs from expect", i,
                            "expect", table, list(key.values()))
        new_fields = dict(fields)
        for column, patch_ops in (patch or {}).items():
            new_fields[column] = self.patched(i, table, old, column, patch_ops, key)
        new_fields = self.normalise(table, new_fields)
        new_row = {**old, **new_fields}
        if set(new_fields) & set(spec.key) and spec.key_tuple(spec.key_of(new_row)) != spec.key_tuple(key):
            renamer = _RENAMERS.get(table)
            if renamer is not None:
                rest = {c: v for c, v in new_fields.items() if c not in spec.key}
                self.shape(i, {"op": "update", "table": table, "key": dict(key), "fields": new_fields})
                renamer(self, i, key, new_row[spec.key[0]])
                if rest:
                    self.do_update(i, table, {spec.key[0]: new_row[spec.key[0]]}, rest)
                return
            new_key = spec.key_tuple(spec.key_of(new_row))
            if new_key in self.rows(table):
                raise self.fail(KEY_EXISTS, f"{table} already has key {list(new_key)}", i, "fields",
                                table, list(new_key))
        self.shape(i, {"op": "update", "table": table, "key": dict(key), "fields": new_fields})
        changed = [c for c, v in new_fields.items() if c not in old or not _same(old[c], v)]
        if not changed:
            return
        self.check_unique(i, table, new_row, spec.key_tuple(key))
        if table in vocabulary.VOCABULARY_TABLES and (vocabulary.VOCABULARY_TABLES[table].column in changed):
            self.check_role(i, table, new_row, spec.key_tuple(key))
        self.check_code(i, table, new_row, [c for c in changed if c in spec.code_columns])
        if table in PARAM_TABLES and ({"value", "value_type", "refers_to"} & set(changed)):
            self.check_typed(i, table, new_row)
        self.e_update(i, table, key, {c: new_fields[c] for c in changed}, reason=reason)

    def patched(self, i, table, old, column, patch_ops, key):
        value = old[column]
        text = table in PARAM_TABLES
        if text:
            if old.get("value_type") != "json":
                raise self.fail(MALFORMED, f"{table}.{column} is not JSON-typed; a JSON Patch needs value_type json",
                                i, f"patch.{column}", table, list(key.values()))
            ok, value = parse_param_value(old[column], "json")
            if not ok:
                raise self.fail(MALFORMED, f"{table}.{column} does not parse as JSON", i,
                                f"patch.{column}", table, list(key.values()))
        try:
            result = apply_patch(value, patch_ops)
        except PatchError as exc:
            kind = {"malformed": MALFORMED, "missing": UNKNOWN_REFERENCE, "test": STALE}[exc.kind]
            raise self.fail(kind, str(exc), i, f"patch.{column}", table, list(key.values()))
        return json.dumps(result) if text else result

    def do_delete(self, i: int, table: str, key: Mapping, *, expect: Mapping | None = None,
                  ok_if_missing: bool = False, reason: str | None = None) -> None:
        old = self.row(table, key)
        if old is None:
            if ok_if_missing:
                return
            raise self.missing(i, table, dict(key))
        if expect is not None and not all(c in old and _same(old[c], v) for c, v in expect.items()):
            raise self.fail(STALE, f"{table} row {list(key.values())} differs from expect", i,
                            "expect", table, list(key.values()))
        if table == THEME_RELS:
            # A bound relation is unbound first, like every bound row (``role_bound``).
            problem = vocabulary.delete_problem(table, old, op_index=i)
            if problem is not None:
                raise _Fail(problem)
        remover = _REMOVERS.get(table)
        if remover is not None:
            remover(self, i, old)
        else:
            self.e_delete(i, table, LAYER_REGISTRY[table].key_of(old), reason=reason)
            if table in PARAM_TABLES:
                pass  # effects are reported by the run-start comparison

    # -- code mentions (dangling) -----------------------------------------------------

    def code_sources(self):
        for r in self.rows(CODELETS).values():
            yield CODELETS, r["name"], "execute_body", r.get("execute_body") or ""
        for r in self.rows(NODES).values():
            yield NODES, r["name"], "descriptor_predicate", r.get("descriptor_predicate") or ""
        for r in self.rows(RULES).values():
            for c in _RULE_CODE_COLUMNS:
                yield RULES, r["rule_key"], c, r.get(c) or ""

    def mark_dangling(self, i: int, pattern: re.Pattern, what: str, skip: tuple[str, str] | None = None) -> None:
        for table, name, column, source in self.code_sources():
            if skip == (table, name):
                continue
            if source and pattern.search(source):
                self.dangling.append(
                    {"cause_op": i, "table": table, "key": LAYER_REGISTRY[table].key_of({LAYER_REGISTRY[table].key[0]: name}),
                     "column": column, "reason": f"source names {what}"}
                )

    def mark_scalar_params(self, i: int, names: tuple[str, ...], value: str, what: str) -> None:
        for pname in names:
            r = self.row(PARAMS, {"name": pname})
            if r is not None and r.get("value") == value:
                self.dangling.append(
                    {"cause_op": i, "table": PARAMS, "key": {"name": pname}, "column": "value",
                     "reason": f"names {what}"}
                )

    def mark_rules_naming_level(self, i: int, level: str, what: str) -> None:
        """A rule's ``urgency_level`` is a scalar, not an element of a list, so a rule that names
        *level* is marked dangling (as a level-naming parameter is), never deleted and never
        nulled: nulling it would quietly post the rule at the tier ``low``."""
        for e in self.rows(RULES).values():
            if e.get("urgency_level") == level:
                self.dangling.append(
                    {"cause_op": i, "table": RULES, "key": LAYER_REGISTRY[RULES].key_of(e),
                     "column": "urgency_level", "reason": f"names {what}"}
                )

    # -- node-keyed parameters ------------------------------------------------------------

    def param_json(self, name: str):
        r = self.row(PARAMS, {"name": name})
        if r is None or r.get("value_type") != "json":
            return None, None
        ok, v = parse_param_value(r["value"], "json")
        return (r, v) if ok else (None, None)

    def edit_param_json(self, i: int, name: str, edit: Callable[[Any], Any], reason: str | None) -> bool:
        r, v = self.param_json(name)
        if r is None:
            return False
        new = edit(json.loads(json.dumps(v)))
        if json.dumps(new) == json.dumps(v):
            return False
        self.e_update(i, PARAMS, {"name": name}, {"value": json.dumps(new)}, reason=reason)
        return True

    def params_referring(self, *kinds: str, doc: ConfigDocument | None = None) -> tuple[str, ...]:
        """The parameters whose ``refers_to`` column is one of *kinds*, in table order: the one
        declaration of which parameters hold node names, codelet type names or an urgency level."""
        rows = (self.doc if doc is None else doc).tables[PARAMS].values()
        return tuple(r["name"] for r in rows if r.get("refers_to") in kinds)

    def stale_pattern_entries(self, doc: ConfigDocument) -> set[tuple[str, str]]:
        """``(parameter, name)`` for each entry of a ``clampable_pattern_list`` parameter that no
        ``clampable_pattern_map`` parameter offers as a key.  Nothing is stale when the
        configuration declares no menu at all."""
        menus = self.params_referring("clampable_pattern_map", doc=doc)
        if not menus:
            return set()
        offered: set[str] = set()
        for p in menus:
            ok, value = parse_param_value(doc.tables[PARAMS][(p,)]["value"], "json")
            if ok and isinstance(value, dict):
                offered |= set(value)
        stale: set[tuple[str, str]] = set()
        for p in self.params_referring("clampable_pattern_list", doc=doc):
            ok, value = parse_param_value(doc.tables[PARAMS][(p,)]["value"], "json")
            if ok and isinstance(value, list):
                stale |= {(p, n) for n in value if n not in offered}
        return stale

    def mark_stale_patterns(self) -> None:
        """A batch that leaves a clampable pattern named in a ``clampable_pattern_list``
        parameter while the menu no longer offers it lists that parameter as dangling (a menu
        name is a key of the map, so no op renames it: the list is reported, never rewritten)."""
        cause = min(
            (i for (table, key), i in self.written.items()
             if table == PARAMS and key[0] in self.params_referring("clampable_pattern_map")),
            default=None,
        )
        if cause is None:
            return
        for p, name in sorted(self.stale_pattern_entries(self.doc) - self.stale_pattern_entries(self.cfg)):
            self.dangling.append(
                {"cause_op": cause, "table": PARAMS, "key": {"name": p}, "column": "value",
                 "reason": f"names clampable pattern {name!r}, which the menu no longer offers"}
            )

    def edit_node_params(self, i, fn_list, fn_map, reason: str, names_list=None,
                         names_map=None) -> None:
        if names_list is None:
            names_list = self.params_referring("node_list", "trigger_node_list")
        if names_map is None:
            names_map = self.params_referring("node_map")
        for p in names_list:
            self.edit_param_json(i, p, lambda v: fn_list(v) if isinstance(v, list) else v, reason.replace("{p}", p))
        for p in names_map:
            self.edit_param_json(i, p, lambda v: fn_map(v) if isinstance(v, dict) else v, reason.replace("{p}", p))

    def edit_triggers(self, i: int, fn: Callable[[list], list], reason: str) -> None:
        for r in list(self.rows(RULES).values()):
            lst = r.get("triggering_slipnodes")
            if isinstance(lst, list):
                new = fn(list(lst))
                if new != lst:
                    self.e_update(i, RULES, {"rule_key": r["rule_key"]}, {"triggering_slipnodes": new}, reason=reason)

    # -- the batch -----------------------------------------------------------------------------

    def execute(self) -> None:
        for i, op in enumerate(self.ops):
            if i in self.excluded:
                continue
            snap = self.snapshot()
            try:
                _HANDLERS.get(op["op"], _generic)(self, i, op)
            except _Fail as f:
                if not self.skip:
                    raise ChangeRefused([f.problem]) from None
                self.restore(snap)
                self.failed[i] = f.problem

    # -- reference check -----------------------------------------------------------------------------

    def exists(self, target: str, value: Any) -> bool:
        if target == "role.node":
            return value in ROLE_NAMES["node"]
        if target == "role.codelet_type":
            return value in ROLE_NAMES["codelet_type"]
        return (value,) in self.doc.tables[target]

    def reference_problems(self) -> list[InputProblem]:
        out: list[InputProblem] = []
        for (table, key), i in sorted(self.written.items(), key=lambda kv: kv[1]):
            row = self.doc.tables[table].get(key)
            if row is None:
                continue
            for column, (target, many) in ((c, r) for (t, c), r in REFERENCES.items() if t == table):
                value = row.get(column)
                if value is None or value == "":
                    continue
                for item in value if many else [value]:
                    if not self.exists(target, item):
                        out.append(InputProblem(
                            UNKNOWN_REFERENCE,
                            f"{table}.{column} names {item!r}, which {target} does not have",
                            i, column, table, list(key)))
        return out

    # -- the report ----------------------------------------------------------------------------------

    def run_start_gaps(self, doc: ConfigDocument) -> dict[tuple[str, str], str]:
        t = doc.tables
        gaps: dict[tuple[str, str], str] = {}
        for n in sorted(_READ_PARAMS):
            if (n,) not in t[PARAMS]:
                gaps[("engine_parameter", n)] = f"the engine reads engine parameter {n!r}; a run will stop at its start"
        for n in sorted(_READ_COEFFS):
            if (n,) not in t[COEFFS]:
                gaps[("formula_coefficient", n)] = f"the engine reads formula coefficient {n!r}; a run will stop at its start"
        bodies = ((r["name"], r.get("execute_body") or "") for r in t[CODELETS].values())
        for n, users in sorted(urgency_levels_read_by_bodies(bodies).items()):
            if (n,) not in t[LEVELS]:
                gaps[("urgency_level", n)] = (
                    f"codelet {', '.join(users)} reads urgency level {n!r}; a run will stop at its start")
        for p in self.params_referring("urgency_level", doc=doc):
            r = t[PARAMS].get((p,))
            if r is not None and (r["value"],) not in t[LEVELS]:
                gaps[("urgency_level", r["value"])] = (
                    f"engine parameter {p!r} names urgency level {r['value']!r}, which the configuration lacks; "
                    "a run will stop at its start")
        for rule in t[RULES].values():
            level = rule.get("urgency_level")
            if level is not None and (level,) not in t[LEVELS]:
                gaps[("urgency_level", level)] = (
                    f"posting rule {rule['rule_key']!r} names urgency level {level!r}, which the configuration lacks; "
                    "a run will stop at its start")
        r = t[PARAMS].get(("initial_codelet_types",))
        if r is not None:
            ok, names = parse_param_value(r["value"], "json")
            if ok and isinstance(names, list) and (
                not any((n,) in t[CODELETS] for n in names) or not t[RULES]
            ):
                gaps[("opening_coderack", "")] = (
                    "the opening Coderack cannot be filled (no initial codelet type exists, or no posting rule); "
                    "a run will stop at its start")
        return gaps

    def effects(self) -> list[dict]:
        before = self.run_start_gaps(self.cfg)
        after = self.run_start_gaps(self.doc)
        out = []
        for (kind, name), message in after.items():
            if before.get((kind, name)) != message:
                ops = sorted({a["op_index"] for a in self.applied
                              if name and (a["op"]["key"].get("name") == name or a["op"]["key"].get("rule_key") == name)})
                out.append({"kind": "run_start", "what": kind, "name": name, "message": message, "ops": ops})
        return out

    def advisories(self) -> list[dict]:
        out: list[dict] = list(self.advisories_extra)
        lengths = None
        r, v = self.param_json("intrinsic_link_lengths")
        if isinstance(v, dict):
            lengths = v
        for (table, key), i in sorted(self.written.items(), key=lambda kv: kv[1]):
            row = self.doc.tables[table].get(key)
            if row is None:
                continue

            def add(field, message):
                out.append({"op": i, "table": table, "key": LAYER_REGISTRY[table].key_of(row),
                            "field": field, "message": message})

            if table == NODES and isinstance(row.get("conceptual_depth"), (int, float)):
                if not 0 <= row["conceptual_depth"] <= 100:
                    add("conceptual_depth", f"depth {row['conceptual_depth']} is outside 0-100")
            if table == LINKS:
                ln = row.get("link_length")
                if isinstance(ln, (int, float)) and not 0 <= ln <= 100:
                    add("link_length", f"length {ln} is outside 0-100")
                label = row.get("label_node")
                if label and ln is None and lengths is not None and label not in lengths:
                    add("label_node", f"label {label!r} has no intrinsic link length")
            if table == PARAMS and row.get("name") in _RANGES:
                ok, val = parse_param_value(row["value"], row.get("value_type") or "string")
                lo, hi = _RANGES[row["name"]]
                if ok and isinstance(val, (int, float)) and not isinstance(val, bool):
                    if (lo is not None and val < lo) or (hi is not None and val > hi):
                        add("value", f"{row['name']} = {val} is outside its declared range {lo}-{hi}")
        return out


# ---------------------------------------------------------------------------------------------------
# Generic ops
# ---------------------------------------------------------------------------------------------------


def _generic(r: _Run, i: int, op: dict) -> None:
    kind = op["op"]
    table = op["table"]
    if kind == "insert":
        r.do_insert(i, table, op["row"])
    elif kind == "update":
        r.do_update(i, table, op["key"], op.get("fields", {}), expect=op.get("expect"), patch=op.get("patch"))
    else:
        r.do_delete(i, table, op["key"], expect=op.get("expect"), ok_if_missing=op.get("ok_if_missing", False))


# ---------------------------------------------------------------------------------------------------
# Removals with cascades (3.12.5)
# ---------------------------------------------------------------------------------------------------


def _remove_node(r: _Run, i: int, row: Mapping, *, splice=None, scan: bool = True) -> None:
    n = row["name"]
    why = f"removed node {n!r}"
    if scan:
        r.mark_dangling(i, _word(n), f"the removed node {n!r}", skip=(NODES, n))
        if row.get("glyph"):
            g = row["glyph"]
            for d in r.rows(DEMOS).values():
                if any(isinstance(d.get(c), str) and g in d[c] for c in ("initial", "modified", "target", "answer")):
                    r.affected.append({"cause_op": i, "table": DEMOS, "key": {"name": d["name"]},
                                       "reason": f"uses the glyph {g!r} of the removed node {n!r}"})
    if splice:
        _splice(r, i, n, splice)
    for lk in list(r.rows(LINKS).values()):
        role = ("from" if lk["from_node"] == n else "to" if lk["to_node"] == n
                else "label" if lk.get("label_node") == n else None)
        if role:
            r.e_delete(i, LINKS, LAYER_REGISTRY[LINKS].key_of(lk), reason=f"link has {why} as its {role}")
    for tname, col in ((NODE_ROLES, "node_name"), (THEME_RELS, "node_name")):
        for dep in list(r.rows(tname).values()):
            if dep.get(col) == n:
                r.e_delete(i, tname, LAYER_REGISTRY[tname].key_of(dep), reason=f"depends on {why}")
    for tname, col in ((LAYOUT, "node_name"), (THEME_DIMS, "slipnet_node")):
        dep = r.row(tname, {col: n})
        if dep is not None:
            r.e_delete(i, tname, {col: n}, reason=f"depends on {why}")
    r.edit_node_params(
        i, lambda v: [x for x in v if x != n], lambda v: {k: x for k, x in v.items() if k != n},
        f"entry of {why} in {{p}}")
    r.edit_triggers(i, lambda v: [x for x in v if x != n], f"trigger entry of {why}")
    r.e_delete(i, NODES, {"name": n})


def _splice(r: _Run, i: int, n: str, relations: list) -> None:
    for rel in relations:
        incoming = [l for l in r.rows(LINKS).values()
                    if l["to_node"] == n and l["from_node"] != n and rel in (l.get("label_node"), l["link_type"])]
        outgoing = [l for l in r.rows(LINKS).values()
                    if l["from_node"] == n and l["to_node"] != n and rel in (l.get("label_node"), l["link_type"])]
        for a in incoming:
            for b in outgoing:
                if a["from_node"] == b["to_node"]:
                    continue
                new = {"from_node": a["from_node"], "to_node": b["to_node"], "link_type": a["link_type"],
                       "label_node": a.get("label_node"), "link_length": a.get("link_length"),
                       "fixed_length": a.get("fixed_length")}
                if r.key_tuple_of(LINKS, new) in r.rows(LINKS):
                    continue
                r.do_insert(i, LINKS, new, reason=f"splice around removed node {n!r} via {rel!r}")


def _remove_codelet_type(r: _Run, i: int, row: Mapping) -> None:
    n = row["name"]
    why = f"removed codelet type {n!r}"
    r.mark_dangling(i, _quoted(n), f"the removed codelet type {n!r}", skip=(CODELETS, n))
    for rule in list(r.rows(RULES).values()):
        if rule["codelet_type"] == n:
            r.e_delete(i, RULES, {"rule_key": rule["rule_key"]}, reason=f"posting rule for {why}")
    for e in list(r.rows(PATTERNS).values()):
        if e["codelet_type"] == n:
            r.e_delete(i, PATTERNS, LAYER_REGISTRY[PATTERNS].key_of(e), reason=f"pattern entry for {why}")
    for e in list(r.rows(CODELET_ROLES).values()):
        if e["codelet_type"] == n:
            r.e_delete(i, CODELET_ROLES, LAYER_REGISTRY[CODELET_ROLES].key_of(e), reason=f"role binding of {why}")
    for p in r.params_referring("codelet_type_list"):
        r.edit_param_json(i, p, lambda v: [x for x in v if x != n] if isinstance(v, list) else v,
                          f"element of {why} in {p}")
    r.e_delete(i, CODELETS, {"name": n})


def _remove_level(r: _Run, i: int, row: Mapping) -> None:
    n = row["name"]
    why = f"removed urgency level {n!r}"
    r.mark_dangling(i, _quoted(n), f"the removed urgency level {n!r}", skip=None)
    r.mark_scalar_params(i, r.params_referring("urgency_level"), n, f"the removed urgency level {n!r}")
    r.mark_rules_naming_level(i, n, f"the removed urgency level {n!r}")
    for e in r.rows(CLAMP_TYPES).values():
        if e.get("codelet_background_level") == n:
            r.dangling.append({"cause_op": i, "table": CLAMP_TYPES, "key": LAYER_REGISTRY[CLAMP_TYPES].key_of(e),
                               "column": "codelet_background_level", "reason": f"names the removed urgency level {n!r}"})
    for e in list(r.rows(PATTERNS).values()):
        if e["urgency_level"] == n:
            r.e_delete(i, PATTERNS, LAYER_REGISTRY[PATTERNS].key_of(e), reason=f"pattern entry names {why}")
    r.e_delete(i, LEVELS, {"name": n})


_REMOVERS: dict[str, Callable] = {
    NODES: _remove_node,
    CODELETS: _remove_codelet_type,
    LEVELS: _remove_level,
}

# ---------------------------------------------------------------------------------------------------
# Renames: the key changes and the references to it are rewritten
# ---------------------------------------------------------------------------------------------------


def _rewrite_fk_dependents(r: _Run, i: int, table: str, column: str, old: str, new: str, why: str) -> list:
    """Role and relation rows reference their parent by a foreign key: they are deleted before
    the parent's key changes and inserted again after it (the journal layer refuses a re-key
    that would cascade), and reported as updates."""
    gone = [dict(d) for d in r.rows(table).values() if d.get(column) == old]
    for d in gone:
        r.e_delete(i, table, LAYER_REGISTRY[table].key_of(d))
    return [(table, column, d, why) for d in gone]


def _reinsert(r: _Run, i: int, gone: list, new: str) -> None:
    for table, column, d, why in gone:
        row = {**d, column: new}
        r.e_insert(i, table, row)
        r.cascaded.append({"cause_op": i, "table": table, "key": LAYER_REGISTRY[table].key_of(row),
                           "op": "update", "reason": why})


def _rename_node(r: _Run, i: int, key: Mapping, new: str) -> None:
    old = key["name"]
    if (new,) in r.rows(NODES):
        raise r.fail(KEY_EXISTS, f"{NODES} already has key {[new]}", i, "fields", NODES, [new])
    why = f"renamed node {old!r} to {new!r}"
    r.mark_dangling(i, _word(old), f"the old name {old!r} of a renamed node", skip=(NODES, old))
    gone = _rewrite_fk_dependents(r, i, NODE_ROLES, "node_name", old, new, f"references {why}")
    gone += _rewrite_fk_dependents(r, i, THEME_RELS, "node_name", old, new, f"references {why}")
    r.e_update(i, NODES, {"name": old}, {"name": new}, reason=None)
    r.cascaded.append({"cause_op": i, "table": NODES, "key": {"name": new}, "op": "update", "reason": why})
    _reinsert(r, i, gone, new)
    for lk in list(r.rows(LINKS).values()):
        changes = {c: new for c in ("from_node", "to_node", "label_node") if lk.get(c) == old}
        if changes:
            nk = r.key_tuple_of(LINKS, {**lk, **changes})
            if nk in r.rows(LINKS):
                raise r.fail(KEY_EXISTS, f"{LINKS} already has key {list(nk)}", i, "fields", LINKS, list(nk))
            r.e_update(i, LINKS, LAYER_REGISTRY[LINKS].key_of(lk), changes, reason=f"link references {why}")
    for tname, col in ((LAYOUT, "node_name"), (THEME_DIMS, "slipnet_node")):
        if r.row(tname, {col: old}) is not None:
            r.e_update(i, tname, {col: old}, {col: new}, reason=f"references {why}")
    r.edit_node_params(
        i, lambda v: [new if x == old else x for x in v],
        lambda v: {(new if k == old else k): x for k, x in v.items()}, f"entry in {{p}} for {why}")
    r.edit_triggers(i, lambda v: [new if x == old else x for x in v], f"trigger entry for {why}")


def _rename_codelet_type(r: _Run, i: int, key: Mapping, new: str) -> None:
    old = key["name"]
    if (new,) in r.rows(CODELETS):
        raise r.fail(KEY_EXISTS, f"{CODELETS} already has key {[new]}", i, "fields", CODELETS, [new])
    why = f"renamed codelet type {old!r} to {new!r}"
    r.mark_dangling(i, _quoted(old), f"the old name {old!r} of a renamed codelet type", skip=(CODELETS, old))
    gone = _rewrite_fk_dependents(r, i, CODELET_ROLES, "codelet_type", old, new, f"references {why}")
    r.e_update(i, CODELETS, {"name": old}, {"name": new})
    r.cascaded.append({"cause_op": i, "table": CODELETS, "key": {"name": new}, "op": "update", "reason": why})
    _reinsert(r, i, gone, new)
    for rule in list(r.rows(RULES).values()):
        if rule["codelet_type"] == old:
            r.e_update(i, RULES, {"rule_key": rule["rule_key"]}, {"codelet_type": new}, reason=f"posting rule references {why}")
    for e in list(r.rows(PATTERNS).values()):
        if e["codelet_type"] == old:
            nk = r.key_tuple_of(PATTERNS, {**e, "codelet_type": new})
            if nk in r.rows(PATTERNS):
                raise r.fail(KEY_EXISTS, f"{PATTERNS} already has key {list(nk)}", i, "fields", PATTERNS, list(nk))
            r.e_update(i, PATTERNS, LAYER_REGISTRY[PATTERNS].key_of(e), {"codelet_type": new}, reason=f"pattern entry references {why}")
    for p in r.params_referring("codelet_type_list"):
        r.edit_param_json(i, p, lambda v: [new if x == old else x for x in v] if isinstance(v, list) else v,
                          f"element in {p} for {why}")


def _rename_level(r: _Run, i: int, key: Mapping, new: str) -> None:
    old = key["name"]
    if (new,) in r.rows(LEVELS):
        raise r.fail(KEY_EXISTS, f"{LEVELS} already has key {[new]}", i, "fields", LEVELS, [new])
    why = f"renamed urgency level {old!r} to {new!r}"
    r.mark_dangling(i, _quoted(old), f"the old name {old!r} of a renamed urgency level")
    r.mark_scalar_params(i, r.params_referring("urgency_level"), old, f"the old name {old!r} of a renamed urgency level")
    r.e_update(i, LEVELS, {"name": old}, {"name": new})
    r.cascaded.append({"cause_op": i, "table": LEVELS, "key": {"name": new}, "op": "update", "reason": why})
    for e in list(r.rows(RULES).values()):
        if e.get("urgency_level") == old:
            r.e_update(i, RULES, LAYER_REGISTRY[RULES].key_of(e), {"urgency_level": new}, reason=f"posting rule references {why}")
    for e in list(r.rows(CLAMP_TYPES).values()):
        if e.get("codelet_background_level") == old:
            r.e_update(i, CLAMP_TYPES, LAYER_REGISTRY[CLAMP_TYPES].key_of(e), {"codelet_background_level": new},
                       reason=f"clamp type references {why}")
    for e in list(r.rows(PATTERNS).values()):
        if e["urgency_level"] == old:
            r.e_update(i, PATTERNS, LAYER_REGISTRY[PATTERNS].key_of(e), {"urgency_level": new}, reason=f"pattern entry references {why}")


# --- an enum row (or a theme relation) renamed -------------------------------------------------


#: Tables renamed by updating the row's name in place (the theme relations are keyed by name and
#: referenced only from the configuration document).
IN_PLACE_RENAMES = (THEME_RELS,)


def _rewritten_references(table: str) -> list[tuple[str, str, bool]]:
    """``(table, column, many)`` for every column that holds a name of a row of *table*: the
    declared references plus the rename-only ones (a theme dimension's valid relations)."""
    refs = {**REFERENCES, **ENUM_RENAME_EXTRA}
    return [(t, c, many) for (t, c), (target, many) in refs.items() if target == table]


def _json_mentions(value: Any, name: str) -> bool:
    """*name* spelled as a key or as a whole string anywhere in a JSON value."""
    if isinstance(value, str):
        return value == name
    if isinstance(value, list):
        return any(_json_mentions(v, name) for v in value)
    if isinstance(value, dict):
        return any(k == name or _json_mentions(v, name) for k, v in value.items())
    return False


def _rename_keys(value: Any, old: str, new: str, deep: bool, top: bool = True) -> Any:
    """*value* with every dict key *old* renamed *new*: the keys of this dict, and (``deep``) of
    every dict below it."""
    if isinstance(value, dict):
        return {(new if k == old else k): (_rename_keys(v, old, new, deep, False) if deep else v)
                for k, v in value.items()}
    if isinstance(value, list) and deep:
        return [_rename_keys(v, old, new, deep, False) for v in value]
    return value


def _rewrite_templates(r: _Run, i: int, table: str, old: str, new: str, why: str) -> None:
    """Rewrite the keys of the commentary sections that are keyed by this table's names
    (``TEMPLATE_KEYED_BY``).  The Standard Configuration holds every section in one row
    (``template_key`` ``all``); a row named for a section holds that section alone."""
    for section, pointer, deep in TEMPLATE_KEYED_BY.get(table, ()):
        for row in list(r.rows(TEMPLATES).values()):
            if row["template_key"] == "all":
                full = f"/{section}{pointer}"
            elif row["template_key"] == section:
                full = pointer
            else:
                continue
            data = row["template_data"]
            node = data
            try:
                for part in [p for p in full.split("/") if p]:
                    node = node[part]
            except (KeyError, TypeError, IndexError):
                continue
            renamed = _rename_keys(node, old, new, deep)
            if renamed == node:
                continue
            result = renamed if not full else apply_patch(
                json.loads(json.dumps(data)), [{"op": "replace", "path": full, "value": renamed}])
            r.e_update(i, TEMPLATES, {"template_key": row["template_key"]}, {"template_data": result},
                       reason=f"commentary section {section}{pointer} is keyed by {table} names: {why}")


def _mark_vocabulary_mentions(r: _Run, i: int, old: str, what: str) -> None:
    """List, and leave alone, every body, predicate, formula, parameter and template that still
    spells *old* (the code that spells it is not rewritten: only ``role(...)`` survives a rename)."""
    r.mark_dangling(i, _quoted(old), what)
    for p in r.rows(PARAMS).values():
        value = p.get("value")
        if p.get("value_type") == "json":
            ok, v = parse_param_value(value, "json")
            hit = ok and _json_mentions(v, old)
        else:
            hit = value == old
        if hit:
            r.dangling.append({"cause_op": i, "table": PARAMS, "key": {"name": p["name"]},
                               "column": "value", "reason": f"names {what}"})
    for t in r.rows(TEMPLATES).values():
        if _json_mentions(t.get("template_data"), old):
            r.dangling.append({"cause_op": i, "table": TEMPLATES, "key": {"template_key": t["template_key"]},
                               "column": "template_data", "reason": f"names {what}"})


def _rename_enum_value(r: _Run, i: int, table: str, old: str, new: str) -> None:
    """Rename a row of an enum table (or of ``theme_relations``) and every column that names it.

    The row's name is its key and other rows reference it by foreign key, so a rename is
    carried out as: insert the row under the new name (unbound, so the role stays unique),
    point every referencing column at it, delete the old row, and give the new row the role
    back.  Bodies, predicates, formulas, parameters and templates that spell the old name are
    listed as dangling and left alone, exactly as ``rename_node`` lists code; the commentary
    sections keyed by the table's names are rewritten.  Episodic Memory is not touched: a
    session's memory keeps the names it stored (see the module docstring).
    """
    spec = LAYER_REGISTRY[table]
    row = r.row(table, {"name": old})
    if row is None:
        raise r.missing(i, table, {"name": old}, "old")
    if old == new:
        return
    if (new,) in r.rows(table):
        raise r.fail(KEY_EXISTS, f"{table} already has key {[new]}", i, "new", table, [new])
    why = f"renamed {table} row {old!r} to {new!r}"
    what = f"the old name {old!r} of a renamed {table} row"
    # the keyed commentary sections are rewritten first, so what is listed afterwards is only
    # what still spells the old name
    _rewrite_templates(r, i, table, old, new, why)
    _mark_vocabulary_mentions(r, i, old, what)
    column = vocabulary.VOCABULARY_TABLES[table].column if table in vocabulary.VOCABULARY_TABLES else None
    held = row.get(column) if column else None
    if table in _TABLE_ADVISORIES:
        r.advisories_extra.append({"op": i, "table": table, "key": {"name": old}, "field": "name",
                                   "message": _TABLE_ADVISORIES[table]})
    if table in IN_PLACE_RENAMES:
        r.e_update(i, table, {"name": old}, {"name": new}, reason=None)
        r.cascaded.append({"cause_op": i, "table": table, "key": {"name": new}, "op": "update", "reason": why})
    else:
        r.e_insert(i, table, {**row, "name": new, **({column: None} if held else {})})
        r.cascaded.append({"cause_op": i, "table": table, "key": {"name": new}, "op": "update", "reason": why})
    for t, c, many in _rewritten_references(table):
        for dep in list(r.rows(t).values()):
            v = dep.get(c)
            if many:
                if not isinstance(v, list) or old not in v:
                    continue
                changed = [new if x == old else x for x in v]
            elif v == old:
                changed = new
            else:
                continue
            tspec = LAYER_REGISTRY[t]
            if c in tspec.key:
                nk = tspec.key_tuple(tspec.key_of({**dep, c: changed}))
                if nk in r.rows(t):
                    raise r.fail(KEY_EXISTS, f"{t} already has key {list(nk)}", i, "new", t, list(nk))
            r.e_update(i, t, tspec.key_of(dep), {c: changed}, reason=f"{t}.{c} references {why}")
    if table not in IN_PLACE_RENAMES:
        r.e_delete(i, table, {"name": old})
        if held:
            r.e_update(i, table, {"name": new}, {column: held})


#: Commentary template sections whose keys are the names of a vocabulary table's rows, so
#: renaming a row renames the key: ``table -> ((template_key, pointer, deep), ...)``.  ``pointer``
#: is the JSON pointer of the dict whose keys are names ("" is the section itself); ``deep``
#: renames the key at every depth below it.  A name spelled anywhere else is listed as dangling.
TEMPLATE_KEYED_BY: dict[str, tuple[tuple[str, str, bool], ...]] = {
    "event_types": (("answer_reporting", "", False),),
    "clamp_types": (("answer_reporting", "/clamp_activation", False),
                    ("answer_reporting", "/clamp_expiry", False)),
    "failure_kinds": (("snag_explanation", "", False),),
    "clause_types": (("rule_english", "", False),),
    "theme_relations": (("theme_phrase_templates", "", True),),
}

#: Tables whose names something outside the configuration compares; renaming one is allowed and
#: advised against.
_TABLE_ADVISORIES: dict[str, str] = {
    "run_statuses": "the client compares run status names; a rename breaks its display of a run",
    "param_value_types": "the engine and the editors parse a parameter's text by these names; "
                         "a rename makes the parameters of that type unreadable",
}


_RENAMERS: dict[str, Callable] = {
    NODES: _rename_node,
    CODELETS: _rename_codelet_type,
    LEVELS: _rename_level,
}

# ---------------------------------------------------------------------------------------------------
# Convenience ops (3.12.4)
# ---------------------------------------------------------------------------------------------------


def _link_row(raw: Mapping, default_from: str | None = None, default_to: str | None = None) -> dict:
    row = {_LINK_SHORT.get(k, k): v for k, v in raw.items()}
    if "from_node" not in row and default_from is not None and "to_node" in row:
        row["from_node"] = default_from
    if "to_node" not in row and default_to is not None and "from_node" in row:
        row["to_node"] = default_to
    return row


def _h_add_node(r: _Run, i: int, op: dict) -> None:
    name = op["name"]
    fields = dict(op.get("fields", {}))
    if "name" in fields and fields["name"] != name:
        raise r.fail(MALFORMED, "fields.name differs from name", i, "fields.name", NODES)
    r.do_insert(i, NODES, {**fields, "name": name})
    for raw in op.get("links", []):
        if not isinstance(raw, Mapping):
            raise r.fail(MALFORMED, "a link must be an object", i, "links")
        r.do_insert(i, LINKS, _link_row(raw, default_from=name, default_to=name))
    for raw in op.get("roles", []):
        role, ordinal = (raw, None) if isinstance(raw, str) else (raw.get("role"), raw.get("ordinal"))
        if not isinstance(role, str):
            raise r.fail(MALFORMED, "a role must be a name or {role, ordinal}", i, "roles")
        if ordinal is None:
            ordinal = _next_ordinal(r, NODE_ROLES, role) if role in ORDERED_ROLES else 0
        r.do_insert(i, NODE_ROLES, {"role": role, "ordinal": ordinal, "node_name": name})
    if "layout" in op:
        r.do_insert(i, LAYOUT, {**op["layout"], "node_name": name})
    if "theme_dimension" in op:
        r.do_insert(i, THEME_DIMS, {"valid_relations": [], **op["theme_dimension"], "slipnet_node": name})
    for pname, value in op.get("params", {}).items():
        _join_param(r, i, pname, name, value)


def _next_ordinal(r: _Run, table: str, role: str) -> int:
    existing = [e["ordinal"] for e in r.rows(table).values() if e["role"] == role]
    return (max(existing) + 1) if existing else 0


def _join_param(r: _Run, i: int, pname: str, node: str, value: Any) -> None:
    row, v = r.param_json(pname)
    if row is None:
        raise r.missing(i, PARAMS, {"name": pname}, "params")
    if isinstance(v, list):
        if value and node not in v:
            r.e_update(i, PARAMS, {"name": pname}, {"value": json.dumps(v + [node])})
    elif isinstance(v, dict):
        r.e_update(i, PARAMS, {"name": pname}, {"value": json.dumps({**v, node: value})})
    else:
        raise r.fail(MALFORMED, f"{pname} is neither a list nor a map", i, "params", PARAMS, [pname])


def _h_remove_node(r: _Run, i: int, op: dict) -> None:
    row = r.row(NODES, {"name": op["name"]})
    if row is None:
        raise r.missing(i, NODES, {"name": op["name"]}, "name")
    _remove_node(r, i, row, splice=op.get("splice"))


def _h_rename_node(r: _Run, i: int, op: dict) -> None:
    if r.row(NODES, {"name": op["old"]}) is None:
        raise r.missing(i, NODES, {"name": op["old"]}, "old")
    if op["old"] != op["new"]:
        r.do_update(i, NODES, {"name": op["old"]}, {"name": op["new"]})


def _h_rename_enum_value(r: _Run, i: int, op: dict) -> None:
    table = op["table"]
    if table not in RENAMEABLE_TABLES:
        raise r.fail(MALFORMED, f"{table!r} is not an enum table or a vocabulary table", i, "table")
    _rename_enum_value(r, i, table, op["old"], op["new"])


def _h_merge_nodes(r: _Run, i: int, op: dict) -> None:
    keep, drop = op["keep"], op["drop"]
    if keep == drop:
        raise r.fail(MALFORMED, "keep and drop are the same node", i, "drop", NODES)
    for field, n in (("keep", keep), ("drop", drop)):
        if r.row(NODES, {"name": n}) is None:
            raise r.missing(i, NODES, {"name": n}, field)
    why = f"merge of {drop!r} into {keep!r}"
    drop_row = r.row(NODES, {"name": drop})
    # links
    for lk in list(r.rows(LINKS).values()):
        touched = {c: keep for c in ("from_node", "to_node", "label_node") if lk.get(c) == drop}
        if not touched:
            continue
        new = {**lk, **touched}
        key = LAYER_REGISTRY[LINKS].key_of(lk)
        was_self = lk["from_node"] == lk["to_node"]
        if (new["from_node"] == new["to_node"] and not was_self):
            r.e_delete(i, LINKS, key, reason=f"link would become a self-link in the {why}")
        elif r.key_tuple_of(LINKS, new) in r.rows(LINKS):
            r.e_delete(i, LINKS, key, reason=f"{keep!r} already has the same link in the {why}")
        else:
            r.e_update(i, LINKS, key, touched, reason=f"link moved to {keep!r} in the {why}")
    # roles
    for e in list(r.rows(NODE_ROLES).values()):
        if e["node_name"] != drop:
            continue
        key = LAYER_REGISTRY[NODE_ROLES].key_of(e)
        held = [x for x in r.rows(NODE_ROLES).values() if x["role"] == e["role"] and x["node_name"] == keep]
        if held:
            r.e_delete(i, NODE_ROLES, key, reason=f"{keep!r} already holds role {e['role']!r} in the {why}")
        else:
            r.e_update(i, NODE_ROLES, key, {"node_name": keep}, reason=f"role {e['role']!r} moved to {keep!r} in the {why}")
    # one-row-per-node tables
    for tname, col in ((THEME_DIMS, "slipnet_node"), (LAYOUT, "node_name")):
        if r.row(tname, {col: drop}) is not None:
            if r.row(tname, {col: keep}) is None:
                r.e_update(i, tname, {col: drop}, {col: keep}, reason=f"moved to {keep!r} in the {why}")
            else:
                r.e_delete(i, tname, {col: drop}, reason=f"{keep!r} has one in the {why}")
    for e in list(r.rows(THEME_RELS).values()):
        if e.get("node_name") == drop:
            if any(x.get("node_name") == keep for x in r.rows(THEME_RELS).values()):
                r.e_delete(i, THEME_RELS, {"name": e["name"]}, reason=f"{keep!r} has a relation row in the {why}")
            else:
                r.e_update(i, THEME_RELS, {"name": e["name"]}, {"node_name": keep}, reason=f"moved to {keep!r} in the {why}")

    def move_list(v: list) -> list:
        out: list = []
        for x in v:
            x = keep if x == drop else x
            if x not in out:
                out.append(x)
        return out

    def move_map(v: dict) -> dict:
        out: dict = {}
        for k, x in v.items():
            if k == drop:
                if keep not in v and keep not in out:
                    out[keep] = x
            else:
                out[k] = x
        return out

    r.edit_node_params(i, move_list, move_map, f"entry in {{p}} in the {why}")
    r.edit_triggers(i, move_list, f"trigger entry in the {why}")
    _remove_node(r, i, r.row(NODES, {"name": drop}), scan=True)


def _h_add_link(r: _Run, i: int, op: dict) -> None:
    row = _link_row({k: v for k, v in op.items() if k != "op"})
    for need in ("from_node", "to_node", "link_type"):
        if need not in row:
            raise r.fail(MALFORMED, f"add_link needs {need!r}", i, need, LINKS)
    r.do_insert(i, LINKS, row)


def _h_remove_link(r: _Run, i: int, op: dict) -> None:
    r.do_delete(i, LINKS, op["key"])


def _param_table(kind: str) -> str:
    return COEFFS if "coefficient" in kind else PARAMS


def _param_equal(row: Mapping, expect: Any) -> bool:
    vt = row.get("value_type") or "string"
    ok, cur = parse_param_value(row["value"], vt)
    if isinstance(expect, str) and vt not in ("string", "json"):
        ok2, expect = parse_param_value(expect, vt)
        if not ok2:
            return False
    return ok and cur == expect and isinstance(cur, bool) == isinstance(expect, bool)


def _h_set_param(r: _Run, i: int, op: dict) -> None:
    table = _param_table(op["op"])
    row = r.row(table, {"name": op["name"]})
    if row is None:
        raise r.missing(i, table, {"name": op["name"]}, "name")
    if "expect" in op and not _param_equal(row, op["expect"]):
        raise r.fail(STALE, f"{table} {op['name']!r} differs from expect", i, "expect", table, [op["name"]])
    vt = op.get("value_type") or row.get("value_type") or "string"
    fields = {"value": checks.format_param(op["to"], vt)}
    if vt != row.get("value_type"):
        fields["value_type"] = vt
    r.do_update(i, table, {"name": op["name"]}, fields)


def _h_set_level(r: _Run, i: int, op: dict) -> None:
    row = r.row(LEVELS, {"name": op["name"]})
    if row is None:
        raise r.missing(i, LEVELS, {"name": op["name"]}, "name")
    if "expect" in op and not _same(row["value"], op["expect"]):
        raise r.fail(STALE, f"{LEVELS} {op['name']!r} differs from expect", i, "expect", LEVELS, [op["name"]])
    r.do_update(i, LEVELS, {"name": op["name"]}, {"value": op["to"]})


def _adjusted_text(r: _Run, i: int, table: str, row: Mapping, by: Any) -> str:
    vt = row.get("value_type") or "string"
    ok, cur = parse_param_value(row["value"], vt)
    where = (i, "value", table, [row["name"]])
    if not ok or vt not in ("int", "float", "rational"):
        raise r.fail(MALFORMED, f"{row['name']!r} is {vt}, not a number", *where)
    if vt == "rational":
        total = Fraction(cur) + Fraction(by).limit_denominator(10**12) if isinstance(by, float) else Fraction(cur) + by
        return checks.fraction_text(total)
    total = cur + by
    if vt == "int":
        if total != int(total):
            raise r.fail(MALFORMED, f"{row['name']!r} is an integer; {total} is not", *where)
        return str(int(total))
    return str(float(total))


def _h_adjust_param(r: _Run, i: int, op: dict) -> None:
    table = _param_table(op["op"])
    row = r.row(table, {"name": op["name"]})
    if row is None:
        raise r.missing(i, table, {"name": op["name"]}, "name")
    r.do_update(i, table, {"name": op["name"]}, {"value": _adjusted_text(r, i, table, row, op["by"])})


def _h_adjust(r: _Run, i: int, op: dict) -> None:
    table, field = op["table"], op["field"]
    if table not in REGISTRY:
        raise r.fail(MALFORMED, f"unknown table {table!r}", i, "table")
    spec = INPUT_TABLES[table]
    col = spec.columns.get(field)
    row = r.row(table, op["key"])
    if row is None:
        raise r.missing(i, table, dict(op["key"]))
    if col is None:
        raise r.fail(MALFORMED, f"unknown field {field!r}", i, "field", table)
    if table in PARAM_TABLES and field == "value":
        return r.do_update(i, table, op["key"], {"value": _adjusted_text(r, i, table, row, op["by"])})
    cur = row.get(field)
    if col.type not in ("int", "float") or not isinstance(cur, (int, float)) or isinstance(cur, bool):
        raise r.fail(MALFORMED, f"{table}.{field} is not a number", i, "field", table)
    total = cur + op["by"]
    if col.type == "int":
        if total != int(total):
            raise r.fail(MALFORMED, f"{table}.{field} is an integer; {total} is not", i, "field", table)
        total = int(total)
    r.do_update(i, table, op["key"], {field: total})


def _list_of(r: _Run, i: int, table: str, row: Mapping, field: str) -> list:
    if table in PARAM_TABLES and field == "value":
        ok, v = parse_param_value(row["value"], row.get("value_type") or "string") if row.get("value_type") == "json" else (False, None)
        if not ok or not isinstance(v, list):
            raise r.fail(MALFORMED, f"{table} {row['name']!r} is not a JSON list", i, "field", table)
        return v
    v = row.get(field)
    if v is None and field in LAYER_REGISTRY[table].json_columns:
        return []
    if not isinstance(v, list):
        raise r.fail(MALFORMED, f"{table}.{field} is not a list", i, "field", table)
    return v


def _h_list_edit(r: _Run, i: int, op: dict) -> None:
    table, field, value = op["table"], op["field"], op["value"]
    if table not in REGISTRY:
        raise r.fail(MALFORMED, f"unknown table {table!r}", i, "table")
    row = r.row(table, op["key"])
    if row is None:
        raise r.missing(i, table, dict(op["key"]))
    if field not in INPUT_TABLES[table].columns:
        raise r.fail(MALFORMED, f"unknown field {field!r}", i, "field", table)
    cur = list(_list_of(r, i, table, row, field))
    new = (cur + [value] if value not in cur else cur) if op["op"] == "list_add" else [x for x in cur if x != value]
    if new == cur:
        return
    r.do_update(i, table, op["key"], {field: json.dumps(new) if table in PARAM_TABLES else new})


def _h_reorder(r: _Run, i: int, op: dict) -> None:
    table = op["table"]
    spec = REGISTRY.get(table)
    if spec is None or len(spec.order) != 1 or spec.order[0] == "role":
        raise r.fail(MALFORMED, f"{table} has no single order column to reorder", i, "table")
    col = spec.order[0]
    if spec.key == ("role", "ordinal"):
        raise r.fail(MALFORMED, f"{table} is ordered by its key", i, "table")
    moving = spec.key_tuple(op["key"])
    if moving not in r.rows(table):
        raise r.missing(i, table, dict(op["key"]))
    order = list(r.rows(table))
    order.remove(moving)
    if op.get("before") is not None:
        target = spec.key_tuple(op["before"])
        if target not in r.rows(table) or target == moving:
            raise r.missing(i, table, dict(op["before"]), "before")
        order.insert(order.index(target), moving)
    else:
        order.append(moving)
    for position, key in enumerate(order):
        row = r.rows(table)[key]
        if row[col] != position:
            r.e_update(i, table, spec.key_of(row), {col: position})


def _h_move_layout(r: _Run, i: int, op: dict) -> None:
    r.do_update(i, LAYOUT, {"node_name": op["node"]}, {"grid_col": op["x"], "grid_row": op["y"]})


def _top_down_edit(r: _Run, i: int, node: str, add: bool, rule_key: str) -> None:
    """A rule-trigger edit also changes the parameter that lists the trigger nodes.

    The parameter is the one whose ``engine_params.refers_to`` is ``trigger_node_list`` (the
    Metacat Standard Configuration declares ``top_down_slipnodes``); a configuration that
    declares none is left alone.  A node added as a trigger is added to the list; one removed
    from a rule is removed from it only when no rule still triggers it.
    """
    for name in r.params_referring("trigger_node_list"):
        row, v = r.param_json(name)
        if row is None or not isinstance(v, list):
            continue
        if add and node not in v:
            r.e_update(i, PARAMS, {"name": name}, {"value": json.dumps(v + [node])})
        elif not add and node in v:
            still = any(node in (x.get("triggering_slipnodes") or []) for x in r.rows(RULES).values())
            if not still:
                r.e_update(i, PARAMS, {"name": name}, {"value": json.dumps([x for x in v if x != node])})


def _h_trigger(r: _Run, i: int, op: dict) -> None:
    rule = r.row(RULES, {"rule_key": op["rule_key"]})
    if rule is None:
        raise r.missing(i, RULES, {"rule_key": op["rule_key"]}, "rule_key")
    cur = list(rule.get("triggering_slipnodes") or [])
    add = op["op"] == "add_trigger"
    new = (cur + [op["node"]] if op["node"] not in cur else cur) if add else [x for x in cur if x != op["node"]]
    r.do_update(i, RULES, {"rule_key": op["rule_key"]}, {"triggering_slipnodes": new})
    _top_down_edit(r, i, op["node"], add, op["rule_key"])


def _role_kind(r: _Run, i: int, role: str) -> tuple[str, str, str]:
    for kind, table, col in (("node", NODE_ROLES, "node_name"), ("codelet_type", CODELET_ROLES, "codelet_type")):
        if role in ROLE_NAMES[kind]:
            return kind, table, col
    raise r.fail(UNKNOWN_REFERENCE, f"role {role!r} is not in the engine's vocabulary", i, "role")


def _h_rebind(r: _Run, i: int, op: dict) -> None:
    kind, table, col = _role_kind(r, i, op["role"])
    target = op.get("node") if kind == "node" else op.get("codelet_type")
    if target is None:
        target = op.get("node") or op.get("codelet_type")
    if target is None:
        raise r.fail(MALFORMED, "rebind_role needs the node (or codelet_type) to bind", i, "node")
    ordinal = op.get("ordinal")
    if ordinal is None:
        ordinal = _next_ordinal(r, table, op["role"]) if op["role"] in ORDERED_ROLES else 0
    key = {"role": op["role"], "ordinal": ordinal}
    if r.row(table, key) is None:
        r.do_insert(i, table, {**key, col: target})
    else:
        r.do_update(i, table, key, {col: target})


def _h_unbind(r: _Run, i: int, op: dict) -> None:
    kind, table, col = _role_kind(r, i, op["role"])
    ordinal = op.get("ordinal")
    if ordinal is None and op["role"] in ORDERED_ROLES:
        rows = [e for e in r.rows(table).values() if e["role"] == op["role"]]
        if not rows and not op.get("ok_if_missing"):
            raise r.missing(i, table, {"role": op["role"], "ordinal": 0})
        for e in rows:
            r.do_delete(i, table, LAYER_REGISTRY[table].key_of(e))
        return
    r.do_delete(i, table, {"role": op["role"], "ordinal": ordinal or 0}, ok_if_missing=op.get("ok_if_missing", False))


def _h_add_with_fields(table: str, key_col: str, arg: str) -> Callable:
    def handler(r: _Run, i: int, op: dict) -> None:
        fields = dict(op.get("fields", {}))
        if arg in op:
            if key_col in fields and fields[key_col] != op[arg]:
                raise r.fail(MALFORMED, f"fields.{key_col} differs from {arg}", i, f"fields.{key_col}", table)
            fields[key_col] = op[arg]
        r.do_insert(i, table, fields)
    return handler


def _h_remove(table: str, key_col: str, arg: str) -> Callable:
    def handler(r: _Run, i: int, op: dict) -> None:
        r.do_delete(i, table, {key_col: op[arg]})
    return handler


def _h_set_column(table: str, key_col: str, arg: str, column: str | None, value_arg: str) -> Callable:
    def handler(r: _Run, i: int, op: dict) -> None:
        col = column or op.get("column")
        if table == RULES and col not in _RULE_CODE_COLUMNS:
            raise r.fail(MALFORMED, f"column must be one of {list(_RULE_CODE_COLUMNS)}", i, "column", table)
        r.do_update(i, table, {key_col: op[arg]}, {col: op[value_arg]})
    return handler


def _h_set_template(r: _Run, i: int, op: dict) -> None:
    row = r.row(TEMPLATES, {"template_key": op["key"]})
    if row is None:
        raise r.missing(i, TEMPLATES, {"template_key": op["key"]}, "key")
    try:
        parse_pointer(op["path"])
        apply_patch(row["template_data"], [{"op": "replace", "path": op["path"], "value": op["text"]}])
        kind = "replace"
    except PatchError as exc:
        if exc.kind == "malformed":
            raise r.fail(MALFORMED, str(exc), i, "path", TEMPLATES)
        kind = "add"
    r.do_update(i, TEMPLATES, {"template_key": op["key"]}, {},
                patch={"template_data": [{"op": kind, "path": op["path"], "value": op["text"]}]})


_HANDLERS: dict[str, Callable] = {
    "add_node": _h_add_node,
    "remove_node": _h_remove_node,
    "rename_node": _h_rename_node,
    "rename_enum_value": _h_rename_enum_value,
    "merge_nodes": _h_merge_nodes,
    "add_link": _h_add_link,
    "remove_link": _h_remove_link,
    "set_param": _h_set_param,
    "set_coefficient": _h_set_param,
    "adjust_param": _h_adjust_param,
    "adjust_coefficient": _h_adjust_param,
    "set_urgency_level": _h_set_level,
    "adjust": _h_adjust,
    "list_add": _h_list_edit,
    "list_remove": _h_list_edit,
    "reorder": _h_reorder,
    "move_layout": _h_move_layout,
    "add_trigger": _h_trigger,
    "remove_trigger": _h_trigger,
    "rebind_role": _h_rebind,
    "unbind_role": _h_unbind,
    "add_codelet_type": _h_add_with_fields(CODELETS, "name", "name"),
    "remove_codelet_type": _h_remove(CODELETS, "name", "name"),
    "set_codelet_body": _h_set_column(CODELETS, "name", "name", "execute_body", "source"),
    "set_predicate": _h_set_column(NODES, "name", "node", "descriptor_predicate", "expr"),
    "set_formula": _h_set_column(RULES, "rule_key", "rule_key", None, "expr"),
    "set_template": _h_set_template,
    "add_posting_rule": _h_add_with_fields(RULES, "rule_key", "rule_key"),
    "remove_posting_rule": _h_remove(RULES, "rule_key", "rule_key"),
    "add_demo_problem": _h_add_with_fields(DEMOS, "name", "name"),
}


# ---------------------------------------------------------------------------------------------------
# The entry point
# ---------------------------------------------------------------------------------------------------


def resolve(cfg: ConfigDocument, batch: Any) -> tuple[list[dict], dict]:
    """Resolve *batch* against *cfg*: ``(resolved_ops, report)``.

    *resolved_ops* are plain generic ``insert`` / ``update`` / ``delete`` dicts with absolute
    values, in application order (``apply_resolved(cfg, resolved_ops)`` is the new document).
    Raises :class:`ChangeRefused` when the batch cannot be applied (``abort``, the default,
    refuses on the first op that cannot be applied; a malformed batch is refused under both).

    The report's lists:

    * ``applied``: one entry per resolved op, ``{op_index, op, before, after}`` with the row
      images (``before`` is ``None`` for an insert, ``after`` for a delete);
    * ``skipped``: ``{op, reason}`` for each batch op left unapplied (``on_op_failure: skip``);
      ``reason`` is the refusal as ``InputProblem.as_dict()``;
    * ``cascaded``: ``{cause_op, table, key, op, reason}`` for each row a removal, rename or merge
      deleted, rewrote or moved;
    * ``dangling``: ``{cause_op, table, key, column, reason}``, code or scalar parameters that
      name a removed or renamed thing; left alone;
    * ``affected``: ``{cause_op, table, key, reason}``, e.g. demo problems that use a removed
      node's glyph;
    * ``effects``: run-start consequences on the engine's declared read list;
    * ``advisories``: ``{op, table, key, field, message}``, never a refusal.
    """
    checks.check_shape(batch)
    skip = batch.get("on_op_failure", "abort") == "skip"
    excluded: dict[int, InputProblem] = {}
    while True:
        run = _Run(cfg, batch["ops"], skip, excluded)
        run.execute()
        bad = run.reference_problems()
        if not bad:
            break
        if not skip:
            raise ChangeRefused(bad)
        for p in bad:
            excluded.setdefault(p.op_index, p)
    run.mark_stale_patterns()
    skipped = {**run.failed, **{i: p for i, p in excluded.items()}}
    report = {
        "ok": True,
        "applied": run.applied,
        "skipped": [{"op": i, "reason": p.as_dict()} for i, p in sorted(skipped.items())],
        "cascaded": run.cascaded,
        "dangling": run.dangling,
        "affected": run.affected,
        "effects": run.effects(),
        "advisories": run.advisories(),
    }
    return run.resolved, report
