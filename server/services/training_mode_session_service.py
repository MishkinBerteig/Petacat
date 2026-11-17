"""Training Mode Sessions: named, long-lived, database-backed episodes of many problems over many seeds.

A Training Mode Session holds context-response analogy problems (made of letters, or any Unicode text).  Each
problem runs over a number of seeds on every core, and problems can be inserted into a Training Mode Session
while it runs (start with 25, add 5 more whenever problems finish).  It is the mode a future ML layer drives.

Exactness
---------
Every run is the serial ``EngineRunner.run_mcat`` run with that seed, built by
``training_mode_session_executor`` exactly as ``swarm.run_one`` builds it.  Which executor ran it (the
parallel plugin's process pool, or the single child process used when the plugin is
detached) cannot change its outcome.  The engine is untouched; each run builds its own
Workspace as any run does.

The Episodic Memory
-------------------
Every Training Mode Session owns one :class:`EpisodicMemory` (``training_mode_session_memory.py``), never cleared and
gone only when the Training Mode Session is deleted.  A run starts from a copy of it at the version current when the
run is dispatched and keeps that copy static; when the run finishes, its additions are
merged into the master (presence-checked), bumping the version.  A run records the
``memory_version`` it started with and its merge order ``seq``.  Only runs dispatched after
a merge see it.  Dispatch keeps at most one run per worker in flight, so
with one worker each run starts after the previous one merged: Metacat's serial episode.

States
------
A Training Mode Session is **Stopped**, **Starting**, **Running**, **Paused** or **Stopping**.
Only the last four are live (held in ``TrainingModeSessionService._live``, Starting being
the load that precedes it); a Stopped one is a record in the database, and every session
is Stopped after a server restart.  ``start`` loads a Stopped session: its Episodic Memory
snapshot, its configuration's stored current state (checked against the stored
``config_hash``, so a mismatch refuses the Start) and its unfinished problems, resumed at
the seeds not stored; it reads no journal row and no merge.  ``stop`` drains the runs in
flight (up to ``drain_timeout``), writes everything the session produced since it started
(including its configuration's journal entries and current state, and the memory snapshot)
in one transaction and drops the live part,
recording ``stopped_from`` (``running`` or ``paused``) and ``stop_reason`` (``user``,
``shutdown`` or ``error``).  A failed Start leaves the session Stopped; a failed Stop
returns it to Paused with its memory intact.  ``cancel`` is an action, not a state: it
cancels every queued and in-flight problem and changes no state.  Inside Running the
activity is derived: ``idle`` (nothing unfinished) or ``stalled`` (it cannot run:
``stalled_reason``) or ``waiting`` (every run that is left is a multi-turn run waiting for the teacher's
input).  Starting and Stopping are transient and refuse every mutation with
409 ``busy``.

The database is written only when a session is Stopped
------------------------------------------------------
The user's decision (2026-10-30): "a Training Mode Session only does database writes when
it is put into a 'Stopped' state.  It may do database reads at other times."

* A *live* session (Running, Paused, Starting, Stopping) writes nothing.  Its runs, memory
  merges, problems, problem outcomes and name, note and policy changes grow in memory
  (``LiveSession``) until Stop, and the API reports them from there with
  ``persisted: false``, ``saved_through`` (what the database holds) and ``unsaved`` (what
  only memory holds).  A crash loses everything since the last Stop.
* A *Stopped* session is a record: creating it, renaming it, adding problems, changing its
  configuration and deleting it are API writes, each in its own transaction.
* The **Stop write** is the one write of a live session: the session row, new problems,
  outcomes, runs and memory merges, in one transaction (``_write_stop``).  S5 adds the
  journal entries (``lt.config.pending_entries()``), the configuration's stored current state
  (``lt.config.document``) and the memory snapshot to the same transaction, and replaces the
  Start read's merge replay.  Until it does, the session's configuration batches are held in
  memory and are not stored at Stop.

A problem's identifier is a per-session **ordinal** (``(session, ordinal)`` is its key and
the API's ``problem_id``), so an identifier handed out while live is the stored one.  The
stored problem status is ``queued | finished | cancelled``; ``running`` is live-only.

The scheduler
-------------
One asyncio task keeps the executor fed from the problems of every Running session: seeds
of problems already started first (so they finish steadily), then the oldest queued
problem, round-robin across sessions so a huge one cannot starve a small one.  Inserting
a problem wakes it.  Nothing in its hot path (dispatch, merge, problem completion) reads
or writes the database.

Multi-turn runs (chats)
-----------------------
A problem with ``multi_turn`` makes each of its runs a chat (``turn_record`` holds the window, the turn seed and
the evidence).  A **turn** is one engine run (one job to the executor), and each turn is one ``finish_run``: its
memory merge and its in-worker learner batch land before the run's next turn is dispatched.  A turn that answers
makes the run **wait**, holding no worker, for the teacher's next input; the input (or the end) arrives through
``supply_input`` (the route) or ``set_teacher`` (in process), both of which come to ``_apply_input``; the next turn's
strings are ``turn_record.next_window`` of the turn that answered and the input.  A turn with no answer, an error, or the
teacher's end ends the run; only then is the run one outcome (``RunRec``) of its problem, so a problem finishes
when every run has ended and a session whose only unfinished runs are waiting is ``waiting`` (the activity).
A single-turn problem's run is the same machinery with one turn that ends it: it is exactly the run it always was.

*Waiting is per run, not a session state.*  A ``LiveRun`` holds a run's turns since Start (or restored at Start),
its ``pending`` turn (the strings of the turn that is queued or in flight) and its state (``running``, ``waiting``,
``ended``).  A queued later turn is dispatched like a fresh seed (its seed goes back on its problem's ``todo``), so
the retry, isolation and Stop paths need no case of their own.  Pause stops dispatch, and an input given while
Paused is kept and dispatched on Resume.  The Stop write stores one row per turn of every run changed since Start
(``training_mode_session_turns``), with a ``pending`` row for the turn that was queued or in flight; Start reads the
rows of runs with no run row, queues each ``pending`` turn again from its stored strings and puts the others back
to waiting.  ``set_teacher`` is consulted when a turn answers and, after a Start, for every run restored waiting.

The session's own configuration
-------------------------------
Each session has its own evolving configuration (the configuration entity of
``server/services/configurations.py``), created with the session in its creation transaction:
the base (``settings.configuration_base``: ``training-v2``, the default, which is the Training Mode
Base Configuration, v2.0 of ``training_base/v2.0/``; ``global``; ``standard``; or ``{"session_id": n}``)
plus the creation overrides, which are ``settings.parameters`` folded in once as one creation
batch.  The result is the session's Starting Conceptual State; the stored ``settings.parameters``
stays as the record, and a task carries no overrides.  Nothing in a session reads or writes
Metacat Mode's configuration apart from that one read of the global configuration at creation.

A live session holds that configuration in memory as a ``LiveConfiguration``
(``session_live_config.py``) on an ``EpisodeLog``: one counter, the episode version, over
Episodic Memory and the whole configuration, and the configuration revision (the entity's own
counter, the compare-and-set token).  A run takes a ``ConfigRef`` with its ``MemoryRef`` when it
is dispatched (the provider, its ``config_hash`` and revision, the episode version) and records
them.  When a run finishes (``_record``) an entry is made, in completion order: the memory
merge, then the in-worker learner's batch (the run's ``proposals``: the nodes and links its
codelets built in the run's own Slipnet and the ops they proposed for the next turn, one op
per row, actor ``learner:in-worker``), then one version.  The batch of
the after-run seam (``set_after_run``; none ships), if it returns ops, rides that entry when the
run made no proposals (actor ``learner:after-run``), and is a second entry straight after it when
the run did, so the journal names the learning source of every op.  An external or Admin batch (``submit_changes`` / ``apply_live``) is an entry with no
memory part; it reaches runs dispatched after it, never one in flight.  Every entry that
changed the configuration is held as a ``journal.PendingEntry`` until the Stop write, which is
S5's.  The configuration store reads a live session through the live source this service
registers (``LiveState``), and ``ChangeService.apply`` hands a live session's batch to
``apply_live``.

Errors
------
Nothing pauses, adopts or rebases automatically (``on_config_change`` is removed): a session
stalls only when its own configuration cannot start a run (the run-start check), and resumes when
a change makes it able to.  The rest of the error policy (``on_run_error``, ``max_errors_*``,
``on_worker_failure``, ``max_retries``) acts as the API contract says and writes a human sentence
to ``last_event``.
"""

from __future__ import annotations

import asyncio
import logging
import pickle
import time
import uuid
from collections import Counter, deque
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable

from sqlalchemy import case, cast, delete, exists, false, func, insert, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from server.engine.memory import EpisodicMemory
from server.engine.metadata import MetadataProvider
from server.engine.parameters import UnknownParameter, validate_overrides
from server.engine.runner import STATUS_ANSWER_FOUND
from server.engine.start_check import RunStartError, require_run_start
from server.models.journal import (
    Configuration, ConfigurationSnapshot, JournalEntry, KIND_SESSION,
)
from server.models.training_mode_session import (
    SessionMemoryMerge, SessionMemorySnapshot, TrainingModeSession, TrainingModeSessionProblem,
    TrainingModeSessionRun, TrainingModeSessionTurn,
)
from server.services import config_document as cd
from server.services import configuration_store as store
from server.services import configurations, journal
from server.services import training_mode_session_memory as tm
from server.services import turn_record
from server.services.problem_text import ProblemTextError, check_problem_mapping, check_string
from server.services.session_live_config import ConfigRef, LiveConfiguration
from server.services.training_mode_session_executor import (
    SessionTask,
    available_backend_names,
    create_executor,
    default_session_backend,
)

#: The names of the learning sources whose batches ride a run's finish, as the journal's actor
#: ``learner:<name>`` (the source is ``learner``): the in-worker learner, which submits the
#: nodes a run made, and the after-run seam (``set_after_run``).
IN_WORKER_LEARNER = "in-worker"
AFTER_RUN_LEARNER = "after-run"

logger = logging.getLogger("petacat.session")

NONE_KEY = "*NONE*"
CAP_KEY = "*CAP*"
ERROR_KEY = "*ERROR*"
MAX_PROBLEMS_PER_REQUEST = 10_000
MAX_SEEDS_PER_PROBLEM = 100_000
MAX_CODELETS_LIMIT = 200_000
RATE_WINDOW = 30.0
INSERT_CHUNK = 2000
RUN_ROW_CHUNK = 2000
#: Merge blobs the scheduler keeps for task tails.
MERGE_KEEP = 1024
INT32_MAX = 2_147_483_647
#: Seconds a Stop waits for runs in flight to finish and merge before it discards them.
DRAIN_TIMEOUT = 10.0
#: Seconds a graceful shutdown waits for every live session to be stopped.
SHUTDOWN_STOP_TIMEOUT = 120.0
#: Sessions a graceful shutdown stops at once.
SHUTDOWN_STOP_CONCURRENCY = 4

DEFAULT_POLICY: dict[str, Any] = {
    "on_run_error": "record",
    "max_errors_per_problem": None,
    "max_errors_total": None,
    "on_worker_failure": "retry",
    "max_retries": 3,
}
_POLICY_CHOICES = {
    "on_run_error": ("record", "skip_problem", "pause", "cancel"),
    "on_worker_failure": ("retry", "pause"),
}
_SETTINGS_KEYS = (
    "seeds_per_problem", "seed_start", "max_codelets", "parameters", "backend", "configuration_base",
)


class SessionError(Exception):
    """An error with an HTTP meaning (the API turns it into an HTTPException)."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


class StaleInput(SessionError):
    """409 ``stale``: an input (or an end) for a run that is not waiting for that turn: a duplicate, a late
    call, a run that has ended or never answered, or the wrong turn number."""

    def __init__(self, detail: str) -> None:
        super().__init__(409, f"stale: {detail}")


def _busy(session_id: int, what: str, state: str) -> SessionError:
    """409 ``busy``: the session is Starting or Stopping and refuses *what* until that ends."""
    return SessionError(409, f"busy: session {session_id} is {state}; wait for it to finish before you {what}")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def normalize_policy(partial: dict | None, base: dict | None = None) -> dict[str, Any]:
    """Merge a partial policy onto *base* (defaults), validating every value (400)."""
    policy = dict(base or DEFAULT_POLICY)
    for key, value in (partial or {}).items():
        if key not in DEFAULT_POLICY:
            raise SessionError(400, f"unknown policy field {key!r}; known: {sorted(DEFAULT_POLICY)}")
        if key in _POLICY_CHOICES:
            if value not in _POLICY_CHOICES[key]:
                raise SessionError(400, f"policy {key} must be one of {list(_POLICY_CHOICES[key])}")
        elif key == "max_retries":
            if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 1000:
                raise SessionError(400, "policy max_retries must be an integer 0..1000")
        else:  # max_errors_*
            if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 1):
                raise SessionError(400, f"policy {key} must be null or an integer >= 1")
        policy[key] = value
    return policy


def run_key(o: Any, max_codelets: int) -> str:
    """The outcome key: the answer, else ``*ERROR*`` / ``*CAP*`` / ``*NONE*``."""
    if o.error:
        return ERROR_KEY
    if o.status == STATUS_ANSWER_FOUND and o.answer:
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
    configuration_revision: int | None = None
    seq: int = 0
    memory_version: int = 0
    added_answers: int = 0
    added_snags: int = 0
    problem_id: int = 0


@dataclass
class TurnSpec:
    """The four strings a turn runs on, before it has run: the turn number, its context, second string and
    input, and who supplied the input.  Turn 1's are the problem's; a later turn's come from the window
    (``turn_record.next_window``)."""

    turn: int
    context: str
    second: str
    input: str
    input_from: str


@dataclass
class TurnRec:
    """A finished turn (or, with ``status == "pending"``, one that is queued or in flight): one row of
    ``training_mode_session_turns``.  ``answer`` is the Workspace's answer string; the **response** is it when
    the turn's status is ``answer_found`` and it is not empty (:attr:`response`)."""

    turn: int
    turn_seed: int
    context: str
    second: str
    input: str
    input_from: str
    status: str = "pending"
    answer: str = ""
    answers: list = field(default_factory=list)
    answer_quality: float | None = None
    codelets: int = 0
    seconds: float = 0.0
    temperature: float = 0.0
    error: str | None = None
    attempts: int = 1
    end_reason: str | None = None
    end_label: str | None = None
    proposals: list = field(default_factory=list)
    evidence: dict | None = None
    seq: int | None = None
    memory_version: int | None = None
    configuration_revision: int | None = None
    config_hash: str = ""
    added_answers: int = 0
    added_snags: int = 0

    @property
    def response(self) -> str | None:
        """What Petacat constructed in the 4th position, or ``None`` when the turn gave no answer."""
        return self.answer if self.status == STATUS_ANSWER_FOUND and self.answer else None


@dataclass(eq=False)
class LiveRun:
    """One run (a problem at one seed) of a live session: its turns so far, and where it stands.

    ``state`` is ``running`` (a turn is queued or in flight: ``pending`` holds its strings, except for turn 1,
    which has none until it has run once), ``waiting`` (the last turn answered, and the run holds no worker
    until the teacher sends the next input or ends it) or ``ended`` (``end_reason`` on the last turn says why).
    A run exists in memory from its first finished turn."""

    problem_id: int
    seed: int
    multi_turn: bool
    turns: list = field(default_factory=list)
    pending: TurnSpec | None = None
    state: str = "running"

    @property
    def waiting_for(self) -> int | None:
        return len(self.turns) + 1 if self.state == "waiting" else None


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
    """A problem of a live session.  ``id`` is its per-session ordinal (the API's ``problem_id``)."""

    id: int
    session_id: int
    initial: str
    modified: str
    target: str
    answer: str | None
    seeds: int
    seed_start: int
    tag: Any = None
    added_at: datetime = field(default_factory=_utcnow)
    #: Each run is a chat: a turn per engine run while the teacher supplies inputs.
    multi_turn: bool = False
    #: Every run of the problem that has finished a turn since Start (or was restored at Start), by seed.
    run_logs: dict = field(default_factory=dict)
    #: ``queued`` (which includes running: see ``started``), ``finished`` or ``cancelled``.
    status: str = "queued"
    #: The database holds a row for it (it existed at Start); otherwise the Stop write inserts it.
    stored: bool = False
    #: Seeds with a turn not yet dispatched: a fresh seed (turn 1), or a run whose next turn is queued (its input
    #: arrived, or it was put back by a failure or a Stop); a failed one goes back on the front.
    todo: deque = field(default_factory=deque)
    inflight: int = 0
    outcomes: dict[int, RunRec] = field(default_factory=dict)
    #: Failed attempts per seed (worker failures), for ``max_retries``.
    failures: dict[int, int] = field(default_factory=dict)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    finished_seq: int | None = None
    cancelled: bool = False
    #: ``summarize`` of the outcomes and the counts the session summary adds, fixed when the
    #: problem finishes or is cancelled.
    tally: dict | None = None
    counts: tuple = (0, 0, 0, 0, 0)

    @property
    def started(self) -> bool:
        return self.started_at is not None

    @property
    def settled(self) -> bool:
        return self.status != "queued"


@dataclass(eq=False)
class Sub:
    """One dispatched run (compared and hashed by identity)."""

    lt: "LiveSession"
    lp: LiveProblem
    seed: int
    version: int
    config_hash: str
    failures: int
    #: Re-run alone after a pool break (see ``_worker_failed``).
    isolated: bool = False
    #: A Stop discarded it: its outcome is ignored when it arrives.
    dropped: bool = False
    #: The turn this dispatch runs, and its strings.
    turn: int = 1
    spec: Any = None
    #: The configuration the run was dispatched under (a ``ConfigRef``'s revision and provider).
    configuration_revision: int | None = None
    provider: Any = None


@dataclass
class LiveSession:
    """Everything a live (Starting-loaded, Running, Paused or Stopping) session holds.

    Nothing here is in the database until the Stop write: the pending lists, the problems and
    their outcomes, the name, note and policy as edited, the counters.  ``base`` is the
    stored tally of the problems that were finished or cancelled at Start, which a live
    session never changes.
    """

    id: int
    #: ``running``, ``paused`` or ``stopping``; a session that is not live is Stopped.
    status: str
    name: str
    note: str
    seeds_per_problem: int
    seed_start: int
    max_codelets: int
    parameters: dict | None
    backend: str
    policy: dict
    created_at: datetime | None = None
    updated_at: datetime | None = None
    #: The last Stop the database holds (what ``saved_through`` reports).
    stopped_at: datetime | None = None
    stopped_from: str | None = None
    stop_reason: str | None = None
    saved_version: int = 0
    stalled_reason: str | None = None
    last_event: str | None = None
    #: The session's own evolving configuration (``None`` only while it is being loaded).
    config: LiveConfiguration | None = None
    #: ``(provider, why a run cannot start under it or None)``: the run-start check, once per
    #: configuration.
    start_check: tuple | None = None
    configuration_base: Any = "training-v2"
    queue: deque = field(default_factory=deque)        # LiveProblem not yet started
    active: dict = field(default_factory=dict)         # pid -> LiveProblem, started and unfinished
    problems: dict = field(default_factory=dict)       # pid -> LiveProblem, every one since Start
    unsubmitted: int = 0
    completions: deque = field(default_factory=deque)
    cancelled: bool = False
    errors_total: int = 0
    #: Next per-session problem ordinal and next ``finished_seq`` to hand out.
    next_problem_id: int = 1
    finished_count: int = 0
    #: Problems finished or cancelled since Start that were given a ``finished_seq``, in order.
    finished_log: list = field(default_factory=list)
    #: Stored tally of the problems finished (``fin``) and cancelled (``can``) at Start:
    #: (problems, seeds, runs_done, errors, codelets, capped, retries).
    base_fin: tuple = (0,) * 7
    base_can: tuple = (0,) * 7
    #: Name, note and policy edits held in memory.
    edits: int = 0
    inflight_subs: set = field(default_factory=set)
    # -- the Episodic Memory --
    memory: EpisodicMemory = field(default_factory=EpisodicMemory)
    version: int = 0
    epoch: str = field(default_factory=lambda: uuid.uuid4().hex)
    merge_blobs: dict = field(default_factory=dict)    # seq -> pickled Additions
    snapshot: tuple | None = None                      # (version, blob)
    pending_runs: list = field(default_factory=list)   # RunRec committed in memory, not in the DB
    pending_merges: list = field(default_factory=list) # (seq, problem_id, seed, Additions)
    want_snapshot: set = field(default_factory=set)    # (pid, seed) whose worker needs one
    #: Runs waiting for the teacher's next input (no worker held); runs changed since Start or the last
    #: write, whose turn rows the Stop write stores.
    waiting: int = 0
    dirty_runs: set = field(default_factory=set)

    @property
    def meta(self) -> MetadataProvider | None:
        """The provider of the configuration as it stands (what the next run is dispatched under)."""
        return self.config.provider if self.config is not None else None

    @property
    def config_hash(self) -> str:
        return self.config.config_hash if self.config is not None else ""

    @property
    def schedulable(self) -> bool:
        return (
            self.config is not None and not self.cancelled and self.stalled_reason is None
            and self.status == "running"
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

    def unsaved(self) -> dict[str, int]:
        """What only memory holds: the Stop write would write it."""
        return {
            "runs": len(self.pending_runs),
            "merges": len(self.pending_merges),
            "problems": sum(1 for lp in self.problems.values() if not lp.stored),
            "outcomes": sum(1 for lp in self.problems.values() if lp.settled),
            "edits": self.edits,
            "configuration_batches": len(self.config.changes) if self.config is not None else 0,
        }

    def memory_ref(self, tail_depth: int, snapshot: bool) -> tm.MemoryRef:
        """The memory a run dispatched now starts from."""
        ref = tm.MemoryRef(self.id, self.epoch, self.version)
        if snapshot:
            if self.snapshot is None or self.snapshot[0] != self.version:
                self.snapshot = (self.version, tm.snapshot_blob(self.memory))
            ref.snapshot = self.snapshot[1]
            return ref
        ref.tail_from = max(0, self.version - tail_depth)
        # A session that was just Started holds no merge blob for the versions before its Start
        # (the Start read loads the memory snapshot and replays nothing): the tail begins at the
        # first version held, and a worker that cannot reach it asks for a snapshot.
        while ref.tail_from < self.version and (ref.tail_from + 1) not in self.merge_blobs:
            ref.tail_from += 1
        ref.tail = [self.merge_blobs[v] for v in range(ref.tail_from + 1, self.version + 1)]
        return ref


# ---------------------------------------------------------------------------
# The service
# ---------------------------------------------------------------------------


class TrainingModeSessionService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        meta_provider: Callable[[], MetadataProvider],
        executor: Any = None,
    ) -> None:
        self._factory = session_factory
        self._meta_provider = meta_provider
        self._executor = executor
        self._live: dict[int, LiveSession] = {}
        #: Sessions being loaded by ``start_session`` (the Starting state).
        self._starting: set[int] = set()
        self._rr = 0
        self._inflight_runs = 0
        #: Runs to re-run one at a time after a pool break: (session, problem, seed).
        self._isolation: deque = deque()
        self._isolated_inflight = 0
        #: Completed futures handed over by the executor's threads, merged by ``_drain``.
        self._done_queue: deque = deque()
        self._wake: asyncio.Event | None = None
        self._task: asyncio.Task | None = None
        self._tasks: set[asyncio.Task] = set()
        self._versions: dict[int, int] = {}
        self._conds: dict[int, asyncio.Condition] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stopped = True
        #: True once a graceful shutdown has begun: no session may be started.
        self._closing = False
        #: The after-run seam, one optional callable per session (none ships): see
        #: :meth:`set_after_run`.
        self._after_run: dict[int, Callable[..., Any]] = {}
        #: The teacher, one optional callable per session: see :meth:`set_teacher`.
        self._teachers: dict[int, Callable[..., Any]] = {}
        #: Seconds a Stop waits for runs in flight before it discards them.
        self.drain_timeout = DRAIN_TIMEOUT
        #: Seconds a graceful shutdown waits for the live sessions to be stopped.
        self.shutdown_stop_timeout = SHUTDOWN_STOP_TIMEOUT
        #: Test hook: ``(problem, seed, failures) -> "error" | "kill" | None``.
        self.fault_hook: Callable[[LiveProblem, int, int], str | None] | None = None
        #: Bytes of memory shipped with tasks (sum, count), for the overhead measurement.
        self.task_memory_bytes = [0, 0]

    # -- life cycle ---------------------------------------------------------

    @property
    def executor(self):
        return self._executor

    async def start(self) -> None:
        """Start the scheduler.  Every Training Mode Session is Stopped: nothing is loaded until it is started."""
        self._loop = asyncio.get_running_loop()
        self._wake = asyncio.Event()
        if self._executor is None:
            self._executor = create_executor()
        self._stopped = False
        self._closing = False
        # Live sessions' configurations are read, and their batches applied, through the one
        # configuration store and writer; a session is found here while it is live.
        store.set_live_source(self._live_state, self.apply_live)
        self._task = asyncio.create_task(self._run(), name="session-scheduler")
        self._wake.set()

    async def stop(self) -> None:
        """Graceful shutdown: refuse new Starts, Stop every live session (concurrently, up to a
        limit, each with ``stop_reason = shutdown``), then close the scheduler and the executor.

        ``shutdown_stop_timeout`` abandons the sessions still being stopped; they are lost back to
        their last Stop, exactly as in a crash, and the log says which and how much."""
        self._closing = True
        live = list(self._live.values())
        if live and not self._stopped:
            gate = asyncio.Semaphore(SHUTDOWN_STOP_CONCURRENCY)

            async def one(lt: LiveSession) -> None:
                async with gate:
                    try:
                        await self.stop_session(lt.id, reason="shutdown")
                        logger.info("shutdown: session %d stopped", lt.id)
                    except Exception:  # noqa: BLE001 - one failed Stop must not keep the others waiting
                        logger.exception("shutdown: stopping session %d failed", lt.id)

            try:
                await asyncio.wait_for(asyncio.gather(*(one(lt) for lt in live)), self.shutdown_stop_timeout)
            except asyncio.TimeoutError:
                pass
            for lt in self._live.values():
                logger.error("shutdown: session %d was not stopped; its unsaved work (%s) is lost",
                             lt.id, lt.unsaved())
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
        self._starting.clear()
        store.set_live_source(None)
        if self._executor is not None:
            self._executor.close()

    @staticmethod
    def _start_problem(lt: LiveSession) -> str | None:
        """Why the session's configuration cannot start a run (the run-start check), or ``None``.

        Computed once per provider: the configuration changes only when an entry changes it."""
        meta = lt.meta
        cached = lt.start_check
        if cached is None or cached[0] is not meta:
            try:
                require_run_start(meta)
                reason = None
            except RunStartError as exc:
                reason = str(exc)
            cached = lt.start_check = (meta, reason)
        return cached[1]

    def _new_live(self, t: TrainingModeSession) -> LiveSession:
        return LiveSession(
            id=t.id, status="running", name=t.name, note=t.note or "",
            seeds_per_problem=t.seeds_per_problem, seed_start=t.seed_start,
            max_codelets=t.max_codelets, parameters=t.parameters, backend=t.backend,
            policy=normalize_policy(t.policy), configuration_base=t.configuration_base,
            created_at=t.created_at, updated_at=t.updated_at, stopped_at=t.stopped_at,
            stopped_from=t.stopped_from, stop_reason=t.stop_reason, last_event=t.last_event,
            next_problem_id=t.next_problem_id, finished_count=t.finished_count,
        )

    def _add_live_problem(self, lt: LiveSession, *, problem_id: int, spec: Any, stored: bool,
                          done: dict[int, RunRec] | None = None) -> LiveProblem:
        """Queue a problem in memory.  *spec* is a stored row or a request dict (both give the fields)."""
        get = spec.get if isinstance(spec, dict) else (lambda k, d=None: getattr(spec, k, d))
        seeds = get("seeds") or lt.seeds_per_problem
        seed_start = get("seed_start") if get("seed_start") is not None else lt.seed_start
        lp = LiveProblem(
            id=problem_id, session_id=lt.id, initial=get("initial"), modified=get("modified"),
            target=get("target"), answer=get("answer"), seeds=seeds, seed_start=seed_start,
            tag=get("tag"), added_at=get("added_at") or _utcnow(), stored=stored,
            multi_turn=bool(get("multi_turn")),
        )
        if done:
            lp.outcomes.update(done)
        lp.todo = deque(s for s in range(seed_start, seed_start + seeds) if s not in lp.outcomes)
        lt.queue.append(lp)
        lt.problems[lp.id] = lp
        lt.unsubmitted += len(lp.todo)
        return lp

    @staticmethod
    async def _stored_totals(s: AsyncSession, ids: list[int]) -> dict[int, dict[str, tuple]]:
        """Per session and stored status: (problems, seeds, runs_done, errors, codelets, capped, retries)."""
        P = TrainingModeSessionProblem
        rows = (await s.execute(
            select(
                P.session_id, P.status, func.count(),
                func.coalesce(func.sum(P.seeds), 0), func.coalesce(func.sum(P.runs_done), 0),
                func.coalesce(func.sum(P.errors), 0), func.coalesce(func.sum(P.codelets_total), 0),
                func.coalesce(func.sum(P.capped), 0), func.coalesce(func.sum(P.retries), 0),
            ).where(P.session_id.in_(ids)).group_by(P.session_id, P.status)
        )).all()
        out: dict[int, dict[str, tuple]] = {}
        for sid, status, *vals in rows:
            out.setdefault(sid, {})[status] = tuple(int(v) for v in vals)
        return out

    async def _load_one(self, s: AsyncSession, t: TrainingModeSession) -> LiveSession:
        """The Start read: build the live part of a Stopped session from the database.

        Reads only, and reads back what the Stop write stored, replaying nothing:

        * the session row (settings, policy, counters, ``last_change_version``);
        * the Episodic Memory snapshot (no merge row is read);
        * the unfinished problems with the runs stored for them, so they resume at the seeds not
          yet run;
        * the configuration's stored current state, checked against its stored ``config_hash``
          (no journal row is read; a mismatch refuses the Start).
        """
        lt = self._new_live(t)
        snap = (await s.execute(
            select(SessionMemorySnapshot).where(SessionMemorySnapshot.session_id == t.id)
        )).scalar_one_or_none()
        if snap is not None:
            lt.memory = tm.memory_from_snapshot(snap.data)
            lt.version = snap.version
            lt.snapshot = (snap.version, snap.data)
        lt.saved_version = lt.version
        P = TrainingModeSessionProblem
        problems = (await s.execute(
            select(P).where(P.session_id == t.id, P.status == "queued").order_by(P.problem_id)
        )).scalars().all()
        stored: dict[int, dict[int, RunRec]] = {}
        if problems:
            runs = (await s.execute(
                select(TrainingModeSessionRun).join(
                    P, (P.session_id == TrainingModeSessionRun.session_id)
                    & (P.problem_id == TrainingModeSessionRun.problem_id))
                .where(TrainingModeSessionRun.session_id == t.id, P.status == "queued")
            )).scalars().all()
            for r in runs:
                stored.setdefault(r.problem_id, {})[r.seed] = self._rec_from_row(r)
        unfinished = await self._stored_unfinished_runs(s, t.id) if problems else {}
        for p in problems:
            lp = self._add_live_problem(lt, problem_id=p.problem_id, spec=p, stored=True,
                                        done=stored.get(p.problem_id))
            lt.errors_total += sum(1 for r in lp.outcomes.values() if r.error)
            self._restore_runs(lt, lp, unfinished.get(p.problem_id, {}))
        totals = (await self._stored_totals(s, [t.id])).get(t.id, {})
        zero = (0,) * 7
        lt.base_fin, lt.base_can = totals.get("finished", zero), totals.get("cancelled", zero)
        lt.errors_total += lt.base_fin[3] + lt.base_can[3]
        await self._load_configuration(s, lt, t)
        return lt

    @staticmethod
    def _turn_from_row(r: Any) -> TurnRec:
        return TurnRec(
            turn=r.turn, turn_seed=r.turn_seed, context=r.context, second=r.second_string, input=r.input,
            input_from=r.input_from, status=r.status, answer=r.answer or "", answers=list(r.answers or []),
            answer_quality=r.answer_quality, codelets=r.codelets, seconds=r.seconds, temperature=r.temperature,
            error=r.error, attempts=r.attempts, end_reason=r.end_reason, end_label=r.end_label,
            proposals=list(r.proposals or []), evidence=r.evidence, seq=r.seq, memory_version=r.memory_version,
            configuration_revision=r.configuration_revision, config_hash=r.config_hash,
            added_answers=r.added_answers, added_snags=r.added_snags,
        )

    async def _stored_unfinished_runs(self, s: AsyncSession, session_id: int) -> dict[int, dict[int, list]]:
        """The turn rows of the runs that have not ended (no run row yet): problem -> seed -> turns in order.
        A run with a ``pending`` last row is run again from it; one whose last row answered is waiting."""
        T, R = TrainingModeSessionTurn, TrainingModeSessionRun
        rows = (await s.execute(
            select(T).where(
                T.session_id == session_id,
                ~exists().where(
                    R.session_id == T.session_id, R.problem_id == T.problem_id, R.seed == T.seed),
            ).order_by(T.problem_id, T.seed, T.turn)
        )).scalars().all()
        out: dict[int, dict[int, list]] = {}
        for r in rows:
            out.setdefault(r.problem_id, {}).setdefault(r.seed, []).append(self._turn_from_row(r))
        return out

    def _restore_runs(self, lt: LiveSession, lp: LiveProblem, runs: dict[int, list]) -> None:
        """Bring the unfinished runs of a problem back at Start: a run whose last turn was ``pending`` is
        queued to run that turn again from its stored strings, and one whose last turn answered waits."""
        for seed, turns in runs.items():
            run = LiveRun(problem_id=lp.id, seed=seed, multi_turn=lp.multi_turn)
            last = turns[-1]
            if last.status == "pending":
                run.turns = turns[:-1]
                run.pending = TurnSpec(last.turn, last.context, last.second, last.input, last.input_from)
                run.state = "running"
                if seed in lp.todo:  # no outcome, so ``_add_live_problem`` queued it for turn 1
                    lp.todo.remove(seed)
                else:
                    lt.unsubmitted += 1
                lp.todo.appendleft(seed)  # a turn in progress is dispatched before a fresh seed
            else:
                run.turns = turns
                run.state = "waiting"
                if seed in lp.todo:  # no outcome, so ``_add_live_problem`` queued it for turn 1
                    lp.todo.remove(seed)
                    lt.unsubmitted -= 1
                lt.waiting += 1
            lp.run_logs[seed] = run

    @staticmethod
    async def _load_configuration(s: AsyncSession, lt: LiveSession, t: TrainingModeSession) -> None:
        """Load the session's configuration into ``lt.config`` (a read).

        The configuration's row is locked first, so a stored write to a Stopped session's
        configuration that began just before this Start is complete before the document is read,
        and one that begins after it finds the session live and goes to memory."""
        C = Configuration.__table__
        row = (await s.execute(
            select(C).where(C.c.session_id == t.id, C.c.kind == KIND_SESSION).with_for_update()
        )).mappings().first()
        if row is None:
            raise SessionError(500, f"session {t.id} has no configuration; clear the database and recreate it")
        document = await configurations.current_document(s, row["id"])
        stored, found = row["config_hash"], cd.config_hash(document)
        if stored != found:
            raise SessionError(
                409, f"the config_hash check failed: session {t.id}'s stored configuration state "
                     f"hashes to {found} but its configuration row records {stored}; the session "
                     "stays Stopped (verify-journal on its configuration shows where they differ)")
        lt.config = LiveConfiguration(
            document, configuration_id=row["id"], revision=row["revision"],
            episode_version=lt.version, base_hash=row["base_snapshot_hash"], frozen=row["frozen"],
            last_change_version=t.last_change_version, saved_at=t.stopped_at,
        )

    @staticmethod
    def _rec_from_row(r: Any) -> RunRec:
        return RunRec(
            seed=r.seed, status=r.status, key=r.key, answer=r.answer, answers=list(r.answers or []),
            codelets=r.codelets, seconds=r.seconds, temperature=r.temperature,
            answer_quality=r.answer_quality, error=r.error, config_hash=r.config_hash,
            attempts=r.attempts, seq=r.seq, memory_version=r.memory_version,
            added_answers=r.added_answers, added_snags=r.added_snags, problem_id=r.problem_id,
            configuration_revision=r.configuration_revision,
        )

    def wake(self) -> None:
        if self._wake is not None:
            self._wake.set()

    # -- the configuration a run starts under: the session's own -------------

    def _check_configs(self) -> None:
        """Stall a session whose own configuration cannot start a run, and resume it when it can.

        Each live session runs under its own configuration (``lt.config``), which only its own
        entries change; nothing here binds a configuration to it (``on_config_change`` is gone).
        """
        for lt in self._live.values():
            if lt.cancelled or lt.config is None:
                continue
            problem = self._start_problem(lt)
            if problem is not None:
                if lt.stalled_reason is None:
                    lt.last_event = f"stalled: {problem}"
                lt.stalled_reason = problem
            elif lt.stalled_reason is not None:
                lt.stalled_reason = None
                lt.last_event = "resumed: the engine configuration can start a run again"

    # -- the scheduler ------------------------------------------------------

    async def _run(self) -> None:
        assert self._wake is not None
        while True:
            # Also on a timer: a stalled session must notice the configuration returning
            # without anything else happening (``_fill`` re-checks the configuration).
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
                logger.exception("session scheduler pass failed")
                await asyncio.sleep(1.0)
                self._wake.set()

    def _window(self) -> int:
        # A run starts as soon as it is dispatched, so a worker is never handed a run
        # before the previous one has merged.
        return max(1, self._executor.workers)

    def _pick(self) -> tuple[LiveSession, LiveProblem] | None:
        sessions = [lt for lt in self._live.values() if lt.schedulable]
        if not sessions:
            return None
        for i in range(len(sessions)):
            lt = sessions[(self._rr + i) % len(sessions)]
            lp = lt.next_problem()
            if lp is not None:
                self._rr = (self._rr + i + 1) % len(sessions)
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
            self._check_configs()  # cheap (identity compare): a long dispatch run must notice too
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

    async def _submit(self, lt: LiveSession, lp: LiveProblem, seed: int,
                      isolated: bool = False) -> None:
        """Hand one run to the executor.

        **When a run's memory copy is taken.**  A run starts from the master
        as it is *at the moment this method builds the run's* ``MemoryRef`` (below): every
        outcome that had completed has been merged first (``_fill`` drains them), and the
        version is recorded as the run's ``memory_version``.  The session owns its pool
        and keeps at most one run per worker in flight, so a dispatched run starts at once
        and no merge can land between this moment and the worker beginning it; the worker
        takes its copy of exactly that version when it begins.  A merge that completes
        later reaches only runs dispatched after it.
        """
        failures = lp.failures.get(seed, 0)
        snapshot = (lp.id, seed) in lt.want_snapshot
        lt.want_snapshot.discard((lp.id, seed))
        depth = max(tm.MIN_TAIL, 4 * self._executor.workers)
        # The run's two inputs, taken at one moment (nothing awaits between them): the Episodic
        # Memory and the session's configuration, both as of the same episode version.
        ref = lt.memory_ref(depth, snapshot)
        cref = lt.config.ref(lt.id)
        blob = len(ref.snapshot) if ref.snapshot is not None else sum(len(b) for b in ref.tail)
        self.task_memory_bytes[0] += blob
        self.task_memory_bytes[1] += 1
        fault = self.fault_hook(lp, seed, failures) if self.fault_hook else None
        # The turn this dispatch runs: the next turn of a run that is part-way through (its strings come
        # from the window, and it runs under ``turn_record.turn_seed``), else turn 1 of the problem.
        run = lp.run_logs.get(seed)
        spec = run.pending if run is not None and run.pending is not None else TurnSpec(
            1, lp.initial, lp.modified, lp.target, turn_record.FROM_PROBLEM)
        # The task carries no parameter overrides: ``settings.parameters`` was folded into the
        # session's configuration at creation, and learning may have changed it since.
        task = SessionTask(
            spec.context, spec.second, spec.input, lp.answer if spec.turn == 1 else None,
            turn_record.turn_seed(seed, spec.turn), lt.max_codelets,
            None, lt.backend, memory=ref, fault=fault,
        )
        sub = Sub(lt, lp, seed, ref.version, cref.config_hash, failures, isolated,
                  configuration_revision=cref.configuration_revision, provider=cref.provider,
                  turn=spec.turn, spec=spec)
        lt.inflight_subs.add(sub)
        self._inflight_runs += 1
        if isolated:
            self._isolated_inflight += 1
        try:
            future = await asyncio.to_thread(self._executor.submit, [task], cref.provider)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("session executor refused a run")
            self._inflight_runs -= 1
            if isolated:
                self._isolated_inflight -= 1
            lt.inflight_subs.discard(sub)
            if not sub.dropped:
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
        sub.lt.inflight_subs.discard(sub)
        if sub.dropped:
            return  # a Stop discarded it; its seed was put back
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

    def _requeue(self, lt: LiveSession, lp: LiveProblem, seed: int) -> None:
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
        are deterministic (a run is re-dispatched at the then-current version).
        """
        lt, lp, seed = sub.lt, sub.lp, sub.seed
        lp.inflight -= 1
        logger.warning("session %d problem %d seed %d: worker failure %r", lt.id, lp.id, seed, exc)
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
        """A turn finished: its one ``finish_run`` entry, its turn row, and what happens to the run.

        The turn's memory merge and its in-worker learner batch land here, before anything of the run is
        dispatched again, so the run's later turns (and every other run) start under what this turn left.
        A turn that answers, in a multi-turn problem, makes the run wait for input (no worker held) and
        consults the session's teacher; any other turn ends the run (``_end_run``)."""
        lt, lp = sub.lt, sub.lp
        lp.inflight -= 1
        if lp.cancelled or lt.cancelled:
            return  # the problem was cancelled while this run was in flight: dropped
        blob = o.additions
        adds = pickle.loads(blob) if blob else tm.Additions()
        # Entries, in completion order (the scheduler is one thread of control, so this is the
        # session's lock).  The run-finish entry holds the memory merge and the in-worker
        # learner's batch (the nodes the run made, one op per row); then the batch of the
        # after-run seam, if one is set and returned ops, is a second entry straight after,
        # so the journal names the learning source of every op (``learner:in-worker``
        # and ``learner:after-run``).  With no proposals the seam's batch rides the run-finish
        # entry as it always did.  The entry's run is the run's own seed, whatever turn it is.
        proposed = self._proposal_batch(o, seed=sub.seed, turn=sub.turn)
        seam = self._learner_batch(sub, o)
        finished = lt.config.finish_run(
            memory_merge=lambda: tm.apply_merge(lt.memory, adds),
            batch=proposed if proposed is not None else seam,
            run=(lp.id, sub.seed), started_revision=sub.configuration_revision,
            learner=IN_WORKER_LEARNER if proposed is not None else AFTER_RUN_LEARNER,
        )
        n_a, n_s = finished.memory
        if proposed is not None and seam is not None:
            second = lt.config.finish_run(
                memory_merge=None, batch=seam, run=(lp.id, sub.seed),
                started_revision=sub.configuration_revision, learner=AFTER_RUN_LEARNER,
            )
            lt.version = second.version
        else:
            lt.version = finished.version
        merged_at = finished.version  # the entry that holds this turn's memory merge
        lt.merge_blobs[merged_at] = blob or tm.dump_additions(adds)
        lt.merge_blobs.pop(merged_at - MERGE_KEEP, None)
        lt.pending_merges.append((merged_at, lp.id, sub.seed, adds))
        spec = sub.spec
        turn = TurnRec(
            turn=sub.turn, turn_seed=o.seed, context=spec.context, second=spec.second, input=spec.input,
            input_from=spec.input_from, status=o.status, answer=o.answer, answers=list(o.answers),
            answer_quality=o.answer_quality, codelets=o.codelets, seconds=o.seconds,
            temperature=o.temperature, error=o.error, attempts=sub.failures + 1,
            proposals=[dict(p) for p in (getattr(o, "proposals", None) or ())],
            evidence=getattr(o, "evidence", None), seq=merged_at, memory_version=sub.version,
            configuration_revision=sub.configuration_revision, config_hash=sub.config_hash,
            added_answers=n_a, added_snags=n_s,
        )
        run = lp.run_logs.get(sub.seed)
        if run is None:
            run = lp.run_logs[sub.seed] = LiveRun(lp.id, sub.seed, lp.multi_turn)
        run.turns.append(turn)
        run.pending = None
        lt.dirty_runs.add(run)
        lp.failures.pop(sub.seed, None)
        if lp.multi_turn and turn.response is not None and not o.error:
            run.state = "waiting"
            lt.waiting += 1
            self._consult_teacher(lt, lp, run)
            return
        if o.error:
            reason = turn_record.END_ERROR
        elif turn.response is None:
            reason = turn_record.END_NO_ANSWER
        else:
            reason = turn_record.END_SINGLE_TURN
        self._end_run(lt, lp, run, reason)

    @staticmethod
    def _turn_key(t: TurnRec, max_codelets: int) -> str:
        """The outcome key of a turn (``run_key``'s rule, on a turn)."""
        if t.error:
            return ERROR_KEY
        if t.response is not None:
            return t.answer
        if t.codelets >= max_codelets:
            return CAP_KEY
        return NONE_KEY

    def _end_run(self, lt: LiveSession, lp: LiveProblem, run: LiveRun, reason: str,
                 label: str | None = None) -> None:
        """The run ends: its last turn carries the reason (and the teacher's label), and, unless the problem
        was cancelled, the run is one outcome of its problem.

        The run's outcome is its last turn's (status, key, answer, answers, temperature, quality), with the
        codelets, seconds and Episodic Memory additions summed over its turns, the first turn's configuration
        and episode version (what the run started from) and the last turn's merge order.  For a single-turn
        run that is exactly the one turn."""
        last, first = run.turns[-1], run.turns[0]
        last.end_reason, last.end_label = reason, label
        if run.state == "waiting":
            lt.waiting -= 1
        run.state, run.pending = "ended", None
        lt.dirty_runs.add(run)
        if reason == turn_record.END_CANCELLED:
            return
        cap = lt.max_codelets
        rec = RunRec(
            seed=run.seed, status=last.status, key=self._turn_key(last, cap), answer=last.answer,
            answers=list(last.answers), codelets=sum(t.codelets for t in run.turns),
            seconds=sum(t.seconds for t in run.turns), temperature=last.temperature,
            answer_quality=last.answer_quality, error=last.error, config_hash=first.config_hash,
            attempts=max(t.attempts for t in run.turns), problem_id=lp.id,
            memory_version=first.memory_version, configuration_revision=first.configuration_revision,
            seq=last.seq, added_answers=sum(t.added_answers for t in run.turns),
            added_snags=sum(t.added_snags for t in run.turns),
        )
        lp.outcomes[run.seed] = rec
        lt.pending_runs.append(rec)
        lt.note_completion()
        if len(lp.outcomes) >= lp.seeds and lp.status == "queued":
            self._finish_problem(lt, lp, "finished")
        self._apply_error_policy(lt, lp, rec)

    # -- the teacher: the input of a multi-turn run's next turn ---------------------------------------

    def set_teacher(self, session_id: int, teacher: Callable[[dict[str, Any]], Any] | None) -> None:
        """Set (or, with ``None``, remove) a session's teacher: one callable per session, in process.

        When a turn of a multi-turn run answers (and, after a Start, for every run still waiting) the
        scheduler calls ``teacher(conversation)`` with the run's conversation exactly as
        ``GET .../runs/{seed}`` returns it (the problem, the seed, every turn so far with its response, and
        ``waiting_for``, the number of the turn the input is for).  It returns

        * a ``str``: the next turn's input (empty is refused, as everywhere),
        * ``{"end": True, "label": <text or None>}``: the teacher ends the run, or
        * ``None``: nothing yet, and the run keeps waiting for ``supply_input`` (the route).

        It runs on the scheduler, synchronously and between runs: it must be quick and must not wait for
        anything.  A teacher that raises, returns something else, or returns an input the service refuses
        never fails its run: the run keeps waiting, a diagnostic is kept on the session's configuration
        (``teacher_raised``, ``teacher_malformed`` or ``teacher_refused``) and ``last_event`` says so.  The
        teacher may be set before the session is started and lasts until it is removed or the session is
        deleted."""
        if teacher is None:
            self._teachers.pop(session_id, None)
        else:
            self._teachers[session_id] = teacher

    def _consult_teacher(self, lt: LiveSession, lp: LiveProblem, run: LiveRun) -> None:
        teacher = self._teachers.get(lt.id)
        if teacher is None or run.state != "waiting":
            return
        where = (lp.id, run.seed)
        turn = run.waiting_for
        try:
            said = teacher(self._conversation_live(lt, lp, run))
        except Exception as exc:  # noqa: BLE001 - a teacher never fails its run
            lt.config.diagnose("teacher_raised", f"{type(exc).__name__}: {exc}", run=where)
            lt.last_event = f"the teacher raised on problem {lp.id} seed {run.seed}: the run keeps waiting"
            return
        if said is None:
            return
        try:
            if isinstance(said, str):
                self._apply_input(lt, lp, run.seed, turn, said, False, None, turn_record.FROM_TEACHER)
            elif isinstance(said, dict) and said.get("end") is True and set(said) <= {"end", "label"}:
                self._apply_input(lt, lp, run.seed, turn, None, True, said.get("label"), turn_record.FROM_TEACHER)
            else:
                lt.config.diagnose(
                    "teacher_malformed", "the teacher must return a string, {'end': True, 'label': ...} or None",
                    run=where)
        except SessionError as exc:
            lt.config.diagnose("teacher_refused", exc.detail, run=where)
            lt.last_event = f"the teacher's reply for problem {lp.id} seed {run.seed} was refused: {exc.detail}"

    def _apply_input(self, lt: LiveSession, lp: LiveProblem, seed: int, turn: Any, text: Any, end: bool,
                     label: Any, supplier: str) -> None:
        """Take the input (or the end) of the run's next turn: the one place both entrances come to.

        Refused: a malformed call (422), a seed the problem does not have (404), and anything but the exact
        next input of a waiting run (409 ``stale``: a duplicate, a late call, a run that is not waiting, the
        wrong turn).  An input becomes the next turn's strings (``turn_record.next_window``) and the run's seed
        is queued; the turn is dispatched when the session is Running (an input given while it is Paused
        waits for Resume)."""
        if not isinstance(turn, int) or isinstance(turn, bool) or turn < 1:
            raise SessionError(422, "turn must be a whole number from 1: the number of the turn the input is for")
        if end:
            if label is not None:
                if not isinstance(label, str):
                    raise SessionError(422, "label must be text")
                self._check_text("label", label)
        else:
            if not isinstance(text, str):
                raise SessionError(422, "an input is text (or the call ends the run)")
            if text == "":
                raise SessionError(422, "input must not be empty: send end, or leave the run waiting")
            self._check_text("input", text)
        if not lp.seed_start <= seed < lp.seed_start + lp.seeds:
            raise SessionError(404, f"problem {lp.id} has no run with seed {seed}")
        run = lp.run_logs.get(seed)
        if run is None or run.state != "waiting":
            state = "has not answered a turn yet" if run is None else f"is {run.state}"
            raise StaleInput(f"the run of problem {lp.id} seed {seed} {state}, so it is not waiting for input")
        if turn != run.waiting_for:
            raise StaleInput(
                f"the run of problem {lp.id} seed {seed} is waiting for the input of turn {run.waiting_for}, "
                f"not turn {turn}")
        if end:
            self._end_run(lt, lp, run, turn_record.END_TEACHER, label)
            return
        last = run.turns[-1]
        context, second, input_text = turn_record.next_window(
            last.context, last.second, last.input, last.response, text)
        run.pending = TurnSpec(turn, context, second, input_text, supplier)
        run.state = "running"
        lt.waiting -= 1
        lt.dirty_runs.add(run)
        lp.todo.appendleft(seed)
        lt.unsubmitted += 1
        self.wake()

    async def supply_input(self, session_id: int, problem_id: int, seed: int, turn: int,
                           text: str | None = None, *, end: bool = False,
                           label: str | None = None) -> dict[str, Any]:
        """The service door of the teacher: the input of turn *turn* of the run of problem *problem_id*
        at *seed* (``text``), or the end of the run (``end=True``, with an optional ``label``).

        *turn* is the number of the turn the input is for, so it is the number of turns the run has
        finished plus one.  It returns the run's conversation (``conversation``).  A session that is Stopped
        is 409 (start it first), Starting or Stopping 409 ``busy``, an unknown problem or seed 404, an empty
        or non-text input 422, and an input that is not the exact next one of a waiting run, 409 ``stale``
        (:class:`StaleInput`): a duplicate, a late call, a run that is not waiting, the wrong turn number.
        An input given while the session is Paused is kept and dispatched on Resume."""
        lt = self._live_or_409(session_id, "supply input to a run of")
        lp = lt.problems.get(problem_id)
        if lp is None:
            async with self._factory() as s:  # a finished or cancelled stored problem: no run waits
                await self._get_problem(s, session_id, problem_id)
            raise StaleInput(f"problem {problem_id} is not running, so none of its runs is waiting for input")
        if (text is None) == (not end):
            raise SessionError(422, "send either text (the next input) or end: true")
        self._apply_input(lt, lp, seed, turn, text, end, label, turn_record.FROM_TEACHER)
        await self._announce(session_id)
        return self._conversation_live(lt, lp, lp.run_logs[seed])

    def set_after_run(self, session_id: int, learner: Callable[..., Any] | None) -> None:
        """Set (or, with ``None``, remove) a session's after-run seam: one callable per session.

        After each of the session's runs it is called with ``(outcome, provider)``: the finished
        run's outcome and the provider that run used (read-only; a learner never sees or edits
        run state).  It returns a change batch (a mapping with ``ops``; ``source``, ``actor``,
        ``base_version`` and so on are filled in) or ``None``.  None ships in v2.0, so with none
        nothing is computed.  A learner that raises, or returns something that is not a batch,
        never fails its run: the entry is taken without a batch and a diagnostic is kept.
        The seam may be set before the session is started and lasts until it is removed or the
        session is deleted."""
        if learner is None:
            self._after_run.pop(session_id, None)
        else:
            self._after_run[session_id] = learner

    @staticmethod
    def _proposal_batch(outcome: Any, seed: int | None = None, turn: int = 1) -> dict[str, Any] | None:
        """The in-worker learner's batch: the run's ``proposals`` (the nodes and links its codelets
        built, and the ops they proposed), one op per row, with ``rebase`` and ``on_op_failure:
        skip`` (the ``finish_run`` defaults),
        so a node that several runs made is one row and the duplicates are skipped cleanly.
        ``None`` when the run proposed nothing.  *seed* is the run's own seed (the outcome's is the turn's
        seed, which differs after turn 1) and *turn* the turn, named in the note from turn 2 on."""
        ops = [dict(p) for p in (getattr(outcome, "proposals", None) or ())]
        if not ops:
            return None
        who = outcome.seed if seed is None else seed
        note = f"in-worker learner: made by the run of seed {who}" + (f", turn {turn}" if turn > 1 else "")
        return {"ops": ops, "note": note}

    def _learner_batch(self, sub: Sub, outcome: Any) -> dict[str, Any] | None:
        learner = self._after_run.get(sub.lt.id)
        if learner is None:
            return None
        where = (sub.lp.id, sub.seed)
        try:
            batch = learner(outcome, sub.provider)
        except Exception as exc:  # noqa: BLE001 - a learner never fails its run
            sub.lt.config.diagnose("learner_raised", f"{type(exc).__name__}: {exc}", run=where)
            return None
        if batch is None:
            return None
        if not isinstance(batch, dict) or not isinstance(batch.get("ops"), list):
            sub.lt.config.diagnose(
                "learner_batch_malformed", "the after-run seam must return a dict with a list `ops`",
                run=where)
            return None
        return batch

    def _apply_error_policy(self, lt: LiveSession, lp: LiveProblem, rec: RunRec) -> None:
        if not rec.error:
            return
        lt.errors_total += 1
        policy = lt.policy
        errs = sum(1 for r in lp.outcomes.values() if r.error)
        where = f"problem {lp.id} seed {rec.seed}"
        action = policy["on_run_error"]
        if action == "cancel":
            lt.last_event = f"cancelled: a run raised ({where}), on_run_error = cancel"
            self._cancel_all_live(lt)
            return
        if action == "pause":
            self._trigger_pause(lt, f"paused: a run raised ({where}), on_run_error = pause")
        elif action == "skip_problem" and lp.status == "queued":
            lt.last_event = f"cancelled problem {lp.id}: a run raised (seed {rec.seed}), on_run_error = skip_problem"
            self._finish_problem(lt, lp, "cancelled")
            return
        limit = policy["max_errors_per_problem"]
        if limit is not None and errs >= limit and lp.status == "queued":
            lt.last_event = f"cancelled problem {lp.id}: {errs} errors reached max_errors_per_problem"
            self._finish_problem(lt, lp, "cancelled")
            return
        total_limit = policy["max_errors_total"]
        if total_limit is not None and lt.errors_total >= total_limit:
            self._trigger_pause(lt, f"paused: {lt.errors_total} errors reached max_errors_total")

    def _trigger_pause(self, lt: LiveSession, event: str) -> None:
        """Pause from inside the scheduler: effective at once, in memory only."""
        if lt.status != "running":
            return
        lt.status = "paused"
        lt.last_event = event

    def _spawn(self, coro) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    # -- problems finishing, in memory --------------------------------------

    def _finish_problem(self, lt: LiveSession, lp: LiveProblem, status: str) -> None:
        """A problem finishes (every one of its runs ended) or is cancelled.  Held in memory until the
        Stop write: its tally, its place in the ``finished_seq`` order and its place in the
        session summary are fixed here."""
        if lp.status != "queued":
            return
        recs = list(lp.outcomes.values())
        lp.status = status
        lp.tally = summarize(recs)
        lp.counts = (
            len(recs), sum(1 for r in recs if r.error), sum(r.codelets for r in recs),
            sum(1 for r in recs if r.key == CAP_KEY), sum(max(r.attempts - 1, 0) for r in recs),
        )
        lp.finished_at = _utcnow()
        if status == "cancelled":
            lp.cancelled = True
            lt.unsubmitted -= len(lp.todo)
            lp.todo.clear()
            for run in lp.run_logs.values():  # a waiting or part-way run ends with its problem
                if run.state != "ended":
                    self._end_run(lt, lp, run, turn_record.END_CANCELLED)
        if status == "finished" or lp.started or recs:
            lt.finished_count += 1
            lp.finished_seq = lt.finished_count
            lt.finished_log.append(lp)
        lt.active.pop(lp.id, None)
        self._spawn(self._announce(lt.id))
        self.wake()

    def _cancel_all_live(self, lt: LiveSession) -> None:
        """Cancel every unfinished problem of a live session (an action, not a state)."""
        for lp in list(lt.problems.values()):
            self._finish_problem(lt, lp, "cancelled")
        lt.unsubmitted = sum(1 for (l, _, _) in self._isolation if l is lt)

    async def _announce(self, session_id: int) -> None:
        self._versions[session_id] = self._versions.get(session_id, 0) + 1
        cond = self._conds.get(session_id)
        if cond is not None:
            async with cond:
                cond.notify_all()

    # -- reading ----------------------------------------------------------------
    #
    # Reads of a live session are served from memory; a Stopped session is read from the
    # database.  (Reads are the only database use a live session makes, and only for what it
    # did not load at Start.)

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
                "seeds_per_problem": 100, "seed_start": 1,
                "max_codelets": meta.get_param("default_max_codelets"), "parameters": None,
                "backend": default_session_backend(meta),
            },
            "policy": dict(DEFAULT_POLICY),
        }

    @staticmethod
    def _shape(*, id: int, name: str, note: str, state: str, activity: str | None,
               stalled: str | None, settings: dict, policy: dict, config_hash: str,
               created_at: datetime | None, updated_at: datetime | None, stopped_at: datetime | None,
               stopped_from: str | None, stop_reason: str | None, problems: dict, runs: dict,
               memory: dict, codelets: int, rate: float | None, memory_version: int, cursor: int,
               last_event: str | None, live: bool, saved_version: int,
               unsaved: dict | None, saved_stopped_at: datetime | None,
               configuration: dict | None, saved_revision: int | None) -> dict[str, Any]:
        remaining = max(runs["total"] - runs["done"], 0)
        if state != "running" or activity is not None:
            rate = None
        return {
            "id": id, "name": name, "note": note, "state": state, "activity": activity,
            "stalled_reason": stalled if activity == "stalled" else None,
            "settings": settings, "policy": policy, "config_hash": config_hash,
            "created_at": _iso(created_at), "updated_at": _iso(updated_at),
            "stopped_at": _iso(stopped_at), "stopped_from": stopped_from, "stop_reason": stop_reason,
            "problems": problems, "runs": runs, "memory": memory, "codelets": codelets,
            "runs_per_second": round(rate, 3) if rate else None,
            "eta_seconds": round(remaining / rate, 1) if rate and remaining else None,
            "memory_version": memory_version, "finished_cursor": cursor, "last_event": last_event,
            # Where the numbers come from, and what the database holds (3.13, 3.16):
            "source": "live" if live else "stored",
            "persisted": not live,
            "saved_through": {
                "stopped_at": _iso(saved_stopped_at),
                "configuration_revision": saved_revision,
                "episode_version": saved_version,
            },
            "unsaved": unsaved,
            # The session's own configuration: ``version`` is its revision (the token an editor
            # sends as ``base_version``), ``last_change_version`` the episode version of its last
            # change; for a live session it is the configuration in memory.
            "configuration": configuration,
        }

    def _live_summary(self, lt: LiveSession) -> dict[str, Any]:
        """A live session's summary, from memory alone.

        **Which runs count.**  ``runs.total/done/errors/capped/retries`` and ``codelets`` count
        the runs of problems that are not cancelled (a cancelled problem leaves the totals; its
        runs stay available on the problem itself)."""
        fin, can = lt.base_fin, lt.base_can
        total = fin[1]
        done, errors, codelets, capped, retries = fin[2:7]
        queued = running = finished = cancelled = 0
        for lp in lt.problems.values():
            if lp.status == "cancelled":
                cancelled += 1
                continue
            total += lp.seeds
            if lp.status == "finished":
                finished += 1
                n, e, cl, cap, rt = lp.counts
            else:
                if lp.started:
                    running += 1
                else:
                    queued += 1
                if not (lp.started or lp.outcomes):
                    continue
                recs = list(lp.outcomes.values())
                n, e, cl = len(recs), sum(1 for r in recs if r.error), sum(r.codelets for r in recs)
                cap, rt = sum(1 for r in recs if r.key == CAP_KEY), sum(max(r.attempts - 1, 0) for r in recs)
            done, errors, codelets, capped, retries = done + n, errors + e, codelets + cl, capped + cap, retries + rt
        unfinished = queued + running
        state, stalled = lt.status, lt.stalled_reason
        activity = None
        if state == "running":
            if stalled:
                activity = "stalled"
            elif unfinished == 0:
                activity = "idle"
            elif lt.waiting and not lt.unsubmitted and not lt.inflight_subs:
                activity = "waiting"  # every run that is left is waiting for the teacher's next input
        return self._shape(
            id=lt.id, name=lt.name, note=lt.note, state=state, activity=activity, stalled=stalled,
            settings={
                "seeds_per_problem": lt.seeds_per_problem, "seed_start": lt.seed_start,
                "max_codelets": lt.max_codelets, "parameters": lt.parameters, "backend": lt.backend,
                "configuration_base": lt.configuration_base,
            },
            policy=normalize_policy(lt.policy), config_hash=lt.config_hash,
            created_at=lt.created_at, updated_at=lt.updated_at, stopped_at=lt.stopped_at,
            stopped_from=lt.stopped_from, stop_reason=lt.stop_reason,
            problems={"total": queued + running + finished + fin[0] + cancelled + can[0],
                      "queued": queued, "running": running, "finished": fin[0] + finished,
                      "cancelled": can[0] + cancelled},
            runs={"total": total, "done": done, "errors": errors, "capped": capped, "retries": retries,
                  "waiting": lt.waiting},
            memory={"answers": len(lt.memory.answers), "snags": len(lt.memory.snags)},
            codelets=codelets, rate=lt.rate(), memory_version=lt.version, cursor=lt.finished_count,
            last_event=lt.last_event, live=True, saved_version=lt.saved_version,
            unsaved=lt.unsaved(), saved_stopped_at=lt.stopped_at,
            configuration=lt.config.summary(), saved_revision=lt.config.saved_revision,
        )

    async def _stored_summaries(self, s: AsyncSession, sessions: list[TrainingModeSession]) -> list[dict[str, Any]]:
        """Summaries of Stopped (and Starting) sessions, from the database.

        **Which runs count.**  As for a live session; a Stopped session's unfinished problems
        keep the runs the Stop wrote, and those count too."""
        if not sessions:
            return []
        ids = [t.id for t in sessions]
        P, R = TrainingModeSessionProblem, TrainingModeSessionRun
        by_t = await self._stored_totals(s, ids)
        # A Stopped session holds no memory in the process: its size is what its stored
        # runs added, and its version the last stored merge.
        stored_mem = {
            tid: (int(a), int(sn)) for tid, a, sn in (await s.execute(
                select(R.session_id, func.coalesce(func.sum(R.added_answers), 0),
                       func.coalesce(func.sum(R.added_snags), 0))
                .where(R.session_id.in_(ids)).group_by(R.session_id)
            )).all()
        }
        partial = {
            tid: tuple(int(v) for v in vals) for tid, *vals in (await s.execute(
                select(
                    R.session_id, func.count(),
                    func.coalesce(func.sum(case((R.error.is_not(None), 1), else_=0)), 0),
                    func.coalesce(func.sum(R.codelets), 0),
                    func.coalesce(func.sum(case((R.key == CAP_KEY, 1), else_=0)), 0),
                    func.coalesce(func.sum(R.attempts - 1), 0),
                ).join(P, (P.session_id == R.session_id) & (P.problem_id == R.problem_id))
                .where(R.session_id.in_(ids), P.status == "queued")
                .group_by(R.session_id)
            )).all()
        }
        stored_version = dict((await s.execute(
            select(SessionMemoryMerge.session_id, func.max(SessionMemoryMerge.seq))
            .where(SessionMemoryMerge.session_id.in_(ids)).group_by(SessionMemoryMerge.session_id)
        )).all())
        configs = await self._stored_configurations(s, ids)
        T = TrainingModeSessionTurn
        # A run is waiting when its last turn answered and the run has not ended (a run's reason is on its
        # last row), in a multi-turn problem that is still unfinished.
        last_turn = (
            select(T.session_id, T.problem_id, T.seed, func.max(T.turn).label("last"))
            .join(P, (P.session_id == T.session_id) & (P.problem_id == T.problem_id))
            .where(T.session_id.in_(ids), P.multi_turn.is_(True), P.status == "queued")
            .group_by(T.session_id, T.problem_id, T.seed).subquery()
        )
        waiting = dict((await s.execute(
            select(T.session_id, func.count())
            .join(last_turn, (T.session_id == last_turn.c.session_id) & (T.problem_id == last_turn.c.problem_id)
                  & (T.seed == last_turn.c.seed) & (T.turn == last_turn.c.last))
            .where(T.end_reason.is_(None), T.status != "pending")
            .group_by(T.session_id)
        )).all())
        zero = (0,) * 7
        out = []
        for t in sessions:
            c = by_t.get(t.id, {})
            config = configs.get(t.id)
            q, f, x = c.get("queued", zero), c.get("finished", zero), c.get("cancelled", zero)
            n, e, cl, cap, rt = partial.get(t.id, (0,) * 5)
            a_n, s_n = stored_mem.get(t.id, (0, 0))
            version = stored_version.get(t.id) or 0
            out.append(self._shape(
                id=t.id, name=t.name, note=t.note, state="starting" if t.id in self._starting else "stopped",
                activity=None, stalled=None,
                settings={
                    "seeds_per_problem": t.seeds_per_problem, "seed_start": t.seed_start,
                    "max_codelets": t.max_codelets, "parameters": t.parameters, "backend": t.backend,
                    "configuration_base": t.configuration_base,
                },
                policy=normalize_policy(t.policy),
                config_hash=config["hash"] if config else t.config_hash,
                created_at=t.created_at, updated_at=t.updated_at, stopped_at=t.stopped_at,
                stopped_from=t.stopped_from, stop_reason=t.stop_reason,
                problems={"total": q[0] + f[0] + x[0], "queued": q[0], "running": 0,
                          "finished": f[0], "cancelled": x[0]},
                runs={"total": q[1] + f[1], "done": f[2] + n, "errors": f[3] + e, "capped": f[5] + cap,
                      "retries": f[6] + rt, "waiting": waiting.get(t.id, 0)},
                memory={"answers": a_n, "snags": s_n}, codelets=f[4] + cl, rate=None,
                memory_version=version, cursor=t.finished_count, last_event=t.last_event,
                live=False, saved_version=version, unsaved=None, saved_stopped_at=t.stopped_at,
                configuration=config, saved_revision=config["version"] if config else None,
            ))
        return out

    @staticmethod
    async def _stored_configurations(s: AsyncSession, ids: list[int]) -> dict[int, dict[str, Any]]:
        """The ``configuration`` block of Stopped sessions, from the database: one query for the
        rows and their sizes, one for the episode version of each one's last journalled change."""
        C, N, J = Configuration.__table__, ConfigurationSnapshot.__table__, JournalEntry.__table__
        tables = cast(N.c.data, JSONB)["tables"]
        rows = (await s.execute(
            select(
                C.c.session_id, C.c.id, C.c.revision, C.c.config_hash, C.c.base_snapshot_hash, C.c.frozen,
                func.jsonb_array_length(tables["slipnet_node_defs"]),
                func.jsonb_array_length(tables["slipnet_link_defs"]),
            ).join(N, (N.c.configuration_id == C.c.id) & (N.c.role == "current"))
            .where(C.c.session_id.in_(ids))
        )).all()
        last = dict((await s.execute(
            select(J.c.configuration_id, func.max(J.c.episode_version))
            .where(J.c.configuration_id.in_([r[1] for r in rows])).group_by(J.c.configuration_id)
        )).all()) if rows else {}
        return {
            sid: {"id": cid, "version": revision, "hash": digest, "base_hash": base, "nodes": nodes,
                  "links": links, "last_change_version": last.get(cid), "frozen": frozen}
            for sid, cid, revision, digest, base, frozen, nodes, links in rows
        }

    async def _summaries(self, s: AsyncSession, sessions: list[TrainingModeSession]) -> list[dict[str, Any]]:
        """Summaries in the order given: a live session from memory, a Stopped one from the database."""
        stored = await self._stored_summaries(s, [t for t in sessions if t.id not in self._live])
        by_id = {d["id"]: d for d in stored}
        return [self._live_summary(self._live[t.id]) if t.id in self._live else by_id[t.id] for t in sessions]

    async def _get_session(self, s: AsyncSession, session_id: int) -> TrainingModeSession:
        t = await s.get(TrainingModeSession, session_id)
        if t is None:
            raise SessionError(404, f"session {session_id} not found")
        return t

    def database(self):
        """A database session from the service's factory (the API's read views use it)."""
        return self._factory()

    async def list_sessions(self) -> list[dict[str, Any]]:
        async with self._factory() as s:
            ts = (await s.execute(select(TrainingModeSession).order_by(TrainingModeSession.id.desc()))).scalars().all()
            return await self._summaries(s, list(ts))

    async def summary(self, session_id: int) -> dict[str, Any]:
        lt = self._live.get(session_id)
        if lt is not None:
            return self._live_summary(lt)
        async with self._factory() as s:
            return (await self._summaries(s, [await self._get_session(s, session_id)]))[0]

    # -- problem rows ---------------------------------------------------------

    @staticmethod
    def _problem_view(*, p: Any, status: str, t: dict, finished_seq: int | None, started_at: datetime | None,
                      finished_at: datetime | None, detail: bool) -> dict[str, Any]:
        done = t["runs_done"]
        row = {
            "id": p.problem_id if hasattr(p, "problem_id") else p.id, "session_id": p.session_id,
            "initial": p.initial, "modified": p.modified, "target": p.target, "answer": p.answer,
            "seeds": p.seeds, "seed_start": p.seed_start, "tag": p.tag, "status": status,
            "multi_turn": bool(p.multi_turn), "runs_done": done, "errors": t["errors"], "capped": t["capped"],
            "mean_codelets": t["mean_codelets"], "top": _shares(t["distribution"], done, 3),
            "none_fraction": t["none_fraction"], "distinct": t["distinct_answers"] or 0,
            "statuses": t["statuses"] or {}, "finished_seq": finished_seq, "added_at": _iso(p.added_at),
            "started_at": _iso(started_at), "finished_at": _iso(finished_at),
        }
        if detail:
            row["distribution"] = _shares(t["distribution"], done, None)
            row["first_error"] = t["first_error"]
        return row

    def _stored_problem_dict(self, p: TrainingModeSessionProblem, detail: bool) -> dict[str, Any]:
        t = {
            "runs_done": p.runs_done, "errors": p.errors, "capped": p.capped,
            "mean_codelets": p.mean_codelets, "none_fraction": p.none_fraction,
            "distinct_answers": p.distinct_answers, "distribution": p.distribution,
            "statuses": p.statuses, "first_error": p.first_error,
        }
        return self._problem_view(p=p, status=p.status, t=t, finished_seq=p.finished_seq,
                                  started_at=p.started_at, finished_at=p.finished_at, detail=detail)

    def _live_problem_dict(self, lp: LiveProblem, detail: bool) -> dict[str, Any]:
        if lp.settled:
            t, status = lp.tally, lp.status
        else:
            t = summarize(list(lp.outcomes.values()))
            status = "running" if lp.started else "queued"
        return self._problem_view(p=lp, status=status, t=t, finished_seq=lp.finished_seq,
                                  started_at=lp.started_at, finished_at=lp.finished_at, detail=detail)

    SORTS = {
        "id": TrainingModeSessionProblem.problem_id, "runs_done": TrainingModeSessionProblem.runs_done,
        "top_fraction": TrainingModeSessionProblem.top_fraction, "none_fraction": TrainingModeSessionProblem.none_fraction,
        "distinct": TrainingModeSessionProblem.distinct_answers, "errors": TrainingModeSessionProblem.errors,
        "mean_codelets": TrainingModeSessionProblem.mean_codelets, "finished_seq": TrainingModeSessionProblem.finished_seq,
    }

    @staticmethod
    def _sort_value(sort: str, d: dict[str, Any]) -> Any:
        if sort == "top_fraction":
            return d["top"][0]["fraction"] if d["top"] else None
        return d["id" if sort == "id" else sort]

    @staticmethod
    def _live_matches(lp: LiveProblem, status: str | None, q: str | None) -> bool:
        if status == "running" and not (lp.status == "queued" and lp.started):
            return False
        if status == "queued" and not (lp.status == "queued" and not lp.started):
            return False
        if status in ("finished", "cancelled") and lp.status != status:
            return False
        if q and q.lower() not in f"{lp.initial} {lp.modified} {lp.target}".lower():
            return False
        return True

    def _problem_filter(self, session_id: int, status: str | None, q: str | None, live: bool):
        """SQL conditions over the stored rows.  For a live session the rows that were queued
        at Start are all in memory, so only its finished and cancelled stored rows are read."""
        P = TrainingModeSessionProblem
        conds = [P.session_id == session_id]
        if status in ("running", "queued"):
            # Nothing stored is running; a live session holds every row that was queued at Start.
            conds.append(false() if live or status == "running" else P.status == "queued")
        elif status in ("finished", "cancelled"):
            conds.append(P.status == status)
        elif status:
            raise SessionError(422, f"unknown status {status!r}")
        elif live:
            conds.append(P.status != "queued")
        if q:
            conds.append(func.concat_ws(" ", P.initial, P.modified, P.target).icontains(q, autoescape=True))
        return conds

    async def list_problems(
        self, session_id: int, status: str | None = None, q: str | None = None,
        sort: str = "id", order: str = "asc", offset: int = 0, limit: int = 100,
    ) -> dict[str, Any]:
        if sort not in self.SORTS:
            raise SessionError(422, f"sort must be one of {sorted(self.SORTS)}")
        if order not in ("asc", "desc"):
            raise SessionError(422, "order must be asc or desc")
        P = TrainingModeSessionProblem
        lt = self._live.get(session_id)
        async with self._factory() as s:
            await self._get_session(s, session_id)
            conds = self._problem_filter(session_id, status, q, lt is not None)
            total = (await s.execute(select(func.count()).select_from(P).where(*conds))).scalar_one()
            col = self.SORTS[sort]
            ordering = col.desc().nulls_last() if order == "desc" else col.asc().nulls_last()
            take = offset + limit if lt is not None else limit
            rows = (await s.execute(
                select(P).where(*conds).order_by(ordering, P.problem_id.asc())
                .offset(0 if lt is not None else offset).limit(take)
            )).scalars().all()
        dicts = [self._stored_problem_dict(p, False) for p in rows]
        if lt is None:
            return {"total": total, "problems": dicts}
        mine = [self._live_problem_dict(lp, False) for lp in lt.problems.values()
                if self._live_matches(lp, status, q)]
        sign = -1 if order == "desc" else 1

        def key(d: dict) -> tuple:
            v = self._sort_value(sort, d)
            return (v is None, sign * v if v is not None else 0, d["id"])

        merged = sorted(dicts + mine, key=key)
        return {"total": total + len(mine), "problems": merged[offset:offset + limit]}

    async def _get_problem(self, s: AsyncSession, session_id: int, pid: int) -> TrainingModeSessionProblem:
        p = await s.get(TrainingModeSessionProblem, (session_id, pid))
        if p is None:
            raise SessionError(404, f"problem {pid} not found in session {session_id}")
        return p

    async def get_problem(self, session_id: int, pid: int) -> dict[str, Any]:
        lt = self._live.get(session_id)
        lp = lt.problems.get(pid) if lt is not None else None
        if lp is not None:
            return self._live_problem_dict(lp, True)
        async with self._factory() as s:
            await self._get_session(s, session_id)
            return self._stored_problem_dict(await self._get_problem(s, session_id, pid), True)

    async def problem_runs(self, session_id: int, pid: int) -> list[dict[str, Any]]:
        """A problem's runs in seed order: those that have ended, each with its ``state`` (``ended``), its
        ``turns`` (how many it finished), ``end_reason`` and ``end_label``; for a multi-turn problem also
        the runs still going (state ``running`` or ``waiting``, with ``waiting_for``, the number of the turn
        the input is for), whose ``answer`` is their latest response.  The conversation of one run is
        ``conversation``."""
        lt = self._live.get(session_id)
        lp = lt.problems.get(pid) if lt is not None else None
        if lp is not None:
            logs = dict(lp.run_logs)
            stored = {}
            if any(seed not in logs for seed in lp.outcomes):  # ended before this Start: the database knows
                async with self._factory() as s:
                    stored = await self._stored_turns(s, session_id, pid)
            recs = [self._run_dict(r, self._run_extras(logs.get(r.seed) or stored.get(r.seed), "ended"))
                    for r in sorted(lp.outcomes.values(), key=lambda r: r.seed)]
            going = [self._unfinished_dict(run.seed, run.turns, run.state) for run in logs.values()
                     if run.state != "ended"]
            return sorted(recs + going, key=lambda d: d["seed"])
        async with self._factory() as s:
            await self._get_session(s, session_id)
            problem = await self._get_problem(s, session_id, pid)
            rows = (await s.execute(
                select(TrainingModeSessionRun).where(
                    TrainingModeSessionRun.session_id == session_id, TrainingModeSessionRun.problem_id == pid
                ).order_by(TrainingModeSessionRun.seed)
            )).scalars().all()
            turns = await self._stored_turns(s, session_id, pid)
        out = [self._run_dict(r, self._run_extras(turns.get(r.seed), "ended")) for r in rows]
        ended = {r.seed for r in rows}
        if problem.status == "queued":
            out += [self._unfinished_dict(seed, [t for t in ts if t.status != "pending"],
                                          "running" if ts[-1].status == "pending" else "waiting")
                    for seed, ts in turns.items() if seed not in ended]
        return sorted(out, key=lambda d: d["seed"])

    async def _stored_turns(self, s: AsyncSession, session_id: int, pid: int) -> dict[int, list[TurnRec]]:
        T = TrainingModeSessionTurn
        rows = (await s.execute(
            select(T).where(T.session_id == session_id, T.problem_id == pid).order_by(T.seed, T.turn)
        )).scalars().all()
        out: dict[int, list[TurnRec]] = {}
        for r in rows:
            out.setdefault(r.seed, []).append(self._turn_from_row(r))
        return out

    @staticmethod
    def _run_extras(turns: Any, state: str) -> dict[str, Any]:
        """The turn-related fields a run's listing entry gains (``turns`` is a ``LiveRun`` or a list of turns)."""
        turns = turns.turns if isinstance(turns, LiveRun) else (turns or [])
        done = [t for t in turns if t.status != "pending"]
        last = turns[-1] if turns else None
        return {
            "state": state, "turns": len(done), "waiting_for": None,
            "end_reason": last.end_reason if last is not None and state == "ended" else None,
            "end_label": last.end_label if last is not None and state == "ended" else None,
        }

    @classmethod
    def _unfinished_dict(cls, seed: int, turns: list[TurnRec], state: str) -> dict[str, Any]:
        """A listing entry for a run that has not ended: ``answer`` is its latest response."""
        done = [t for t in turns if t.status != "pending"]
        first, last = (done[0], done[-1]) if done else (None, None)
        return {
            "seq": None, "memory_version": first.memory_version if first else None,
            "episode_version": first.memory_version if first else None,
            "configuration_revision": first.configuration_revision if first else None,
            "seed": seed, "status": state, "key": None,
            "answer": (last.response or "") if last else "", "answers": [],
            "codelets": sum(t.codelets for t in done), "seconds": round(sum(t.seconds for t in done), 4),
            "temperature": last.temperature if last else 0.0, "answer_quality": None, "error": None,
            "config_hash": first.config_hash if first else "", "attempts": 1, "memory_added": None,
            "state": state, "turns": len(done), "waiting_for": len(done) + 1 if state == "waiting" else None,
            "end_reason": None, "end_label": None,
        }

    # -- the conversation of a run (the chat-shaped call) ---------------------------------------------

    @staticmethod
    def _turn_dict(t: TurnRec) -> dict[str, Any]:
        """One turn of a conversation: its four positions (context, second string, input and the response
        Petacat constructed), who supplied each, and what the turn did."""
        first = t.turn == 1
        return {
            "turn": t.turn,
            "positions": {"context": t.context, "second": t.second, "input": t.input, "response": t.response},
            "supplied_by": {
                "context": "problem" if first else "window", "second": "problem" if first else "petacat",
                "input": t.input_from, "response": "petacat",
            },
            "status": t.status, "codelets": t.codelets, "seconds": round(t.seconds, 4),
            "answers": list(t.answers), "answer_quality": t.answer_quality, "temperature": t.temperature,
            "error": t.error, "turn_seed": t.turn_seed, "attempts": t.attempts,
            "end_reason": t.end_reason, "end_label": t.end_label,
            "proposals": list(t.proposals), "evidence": t.evidence,
            "seq": t.seq, "episode_version": t.memory_version,
            "configuration_revision": t.configuration_revision, "config_hash": t.config_hash,
        }

    @classmethod
    def _conversation_body(cls, *, session_id: int, problem_id: int, problem: dict, seed: int,
                           multi_turn: bool, state: str, turns: list[TurnRec], session_state: str,
                           end_reason: str | None = None) -> dict[str, Any]:
        done = [t for t in turns if t.status != "pending"]
        last = turns[-1] if turns else None
        return {
            "session_id": session_id, "problem_id": problem_id, "seed": seed, "multi_turn": multi_turn,
            "problem": problem, "session_state": session_state,
            # ``queued`` (nothing run yet, or the next turn is queued while the session is Stopped), ``running``
            # (a turn is queued or in flight), ``waiting`` (for the input of turn ``waiting_for``) or ``ended``.
            "state": state,
            "waiting_for": len(done) + 1 if state == "waiting" else None,
            # True when ``POST .../input`` would be taken now for ``waiting_for``.
            "accepts_input": state == "waiting" and session_state in ("running", "paused"),
            "end_reason": end_reason if end_reason is not None else (last.end_reason if state == "ended" and last else None),
            "end_label": last.end_label if state == "ended" and last else None,
            "turn_count": len(turns), "turns": [cls._turn_dict(t) for t in turns],
        }

    @staticmethod
    def _problem_block(p: Any) -> dict[str, Any]:
        return {"initial": p.initial, "modified": p.modified, "target": p.target, "tag": p.tag}

    def _conversation_live(self, lt: LiveSession, lp: LiveProblem, run: LiveRun | None,
                           seed: int | None = None) -> dict[str, Any]:
        turns = list(run.turns) if run is not None else []
        state = run.state if run is not None else "running"
        seed = run.seed if run is not None else seed
        if run is not None and run.pending is not None:
            p = run.pending
            turns.append(TurnRec(
                turn=p.turn, turn_seed=turn_record.turn_seed(run.seed, p.turn), context=p.context,
                second=p.second, input=p.input, input_from=p.input_from))
        elif run is None and seed in lp.todo:
            state = "queued"
        return self._conversation_body(
            session_id=lt.id, problem_id=lp.id, problem=self._problem_block(lp), seed=seed,
            multi_turn=lp.multi_turn, state=state, turns=turns, session_state=lt.status)

    async def conversation(self, session_id: int, pid: int, seed: int) -> dict[str, Any]:
        """A run's whole conversation, in order: for each turn its four positions (``context``, ``second``,
        ``input`` and ``response``), who supplied each, its status, codelets, end reason and ``evidence``;
        and for the run, whether it is ``running`` a turn, ``waiting`` for input (``waiting_for`` is the
        number of the turn the input is for, ``accepts_input`` says the session would take it now) or
        ``ended`` (``end_reason``: ``single-turn``, ``no-answer``, ``teacher`` with ``end_label``, ``error`` or
        ``cancelled``).  A live session answers from memory, a Stopped one from its turn rows.  404 for an
        unknown problem or a seed the problem does not have."""
        lt = self._live.get(session_id)
        lp = lt.problems.get(pid) if lt is not None else None
        if lp is not None:
            if not lp.seed_start <= seed < lp.seed_start + lp.seeds:
                raise SessionError(404, f"problem {pid} has no run with seed {seed}")
            run = lp.run_logs.get(seed)
            if run is not None or seed not in lp.outcomes:
                return self._conversation_live(lt, lp, run, seed)
        T, R = TrainingModeSessionTurn, TrainingModeSessionRun
        async with self._factory() as s:
            await self._get_session(s, session_id)
            problem = await self._get_problem(s, session_id, pid)
            if not problem.seed_start <= seed < problem.seed_start + problem.seeds:
                raise SessionError(404, f"problem {pid} has no run with seed {seed}")
            rows = (await s.execute(
                select(T).where(T.session_id == session_id, T.problem_id == pid, T.seed == seed).order_by(T.turn)
            )).scalars().all()
            ran = (await s.execute(
                select(R.id).where(R.session_id == session_id, R.problem_id == pid, R.seed == seed)
            )).first() is not None
        turns = [self._turn_from_row(r) for r in rows]
        reason = None
        if ran:
            state = "ended"
        elif not turns:
            state, reason = ("ended", turn_record.END_CANCELLED) if problem.status == "cancelled" else ("queued", None)
        elif turns[-1].status == "pending":
            state = "queued"
        elif turns[-1].end_reason is not None:
            state = "ended"
        elif problem.status == "cancelled":
            state, reason = "ended", turn_record.END_CANCELLED
        else:
            state = "waiting"
        session_state = lt.status if lt is not None else ("starting" if session_id in self._starting else "stopped")
        return self._conversation_body(
            session_id=session_id, problem_id=pid, problem=self._problem_block(problem), seed=seed,
            multi_turn=bool(problem.multi_turn), state=state, turns=turns, session_state=session_state,
            end_reason=reason)

    @staticmethod
    def _run_dict(r: Any, extras: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "seq": r.seq, "memory_version": r.memory_version,
            # The Training episode version the run started from (one counter over Episodic
            # Memory and the whole configuration) and the configuration revision it ran under;
            # ``config_hash`` below is the hash of that configuration.
            "episode_version": r.memory_version, "configuration_revision": r.configuration_revision,
            "seed": r.seed, "status": r.status,
            "key": r.key, "answer": r.answer, "answers": list(r.answers or []),
            "codelets": r.codelets, "seconds": round(r.seconds, 4), "temperature": r.temperature,
            "answer_quality": r.answer_quality, "error": r.error, "config_hash": r.config_hash,
            "attempts": r.attempts,
            "memory_added": (
                {"answers": r.added_answers, "snags": r.added_snags}
                if r.added_answers is not None else None
            ),
            **(extras or {}),
        }

    async def finished(self, session_id: int, after: int = 0, limit: int = 100,
                       wait: float = 0.0) -> dict[str, Any]:
        """Problems finished after a cursor, in the order they finished.  A live session's
        finishes since its Start are served from memory, the earlier ones from the database."""
        deadline = time.monotonic() + max(0.0, min(wait, 60.0))
        if session_id not in self._live:
            async with self._factory() as s:
                await self._get_session(s, session_id)
        cond = self._conds.get(session_id)
        if cond is None:
            cond = self._conds[session_id] = asyncio.Condition()
        P = TrainingModeSessionProblem
        while True:
            version = self._versions.get(session_id, 0)
            async with self._factory() as s:
                rows = (await s.execute(
                    select(P).where(P.session_id == session_id, P.finished_seq > after)
                    .order_by(P.finished_seq).limit(limit)
                )).scalars().all()
            lt = self._live.get(session_id)  # it may have been stopped while the rows were read
            items = [self._stored_problem_dict(p, False) for p in rows]
            if lt is not None:
                seen = {d["id"] for d in items}
                items += [self._live_problem_dict(lp, False) for lp in lt.finished_log
                          if lp.finished_seq > after and lp.id not in seen][:max(limit - len(items), 0)]
                items.sort(key=lambda d: d["finished_seq"])
                items = items[:limit]
            remaining = deadline - time.monotonic()
            if items or remaining <= 0 or self._stopped:
                cursor = items[-1]["finished_seq"] if items else after
                return {"cursor": cursor, "problems": items}
            async with cond:
                if self._versions.get(session_id, 0) == version:
                    try:
                        await asyncio.wait_for(cond.wait(), remaining)
                    except asyncio.TimeoutError:
                        pass

    # -- the Episodic Memory --------------------------------------------------

    async def memory_of(self, session_id: int) -> EpisodicMemory:
        """The Episodic Memory (live if started, else the snapshot the last Stop stored)."""
        lt = self._live.get(session_id)
        if lt is not None:
            return tm.copy_for_run(lt.memory)
        async with self._factory() as s:
            await self._get_session(s, session_id)
            snap = (await s.execute(
                select(SessionMemorySnapshot).where(SessionMemorySnapshot.session_id == session_id)
            )).scalar_one_or_none()
            return tm.memory_from_snapshot(snap.data) if snap is not None else EpisodicMemory()

    @staticmethod
    async def stored_replay_source(s: AsyncSession, session_id: int) -> tm.ListReplaySource:
        """The stored memory merges of a session as a :class:`~server.services.training_mode_session_memory.ReplaySource`."""
        rows = (await s.execute(
            select(SessionMemoryMerge).where(SessionMemoryMerge.session_id == session_id)
            .order_by(SessionMemoryMerge.seq)
        )).scalars().all()
        return tm.ListReplaySource([
            tm.ReplayEntry(m.seq, "memory_merge", tm.decode_additions(m.answers, m.snags)) for m in rows
        ])

    @staticmethod
    async def rebuild_memory(s: AsyncSession, session_id: int, upto: int | None = None) -> EpisodicMemory:
        """Replay the stored merges (to version *upto*, default all) into a fresh memory."""
        source = await TrainingModeSessionService.stored_replay_source(s, session_id)
        return tm.replay_memory(source, upto)

    def live_memory(self, session_id: int) -> EpisodicMemory | None:
        """The live Episodic Memory, or ``None`` for a Stopped session."""
        lt = self._live.get(session_id)
        return lt.memory if lt is not None else None

    def is_live(self, session_id: int) -> bool:
        return session_id in self._live

    # -- writing: create / add -------------------------------------------------

    def _validate_problems(self, problems: list[dict]) -> None:
        if len(problems) > MAX_PROBLEMS_PER_REQUEST:
            raise SessionError(422, f"at most {MAX_PROBLEMS_PER_REQUEST} problems per request")
        for p in problems:
            try:
                check_problem_mapping(p, require_nonempty=True)
            except ProblemTextError as exc:
                raise SessionError(422, str(exc)) from None
            n = p.get("seeds")
            if n is not None and not (1 <= n <= MAX_SEEDS_PER_PROBLEM):
                raise SessionError(422, f"seeds must be 1..{MAX_SEEDS_PER_PROBLEM}")
            if p.get("multi_turn") is not None and not isinstance(p["multi_turn"], bool):
                raise SessionError(422, "multi_turn must be true or false")
            if p.get("multi_turn") and p.get("answer") is not None:
                raise SessionError(
                    422, "a multi-turn problem has no answer: Petacat constructs the response of every turn")

    async def _insert_problems(self, s: AsyncSession, t: TrainingModeSession, problems: list[dict]) -> list[int]:
        """Store problems for a Stopped session, giving them the next per-session ordinals."""
        now = _utcnow()
        first = t.next_problem_id
        values = [
            {
                "session_id": t.id, "problem_id": first + i, "initial": p["initial"],
                "modified": p["modified"], "target": p["target"], "answer": p.get("answer"),
                "seeds": p.get("seeds") or t.seeds_per_problem, "seed_start": t.seed_start,
                "tag": p.get("tag"), "multi_turn": bool(p.get("multi_turn")), "status": "queued", "runs_done": 0, "errors": 0, "capped": 0,
                "retries": 0, "codelets_total": 0, "distinct_answers": 0, "added_at": now,
            }
            for i, p in enumerate(problems)
        ]
        for i in range(0, len(values), INSERT_CHUNK):
            await s.execute(insert(TrainingModeSessionProblem), values[i:i + INSERT_CHUNK])
        t.next_problem_id = first + len(values)
        return [v["problem_id"] for v in values]

    @staticmethod
    def _check_seed_range(seed_start: int, seed_counts: list[int]) -> None:
        """Seeds are stored as int32: the last seed of the longest problem must fit."""
        last = seed_start + max(seed_counts) - 1
        if last > INT32_MAX:
            raise SessionError(
                422, f"seed_start {seed_start} with {max(seed_counts)} seeds runs past the "
                     f"largest seed, {INT32_MAX}")

    @staticmethod
    def _check_configuration_base(base: Any) -> Any:
        """``settings.configuration_base``: ``'training-v2'`` (the default), ``'global'``,
        ``'standard'`` or ``{"session_id": n}``."""
        if base in ("training-v2", "global", "standard"):
            return base
        if (isinstance(base, dict) and set(base) == {"session_id"}
                and isinstance(base["session_id"], int) and not isinstance(base["session_id"], bool)):
            return base
        raise SessionError(
            422, "settings.configuration_base must be 'training-v2', 'global', 'standard' or "
                 "{\"session_id\": <number>}")

    def resolve_backend(self, meta: MetadataProvider, requested: str | None) -> str:
        if requested is not None:
            allowed = available_backend_names()
            if requested not in allowed:
                raise SessionError(
                    400, f"numeric backend {requested!r} is not available here; choose from {allowed}"
                )
            return requested
        return default_session_backend(meta)

    @staticmethod
    def _check_text(field: str, value: str) -> None:
        """Any text is a valid name or note except what the database cannot hold (a 422)."""
        try:
            check_string(field, value)
        except ProblemTextError as exc:
            raise SessionError(422, str(exc)) from exc

    async def create_session(
        self, *, name: str, note: str = "", settings: dict | None = None,
        policy: dict | None = None, problems: list[dict] | None = None,
    ) -> dict[str, Any]:
        """Create a Stopped session: a record, written at once in its own transaction."""
        name = (name or "").strip()
        if not name:
            raise SessionError(422, "name is required (any text, at least one character)")
        self._check_text("name", name)
        self._check_text("note", note)
        problems = problems or []
        self._validate_problems(problems)
        settings = dict(settings or {})
        for key in settings:
            if key not in _SETTINGS_KEYS:
                raise SessionError(422, f"unknown setting {key!r}; known: {list(_SETTINGS_KEYS)}")
        spp = settings.get("seeds_per_problem", 100)
        if not isinstance(spp, int) or isinstance(spp, bool) or not 1 <= spp <= MAX_SEEDS_PER_PROBLEM:
            raise SessionError(422, f"settings.seeds_per_problem must be 1..{MAX_SEEDS_PER_PROBLEM}")
        seed_start = settings.get("seed_start", 1)
        if not isinstance(seed_start, int) or isinstance(seed_start, bool) or not 0 <= seed_start <= INT32_MAX:
            raise SessionError(422, f"settings.seed_start must be an integer 0..{INT32_MAX}")
        self._check_seed_range(seed_start, [spp] + [p.get("seeds") or 0 for p in problems])
        max_codelets = settings.get(
            "max_codelets", self._meta_provider().get_param("default_max_codelets")
        )
        if (not isinstance(max_codelets, int) or isinstance(max_codelets, bool)
                or not 1 <= max_codelets <= MAX_CODELETS_LIMIT):
            raise SessionError(422, f"settings.max_codelets must be 1..{MAX_CODELETS_LIMIT}")
        base = self._check_configuration_base(settings.get("configuration_base", "training-v2"))
        # The overrides are checked against the configuration the session will start from (its
        # base), because a reference parameter's shape comes from that configuration's
        # ``engine_params.refers_to``, not from the global configuration's.
        async with self._factory() as s:
            try:
                base_document, _id, _revision = await configurations.base_document_for(s, base)
            except configurations.ConfigurationError as exc:
                raise SessionError(422, f"settings.configuration_base: {exc}") from exc
        try:
            overrides = validate_overrides(settings.get("parameters"), cd.provider(base_document))
        except (UnknownParameter, ValueError) as exc:
            raise SessionError(400, str(exc)) from exc
        full_policy = normalize_policy(policy)
        requested_backend = settings.get("backend")
        # A requested backend is checked now; the default depends on the configuration the
        # session starts with, so it is chosen once that exists.
        backend_name = self.resolve_backend(self._meta_provider(), requested_backend)
        # ``settings.parameters`` is folded into the Starting Conceptual State once, here: the
        # session's configuration is the base plus these overrides (as one creation batch), the
        # task carries none, and the stored ``settings.parameters`` stays as the record.
        creation_ops = [{"op": "set_param", "name": n, "to": v} for n, v in overrides.items()]
        from server.services.configuration_writer import ChangeError

        async with self._factory() as s:
            async with s.begin():
                t = TrainingModeSession(
                    name=name, note=note or "",
                    seeds_per_problem=spp, seed_start=seed_start, max_codelets=max_codelets,
                    parameters=overrides or None, backend=backend_name, policy=full_policy,
                    configuration_base=base, config_hash="", finished_count=0, next_problem_id=1,
                )
                s.add(t)
                await s.flush()
                try:
                    cid = await configurations.create_session_configuration(
                        s, t.id, base, creation_ops, name=name, actor="system")
                except configurations.ConfigurationError as exc:
                    raise SessionError(422, f"settings.configuration_base: {exc}") from exc
                except ChangeError as exc:
                    raise SessionError(422, f"the creation overrides were refused ({exc.code}): {exc.message}") from exc
                document = await configurations.current_document(s, cid)
                meta = cd.provider(document)
                # A session whose configuration cannot start a run is not created
                # (the executor makes the same check again at each dispatch).
                try:
                    require_run_start(meta)
                except RunStartError as exc:
                    raise SessionError(422, str(exc)) from exc
                if requested_backend is None:
                    t.backend = default_session_backend(meta)
                t.config_hash = cd.config_hash(document)
                ids = await self._insert_problems(s, t, problems)
            summary = (await self._summaries(s, [t]))[0]  # a new session is Stopped
        return {"session": summary, "added": len(ids), "problem_ids": ids, "persisted": True}

    def _refuse_if_busy(self, session_id: int, what: str) -> LiveSession | None:
        """The live part of a session for a mutation (``None`` when Stopped), or 409 ``busy``
        while it is Starting or Stopping."""
        if session_id in self._starting:
            raise _busy(session_id, what, "starting")
        lt = self._live.get(session_id)
        if lt is not None and lt.status == "stopping":
            raise _busy(session_id, what, "stopping")
        return lt

    async def add_problems(self, session_id: int, problems: list[dict]) -> dict[str, Any]:
        """Add problems.  To a live session they go into memory with the next ordinals (written at
        Stop, ``persisted: false``); to a Stopped one they are written at once."""
        self._validate_problems(problems)
        lt = self._refuse_if_busy(session_id, "add problems to it")
        if lt is not None:
            self._check_seed_range(
                lt.seed_start, [lt.seeds_per_problem] + [p.get("seeds") or 0 for p in problems])
            ids = []
            for p in problems:
                lp = self._add_live_problem(lt, problem_id=lt.next_problem_id, spec=p, stored=False)
                lt.next_problem_id += 1
                ids.append(lp.id)
            self.wake()
            return {"session": self._live_summary(lt), "added": len(ids), "problem_ids": ids,
                    "persisted": False}
        async with self._factory() as s:
            async with s.begin():
                t = (await s.execute(
                    select(TrainingModeSession).where(TrainingModeSession.id == session_id).with_for_update()
                )).scalar_one_or_none()
                if t is None:
                    raise SessionError(404, f"session {session_id} not found")
                self._check_seed_range(
                    t.seed_start, [t.seeds_per_problem] + [p.get("seeds") or 0 for p in problems])
                ids = await self._insert_problems(s, t, problems)
            summary = (await self._summaries(s, [t]))[0]
        return {"session": summary, "added": len(ids), "problem_ids": ids, "persisted": True}

    # -- control -----------------------------------------------------------------

    async def update(self, session_id: int, name: str | None = None, note: str | None = None,
                     policy: dict | None = None) -> dict[str, Any]:
        """Change name, note or policy: in memory for a live session, at once for a Stopped one."""
        if name is not None:
            name = name.strip()
            if not name:
                raise SessionError(422, "name must not be empty")
            self._check_text("name", name)
        if note is not None:
            self._check_text("note", note)
        lt = self._refuse_if_busy(session_id, "change it")
        if lt is not None:
            if policy is not None:
                lt.policy = normalize_policy(policy, lt.policy)
            if name is not None:
                lt.name = name
            if note is not None:
                lt.note = note
            lt.edits += 1
            lt.updated_at = _utcnow()
            await self._announce(session_id)
            self.wake()
            return self._live_summary(lt)
        async with self._factory() as s:
            async with s.begin():
                t = (await s.execute(
                    select(TrainingModeSession).where(TrainingModeSession.id == session_id).with_for_update()
                )).scalar_one_or_none()
                if t is None:
                    raise SessionError(404, f"session {session_id} not found")
                if policy is not None:
                    t.policy = normalize_policy(policy, t.policy)
                if name is not None:
                    t.name = name
                if note is not None:
                    t.note = note
                t.updated_at = _utcnow()
            summary = (await self._summaries(s, [t]))[0]
        await self._announce(session_id)
        return summary

    async def start_session(self, session_id: int, paused: bool = False) -> dict[str, Any]:
        """Stopped -> Starting -> Running (or Paused).  Starting a live session changes nothing.

        The Start only reads: a failed Start leaves the session Stopped, exactly as it was."""
        lt = self._live.get(session_id)
        if lt is not None:
            if lt.status == "stopping":
                raise _busy(session_id, "start it", "stopping")
            return self._live_summary(lt)
        if session_id in self._starting:
            raise _busy(session_id, "start it", "starting")
        if self._closing:
            raise SessionError(409, "busy: the server is shutting down and starts no session")
        self._starting.add(session_id)
        try:
            async with self._factory() as s:
                # The row lock holds off a write to a Stopped record (new problems, a rename)
                # that began just before this Start, so the load sees it.
                t = (await s.execute(
                    select(TrainingModeSession).where(TrainingModeSession.id == session_id).with_for_update()
                )).scalar_one_or_none()
                if t is None:
                    raise SessionError(404, f"session {session_id} not found")
                lt = await self._load_one(s, t)
                lt.status = "paused" if paused else "running"
                # Live before the configuration's row lock is released (this block's exit): a
                # change that was waiting for the lock finds the session live and goes to memory.
                self._live[session_id] = lt
                self._starting.discard(session_id)
        except SessionError:
            raise
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - the load only read: the session is still Stopped
            logger.exception("starting session %d failed", session_id)
            raise SessionError(
                500, f"starting session {session_id} failed; it is still Stopped, exactly as it was: {exc}"
            ) from exc
        finally:
            self._starting.discard(session_id)
        self._check_configs()
        for lp in list(lt.problems.values()):
            for run in list(lp.run_logs.values()):  # a run restored while waiting asks the teacher again
                self._consult_teacher(lt, lp, run)
        for lp in list(lt.problems.values()):
            # Every seed was stored: it only has to finish.  The test is the one ``_record`` uses.  An
            # empty ``lp.todo`` is not it: the block above yielded to the event loop with the session
            # already live, so the scheduler may have dispatched the last seeds meanwhile, and a
            # problem finished here would keep a tally short of the runs still in flight.
            if lp.status == "queued" and len(lp.outcomes) >= lp.seeds:
                lp.started_at = lp.started_at or _utcnow()
                self._finish_problem(lt, lp, "finished")
        await self._announce(session_id)
        self.wake()
        return self._live_summary(lt)

    # -- the session's configuration: changes from every learning source -----------------------

    def _live_state(self, session_id: int) -> store.LiveState | None:
        """The configuration store's live source: the session's configuration as memory holds it,
        or ``None`` when the session is Stopped.  A session that is Starting has no document yet."""
        if session_id in self._starting:
            return store.LiveState("starting", None, 0, 0, 0)
        lt = self._live.get(session_id)
        if lt is None or lt.config is None:
            return None
        c = lt.config
        return store.LiveState(
            state=lt.status, document=c.document, revision=c.revision,
            saved_through=c.saved_revision, unsaved=len(c.changes), saved_at=lt.stopped_at,
            pending=c.pending_entries(),
        )

    @staticmethod
    def _busy_change(session_id: int, state: str) -> Exception:
        from server.services.configuration_writer import BUSY, ChangeError

        return ChangeError(
            BUSY, f"busy: session {session_id} is {state}; wait for it to finish before you "
                  "change its configuration")

    async def apply_live(self, session_id: int, batch: dict[str, Any]) -> dict[str, Any]:
        """Apply *batch* to a live session's configuration, in memory.

        The one door for an external or Admin batch on a live session (``ChangeService.apply``
        and :meth:`submit_changes` both come here).  It goes through the session's episode log:
        it takes the next episode version and the next revision at once, reaches every run
        dispatched afterward (and none already in flight), and is held for the Stop write.  The
        report is the change API's, with ``persisted: false``, ``version_before`` and
        ``version_after`` the configuration revisions, and ``episode_version``.  A batch that
        applies nothing takes no version (a diagnostic).  Refusals are ``ChangeError``s (the
        change API's codes: ``malformed``, ``unknown_reference``, ``stale``, ``key_exists``, ...),
        and ``busy`` while the session is Starting or Stopping.
        """
        from server.services import configuration_writer as writer

        if session_id in self._starting:
            raise self._busy_change(session_id, "starting")
        lt = self._live.get(session_id)
        if lt is None:
            return await self.submit_changes(session_id, batch)
        if lt.status == "stopping":
            raise self._busy_change(session_id, "stopping")
        writer.check_envelope(batch)
        given = batch.get("configuration_id")
        if given is not None and given != lt.config.configuration_id:
            raise writer._malformed(
                f"configuration_id {given} is not session {session_id}'s configuration "
                f"({lt.config.configuration_id})", "configuration_id")
        try:
            out = lt.config.submit(batch)
        except Exception as exc:  # noqa: BLE001 - mapped to the change API's codes, or re-raised
            translated = writer._translate(exc)
            if translated is not None and translated is not exc:
                raise translated from exc
            raise
        if out.applied:
            # The entry took an episode version and has no memory part: an empty merge keeps the
            # version stream, the tail and the stored merge log contiguous.
            lt.version = lt.config.version
            empty = tm.Additions()
            lt.merge_blobs[lt.version] = tm.dump_additions(empty)
            lt.merge_blobs.pop(lt.version - MERGE_KEEP, None)
            lt.pending_merges.append((lt.version, None, None, empty))
            lt.updated_at = _utcnow()
            self.wake()
        return out.report

    async def submit_changes(self, session_id: int, batch: dict[str, Any]) -> dict[str, Any]:
        """A change batch for session ``session_id``'s configuration, in any state.

        The function behind the external route (S6's ``POST /api/training-mode/sessions/{id}/changes``;
        the route sets ``source = external``) and used by every other writer of a session's
        configuration.  Running or Paused: applied in memory (:meth:`apply_live`),
        ``persisted: false``.  Stopped: the stored record is written at once, in its own
        transaction, through ``ChangeService.apply`` (``persisted: true``).  Starting or Stopping:
        409 ``busy``.  Raises :class:`SessionError` 404 for an unknown session, otherwise
        ``configuration_writer.ChangeError``.
        """
        from server.services import configuration_writer as writer

        if session_id in self._starting:
            raise self._busy_change(session_id, "starting")
        lt = self._live.get(session_id)
        if lt is not None:
            return await self.apply_live(session_id, batch)
        writer.check_envelope(batch)
        async with self._factory() as s:
            await self._get_session(s, session_id)
            row = await configurations.row_for_session(s, session_id)
            given = batch.get("configuration_id")
            if given is not None and given != row["id"]:
                raise writer._malformed(
                    f"configuration_id {given} is not session {session_id}'s configuration "
                    f"({row['id']})", "configuration_id")
            return await writer.ChangeService.apply(s, {**batch, "configuration_id": row["id"]})

    def _live_or_409(self, session_id: int, action: str) -> LiveSession:
        lt = self._refuse_if_busy(session_id, action)
        if lt is None:
            raise SessionError(409, f"session {session_id} is stopped; start it before you {action} it")
        return lt

    async def pause(self, session_id: int) -> dict[str, Any]:
        async with self._factory() as s:
            await self._get_session(s, session_id)
        lt = self._live_or_409(session_id, "pause")
        lt.status = "paused"
        await self._announce(session_id)
        return self._live_summary(lt)

    async def resume(self, session_id: int) -> dict[str, Any]:
        async with self._factory() as s:
            await self._get_session(s, session_id)
        lt = self._live_or_409(session_id, "resume")
        if lt.status == "paused":
            for lp in lt.active.values():
                lp.failures.clear()  # a resume is a fresh start for the retry budget
            lt.status = "running"
        await self._announce(session_id)
        self.wake()
        return self._live_summary(lt)

    async def _drain_session(self, lt: LiveSession) -> None:
        """Let the runs in flight finish and merge, up to ``drain_timeout``; discard the rest.

        A discarded run's seed is put back with its problem, so it runs after the next Start
        (or after a Resume, if the Stop fails)."""
        deadline = time.monotonic() + self.drain_timeout
        while lt.inflight_subs and time.monotonic() < deadline:
            self.wake()
            await asyncio.sleep(0.02)
        for sub in list(lt.inflight_subs):
            sub.dropped = True
            lt.inflight_subs.discard(sub)
            sub.lp.inflight -= 1
            if sub.lp.status == "queued":
                self._requeue(lt, sub.lp, sub.seed)

    async def stop_session(self, session_id: int, reason: str = "user") -> dict[str, Any]:
        """Running or Paused -> Stopping -> Stopped.  Runs in flight are drained (up to
        ``drain_timeout``) and merged, the rest are discarded; then everything the session
        produced is written in one transaction (``_write_stop``).  If the write fails nothing
        is written and the session returns to Paused with its memory intact (``last_event``
        says why); Stop may be retried.  A Stopped session is left as it is."""
        if session_id in self._starting:
            raise _busy(session_id, "stop it", "starting")
        lt = self._live.get(session_id)
        if lt is None:
            async with self._factory() as s:
                await self._get_session(s, session_id)
            return await self.summary(session_id)
        if lt.status == "stopping":
            raise _busy(session_id, "stop it", "stopping")
        was = lt.status
        lt.status = "stopping"
        try:
            await self._drain_session(lt)
            await self._write_stop(lt, stopped_from=was, reason=reason)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - nothing was written: back to Paused, memory intact
            logger.exception("stopping session %d failed", session_id)
            lt.status = "paused"
            lt.last_event = f"stop failed, nothing was written: {exc}"
            await self._announce(session_id)
            raise SessionError(
                500, f"stopping session {session_id} failed; it is Paused with its work intact "
                     f"and Stop may be retried: {exc}") from exc
        lt.cancelled = True
        self._live.pop(session_id, None)
        await self._announce(session_id)
        return await self.summary(session_id)

    @staticmethod
    def _problem_row(lt: LiveSession, lp: LiveProblem) -> dict[str, Any]:
        tally = lp.tally or {}
        return {
            "session_id": lt.id, "problem_id": lp.id, "initial": lp.initial, "modified": lp.modified,
            "target": lp.target, "answer": lp.answer, "seeds": lp.seeds, "seed_start": lp.seed_start,
            "tag": lp.tag, "multi_turn": lp.multi_turn, "status": lp.status,
            "runs_done": tally.get("runs_done", 0),
            "errors": tally.get("errors", 0), "capped": tally.get("capped", 0),
            "retries": tally.get("retries", 0), "codelets_total": tally.get("codelets_total", 0),
            "mean_codelets": tally.get("mean_codelets"), "top_answer": tally.get("top_answer"),
            "top_fraction": tally.get("top_fraction"), "none_fraction": tally.get("none_fraction"),
            "distinct_answers": tally.get("distinct_answers", 0), "distribution": tally.get("distribution"),
            "statuses": tally.get("statuses"), "first_error": tally.get("first_error"),
            "finished_seq": lp.finished_seq, "added_at": lp.added_at, "started_at": lp.started_at,
            "finished_at": lp.finished_at,
        }

    async def _write_stop(self, lt: LiveSession, *, stopped_from: str, reason: str) -> None:
        """The Stop write: the one database write of a live session, in one transaction.

        It writes, together:

        * the session row, new problems, outcomes (finished and cancelled problems) and runs;
        * the Episodic Memory merges, and the memory snapshot at the last of them;
        * the configuration's held journal entries (``journal.write_deferred``) and its stored
          current state, revision and hash (``journal.store_current_state``), so the Start read
          loads them back and replays nothing.

        Nothing is removed from the live part until it commits, so a failure leaves the session
        exactly as it was, and the database as the previous Stop left it."""
        P, R = TrainingModeSessionProblem, TrainingModeSessionRun
        now = _utcnow()
        problems = sorted(lt.problems.values(), key=lambda lp: lp.id)
        new_rows = [self._problem_row(lt, lp) for lp in problems if not lp.stored]
        settled = [lp for lp in problems if lp.stored and lp.settled]
        run_rows = [self._run_row(lt, r) for r in lt.pending_runs]
        turn_rows = self._turn_rows(lt)
        merge_rows = await asyncio.to_thread(self._merge_rows, lt, list(lt.pending_merges))
        config = lt.config
        entries = config.pending_entries()
        snapshot = (await asyncio.to_thread(tm.snapshot_blob, lt.memory)
                    if lt.version != lt.saved_version else None)
        async with self._factory() as s:
            async with s.begin():
                for i in range(0, len(new_rows), INSERT_CHUNK):
                    await s.execute(insert(P), new_rows[i:i + INSERT_CHUNK])
                for lp in settled:
                    row = self._problem_row(lt, lp)
                    for k in ("session_id", "problem_id", "initial", "modified", "target", "answer",
                              "seeds", "seed_start", "tag", "added_at"):
                        row.pop(k)
                    await s.execute(update(P).where(
                        P.session_id == lt.id, P.problem_id == lp.id, P.status == "queued").values(**row))
                for i in range(0, len(run_rows), RUN_ROW_CHUNK):
                    await s.execute(insert(R), run_rows[i:i + RUN_ROW_CHUNK])
                for i in range(0, len(turn_rows), RUN_ROW_CHUNK):
                    chunk = pg_insert(TrainingModeSessionTurn).values(turn_rows[i:i + RUN_ROW_CHUNK])
                    keys = ("session_id", "problem_id", "seed", "turn")
                    await s.execute(chunk.on_conflict_do_update(
                        index_elements=list(keys),
                        set_={c: chunk.excluded[c] for c in turn_rows[0] if c not in keys}))
                for i in range(0, len(merge_rows), RUN_ROW_CHUNK):
                    await s.execute(insert(SessionMemoryMerge), merge_rows[i:i + RUN_ROW_CHUNK])
                res = await s.execute(update(TrainingModeSession).where(TrainingModeSession.id == lt.id).values(
                    name=lt.name, note=lt.note, policy=lt.policy, config_hash=lt.config_hash,
                    last_event=lt.last_event, finished_count=lt.finished_count,
                    next_problem_id=lt.next_problem_id, updated_at=now, stopped_at=now,
                    stopped_from=stopped_from, stop_reason=reason,
                    last_change_version=config.last_change_version))
                if res.rowcount == 0:
                    raise SessionError(404, f"session {lt.id} was deleted")
                if snapshot is not None:
                    values = {"version": lt.version, "data": snapshot, "saved_at": now}
                    await s.execute(pg_insert(SessionMemorySnapshot).values(session_id=lt.id, **values)
                                    .on_conflict_do_update(index_elements=["session_id"], set_=values))
                if entries:
                    await journal.write_deferred(
                        s, configuration_id=config.configuration_id, entries=entries, commit=False)
                    await journal.store_current_state(
                        s, config.configuration_id, config.document, revision=config.revision,
                        config_hash=config.config_hash)

    @staticmethod
    def _run_row(lt: LiveSession, r: RunRec) -> dict[str, Any]:
        return {
            "session_id": lt.id, "problem_id": r.problem_id, "seed": r.seed, "status": r.status,
            "key": r.key, "answer": r.answer, "answers": list(r.answers), "codelets": r.codelets,
            "seconds": r.seconds, "temperature": r.temperature, "answer_quality": r.answer_quality,
            "error": r.error, "config_hash": r.config_hash, "attempts": r.attempts, "seq": r.seq,
            "configuration_revision": r.configuration_revision,
            "memory_version": r.memory_version, "added_answers": r.added_answers,
            "added_snags": r.added_snags,
        }

    @staticmethod
    def _turn_rows(lt: LiveSession) -> list[dict[str, Any]]:
        """The turn rows of every run changed since Start (or the last write): each finished turn, and the
        next turn of a run that is queued or was in flight (``status`` ``pending``, with its stored strings,
        so Start can run it again).  Written as upserts: a row that is already stored is replaced."""
        rows = []
        for run in sorted(lt.dirty_runs, key=lambda r: (r.problem_id, r.seed)):
            for t in run.turns:
                rows.append({
                    "session_id": lt.id, "problem_id": run.problem_id, "seed": run.seed, "turn": t.turn,
                    "turn_seed": t.turn_seed, "context": t.context, "second_string": t.second, "input": t.input,
                    "input_from": t.input_from, "status": t.status, "answer": t.answer,
                    "answers": list(t.answers), "answer_quality": t.answer_quality, "codelets": t.codelets,
                    "seconds": t.seconds, "temperature": t.temperature, "error": t.error,
                    "attempts": t.attempts, "added_answers": t.added_answers, "added_snags": t.added_snags,
                    "end_reason": t.end_reason, "end_label": t.end_label, "proposals": list(t.proposals),
                    "evidence": t.evidence, "seq": t.seq, "memory_version": t.memory_version,
                    "configuration_revision": t.configuration_revision, "config_hash": t.config_hash,
                })
            p = run.pending
            if p is not None:
                rows.append({
                    "session_id": lt.id, "problem_id": run.problem_id, "seed": run.seed, "turn": p.turn,
                    "turn_seed": turn_record.turn_seed(run.seed, p.turn), "context": p.context,
                    "second_string": p.second, "input": p.input, "input_from": p.input_from,
                    "status": "pending", "answer": "", "answers": [], "answer_quality": None, "codelets": 0,
                    "seconds": 0.0, "temperature": 0.0, "error": None, "attempts": 1, "added_answers": 0,
                    "added_snags": 0, "end_reason": None, "end_label": None, "proposals": [], "evidence": None,
                    "seq": None, "memory_version": None, "configuration_revision": None, "config_hash": "",
                })
        return rows

    @staticmethod
    def _merge_rows(lt: LiveSession, merges: list) -> list[dict[str, Any]]:
        rows = []
        for seq, pid, seed, adds in merges:
            answers, snags = tm.encode_additions(adds)
            rows.append({"session_id": lt.id, "seq": seq, "problem_id": pid, "seed": seed,
                         "answers": answers, "snags": snags})
        return rows

    async def cancel_problem(self, session_id: int, pid: int) -> dict[str, Any]:
        lt = self._refuse_if_busy(session_id, "cancel a problem of it")
        if lt is not None:
            lp = lt.problems.get(pid)
            if lp is None:  # a finished or cancelled stored problem: nothing to cancel
                async with self._factory() as s:
                    await self._get_problem(s, session_id, pid)
            else:
                self._finish_problem(lt, lp, "cancelled")
                await self._announce(session_id)
            return await self.get_problem(session_id, pid)
        async with self._factory() as s:
            async with s.begin():
                p = await self._get_problem(s, session_id, pid)
                if p.status == "queued":
                    await s.execute(update(TrainingModeSessionProblem).where(
                        TrainingModeSessionProblem.session_id == session_id,
                        TrainingModeSessionProblem.problem_id == pid,
                        TrainingModeSessionProblem.status == "queued",
                    ).values(status="cancelled", finished_at=_utcnow()))
        await self._announce(session_id)
        return await self.get_problem(session_id, pid)

    async def cancel_session(self, session_id: int, event: str | None = None) -> dict[str, Any]:
        """Cancel every queued and in-flight problem.  An action, not a state: the session
        keeps its state and accepts new problems afterwards."""
        async with self._factory() as s:
            await self._get_session(s, session_id)
        lt = self._refuse_if_busy(session_id, "cancel its problems")
        if lt is not None:
            if event is not None:
                lt.last_event = event
            self._cancel_all_live(lt)
            await self._announce(session_id)
            return self._live_summary(lt)
        async with self._factory() as s:
            async with s.begin():
                await s.execute(update(TrainingModeSessionProblem).where(
                    TrainingModeSessionProblem.session_id == session_id, TrainingModeSessionProblem.status == "queued"
                ).values(status="cancelled", finished_at=_utcnow()))
                if event is not None:
                    await s.execute(update(TrainingModeSession).where(TrainingModeSession.id == session_id)
                                    .values(last_event=event))
        await self._announce(session_id)
        return await self.summary(session_id)

    async def delete_session(self, session_id: int) -> None:
        """Delete a session and everything it owns: its Episodic Memory, problems and runs
        (the foreign keys cascade) and its live part, which is discarded with no Stop
        write.  Nothing is left behind.  This is the only act that removes its memory."""
        async with self._factory() as s:
            await self._get_session(s, session_id)
        lt = self._refuse_if_busy(session_id, "delete it")
        if lt is not None:
            lt.cancelled = True
            for lp in lt.problems.values():
                lp.cancelled = True  # later outcomes of runs in flight are dropped
            self._live.pop(session_id, None)
        async with self._factory() as s:
            async with s.begin():
                await s.execute(delete(TrainingModeSession).where(TrainingModeSession.id == session_id))
        self._after_run.pop(session_id, None)
        self._teachers.pop(session_id, None)
        self._versions.pop(session_id, None)
        await self._announce(session_id)
        self._conds.pop(session_id, None)

    # -- export streams ---------------------------------------------------------
    #
    # A Stopped session streams its stored rows.  A live session streams the stored rows (as of
    # its last Stop) and then a labelled tail from memory (the API says so in a header).

    async def iter_problem_dicts(self, session_id: int) -> AsyncIterator[list[dict[str, Any]]]:
        P = TrainingModeSessionProblem
        lt = self._live.get(session_id)
        last = 0
        while True:
            async with self._factory() as s:
                conds = [P.session_id == session_id, P.problem_id > last]
                if lt is not None:
                    conds.append(P.status != "queued")  # every queued stored row is in memory
                rows = (await s.execute(select(P).where(*conds).order_by(P.problem_id).limit(1000))).scalars().all()
            if not rows:
                break
            last = rows[-1].problem_id
            yield [self._stored_problem_dict(p, True) for p in rows]
        if lt is not None:
            mem = [self._live_problem_dict(lp, True) for lp in sorted(lt.problems.values(), key=lambda lp: lp.id)]
            for i in range(0, len(mem), 1000):
                yield mem[i:i + 1000]

    async def iter_run_rows(self, session_id: int) -> AsyncIterator[list[dict[str, Any]]]:
        """Run rows with their problem's identity, in (problem, seed) order (stored rows first,
        then, for a live session, the runs only memory holds)."""
        from sqlalchemy import tuple_

        R, P = TrainingModeSessionRun, TrainingModeSessionProblem
        lt = self._live.get(session_id)
        last = (0, -(2 ** 62))
        while True:
            async with self._factory() as s:
                rows = (await s.execute(
                    select(R, P.initial, P.modified, P.target, P.answer)
                    .join(P, (P.session_id == R.session_id) & (P.problem_id == R.problem_id))
                    .where(R.session_id == session_id, tuple_(R.problem_id, R.seed) > tuple_(*last))
                    .order_by(R.problem_id, R.seed).limit(2000)
                )).all()
            if not rows:
                break
            last = (rows[-1][0].problem_id, rows[-1][0].seed)
            yield [
                {"problem_id": r.problem_id, "initial": i, "modified": m, "target": t,
                 "problem_answer": a, **self._run_dict(r)}
                for r, i, m, t, a in rows
            ]
        if lt is not None:
            tail = sorted(lt.pending_runs, key=lambda r: (r.problem_id, r.seed))
            for i in range(0, len(tail), 2000):
                out = []
                for r in tail[i:i + 2000]:
                    lp = lt.problems.get(r.problem_id)
                    out.append({
                        "problem_id": r.problem_id, "initial": lp.initial if lp else None,
                        "modified": lp.modified if lp else None, "target": lp.target if lp else None,
                        "problem_answer": lp.answer if lp else None, **self._run_dict(r),
                    })
                yield out


# ---------------------------------------------------------------------------
# The process-wide service
# ---------------------------------------------------------------------------

_service: TrainingModeSessionService | None = None


def get_training_mode_session_service() -> TrainingModeSessionService | None:
    return _service


def set_training_mode_session_service(service: TrainingModeSessionService | None) -> None:
    global _service
    _service = service


async def start_default_service(meta_provider: Callable[[], MetadataProvider]) -> TrainingModeSessionService:
    from server.db import async_session_factory

    service = TrainingModeSessionService(async_session_factory, meta_provider)
    await service.start()
    set_training_mode_session_service(service)
    return service


async def stop_default_service() -> None:
    service = get_training_mode_session_service()
    set_training_mode_session_service(None)
    if service is not None:
        await service.stop()
