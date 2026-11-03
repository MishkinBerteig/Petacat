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

The database is written only at milestones (see ``server/services/training_mode_session_service.py``):
a Training Mode Session or its problems are created or changed, and **once when a problem finishes** --
that problem's summary, every run committed since the last write from any problem, and the
memory merges since the last write, in one transaction.  ``running`` is live-only.

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
    BigInteger, CheckConstraint, Column, DateTime, Float, ForeignKey, Index, Integer,
    String, Text, UniqueConstraint,
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
    name = Column(String(200), nullable=False)
    note = Column(Text, nullable=False, default="")

    # Settings: fixed at creation, because they shape what a run is.
    seeds_per_problem = Column(Integer, nullable=False, default=100)
    seed_start = Column(Integer, nullable=False, default=1)
    max_codelets = Column(Integer, nullable=False, default=20000)
    parameters = Column(JSONB, nullable=True)
    backend = Column(String(32), nullable=False)

    #: The error policy (``ErrorPolicy`` in the API contract); changeable at any time.
    policy = Column(JSONB, nullable=False)
    #: ``hashing.config_hash`` of the metadata the Training Mode Session runs under.
    config_hash = Column(String(64), nullable=False, default="")
    #: The last ``finished_seq`` handed out; incremented in the finishing transaction.
    finished_count = Column(Integer, nullable=False, default=0)
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

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(
        Integer, ForeignKey("training_mode_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    initial = Column(String(64), nullable=False)
    modified = Column(String(64), nullable=False)
    target = Column(String(64), nullable=False)
    answer = Column(String(64), nullable=True)
    seeds = Column(Integer, nullable=False)
    seed_start = Column(Integer, nullable=False)
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
        UniqueConstraint("problem_id", "seed", name="uq_training_mode_session_runs_problem_seed"),
        Index("ix_training_mode_session_runs_session_seq", "session_id", "seq"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    session_id = Column(
        Integer, ForeignKey("training_mode_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    problem_id = Column(
        Integer, ForeignKey("training_mode_session_problems.id", ondelete="CASCADE"), nullable=False
    )
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
    config_hash = Column(String(64), nullable=False, default="")
    attempts = Column(Integer, nullable=False, default=1)
    #: Merge order in the Training episode.
    seq = Column(Integer, nullable=False)
    #: The Episodic Memory version the run started with.
    memory_version = Column(Integer, nullable=False)
    #: What the merge actually added to the episode after the presence checks.
    added_answers = Column(Integer, nullable=False)
    added_snags = Column(Integer, nullable=False)


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

# Registered here so every drop_all/create_all that imports the runtime models also covers
# ``configuration_state`` (the start-up load marker; see server/services/configuration_startup.py).
import server.models.configuration_state  # noqa: E402,F401
