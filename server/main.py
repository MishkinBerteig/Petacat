"""FastAPI application entry point."""

from __future__ import annotations

import logging
import os
import signal
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from server.config import SEED_DATA_DIR
from server.engine.metadata import MetadataProvider
from server.services.seeding import (
    BULK_SEED_FILES as _BULK_SEED_FILES,
    HELP_TOPICS_FILENAME,
    NON_DERIVED_TABLES as _NON_DERIVED_TABLES,
    SEED_FINGERPRINT_PARAM as _SEED_FINGERPRINT_PARAM,
    derived_metadata_tables as _derived_metadata_tables,
    protected_enum_tables as _protected_enum_tables,
    seed_metadata_from_json,
    sync_help_topics as _sync_help_topics,
    tables_referenced_by_runtime as _tables_referenced_by_runtime,
)

logger = logging.getLogger("petacat")


def _seed_data_fingerprint() -> str:
    """A digest of the checked-in bulk seed files."""
    from server.services.seeding import seed_data_fingerprint

    return seed_data_fingerprint(SEED_DATA_DIR)


async def _stored_seed_fingerprint_safe(engine) -> str | None:
    """The fingerprint the DB was last seeded from, or ``None``.

    Uses raw SQL and swallows failures on purpose: the table may not exist yet,
    or may predate a column the ORM now expects, and either way the answer we
    want is "unknown, so re-seed".
    """
    from sqlalchemy import text

    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT value FROM engine_params WHERE name = :name"),
                {"name": _SEED_FINGERPRINT_PARAM},
            )
            row = result.first()
            return row[0] if row else None
    except Exception:
        return None


async def _reconcile_metadata_columns(engine) -> None:
    """Add any columns the models declare that the database is missing.

    ``create_all`` creates missing *tables* but never alters an existing one, so a
    seed file that grows a new field — ``slipnet_nodes.descriptor_predicate`` —
    left the old column set in place on any pre-existing volume, and every query
    naming the new column failed.  Dropping the tables instead is not an option:
    runtime data holds foreign keys into several of them.

    The models share one ``Base``, so this covers the runtime tables too — which
    matters for a column like ``runs.spreading_threshold`` that existing rows must
    acquire a sensible value for rather than NULL.
    """
    from sqlalchemy import text
    from server.models.metadata import Base

    async with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            result = await conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = :table"
                ),
                {"table": table.name},
            )
            present = {row[0] for row in result}
            if not present:
                continue  # table does not exist yet; create_all will make it
            for column in table.columns:
                if column.name in present:
                    continue
                # Added nullable regardless of the model's constraint: the
                # derived tables are re-seeded immediately afterwards, and a NOT
                # NULL column cannot be added to a populated table without a
                # default.
                type_sql = column.type.compile(dialect=conn.dialect)
                # Carry the model's server_default through, so rows that already
                # exist get the intended value instead of NULL. Without this a
                # runtime table gaining a column — where the rows are real data
                # and are not re-seeded — would read back None everywhere.
                # Interpolated defaults have to be quoted when they are strings.
                # Postgres reads an unquoted ``DEFAULT normal`` as a *column
                # reference* and rejects it — "cannot use column reference in DEFAULT
                # expression" — which went unnoticed while the only column with a
                # server_default was ``spreading_threshold``, whose ``"100"`` happens
                # to be valid unquoted. The first string-valued default (``runs.mode``)
                # broke it. Numeric literals are still emitted bare so existing
                # behaviour is unchanged.
                default_sql = ""
                if column.server_default is not None:
                    arg = getattr(column.server_default, "arg", None)
                    if arg is not None:
                        literal = str(getattr(arg, "text", arg))
                        try:
                            float(literal)
                        except ValueError:
                            literal = "'" + literal.replace("'", "''") + "'"
                        default_sql = f" DEFAULT {literal}"
                logger.info(
                    "Adding missing column %s.%s (%s%s)",
                    table.name, column.name, type_sql, default_sql,
                )
                await conn.execute(
                    text(
                        f'ALTER TABLE "{table.name}" '
                        f'ADD COLUMN "{column.name}" {type_sql}{default_sql}'
                    )
                )


async def _ensure_db_ready():
    """Create tables and seed metadata if they don't exist yet.

    Help topics are always synced on startup (idempotent upsert by topic_key),
    so JSON updates take effect after a simple restart.
    """
    import json
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from sqlalchemy.pool import NullPool
    from server.config import DATABASE_URL

    try:
        engine = create_async_engine(DATABASE_URL, poolclass=NullPool)

        from server.models.metadata import Base
        import server.models.run  # noqa — register runtime tables

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        # create_all only creates missing tables; bring existing ones up to date.
        await _reconcile_metadata_columns(engine)

        # Decide whether the bulk metadata in the DB is still current.
        #
        # Checking merely "are there any rows?" meant a database left over
        # from an earlier build kept serving stale metadata to the admin panel
        # while the engine ran the new seed files from JSON — a silent divergence
        # between what you can inspect and what is actually executing.  And
        # ``create_all`` never alters an existing table, so a seed file that grew
        # a new field (``slipnet_nodes.descriptor_predicate``) left the old column
        # set in place and every query against it failed.
        #
        # So: fingerprint the seed files, and when they differ, drop the derived
        # metadata tables and let ``create_all`` rebuild them at the current
        # schema before re-seeding.  Runtime data is never touched.
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        fingerprint = _seed_data_fingerprint()
        stored = await _stored_seed_fingerprint_safe(engine)

        if stored == fingerprint:
            async with factory() as session:
                await _sync_help_topics(session, SEED_DATA_DIR)
                await session.commit()
            await engine.dispose()
            return

        if stored is not None:
            logger.info(
                "Seed data changed (%s -> %s); re-seeding derived metadata",
                stored[:12], fingerprint[:12],
            )
        from sqlalchemy import delete as _delete

        async with factory() as session:
            for table in _derived_metadata_tables():
                await session.execute(_delete(table))
            await session.commit()

        # Seed from JSON files (help topics handled separately by _sync_help_topics)
        async with factory() as session:
            await seed_metadata_from_json(session, SEED_DATA_DIR, fingerprint=fingerprint)

            await session.commit()
            logger.info("Database tables created and seeded")

            # Sync help topics from the topics JSON (idempotent upsert)
            await _sync_help_topics(session, SEED_DATA_DIR)

        await engine.dispose()
    except Exception as e:
        logger.warning("DB setup skipped (may not be available): %s", e)


async def _regenerate_derived_help_docs() -> None:
    """Regenerate HELP.md and helpTopics.ts from the topics JSON.

    This runs on every backend startup so that the derived artifacts stay in
    sync with `seed_data/help_topics.en.json` without requiring a manual
    invocation of `scripts/generate_help_docs.py`. It is idempotent -- if the
    generated output already matches what's on disk, no files are written.

    Fails silently (with a warning log) in environments where the client
    source tree is not writable (e.g. a read-only production filesystem).
    """
    try:
        from server.services.help_docs import regenerate_all
        result = regenerate_all()
        if result.help_md_changed or result.ts_constants_changed:
            logger.info(
                "Help docs regenerated: HELP.md=%s, helpTopics.ts=%s",
                "updated" if result.help_md_changed else "unchanged",
                "updated" if result.ts_constants_changed else "unchanged",
            )
        else:
            logger.debug(
                "Help docs already in sync (%d topics)",
                result.topics_loaded,
            )
    except Exception as e:
        logger.warning("Help doc regeneration skipped: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize services at startup, clean up on shutdown."""
    # Ensure DB tables exist and are seeded (syncs help topics into the DB)
    await _ensure_db_ready()

    # Regenerate derived help artifacts (HELP.md + TypeScript constants)
    await _regenerate_derived_help_docs()

    # Load metadata from seed_data/ JSON (or DB in production)
    meta = MetadataProvider.from_seed_data(SEED_DATA_DIR)

    # Create RunService and wire it into the routers
    from server.services.run_service import RunService
    from server.api import runs as runs_module

    run_service = RunService(meta)
    runs_module._run_service = run_service

    # The review surfaces read the record rather than a live runner, so they get their
    # own service with the metadata and nothing else (WP3.9).
    from server.services.review_service import ReviewService
    from server.api import review as review_module

    review_module._review_service = ReviewService(meta)

    # Rehydrate episodic memory from DB (if DB is available)
    try:
        from server.db import async_session_factory
        async with async_session_factory() as session:
            await run_service.rehydrate_memory(session)
            from server.services.run_service import _global_memory
            logger.info(
                "Episodic memory rehydrated: %d answers, %d snags",
                len(_global_memory.answers),
                len(_global_memory.snags),
            )
    except Exception as e:
        logger.debug("Memory rehydration skipped (DB may not be available): %s", e)

    logger.info("Petacat started — %d codelet types loaded", len(meta.codelet_specs))
    yield

    # Graceful shutdown: stop any running runs
    for run_id, runner in list(run_service._runners.items()):
        if runner.status == "running":
            run_service.stop_run(run_id)
            logger.info("Stopped run #%d on shutdown", run_id)
    logger.info("Petacat shutdown complete")


app = FastAPI(
    title="Petacat",
    version="0.9.0",
    description="Python/React port of Metacat cognitive architecture for analogy-making",
    lifespan=lifespan,
)

# CORS for frontend dev server: the port `scripts/dev.sh` starts Vite on,
# plus Vite's own default for running `npm run dev` on the host.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:59595", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
from server.api.runs import router as runs_router
from server.api.controls import router as controls_router
from server.api.memory import router as memory_router
from server.api.admin import router as admin_router
from server.api.docs import router as docs_router
from server.api.ws import router as ws_router
from server.api.review import router as review_router
from server.api.system import router as system_router

_CONFIG_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@app.middleware("http")
async def adopt_configuration_edits(request: Request, call_next):
    """Carry an admin edit through to the Runs created after it.

    A write under ``/api/admin`` changes the configuration in the database. The
    ``RunService`` holds a ``MetadataProvider`` built from that configuration, and this
    marks it stale so ``create_run`` rebuilds it from the database for the next Run.

    Marking rather than reloading here keeps a Run's metadata fixed for its whole life:
    an edit made while something is running takes effect on the Run after it, and the
    reload happens once however many cells were edited.
    """
    response = await call_next(request)
    if (
        request.method in _CONFIG_WRITE_METHODS
        and request.url.path.startswith("/api/admin")
        and 200 <= response.status_code < 300
    ):
        from server.api.runs import _run_service

        if _run_service is not None:
            _run_service.mark_metadata_stale()
    return response


app.include_router(runs_router)
app.include_router(controls_router)
app.include_router(memory_router)
app.include_router(admin_router)
app.include_router(docs_router)
app.include_router(ws_router)
app.include_router(review_router)
app.include_router(system_router)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


# Serve static frontend files in production
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.isdir(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
