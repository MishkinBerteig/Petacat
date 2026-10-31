"""Input validation for configuration change batches: the four classes of 3.4(a).

Pure library functions, no database, no engine imports, no side effects.  The change API
(work package C14, with the ``ConfigurationWriter`` funnel of C5) will call them; nothing is
wired to a route here.  The plan is ``agents-workspace/config-source/CONFIG-SOURCE-PLAN.md``,
sections 3.4(a), 3.12.0 and 3.12.6.

The API refuses a change **only when it cannot apply it**, never because of *what* the change
does.  That is four classes, and each is one function here:

=====================  ======  ============================================================
class                  status  function
=====================  ======  ============================================================
malformed              400     :func:`check_malformed`
unknown reference      422     :func:`check_references` (and missing keys, in
                               :func:`apply_ops_to_copy`)
does not compile       422     :func:`check_code`, :func:`check_code_in_ops`
stale or conflicting   409     :func:`check_base_version`, and ``expect`` / ``key_exists``
                               in :func:`apply_ops_to_copy`
=====================  ======  ============================================================

What is deliberately **not** checked (3.4(a)): that roles are bound; that relation rows
exist; that letters form a chain; that a depth or length is in 0-100; that a
``post_codelet("x")`` literal names a known type; that a node may be removed.  There is no
function for any of those, and a test pins that a removal of anything is accepted.

:func:`validate_batch` runs the four in the plan's order on a *working copy*: ops are applied
in order (so an ``update`` sees what an earlier op inserted), then references are checked once
on the resulting state, so a node and its links may be inserted in either order.

The cascade (3.12.5) is not performed here.  A caller that cascades (C14's ``resolve``) hands
this module the batch it resolved, with the cascade's deletions already in ``ops``; a
reference the cascade removed is then not in the resulting state and is not dangling.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

# --- the four classes -------------------------------------------------------

MALFORMED = "malformed"
UNKNOWN_REFERENCE = "unknown_reference"
DOES_NOT_COMPILE = "does_not_compile"
STALE = "stale"
KEY_EXISTS = "key_exists"

#: HTTP status per class.
STATUS = {
    MALFORMED: 400,
    UNKNOWN_REFERENCE: 422,
    DOES_NOT_COMPILE: 422,
    STALE: 409,
    KEY_EXISTS: 409,
}

OPS = ("insert", "update", "delete")
BASE_MODES = ("strict", "rebase")
ON_OP_FAILURE = ("abort", "skip")
SOURCES = (
    "admin", "external", "learner", "standard_load", "reset", "restore", "import", "creation",
)
ENVELOPE_FIELDS = frozenset(
    {
        "configuration_id", "base_version", "base_mode", "source", "actor", "note", "ops",
        "on_op_failure", "dry_run",
    }
)

#: Column types a :class:`ColumnSpec` can declare.  ``code_exec`` and ``code_eval`` are
#: Python source (a codelet body; a predicate, formula or condition) and are compiled by
#: :func:`check_code`.
COLUMN_TYPES = ("str", "int", "float", "bool", "json", "code_exec", "code_eval")

#: Parameter ``value_type`` names (``param_value_types``) and how their text parses.
VALUE_TYPES = ("int", "float", "bool", "json", "string")


@dataclass(frozen=True)
class InputProblem:
    """One refusal: the class, where in the batch, and what.

    ``op_index`` is ``None`` for the batch envelope.  ``line`` and ``column`` are 1-based and
    set only for :data:`DOES_NOT_COMPILE`.
    """

    kind: str
    message: str
    op_index: int | None = None
    field: str | None = None
    table: str | None = None
    key: Any = None
    language: str | None = None
    line: int | None = None
    column: int | None = None

    @property
    def status(self) -> int:
        return STATUS[self.kind]

    def as_dict(self) -> dict[str, Any]:
        out = {"error": self.kind, "status": self.status, "message": self.message}
        for name in ("op_index", "field", "table", "key", "language", "line", "column"):
            value = getattr(self, name)
            if value is not None:
                out[name] = value
        return out


@dataclass(frozen=True)
class Reference:
    """A column's value names something else.

    *target* is a table name (the referenced value is that table's single key column) or the
    name of a vocabulary in the ``vocabularies`` argument (role names, link kinds, posting
    directions: names the engine declares).  ``many`` says the column holds a JSON list of
    names rather than one.
    """

    target: str
    many: bool = False


@dataclass(frozen=True)
class ColumnSpec:
    type: str = "str"
    nullable: bool = False
    #: A row may omit a nullable or defaulted column; a required column must be present
    #: on ``insert``.
    required: bool = True
    reference: Reference | None = None
    #: With ``type == "json"``: the column holds engine-parameter text and the row's
    #: ``value_type`` column names how that text parses.  See :func:`check_param_value`.
    value_type_column: str | None = None


@dataclass(frozen=True)
class TableSpec:
    name: str
    key: tuple[str, ...]
    columns: Mapping[str, ColumnSpec]

    def key_of(self, row: Mapping[str, Any]) -> tuple:
        return tuple(row.get(k) for k in self.key)


#: ``{table: {key tuple: row}}``: a configuration's rows, as plain data.
State = dict[str, dict[tuple, dict[str, Any]]]


# ---------------------------------------------------------------------------
# 400 malformed
# ---------------------------------------------------------------------------


def _is_type(value: Any, column_type: str) -> bool:
    if column_type == "str" or column_type in ("code_exec", "code_eval"):
        return isinstance(value, str)
    if column_type == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if column_type == "float":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if column_type == "bool":
        return isinstance(value, bool)
    if column_type == "json":
        try:
            json.dumps(value)
        except (TypeError, ValueError):
            return False
        return True
    return False


def parse_param_value(text: str, value_type: str) -> tuple[bool, Any]:
    """Parse engine-parameter text as its ``value_type``; ``(ok, parsed)``.

    ``int`` and ``float`` must parse as written; ``bool`` is ``true`` or ``false`` (any case);
    ``json`` must be valid JSON; ``string`` is any text.
    """
    try:
        if value_type == "int":
            return True, int(text)
        if value_type == "float":
            return True, float(text)
        if value_type == "bool":
            lowered = text.strip().lower()
            if lowered in ("true", "false"):
                return True, lowered == "true"
            return False, None
        if value_type == "json":
            return True, json.loads(text)
        if value_type == "string":
            return True, text
    except (ValueError, TypeError):
        return False, None
    return False, None


def check_param_value(
    text: Any, value_type: Any, *, op_index: int | None = None, table: str | None = None
) -> InputProblem | None:
    """A ``value_type`` the value does not parse as is malformed (400)."""
    if value_type not in VALUE_TYPES:
        return InputProblem(
            MALFORMED, f"unknown value_type {value_type!r}", op_index, "value_type", table
        )
    if not isinstance(text, str):
        return InputProblem(MALFORMED, "value must be text", op_index, "value", table)
    ok, _ = parse_param_value(text, value_type)
    if not ok:
        return InputProblem(
            MALFORMED, f"value {text!r} does not parse as {value_type}", op_index, "value", table
        )
    return None


def _check_fields(
    fields: Any,
    spec: TableSpec,
    op_index: int,
    where: str,
    *,
    require_all: bool,
    allow_key_columns: bool = True,
) -> list[InputProblem]:
    out: list[InputProblem] = []
    if not isinstance(fields, Mapping):
        return [InputProblem(MALFORMED, f"{where} must be an object", op_index, where, spec.name)]
    for name in fields:
        if name not in spec.columns:
            out.append(
                InputProblem(MALFORMED, f"unknown field {name!r}", op_index, f"{where}.{name}", spec.name)
            )
    if require_all:
        for name, column in spec.columns.items():
            if column.required and not column.nullable and name not in fields:
                out.append(
                    InputProblem(MALFORMED, f"missing field {name!r}", op_index, f"{where}.{name}", spec.name)
                )
    for name, value in fields.items():
        column = spec.columns.get(name)
        if column is None:
            continue
        if value is None:
            if not column.nullable:
                out.append(
                    InputProblem(MALFORMED, f"field {name!r} may not be null", op_index, f"{where}.{name}", spec.name)
                )
            continue
        if not _is_type(value, column.type):
            out.append(
                InputProblem(
                    MALFORMED,
                    f"field {name!r} must be {column.type}, not {type(value).__name__}",
                    op_index, f"{where}.{name}", spec.name,
                )
            )
            continue
        if column.reference is not None and column.reference.many:
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                out.append(
                    InputProblem(MALFORMED, f"field {name!r} must be a list of names", op_index, f"{where}.{name}", spec.name)
                )
    for name, column in spec.columns.items():
        vt = column.value_type_column
        if vt is not None and name in fields and vt in fields and fields[name] is not None:
            problem = check_param_value(fields[name], fields[vt], op_index=op_index, table=spec.name)
            if problem is not None:
                out.append(problem)
    return out


def check_malformed(batch: Any, tables: Mapping[str, TableSpec]) -> list[InputProblem]:
    """The 400 class: the batch, or one op, is not in the shape the API takes.

    ``tables`` is the **target configuration's table set**: an op naming a table outside it is
    malformed, as is an unknown op, a missing or extra field, a wrong type, JSON that does not
    parse as its column, and a ``value_type`` the value does not parse as.  An error in the
    envelope (not an object, no ``ops``) is returned alone: the ops cannot be read.
    """
    if not isinstance(batch, Mapping):
        return [InputProblem(MALFORMED, "the batch must be an object")]
    out: list[InputProblem] = []
    for name in batch:
        if name not in ENVELOPE_FIELDS:
            out.append(InputProblem(MALFORMED, f"unknown batch field {name!r}", None, name))
    if "base_mode" in batch and batch["base_mode"] not in BASE_MODES:
        out.append(InputProblem(MALFORMED, f"base_mode must be one of {BASE_MODES}", None, "base_mode"))
    if "on_op_failure" in batch and batch["on_op_failure"] not in ON_OP_FAILURE:
        out.append(InputProblem(MALFORMED, f"on_op_failure must be one of {ON_OP_FAILURE}", None, "on_op_failure"))
    if "source" in batch and batch["source"] not in SOURCES:
        out.append(InputProblem(MALFORMED, f"source must be one of {SOURCES}", None, "source"))
    if "dry_run" in batch and not isinstance(batch["dry_run"], bool):
        out.append(InputProblem(MALFORMED, "dry_run must be true or false", None, "dry_run"))
    ops = batch.get("ops")
    if not isinstance(ops, list):
        out.append(InputProblem(MALFORMED, "ops must be a list", None, "ops"))
        return out
    for i, op in enumerate(ops):
        out.extend(_check_op_shape(i, op, tables))
    return out


def _check_op_shape(i: int, op: Any, tables: Mapping[str, TableSpec]) -> list[InputProblem]:
    if not isinstance(op, Mapping):
        return [InputProblem(MALFORMED, "an op must be an object", i, "op")]
    kind = op.get("op")
    if kind not in OPS:
        return [InputProblem(MALFORMED, f"unknown op {kind!r}", i, "op")]
    table = op.get("table")
    if not isinstance(table, str) or table not in tables:
        return [InputProblem(MALFORMED, f"unknown table {table!r}", i, "table")]
    spec = tables[table]
    allowed = {
        "insert": {"op", "table", "row"},
        "update": {"op", "table", "key", "fields", "expect"},
        "delete": {"op", "table", "key", "expect", "ok_if_missing"},
    }[kind]
    out = [
        InputProblem(MALFORMED, f"unknown op field {name!r}", i, name, table)
        for name in op
        if name not in allowed
    ]
    if kind == "insert":
        if "row" not in op:
            return out + [InputProblem(MALFORMED, "insert needs a row", i, "row", table)]
        return out + _check_fields(op["row"], spec, i, "row", require_all=True)
    # update and delete are addressed by natural key.
    key = op.get("key")
    if not isinstance(key, Mapping) or set(key) != set(spec.key):
        out.append(InputProblem(MALFORMED, f"key must give exactly {list(spec.key)}", i, "key", table))
    else:
        out.extend(_check_fields(key, spec, i, "key", require_all=False))
    if kind == "update":
        if "fields" not in op:
            out.append(InputProblem(MALFORMED, "update needs fields", i, "fields", table))
        else:
            out.extend(_check_fields(op["fields"], spec, i, "fields", require_all=False))
    if "expect" in op:
        out.extend(_check_fields(op["expect"], spec, i, "expect", require_all=False))
    if "ok_if_missing" in op and not isinstance(op["ok_if_missing"], bool):
        out.append(InputProblem(MALFORMED, "ok_if_missing must be true or false", i, "ok_if_missing", table))
    return out


# ---------------------------------------------------------------------------
# 422 does_not_compile
# ---------------------------------------------------------------------------

#: Which Python compile mode each language takes, exactly as the engine compiles it:
#: a codelet body is a module (``interpreter.compile``, mode ``exec``); a descriptor
#: predicate, posting formula, count formula, condition and ``initial_codelet_rounds`` are
#: single expressions (mode ``eval``).
LANGUAGE_MODE = {"codelet_body": "exec", "expression": "eval"}


def check_code(
    language: str,
    source: Any,
    *,
    name: str = "<source>",
    op_index: int | None = None,
    field: str | None = None,
    table: str | None = None,
) -> InputProblem | None:
    """Compile *source* without running it; ``None`` if it compiles.

    ``language`` is ``"codelet_body"`` or ``"expression"``.  Empty or blank source compiles
    (an empty body is the defined no-op, and an empty formula is read as absent).  The result
    carries the 1-based line and column of the first syntax error.
    """
    mode = LANGUAGE_MODE[language]
    if not isinstance(source, str):
        return InputProblem(MALFORMED, "code must be text", op_index, field, table, language=language)
    if not source.strip():
        return None
    try:
        compile(source, name, mode)
    except SyntaxError as exc:
        return InputProblem(
            DOES_NOT_COMPILE,
            f"{exc.msg}",
            op_index,
            field,
            table,
            language=language,
            line=exc.lineno or 1,
            column=exc.offset or 1,
        )
    except (ValueError, OverflowError, RecursionError, MemoryError) as exc:  # null bytes, absurd nesting
        return InputProblem(
            DOES_NOT_COMPILE, f"{type(exc).__name__}: {exc}", op_index, field, table,
            language=language, line=1, column=1,
        )
    return None


def check_code_in_ops(
    ops: Sequence[Mapping[str, Any]], tables: Mapping[str, TableSpec]
) -> list[InputProblem]:
    """Compile every code column an ``insert`` or ``update`` writes (assumes well-formed ops)."""
    out: list[InputProblem] = []
    for i, op in enumerate(ops):
        if op.get("op") == "insert":
            written = op.get("row", {})
        elif op.get("op") == "update":
            written = op.get("fields", {})
        else:
            continue
        spec = tables.get(op.get("table"))
        if spec is None:
            continue
        for name, value in written.items():
            column = spec.columns.get(name)
            if column is None or value is None or column.type not in ("code_exec", "code_eval"):
                continue
            language = "codelet_body" if column.type == "code_exec" else "expression"
            problem = check_code(
                language, value, name=f"<{spec.name}.{name}>", op_index=i,
                field=name, table=spec.name,
            )
            if problem is not None:
                out.append(problem)
    return out


# ---------------------------------------------------------------------------
# 409 stale
# ---------------------------------------------------------------------------


def check_base_version(
    base_version: Any, current_version: int, base_mode: str = "strict"
) -> InputProblem | None:
    """A stale ``base_version`` is refused, only under ``base_mode: strict``.

    ``rebase`` applies the batch whatever the author saw (each op is then guarded by its own
    ``expect``).  ``"head"`` means rebase.  A missing ``base_version`` under strict is
    malformed (400): the compare-and-set needs it.
    """
    if base_mode == "rebase" or base_version == "head":
        return None
    if isinstance(base_version, bool) or not isinstance(base_version, int):
        return InputProblem(MALFORMED, "base_version must be an integer revision or \"head\"", None, "base_version")
    if base_version != current_version:
        return InputProblem(
            STALE,
            f"base_version {base_version} is not the current version {current_version}",
            None, "base_version",
        )
    return None


# ---------------------------------------------------------------------------
# The working copy: ops applied in order (missing key, expect, key exists)
# ---------------------------------------------------------------------------


def _key_tuple(spec: TableSpec, key: Mapping[str, Any]) -> tuple:
    return tuple(key.get(k) for k in spec.key)


def _expect_matches(row: Mapping[str, Any], expect: Mapping[str, Any]) -> bool:
    return all(name in row and _same(row[name], value) for name, value in expect.items())


def _same(a: Any, b: Any) -> bool:
    """Equal in value *and* in JSON number type (``5`` is not ``5.0``)."""
    if isinstance(a, bool) != isinstance(b, bool):
        return False
    if isinstance(a, float) != isinstance(b, float):
        return False
    return a == b


@dataclass
class ApplyResult:
    state: State
    problems: list[InputProblem] = field(default_factory=list)
    #: Under ``on_op_failure: skip``: ``(op_index, problem)`` for each op left unapplied.
    skipped: list[tuple[int, InputProblem]] = field(default_factory=list)
    applied: list[int] = field(default_factory=list)


def apply_ops_to_copy(
    state: State,
    tables: Mapping[str, TableSpec],
    ops: Sequence[Mapping[str, Any]],
    *,
    on_op_failure: str = "abort",
) -> ApplyResult:
    """Apply *ops* in order to a deep copy of *state*; *state* itself is never touched.

    An op that cannot be applied is a problem: ``update`` or ``delete`` of a missing key
    (422 ``unknown_reference``, unless the delete says ``ok_if_missing``), a failed ``expect``
    (409 ``stale``), an ``insert`` whose natural key exists (409 ``key_exists``).  Under
    ``abort`` the first problem ends the walk and the caller refuses the batch; under
    ``skip`` the op is recorded in ``skipped`` and the rest apply.
    """
    work: State = copy.deepcopy(state)
    result = ApplyResult(state=work)
    for i, op in enumerate(ops):
        spec = tables[op["table"]]
        rows = work.setdefault(spec.name, {})
        problem: InputProblem | None = None
        kind = op["op"]
        if kind == "insert":
            row = dict(op["row"])
            key = spec.key_of(row)
            if key in rows:
                problem = InputProblem(
                    KEY_EXISTS, f"{spec.name} already has key {list(key)}", i, "row", spec.name, list(key)
                )
            else:
                rows[key] = row
        else:
            key = _key_tuple(spec, op["key"])
            existing = rows.get(key)
            if existing is None:
                if not (kind == "delete" and op.get("ok_if_missing")):
                    problem = InputProblem(
                        UNKNOWN_REFERENCE, f"{spec.name} has no row with key {list(key)}", i, "key",
                        spec.name, list(key),
                    )
                else:
                    result.applied.append(i)
                    continue
            elif "expect" in op and not _expect_matches(existing, op["expect"]):
                problem = InputProblem(
                    STALE, f"{spec.name} row {list(key)} differs from expect", i, "expect", spec.name, list(key)
                )
            elif kind == "delete":
                del rows[key]
            else:
                updated = {**existing, **op["fields"]}
                new_key = spec.key_of(updated)
                if new_key != key:
                    if new_key in rows:
                        problem = InputProblem(
                            KEY_EXISTS, f"{spec.name} already has key {list(new_key)}", i, "fields",
                            spec.name, list(new_key),
                        )
                    else:
                        del rows[key]
                        rows[new_key] = updated
                else:
                    rows[key] = updated
        if problem is None:
            result.applied.append(i)
        elif on_op_failure == "skip":
            result.skipped.append((i, problem))
            # an op that failed halfway must leave nothing behind: only the failure paths
            # above that mutate are the key-collision ones, and they mutate after checking.
        else:
            result.problems.append(problem)
            break
    return result


# ---------------------------------------------------------------------------
# 422 unknown_reference
# ---------------------------------------------------------------------------


def _exists(target: str, value: Any, state: State, tables: Mapping[str, TableSpec],
            vocabularies: Mapping[str, Iterable[str]]) -> bool:
    if target in vocabularies:
        return value in vocabularies[target]
    spec = tables.get(target)
    if spec is None:
        # A reference to a table outside the target configuration's set cannot resolve.
        return False
    return (value,) in state.get(target, {})


def check_references(
    state: State,
    tables: Mapping[str, TableSpec],
    *,
    ops: Sequence[Mapping[str, Any]] | None = None,
    vocabularies: Mapping[str, Iterable[str]] | None = None,
) -> list[InputProblem]:
    """Every reference field names something that exists in *state* (the resulting state).

    With *ops*, only the rows those ops wrote are checked, each problem naming its op: the
    configuration may already hold references that are absent by design (a removed node that
    code still mentions is ``dangling``, not refused), and a batch is not to blame for them.
    Without *ops*, every row is checked and ``op_index`` is ``None``.

    A reference the cascade removed is not in *state* and so is not looked for: the cascade's
    deletions are part of the batch the caller resolved.
    """
    vocabularies = vocabularies or {}
    out: list[InputProblem] = []

    def check_row(spec: TableSpec, row: Mapping[str, Any], op_index: int | None) -> None:
        for name, column in spec.columns.items():
            ref = column.reference
            value = row.get(name)
            if ref is None or value is None:
                continue
            for item in (value if ref.many else [value]):
                if not _exists(ref.target, item, state, tables, vocabularies):
                    out.append(
                        InputProblem(
                            UNKNOWN_REFERENCE,
                            f"{spec.name}.{name} names {item!r}, which {ref.target} does not have",
                            op_index, name, spec.name, list(spec.key_of(row)),
                        )
                    )

    if ops is None:
        for table, rows in state.items():
            spec = tables.get(table)
            if spec is not None:
                for row in rows.values():
                    check_row(spec, row, None)
        return out

    for i, op in enumerate(ops):
        if op.get("op") == "delete":
            continue
        spec = tables[op["table"]]
        if op["op"] == "insert":
            key = spec.key_of(op["row"])
        else:
            key = spec.key_of({**op["key"], **op["fields"]})
        row = state.get(spec.name, {}).get(key)
        if row is not None:
            written = op["row"] if op["op"] == "insert" else op["fields"]
            check_row(spec, {k: v for k, v in row.items() if k in written or k in spec.key}, i)
    return out


# ---------------------------------------------------------------------------
# The four together
# ---------------------------------------------------------------------------


@dataclass
class Validation:
    """The outcome of :func:`validate_batch`.

    ``problems`` non-empty means the whole batch is refused and nothing is written.  Under
    ``on_op_failure: skip``, ops refused for a missing key, a failed ``expect``, a missing
    reference or code that does not compile are in ``skipped`` (with their reasons) and
    ``state`` is the result of applying the rest.
    """

    problems: list[InputProblem] = field(default_factory=list)
    skipped: list[tuple[int, InputProblem]] = field(default_factory=list)
    state: State | None = None

    @property
    def ok(self) -> bool:
        return not self.problems

    @property
    def status(self) -> int | None:
        return self.problems[0].status if self.problems else None


def validate_batch(
    batch: Any,
    state: State,
    tables: Mapping[str, TableSpec],
    *,
    current_version: int,
    vocabularies: Mapping[str, Iterable[str]] | None = None,
) -> Validation:
    """The four classes of 3.4(a), in order, on a working copy of *state*.

    1. malformed (400) -- the batch is read as a whole; if it is malformed nothing else runs;
    2. a stale ``base_version`` (409), under ``strict``;
    3. code that does not compile (422), then ops applied in order (missing key 422,
       failed ``expect`` 409, ``key_exists`` 409);
    4. references on the resulting state (422).

    *state* is not modified.  Under ``skip`` the ops that fail for the reasons the plan lists
    are skipped and reported; a malformed batch or a stale ``base_version`` refuses it either way.
    """
    malformed = check_malformed(batch, tables)
    if malformed:
        return Validation(problems=malformed)
    base_mode = batch.get("base_mode", "strict")
    stale = check_base_version(batch.get("base_version"), current_version, base_mode)
    if stale is not None:
        return Validation(problems=[stale])
    skip = batch.get("on_op_failure", "abort") == "skip"
    ops: list[Mapping[str, Any]] = batch["ops"]

    skipped: dict[int, InputProblem] = {}
    broken = check_code_in_ops(ops, tables)
    if broken and not skip:
        return Validation(problems=broken)
    for p in broken:
        skipped[p.op_index] = p  # type: ignore[index]

    # Under ``skip`` an op skipped for one reason can leave a later op's reference dangling
    # (a skipped node insert, then the link to it), so the walk repeats until it is stable.
    while True:
        kept = [(i, op) for i, op in enumerate(ops) if i not in skipped]
        index_of = [i for i, _ in kept]

        def original(problem: InputProblem) -> InputProblem:
            if problem.op_index is None:
                return problem
            return InputProblem(**{**problem.__dict__, "op_index": index_of[problem.op_index]})

        applied = apply_ops_to_copy(
            state, tables, [op for _, op in kept], on_op_failure="skip" if skip else "abort"
        )
        if applied.problems:
            return Validation(problems=[original(p) for p in applied.problems])
        for j, p in applied.skipped:
            skipped[index_of[j]] = original(p)
        survivors = [(index_of[j], kept[j][1]) for j in applied.applied]
        dangling = [
            InputProblem(**{**p.__dict__, "op_index": survivors[p.op_index][0]})
            for p in check_references(
                applied.state, tables, ops=[op for _, op in survivors], vocabularies=vocabularies
            )
        ]
        if dangling and not skip:
            return Validation(problems=dangling)
        if not dangling:
            break
        for p in dangling:
            skipped[p.op_index] = p  # type: ignore[index]
    return Validation(problems=[], skipped=sorted(skipped.items()), state=applied.state)
