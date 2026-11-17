"""SQLAlchemy models for Training Mode Sessions: named, long-lived episodes of
many problems over many seeds.

A **Training Mode Session** owns one Training episode and so one Episodic Memory, which each run copies
when it starts and merges its additions into when it finishes.  Every Training Mode Session has one; it
is never cleared and goes only when the whole Training Mode Session is deleted.  A Training Mode Session holds
problems; a problem holds its per-seed runs; the memory merges are logged in order so the
memory can be rebuilt exactly.

(Metacat Mode's episodic runs share the process Episodic Memory until it is cleared; the
clears are ``episodic_memory_clears`` in ``server/models/run.py``.  A Training Mode Session is a different
thing.)

The database is written only when a Training Mode Session is Stopped (see
``server/services/training_mode_session_service.py``): the Stop write puts the session row, new
problems, outcomes, runs and memory merges in one transaction.  A Stopped session's record is
written at once (creating it, renaming it, adding problems).  ``running`` is live-only.

A **run** (a problem at one seed) has one or more **turns**, one row each in ``training_mode_session_turns`` (a
single-turn problem's run has exactly one); the runs row is the run as one outcome of its problem and is written
when the run ends, so a run that is waiting for the teacher's input, or has a turn pending, has turn rows and no
runs row.

A problem's identifier is a per-session **ordinal**: ``(session_id, problem_id)`` is its key,
so the identifier a live session hands out is the stored one.  Runs and merges name their
problem by the same ordinal.

A Training Mode Session row carries no live state.  Its state (Stopped, Running or Paused) is held by the
service: a Training Mode Session that is not live is **Stopped**, which is every Training Mode Session after a server
restart.  The row records only the last Stop (``stopped_at``, ``stopped_from``,
``stop_reason``).

The status columns are plain strings with CHECK constraints rather than foreign keys to
enum tables: the enum tables are derived metadata that a re-seed rewrites, and these are
runtime tables whose value sets are fixed by the service.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Column, DateTime, Float, ForeignKey, ForeignKeyConstraint, Index,
    Integer, LargeBinary, String, Text, UniqueConstraint, false,
)
from sqlalchemy.dialects.postgresql import JSONB

from server.models.metadata import Base
from server.models.run import _utcnow

STOPPED_FROM = ("running", "paused")
STOP_REASONS = ("user", "shutdown", "error")
PROBLEM_STATUSES = ("queued", "finished", "cancelled")


class TrainingModeSession(Base):
    __tablename__ = "training_mode_sessions"
    __table_args__ = (
        CheckConstraint("stopped_from IN ('running','paused')", name="ck_training_mode_sessions_stopped_from"),
        CheckConstraint("stop_reason IN ('user','shutdown','error')", name="ck_training_mode_sessions_stop_reason"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(Text, nullable=False)
    note = Column(Text, nullable=False, default="")

    # Settings: fixed at creation, because they shape what a run is.
    seeds_per_problem = Column(Integer, nullable=False, default=100)
    seed_start = Column(Integer, nullable=False, default=1)
    max_codelets = Column(Integer, nullable=False)
    parameters = Column(JSONB, nullable=True)
    backend = Column(String(32), nullable=False)
    #: Where the session's configuration came from, fixed at creation: ``"training-v2"``
    #: (the default: the Training Mode Base Configuration, v2.0), ``"global"``, ``"standard"``
    #: or ``{"session_id": n}``.  The session's own configuration is the
    #: ``configurations`` row whose ``session_id`` is this session's; ``parameters`` above is
    #: folded into it at creation and stays here as the record.
    configuration_base = Column(JSONB, nullable=False, default="training-v2")

    #: The error policy (``ErrorPolicy`` in the API contract); changeable at any time.
    policy = Column(JSONB, nullable=False)
    #: ``hashing.config_hash`` of the session's own configuration, as of the last Stop (or its
    #: creation).  A live session's current hash is in memory.
    config_hash = Column(String(64), nullable=False, default="")
    #: The Training episode version of the configuration's last change, as of the last Stop
    #: (``None`` if it has never changed); the Start read takes it from here, not from the journal.
    last_change_version = Column(Integer, nullable=True)
    #: The last ``finished_seq`` handed out, as of the last Stop.
    finished_count = Column(Integer, nullable=False, default=0)
    #: The next per-session problem ordinal, as of the last Stop.
    next_problem_id = Column(Integer, nullable=False, default=1)
    #: A human sentence for the last time a policy acted ("paused: 5 errors ...").
    last_event = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)
    #: The last Stop: when, from which live state, and why.  Null for a Training Mode Session never stopped.
    stopped_at = Column(DateTime, nullable=True)
    stopped_from = Column(String(16), nullable=True)
    stop_reason = Column(String(16), nullable=True)


class TrainingModeSessionProblem(Base):
    __tablename__ = "training_mode_session_problems"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','finished','cancelled')", name="ck_training_mode_session_problems_status"
        ),
        Index("ix_training_mode_session_problems_session_status", "session_id", "status"),
        Index("ix_training_mode_session_problems_session_seq", "session_id", "finished_seq"),
    )

    session_id = Column(
        Integer, ForeignKey("training_mode_sessions.id", ondelete="CASCADE"), primary_key=True
    )
    #: The problem's ordinal within its session (the API's ``problem_id``).
    problem_id = Column(Integer, primary_key=True, autoincrement=False)
    initial = Column(Text, nullable=False)
    modified = Column(Text, nullable=False)
    target = Column(Text, nullable=False)
    answer = Column(Text, nullable=True)
    seeds = Column(Integer, nullable=False)
    seed_start = Column(Integer, nullable=False)
    #: A multi-turn problem: each of its runs is a chat, a turn per engine run, that goes on while the
    #: teacher supplies inputs (``training_mode_session_turns``).  A problem without it is one turn.
    multi_turn = Column(Boolean, nullable=False, default=False, server_default=false())
    #: The client's own label for the problem, returned untouched.
    tag = Column(JSONB, nullable=True)
    status = Column(String(16), nullable=False, default="queued")

    # Summary, filled when the problem finishes (or is cancelled) so SQL can sort/filter.
    runs_done = Column(Integer, nullable=False, default=0)
    errors = Column(Integer, nullable=False, default=0)
    capped = Column(Integer, nullable=False, default=0)
    retries = Column(Integer, nullable=False, default=0)
    codelets_total = Column(BigInteger, nullable=False, default=0)
    mean_codelets = Column(Float, nullable=True)
    top_answer = Column(Text, nullable=True)
    top_fraction = Column(Float, nullable=True)
    none_fraction = Column(Float, nullable=True)
    distinct_answers = Column(Integer, nullable=False, default=0)
    #: ``[{answer, count, quality_sum, quality_n}]``, most frequent first.
    distribution = Column(JSONB, nullable=True)
    statuses = Column(JSONB, nullable=True)
    first_error = Column(Text, nullable=True)

    finished_seq = Column(Integer, nullable=True)
    added_at = Column(DateTime, nullable=False, default=_utcnow)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)


class TrainingModeSessionRun(Base):
    __tablename__ = "training_mode_session_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["session_id", "problem_id"],
            ["training_mode_session_problems.session_id", "training_mode_session_problems.problem_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("session_id", "problem_id", "seed", name="uq_training_mode_session_runs_problem_seed"),
        Index("ix_training_mode_session_runs_session_seq", "session_id", "seq"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    session_id = Column(
        Integer, ForeignKey("training_mode_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: The problem's ordinal in the session.
    problem_id = Column(Integer, nullable=False)
    seed = Column(Integer, nullable=False)
    status = Column(String(16), nullable=False)
    #: ``answer`` | ``*CAP*`` | ``*ERROR*`` | ``*NONE*``.
    key = Column(Text, nullable=False)
    answer = Column(Text, nullable=False, default="")
    answers = Column(JSONB, nullable=True)
    codelets = Column(Integer, nullable=False, default=0)
    seconds = Column(Float, nullable=False, default=0.0)
    temperature = Column(Float, nullable=False, default=0.0)
    answer_quality = Column(Float, nullable=True)
    error = Column(Text, nullable=True)
    #: The hash of the session's configuration at the run's episode version.
    config_hash = Column(String(64), nullable=False, default="")
    #: The revision of that configuration (``configurations.revision`` of the session's own
    #: configuration): the last configuration change at or before the run's episode version.
    configuration_revision = Column(Integer, nullable=True)
    attempts = Column(Integer, nullable=False, default=1)
    #: Merge order in the Training episode.
    seq = Column(Integer, nullable=False)
    #: The Training episode version the run started from (the API's ``episode_version``): one
    #: counter over Episodic Memory and the whole configuration.
    memory_version = Column(Integer, nullable=False)
    #: What the merge actually added to the episode after the presence checks.
    added_answers = Column(Integer, nullable=False)
    added_snags = Column(Integer, nullable=False)


class TrainingModeSessionTurn(Base):
    """One turn of a run: one engine run, keyed ``(session, problem, seed, turn)``.

    Every run has at least one turn row (a single-turn problem's run has exactly one, turn 1).  The four
    positions are the turn's context, second string and input, and the response Petacat constructed
    (``answer``, set when the turn answered).  A turn of a multi-turn run after the first has its context
    and second string from the window (``training_mode_session_service`` and ``turn_record``): its context is
    the previous turn's context, second string and input joined with single spaces, and its second string is
    the previous turn's response.

    ``status`` is the engine run's status, or ``pending`` for a turn that was dispatched or queued and had not
    finished when the session was Stopped (it is run again, from these stored positions, on Start).  A run is
    **waiting** when its last row has an ``answer``, no ``end_reason`` and the status is not ``pending``;
    ``end_reason`` is set on the last row of a run that has ended.  The Stop write is the only writer.
    """

    __tablename__ = "training_mode_session_turns"
    __table_args__ = (
        ForeignKeyConstraint(
            ["session_id", "problem_id"],
            ["training_mode_session_problems.session_id", "training_mode_session_problems.problem_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("input_from IN ('problem','teacher')", name="ck_training_mode_session_turns_input_from"),
        CheckConstraint(
            "end_reason IS NULL OR end_reason IN ('single-turn','no-answer','teacher','error','cancelled')",
            name="ck_training_mode_session_turns_end_reason",
        ),
        Index("ix_training_mode_session_turns_session_problem", "session_id", "problem_id"),
    )

    session_id = Column(Integer, ForeignKey("training_mode_sessions.id", ondelete="CASCADE"), primary_key=True)
    #: The problem's ordinal in the session.
    problem_id = Column(Integer, primary_key=True, autoincrement=False)
    #: The run's seed (the problem's seed for turn 1).
    seed = Column(Integer, primary_key=True, autoincrement=False)
    #: The turn number, from 1.
    turn = Column(Integer, primary_key=True, autoincrement=False)
    #: The seed this turn's engine run used: the run's seed for turn 1, ``turn_record.turn_seed`` after.
    turn_seed = Column(BigInteger, nullable=False)
    context = Column(Text, nullable=False)
    second_string = Column(Text, nullable=False)
    input = Column(Text, nullable=False)
    #: Who supplied the input: ``problem`` (turn 1) or ``teacher``.
    input_from = Column(String(16), nullable=False)
    status = Column(String(16), nullable=False)
    #: The Workspace's answer string at the end of the turn (the response when ``status`` is ``answer_found``).
    answer = Column(Text, nullable=False, default="")
    answers = Column(JSONB, nullable=True)
    answer_quality = Column(Float, nullable=True)
    codelets = Column(Integer, nullable=False, default=0)
    seconds = Column(Float, nullable=False, default=0.0)
    temperature = Column(Float, nullable=False, default=0.0)
    error = Column(Text, nullable=True)
    attempts = Column(Integer, nullable=False, default=1)
    #: What this turn's merge added to the Episodic Memory (summed into the run's row).
    added_answers = Column(Integer, nullable=False, default=0)
    added_snags = Column(Integer, nullable=False, default=0)
    #: Why the run ended, on its last turn: ``single-turn``, ``no-answer``, ``teacher`` (with ``end_label``),
    #: ``error`` or ``cancelled``.  ``NULL`` while the run goes on.
    end_reason = Column(String(16), nullable=True)
    end_label = Column(Text, nullable=True)
    #: The change-API ops the turn's codelets built or proposed (what the in-worker learner submitted).
    proposals = Column(JSONB, nullable=True)
    #: What the turn's Workspace built (``turn_record.gather_evidence``): bonds and groups by category, the
    #: rule, the snags, the symbols still unperceived and the Coderack's pressure.
    evidence = Column(JSONB, nullable=True)
    #: The merge order, the Training episode version the turn started from, the configuration revision it
    #: ran under and that configuration's hash; ``NULL`` for a turn still ``pending``.
    seq = Column(Integer, nullable=True)
    memory_version = Column(Integer, nullable=True)
    configuration_revision = Column(Integer, nullable=True)
    config_hash = Column(String(64), nullable=False, default="")


class SessionMemoryMerge(Base):
    """One run's additions to the episode memory, in merge order.

    ``seq`` is the merge number: the episode memory's version after this merge.  Replaying
    the merges in order rebuilds the memory exactly (``training_mode_session_memory.apply_merge``).
    """

    __tablename__ = "training_memory_merges"
    __table_args__ = (UniqueConstraint("session_id", "seq", name="uq_session_memory_merges_seq"),)

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    session_id = Column(
        Integer, ForeignKey("training_mode_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seq = Column(Integer, nullable=False)
    problem_id = Column(Integer, nullable=True)
    seed = Column(Integer, nullable=True)
    #: The run's new descriptions, oldest first, as ``state_graph`` records.
    answers = Column(JSONB, nullable=True)
    snags = Column(JSONB, nullable=True)


class SessionMemorySnapshot(Base):
    """The session's Episodic Memory as of its last Stop: what the Start read loads.

    The Stop write replaces it in the same transaction that appends the merges it covers, so
    ``version`` is the last stored merge's ``seq``.  Start loads this row and replays no merge
    (the merges stay as the record, and ``rebuild_memory`` can replay them to check it).
    """

    __tablename__ = "training_mode_session_memory_snapshots"

    session_id = Column(
        Integer, ForeignKey("training_mode_sessions.id", ondelete="CASCADE"), primary_key=True
    )
    #: The Training episode version the snapshot is at.
    version = Column(Integer, nullable=False)
    #: ``training_mode_session_memory.snapshot_blob``.
    data = Column(LargeBinary, nullable=False)
    saved_at = Column(DateTime, nullable=False, default=_utcnow)


# Registered here so every drop_all/create_all that imports the runtime models also covers
# ``configuration_state`` (the start-up load marker; see server/services/configuration_startup.py).
import server.models.configuration_state  # noqa: E402,F401
