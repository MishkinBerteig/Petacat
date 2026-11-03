"""The ``ConfigurationStore``: the one place that holds the global configuration's provider.

Metacat Mode's configuration is the database's global configuration (configuration 1).  The
engine reads it through a ``MetadataProvider``, which is built once from the database and
reused.  This store holds that provider, so there is one answer to "what must a run created
now use?": :meth:`ConfigurationStore.current`.

How an edit reaches the next run
================================
Every change to the global configuration commits through ``journal.write_immediate``.  After
a successful commit the journal layer calls the post-commit hook this module registers
(:func:`set_configuration_store` installs :meth:`ConfigurationStore.refresh` as the hook), so
the store is reloaded from the database before the write returns.  There is no
mark-stale middleware and no reload route.

A service reads ``store.current()`` **once**, when it creates or dispatches a run, and the run
holds that provider for life.  So "the next run" is exact: a run created before an edit keeps
the configuration (and ``config_hash``) it was created under; the next run uses the new one.

Reading any configuration: ``provider(session, configuration_id, revision, episode_version)``
===============================================================================================
:meth:`ConfigurationStore.provider` answers for any configuration, global or a Training Mode
Session's, now or at an earlier revision or Training episode version, with a
``ConfigurationView`` (the ``MetadataProvider``, its ``config_hash`` and where it came from).

* The global configuration now is ``current()`` (no database read).
* A session's configuration now is its stored current state.  An earlier revision is
  ``configurations.config_at``: the immutable base snapshot plus the journal's resolved ops.
* A **live** session (held in memory by the session service, S3) registers a *live source* with
  :func:`set_live_source`.  Asked for its configuration now, the store then returns the live
  document with ``source = "live"``, ``saved_through`` (the last Stop's revision) and
  ``unsaved`` (batches held in memory).  An earlier revision is always read from the database.
  The Training Mode Session service registers the source when it starts and removes it when it
  stops; with none registered every session is read from the database.

The live session's own batches: :func:`live_apply`
==================================================
A live session writes nothing to the database until it is Stopped, so a batch for its
configuration must not take the stored path.  :func:`set_live_source` registers, with the source,
the function that applies a batch in memory (the session service's ``apply_live``);
``ChangeService.apply`` calls :func:`live_apply` first for any session configuration whose
session is live, and so every writer of batches (the external route, the Admin editors, a
learner) reaches a live session by the one door.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.engine.metadata import MetadataProvider
from server.models.journal import GLOBAL_CONFIGURATION_ID, KIND_GLOBAL, Configuration

logger = logging.getLogger("petacat")


async def read_revision(session: AsyncSession) -> int:
    """The global configuration's ``revision`` (0 when its row does not exist yet)."""
    row = (
        await session.execute(
            select(Configuration.__table__.c.revision).where(
                Configuration.__table__.c.id == GLOBAL_CONFIGURATION_ID
            )
        )
    ).first()
    return int(row[0]) if row else 0


@dataclass(frozen=True)
class LiveState:
    """A live Training Mode Session's configuration, as its holder in memory reports it."""

    #: ``starting``, ``running``, ``paused`` or ``stopping``.
    state: str
    #: The in-memory ``ConfigDocument``.
    document: Any
    #: The in-memory revision.
    revision: int
    #: The revision of the last Stop write (what the database shows).
    saved_through: int
    #: Batches held in memory, not yet stored.
    unsaved: int
    saved_at: datetime | None = None
    #: The ``journal.PendingEntry`` list held in memory (revision order): the live part of the
    #: session's History, which is the stored entries plus these.
    pending: list = field(default_factory=list)


#: ``source(session_id) -> LiveState | None``.
LiveSource = Callable[[int], "LiveState | None"]
#: ``apply(session_id, batch) -> report``: applies a batch to a live session in memory.
LiveApply = Callable[[int, Any], Awaitable[dict]]

_LIVE_SOURCE: LiveSource | None = None
_LIVE_APPLY: LiveApply | None = None


def set_live_source(source: LiveSource | None, apply: LiveApply | None = None) -> None:
    """Register (or, with ``None``, remove) the source of live sessions' configurations (S3),
    and the function that applies a batch to a live session in memory."""
    global _LIVE_SOURCE, _LIVE_APPLY
    _LIVE_SOURCE = source
    _LIVE_APPLY = apply if source is not None else None


async def live_apply(session_id: int, batch: Any) -> dict:
    """Apply *batch* to live session ``session_id``'s configuration, in memory (the report says
    ``persisted: false``).  Raises ``RuntimeError`` when no live source is registered."""
    if _LIVE_APPLY is None:
        raise RuntimeError("no live session source is registered")
    return await _LIVE_APPLY(session_id, batch)


def live_state(session_id: int | None) -> LiveState | None:
    """The live state of Training Mode Session ``session_id``, or ``None`` (stopped, or no
    live source registered)."""
    if _LIVE_SOURCE is None or session_id is None:
        return None
    return _LIVE_SOURCE(session_id)


@dataclass(frozen=True)
class ConfigurationView:
    """What :meth:`ConfigurationStore.provider` returns."""

    configuration_id: int
    provider: MetadataProvider
    config_hash: str
    revision: int
    #: ``stored`` (the database) or ``live`` (a session held in memory).
    source: str = "stored"
    saved_through: int | None = None
    unsaved: int = 0
    document: Any = None


class ConfigurationStore:
    """Holds the global configuration's provider and the revision it was built at."""

    def __init__(self, provider: MetadataProvider, revision: int = 0) -> None:
        self._provider = provider
        self._revision = revision
        self._lock = asyncio.Lock()

    def current(self) -> MetadataProvider:
        """What a run created now must use.  Synchronous: it only returns the held provider."""
        return self._provider

    async def provider(
        self,
        session: AsyncSession,
        configuration_id: int = GLOBAL_CONFIGURATION_ID,
        revision: int | None = None,
        episode_version: int | None = None,
    ) -> ConfigurationView:
        """The provider and ``config_hash`` of any configuration (see the module docstring).

        ``revision`` and ``episode_version`` select an earlier state (``revision`` wins);
        with neither, it is the configuration now.  ``session`` is the database session to
        read through (the store holds none).
        """
        from server.engine.hashing import config_hash
        from server.services import config_document as cd
        from server.services import configurations

        row = await configurations.get_row(session, configuration_id)
        now = revision is None and episode_version is None
        if row["kind"] == KIND_GLOBAL:
            if now or revision == self._revision:
                provider = self._provider
                return ConfigurationView(
                    configuration_id, provider, config_hash(provider), self._revision,
                    document=None,
                )
        elif now:
            live = live_state(row["session_id"])
            if live is not None and live.document is not None:
                return ConfigurationView(
                    configuration_id, cd.provider(live.document), cd.config_hash(live.document),
                    live.revision, source="live", saved_through=live.saved_through,
                    unsaved=live.unsaved, document=live.document,
                )
        document = await configurations.config_at(
            session, configuration_id, revision, episode_version
        )
        return ConfigurationView(
            configuration_id, cd.provider(document), cd.config_hash(document), document.version,
            document=document,
        )

    @property
    def revision(self) -> int:
        """``configurations.revision`` of the global configuration, as of the last refresh."""
        return self._revision

    async def refresh(self, session: AsyncSession) -> None:
        """Reload the provider from the database (``load_metadata_from_db``).

        Reads through a probe session that shares ``session``'s connection, so it sees what
        the caller just committed and never an object cached in the caller's identity map.
        If the database holds a configuration the provider cannot be built from, this
        raises and the previous provider stays in place.
        """
        from server.services.metadata_service import load_metadata_from_db

        async with self._lock:
            connection = await session.connection()
            async with AsyncSession(bind=connection, expire_on_commit=False) as probe:
                revision = await read_revision(probe)
                provider = await load_metadata_from_db(probe)
            self._provider, self._revision = provider, revision


_STORE: ConfigurationStore | None = None


def get_configuration_store() -> ConfigurationStore:
    """The process-wide store; ``RuntimeError`` before start-up has built one."""
    if _STORE is None:
        raise RuntimeError("the configuration store is not initialised")
    return _STORE


def set_configuration_store(store: ConfigurationStore | None) -> None:
    """Install *store* as the process-wide store (a test can replace it; ``None`` clears it).

    Also registers its ``refresh`` as the journal's post-commit hook for global changes.
    """
    from server.services import journal

    global _STORE
    _STORE = store
    journal.set_global_commit_hook(store.refresh if store is not None else None)
