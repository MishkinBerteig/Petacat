"""Executors for Trainings: where a Training's runs actually execute.

A Training feeds runs to an executor as they become due, so the interface is *submit a small
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

Both execute exactly the steps of ``swarm.run_one`` (``EngineRunner(meta)``,
``init_mcat(..., seed=seed, parameters=...)``, ``run_mcat(max_steps=...)`` under the task's
backend), so a run's outcome is the same whichever executor ran it
(``tests/parallel/test_swarm.py`` holds that).
"""

from __future__ import annotations

import importlib.util
import logging
import multiprocessing
import os
import pickle
import threading
import time
import traceback
from concurrent.futures import Future, ProcessPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from server.engine.hashing import config_hash
from server.engine.metadata import MetadataProvider

logger = logging.getLogger("petacat.training")

ENV_EXECUTOR = "PETACAT_TRAINING_EXECUTOR"


@dataclass
class TrainingTask:
    """One run of a Training: a problem at one seed."""

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
    #: Test hook: ``"error"`` raises inside the run, ``"kill"`` kills the worker process.
    fault: str | None = None


@dataclass
class TrainingOutcome:
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

    def fingerprint(self) -> tuple:
        return (
            self.seed, self.status, self.answer, tuple(self.answers), self.codelets,
            self.stopping_state, self.temperature, self.answer_quality, self.error,
        )


def outcome_fingerprint(o: Any) -> tuple:
    """The deterministic fields of an outcome of either executor."""
    return (
        o.seed, o.status, o.answer, tuple(o.answers), o.codelets, o.stopping_state,
        o.temperature, o.answer_quality, o.error,
    )


# ---------------------------------------------------------------------------
# Backend resolution (the same rule with or without the plugin)
# ---------------------------------------------------------------------------


def available_backend_names() -> list[str]:
    from server.engine.numeric import available_backends

    return [*available_backends(), "off"]


def default_training_backend(meta: MetadataProvider) -> str:
    """The backend a Training uses when the client names none.

    The plugin's measured policy (``swarm.default_backend``) when it imports; otherwise
    the same size rule computed here, so a Training's results do not depend on whether the
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
# The serial executor's child process
# ---------------------------------------------------------------------------

_C_META: MetadataProvider | None = None


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


def _child_init(meta_blob: bytes, owner_pid: int = 0) -> None:
    global _C_META
    if owner_pid:
        _watch_owner(owner_pid)
    for name in ("OMP_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ.setdefault(name, "1")
    _C_META = pickle.loads(meta_blob)


def run_task(task: TrainingTask, meta: MetadataProvider) -> TrainingOutcome:
    """Execute one run in this process under the task's backend (``swarm.run_one``'s steps)."""
    from server.engine.numeric.backend import use_backend
    from server.engine.runner import EngineRunner

    started = time.perf_counter()
    try:
        if task.fault == "kill":
            os._exit(137)  # test hook: this worker dies mid-task
        memory = None
        if task.memory is not None:
            from server.services import training_memory as tm

            try:
                memory, base_a, base_s = tm.begin(task.memory)
            except tm.NeedSnapshot:
                return TrainingOutcome(
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
            return TrainingOutcome(
                seed=task.seed, status=runner.status, answer=answer, answers=reported,
                codelets=ctx.codelet_count if ctx else 0,
                seconds=time.perf_counter() - started,
                stopping_state=f"{runner.status}:{answer}",
                temperature=float(ctx.temperature.value) if ctx else 0.0,
                answer_quality=quality, worker_pid=os.getpid(),
                additions=tm.end(memory, base_a, base_s) if memory is not None else None,
            )
    except Exception:  # noqa: BLE001 - one bad run must not sink a Training
        return TrainingOutcome(
            seed=task.seed, status="error", answer="", answers=[], codelets=0,
            seconds=time.perf_counter() - started, stopping_state="error:",
            error=traceback.format_exc(limit=6), worker_pid=os.getpid(),
        )


def _child_run(tasks: list[TrainingTask]) -> list[TrainingOutcome]:
    assert _C_META is not None
    return [run_task(t, _C_META) for t in tasks]


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
    """One run at a time in one spawned child process (no plugin needed)."""

    kind = "serial"
    workers = 1

    def __init__(self) -> None:
        super().__init__()
        self._pools: dict[str, tuple[ProcessPoolExecutor, _Counting]] = {}
        self._plock = threading.Lock()
        self._closed = False

    def _pool(self, meta: MetadataProvider) -> tuple[ProcessPoolExecutor, _Counting]:
        cfg = config_hash(meta)
        with self._plock:
            if self._closed:
                raise RuntimeError("executor is closed")
            entry = self._pools.get(cfg)
            if entry is not None and getattr(entry[0], "_broken", False):
                # The child died (killed, out of memory): start a fresh one.
                entry[0].shutdown(wait=False, cancel_futures=True)
                del self._pools[cfg]
                entry = None
            if entry is None:
                # A configuration nobody is using any more does not keep its child alive.
                for key, (pool, count) in list(self._pools.items()):
                    if count.in_flight == 0:
                        pool.shutdown(wait=False, cancel_futures=True)
                        del self._pools[key]
                pool = ProcessPoolExecutor(
                    max_workers=1,
                    mp_context=multiprocessing.get_context("spawn"),
                    initializer=_child_init,
                    initargs=(pickle.dumps(meta, protocol=pickle.HIGHEST_PROTOCOL), os.getpid()),
                )
                entry = (pool, _Counting())
                self._pools[cfg] = entry
            return entry

    def submit(self, tasks: list[TrainingTask], meta: MetadataProvider) -> Future:
        pool, count = self._pool(meta)
        future = pool.submit(_child_run, list(tasks))
        count._track(future, len(tasks))
        return self._track(future, len(tasks))

    def close(self) -> None:
        with self._plock:
            self._closed = True
            pools, self._pools = list(self._pools.values()), {}
        for pool, _ in pools:
            pool.shutdown(wait=False, cancel_futures=True)


class SwarmExecutor(_Counting):
    """The parallel plugin's warm process pool, fed through ``Swarm.submit``."""

    kind = "swarm"

    def __init__(self, swarm: Any = None) -> None:
        """A Training gets a pool of its own (sized like the default), not ``default_swarm()``.

        The default swarm is shared with ``/api/swarm`` and the dashboard; a Training run
        dispatched to it could queue behind their jobs and start on an older memory than
        the one it was dispatched with.  Alone on its pool, with at most one run per
        worker in flight, a dispatched run starts at once.
        """
        super().__init__()
        from server.parallel import swarm as swarm_module

        self._mod = swarm_module
        self._swarm = swarm if swarm is not None else swarm_module.Swarm()
        self._owned = True

    @property
    def swarm(self):
        return self._swarm

    @property
    def workers(self) -> int:
        return self.swarm.workers

    def submit(self, tasks: list[TrainingTask], meta: MetadataProvider) -> Future:
        run_tasks = [
            self._mod.RunTask(
                t.initial, t.modified, t.target, t.answer, t.seed, t.max_steps,
                parameters=t.parameters or None, backend=t.backend,
                memory=t.memory, fault=t.fault,
            )
            for t in tasks
        ]
        return self._track(self.swarm.submit(run_tasks, meta), len(tasks))

    def close(self) -> None:
        if self._owned and self._swarm is not None:
            self._swarm.shutdown(wait_for_tasks=False)  # the owner watchdog covers a kill


def swarm_available() -> bool:
    try:
        from server.parallel import swarm  # noqa: F401
    except ImportError:
        return False
    return True


def create_executor(kind: str | None = None):
    """The executor for this process: forced by *kind* or ``PETACAT_TRAINING_EXECUTOR``,
    else the swarm when the plugin imports, else the serial child."""
    kind = (kind or os.environ.get(ENV_EXECUTOR) or "").strip().lower() or None
    if kind not in (None, "serial", "swarm"):
        raise ValueError(f"{ENV_EXECUTOR} must be 'serial' or 'swarm', not {kind!r}")
    if kind == "swarm" or (kind is None and swarm_available()):
        if not swarm_available():
            raise RuntimeError("the swarm executor needs server/parallel/, which is absent")
        return SwarmExecutor()
    return SerialExecutor()
