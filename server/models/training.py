"""SQLAlchemy models for Trainings: named, long-lived episodes of many problems over many seeds.

A **Training** owns one episode: with ``memory = 'shared'`` a single Episodic Memory that
each run copies when it starts and merges its additions into when it finishes.  It holds
problems; a problem holds its per-seed runs; the memory merges are logged in order so the
memory can be rebuilt exactly.

(Metacat Mode's episodic runs share the process Episodic Memory until it is cleared; the
clears are ``episodic_memory_clears`` in ``server/models/run.py``.  A Training is a different
thing.)

The database is written only at milestones (see ``server/services/training_service.py``):
a Training or its problems are created or changed, and **once when a problem finishes** --
that problem's summary, every run committed since the last write from any problem, and the
memory merges since the last write, in one transaction.  ``running`` is live-only.

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

TRAINING_STATUSES = ("open", "paused", "closed", "cancelled")
PROBLEM_STATUSES = ("queued", "finished", "cancelled")
MEMORY_MODES = ("shared", "independent")


class Training(Base):
    __tablename__ = "trainings"
    __table_args__ = (
        CheckConstraint("status IN ('open','paused','closed','cancelled')", name="ck_trainings_status"),
        CheckConstraint("memory IN ('shared','independent')", name="ck_trainings_memory"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    note = Column(Text, nullable=False, default="")
    status = Column(String(16), nullable=False, default="open")

    # Settings: fixed at creation, because they shape what a run is.
    memory = Column(String(16), nullable=False, default="shared")
    seeds_per_problem = Column(Integer, nullable=False, default=100)
    seed_start = Column(Integer, nullable=False, default=1)
    max_codelets = Column(Integer, nullable=False, default=20000)
    parameters = Column(JSONB, nullable=True)
    backend = Column(String(32), nullable=False)

    #: The error policy (``ErrorPolicy`` in the API contract); changeable at any time.
    policy = Column(JSONB, nullable=False)
    #: ``hashing.config_hash`` of the metadata the Training runs under.
    config_hash = Column(String(64), nullable=False, default="")
    #: The last ``finished_seq`` handed out; incremented in the finishing transaction.
    finished_count = Column(Integer, nullable=False, default=0)
    #: A human sentence for the last time a policy acted ("paused: 5 errors ...").
    last_event = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)
    closed_at = Column(DateTime, nullable=True)


class TrainingProblem(Base):
    __tablename__ = "training_problems"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','finished','cancelled')", name="ck_training_problems_status"
        ),
        Index("ix_training_problems_training_status", "training_id", "status"),
        Index("ix_training_problems_training_seq", "training_id", "finished_seq"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    training_id = Column(
        Integer, ForeignKey("trainings.id", ondelete="CASCADE"), nullable=False, index=True
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


class TrainingRun(Base):
    __tablename__ = "training_runs"
    __table_args__ = (
        UniqueConstraint("problem_id", "seed", name="uq_training_runs_problem_seed"),
        Index("ix_training_runs_training_seq", "training_id", "seq"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    training_id = Column(
        Integer, ForeignKey("trainings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    problem_id = Column(
        Integer, ForeignKey("training_problems.id", ondelete="CASCADE"), nullable=False
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
    #: Merge order in the episode (shared memory); null for independent runs.
    seq = Column(Integer, nullable=True)
    #: The memory version the run started with (shared memory).
    memory_version = Column(Integer, nullable=True)
    #: What the merge actually added to the episode after the presence checks.
    added_answers = Column(Integer, nullable=True)
    added_snags = Column(Integer, nullable=True)


class TrainingMemoryMerge(Base):
    """One run's additions to the episode memory, in merge order.

    ``seq`` is the merge number: the episode memory's version after this merge.  Replaying
    the merges in order rebuilds the memory exactly (``training_memory.apply_merge``).
    """

    __tablename__ = "training_memory_merges"
    __table_args__ = (UniqueConstraint("training_id", "seq", name="uq_training_merges_seq"),)

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    training_id = Column(
        Integer, ForeignKey("trainings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seq = Column(Integer, nullable=False)
    problem_id = Column(Integer, nullable=True)
    seed = Column(Integer, nullable=True)
    #: The run's new descriptions, oldest first, as ``state_graph`` records.
    answers = Column(JSONB, nullable=True)
    snags = Column(JSONB, nullable=True)
