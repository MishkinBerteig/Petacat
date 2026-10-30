"""Trainings: named, long-lived, database-backed episodes of many problems over many seeds.

A Training holds letter-string problems.  Each problem runs over a number of seeds on every
core, and problems can be inserted into a Training while it runs (start with 25, add 5 more
whenever problems finish).  It is the mode a future ML layer drives.

Exactness
---------
Every run is the serial ``EngineRunner.run_mcat`` run with that seed, built by
``training_executor`` exactly as ``swarm.run_one`` builds it.  Which executor ran it (the
parallel plugin's process pool, or the single child process used when the plugin is
detached) cannot change its outcome.  The engine is untouched; each run builds its own
Workspace as any run does.

The episode memory
------------------
With ``memory = 'shared'`` a Training owns one :class:`EpisodicMemory`
(``training_memory.py``).  A run starts from a copy of it at the version current when the
run is dispatched and keeps that copy static; when the run finishes, its additions are
merged into the master (presence-checked), bumping the version.  A run records the
``memory_version`` it started with and its merge order ``seq``.  Only runs dispatched after
a merge see it.  Dispatch keeps at most one run per worker in flight in shared mode, so
with one worker each run starts after the previous one merged: Metacat's serial episode.
``memory = 'independent'`` gives every run a fresh memory.

The database is written only at milestones
------------------------------------------
* a Training is created or renamed, problems are added, its status or policy changes;
* **a problem finishes all its seeds (or is cancelled)**: in one transaction, that problem's
  summary, *every run committed since the last write from any problem*, and the memory
  merges since the last write.

Progress inside a problem lives in memory and the API reports it from there.  The stored
problem status is ``queued | finished | cancelled``; ``running`` is live-only.  On startup
the memory is rebuilt from the stored merges, each queued problem resumes at the seeds it
has not stored, and anything after the last milestone is redone.

The scheduler
-------------
One asyncio task keeps the executor fed from the problems of every active Training: seeds
of problems already started first (so they finish steadily), then the oldest queued
problem, round-robin across Trainings so a huge one cannot starve a small one.  Inserting
a problem wakes it.

Configuration and errors
------------------------
A Training runs under the ``MetadataProvider`` current at creation.  If the current
configuration's ``config_hash`` differs, ``on_config_change`` decides: ``pause`` (the
Training is ``stalled`` until the configuration returns) or ``adopt`` (continue under the
new one; each run records its ``config_hash``).  The rest of the error policy
(``on_run_error``, ``max_errors_*``, ``on_worker_failure``, ``max_retries``) acts as the
API contract says and writes a human sentence to ``last_event``.
"""

from __future__ import annotations

import asyncio
import logging
import pickle
import re
import time
import uuid
from collections import Counter, deque
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from server.engine.hashing import config_hash
from server.engine.memory import EpisodicMemory
from server.engine.metadata import MetadataProvider
from server.engine.parameters import UnknownParameter, validate_overrides
from server.models.training import Training, TrainingMemoryMerge, TrainingProblem, TrainingRun
from server.services import training_memory as tm
from server.services.training_executor import (
    TrainingTask,
    available_backend_names,
    create_executor,
    default_training_backend,
)

logger = logging.getLogger("petacat.training")

NONE_KEY = "*NONE*"
CAP_KEY = "*CAP*"
ERROR_KEY = "*ERROR*"
MAX_PROBLEMS_PER_REQUEST = 10_000
MAX_SEEDS_PER_PROBLEM = 100_000
MAX_CODELETS_LIMIT = 200_000
LETTERS = re.compile(r"^[A-Za-z]{1,64}$")
RATE_WINDOW = 30.0
INSERT_CHUNK = 2000
RUN_ROW_CHUNK = 2000
#: Merge blobs the scheduler keeps for task tails.
MERGE_KEEP = 1024
INT32_MAX = 2_147_483_647

DEFAULT_POLICY: dict[str, Any] = {
    "on_run_error": "record",
    "max_errors_per_problem": None,
    "max_errors_total": None,
    "on_worker_failure": "retry",
    "max_retries": 3,
    "on_config_change": "pause",
}
_POLICY_CHOICES = {
    "on_run_error": ("record", "skip_problem", "pause", "cancel"),
    "on_worker_failure": ("retry", "pause"),
    "on_config_change": ("pause", "adopt"),
}
_SETTINGS_KEYS = ("memory", "seeds_per_problem", "seed_start", "max_codelets", "parameters", "backend")


class _Skip(Exception):
    pass


class TrainingError(Exception):
    """An error with an HTTP meaning (the API turns it into an HTTPException)."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def normalize_policy(partial: dict | None, base: dict | None = None) -> dict[str, Any]:
    """Merge a partial policy onto *base* (defaults), validating every value (400)."""
    policy = dict(base or DEFAULT_POLICY)
    for key, value in (partial or {}).items():
        if key not in DEFAULT_POLICY:
            raise TrainingError(400, f"unknown policy field {key!r}; known: {sorted(DEFAULT_POLICY)}")
        if key in _POLICY_CHOICES:
            if value not in _POLICY_CHOICES[key]:
                raise TrainingError(400, f"policy {key} must be one of {list(_POLICY_CHOICES[key])}")
        elif key == "max_retries":
            if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 1000:
                raise TrainingError(400, "policy max_retries must be an integer 0..1000")
        else:  # max_errors_*
            if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 1):
                raise TrainingError(400, f"policy {key} must be null or an integer >= 1")
        policy[key] = value
    return policy


def run_key(o: Any, max_codelets: int) -> str:
    """The outcome key: the answer, else ``*ERROR*`` / ``*CAP*`` / ``*NONE*``."""
    if o.error:
        return ERROR_KEY
    if o.status == "answer_found" and o.answer:
        return o.answer
    if o.codelets >= max_codelets:
        return CAP_KEY
    return NONE_KEY


@dataclass
class RunRec:
    """A completed run with everything the API reports about it."""

    seed: int
    status: str
    key: str
    answer: str
    answers: list
    codelets: int
    seconds: float
    temperature: float
    answer_quality: float | None
    error: str | None
    config_hash: str
    attempts: int = 1
    seq: int | None = None
    memory_version: int | None = None
    added_answers: int | None = None
    added_snags: int | None = None
    problem_id: int = 0


def summarize(recs: list[RunRec]) -> dict[str, Any]:
    """Tally a problem's runs (seed order in, deterministic out)."""
    recs = sorted(recs, key=lambda r: r.seed)
    n = len(recs)
    counts: Counter[str] = Counter()
    q_sum: dict[str, float] = {}
    q_n: dict[str, int] = {}
    statuses: Counter[str] = Counter()
    errors = codelets = retries = 0
    first_error = None
    for r in recs:
        counts[r.key] += 1
        statuses[r.status] += 1
        codelets += r.codelets
        retries += max(r.attempts - 1, 0)
        if r.error:
            errors += 1
            first_error = first_error or r.error
        if r.answer_quality is not None and r.key not in (NONE_KEY, CAP_KEY, ERROR_KEY):
            q_sum[r.key] = q_sum.get(r.key, 0.0) + r.answer_quality
            q_n[r.key] = q_n.get(r.key, 0) + 1
    ranked = counts.most_common()
    return {
        "runs_done": n,
        "errors": errors,
        "capped": counts.get(CAP_KEY, 0),
        "retries": retries,
        "codelets_total": codelets,
        "mean_codelets": (codelets / n) if n else None,
        "top_answer": ranked[0][0] if ranked else None,
        "top_fraction": (ranked[0][1] / n) if n else None,
        "none_fraction": (counts.get(NONE_KEY, 0) / n) if n else None,
        "distinct_answers": len(ranked),
        "distribution": [
            {"answer": a, "count": c, "quality_sum": q_sum.get(a, 0.0), "quality_n": q_n.get(a, 0)}
            for a, c in ranked
        ],
        "statuses": dict(statuses),
        "first_error": first_error,
    }


def _shares(distribution: list[dict] | None, runs_done: int, limit: int | None) -> list[dict]:
    out = []
    for d in (distribution or [])[:limit]:
        qn = d.get("quality_n") or 0
        out.append({
            "answer": d["answer"], "count": d["count"],
            "fraction": (d["count"] / runs_done) if runs_done else 0.0,
            "mean_quality": (d["quality_sum"] / qn) if qn else None,
        })
    return out


# ---------------------------------------------------------------------------
# Live (in-memory) state
# ---------------------------------------------------------------------------


@dataclass
class LiveProblem:
    id: int
    training_id: int
    initial: str
    modified: str
    target: str
    answer: str | None
    seeds: int
    seed_start: int
    #: Seeds not yet dispatched (a failed one goes back on the front).
    todo: deque = field(default_factory=deque)
    inflight: int = 0
    outcomes: dict[int, RunRec] = field(default_factory=dict)
    #: Failed attempts per seed (worker failures), for ``max_retries``.
    failures: dict[int, int] = field(default_factory=dict)
    started_at: datetime | None = None
    cancelled: bool = False
    finishing: bool = False
    written: asyncio.Event | None = None

    @property
    def started(self) -> bool:
        return self.started_at is not None


@dataclass
class Sub:
    """One dispatched run."""

    lt: "LiveTraining"
    lp: LiveProblem
    seed: int
    version: int | None
    config_hash: str
    failures: int
    #: Re-run alone after a pool break (see ``_worker_failed``).
    isolated: bool = False


@dataclass
class LiveTraining:
    id: int
    status: str
    memory_mode: str
    seeds_per_problem: int
    seed_start: int
    max_codelets: int
    parameters: dict | None
    backend: str
    policy: dict
    config_hash: str
    meta: MetadataProvider | None
    closed: bool = False
    stalled_reason: str | None = None
    last_event: str | None = None
    queue: deque = field(default_factory=deque)        # LiveProblem not yet started
    active: dict = field(default_factory=dict)         # pid -> LiveProblem, started and unwritten
    problems: dict = field(default_factory=dict)       # pid -> LiveProblem, every unwritten one
    unsubmitted: int = 0
    completions: deque = field(default_factory=deque)
    cancelled: bool = False
    errors_total: int = 0
    # -- the episode memory (shared mode) --
    memory: EpisodicMemory | None = None
    version: int = 0
    epoch: str = field(default_factory=lambda: uuid.uuid4().hex)
    merge_blobs: dict = field(default_factory=dict)    # seq -> pickled Additions
    snapshot: tuple | None = None                      # (version, blob)
    pending_runs: list = field(default_factory=list)   # RunRec committed in memory, not in the DB
    pending_merges: list = field(default_factory=list) # (seq, problem_id, seed, Additions)
    want_snapshot: set = field(default_factory=set)    # (pid, seed) whose worker needs one

    @property
    def shared(self) -> bool:
        return self.memory_mode == "shared"

    @property
    def schedulable(self) -> bool:
        return (
            self.meta is not None and not self.cancelled and self.stalled_reason is None
            and self.status in ("open", "closed")
        )

    def next_problem(self) -> LiveProblem | None:
        for lp in self.active.values():
            if not lp.cancelled and lp.todo:
                return lp
        while self.queue:
            lp = self.queue.popleft()
            if lp.cancelled or not lp.todo:
                continue
            lp.started_at = _utcnow()
            self.active[lp.id] = lp
            return lp
        return None

    def note_completion(self) -> None:
        now = time.monotonic()
        self.completions.append(now)
        self._prune(now)

    def _prune(self, now: float) -> None:
        while self.completions and now - self.completions[0] > RATE_WINDOW:
            self.completions.popleft()

    def rate(self) -> float | None:
        now = time.monotonic()
        self._prune(now)
        if len(self.completions) < 2:
            return None
        span = now - self.completions[0]
        return len(self.completions) / span if span > 0 else None

    def memory_ref(self, tail_depth: int, snapshot: bool) -> tm.MemoryRef:
        """The memory a run dispatched now starts from."""
        ref = tm.MemoryRef(self.id, self.epoch, self.version)
        if snapshot:
            if self.snapshot is None or self.snapshot[0] != self.version:
                self.snapshot = (self.version, tm.snapshot_blob(self.memory))
            ref.snapshot = self.snapshot[1]
            return ref
        ref.tail_from = max(0, self.version - tail_depth)
        ref.tail = [self.merge_blobs[v] for v in range(ref.tail_from + 1, self.version + 1)]
        return ref


# ---------------------------------------------------------------------------
# The service
# ---------------------------------------------------------------------------


class TrainingService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        meta_provider: Callable[[], MetadataProvider],
        executor: Any = None,
    ) -> None:
        self._factory = session_factory
        self._meta_provider = meta_provider
        self._executor = executor
        self._live: dict[int, LiveTraining] = {}
        self._rr = 0
        self._inflight_runs = 0
        #: Runs to re-run one at a time after a pool break: (training, problem, seed).
        self._isolation: deque = deque()
        self._isolated_inflight = 0
        #: Completed futures handed over by the executor's threads, merged by ``_drain``.
        self._done_queue: deque = deque()
        self._status_locks: dict[int, asyncio.Lock] = {}
        self._wake: asyncio.Event | None = None
        self._task: asyncio.Task | None = None
        self._tasks: set[asyncio.Task] = set()
        self._write_lock: asyncio.Lock | None = None
        self._versions: dict[int, int] = {}
        self._conds: dict[int, asyncio.Condition] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stopped = True
        self._hashes: tuple[MetadataProvider, str] | None = None
        #: Test hook: ``(problem, seed, failures) -> "error" | "kill" | None``.
        self.fault_hook: Callable[[LiveProblem, int, int], str | None] | None = None
        #: Bytes of memory shipped with tasks (sum, count), for the overhead measurement.
        self.task_memory_bytes = [0, 0]

    # -- life cycle ---------------------------------------------------------

    @property
    def executor(self):
        return self._executor

    async def start(self) -> None:
        """Load the live Trainings and start the scheduler."""
        self._loop = asyncio.get_running_loop()
        self._wake = asyncio.Event()
        self._write_lock = asyncio.Lock()
        if self._executor is None:
            self._executor = create_executor()
        self._stopped = False
        await self._load()
        self._task = asyncio.create_task(self._run(), name="training-scheduler")
        self._wake.set()

    async def stop(self) -> None:
        """Stop scheduling.  Progress after the last milestone is dropped; unfinished
        problems resume from their stored seeds on the next start."""
        self._stopped = True
        tasks = [t for t in [self._task, *self._tasks] if t is not None]
        for t in tasks:
            t.cancel()
        for t in tasks:
            try:
                await t
            except BaseException:  # noqa: BLE001 - cancellation and anything it surfaces
                pass
        self._task = None
        self._tasks.clear()
        self._live.clear()
        if self._executor is not None:
            self._executor.close()

    def _config_hash(self, meta: MetadataProvider) -> str:
        cached = self._hashes
        if cached is None or cached[0] is not meta:
            cached = self._hashes = (meta, config_hash(meta))
        return cached[1]

    def _new_live(self, t: Training, meta: MetadataProvider | None) -> LiveTraining:
        lt = LiveTraining(
            id=t.id, status=t.status, memory_mode=t.memory,
            seeds_per_problem=t.seeds_per_problem, seed_start=t.seed_start,
            max_codelets=t.max_codelets, parameters=t.parameters, backend=t.backend,
            policy=normalize_policy(t.policy), config_hash=t.config_hash, meta=meta,
            closed=t.closed_at is not None, last_event=t.last_event,
        )
        if lt.shared:
            lt.memory = EpisodicMemory()
        return lt

    def _enqueue(self, lt: LiveTraining, p: Any, stored: dict[int, RunRec] | None = None) -> LiveProblem:
        lp = LiveProblem(
            id=p.id, training_id=lt.id, initial=p.initial, modified=p.modified, target=p.target,
            answer=p.answer, seeds=p.seeds, seed_start=p.seed_start,
        )
        if stored:
            lp.outcomes.update(stored)
        lp.todo = deque(
            s for s in range(p.seed_start, p.seed_start + p.seeds) if s not in lp.outcomes
        )
        lt.queue.append(lp)
        lt.problems[lp.id] = lp
        lt.unsubmitted += len(lp.todo)
        return lp

    async def _load(self) -> None:
        resumed: list[tuple[LiveTraining, LiveProblem]] = []
        async with self._factory() as s:
            trainings = (await s.execute(
                select(Training).where(Training.status != "cancelled").order_by(Training.id)
            )).scalars().all()
            for t in trainings:
                lt = self._new_live(t, None)
                if lt.shared:
                    merges = (await s.execute(
                        select(TrainingMemoryMerge).where(TrainingMemoryMerge.training_id == t.id)
                        .order_by(TrainingMemoryMerge.seq)
                    )).scalars().all()
                    for m in merges:
                        adds = tm.decode_additions(m.answers, m.snags)
                        tm.apply_merge(lt.memory, adds)
                        lt.version = m.seq
                        lt.merge_blobs[m.seq] = tm.dump_additions(adds)
                    if lt.version != len(merges):
                        logger.warning("training %d: merge log has gaps (%d merges, version %d)",
                                       t.id, len(merges), lt.version)
                    for k in sorted(lt.merge_blobs)[:-MERGE_KEEP]:
                        del lt.merge_blobs[k]
                problems = (await s.execute(
                    select(TrainingProblem).where(
                        TrainingProblem.training_id == t.id, TrainingProblem.status == "queued"
                    ).order_by(TrainingProblem.id)
                )).scalars().all()
                stored: dict[int, dict[int, RunRec]] = {}
                if problems:
                    runs = (await s.execute(
                        select(TrainingRun).join(TrainingProblem, TrainingProblem.id == TrainingRun.problem_id)
                        .where(TrainingRun.training_id == t.id, TrainingProblem.status == "queued")
                    )).scalars().all()
                    for r in runs:
                        stored.setdefault(r.problem_id, {})[r.seed] = self._rec_from_row(r)
                for p in problems:
                    lp = self._enqueue(lt, p, stored.get(p.id))
                    lt.errors_total += sum(1 for r in lp.outcomes.values() if r.error)
                    if not lp.todo and lp.inflight == 0:
                        resumed.append((lt, lp))
                lt.errors_total += int((await s.execute(
                    select(func.coalesce(func.sum(TrainingProblem.errors), 0)).where(
                        TrainingProblem.training_id == t.id, TrainingProblem.status != "queued")
                )).scalar_one())
                self._live[t.id] = lt
        self._check_configs(initial=True)
        for lt, lp in resumed:  # every seed was stored but the problem's own write was not
            lt.active[lp.id] = lp
            lp.started_at = lp.started_at or _utcnow()
            self._begin_finish(lt, lp)

    @staticmethod
    def _rec_from_row(r: Any) -> RunRec:
        return RunRec(
            seed=r.seed, status=r.status, key=r.key, answer=r.answer, answers=list(r.answers or []),
            codelets=r.codelets, seconds=r.seconds, temperature=r.temperature,
            answer_quality=r.answer_quality, error=r.error, config_hash=r.config_hash,
            attempts=r.attempts, seq=r.seq, memory_version=r.memory_version,
            added_answers=r.added_answers, added_snags=r.added_snags, problem_id=r.problem_id,
        )

    def wake(self) -> None:
        if self._wake is not None:
            self._wake.set()

    # -- configuration policy -----------------------------------------------

    def _check_configs(self, initial: bool = False) -> None:
        """Apply ``on_config_change``: stall, adopt, or resume when the configuration returns."""
        current = self._meta_provider()
        h = self._config_hash(current)
        for lt in self._live.values():
            if lt.cancelled:
                continue
            if h == lt.config_hash:
                lt.meta = current
                if lt.stalled_reason is not None:
                    lt.stalled_reason = None
                    lt.last_event = "resumed: the engine configuration matches again"
                continue
            if lt.policy["on_config_change"] == "adopt":
                old = lt.config_hash
                lt.meta, lt.config_hash, lt.stalled_reason = current, h, None
                lt.last_event = f"adopted a new engine configuration ({old[:12]} -> {h[:12]})"
                self._spawn(self._persist(lt, config_hash=h, last_event=lt.last_event))
            else:
                if lt.stalled_reason is None:
                    lt.last_event = "stalled: the engine configuration changed"
                lt.meta = None
                lt.stalled_reason = (
                    "the engine configuration changed since the Training was created "
                    f"(Training {lt.config_hash[:12]}, current {h[:12]}); its runs would not be "
                    "comparable, so it is not scheduled (policy on_config_change = pause)"
                )

    async def _persist(self, lt: LiveTraining, **values: Any) -> None:
        try:
            async with self._factory() as s:
                async with s.begin():
                    await s.execute(update(Training).where(Training.id == lt.id)
                                    .values(updated_at=_utcnow(), **values))
        except Exception:  # noqa: BLE001
            logger.exception("persisting training %d failed", lt.id)

    def _status_lock(self, training_id: int) -> asyncio.Lock:
        lock = self._status_locks.get(training_id)
        if lock is None:
            lock = self._status_locks[training_id] = asyncio.Lock()
        return lock

    async def _sync_live(self, lt: LiveTraining) -> None:
        """Write the live status and event to the row.  The live state is authoritative:
        this writes what it is *now*, under the Training's status lock, so a pause made
        by a policy cannot be overwritten by (or overwrite) a user's close/resume/PATCH."""
        async with self._status_lock(lt.id):
            await self._persist(lt, status=lt.status, last_event=lt.last_event)

    # -- the scheduler ------------------------------------------------------

    async def _run(self) -> None:
        assert self._wake is not None
        while True:
            # Also on a timer: a stalled Training must notice the configuration returning
            # without anything else happening (``_fill`` re-checks the configurations).
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=1.5)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()
            try:
                await self._fill()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - the scheduler must outlive a bad pass
                logger.exception("training scheduler pass failed")
                await asyncio.sleep(1.0)
                self._wake.set()

    def _window(self) -> int:
        w = self._executor.workers
        # Shared memory: a run starts as soon as it is dispatched, so a worker is never
        # handed a run before the previous one has merged.
        if any(lt.shared and lt.schedulable for lt in self._live.values()):
            return max(1, w)
        return max(2, w * 2)

    def _pick(self) -> tuple[LiveTraining, LiveProblem] | None:
        trainings = [lt for lt in self._live.values() if lt.schedulable]
        if not trainings:
            return None
        for i in range(len(trainings)):
            lt = trainings[(self._rr + i) % len(trainings)]
            lp = lt.next_problem()
            if lp is not None:
                self._rr = (self._rr + i + 1) % len(trainings)
                return lt, lp
        return None

    def _drain(self) -> None:
        """Merge every completed outcome before anything is dispatched."""
        while self._done_queue:
            sub, fut = self._done_queue.popleft()
            self._on_done(sub, fut)

    async def _fill(self) -> None:
        self._drain()
        self._check_configs()
        while not self._stopped:
            self._drain()
            self._check_configs()  # cheap (hash compare): a long dispatch run must notice too
            if self._isolation:
                # After a pool break the affected runs go one at a time, ahead of
                # everything else, so the run that breaks the pool is identified.
                if self._inflight_runs > 0:
                    return
                lt, lp, seed = self._isolation.popleft()
                lt.unsubmitted -= 1
                if lp.cancelled or lt.cancelled:
                    continue
                if not lt.schedulable:
                    self._requeue(lt, lp, seed)  # paused/stalled: it waits with its problem
                    continue
                lp.inflight += 1
                await self._submit(lt, lp, seed, isolated=True)
                continue
            if self._isolated_inflight or self._inflight_runs >= self._window():
                return
            picked = self._pick()
            if picked is None:
                return
            lt, lp = picked
            seed = lp.todo.popleft()
            lt.unsubmitted -= 1
            lp.inflight += 1
            await self._submit(lt, lp, seed)

    async def _submit(self, lt: LiveTraining, lp: LiveProblem, seed: int,
                      isolated: bool = False) -> None:
        """Hand one run to the executor.

        **When a run's memory copy is taken.**  A shared-memory run starts from the master
        as it is *at the moment this method builds the run's* ``MemoryRef`` (below): every
        outcome that had completed has been merged first (``_fill`` drains them), and the
        version is recorded as the run's ``memory_version``.  The Training owns its pool
        and keeps at most one run per worker in flight, so a dispatched run starts at once
        and no merge can land between this moment and the worker beginning it; the worker
        takes its copy of exactly that version when it begins.  A merge that completes
        later reaches only runs dispatched after it.
        """
        failures = lp.failures.get(seed, 0)
        ref = None
        if lt.shared:
            snapshot = (lp.id, seed) in lt.want_snapshot
            lt.want_snapshot.discard((lp.id, seed))
            depth = max(tm.MIN_TAIL, 4 * self._executor.workers)
            ref = lt.memory_ref(depth, snapshot)
            blob = len(ref.snapshot) if ref.snapshot is not None else sum(len(b) for b in ref.tail)
            self.task_memory_bytes[0] += blob
            self.task_memory_bytes[1] += 1
        fault = self.fault_hook(lp, seed, failures) if self.fault_hook else None
        task = TrainingTask(
            lp.initial, lp.modified, lp.target, lp.answer, seed, lt.max_codelets,
            lt.parameters, lt.backend, memory=ref, fault=fault,
        )
        sub = Sub(lt, lp, seed, ref.version if ref is not None else None, lt.config_hash, failures,
                  isolated)
        self._inflight_runs += 1
        if isolated:
            self._isolated_inflight += 1
        try:
            future = await asyncio.to_thread(self._executor.submit, [task], lt.meta)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("training executor refused a run")
            self._inflight_runs -= 1
            if isolated:
                self._isolated_inflight -= 1
            self._worker_failed(sub, exc)
            await asyncio.sleep(0.2)
            return
        loop = self._loop

        def _cb(f) -> None:
            self._done_queue.append((sub, f))
            try:
                loop.call_soon_threadsafe(self.wake)
            except RuntimeError:  # loop closed: the service is gone
                pass

        future.add_done_callback(_cb)

    def _on_done(self, sub: Sub, fut) -> None:
        if self._stopped:
            return
        self._inflight_runs -= 1
        if sub.isolated:
            self._isolated_inflight -= 1
        if fut.cancelled() or fut.exception() is not None:
            self._worker_failed(sub, None if fut.cancelled() else fut.exception())
            return
        outcome = fut.result()[0]
        lt, lp = sub.lt, sub.lp
        if outcome.need_snapshot:
            lp.inflight -= 1
            if not lp.cancelled:
                lt.want_snapshot.add((lp.id, sub.seed))
                self._requeue(lt, lp, sub.seed)
            self.wake()
            return
        self._record(sub, outcome)
        self.wake()

    def _requeue(self, lt: LiveTraining, lp: LiveProblem, seed: int) -> None:
        lp.todo.appendleft(seed)
        lt.unsubmitted += 1

    def _worker_failed(self, sub: Sub, exc: BaseException | None) -> None:
        """The run did not complete (worker died, pool broken).

        A broken pool fails *every* in-flight run, and only one of them is the culprit.
        So a first break charges nobody: the affected runs are re-run one at a time
        (``_isolation``, ahead of normal work).  A run that breaks the pool while it is
        alone is the culprit and only it is charged -- its ``attempts``, the ``max_retries``
        budget and ``on_worker_failure``.  Innocent runs are re-run normally and their
        ``attempts`` count only their own failures.  Results are exact either way: runs
        are deterministic (a shared-memory run is re-dispatched at the then-current version).
        """
        lt, lp, seed = sub.lt, sub.lp, sub.seed
        lp.inflight -= 1
        logger.warning("training %d problem %d seed %d: worker failure %r", lt.id, lp.id, seed, exc)
        if lp.cancelled or lt.cancelled:
            return
        policy = lt.policy
        broke = isinstance(exc, BrokenProcessPool)
        if policy["on_worker_failure"] == "pause":
            self._requeue(lt, lp, seed)
            self._trigger_pause(lt, f"paused: a worker failed on problem {lp.id} seed {seed} "
                                    "(on_worker_failure = pause)")
        elif broke and not sub.isolated:
            self._isolation.append((lt, lp, seed))  # unattributed: nobody is charged yet
            lt.unsubmitted += 1
        else:
            lp.failures[seed] = lp.failures.get(seed, 0) + 1
            if lp.failures[seed] > policy["max_retries"]:
                self._requeue(lt, lp, seed)  # never lost: it runs again on resume
                self._trigger_pause(lt, f"paused: problem {lp.id} seed {seed} failed on a worker "
                                        f"{lp.failures[seed]} times, over max_retries {policy['max_retries']}")
            elif broke:
                self._isolation.append((lt, lp, seed))  # a retry stays on its own
                lt.unsubmitted += 1
            else:
                self._requeue(lt, lp, seed)
        self.wake()

    def _record(self, sub: Sub, o: Any) -> None:
        lt, lp = sub.lt, sub.lp
        lp.inflight -= 1
        if lp.cancelled:
            return  # the problem was cancelled while this run was in flight: dropped
        rec = RunRec(
            seed=o.seed, status=o.status, key=run_key(o, lt.max_codelets), answer=o.answer,
            answers=list(o.answers), codelets=o.codelets, seconds=o.seconds,
            temperature=o.temperature, answer_quality=o.answer_quality, error=o.error,
            config_hash=sub.config_hash, attempts=sub.failures + 1, problem_id=lp.id,
            memory_version=sub.version,
        )
        if lt.shared:
            blob = o.additions
            adds = pickle.loads(blob) if blob else tm.Additions()
            n_a, n_s = tm.apply_merge(lt.memory, adds)
            lt.version += 1
            rec.seq, rec.added_answers, rec.added_snags = lt.version, n_a, n_s
            lt.merge_blobs[lt.version] = blob or tm.dump_additions(adds)
            lt.merge_blobs.pop(lt.version - MERGE_KEEP, None)
            lt.pending_merges.append((lt.version, lp.id, o.seed, adds))
        lp.outcomes[o.seed] = rec
        lp.failures.pop(o.seed, None)
        lt.pending_runs.append(rec)
        lt.note_completion()
        self._apply_error_policy(lt, lp, rec)
        if len(lp.outcomes) >= lp.seeds and not lp.finishing and not lp.cancelled:
            self._begin_finish(lt, lp)

    def _apply_error_policy(self, lt: LiveTraining, lp: LiveProblem, rec: RunRec) -> None:
        if not rec.error:
            return
        lt.errors_total += 1
        policy = lt.policy
        errs = sum(1 for r in lp.outcomes.values() if r.error)
        where = f"problem {lp.id} seed {rec.seed}"
        action = policy["on_run_error"]
        if action == "cancel":
            self._spawn(self._policy_cancel_training(lt, f"cancelled: a run raised ({where}), on_run_error = cancel"))
            return
        if action == "pause":
            self._trigger_pause(lt, f"paused: a run raised ({where}), on_run_error = pause")
        elif action == "skip_problem" and not lp.finishing:
            self._spawn(self._policy_cancel_problem(
                lt, lp, f"cancelled problem {lp.id}: a run raised (seed {rec.seed}), on_run_error = skip_problem"))
            return
        limit = policy["max_errors_per_problem"]
        if limit is not None and errs >= limit and not lp.finishing:
            self._spawn(self._policy_cancel_problem(
                lt, lp, f"cancelled problem {lp.id}: {errs} errors reached max_errors_per_problem"))
            return
        total_limit = policy["max_errors_total"]
        if total_limit is not None and lt.errors_total >= total_limit:
            self._trigger_pause(lt, f"paused: {lt.errors_total} errors reached max_errors_total")

    def _trigger_pause(self, lt: LiveTraining, event: str) -> None:
        """Pause from inside the scheduler: effective at once, persisted right after."""
        if lt.status in ("paused", "cancelled"):
            return
        lt.status = "paused"
        lt.last_event = event
        self._spawn(self._sync_live(lt))

    async def _policy_cancel_problem(self, lt: LiveTraining, lp: LiveProblem, event: str) -> None:
        if lp.cancelled or lp.finishing:
            return
        lt.last_event = event
        try:
            await self._cancel_live(lt, lp)
            await self._sync_live(lt)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - the problem is rerun from its stored seeds on restart
            logger.exception("policy cancel of problem %d failed", lp.id)
        await self._announce(lt.id)

    async def _policy_cancel_training(self, lt: LiveTraining, event: str) -> None:
        lt.last_event = event
        try:
            await self.cancel_training(lt.id, event)
        except TrainingError:
            pass

    async def _persist_event(self, tid: int, event: str) -> None:
        async with self._factory() as s:
            async with s.begin():
                await s.execute(update(Training).where(Training.id == tid).values(last_event=event))

    def _spawn(self, coro) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    # -- the milestone write ----------------------------------------------------

    def _begin_finish(self, lt: LiveTraining, lp: LiveProblem) -> None:
        lp.finishing = True
        lp.written = asyncio.Event()
        self._spawn(self._finish(lt, lp, "finished"))

    async def _write_problem(self, lt: LiveTraining, lp: LiveProblem, status: str) -> int | None:
        """The milestone: the problem's summary, every run committed since the last write
        (from any problem) and the memory merges since the last write, in one transaction.
        Returns the problem's ``finished_seq`` (0 when it gets none)."""
        tally = summarize(list(lp.outcomes.values()))
        wants_seq = status == "finished" or lp.started or bool(lp.outcomes)
        assert self._write_lock is not None
        async with self._write_lock:
            # Taken under the lock so writes commit in order and nothing is written twice.
            n_runs, n_merges = len(lt.pending_runs), len(lt.pending_merges)
            runs = lt.pending_runs[:n_runs]
            merges = lt.pending_merges[:n_merges]
            run_rows = [self._run_row(lt, r) for r in runs]
            merge_rows = await asyncio.to_thread(self._merge_rows, lt, merges)
            try:
                async with self._factory() as s:
                    async with s.begin():
                        seq = None
                        if wants_seq:
                            seq = (await s.execute(
                                update(Training).where(Training.id == lt.id)
                                .values(finished_count=Training.finished_count + 1)
                                .returning(Training.finished_count)
                            )).scalar_one_or_none()
                            if seq is None:
                                return None  # the Training was deleted
                        res = await s.execute(
                            update(TrainingProblem)
                            .where(TrainingProblem.id == lp.id, TrainingProblem.status == "queued")
                            .values(status=status, finished_seq=seq, started_at=lp.started_at,
                                    finished_at=_utcnow(), **tally)
                        )
                        if res.rowcount == 0:
                            raise _Skip()  # cancelled or deleted meanwhile: write nothing
                        for i in range(0, len(run_rows), RUN_ROW_CHUNK):
                            await s.execute(insert(TrainingRun), run_rows[i:i + RUN_ROW_CHUNK])
                        for i in range(0, len(merge_rows), RUN_ROW_CHUNK):
                            await s.execute(insert(TrainingMemoryMerge), merge_rows[i:i + RUN_ROW_CHUNK])
            except _Skip:
                return None
            del lt.pending_runs[:n_runs]
            del lt.pending_merges[:n_merges]
            return seq if seq is not None else 0

    @staticmethod
    def _run_row(lt: LiveTraining, r: RunRec) -> dict[str, Any]:
        return {
            "training_id": lt.id, "problem_id": r.problem_id, "seed": r.seed, "status": r.status,
            "key": r.key, "answer": r.answer, "answers": list(r.answers), "codelets": r.codelets,
            "seconds": r.seconds, "temperature": r.temperature, "answer_quality": r.answer_quality,
            "error": r.error, "config_hash": r.config_hash, "attempts": r.attempts, "seq": r.seq,
            "memory_version": r.memory_version, "added_answers": r.added_answers,
            "added_snags": r.added_snags,
        }

    @staticmethod
    def _merge_rows(lt: LiveTraining, merges: list) -> list[dict[str, Any]]:
        rows = []
        for seq, pid, seed, adds in merges:
            answers, snags = tm.encode_additions(adds)
            rows.append({"training_id": lt.id, "seq": seq, "problem_id": pid, "seed": seed,
                         "answers": answers, "snags": snags})
        return rows

    def _forget(self, lt: LiveTraining, lp: LiveProblem) -> None:
        lt.problems.pop(lp.id, None)
        lt.active.pop(lp.id, None)
        if lp.written is not None:
            lp.written.set()

    async def _finish(self, lt: LiveTraining, lp: LiveProblem, status: str) -> None:
        delay = 0.5
        while True:
            try:
                await self._write_problem(lt, lp, status)
                break
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("writing problem %d failed; retrying", lp.id)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 10.0)
        self._forget(lt, lp)
        await self._announce(lt.id)
        self.wake()

    async def _announce(self, training_id: int) -> None:
        self._versions[training_id] = self._versions.get(training_id, 0) + 1
        cond = self._conds.get(training_id)
        if cond is not None:
            async with cond:
                cond.notify_all()

    # -- reading ----------------------------------------------------------------

    def executor_info(self) -> dict[str, Any]:
        queued = sum(lt.unsubmitted for lt in self._live.values() if lt.schedulable)
        return {
            "kind": self._executor.kind, "workers": self._executor.workers,
            "in_flight": self._executor.in_flight, "queued_runs": queued,
        }

    @staticmethod
    def limits() -> dict[str, int]:
        return {
            "max_problems_per_request": MAX_PROBLEMS_PER_REQUEST,
            "max_seeds_per_problem": MAX_SEEDS_PER_PROBLEM,
            "max_codelets": MAX_CODELETS_LIMIT,
        }

    def defaults(self) -> dict[str, Any]:
        meta = self._meta_provider()
        return {
            "settings": {
                "memory": "shared", "seeds_per_problem": 100, "seed_start": 1,
                "max_codelets": 20_000, "parameters": None,
                "backend": default_training_backend(meta),
            },
            "policy": dict(DEFAULT_POLICY),
        }

    async def _summaries(self, s: AsyncSession, trainings: list[Training]) -> list[dict[str, Any]]:
        """Summaries from the database plus the live problems.

        **Consistency.**  The live state is read first (synchronously, so it is one
        instant), then the database in one REPEATABLE READ snapshot.  A live problem the
        snapshot already shows as written is counted from the database only; one it still
        shows as queued is counted from memory.  Counts therefore never step backwards:
        a problem is always in exactly one of the two.

        **Which runs count.**  ``runs.total/done/errors/capped/retries`` and ``codelets``
        all count the runs of problems that are not cancelled (a cancelled problem leaves
        the totals; its runs stay available on the problem itself).
        """
        if not trainings:
            return []
        ids = [t.id for t in trainings]
        P = TrainingProblem
        live: dict[int, dict[int, tuple]] = {}
        for t in trainings:
            lt = self._live.get(t.id)
            if lt is None:
                continue
            live[t.id] = {}
            for lp in lt.active.values():
                if lp.cancelled:
                    continue
                recs = list(lp.outcomes.values())
                live[t.id][lp.id] = (
                    len(recs), sum(1 for r in recs if r.error), sum(r.codelets for r in recs),
                    sum(1 for r in recs if r.key == CAP_KEY),
                    sum(max(r.attempts - 1, 0) for r in recs),
                )
        s = self._factory()
        await s.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        rows = (await s.execute(
            select(
                P.training_id, P.status, func.count(),
                func.coalesce(func.sum(P.seeds), 0), func.coalesce(func.sum(P.runs_done), 0),
                func.coalesce(func.sum(P.errors), 0), func.coalesce(func.sum(P.codelets_total), 0),
                func.coalesce(func.sum(P.capped), 0), func.coalesce(func.sum(P.retries), 0),
            ).where(P.training_id.in_(ids)).group_by(P.training_id, P.status)
        )).all()
        by_t: dict[int, dict[str, tuple]] = {}
        for tid, status, *vals in rows:
            by_t.setdefault(tid, {})[status] = tuple(int(v) for v in vals)
        live_ids = [pid for per in live.values() for pid in per]
        written: set[int] = set()
        if live_ids:
            written = set((await s.execute(
                select(P.id).where(P.id.in_(live_ids), P.status != "queued"))).scalars())
        # The cursor comes from the same snapshot as the counts: the Training rows the caller
        # loaded may predate it, and a summary must not count a problem as finished while
        # its finished_seq is still beyond finished_cursor.
        cursors = dict((await s.execute(
            select(Training.id, Training.finished_count).where(Training.id.in_(ids)))).all())
        await s.close()
        zero = (0,) * 7
        out = []
        for t in trainings:
            c = by_t.get(t.id, {})
            q, f, x = c.get("queued", zero), c.get("finished", zero), c.get("cancelled", zero)
            queued, running = q[0], 0
            total = q[1] + f[1]
            done, errors, codelets, capped, retries = f[2], f[3], f[4], f[5], f[6]
            lt = self._live.get(t.id)
            for pid, (n, e, cl, cap, rt) in live.get(t.id, {}).items():
                if pid in written:
                    continue
                running += 1
                queued -= 1
                done += n
                errors += e
                codelets += cl
                capped += cap
                retries += rt
            unfinished = queued + running
            closed = t.closed_at is not None
            stalled = lt.stalled_reason if lt is not None else None
            if lt is None and t.status != "cancelled":
                stalled = "the Training is not loaded by this server"
            status = lt.status if lt is not None and not lt.cancelled else t.status
            if status == "cancelled":
                state = "cancelled"
            elif stalled and (not closed or unfinished > 0):
                state = "stalled"
            elif status == "paused":
                state = "paused"
            elif closed and unfinished == 0:
                state = "finished"
            elif unfinished > 0:
                state = "running"
            else:
                state = "idle"
            rate = lt.rate() if lt is not None else None
            if state != "running":
                rate = None
            remaining = max(total - done, 0)
            shared = t.memory == "shared"
            out.append({
                "id": t.id, "name": t.name, "note": t.note, "status": status, "state": state,
                "stalled_reason": stalled if state == "stalled" else None,
                "settings": {
                    "memory": t.memory, "seeds_per_problem": t.seeds_per_problem,
                    "seed_start": t.seed_start, "max_codelets": t.max_codelets,
                    "parameters": t.parameters, "backend": t.backend,
                },
                "policy": normalize_policy(lt.policy if lt is not None else t.policy),
                "config_hash": lt.config_hash if lt is not None else t.config_hash,
                "created_at": _iso(t.created_at), "updated_at": _iso(t.updated_at),
                "closed_at": _iso(t.closed_at),
                "problems": {
                    "total": queued + running + f[0] + x[0], "queued": queued,
                    "running": running, "finished": f[0], "cancelled": x[0],
                },
                "runs": {"total": total, "done": done, "errors": errors, "capped": capped,
                         "retries": retries},
                "memory": (
                    {"answers": len(lt.memory.answers), "snags": len(lt.memory.snags)}
                    if shared and lt is not None and lt.memory is not None else
                    ({"answers": 0, "snags": 0} if shared else None)
                ),
                "codelets": codelets,
                "runs_per_second": round(rate, 3) if rate else None,
                "eta_seconds": round(remaining / rate, 1) if rate and remaining else None,
                "memory_version": (lt.version if lt is not None else 0) if shared else None,
                "finished_cursor": cursors.get(t.id, t.finished_count),
                "last_event": (lt.last_event if lt is not None else None) or t.last_event,
            })
        return out

    async def _get_training(self, s: AsyncSession, training_id: int) -> Training:
        t = await s.get(Training, training_id)
        if t is None:
            raise TrainingError(404, f"training {training_id} not found")
        return t

    async def list_trainings(self) -> list[dict[str, Any]]:
        async with self._factory() as s:
            ts = (await s.execute(select(Training).order_by(Training.id.desc()))).scalars().all()
            return await self._summaries(s, list(ts))

    async def summary(self, training_id: int) -> dict[str, Any]:
        async with self._factory() as s:
            return (await self._summaries(s, [await self._get_training(s, training_id)]))[0]

    # -- problem rows ---------------------------------------------------------

    def _problem_dict(self, p: TrainingProblem, detail: bool) -> dict[str, Any]:
        lt = self._live.get(p.training_id)
        lp = lt.problems.get(p.id) if lt is not None and p.status == "queued" else None
        status = p.status
        if lp is not None and lp.started and not lp.cancelled:
            status = "running"
            t = summarize(list(lp.outcomes.values()))
            finished_seq = None
        else:
            t = {
                "runs_done": p.runs_done, "errors": p.errors, "capped": p.capped,
                "mean_codelets": p.mean_codelets, "none_fraction": p.none_fraction,
                "distinct_answers": p.distinct_answers, "distribution": p.distribution,
                "statuses": p.statuses, "first_error": p.first_error,
            }
            finished_seq = p.finished_seq
        done = t["runs_done"]
        row = {
            "id": p.id, "training_id": p.training_id, "initial": p.initial,
            "modified": p.modified, "target": p.target, "answer": p.answer, "seeds": p.seeds,
            "seed_start": p.seed_start, "tag": p.tag, "status": status, "runs_done": done,
            "errors": t["errors"], "capped": t["capped"], "mean_codelets": t["mean_codelets"],
            "top": _shares(t["distribution"], done, 3), "none_fraction": t["none_fraction"],
            "distinct": t["distinct_answers"] or 0, "statuses": t["statuses"] or {},
            "finished_seq": finished_seq, "added_at": _iso(p.added_at),
            "started_at": _iso(lp.started_at if lp is not None and lp.started else p.started_at),
            "finished_at": _iso(p.finished_at),
        }
        if detail:
            row["distribution"] = _shares(t["distribution"], done, None)
            row["first_error"] = t["first_error"]
        return row

    def _running_ids(self, training_id: int) -> list[int]:
        lt = self._live.get(training_id)
        return [i for i, lp in lt.active.items() if not lp.cancelled] if lt is not None else []

    SORTS = {
        "id": TrainingProblem.id, "runs_done": TrainingProblem.runs_done,
        "top_fraction": TrainingProblem.top_fraction, "none_fraction": TrainingProblem.none_fraction,
        "distinct": TrainingProblem.distinct_answers, "errors": TrainingProblem.errors,
        "mean_codelets": TrainingProblem.mean_codelets, "finished_seq": TrainingProblem.finished_seq,
    }

    def _problem_filter(self, training_id: int, status: str | None, q: str | None):
        P = TrainingProblem
        conds = [P.training_id == training_id]
        if status:
            running = self._running_ids(training_id)
            if status == "running":
                conds += [P.status == "queued", P.id.in_(running or [-1])]
            elif status == "queued":
                conds += [P.status == "queued"]
                if running:
                    conds.append(P.id.not_in(running))
            elif status in ("finished", "cancelled"):
                conds.append(P.status == status)
            else:
                raise TrainingError(422, f"unknown status {status!r}")
        if q:
            conds.append(func.concat_ws(" ", P.initial, P.modified, P.target).icontains(q, autoescape=True))
        return conds

    async def list_problems(
        self, training_id: int, status: str | None = None, q: str | None = None,
        sort: str = "id", order: str = "asc", offset: int = 0, limit: int = 100,
    ) -> dict[str, Any]:
        if sort not in self.SORTS:
            raise TrainingError(422, f"sort must be one of {sorted(self.SORTS)}")
        if order not in ("asc", "desc"):
            raise TrainingError(422, "order must be asc or desc")
        P = TrainingProblem
        async with self._factory() as s:
            await self._get_training(s, training_id)
            conds = self._problem_filter(training_id, status, q)
            total = (await s.execute(select(func.count()).select_from(P).where(*conds))).scalar_one()
            col = self.SORTS[sort]
            ordering = col.desc().nulls_last() if order == "desc" else col.asc().nulls_last()
            rows = (await s.execute(
                select(P).where(*conds).order_by(ordering, P.id.asc()).offset(offset).limit(limit)
            )).scalars().all()
            return {"total": total, "problems": [self._problem_dict(p, False) for p in rows]}

    async def _get_problem(self, s: AsyncSession, training_id: int, pid: int) -> TrainingProblem:
        p = await s.get(TrainingProblem, pid)
        if p is None or p.training_id != training_id:
            raise TrainingError(404, f"problem {pid} not found in training {training_id}")
        return p

    async def get_problem(self, training_id: int, pid: int) -> dict[str, Any]:
        async with self._factory() as s:
            return self._problem_dict(await self._get_problem(s, training_id, pid), True)

    async def problem_runs(self, training_id: int, pid: int) -> list[dict[str, Any]]:
        async with self._factory() as s:
            p = await self._get_problem(s, training_id, pid)
            lt = self._live.get(training_id)
            lp = lt.problems.get(pid) if lt is not None else None
            if lp is not None and p.status == "queued":
                return [self._run_dict(r) for r in sorted(lp.outcomes.values(), key=lambda r: r.seed)]
            rows = (await s.execute(
                select(TrainingRun).where(TrainingRun.problem_id == pid).order_by(TrainingRun.seed)
            )).scalars().all()
            return [self._run_dict(r) for r in rows]

    @staticmethod
    def _run_dict(r: Any) -> dict[str, Any]:
        return {
            "seq": r.seq, "memory_version": r.memory_version, "seed": r.seed, "status": r.status,
            "key": r.key, "answer": r.answer, "answers": list(r.answers or []),
            "codelets": r.codelets, "seconds": round(r.seconds, 4), "temperature": r.temperature,
            "answer_quality": r.answer_quality, "error": r.error, "config_hash": r.config_hash,
            "attempts": r.attempts,
            "memory_added": (
                {"answers": r.added_answers, "snags": r.added_snags}
                if r.added_answers is not None else None
            ),
        }

    async def finished(self, training_id: int, after: int = 0, limit: int = 100,
                       wait: float = 0.0) -> dict[str, Any]:
        deadline = time.monotonic() + max(0.0, min(wait, 60.0))
        async with self._factory() as s:
            await self._get_training(s, training_id)
        cond = self._conds.get(training_id)
        if cond is None:
            cond = self._conds[training_id] = asyncio.Condition()
        P = TrainingProblem
        while True:
            version = self._versions.get(training_id, 0)
            async with self._factory() as s:
                rows = (await s.execute(
                    select(P).where(P.training_id == training_id, P.finished_seq > after)
                    .order_by(P.finished_seq).limit(limit)
                )).scalars().all()
            remaining = deadline - time.monotonic()
            if rows or remaining <= 0 or self._stopped:
                cursor = rows[-1].finished_seq if rows else after
                return {"cursor": cursor, "problems": [self._problem_dict(p, False) for p in rows]}
            async with cond:
                if self._versions.get(training_id, 0) == version:
                    try:
                        await asyncio.wait_for(cond.wait(), remaining)
                    except asyncio.TimeoutError:
                        pass

    # -- the episode memory --------------------------------------------------

    async def memory_of(self, training_id: int) -> EpisodicMemory:
        """The episode memory (live if loaded, else rebuilt from the stored merges)."""
        async with self._factory() as s:
            t = await self._get_training(s, training_id)
            if t.memory != "shared":
                raise TrainingError(409, f"training {training_id} uses independent memory: "
                                         "it has no episode memory")
            lt = self._live.get(training_id)
            if lt is not None and lt.memory is not None:
                return tm.copy_for_run(lt.memory)
            return await self.rebuild_memory(s, training_id)

    @staticmethod
    async def rebuild_memory(s: AsyncSession, training_id: int, upto: int | None = None) -> EpisodicMemory:
        """Replay the stored merges (to version *upto*, default all) into a fresh memory."""
        mem = EpisodicMemory()
        q = select(TrainingMemoryMerge).where(TrainingMemoryMerge.training_id == training_id)
        if upto is not None:
            q = q.where(TrainingMemoryMerge.seq <= upto)
        for m in (await s.execute(q.order_by(TrainingMemoryMerge.seq))).scalars():
            tm.apply_merge(mem, tm.decode_additions(m.answers, m.snags))
        return mem

    def live_memory(self, training_id: int) -> EpisodicMemory | None:
        lt = self._live.get(training_id)
        return lt.memory if lt is not None else None

    # -- writing: create / add -------------------------------------------------

    def _validate_problems(self, problems: list[dict]) -> None:
        if len(problems) > MAX_PROBLEMS_PER_REQUEST:
            raise TrainingError(422, f"at most {MAX_PROBLEMS_PER_REQUEST} problems per request")
        for p in problems:
            for k in ("initial", "modified", "target"):
                if not LETTERS.match(p.get(k) or ""):
                    raise TrainingError(422, f"{k} must be 1-64 letters")
            if p.get("answer") is not None and not LETTERS.match(p["answer"]):
                raise TrainingError(422, "answer must be 1-64 letters")
            n = p.get("seeds")
            if n is not None and not (1 <= n <= MAX_SEEDS_PER_PROBLEM):
                raise TrainingError(422, f"seeds must be 1..{MAX_SEEDS_PER_PROBLEM}")

    async def _insert_problems(self, s: AsyncSession, t: Training, problems: list[dict]) -> list[TrainingProblem]:
        now = _utcnow()
        values = [
            {
                "training_id": t.id, "initial": p["initial"], "modified": p["modified"],
                "target": p["target"], "answer": p.get("answer"),
                "seeds": p.get("seeds") or t.seeds_per_problem, "seed_start": t.seed_start,
                "tag": p.get("tag"), "status": "queued", "runs_done": 0, "errors": 0, "capped": 0,
                "retries": 0, "codelets_total": 0, "distinct_answers": 0, "added_at": now,
            }
            for p in problems
        ]
        ids: list[int] = []
        for i in range(0, len(values), INSERT_CHUNK):
            res = await s.execute(
                insert(TrainingProblem).returning(TrainingProblem.id, sort_by_parameter_order=True),
                values[i:i + INSERT_CHUNK],
            )
            ids.extend(r[0] for r in res)
        return [TrainingProblem(id=pid, **v) for pid, v in zip(ids, values)]

    @staticmethod
    def _check_seed_range(seed_start: int, seed_counts: list[int]) -> None:
        """Seeds are stored as int32: the last seed of the longest problem must fit."""
        last = seed_start + max(seed_counts) - 1
        if last > INT32_MAX:
            raise TrainingError(
                422, f"seed_start {seed_start} with {max(seed_counts)} seeds runs past the "
                     f"largest seed, {INT32_MAX}")

    def resolve_backend(self, meta: MetadataProvider, requested: str | None) -> str:
        if requested is not None:
            allowed = available_backend_names()
            if requested not in allowed:
                raise TrainingError(
                    400, f"numeric backend {requested!r} is not available here; choose from {allowed}"
                )
            return requested
        return default_training_backend(meta)

    async def create_training(
        self, *, name: str, note: str = "", settings: dict | None = None,
        policy: dict | None = None, problems: list[dict] | None = None,
    ) -> dict[str, Any]:
        name = (name or "").strip()
        if not 1 <= len(name) <= 200:
            raise TrainingError(422, "name is required (1..200 characters)")
        problems = problems or []
        self._validate_problems(problems)
        settings = dict(settings or {})
        for key in settings:
            if key not in _SETTINGS_KEYS:
                raise TrainingError(422, f"unknown setting {key!r}; known: {list(_SETTINGS_KEYS)}")
        memory = settings.get("memory") or "shared"
        if memory not in ("shared", "independent"):
            raise TrainingError(422, "settings.memory must be 'shared' or 'independent'")
        spp = settings.get("seeds_per_problem", 100)
        if not isinstance(spp, int) or isinstance(spp, bool) or not 1 <= spp <= MAX_SEEDS_PER_PROBLEM:
            raise TrainingError(422, f"settings.seeds_per_problem must be 1..{MAX_SEEDS_PER_PROBLEM}")
        seed_start = settings.get("seed_start", 1)
        if not isinstance(seed_start, int) or isinstance(seed_start, bool) or not 0 <= seed_start <= INT32_MAX:
            raise TrainingError(422, f"settings.seed_start must be an integer 0..{INT32_MAX}")
        self._check_seed_range(seed_start, [spp] + [p.get("seeds") or 0 for p in problems])
        max_codelets = settings.get("max_codelets", 20_000)
        if (not isinstance(max_codelets, int) or isinstance(max_codelets, bool)
                or not 1 <= max_codelets <= MAX_CODELETS_LIMIT):
            raise TrainingError(422, f"settings.max_codelets must be 1..{MAX_CODELETS_LIMIT}")
        try:
            overrides = validate_overrides(settings.get("parameters"))
        except (UnknownParameter, ValueError) as exc:
            raise TrainingError(400, str(exc)) from exc
        full_policy = normalize_policy(policy)
        meta = self._meta_provider()
        backend_name = self.resolve_backend(meta, settings.get("backend"))
        cfg = self._config_hash(meta)
        async with self._factory() as s:
            async with s.begin():
                t = Training(
                    name=name, note=note or "", status="open", memory=memory,
                    seeds_per_problem=spp, seed_start=seed_start, max_codelets=max_codelets,
                    parameters=overrides or None, backend=backend_name, policy=full_policy,
                    config_hash=cfg, finished_count=0,
                )
                s.add(t)
                await s.flush()
                created = await self._insert_problems(s, t, problems)
            lt = self._new_live(t, meta)
            for p in created:
                self._enqueue(lt, p)
            self._live[t.id] = lt
            summary = (await self._summaries(s, [t]))[0]
        self.wake()
        return {"training": summary, "added": len(created), "problem_ids": [p.id for p in created]}

    async def add_problems(self, training_id: int, problems: list[dict]) -> dict[str, Any]:
        self._validate_problems(problems)
        async with self._factory() as s:
            async with s.begin():
                t = (await s.execute(
                    select(Training).where(Training.id == training_id).with_for_update()
                )).scalar_one_or_none()
                if t is None:
                    raise TrainingError(404, f"training {training_id} not found")
                if t.status == "cancelled" or t.closed_at is not None or t.status == "closed":
                    raise TrainingError(409, f"training {training_id} is {t.status}; it accepts no more problems")
                self._check_seed_range(
                    t.seed_start, [t.seeds_per_problem] + [p.get("seeds") or 0 for p in problems])
                created = await self._insert_problems(s, t, problems)
            lt = self._live.get(training_id)
            if lt is not None:
                for p in created:
                    self._enqueue(lt, p)
            summary = (await self._summaries(s, [t]))[0]
        self.wake()
        return {"training": summary, "added": len(created), "problem_ids": [p.id for p in created]}

    # -- control -----------------------------------------------------------------

    async def _set_status(self, training_id: int, fn) -> dict[str, Any]:
        """Apply a status/policy change.  The live state is authoritative: the row is
        brought up to the live status first, *then* the change is applied, and the result
        goes back to the live state -- a stale row never overwrites a policy's pause.
        Serialised per Training."""
        async with self._status_lock(training_id):
            async with self._factory() as s:
                async with s.begin():
                    t = (await s.execute(
                        select(Training).where(Training.id == training_id).with_for_update()
                    )).scalar_one_or_none()
                    if t is None:
                        raise TrainingError(404, f"training {training_id} not found")
                    lt = self._live.get(training_id)
                    if lt is not None and t.status != "cancelled":
                        t.status = lt.status
                        t.last_event = lt.last_event
                    fn(t)
                    t.updated_at = _utcnow()
                lt = self._live.get(training_id)
                if lt is not None:
                    lt.status = t.status
                    lt.closed = t.closed_at is not None
                    lt.policy = normalize_policy(t.policy)
                    lt.last_event = t.last_event
                summary = (await self._summaries(s, [t]))[0]
        await self._announce(training_id)
        self.wake()
        return summary

    async def update(self, training_id: int, name: str | None = None, note: str | None = None,
                     policy: dict | None = None) -> dict[str, Any]:
        if name is not None:
            name = name.strip()
            if not 1 <= len(name) <= 200:
                raise TrainingError(422, "name must be 1..200 characters")
        async with self._factory() as s:
            current = await self._get_training(s, training_id)
            new_policy = normalize_policy(policy, current.policy) if policy is not None else None

        def fn(t: Training) -> None:
            if name is not None:
                t.name = name
            if note is not None:
                t.note = note
            if new_policy is not None:
                t.policy = new_policy

        return await self._set_status(training_id, fn)

    async def pause(self, training_id: int) -> dict[str, Any]:
        def fn(t: Training) -> None:
            if t.status in ("open", "closed"):
                t.status = "paused"
        return await self._set_status(training_id, fn)

    async def resume(self, training_id: int) -> dict[str, Any]:
        lt = self._live.get(training_id)
        if lt is not None:
            for lp in lt.active.values():
                lp.failures.clear()  # a resume is a fresh start for the retry budget

        def fn(t: Training) -> None:
            if t.status == "paused":
                t.status = "closed" if t.closed_at is not None else "open"
        return await self._set_status(training_id, fn)

    async def close(self, training_id: int) -> dict[str, Any]:
        def fn(t: Training) -> None:
            if t.status == "cancelled":
                return
            if t.closed_at is None:
                t.closed_at = _utcnow()
            if t.status == "open":
                t.status = "closed"
        return await self._set_status(training_id, fn)

    async def cancel_problem(self, training_id: int, pid: int) -> dict[str, Any]:
        async with self._factory() as s:
            p = await self._get_problem(s, training_id, pid)
        lt = self._live.get(training_id)
        lp = lt.problems.get(pid) if lt is not None else None
        if p.status == "queued":
            if lp is not None and lp.finishing and lp.written is not None:
                await lp.written.wait()
            elif lp is not None:
                await self._cancel_live(lt, lp)
            else:
                async with self._factory() as s:
                    async with s.begin():
                        await s.execute(update(TrainingProblem).where(
                            TrainingProblem.id == pid, TrainingProblem.status == "queued"
                        ).values(status="cancelled", finished_at=_utcnow()))
        await self._announce(training_id)
        return await self.get_problem(training_id, pid)

    async def _cancel_live(self, lt: LiveTraining, lp: LiveProblem) -> None:
        lp.cancelled = True
        lt.unsubmitted -= len(lp.todo)
        lp.todo.clear()
        try:
            for attempt in range(3):  # a transient database error must not lose the write
                try:
                    await self._write_problem(lt, lp, "cancelled")
                    break
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001
                    logger.exception("writing cancelled problem %d failed (attempt %d)", lp.id, attempt + 1)
                    if attempt == 2:
                        raise
                    await asyncio.sleep(0.5 * (attempt + 1))
        finally:
            self._forget(lt, lp)

    async def cancel_training(self, training_id: int, event: str | None = None) -> dict[str, Any]:
        def fn(t: Training) -> None:
            t.status = "cancelled"
            if event is not None:
                t.last_event = event
            if t.closed_at is None:
                t.closed_at = _utcnow()
        await self._set_status(training_id, fn)
        lt = self._live.pop(training_id, None)
        if lt is not None:
            lt.cancelled = True
            await self._settle(lt, keep_results=True)
        async with self._factory() as s:
            async with s.begin():
                await s.execute(update(TrainingProblem).where(
                    TrainingProblem.training_id == training_id, TrainingProblem.status == "queued"
                ).values(status="cancelled", finished_at=_utcnow()))
        await self._announce(training_id)
        return await self.summary(training_id)

    async def _settle(self, lt: LiveTraining, keep_results: bool) -> None:
        """Stop a Training's live problems: wait for those being written, write the started
        ones as cancelled (or drop them), and forget the rest."""
        waiting = []
        for lp in list(lt.problems.values()):
            if lp.finishing and lp.written is not None:
                waiting.append(lp)
            else:
                lp.cancelled = True  # later outcomes of this problem are dropped
        for lp in waiting:
            await lp.written.wait()
        for lp in list(lt.problems.values()):
            lp.cancelled = True
            if keep_results and (lp.started or lp.outcomes):
                await self._cancel_live(lt, lp)
            else:
                self._forget(lt, lp)
        if keep_results and lt.pending_runs:
            await self._flush_pending(lt)
        lt.unsubmitted = 0

    async def _flush_pending(self, lt: LiveTraining) -> None:
        """Write runs that are still pending (their problem is already settled)."""
        # Reuses the milestone write on a throw-away, already-written problem.
        async with self._factory() as s:
            row = (await s.execute(select(TrainingProblem.id).where(
                TrainingProblem.training_id == lt.id).limit(1))).first()
        if row is None:
            return
        # Every pending run belongs to a problem that exists; write them on their own.
        n_runs, n_merges = len(lt.pending_runs), len(lt.pending_merges)
        run_rows = [self._run_row(lt, r) for r in lt.pending_runs[:n_runs]]
        merge_rows = await asyncio.to_thread(self._merge_rows, lt, lt.pending_merges[:n_merges])
        async with self._write_lock:
            async with self._factory() as s:
                async with s.begin():
                    for i in range(0, len(run_rows), RUN_ROW_CHUNK):
                        await s.execute(insert(TrainingRun), run_rows[i:i + RUN_ROW_CHUNK])
                    for i in range(0, len(merge_rows), RUN_ROW_CHUNK):
                        await s.execute(insert(TrainingMemoryMerge), merge_rows[i:i + RUN_ROW_CHUNK])
        del lt.pending_runs[:n_runs]
        del lt.pending_merges[:n_merges]

    async def delete_training(self, training_id: int) -> None:
        async with self._factory() as s:
            await self._get_training(s, training_id)
        lt = self._live.pop(training_id, None)
        if lt is not None:
            lt.cancelled = True
            await self._settle(lt, keep_results=False)
        async with self._factory() as s:
            async with s.begin():
                await s.execute(delete(Training).where(Training.id == training_id))
        self._versions.pop(training_id, None)
        await self._announce(training_id)
        self._conds.pop(training_id, None)

    # -- export streams ---------------------------------------------------------

    async def iter_problem_dicts(self, training_id: int) -> AsyncIterator[list[dict[str, Any]]]:
        P = TrainingProblem
        last = 0
        while True:
            async with self._factory() as s:
                rows = (await s.execute(
                    select(P).where(P.training_id == training_id, P.id > last).order_by(P.id).limit(1000)
                )).scalars().all()
            if not rows:
                return
            last = rows[-1].id
            yield [self._problem_dict(p, True) for p in rows]

    async def iter_run_rows(self, training_id: int) -> AsyncIterator[list[dict[str, Any]]]:
        """Run rows with their problem's identity, in (problem, seed) order."""
        from sqlalchemy import tuple_

        R, P = TrainingRun, TrainingProblem
        last = (0, -(2 ** 62))
        while True:
            async with self._factory() as s:
                rows = (await s.execute(
                    select(R, P.initial, P.modified, P.target, P.answer)
                    .join(P, P.id == R.problem_id)
                    .where(R.training_id == training_id, tuple_(R.problem_id, R.seed) > tuple_(*last))
                    .order_by(R.problem_id, R.seed).limit(2000)
                )).all()
            if not rows:
                return
            last = (rows[-1][0].problem_id, rows[-1][0].seed)
            yield [
                {"problem_id": r.problem_id, "initial": i, "modified": m, "target": t,
                 "problem_answer": a, **self._run_dict(r)}
                for r, i, m, t, a in rows
            ]


# ---------------------------------------------------------------------------
# The process-wide service
# ---------------------------------------------------------------------------

_service: TrainingService | None = None


def get_training_service() -> TrainingService | None:
    return _service


def set_training_service(service: TrainingService | None) -> None:
    global _service
    _service = service


async def start_default_service(meta_provider: Callable[[], MetadataProvider]) -> TrainingService:
    from server.db import async_session_factory

    service = TrainingService(async_session_factory, meta_provider)
    await service.start()
    set_training_service(service)
    return service


async def stop_default_service() -> None:
    service = get_training_service()
    set_training_service(None)
    if service is not None:
        await service.stop()
