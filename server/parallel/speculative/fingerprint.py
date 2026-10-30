"""A fingerprint of the shared engine state, component by component.

Two jobs.  The **hidden-write detector** (``SpeculativeEngine(..., detect=True)``) takes
one before a codelet body and compares it to one taken the moment the body first does
anything the speculative engine would trap: any component that moved was written by
what the audit called a pure read, and the speculation would have been inexact.  The
**exactness harness** takes one at the end of a run, from the SSR and from the
speculative run, and they must be equal.

The fingerprint is deliberately *structural and exhaustive* rather than clever: every
object reachable from a component is walked, every attribute is recorded, and an engine
object met on the way is recorded by ``(class, id)`` so that identity, not content, is
what a reference contributes.  It is slow (milliseconds) and only used in tests.
"""

from __future__ import annotations

import hashlib
from typing import Any

_PRIMITIVES = (type(None), bool, int, str, bytes)

#: Attributes that are not part of a component's state (back-references to the shared
#: infrastructure, or callables).
_SKIP = frozenset({
    "verbose_ctx", "ctx", "meta", "slipnet", "workspace", "commentary",
    "commentary_templates", "_themespace", "sink", "view_history", "_lock",
})


def _attrs(obj: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    d = getattr(obj, "__dict__", None)
    if d:
        out.update(d)
    for klass in type(obj).__mro__:
        for name in getattr(klass, "__slots__", ()) or ():
            if name in ("__dict__", "__weakref__") or name in out:
                continue
            try:
                out[name] = getattr(obj, name)
            except AttributeError:
                pass
    return out


def _engine_class(obj: Any) -> type | None:
    """The engine class *obj* is (or derives from): plugin subclasses swapped in by the
    speculative engine (``_SpecContext``, ``_DeferredNode`` ...) are transparent."""
    if isinstance(obj, type):
        return None
    for klass in type(obj).__mro__:
        if klass.__module__.startswith("server.engine"):
            return klass
    return None


def _is_engine_object(obj: Any) -> bool:
    return _engine_class(obj) is not None


def _ref(obj: Any) -> tuple:
    ident = getattr(obj, "id", None)
    if ident is None:
        ident = getattr(obj, "name", None)
    if ident is None:
        ident = getattr(obj, "event_number", None)
    return ("ref", _engine_class(obj).__name__, ident if ident is not None else "?")


def canon(obj: Any, seen: set[int] | None = None, top: bool = True) -> Any:
    """A hashable, deterministic description of *obj*'s state."""
    if isinstance(obj, _PRIMITIVES):
        return obj
    if isinstance(obj, float):
        return ("f", repr(obj))
    if isinstance(obj, (list, tuple)):
        return ("seq", tuple(canon(x, seen, False) for x in obj))
    if isinstance(obj, (set, frozenset)):
        return ("set", tuple(sorted(repr(canon(x, seen, False)) for x in obj)))
    if isinstance(obj, dict):
        items = [(repr(canon(k, seen, False)), canon(v, seen, False)) for k, v in obj.items()]
        return ("map", tuple(sorted(items, key=lambda kv: kv[0])))
    if callable(obj) and not _is_engine_object(obj):
        return ("callable",)
    if not _is_engine_object(obj):
        return ("opaque", type(obj).__name__)
    if not top and (hasattr(obj, "id") or hasattr(obj, "name")):
        return _ref(obj)
    seen = set() if seen is None else seen
    if id(obj) in seen:
        return ("cycle", _engine_class(obj).__name__)
    seen.add(id(obj))
    try:
        fields = _attrs(obj)
        body = tuple(
            (k, canon(v, seen, False))
            for k, v in sorted(fields.items())
            if k not in _SKIP and not k.startswith("__")
        )
        return ("obj", _engine_class(obj).__name__, body)
    finally:
        seen.discard(id(obj))


def _workspace_state(ctx: Any) -> Any:
    ws = ctx.workspace
    seen: set[int] = set()
    parts: list[Any] = [canon(ws, seen, True)]
    for s in ws.all_strings:
        parts.append(canon(s, seen, True))
        for o in list(s.objects):
            parts.append(canon(o, seen, True))
        for b in list(s.bonds):
            parts.append(canon(b, seen, True))
        for g in list(s.groups):
            parts.append(canon(g, seen, True))
    for lst in (ws.top_bridges, ws.bottom_bridges, ws.vertical_bridges,
                ws.top_rules, ws.bottom_rules):
        for x in list(lst):
            parts.append(canon(x, seen, True))
    return tuple(parts)


def _slipnet_state(ctx: Any) -> tuple[Any, Any]:
    act, buf = [], []
    for name, node in sorted(ctx.slipnet.nodes.items()):
        act.append((name, repr(node.activation), node.frozen,
                    repr(getattr(node, "_decay_percent", None))))
        buf.append((name, repr(node.activation_buffer)))
    return tuple(act), tuple(buf)


def state(ctx: Any) -> dict[str, Any]:
    """The raw canonical state of each component (what :func:`fingerprint` hashes)."""
    ws = _workspace_state(ctx)
    act, buf = _slipnet_state(ctx)
    rack = ctx.coderack
    trace = ctx.trace
    out: dict[str, Any] = {
        "workspace": ws,
        "slipnet_act": act,
        "slipnet_buf": buf,
        "themespace": canon(ctx.themespace, None, True),
        "trace": (
            len(trace.events),
            tuple(getattr(e, "event_number", None) for e in trace.events),
            canon({k: v for k, v in _attrs(trace).items() if k != "events" and k not in _SKIP}, None, True),
        ),
        "memory": canon(ctx.memory, None, True),
        "temperature": canon(ctx.temperature, None, True),
        "coderack": (
            rack.total_count,
            tuple(tuple(c.id for c in b.codelets) for b in rack.bins),
            tuple(sorted(rack.clamped_urgencies.items())),
        ),
        "ids": tuple(sorted(ctx.ids.snapshot().items())),
        "ctx_scalars": tuple(
            (name, canon(getattr(ctx, name, None), None, False))
            for name in ("_pending_answer", "_pending_answer_quality", "_gave_up",
                         "last_failure_objects", "last_failure_kind", "last_failure",
                         "run_ended", "last_codelet_type", "justify_mode")
        ),
    }
    return out


def fingerprint(ctx: Any) -> dict[str, str]:
    """``{component: sha1}`` over the shared state of *ctx*."""
    return {
        name: hashlib.sha1(repr(value).encode()).hexdigest()
        for name, value in state(ctx).items()
    }


def first_differences(a: Any, b: Any, path: str = "", limit: int = 4) -> list[str]:
    """Where two canonical states first differ (for diagnostics)."""
    out: list[str] = []

    def walk(x: Any, y: Any, p: str) -> None:
        if len(out) >= limit or x == y:
            return
        if isinstance(x, tuple) and isinstance(y, tuple) and len(x) != len(y):
            n = next((i for i, (xi, yi) in enumerate(zip(x, y)) if xi != yi), min(len(x), len(y)))
            out.append(f"{p}: length {len(x)} -> {len(y)}; at [{n}]: "
                       f"{str(x[n] if n < len(x) else None)[:70]} -> "
                       f"{str(y[n] if n < len(y) else None)[:70]}")
            return
        if isinstance(x, tuple) and isinstance(y, tuple):
            label = p
            if len(x) >= 2 and x[0] == "obj":
                label = f"{p}/{x[1]}"
            for i, (xi, yi) in enumerate(zip(x, y)):
                if len(x) == 2 and isinstance(x[0], str) and x[0] != "obj":
                    walk(xi, yi, f"{label}.{x[0]}")
                else:
                    walk(xi, yi, f"{label}[{i}]")
            return
        out.append(f"{p}: {str(x)[:90]} -> {str(y)[:90]}")

    walk(a, b, path)
    return out


def combined(ctx: Any) -> str:
    """One digest over every component (for the end-of-run comparison)."""
    fp = fingerprint(ctx)
    return hashlib.sha256(repr(sorted(fp.items())).encode()).hexdigest()
