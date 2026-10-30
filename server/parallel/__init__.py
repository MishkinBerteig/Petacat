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
``swarm`` (with ``qos``)
    Run-level parallelism: a warm ``forkserver`` process pool over every core, each run
    byte-for-byte the serial run with the same seed.  The throughput path -- answer
    distributions, oracle comparisons, sweeps, episodes -- and ``POST /api/swarm``.
``speculative``
    Within-run parallelism that is *exact*: the stream-serial reference (``"stream"``:
    per-codelet counter-based random streams and an exponential-race coderack, equal in
    law to the faithful loop) and the speculative executor (``"speculative"``), which runs
    codelets' read prefixes on worker threads and commits them in serial order, so its
    result is bit-identical to the stream reference for every worker count.
``update_cycle``
    The update cycle re-implemented plugin-side, faithful or stream-keyed, with its
    Jacobi-safe loops on a thread team.
``placement``
    Which numeric backend each executor runs on, from measurements: the CPU, because at
    today's Slipnet size a Metal dispatch costs more than the whole update.
``free_running``
    The first free-running engine (WP4.4): codelets on several threads with no global
    barrier.  Measurably changes cognition (``abce`` 15.0% serially, 9.3% at six
    workers), so the service no longer uses it; kept as the comparison point.
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


# -- within-run, exact executors (WP3) -------------------------------------------------
# ``"stream"`` is the stream-serial reference; ``"speculative"`` runs the same run across
# threads and is bit-identical to it for every worker count.  See
# ``server/parallel/speculative/``.
register_executor("stream", "server.parallel.speculative.reference:StreamSerialExecutor")
register_executor("speculative", "server.parallel.speculative.engine:SpeculativeExecutor")
