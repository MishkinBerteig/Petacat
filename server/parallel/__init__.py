"""Petacat Parallel — the pluggable multi-core subsystem.

``server/engine/`` is the cognitive architecture, and it is single-threaded and
Metacat-faithful by construction: one codelet at a time, one random stream, one
update cycle every fifteen codelets.  Everything that spreads Petacat across a
machine's cores lives here instead, so the engine never acquires concurrency by
proximity and Petacat runs, unchanged, with this package deleted.

The dependency points one way only.  This package imports the engine; the engine
never imports this package (``tests/architecture/test_parallel_detachable.py``
holds it to that), and the service layer reaches it through :func:`load`, which
answers ``None`` when the package is absent so a caller can fall back to the serial
loop rather than fail.

What lives here
---------------
``free_running``
    The first free-running engine (WP4.4): codelets on several threads with no
    global barrier.  Measurably changes cognition — see the README — and is kept
    as the comparison point for what replaces it.
``coderack_shards``
    The locked rack free-running installs, and the sharded benchmark candidates.
``population``
    K independent runs across a process pool, and the lockstep batching seam.
"""

from __future__ import annotations

from importlib import import_module
from types import ModuleType
from typing import Any, Callable

#: Executors by name.  A factory takes a prepared ``EngineRunner`` and keyword
#: options and returns an object with ``run(max_steps) -> result``.  Registered
#: lazily (by dotted path) so importing the plugin costs nothing until an executor
#: is actually asked for.
_EXECUTORS: dict[str, str] = {
    "free": "server.parallel.free_running:FreeRunningEngine",
}


def register_executor(name: str, target: str | Callable[..., Any]) -> None:
    """Register an executor factory under *name*.

    *target* is a callable or a ``"module:attribute"`` path resolved on first use.
    """
    _EXECUTORS[name] = target  # type: ignore[assignment]


def executor_names() -> list[str]:
    """The executors this plugin offers, in registration order."""
    return list(_EXECUTORS)


def get_executor(name: str) -> Callable[..., Any]:
    """Resolve the factory registered as *name*.  ``KeyError`` if there is none."""
    target: Any = _EXECUTORS[name]
    if isinstance(target, str):
        module_name, _, attribute = target.partition(":")
        target = getattr(import_module(module_name), attribute)
        _EXECUTORS[name] = target
    return target


def load() -> ModuleType | None:
    """This package, or ``None`` when it has been detached.

    The one entry point the service layer uses, so "is the parallel subsystem
    installed?" has a single answer and a missing plugin degrades to serial
    execution instead of an ``ImportError`` at startup.
    """
    try:
        return import_module("server.parallel")
    except ImportError:
        return None
