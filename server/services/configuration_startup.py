"""Start-up: the database is the configuration source of truth.

The Metacat Standard Configuration (``seed_data/*.json``) is loaded into the database
**only when the database is empty** (a fresh install, or deliberately for testing).  There
is no "re-seed when the files change", no delete-and-reseed, no upgrade of an existing
database: a database that predates a schema change is cleared by a developer, and the next
start-up loads it afresh.  Clearing a database is a development action, never an
application feature.

Every start-up:

1. connects (an unreachable database refuses to start);
2. takes an advisory lock, so two simultaneous start-ups end with one first load;
3. ``create_all``;
4. classifies the database from ``configuration_state`` and the configuration tables:

   ====================  =======================================================
   EMPTY                 no ``configuration_state`` row and every configuration
                         table has zero rows: first load, one transaction
   COMPLETE              a ``ready`` row and populated tables: use as it is
   anything else         refuse to start, naming the remedy
   ====================  =======================================================

5. syncs the help topics (as before);
6. builds the engine's provider from the database (the only source the engine sees);
7. separately reads the seed files once into the read-only Metacat Standard Configuration
   reference (held in this module; later used for Reset, the "differs from the standard"
   badge and creating sessions).  Nothing at run time writes the seed files.

Any failure raises :class:`ConfigurationStartupError`, which the application lets escape
from ``lifespan`` so the process does not serve.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

logger = logging.getLogger("petacat")

#: Advisory-lock key serialising start-ups against one database.
STARTUP_LOCK_KEY = 0x7E7AC002

#: The remedy named in every refusal that a developer can fix by clearing the database.
CLEAR_REMEDY = (
    "Petacat does not upgrade or repair an existing database. If this is a development "
    "database, clear it (for example `dropdb`/`createdb`, or `docker compose down -v`) "
    "and start again: start-up loads the Metacat Standard Configuration into an empty "
    "database."
)


class ConfigurationStartupError(RuntimeError):
    """The application must not start serving; the message names the cause and remedy."""


# ──────────────────────────────────────────────────────────────────
# The read-only Metacat Standard Configuration reference
# ──────────────────────────────────────────────────────────────────

_standard_reference: Any = None


def read_standard_reference(seed_dir: str) -> Any:
    """Read the seed files once into a ``MetadataProvider`` (never handed to the engine)."""
    from server.engine.metadata import MetadataProvider

    try:
        return MetadataProvider.from_seed_data(seed_dir)
    except Exception as exc:
        raise ConfigurationStartupError(
            f"The Metacat Standard Configuration files in {seed_dir} cannot be read "
            f"({type(exc).__name__}: {exc}). Restore them from the repository "
            "(`git checkout -- seed_data`) and start again."
        ) from exc


def set_standard_reference(reference: Any) -> None:
    global _standard_reference
    _standard_reference = reference


def standard_reference() -> Any:
    """The start-up Metacat Standard Configuration reference (read only)."""
    if _standard_reference is None:
        raise RuntimeError("the Metacat Standard Configuration reference is not loaded yet")
    return _standard_reference


# ──────────────────────────────────────────────────────────────────
# Classification and first load
# ──────────────────────────────────────────────────────────────────

EMPTY = "empty"
COMPLETE = "complete"


async def classify_database(session: AsyncSession) -> str:
    """``EMPTY`` or ``COMPLETE``; raises :class:`ConfigurationStartupError` otherwise."""
    from server.models import metadata as models
    from server.models.configuration_state import ConfigurationState, LOAD_STATE_READY
    from server.services.seeding import _derived_names

    populated: list[str] = []
    for cls in _configuration_classes(models, _derived_names()):
        count = (await session.execute(select(func.count()).select_from(cls))).scalar_one()
        if count:
            populated.append(cls.__tablename__)
    empty = not populated

    state = (await session.execute(select(ConfigurationState))).scalars().all()

    if not state and empty:
        return EMPTY
    if not state:
        raise ConfigurationStartupError(
            "The database holds configuration rows (%d tables populated) but no "
            "configuration_state row, so it was not loaded by this version. %s"
            % (len(populated), CLEAR_REMEDY)
        )
    if len(state) != 1 or state[0].load_state != LOAD_STATE_READY:
        found = [(r.id, r.load_state) for r in state]
        raise ConfigurationStartupError(
            f"configuration_state is not a single 'ready' row (found {found}): a load was "
            f"left unfinished or the table was edited. {CLEAR_REMEDY}"
        )
    if empty:
        raise ConfigurationStartupError(
            "configuration_state says the Metacat Standard Configuration was loaded, but "
            f"every configuration table is empty. {CLEAR_REMEDY}"
        )
    return COMPLETE


def _configuration_classes(models: Any, names: set[str]) -> list[Any]:
    import inspect

    return sorted(
        (
            cls
            for _, cls in inspect.getmembers(models, inspect.isclass)
            if getattr(cls, "__module__", "") == models.__name__
            and getattr(cls, "__tablename__", None) in names
        ),
        key=lambda c: c.__tablename__,
    )


async def first_load(session: AsyncSession, seed_dir: str) -> None:
    """Load the Metacat Standard Configuration into the empty database, uncommitted.

    The caller commits: the configuration rows and the ``configuration_state`` row go in
    one transaction.
    """
    from server.models.configuration_state import (
        ConfigurationState,
        LOAD_STATE_READY,
        ORIGIN_METACAT_STANDARD,
    )
    from server.services.seeding import seed_metadata_from_json, standard_configuration_hash

    # C6: route this load through the journal layer, as the global journal's first entry
    # (source = standard_load), instead of writing the rows directly.
    await seed_metadata_from_json(session, seed_dir)
    session.add(
        ConfigurationState(
            id=1,
            origin=ORIGIN_METACAT_STANDARD,
            standard_hash=standard_configuration_hash(seed_dir),
            load_state=LOAD_STATE_READY,
        )
    )
    await session.flush()


# ──────────────────────────────────────────────────────────────────
# The start-up sequence
# ──────────────────────────────────────────────────────────────────


async def prepare_database(database_url: str, seed_dir: str) -> Any:
    """Steps 1-6: connect, lock, create tables, classify, load if empty, sync help, load.

    Returns the engine's ``MetadataProvider``, built from the database.
    """
    from server.models.metadata import Base
    import server.models.run  # noqa: F401 — registers the runtime tables
    import server.models.training  # noqa: F401 — and configuration_state
    from server.services.metadata_service import load_metadata_from_db
    from server.services.seeding import sync_help_topics

    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        try:
            lock_conn = await engine.connect()
        except Exception as exc:
            raise ConfigurationStartupError(
                f"The database is unreachable ({type(exc).__name__}: {exc}). Start "
                "Postgres (`scripts/dev.sh db`) and check DATABASE_URL."
            ) from exc
        try:
            await lock_conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": STARTUP_LOCK_KEY})
            try:
                return await _prepare_locked(engine, seed_dir, Base, load_metadata_from_db,
                                             sync_help_topics)
            finally:
                await lock_conn.execute(
                    text("SELECT pg_advisory_unlock(:k)"), {"k": STARTUP_LOCK_KEY}
                )
        finally:
            await lock_conn.close()
    finally:
        await engine.dispose()


async def _prepare_locked(engine, seed_dir, Base, load_metadata_from_db, sync_help_topics):
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with factory() as session:
            try:
                kind = await classify_database(session)
            except ConfigurationStartupError:
                raise
            except Exception as exc:
                raise ConfigurationStartupError(
                    f"The database cannot be read ({type(exc).__name__}: {exc}). "
                    f"{CLEAR_REMEDY}"
                ) from exc

        if kind == EMPTY:
            logger.info("Empty database: loading the Metacat Standard Configuration")
            async with factory() as session:
                await first_load(session, seed_dir)
                await session.commit()
            logger.info("Database tables created and the Metacat Standard Configuration loaded")

        async with factory() as session:
            await sync_help_topics(session, seed_dir)

        async with factory() as session:
            return await load_metadata_from_db(session)
    except ConfigurationStartupError:
        raise
    except Exception as exc:
        raise ConfigurationStartupError(
            f"Start-up could not load the configuration ({type(exc).__name__}: {exc}). "
            f"{CLEAR_REMEDY}"
        ) from exc


async def startup_configuration(database_url: str, seed_dir: str) -> Any:
    """Prepare the database, then read the reference; returns the engine's provider."""
    meta = await prepare_database(database_url, seed_dir)
    set_standard_reference(read_standard_reference(seed_dir))
    return meta
