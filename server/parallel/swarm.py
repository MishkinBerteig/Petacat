"""The swarm: run-level parallelism, a warm process pool over every core (WP2).

Research workloads are *many runs*: an answer distribution over seeds, the Metacat
oracle comparison, a parameter sweep, an episode corpus.  Each run is independent and
shares nothing, so the exact way to use a whole machine on them is to run one engine per
core.  Nothing about a run changes: a worker executes ``EngineRunner.run_mcat`` on the
same metadata with the same seed, and the outcome is **byte-for-byte the serial run's**
(``tests/parallel/test_swarm.py`` holds that, problem by problem and seed by seed).  That
is why this is the headline throughput path: roughly N-cores times the work, with zero
cognitive risk, where within-run parallelism has to work to stay faithful.

Design
------
* **A persistent pool, started ``forkserver``.**  ``fork`` is unsafe on macOS once the
  parent has threads, Objective-C or Metal state, and the API process has all three;
  ``spawn`` per task would pay an interpreter start-up and an engine import for every
  run.  A forkserver is a clean single-threaded process that imports the engine *once*
  (``set_forkserver_preload``) and forks a worker from that warm image, so a worker
  starts in tens of milliseconds and a task never starts a process.
* **Metadata is sent once.**  The pool is *bound* to one ``MetadataProvider`` (pickled
  and shipped through the worker initializer, keyed by ``hashing.config_hash``).  A call
  that brings a different configuration re-initialises the workers when the pool is idle;
  if the pool is busy with another caller's job, the new metadata rides along with each
  of that call's tasks instead and workers cache it by hash.  Either way a run only ever
  executes under the configuration the caller asked for.
* **Dynamic scheduling.**  Tasks are submitted individually (``chunksize`` 1 by default)
  and each worker takes the next when it finishes, so unequal cores (Super vs Performance,
  P vs E) and unequal runs (200 codelets vs 20,000) balance on their own.
* **Workers run at QoS ``USER_INITIATED``** (``server.parallel.qos``): not confined to the
  efficiency tier, and invisible to the arithmetic.
* **The numeric backend is per task**, resolved by the caller to a name so a worker never
  depends on its own environment.  ``mlx`` is accepted and measured, and is not the
  default: 17 processes share one GPU and every update pays a ~0.2 ms Metal dispatch
  against ~0.007 ms of CPU work (``scripts/bench_swarm.py`` records it).
* **The executor is per task** (``"serial"``, the faithful ``run_mcat``, by default).  A
  name registered in ``server.parallel`` (``"stream"``, ``"speculative"``...) is resolved
  in the worker and driven as ``get_executor(name)(runner, **options).run(max_steps)``.
  A swarm of within-run-parallel runs oversubscribes the cores unless ``workers`` is cut
  to match, which is the caller's call.

The Scheme has no analogue: Metacat is one run on one core.
"""

from __future__ import annotations

import atexit
import importlib.util
import multiprocessing
import os
import pickle
import threading
import time
import traceback
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

from server.engine import hardware
from server.engine.hashing import config_hash
from server.engine.metadata import MetadataProvider
from server.parallel import qos as _qos

#: Repository seed data: the default configuration of a swarm.
SEED_DIR = str(Path(__file__).resolve().parents[2] / "seed_data")

#: Modules the forkserver imports once, so every worker is forked warm.  ``mlx`` is
#: deliberately absent: Metal state must never be inherited through a fork.
PRELOAD = (
    "server.engine.metadata",
    "server.engine.runner",
    "server.engine.memory",
    "server.engine.hashing",
    "server.engine.numeric.backend",
    "server.parallel.swarm",
)

ANSWERLESS = frozenset({"*NONE*", "*CAP*"})

#: Executor names that mean "the faithful serial loop".
SERIAL_EXECUTORS = frozenset({None, "", "serial", "faithful"})


# ---------------------------------------------------------------------------
# Tasks and outcomes
# ---------------------------------------------------------------------------


@dataclass
class RunTask:
    """One run.  ``answer`` set means justification mode (``init_mcat(answer=...)``)."""

    initial: str
    modified: str
    target: str
    answer: str | None = None
    seed: int = 0
    max_steps: int = 20_000
    #: Per-run parameter overrides, applied exactly as ``EngineRunner.init_mcat`` does.
    parameters: dict[str, Any] | None = None
    #: Numeric backend name (``numpy``, ``off``, ``python``, ``mlx``...).  ``None`` takes
    #: the swarm's default (:func:`default_backend`).
    backend: str | None = None
    #: Executor name in the ``server.parallel`` registry; ``"serial"`` is ``run_mcat``.
    executor: str | None = "serial"
    executor_options: dict[str, Any] | None = None
    #: Caller's label, returned untouched on the outcome.
    tag: Any = None


@dataclass
class EpisodeTask:
    """Several runs sharing one ``EpisodicMemory``.

    Carried exactly as ``scripts/compare_to_metacat.py`` and ``studies/episodic-v1`` do:
    one memory object, run ``i`` seeded ``first_seed + i``, a fresh ``EngineRunner`` each
    time, ``init_mcat(..., memory=memory)``.  Memory only clears activations between runs
    (``run.ss:212``), so it cannot be inferred to be empty; a run counts as having
    *answered* only if it added an answer to the memory.
    """

    initial: str
    modified: str
    target: str
    first_seed: int = 0
    runs: int = 8
    answer: str | None = None
    max_steps: int = 20_000
    parameters: dict[str, Any] | None = None
    backend: str | None = None
    executor: str | None = "serial"
    executor_options: dict[str, Any] | None = None
    tag: Any = None


@dataclass
class RunOutcome:
    """What a run produced, small and picklable."""

    seed: int
    status: str
    #: The answer string on the Workspace at the end ("" if none).
    answer: str
    #: Every answer reported during the run, in order (``RunResult.answers``).
    answers: list[str]
    codelets: int
    seconds: float
    #: ``status:answer`` — the oracle's key (``population.stopping_state``).
    stopping_state: str
    temperature: float = 0.0
    #: Quality of the last answer reported to memory, when one was.
    answer_quality: float | None = None
    #: Position of the task in the call that submitted it.
    index: int = -1
    tag: Any = None
    #: A traceback summary when the run raised; the other fields are then empty.
    error: str | None = None
    worker_pid: int = 0

    def fingerprint(self) -> tuple:
        """The fields that must be identical to a serial run (not timing/pid/index)."""
        return (
            self.seed, self.status, self.answer, tuple(self.answers), self.codelets,
            self.stopping_state, self.temperature, self.answer_quality, self.error,
        )


@dataclass
class EpisodeOutcome:
    """An episode: its runs, and the oracle comparison's per-run states."""

    first_seed: int
    runs: list[RunOutcome]
    #: Per run, ``compare_to_metacat``'s state: the answer, ``*NONE*`` or ``*CAP*``.
    states: list[str]
    #: The last run's answer that is not ``*NONE*``/``*CAP*`` (``convergence_answer``).
    convergence: str | None
    #: Answers in the memory at the end.
    memory_answers: int
    seconds: float
    index: int = -1
    tag: Any = None
    error: str | None = None
    worker_pid: int = 0

    def fingerprint(self) -> tuple:
        return (
            self.first_seed, tuple(r.fingerprint() for r in self.runs), tuple(self.states),
            self.convergence, self.memory_answers, self.error,
        )


# ---------------------------------------------------------------------------
# Execution (shared by the workers and the in-process reference)
# ---------------------------------------------------------------------------


def default_backend(meta: MetadataProvider | None = None) -> str:
    """The numeric backend a swarm uses when a task names none.

    The fastest CPU backend that gives the serial run's result exactly.  ``server.parallel
    .placement`` (WP6) owns the measured policy; when it offers a swarm backend that is
    used.  Otherwise it is size-aware, as the engine's own ``auto`` policy is for the CPU
    tiers: below the vectorising threshold (512 Slipnet nodes) the engine's own loops
    (``off``) beat NumPy -- 59 nodes cost ~0.015 ms per update cycle on the reference
    loops and more through NumPy's marshalling -- and at or above it ``numpy`` (vectorised
    float64) wins.  The two agree run for run on the 200 runs the serial-corpus baselines (WP4's
    bit-identity corpus) record under both: identical stopping states and codelet counts.
    Never ``mlx``: float32 on one GPU shared by every worker, ~7x slower here.
    """
    nodes = len(meta.slipnet_node_specs) if meta is not None else 0
    try:
        from server.parallel import placement
    except ImportError:  # the policy module is optional
        placement = None
    if placement is not None:
        chosen = placement.swarm_backend(nodes)
        if chosen != "numpy" or importlib.util.find_spec("numpy") is not None:
            return chosen
    if importlib.util.find_spec("numpy") is None:
        return "off"
    from server.engine.numeric.backend import vectorise_threshold

    return "numpy" if nodes >= vectorise_threshold() else "off"


def _answer_text(runner) -> str:
    answer = runner.ctx.workspace.answer_string
    return answer.text if answer else ""


def _make_executor(runner, task):
    from server import parallel

    return parallel.get_executor(task.executor)(runner, **(task.executor_options or {}))


def _drive(runner, task) -> Any:
    """Run a prepared runner under the task's executor; returns its ``RunResult``-like."""
    if task.executor in SERIAL_EXECUTORS:
        return runner.run_mcat(max_steps=task.max_steps)
    return _make_executor(runner, task).run(task.max_steps)


def _outcome(runner, result, seed: int, started: float, memory_before: int | None = None) -> RunOutcome:
    ctx = runner.ctx
    answer = _answer_text(runner)
    quality = None
    answers = ctx.memory.answers if ctx is not None else []
    if answers and (memory_before is None or len(answers) > memory_before):
        quality = float(answers[0].quality)  # newest first
    reported = list(getattr(result, "answers", None) or getattr(runner, "_answers", []) or [])
    return RunOutcome(
        seed=seed,
        status=runner.status,
        answer=answer,
        answers=reported,
        codelets=ctx.codelet_count if ctx else 0,
        seconds=time.perf_counter() - started,
        stopping_state=f"{runner.status}:{answer}",
        temperature=float(ctx.temperature.value) if ctx else 0.0,
        answer_quality=quality,
        worker_pid=os.getpid(),
    )


def _failure(seed: int, started: float) -> RunOutcome:
    return RunOutcome(
        seed=seed, status="error", answer="", answers=[], codelets=0,
        seconds=time.perf_counter() - started, stopping_state="error:",
        error=traceback.format_exc(limit=6), worker_pid=os.getpid(),
    )


def run_one(task: RunTask, meta: MetadataProvider) -> RunOutcome:
    """Execute one run in this process.  The swarm's workers call exactly this, so the
    in-process result and the swarm's are the same code on the same inputs."""
    from server.engine.runner import EngineRunner

    started = time.perf_counter()
    try:
        runner = EngineRunner(meta)
        runner.init_mcat(
            task.initial, task.modified, task.target, task.answer,
            seed=task.seed, parameters=task.parameters or None,
        )
        result = _drive(runner, task)
        return _outcome(runner, result, task.seed, started)
    except Exception:  # noqa: BLE001 - one bad run must not sink a sweep
        return _failure(task.seed, started)


def run_episode(task: EpisodeTask, meta: MetadataProvider) -> EpisodeOutcome:
    """Execute one episode in this process (the swarm's workers call exactly this)."""
    from server.engine.memory import EpisodicMemory
    from server.engine.runner import STATUS_ANSWER_FOUND, EngineRunner

    started = time.perf_counter()
    memory = EpisodicMemory()
    outcomes: list[RunOutcome] = []
    states: list[str] = []
    try:
        for i in range(task.runs):
            t0 = time.perf_counter()
            before = len(memory.answers)
            runner = EngineRunner(meta)
            runner.init_mcat(
                task.initial, task.modified, task.target, task.answer,
                seed=task.first_seed + i, memory=memory, parameters=task.parameters or None,
            )
            result = _drive(runner, task)
            outcome = _outcome(runner, result, task.first_seed + i, t0, before)
            outcomes.append(outcome)
            answered = len(memory.answers) > before and runner.status == STATUS_ANSWER_FOUND
            if answered and runner.status == STATUS_ANSWER_FOUND:
                states.append(outcome.answer or "*NONE*")
            elif runner.ctx.codelet_count >= task.max_steps:
                states.append("*CAP*")
            else:
                states.append("*NONE*")
    except Exception:  # noqa: BLE001
        return EpisodeOutcome(
            first_seed=task.first_seed, runs=outcomes, states=states, convergence=None,
            memory_answers=len(memory.answers), seconds=time.perf_counter() - started,
            error=traceback.format_exc(limit=6), worker_pid=os.getpid(),
        )
    convergence = next((s for s in reversed(states) if s not in ANSWERLESS), None)
    return EpisodeOutcome(
        first_seed=task.first_seed, runs=outcomes, states=states, convergence=convergence,
        memory_answers=len(memory.answers), seconds=time.perf_counter() - started,
        worker_pid=os.getpid(),
    )


def _execute(task: RunTask | EpisodeTask, meta: MetadataProvider):
    return run_episode(task, meta) if isinstance(task, EpisodeTask) else run_one(task, meta)


def run_inprocess(
    task: RunTask | EpisodeTask, meta: MetadataProvider | None = None, backend: str | None = None
):
    """The serial reference: *task* executed in this process, on *task*'s backend.

    The backend is scoped (restored afterwards), so a test or script can call this
    between swarm calls without disturbing its own numeric policy.
    """
    from server.engine.numeric.backend import use_backend

    meta = meta or MetadataProvider.from_seed_data(SEED_DIR)
    name = task.backend or backend or default_backend(meta)
    with use_backend(name):
        return _execute(task, meta)


# ---------------------------------------------------------------------------
# Worker side
# ---------------------------------------------------------------------------

_W_META: MetadataProvider | None = None
_W_HASH: str = ""
_W_CACHE: dict[str, MetadataProvider] = {}
_W_BACKEND: str | None = None
_W_QOS: _qos.QosResult | None = None
_W_QOS_ON = False
_W_THREAD: Any = None
#: Stack for the worker's run thread.  A secondary thread gets a small default stack on
#: macOS (512 KB) where the main thread gets 8 MB; the engine recurses, so ask for more.
_W_STACK_BYTES = 64 * 1024 * 1024
_W_CACHE_LIMIT = 4


def _worker_init(meta_blob: bytes, cfg_hash: str, qos_on: bool) -> None:
    """Pool initializer: receive the bound metadata once, and take a QoS class."""
    global _W_META, _W_HASH, _W_QOS, _W_QOS_ON
    for name in ("OMP_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ.setdefault(name, "1")  # one engine per core; no BLAS fan-out under it
    _W_META = pickle.loads(meta_blob)
    _W_HASH = cfg_hash
    _W_QOS = None
    _W_QOS_ON = qos_on


def _worker_meta(cfg_hash: str, payload: bytes | None) -> MetadataProvider:
    if cfg_hash == _W_HASH and _W_META is not None:
        return _W_META
    cached = _W_CACHE.get(cfg_hash)
    if cached is not None:
        return cached
    if payload is None:
        raise RuntimeError(f"worker has no metadata for config {cfg_hash} and none was sent")
    meta = pickle.loads(payload)
    if len(_W_CACHE) >= _W_CACHE_LIMIT:
        _W_CACHE.pop(next(iter(_W_CACHE)))
    _W_CACHE[cfg_hash] = meta
    return meta


def _set_backend(name: str) -> None:
    """Make *name* the numeric backend here, only when it changes (resetting the policy
    cache costs a lookup; the common case is one backend for a whole sweep)."""
    global _W_BACKEND
    if name == _W_BACKEND:
        return
    from server.engine.numeric.backend import ENV_BACKEND, reset_backend_cache

    os.environ[ENV_BACKEND] = name
    reset_backend_cache()
    _W_BACKEND = name


def _qos_thread_init() -> None:
    global _W_QOS
    _W_QOS = _qos.set_worker_qos()


def _worker_run(batch: list, cfg_hash: str, payload: bytes | None) -> list:
    """Run a batch on this worker's dedicated thread.

    ``pthread_set_qos_class_self_np`` is refused (EPERM) on a forked process's initial
    thread, so the engine runs on a thread of its own that takes the QoS class.  The
    hand-off costs microseconds against runs of tens of milliseconds.
    """
    global _W_THREAD
    if not _W_QOS_ON:
        return _worker_run_here(batch, cfg_hash, payload)
    if _W_THREAD is None:
        from concurrent.futures import ThreadPoolExecutor

        previous = threading.stack_size(_W_STACK_BYTES)
        try:
            _W_THREAD = ThreadPoolExecutor(1, initializer=_qos_thread_init)
            _W_THREAD.submit(lambda: None).result()  # start the thread at this stack size
        finally:
            threading.stack_size(previous)
    return _W_THREAD.submit(_worker_run_here, batch, cfg_hash, payload).result()


def _worker_run_here(batch: list, cfg_hash: str, payload: bytes | None) -> list:
    meta = _worker_meta(cfg_hash, payload)
    out = []
    for index, task in batch:
        _set_backend(task.backend or "off")
        result = _execute(task, meta)
        result.index = index
        result.tag = task.tag
        out.append(result)
    return out


def _warm_batch() -> list:
    """A short run so the engine's lazy imports and first-call costs are paid at start-up."""
    task = RunTask("abc", "abd", "ijk", seed=1, max_steps=60, backend="off")
    return [(0, task)]


def _worker_probe(delay: float, warm: bool = False) -> dict:
    """Describe this worker; the sleep makes concurrent probes land on distinct workers."""
    time.sleep(delay)
    if warm and _W_META is not None:
        _worker_run(_warm_batch(), _W_HASH, None)
    if _W_QOS_ON and _W_THREAD is None:
        _worker_run([], _W_HASH, None)  # make sure the QoS thread exists
    qos_name = _W_THREAD.submit(_qos.current_thread_qos).result() if _W_THREAD else None
    return {
        "pid": os.getpid(),
        "config_hash": _W_HASH,
        "cached_configs": sorted(_W_CACHE),
        "backend": _W_BACKEND,
        "qos": _qos.QOS_NAMES.get(qos_name or 0),
        "qos_applied": _W_QOS.applied if _W_QOS else None,
        "qos_detail": _W_QOS.detail if _W_QOS else "",
    }


# ---------------------------------------------------------------------------
# The pool
# ---------------------------------------------------------------------------


class SwarmError(RuntimeError):
    pass


class Swarm:
    """A persistent, warm process pool that executes runs and episodes exactly.

    Thread-safe: several threads (or ``asyncio.to_thread`` callers) may use one swarm at
    once; their tasks interleave on the same workers.

    ``workers`` defaults to :func:`server.engine.hardware.population_worker_count` — every
    logical core but one, efficiency cores included, because runs share nothing and the
    reserved core leaves the parent and the OS somewhere to run.
    """

    def __init__(
        self,
        workers: int | None = None,
        meta: MetadataProvider | None = None,
        seed_dir: str | None = None,
        backend: str | None = None,
        qos: bool = True,
    ) -> None:
        self.workers = max(1, workers or hardware.population_worker_count())
        self._backend = backend
        self._qos_on = qos
        self._seed_dir = seed_dir or SEED_DIR
        self._bound_meta: MetadataProvider | None = meta
        self._bound_hash: str = ""
        self._blob: bytes = b""
        self._executor: ProcessPoolExecutor | None = None
        self._lock = threading.RLock()
        self._inflight = 0
        self._closed = False
        #: Start-up and traffic figures for ``status()``.
        self.started_seconds: float | None = None
        self.rebinds = 0
        self.tasks_run = 0

    @property
    def backend(self) -> str:
        """The backend tasks without one get: the constructor's, else the policy for the
        bound configuration (:func:`default_backend`)."""
        return self._backend or default_backend(self._bound_meta)

    # -- life cycle -------------------------------------------------------

    def _context(self):
        ctx = multiprocessing.get_context("forkserver")
        try:
            ctx.set_forkserver_preload(list(PRELOAD))
        except Exception:  # noqa: BLE001 - already-running forkserver keeps its preload
            pass
        return ctx

    def _bind(self, meta: MetadataProvider | None) -> None:
        """Make *meta* (or the seed data) this pool's configuration.  Lock held."""
        if meta is None:
            meta = self._bound_meta or MetadataProvider.from_seed_data(self._seed_dir)
        self._bound_meta = meta
        self._bound_hash = config_hash(meta)
        self._blob = pickle.dumps(meta, protocol=pickle.HIGHEST_PROTOCOL)

    def _start(self) -> ProcessPoolExecutor:
        """Create the pool and fork every worker.  Lock held."""
        if self._closed:
            raise SwarmError("swarm is shut down")
        if self._bound_hash == "":
            self._bind(None)
        began = time.perf_counter()
        executor = ProcessPoolExecutor(
            max_workers=self.workers,
            mp_context=self._context(),
            initializer=_worker_init,
            initargs=(self._blob, self._bound_hash, self._qos_on),
        )
        # ProcessPoolExecutor starts workers on demand under forkserver; slow probes
        # held concurrently force all of them up now, so the first real task is not
        # charged for start-up and the start-up itself is measurable.
        if self.workers > 1:
            wait([executor.submit(_worker_probe, 0.05, True) for _ in range(self.workers)])
        else:
            executor.submit(_worker_probe, 0.0, True).result()
        self.started_seconds = time.perf_counter() - began
        self._executor = executor
        return executor

    def start(self) -> "Swarm":
        """Start the workers now (otherwise the first call does)."""
        with self._lock:
            if self._executor is None:
                self._start()
        return self

    def shutdown(self, wait_for_tasks: bool = True) -> None:
        """Stop the workers.  Idempotent; the swarm cannot be used afterwards."""
        with self._lock:
            self._closed = True
            executor, self._executor = self._executor, None
        if executor is not None:
            executor.shutdown(wait=wait_for_tasks, cancel_futures=not wait_for_tasks)

    close = shutdown

    def __enter__(self) -> "Swarm":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.shutdown()

    def _drop_pool(self) -> None:
        with self._lock:
            executor, self._executor = self._executor, None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)

    # -- configuration ----------------------------------------------------

    def configure(self, meta: MetadataProvider | None) -> bool:
        """Re-initialise the workers with *meta* if its config hash differs.

        Returns whether workers were re-initialised.  Waits for nothing: callers that
        want to change the pool's configuration while jobs are in flight should expect
        those jobs to finish on the old workers first (``shutdown(wait=True)``).
        """
        with self._lock:
            if meta is None or (self._bound_hash and config_hash(meta) == self._bound_hash):
                return False
            old, self._executor = self._executor, None
            self._bind(meta)
            self.rebinds += 1
        if old is not None:
            old.shutdown(wait=True)
        self.start()
        return True

    def config_hash(self) -> str:
        return self._bound_hash

    # -- job plumbing -----------------------------------------------------

    def _acquire(self, meta: MetadataProvider | None) -> tuple[ProcessPoolExecutor, str, bytes | None]:
        """Pick the pool and metadata route for one job; counts it in flight."""
        with self._lock:
            if self._closed:
                raise SwarmError("swarm is shut down")
            payload: bytes | None = None
            cfg = self._bound_hash
            if meta is not None:
                cfg = config_hash(meta)
                if self._bound_hash and cfg != self._bound_hash:
                    if self._inflight == 0:
                        # Idle: re-initialise the workers with the new configuration.
                        old, self._executor = self._executor, None
                        self._bind(meta)
                        self.rebinds += 1
                        if old is not None:
                            old.shutdown(wait=True)
                    else:
                        payload = pickle.dumps(meta, protocol=pickle.HIGHEST_PROTOCOL)
                elif not self._bound_hash:
                    self._bind(meta)
            if self._executor is None or getattr(self._executor, "_broken", False):
                if self._executor is not None:
                    self._executor.shutdown(wait=False, cancel_futures=True)
                    self._executor = None
                self._start()
            if meta is None:
                # A fresh pool binds the seed data in ``_start``; the tasks must name
                # that configuration, not the empty hash read before it existed.
                cfg = self._bound_hash
            self._inflight += 1
            return self._executor, cfg, payload

    def _release(self) -> None:
        with self._lock:
            self._inflight -= 1

    def _prepare(
        self, tasks: Iterable[RunTask | EpisodeTask], meta: MetadataProvider | None
    ) -> Iterator[tuple[int, Any]]:
        fallback = self._backend or default_backend(meta or self._bound_meta)
        for index, task in enumerate(tasks):
            if task.backend is None:
                task = _with_backend(task, fallback)
            yield index, task

    # -- the executor interface --------------------------------------------

    def imap_unordered(
        self,
        tasks: Iterable[RunTask | EpisodeTask],
        meta: MetadataProvider | None = None,
        chunksize: int = 1,
        window: int | None = None,
    ) -> Iterator[RunOutcome | EpisodeOutcome]:
        """Yield outcomes as they finish.  ``outcome.index`` is the task's position.

        At most ``window`` (default ``4 x workers``) tasks are in flight, so a lazy
        generator of a million tasks is not materialised.
        """
        executor, cfg, payload = self._acquire(meta)
        window = window or self.workers * 4
        chunksize = max(1, int(chunksize))
        pending: set[Future] = set()
        source = self._prepare(tasks, meta)
        exhausted = False
        try:
            while True:
                while not exhausted and len(pending) < window:
                    batch = []
                    for item in source:
                        batch.append(item)
                        if len(batch) >= chunksize:
                            break
                    if not batch:
                        exhausted = True
                        break
                    pending.add(executor.submit(_worker_run, batch, cfg, payload))
                if not pending:
                    return
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    for outcome in future.result():
                        self.tasks_run += 1
                        yield outcome
        except BrokenProcessPool:
            self._drop_pool()
            raise
        finally:
            for future in pending:
                future.cancel()
            self._release()

    def map(
        self,
        tasks: Iterable[RunTask | EpisodeTask],
        meta: MetadataProvider | None = None,
        chunksize: int = 1,
    ) -> list[RunOutcome | EpisodeOutcome]:
        """Outcomes in task order."""
        results: dict[int, Any] = {}
        for outcome in self.imap_unordered(tasks, meta=meta, chunksize=chunksize):
            results[outcome.index] = outcome
        return [results[i] for i in range(len(results))]

    def run(self, task: RunTask | EpisodeTask, meta: MetadataProvider | None = None):
        """One task, on whichever worker is free."""
        return self.map([task], meta=meta)[0]

    async def amap(self, tasks, meta: MetadataProvider | None = None, chunksize: int = 1):
        """``map`` for asyncio callers (the API): runs off the event loop's thread."""
        import asyncio

        return await asyncio.to_thread(self.map, list(tasks), meta, chunksize)

    def run_seeds(
        self,
        initial: str,
        modified: str,
        target: str,
        seeds: Sequence[int],
        answer: str | None = None,
        max_steps: int = 20_000,
        parameters: dict[str, Any] | None = None,
        backend: str | None = None,
        meta: MetadataProvider | None = None,
        executor: str = "serial",
    ) -> list[RunOutcome]:
        """The common case: one problem over many seeds, in seed order."""
        return self.map(
            (
                RunTask(initial, modified, target, answer, int(s), max_steps, parameters,
                        backend, executor)
                for s in seeds
            ),
            meta=meta,
        )

    # -- introspection ------------------------------------------------------

    def worker_info(self) -> list[dict]:
        """One probe per worker (pid, config hash, backend, QoS actually in force)."""
        executor, _, _ = self._acquire(None)
        try:
            futures = [executor.submit(_worker_probe, 0.05) for _ in range(self.workers)]
            seen: dict[int, dict] = {}
            for f in futures:
                info = f.result()
                seen[info["pid"]] = info
            return sorted(seen.values(), key=lambda d: d["pid"])
        finally:
            self._release()

    def status(self) -> dict:
        """Pool state for ``GET /api/swarm`` — cheap, never starts the pool."""
        with self._lock:
            return {
                "started": self._executor is not None,
                "closed": self._closed,
                "workers": self.workers,
                "start_method": "forkserver",
                "default_backend": self.backend,
                "config_hash": self._bound_hash or None,
                "inflight_jobs": self._inflight,
                "tasks_run": self.tasks_run,
                "rebinds": self.rebinds,
                "startup_seconds": self.started_seconds,
                "qos": self._qos_on and _qos.available(),
            }


def _with_backend(task, backend: str):
    from dataclasses import replace

    return replace(task, backend=backend)


# ---------------------------------------------------------------------------
# The module-level default swarm
# ---------------------------------------------------------------------------

_DEFAULT: Swarm | None = None
_DEFAULT_LOCK = threading.Lock()


def default_swarm() -> Swarm:
    """The shared swarm, created lazily on first use (workers start on first task)."""
    global _DEFAULT
    with _DEFAULT_LOCK:
        if _DEFAULT is None or _DEFAULT._closed:
            _DEFAULT = Swarm()
        return _DEFAULT


def shutdown_default() -> None:
    """Stop the default swarm, if one was created."""
    global _DEFAULT
    with _DEFAULT_LOCK:
        swarm, _DEFAULT = _DEFAULT, None
    if swarm is not None:
        swarm.shutdown()


def default_swarm_status() -> dict:
    """Status of the default swarm without creating it."""
    with _DEFAULT_LOCK:
        swarm = _DEFAULT
    if swarm is None:
        return {
            "started": False, "closed": False,
            "workers": hardware.population_worker_count(), "start_method": "forkserver",
            "default_backend": default_backend(), "config_hash": None, "inflight_jobs": 0,
            "tasks_run": 0, "rebinds": 0, "startup_seconds": None, "qos": _qos.available(),
        }
    return swarm.status()


atexit.register(shutdown_default)
