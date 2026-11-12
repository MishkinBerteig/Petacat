"""Executors for Training Mode Sessions: where a Training Mode Session's runs actually execute.

A Training Mode Session feeds runs to an executor as they become due, so the interface is *submit a small
list of tasks, get a future of their outcomes*:

    submit(tasks, meta) -> concurrent.futures.Future[list[outcome]]   (outcomes in task order)
    workers, in_flight, kind, close()

Two implementations:

* :class:`SwarmExecutor` -- the warm forkserver process pool of the parallel plugin
  (``server.parallel.swarm``), one engine per core.  Used when the plugin imports.
* :class:`SerialExecutor` -- core, no plugin: runs one task at a time in **one child
  process** (``spawn``).  The numeric backend is selected through process-global
  environment variables, so switching it inside the API process would disturb the
  dashboard's live runs; a child owns its own environment.

**Pools are bound once; the configuration travels with the task.**  Neither executor hashes a
configuration, rebinds a pool or restarts a child when a session's configuration changes.
Each task carries a ``ConfigShip`` (``training_mode_session_memory``): the pickled provider its
run starts under, pickled once per provider object by the executor and cached by key in the
worker.  Sessions with different configurations, and one session across many versions, share
one pool (the swarm) or one child (the serial executor).

Both execute exactly the steps of ``swarm.run_one`` (``EngineRunner(meta)``,
``init_mcat(..., seed=seed, parameters=...)``, ``run_mcat(max_steps=...)`` under the task's
backend), so a run's outcome is the same whichever executor ran it
(``tests/parallel/test_swarm.py`` holds that).
"""

from __future__ import annotations

import importlib.util
import itertools
import json
import logging
import multiprocessing
import os
import pickle
import threading
import time
import traceback
from collections import OrderedDict
from concurrent.futures import Future, ProcessPoolExecutor
from dataclasses import dataclass, field, replace
from typing import Any

from server.engine.metadata import MetadataProvider
from server.engine.start_check import require_run_start

logger = logging.getLogger("petacat.session")

ENV_EXECUTOR = "PETACAT_SESSION_EXECUTOR"


@dataclass
class SessionTask:
    """One run of a Training Mode Session: a problem at one seed."""

    initial: str
    modified: str
    target: str
    answer: str | None
    seed: int
    max_steps: int
    parameters: dict[str, Any] | None
    backend: str
    #: The episode memory the run starts from (shared mode); ``None`` = a fresh memory.
    memory: Any = None
    #: The configuration the run starts under (a ``ConfigShip``); the executor's ``submit``
    #: fills it from the provider it is given.
    config: Any = None
    #: Test hook: ``"error"`` raises inside the run, ``"kill"`` kills the worker process.
    fault: str | None = None


@dataclass
class SessionOutcome:
    """What a run produced (same fields as the swarm's ``RunOutcome`` that matter)."""

    seed: int
    status: str
    answer: str
    answers: list[str]
    codelets: int
    seconds: float
    stopping_state: str
    temperature: float = 0.0
    answer_quality: float | None = None
    error: str | None = None
    worker_pid: int = 0
    additions: bytes | None = None
    need_snapshot: bool = False
    #: The change-API ops the run's codelets applied to its own Slipnet (``apply_ops``): plain,
    #: picklable dicts, identical ops removed.  The session's in-worker learner submits them.
    proposals: list = field(default_factory=list)

    def fingerprint(self) -> tuple:
        return (
            self.seed, self.status, self.answer, tuple(self.answers), self.codelets,
            self.stopping_state, self.temperature, self.answer_quality, self.error,
            _proposals_key(self.proposals),
        )


def outcome_fingerprint(o: Any) -> tuple:
    """The deterministic fields of an outcome of either executor."""
    return (
        o.seed, o.status, o.answer, tuple(o.answers), o.codelets, o.stopping_state,
        o.temperature, o.answer_quality, o.error, _proposals_key(getattr(o, "proposals", ())),
    )


def _proposals_key(proposals: Any) -> tuple:
    return tuple(json.dumps(p, sort_keys=True) for p in proposals or ())


# ---------------------------------------------------------------------------
# Backend resolution (the same rule with or without the plugin)
# ---------------------------------------------------------------------------


def available_backend_names() -> list[str]:
    from server.engine.numeric import available_backends

    return [*available_backends(), "off"]


def default_session_backend(meta: MetadataProvider) -> str:
    """The backend a Training Mode Session uses when the client names none.

    The plugin's measured policy (``swarm.default_backend``) when it imports; otherwise
    the same size rule computed here, so a Training Mode Session's results do not depend on whether the
    plugin is present.
    """
    try:
        from server.parallel import swarm as _swarm
    except ImportError:
        _swarm = None
    if _swarm is not None:
        return _swarm.default_backend(meta)
    if importlib.util.find_spec("numpy") is None:
        return "off"
    from server.engine.numeric.backend import vectorise_threshold

    nodes = len(meta.slipnet_node_specs) if meta is not None else 0
    return "numpy" if nodes >= vectorise_threshold() else "off"


# ---------------------------------------------------------------------------
# Shipping a configuration with the tasks
# ---------------------------------------------------------------------------

#: Keys for shipped providers, unique in this (the sending) process.
_SHIP_KEYS = itertools.count(1)


class _Shipper:
    """Pickles each provider object once and names it (a few sessions' current versions).

    A session's provider is one object until an entry changes the configuration, so the
    pickle (about 0.2 ms) is paid once per configuration version, never per task.  Holding
    the provider keeps its ``id`` from being reused while it is cached.
    """

    LIMIT = 16

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_id: OrderedDict[int, tuple[MetadataProvider, Any]] = OrderedDict()

    def ship(self, meta: MetadataProvider):
        from server.services.training_mode_session_memory import ConfigShip

        with self._lock:
            got = self._by_id.get(id(meta))
            if got is not None:
                self._by_id.move_to_end(id(meta))
                return got[1]
            ship = ConfigShip(next(_SHIP_KEYS), pickle.dumps(meta, protocol=pickle.HIGHEST_PROTOCOL))
            self._by_id[id(meta)] = (meta, ship)
            while len(self._by_id) > self.LIMIT:
                self._by_id.popitem(last=False)
            return ship


# ---------------------------------------------------------------------------
# The serial executor's child process
# ---------------------------------------------------------------------------

#: The key of the serial executor's one child.
_CHILD = "child"


def _watch_owner(owner_pid: int) -> None:
    """Exit when the process that owns this child is gone (it was killed: no ``atexit``)."""
    import threading

    def _loop() -> None:
        while True:
            time.sleep(1.0)
            try:
                os.kill(owner_pid, 0)
            except PermissionError:
                continue
            except ProcessLookupError:
                os._exit(0)

    threading.Thread(target=_loop, name="owner-watchdog", daemon=True).start()


def _child_init(owner_pid: int = 0) -> None:
    if owner_pid:
        _watch_owner(owner_pid)
    for name in ("OMP_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ.setdefault(name, "1")


def run_task(task: SessionTask, meta: MetadataProvider | None = None) -> SessionOutcome:
    """Execute one run in this process under the task's backend (``swarm.run_one``'s steps).

    The run's provider is the task's shipped configuration, else *meta*."""
    from server.engine.numeric.backend import use_backend
    from server.engine.runner import EngineRunner

    started = time.perf_counter()
    try:
        if task.fault == "kill":
            os._exit(137)  # test hook: this worker dies mid-task
        memory = None
        from server.services import training_mode_session_memory as tm

        try:
            memory, base_a, base_s, meta = tm.begin_run(task.memory, task.config, meta)
        except tm.NeedSnapshot:
            return SessionOutcome(
                seed=task.seed, status="need_snapshot", answer="", answers=[], codelets=0,
                seconds=0.0, stopping_state="need_snapshot:", need_snapshot=True,
                worker_pid=os.getpid(),
            )
        with use_backend(task.backend):
            runner = EngineRunner(meta)
            runner.init_mcat(
                task.initial, task.modified, task.target, task.answer,
                seed=task.seed, parameters=task.parameters or None, memory=memory,
            )
            if task.fault == "error":
                raise RuntimeError("injected fault")
            result = runner.run_mcat(max_steps=task.max_steps)
            ctx = runner.ctx
            ans = ctx.workspace.answer_string
            answer = ans.text if ans else ""
            quality = None
            # Only an answer this run added counts (``swarm._outcome``'s rule).
            before = base_a if memory is not None else None
            if ctx is not None and ctx.memory.answers and (
                before is None or len(ctx.memory.answers) > before
            ):
                quality = float(ctx.memory.answers[0].quality)
            reported = list(
                getattr(result, "answers", None) or getattr(runner, "_answers", []) or []
            )
            return SessionOutcome(
                seed=task.seed, status=runner.status, answer=answer, answers=reported,
                codelets=ctx.codelet_count if ctx else 0,
                seconds=time.perf_counter() - started,
                stopping_state=f"{runner.status}:{answer}",
                temperature=float(ctx.temperature.value) if ctx else 0.0,
                answer_quality=quality, worker_pid=os.getpid(),
                additions=tm.end(memory, base_a, base_s) if memory is not None else None,
                proposals=list(ctx.proposals) if ctx else [],
            )
    except Exception:  # noqa: BLE001 - one bad run must not sink a Training Mode Session
        return SessionOutcome(
            seed=task.seed, status="error", answer="", answers=[], codelets=0,
            seconds=time.perf_counter() - started, stopping_state="error:",
            error=traceback.format_exc(limit=6), worker_pid=os.getpid(),
        )


def _child_run(tasks: list[SessionTask]) -> list[SessionOutcome]:
    return [run_task(t) for t in tasks]


# ---------------------------------------------------------------------------
# Executors
# ---------------------------------------------------------------------------


class _Counting:
    """In-flight task accounting shared by the executors."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._in_flight = 0

    @property
    def in_flight(self) -> int:
        return self._in_flight

    def _track(self, future: Future, n: int) -> Future:
        with self._lock:
            self._in_flight += n

        def _done(_f: Future) -> None:
            with self._lock:
                self._in_flight -= n

        future.add_done_callback(_done)
        return future


class SerialExecutor(_Counting):
    """One run at a time in one spawned child process (no plugin needed).

    The child is keyed by a constant: it is started at the first submit and replaced only
    if it dies.  It is bound to nothing; each task brings its configuration."""

    kind = "serial"
    workers = 1

    def __init__(self) -> None:
        super().__init__()
        self._pools: dict[str, tuple[ProcessPoolExecutor, _Counting]] = {}
        self._plock = threading.Lock()
        self._closed = False
        self._shipper = _Shipper()

    def _pool(self) -> tuple[ProcessPoolExecutor, _Counting]:
        with self._plock:
            if self._closed:
                raise RuntimeError("executor is closed")
            entry = self._pools.get(_CHILD)
            if entry is not None and getattr(entry[0], "_broken", False):
                # The child died (killed, out of memory): start a fresh one.
                entry[0].shutdown(wait=False, cancel_futures=True)
                del self._pools[_CHILD]
                entry = None
            if entry is None:
                pool = ProcessPoolExecutor(
                    max_workers=1,
                    mp_context=multiprocessing.get_context("spawn"),
                    initializer=_child_init,
                    initargs=(os.getpid(),),
                )
                entry = (pool, _Counting())
                self._pools[_CHILD] = entry
            return entry

    def submit(self, tasks: list[SessionTask], meta: MetadataProvider) -> Future:
        require_run_start(meta)  # first: before a child process is started for it
        ship = self._shipper.ship(meta)
        pool, count = self._pool()
        future = pool.submit(_child_run, [replace(t, config=ship) for t in tasks])
        count._track(future, len(tasks))
        return self._track(future, len(tasks))

    def close(self) -> None:
        with self._plock:
            self._closed = True
            pools, self._pools = list(self._pools.values()), {}
        for pool, _ in pools:
            pool.shutdown(wait=False, cancel_futures=True)


class SwarmExecutor(_Counting):
    """The parallel plugin's warm process pool, fed through ``Swarm.submit``.

    The pool is bound once (see :meth:`_bind`) and every submit passes it no provider: the
    tasks carry their configuration, so a change of configuration never touches the pool."""

    kind = "swarm"

    def __init__(self, swarm: Any = None, base: MetadataProvider | None = None) -> None:
        """A Training Mode Session gets a pool of its own (sized like the default), not ``default_swarm()``.

        The default swarm is shared with ``/api/swarm`` and the dashboard; a Training Mode Session run
        dispatched to it could queue behind their jobs and start on an older memory than
        the one it was dispatched with.  Alone on its pool, with at most one run per
        worker in flight, a dispatched run starts at once.

        *base* is the global provider to bind the pool to.  Without it the pool is bound to the
        first provider submitted (the workers need some configuration to warm up on; no task
        runs on it).
        """
        super().__init__()
        from server.parallel import swarm as swarm_module

        self._mod = swarm_module
        self._swarm = swarm if swarm is not None else swarm_module.Swarm(meta=base)
        self._owned = True
        self._shipper = _Shipper()
        self._bind_lock = threading.Lock()

    @property
    def swarm(self):
        return self._swarm

    @property
    def workers(self) -> int:
        return self.swarm.workers

    def _bind(self, meta: MetadataProvider) -> None:
        """Bind the pool once, to *meta* if nothing has bound it yet.  Never again."""
        if self._swarm.bound:
            return
        with self._bind_lock:
            if not self._swarm.bound:
                self._swarm.configure(meta)

    def submit(self, tasks: list[SessionTask], meta: MetadataProvider) -> Future:
        require_run_start(meta)  # first: before a run task is built
        self._bind(meta)
        ship = self._shipper.ship(meta)
        run_tasks = [
            self._mod.RunTask(
                t.initial, t.modified, t.target, t.answer, t.seed, t.max_steps,
                parameters=t.parameters or None, backend=t.backend,
                memory=t.memory, config=ship, fault=t.fault,
            )
            for t in tasks
        ]
        return self._track(self.swarm.submit(run_tasks, None), len(tasks))

    def close(self) -> None:
        if self._owned and self._swarm is not None:
            self._swarm.shutdown(wait_for_tasks=False)  # the owner watchdog covers a kill


def swarm_available() -> bool:
    try:
        from server.parallel import swarm  # noqa: F401
    except ImportError:
        return False
    return True


def create_executor(kind: str | None = None, base: MetadataProvider | None = None):
    """The executor for this process: forced by *kind* or ``PETACAT_SESSION_EXECUTOR``,
    else the swarm when the plugin imports, else the serial child.  *base* is the global
    provider the swarm's pool is bound to (see :class:`SwarmExecutor`)."""
    kind = (kind or os.environ.get(ENV_EXECUTOR) or "").strip().lower() or None
    if kind not in (None, "serial", "swarm"):
        raise ValueError(f"{ENV_EXECUTOR} must be 'serial' or 'swarm', not {kind!r}")
    if kind == "swarm" or (kind is None and swarm_available()):
        if not swarm_available():
            raise RuntimeError("the swarm executor needs server/parallel/, which is absent")
        return SwarmExecutor(base=base)
    return SerialExecutor()
