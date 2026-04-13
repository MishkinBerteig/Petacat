"""SQLAlchemy ORM models for run state."""

from __future__ import annotations

from datetime import datetime, timezone


def _utcnow() -> datetime:
    """Naive UTC datetime — avoids the deprecated datetime.utcnow()."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, Integer, String, Text, Float, Boolean
from sqlalchemy.dialects.postgresql import JSONB

from server.models.metadata import Base


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
    created_at = Column(DateTime, default=_utcnow)


class SnagDescriptionRow(Base):
    """Persisted snag description (cross-run episodic memory)."""

    __tablename__ = "snag_descriptions"
    __table_args__ = (
        Index("ix_snag_descriptions_run", "run_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Integer, nullable=True)
    problem = Column(JSONB, nullable=False)  # [initial, modified, target]
    codelet_count = Column(Integer, default=0)
    temperature = Column(Float, default=0)
    theme_pattern = Column(JSONB, default=dict)
    description = Column(Text, default="")
    created_at = Column(DateTime, default=_utcnow)
