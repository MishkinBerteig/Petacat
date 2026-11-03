"""The journal tables (configuration plan 3.11) and the ``configurations`` row they hang from.

* ``configurations``: the minimum of the configuration entity (3.10.1) that the journal
  needs: ``id``, ``kind``, ``revision`` and ``config_hash``.  The global configuration is
  always id 1.  C8 adds the rest of the entity (name, note, base snapshot, ``frozen``,
  lineage) to this table.
* ``configuration_journal``: one append-only record per configuration.  An entry holds the
  ops as proposed, the resolved ops with their cascades, the before-images and provenance.
  Only ``server/services/journal.py`` writes either table, and it has no update or delete
  of an entry; the ORM refuses one here as well.

The JSON columns are ``JSON``, not ``JSONB``: JSONB reorders object keys, and the key order
of a stored value (``count_values``, the commentary templates) is read back.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, Text,
    UniqueConstraint, event, text,
)
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Session

from server.models.metadata import Base

#: The global configuration (Metacat Mode) is always configuration 1.
GLOBAL_CONFIGURATION_ID = 1

KIND_GLOBAL = "global"
KIND_SESSION = "session"

#: ``source`` of a journal entry (3.12.0).  Provenance only.
SOURCES = (
    "admin", "external", "learner", "standard_load", "reset", "restore", "import", "creation",
)
#: Sources that Training Mode owns; the global configuration (Metacat Mode) refuses them (M2).
TRAINING_MODE_SOURCES = ("learner", "external")
#: The sources whose entry is the baseline a provenance query measures against: the
#: Metacat Standard Configuration's first load, and a configuration's creation batch.
BASELINE_SOURCES = ("standard_load", "creation")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Configuration(Base):
    __tablename__ = "configurations"
    __table_args__ = (
        CheckConstraint("kind IN ('global','session')", name="ck_configurations_kind"),
        Index("uq_configurations_one_global", "kind", unique=True,
              postgresql_where=text("kind = 'global'")),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    kind = Column(String(8), nullable=False)
    #: Counts the committed batches that changed this configuration; the compare-and-set token.
    revision = Column(Integer, nullable=False, default=0)
    #: The effective hash at ``revision`` (``server.engine.hashing.config_hash``); ``NULL``
    #: when the configuration at that revision could not be loaded.
    config_hash = Column(String(64), nullable=True)


class JournalEntry(Base):
    __tablename__ = "configuration_journal"
    __table_args__ = (
        UniqueConstraint("configuration_id", "revision", name="uq_configuration_journal_revision"),
        CheckConstraint(
            "source IN ('admin','external','learner','standard_load','reset','restore',"
            "'import','creation')",
            name="ck_configuration_journal_source",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    configuration_id = Column(
        Integer, ForeignKey("configurations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: The configuration's revision after this entry.  Queries order by
    #: ``(configuration_id, revision)``, never by ``id`` or ``recorded_at``.
    revision = Column(Integer, nullable=False)
    #: Entries of one edit-all, or one undone batch, share a group.
    group_id = Column(String(64), nullable=True, index=True)
    source = Column(String(16), nullable=False)
    actor = Column(String(80), nullable=False)
    #: The finer route (``admin_editor``, ``admin_database``, ``admin_undo``, ...).
    channel = Column(String(40), nullable=False, default="")
    note = Column(Text, nullable=False, default="")
    #: The run that caused the change (a learner's), if any.
    causing_run_id = Column(Integer, nullable=True)
    #: A session's Training episode version.
    episode_version = Column(Integer, nullable=True)
    #: What was asked for: the batch's ops as submitted (a description of the files, for a
    #: ``standard_load``).
    proposed = Column(JSON, nullable=False)
    #: What changed: the resolved ops, absolute values, cascades included, in application
    #: order (``server/services/config_registry.py``).
    resolved = Column(JSON, nullable=False)
    #: ``before[i]`` is the old row of ``resolved[i]`` (an update or a delete), else ``null``.
    before = Column(JSON, nullable=False)
    config_hash = Column(String(64), nullable=True)
    #: When the change happened (in memory, for a deferred entry) and when it was stored.
    occurred_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    recorded_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class JournalImmutable(RuntimeError):
    """Raised on any attempt to update or delete a journal entry: the journal is append-only."""


@event.listens_for(JournalEntry, "before_update")
def _refuse_update(mapper, connection, target):  # pragma: no cover - exercised by tests
    raise JournalImmutable("a journal entry is append-only; it is never updated")


@event.listens_for(JournalEntry, "before_delete")
def _refuse_delete(mapper, connection, target):  # pragma: no cover - exercised by tests
    raise JournalImmutable("a journal entry is append-only; it is never deleted")


@event.listens_for(Session, "do_orm_execute")
def _refuse_bulk_change(state):
    """Refuse an ORM-enabled UPDATE or DELETE statement aimed at the journal."""
    if not (state.is_update or state.is_delete):
        return
    table = getattr(state.statement, "table", None)
    if getattr(table, "name", None) == JournalEntry.__tablename__:
        raise JournalImmutable("a journal entry is append-only; it is never updated or deleted")


# The tables register on the shared ``Base`` when this module is imported;
# ``server/models/configuration_state.py`` imports it, as ``training_mode_session.py`` imports that.
