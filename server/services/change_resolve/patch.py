"""A JSON Patch subset (RFC 6902: add, remove, replace, move, test), pure.

Used for JSON columns and for JSON-typed engine parameters (3.12.2, 3.12.3).  ``apply_patch``
returns a new value and never mutates its argument.
"""

from __future__ import annotations

import copy
from typing import Any, Sequence

PATCH_OPS = ("add", "remove", "replace", "move", "test")


class PatchError(ValueError):
    """A patch that cannot be applied.

    ``kind`` is ``malformed`` (not a patch), ``missing`` (a path names nothing) or ``test``
    (a ``test`` op found a different value).
    """

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


def parse_pointer(pointer: Any) -> list[str]:
    if not isinstance(pointer, str):
        raise PatchError("malformed", "a path must be a JSON pointer string")
    if pointer == "":
        return []
    if not pointer.startswith("/"):
        raise PatchError("malformed", f"path {pointer!r} must be empty or start with '/'")
    return [p.replace("~1", "/").replace("~0", "~") for p in pointer[1:].split("/")]


def _index(container: list, token: str, *, allow_end: bool) -> int:
    if token == "-" and allow_end:
        return len(container)
    if not token.isdigit() or (len(token) > 1 and token[0] == "0"):
        raise PatchError("missing", f"{token!r} is not an array index")
    i = int(token)
    if i > len(container) or (i == len(container) and not allow_end):
        raise PatchError("missing", f"index {i} is out of range")
    return i


def _walk(doc: Any, tokens: Sequence[str]) -> Any:
    cur = doc
    for t in tokens:
        if isinstance(cur, dict):
            if t not in cur:
                raise PatchError("missing", f"no member {t!r}")
            cur = cur[t]
        elif isinstance(cur, list):
            cur = cur[_index(cur, t, allow_end=False)]
        else:
            raise PatchError("missing", f"cannot descend into {type(cur).__name__}")
    return cur


def _add(doc: Any, tokens: list[str], value: Any) -> Any:
    if not tokens:
        return value
    parent = _walk(doc, tokens[:-1])
    last = tokens[-1]
    if isinstance(parent, dict):
        parent[last] = value
    elif isinstance(parent, list):
        parent.insert(_index(parent, last, allow_end=True), value)
    else:
        raise PatchError("missing", f"cannot add into {type(parent).__name__}")
    return doc


def _remove(doc: Any, tokens: list[str]) -> tuple[Any, Any]:
    if not tokens:
        raise PatchError("malformed", "cannot remove the whole document")
    parent = _walk(doc, tokens[:-1])
    last = tokens[-1]
    if isinstance(parent, dict):
        if last not in parent:
            raise PatchError("missing", f"no member {last!r}")
        return doc, parent.pop(last)
    if isinstance(parent, list):
        return doc, parent.pop(_index(parent, last, allow_end=False))
    raise PatchError("missing", f"cannot remove from {type(parent).__name__}")


def apply_patch(doc: Any, patch: Any) -> Any:
    """*doc* with the patch's ops applied in order (a deep copy; *doc* is untouched)."""
    if not isinstance(patch, list):
        raise PatchError("malformed", "a patch must be a list of ops")
    out = copy.deepcopy(doc)
    for n, op in enumerate(patch):
        if not isinstance(op, dict) or op.get("op") not in PATCH_OPS:
            raise PatchError("malformed", f"patch op {n} must be an object with op in {PATCH_OPS}")
        kind = op["op"]
        tokens = parse_pointer(op.get("path"))
        if kind in ("add", "replace", "test") and "value" not in op:
            raise PatchError("malformed", f"patch op {n} ({kind}) needs a value")
        if kind == "add":
            out = _add(out, tokens, copy.deepcopy(op["value"]))
        elif kind == "remove":
            out, _ = _remove(out, tokens)
        elif kind == "replace":
            if not tokens:
                out = copy.deepcopy(op["value"])
            else:
                _walk(out, tokens)  # must exist
                parent = _walk(out, tokens[:-1])
                if isinstance(parent, dict):
                    parent[tokens[-1]] = copy.deepcopy(op["value"])
                else:
                    parent[_index(parent, tokens[-1], allow_end=False)] = copy.deepcopy(op["value"])
        elif kind == "move":
            src = parse_pointer(op.get("from"))
            if tokens[: len(src)] == src and len(tokens) > len(src):
                raise PatchError("malformed", "cannot move a value into itself")
            out, moved = _remove(out, src)
            out = _add(out, tokens, moved)
        else:  # test
            if _walk(out, tokens) != op["value"]:
                raise PatchError("test", f"value at {op.get('path')!r} differs from the test value")
    return out
