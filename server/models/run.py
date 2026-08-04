"""SQLAlchemy ORM models for run state."""

from __future__ import annotations

from datetime import datetime, timezone


def _utcnow() -> datetime:
    """Naive UTC datetime — avoids the deprecated datetime.utcnow()."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, Integer, String, Text, Float, Boolean
from sqlalchemy.dialects.postgresql import JSONB

from server.models.metadata import Base


class TrainingSession(Base):
    """A sequence of Runs sharing one Episodic Memory (WP3.0).

    The concept already existed and already worked — Episodic Memory is carried across
    Run boundaries by injection, and a memory clear is already the boundary between one
    session and the next. What was missing was any way to *say so*: Runs could not be
    grouped, and there was no row to hang a session's identity on. This adds the
    representation and changes no behaviour; in particular it does not touch
    ``init_mcat``.

    ``ended_at`` is set when the memory is cleared, which is what ends a session.
    """

    __tablename__ = "training_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    started_at = Column(DateTime, default=_utcnow)
    #: Set by ``POST /api/memory/clear`` — the action that ends a session by
    #: discarding the one thing that crosses Run boundaries.
    ended_at = Column(DateTime, nullable=True)
    note = Column(Text, default="")


class RunStateCapture(Base):
    """A complete Petacat state, captured at a Run boundary (WP3.4/WP3.7).

    Normal mode writes exactly two of these per Run: one before the first codelet and
    one after the last. That is the whole of what Normal persists, and it is enough to
    re-execute the Run — reload the start state, run, and the end state must follow.

    Replaces ``cycle_snapshots``, which wrote a ~43 KB blob every fifteenth codelet
    that no code path could read back. The difference is not the cadence but the
    content: this is the id-based object graph from ``server/engine/state_graph.py``,
    complete enough to restore, where the old blob was assembled for display.
    """

    __tablename__ = "run_state_captures"
    __table_args__ = (
        Index("ix_run_state_captures_run_boundary", "run_id", "boundary"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Integer, nullable=False, index=True)
    #: ``start`` or ``end``.
    boundary = Column(String(8), nullable=False)
    codelet_count = Column(Integer, nullable=False, default=0)
    #: The ``state_graph`` capture. Versioned by its own ``format_version`` field.
    state = Column(JSONB, nullable=False)
    created_at = Column(DateTime, default=_utcnow)


class AuditAction(Base):
    """One state-changing action during an Audit Run (WP3.8).

    Audit records every action rather than the two boundary states, so that any
    intermediate state can be reconstructed by replaying forward from the Run-start
    capture. ``sequence`` is the replay order and is dense within a Run.

    ``before`` carries enough of the prior state to invert the action later. Phase 0
    ships forward stepping only, but backwards scrubbing constrains the *format* rather
    than only the UI, so the format admits it now and the machinery is deferred.
    """

    __tablename__ = "audit_actions"
    __table_args__ = (
        Index("ix_audit_actions_run_sequence", "run_id", "sequence"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Integer, nullable=False, index=True)
    sequence = Column(Integer, nullable=False)
    codelet_count = Column(Integer, nullable=False)
    action_type = Column(String(32), nullable=False)
    temperature = Column(Float, nullable=False, default=0.0)
    payload = Column(JSONB, nullable=True)
    #: State prior to the action, sufficient to invert it. Not read in Phase 0.
    before = Column(JSONB, nullable=True)


class Run(Base):
    """A single Metacat run."""

    __tablename__ = "runs"
    __table_args__ = (
        Index("ix_runs_status", "status"),
        Index("ix_runs_created_at", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    initial_string = Column(String(64), nullable=False)
    modified_string = Column(String(64), nullable=False)
    target_string = Column(String(64), nullable=False)
    answer_string = Column(String(64), nullable=True)
    seed = Column(BigInteger, nullable=False)
    status = Column(String(16), ForeignKey("run_statuses.name"), default="initialized")
    justify_mode = Column(Boolean, default=False)
    self_watching = Column(Boolean, default=True)
    codelet_count = Column(Integer, default=0)
    temperature = Column(Float, default=100.0)
    #: Which Slipnet nodes were allowed to spread during this run (0-100).
    #: Recorded per run because it changes what the run does — 100 is the
    #: original's behaviour, and a run at any other value is not comparable with
    #: the dissertation's. ``server_default`` so pre-existing rows read as 100.
    spreading_threshold = Column(
        Integer, nullable=False, default=100, server_default="100",
    )
    #: Which Training Session this Run belongs to (WP3.0). Nullable so Runs recorded
    #: before sessions existed still read back.
    session_id = Column(Integer, nullable=True, index=True)
    #: Persistence mode — a property of the Run, chosen at creation, never a global
    #: setting: later phases want a Fast corpus-training population and a Normal live
    #: dialogue in the same process.
    mode = Column(String(8), nullable=False, default="normal", server_default="normal")
    #: Hash of the MetadataProvider this Run executed under (WP3.5).
    config_hash = Column(String(64), nullable=True)
    #: Identifies the Episodic Memory state the Run executed against (WP3.5). Two runs
    #: with the same seed and different memory hashes are distinguishable in the record,
    #: which matters once Phase 1 puts the concept vocabulary in episodic memory.
    memory_hash = Column(String(64), nullable=True)
    #: Every run parameter's *resolved* value for this Run — the whole set, not just the
    #: overrides. Stored whole because the global defaults can change afterwards, and a
    #: record of overrides alone would have to be read against whatever the defaults are
    #: at the time of reading, so the Run's meaning would quietly drift. Written for
    #: Normal and Audit; a Fast Run has no row, by design.
    parameters = Column(JSONB, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class CycleSnapshot(Base):
    """Full engine state checkpoint for resume/replay."""

    __tablename__ = "cycle_snapshots"
    __table_args__ = (
        Index("ix_cycle_snapshots_run_step", "run_id", "codelet_count"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Integer, nullable=False, index=True)
    codelet_count = Column(Integer, nullable=False)
    temperature = Column(Float, nullable=False)
    rng_state = Column(JSONB, nullable=False)  # Pickled RNG state
    workspace_state = Column(JSONB, nullable=False)  # Serialized workspace structures
    slipnet_state = Column(JSONB, nullable=False)  # Node activations
    coderack_state = Column(JSONB, nullable=False)  # Bin contents
    themespace_state = Column(JSONB, nullable=False)  # Theme activations
    trace_state = Column(JSONB, nullable=False)  # Clamp period state
    runner_state = Column(JSONB, nullable=False)  # Control state
    created_at = Column(DateTime, default=_utcnow)


class TraceEventRow(Base):
    """Persisted trace event."""

    __tablename__ = "trace_events"
    __table_args__ = (
        Index("ix_trace_events_run_number", "run_id", "event_number"),
        Index("ix_trace_events_run_type", "run_id", "event_type"),
        Index("ix_trace_events_run_step", "run_id", "codelet_count"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Integer, nullable=False, index=True)
    event_number = Column(Integer, nullable=False)
    event_type = Column(String(32), ForeignKey("event_types.name"), nullable=False)
    codelet_count = Column(Integer, nullable=False)
    temperature = Column(Float, nullable=False)
    description = Column(Text, default="")
    structures = Column(JSONB, nullable=True)
    theme_pattern = Column(JSONB, nullable=True)
    created_at = Column(DateTime, default=_utcnow)


class AnswerDescriptionRow(Base):
    """Persisted answer description (cross-run episodic memory)."""

    __tablename__ = "answer_descriptions"
    __table_args__ = (
        Index("ix_answer_descriptions_run", "run_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    # The Episodic Memory's own identifier for this answer, and the one every API that
    # names an answer uses (compare, display, forget).  Recorded here rather than
    # letting the row's primary key stand in for it: a Fast Run contributes answers to
    # the session but writes no rows, so a row-derived identifier would collide with a
    # Fast answer's and resolve a comparison to the wrong pair.  One id space, owned by
    # the memory, of which this column is a record.
    answer_id = Column(Integer, nullable=True)
    run_id = Column(Integer, nullable=True)  # Which run produced this
    problem = Column(JSONB, nullable=False)  # [initial, modified, target, answer]
    top_rule_description = Column(Text, default="")
    bottom_rule_description = Column(Text, default="")
    top_rule_quality = Column(Float, default=0)
    bottom_rule_quality = Column(Float, default=0)
    quality = Column(Float, default=0)
    temperature = Column(Float, default=0)
    themes = Column(JSONB, default=dict)
    unjustified_slippages = Column(JSONB, default=list)
    # §4.7.1 keeps the top, bottom and unjustified theme-patterns separately from the
    # vertical one, and §4.7.3's comparison reads the rules' abstractness and the
    # answer's activation.  Without these columns a restart silently zeroed them, which
    # switched off ``is_coherent``, two of the five distance components, the
    # snag-justified distinction and two of the preference criteria.
    top_themes = Column(JSONB, default=dict)
    bottom_themes = Column(JSONB, default=dict)
    unjustified_themes = Column(JSONB, default=dict)
    top_rule_abstractness = Column(Float, default=0)
    bottom_rule_abstractness = Column(Float, default=0)
    theme_abstractness = Column(Float, default=0)
    activation = Column(Float, default=0)
    # The structural clause keys ``answer_present`` compares (``memory.ss:117``).
    top_rule_signature = Column(JSONB, nullable=True)
    bottom_rule_signature = Column(JSONB, nullable=True)
    created_at = Column(DateTime, default=_utcnow)


class SnagDescriptionRow(Base):
    """Persisted snag description (cross-run episodic memory)."""

    __tablename__ = "snag_descriptions"
    __table_args__ = (
        Index("ix_snag_descriptions_run", "run_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    # The Episodic Memory's own identifier for this snag, recorded the way
    # ``answer_descriptions.answer_id`` records an answer's.  One id space, owned by the
    # memory: a Fast Run contributes snags to the session and writes no rows, so the
    # memory's counter is the only identifier that covers every snag, and every
    # projection of a snag — live object or row — reports that one.
    snag_id = Column(Integer, nullable=True)
    run_id = Column(Integer, nullable=True)
    problem = Column(JSONB, nullable=False)  # [initial, modified, target]
    codelet_count = Column(Integer, default=0)
    temperature = Column(Float, default=0)
    theme_pattern = Column(JSONB, default=dict)
    description = Column(Text, default="")
    # The structural clause keys ``snag_present`` and ``get_equivalent_snag`` compare
    # (``memory.ss:289-291, 336-340``).  Without them a rehydrated snag could only be
    # matched on its English prose, which is what the structural comparison replaced.
    rule_signature = Column(JSONB, nullable=True)
    translated_rule_signature = Column(JSONB, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
