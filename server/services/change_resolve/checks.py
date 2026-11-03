"""Shape checks for the whole batch (400 ``malformed``), the compile check and typed values.

The generic ops are checked by C0's ``check_malformed`` (``configuration_input.py``); this
module adds the envelope, the convenience ops' arguments and the JSON Patch field, and wraps
the engine's own compilers for the code columns.
"""

from __future__ import annotations

import json
from fractions import Fraction
from typing import Any, Mapping

from server.services.change_resolve.errors import ChangeRefused
from server.services.change_resolve.patch import PATCH_OPS
from server.services.change_resolve.spec import (
    CONVENIENCE_OPS,
    INPUT_TABLES,
)
from server.services.configuration_input import (
    DOES_NOT_COMPILE,
    MALFORMED,
    OPS,
    InputProblem,
    check_malformed,
    parse_param_value,
)

# --- convenience-op arguments ------------------------------------------------
# tag: s text, i integer, n number, o object, l list, b bool, a anything.  A trailing * is
# required.
_ARGS: dict[str, dict[str, str]] = {
    "add_node": {"name": "s*", "fields": "o", "links": "l", "roles": "l", "layout": "o",
                 "theme_dimension": "o", "params": "o"},
    "remove_node": {"name": "s*", "splice": "l"},
    "rename_node": {"old": "s*", "new": "s*"},
    "merge_nodes": {"keep": "s*", "drop": "s*"},
    "add_link": {"from": "s", "to": "s", "type": "s", "label": "s", "length": "i", "fixed": "b",
                 "from_node": "s", "to_node": "s", "link_type": "s", "label_node": "s",
                 "link_length": "i", "fixed_length": "b"},
    "remove_link": {"key": "o*"},
    "set_param": {"name": "s*", "to": "a*", "value_type": "s", "expect": "a"},
    "adjust_param": {"name": "s*", "by": "n*"},
    "set_coefficient": {"name": "s*", "to": "a*", "value_type": "s", "expect": "a"},
    "adjust_coefficient": {"name": "s*", "by": "n*"},
    "set_urgency_level": {"name": "s*", "to": "i*", "expect": "i"},
    "adjust": {"table": "s*", "key": "o*", "field": "s*", "by": "n*"},
    "list_add": {"table": "s*", "key": "o*", "field": "s*", "value": "a*"},
    "list_remove": {"table": "s*", "key": "o*", "field": "s*", "value": "a*"},
    "reorder": {"table": "s*", "key": "o*", "before": "o"},
    "move_layout": {"node": "s*", "x": "i*", "y": "i*"},
    "add_trigger": {"rule_key": "s*", "node": "s*"},
    "remove_trigger": {"rule_key": "s*", "node": "s*"},
    "rebind_role": {"role": "s*", "node": "s", "codelet_type": "s", "ordinal": "i"},
    "unbind_role": {"role": "s*", "ordinal": "i", "ok_if_missing": "b"},
    "add_codelet_type": {"name": "s*", "fields": "o"},
    "remove_codelet_type": {"name": "s*"},
    "set_codelet_body": {"name": "s*", "source": "s*"},
    "set_predicate": {"node": "s*", "expr": "a*"},
    "set_formula": {"rule_key": "s*", "column": "s*", "expr": "a*"},
    "set_template": {"key": "s*", "path": "s*", "text": "a*"},
    "add_posting_rule": {"rule_key": "s", "fields": "o"},
    "remove_posting_rule": {"rule_key": "s*"},
    "add_demo_problem": {"name": "s*", "fields": "o"},
}
assert set(_ARGS) == set(CONVENIENCE_OPS)

_TAG_NAME = {"s": "text", "i": "an integer", "n": "a number", "o": "an object", "l": "a list",
             "b": "true or false"}


def _tag_ok(tag: str, v: Any) -> bool:
    if tag == "a":
        return True
    if tag == "s":
        return isinstance(v, str)
    if tag == "i":
        return isinstance(v, int) and not isinstance(v, bool)
    if tag == "n":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    if tag == "o":
        return isinstance(v, Mapping)
    if tag == "l":
        return isinstance(v, list)
    return isinstance(v, bool)


def _convenience_problems(i: int, op: Mapping[str, Any]) -> list[InputProblem]:
    kind = op["op"]
    args = _ARGS[kind]
    out = [
        InputProblem(MALFORMED, f"unknown argument {name!r} for {kind}", i, name)
        for name in op
        if name != "op" and name not in args
    ]
    for name, raw in args.items():
        tag = raw.rstrip("*")
        if name not in op:
            if raw.endswith("*"):
                out.append(InputProblem(MALFORMED, f"{kind} needs {name!r}", i, name))
            continue
        if not _tag_ok(tag, op[name]):
            out.append(
                InputProblem(MALFORMED, f"{name!r} must be {_TAG_NAME[tag]}", i, name)
            )
    return out


def _generic_problems(i: int, op: Mapping[str, Any]) -> list[InputProblem]:
    op = dict(op)
    patch = op.pop("patch", None) if op.get("op") == "update" else None
    out: list[InputProblem] = []
    if patch is not None:
        table = op.get("table")
        spec = INPUT_TABLES.get(table) if isinstance(table, str) else None
        if not isinstance(patch, Mapping):
            out.append(InputProblem(MALFORMED, "patch must map a column to a JSON Patch", i, "patch"))
        elif spec is not None:
            for column, ops in patch.items():
                col = spec.columns.get(column)
                if col is None or not (col.type == "json" or col.value_type_column):
                    out.append(InputProblem(MALFORMED, f"column {column!r} takes no JSON Patch", i, f"patch.{column}", table))
                elif not isinstance(ops, list) or not all(
                    isinstance(p, Mapping) and p.get("op") in PATCH_OPS for p in ops
                ):
                    out.append(InputProblem(MALFORMED, f"patch.{column} must be a list of JSON Patch ops", i, f"patch.{column}", table))
        if "fields" not in op:
            op["fields"] = {}
    for p in check_malformed({"ops": [op]}, INPUT_TABLES):
        out.append(InputProblem(**{**p.__dict__, "op_index": i if p.op_index is not None else None}))
    return out


def check_shape(batch: Any) -> None:
    """Raise :class:`ChangeRefused` (400 ``malformed``) unless the batch, its envelope and
    every op are in the shape the API takes."""
    if not isinstance(batch, Mapping):
        raise ChangeRefused([InputProblem(MALFORMED, "the batch must be an object")])
    problems = check_malformed({k: v for k, v in batch.items() if k != "ops"} | {"ops": []}, INPUT_TABLES)
    ops = batch.get("ops")
    if not isinstance(ops, list):
        problems.append(InputProblem(MALFORMED, "ops must be a list", None, "ops"))
        raise ChangeRefused(problems)
    for i, op in enumerate(ops):
        if not isinstance(op, Mapping):
            problems.append(InputProblem(MALFORMED, "an op must be an object", i, "op"))
        elif op.get("op") in OPS:
            problems.extend(_generic_problems(i, op))
        elif op.get("op") in CONVENIENCE_OPS:
            problems.extend(_convenience_problems(i, op))
        else:
            problems.append(InputProblem(MALFORMED, f"unknown op {op.get('op')!r}", i, "op"))
    if problems:
        raise ChangeRefused(problems)


# --- code -------------------------------------------------------------------


def compile_problem(table: str, column: str, source: Any, name: str) -> tuple[str, int, int] | None:
    """``(message, line, column)`` if the engine's own compiler refuses *source*, else ``None``.

    The codelet body goes through ``CodeletInterpreter.compile``, the descriptor predicate
    through ``compile_descriptor_predicate`` and the posting formulas through
    ``compile_posting_formula``.  Blank source compiles (an empty body is the defined no-op).
    """
    if source is None or not isinstance(source, str) or not source.strip():
        return None
    try:
        if table == "codelet_type_defs":
            from server.engine.codelet_dsl.interpreter import CodeletInterpreter

            CodeletInterpreter().compile(source, name)
        elif table == "slipnet_node_defs":
            from server.engine.slipnet import compile_descriptor_predicate

            compile_descriptor_predicate(source, name)
        else:
            from server.engine.posting import compile_posting_formula

            compile_posting_formula(source, name)
    except (ValueError, SyntaxError, OverflowError, RecursionError, MemoryError) as exc:
        cause = exc if isinstance(exc, SyntaxError) else exc.__cause__
        if isinstance(cause, SyntaxError):
            return cause.msg, cause.lineno or 1, cause.offset or 1
        return f"{type(exc).__name__}: {exc}", 1, 1
    return None


def does_not_compile(i: int, table: str, column: str, key: Any, language: str, found) -> InputProblem:
    message, line, col = found
    return InputProblem(
        DOES_NOT_COMPILE, message, i, column, table, key, language=language, line=line, column=col
    )


# --- typed parameter text ---------------------------------------------------


def format_param(value: Any, value_type: str) -> str:
    """The text a parameter stores for *value* under *value_type* (an invalid value gives text
    that ``check_param_value`` then refuses)."""
    if value_type == "json":
        return value if isinstance(value, str) else json.dumps(value)
    if value_type == "bool":
        return str(value).lower() if isinstance(value, bool) else str(value)
    if value_type == "float":
        return str(float(value)) if isinstance(value, (int, float)) and not isinstance(value, bool) else str(value)
    if value_type == "int":
        if isinstance(value, float) and value == int(value):
            return str(int(value))
        return str(value)
    if value_type == "rational":
        if isinstance(value, int) and not isinstance(value, bool):
            return f"{value}/1"
        return str(value)
    return value if isinstance(value, str) else str(value)


def parse_text(text: str, value_type: str) -> tuple[bool, Any]:
    return parse_param_value(text, value_type)


def fraction_text(f: Fraction) -> str:
    return f"{f.numerator}/{f.denominator}"
