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
The store is global-only; a later package extends it to ``provider(configuration_id,
revision)``.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.engine.metadata import MetadataProvider
from server.models.journal import GLOBAL_CONFIGURATION_ID, Configuration

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


class ConfigurationStore:
    """Holds the global configuration's provider and the revision it was built at."""

    def __init__(self, provider: MetadataProvider, revision: int = 0) -> None:
        self._provider = provider
        self._revision = revision
        self._lock = asyncio.Lock()

    def current(self) -> MetadataProvider:
        """What a run created now must use.  Synchronous: it only returns the held provider."""
        return self._provider

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
