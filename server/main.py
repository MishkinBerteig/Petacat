"""FastAPI application entry point."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from server.config import SEED_DATA_DIR
from server.db import get_session
from server.services.configuration_startup import startup_configuration

logger = logging.getLogger("petacat")

# uvicorn configures only its own loggers, so Petacat's INFO messages (the start-up
# configuration line, "Petacat started", shutdown) would otherwise never be shown.
# Attach one console handler to the "petacat" logger, laid out like uvicorn's lines.
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s:     %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


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
    # Regenerate derived help artifacts (HELP.md + TypeScript constants)
    await _regenerate_derived_help_docs()

    # The database is the configuration source of truth.  Start-up connects (refusing to
    # start if it cannot), loads the Metacat Standard Configuration only into an EMPTY
    # database, syncs the help topics, builds the engine's provider from the database, and
    # reads the seed files once into the read-only reference
    # (``configuration_startup.standard_reference()``).  Any failure raises and the
    # process does not serve.
    from server.config import DATABASE_URL

    try:
        meta = await startup_configuration(DATABASE_URL, SEED_DATA_DIR)
    except Exception:
        logger.critical("Petacat cannot start: the configuration could not be prepared", exc_info=True)
        raise

    # Create RunService and wire it into the routers
    from server.services.run_service import RunService
    from server.api import runs as runs_module

    # The configuration store holds the global configuration's provider.  Every Admin edit,
    # reset and restore commits through the journal layer, which refreshes the store after
    # the commit, so the next run in either mode starts under the edit.
    from server.db import async_session_factory as _factory
    from server.services.configuration_store import (
        ConfigurationStore,
        read_revision,
        set_configuration_store,
    )

    async with _factory() as _session:
        store = ConfigurationStore(meta, await read_revision(_session))
    set_configuration_store(store)

    run_service = RunService(store)
    runs_module._run_service = run_service

    # The review surfaces read the record rather than a live runner, so they get their
    # own service with the metadata and nothing else (WP3.9).
    from server.services.review_service import ReviewService
    from server.api import review as review_module

    review_module._review_service = ReviewService(store)

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

    # Training Mode Sessions: the scheduler that feeds every core from the problems of all active Training Mode Sessions.
    try:
        from server.services.training_mode_session_service import start_default_service

        await start_default_service(store.current)
    except Exception as e:
        logger.warning("Training Mode Session service not started (database may not be available): %s", e)

    logger.info("Petacat started — %d codelet types loaded", len(meta.codelet_specs))
    yield

    from server.services.training_mode_session_service import stop_default_service

    await stop_default_service()

    # The swarm's process pool must not outlive this process (it is a detachable plugin).
    try:
        from server.parallel.swarm import shutdown_default
    except ImportError:
        pass
    else:
        await asyncio.to_thread(shutdown_default)

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
from server.api.configurations import router as configurations_router
from server.api.database import router as database_router
from server.api.docs import router as docs_router
from server.api.ws import router as ws_router
from server.api.review import router as review_router
from server.api.system import router as system_router
from server.api.swarm import router as swarm_router
from server.api.training_mode_sessions import router as training_mode_sessions_router



@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    """FastAPI's list-of-errors body, except under /api/training-mode/sessions, whose contract is a
    ``{"detail": string}`` for every error."""
    if request.url.path.startswith("/api/training-mode/sessions"):
        parts = []
        for err in exc.errors():
            where = ".".join(str(x) for x in err.get("loc", ()) if x != "body")
            parts.append(f"{where}: {err.get('msg')}" if where else str(err.get("msg")))
        return JSONResponse({"detail": "; ".join(parts[:5])}, status_code=422)
    return await request_validation_exception_handler(request, exc)


app.include_router(runs_router)
app.include_router(controls_router)
app.include_router(memory_router)
app.include_router(admin_router)
app.include_router(configurations_router)
app.include_router(database_router)
app.include_router(docs_router)
app.include_router(ws_router)
app.include_router(review_router)
app.include_router(system_router)
app.include_router(swarm_router)
app.include_router(training_mode_sessions_router)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


# Serve static frontend files in production
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.isdir(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
