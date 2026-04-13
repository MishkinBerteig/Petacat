"""FastAPI application entry point."""

from __future__ import annotations

import logging
import os
import signal
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from server.config import SEED_DATA_DIR
from server.engine.metadata import MetadataProvider

logger = logging.getLogger("petacat")


HELP_LOCALE = os.environ.get("HELP_LOCALE", "en")


def _help_topics_filename() -> str:
    """Return the help topics JSON filename for the configured locale.

    Prefers `help_topics.{locale}.json`, falls back to legacy `help_topics.json`.
    """
    localized = f"help_topics.{HELP_LOCALE}.json"
    if os.path.exists(os.path.join(SEED_DATA_DIR, localized)):
        return localized
    return "help_topics.json"


async def _sync_help_topics(session) -> None:
    """Upsert all help topics from the locale JSON into the `help_topics` table.

    Unlike the bulk seeding, this is idempotent — it runs on every startup and
    keeps the DB in sync with the JSON source of truth. Existing rows are
    updated by `topic_key`; new rows are inserted.
    """
    import json
    from sqlalchemy import select
    from server.models.metadata import HelpTopic

    help_file = os.path.join(SEED_DATA_DIR, _help_topics_filename())
    if not os.path.exists(help_file):
        logger.warning("Help topics file not found: %s", help_file)
        return

    with open(help_file) as f:
        topics = json.load(f)

    # Load existing rows by key
    result = await session.execute(select(HelpTopic))
    existing = {t.topic_key: t for t in result.scalars().all()}
    seen_keys: set[str] = set()

    for t in topics:
        key = t["topic_key"]
        seen_keys.add(key)
        if key in existing:
            row = existing[key]
            row.topic_type = t["topic_type"]
            row.title = t["title"]
            row.short_desc = t.get("short_desc", "")
            row.full_desc = t.get("full_desc", "")
            row.metadata_json = t.get("metadata", {})
        else:
            session.add(HelpTopic(
                topic_type=t["topic_type"],
                topic_key=key,
                title=t["title"],
                short_desc=t.get("short_desc", ""),
                full_desc=t.get("full_desc", ""),
                metadata_json=t.get("metadata", {}),
            ))

    await session.commit()
    logger.info(
        "Help topics synced (locale=%s): %d in file, %d pre-existing",
        HELP_LOCALE, len(topics), len(existing),
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

        # Check if bulk metadata is already seeded (slipnet nodes, codelets, etc.)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            from server.models.metadata import SlipnetNodeDef
            result = await session.execute(select(SlipnetNodeDef).limit(1))
            bulk_seeded = result.scalar_one_or_none() is not None

        if bulk_seeded:
            # Bulk metadata is already in place — only sync help topics
            async with factory() as session:
                await _sync_help_topics(session)
            await engine.dispose()
            return

        # Seed from JSON files (help topics handled separately by _sync_help_topics)
        from server.models.metadata import (
            BridgeOrientationDef, BridgeTypeDef, ClauseTypeDef, CodeletFamilyDef,
            CodeletPhaseDef, CodeletTypeDef, CommentaryTemplate,
            DemoModeDef, DemoProblem as DemoProblemRow, EngineParam,
            EventTypeDef, FormulaCoefficient, LinkTypeDef,
            ParamValueTypeDef, PostingDirectionDef, ProposalLevelDef,
            RuleTypeDef, RunStatusDef, SlipnetLayoutPos, SlipnetLinkDef,
            SlipnetNodeDef, ThemeDimensionDef, ThemeTypeDef, UrgencyLevel,
        )

        def _load(fn):
            with open(os.path.join(SEED_DATA_DIR, fn)) as f:
                return json.load(f)

        async with factory() as session:
            # Seed enum lookup tables first (required by FK constraints)
            _enum_models = {
                "run_statuses": RunStatusDef, "event_types": EventTypeDef,
                "bridge_types": BridgeTypeDef, "bridge_orientations": BridgeOrientationDef,
                "clause_types": ClauseTypeDef, "rule_types": RuleTypeDef,
                "theme_types": ThemeTypeDef, "proposal_levels": ProposalLevelDef,
                "link_types": LinkTypeDef, "codelet_families": CodeletFamilyDef,
                "codelet_phases": CodeletPhaseDef, "posting_directions": PostingDirectionDef,
                "param_value_types": ParamValueTypeDef, "demo_modes": DemoModeDef,
            }
            enums_data = _load("enums.json")
            for table_name, model_cls in _enum_models.items():
                for row in enums_data.get(table_name, []):
                    session.add(model_cls(
                        name=row["name"], display_label=row["display_label"],
                        sort_order=row["sort_order"], description=row.get("description", ""),
                    ))
            await session.flush()

            for n in _load("slipnet_nodes.json"):
                session.add(SlipnetNodeDef(name=n["name"], short_name=n["short_name"],
                                            conceptual_depth=n["conceptual_depth"],
                                            description=n.get("description", "")))
            for lk in _load("slipnet_links.json"):
                session.add(SlipnetLinkDef(
                    from_node=lk["from_node"], to_node=lk["to_node"],
                    link_type=lk["link_type"], label_node=lk.get("label_node"),
                    link_length=lk.get("link_length"),
                    fixed_length=lk.get("link_length") is not None if "fixed_length" not in lk else lk["fixed_length"],
                ))
            for c in _load("codelet_types.json"):
                session.add(CodeletTypeDef(
                    name=c["name"], family=c["family"], phase=c["phase"],
                    default_urgency=c.get("default_urgency"),
                    description=c.get("description", ""),
                    source_file=c.get("source_file", ""),
                    source_line=c.get("source_line", 0),
                    execute_body=c.get("execute_body", ""),
                ))
            params = _load("engine_params.json")
            for k, v in params.items():
                if isinstance(v, (list, dict)):
                    session.add(EngineParam(name=k, value=json.dumps(v), value_type="json"))
                elif isinstance(v, bool):
                    session.add(EngineParam(name=k, value=str(v).lower(), value_type="bool"))
                elif isinstance(v, int):
                    session.add(EngineParam(name=k, value=str(v), value_type="int"))
                elif isinstance(v, float):
                    session.add(EngineParam(name=k, value=str(v), value_type="float"))
                else:
                    session.add(EngineParam(name=k, value=str(v), value_type="string"))
            for k, v in _load("urgency_levels.json").items():
                session.add(UrgencyLevel(name=k, value=v))
            for k, v in _load("formula_coefficients.json").items():
                session.add(FormulaCoefficient(name=k, value=v))
            for d in _load("demo_problems.json"):
                session.add(DemoProblemRow(
                    name=d["name"], section=d.get("section", ""),
                    initial=d["initial"], modified=d["modified"], target=d["target"],
                    answer=d.get("answer"), seed=d["seed"], mode=d["mode"],
                    description=d.get("description", ""),
                ))
            themes = _load("theme_dimensions.json")
            for td in themes.get("dimensions", []):
                session.add(ThemeDimensionDef(
                    slipnet_node=td["slipnet_node"],
                    valid_relations=td["valid_relations"],
                ))
            layout = _load("slipnet_layout.json")
            for name, pos in layout.get("node_positions", {}).items():
                session.add(SlipnetLayoutPos(node_name=name, grid_row=pos[0], grid_col=pos[1]))
            commentary = _load("commentary_templates.json")
            session.add(CommentaryTemplate(template_key="all", template_data=commentary))

            await session.commit()
            logger.info("Database tables created and seeded")

            # Sync help topics from the locale JSON (idempotent upsert)
            await _sync_help_topics(session)

        await engine.dispose()
    except Exception as e:
        logger.warning("DB setup skipped (may not be available): %s", e)


async def _regenerate_derived_help_docs() -> None:
    """Regenerate HELP.md and helpTopics.ts from the locale JSON.

    This runs on every backend startup so that the derived artifacts stay in
    sync with `seed_data/help_topics.{locale}.json` without requiring a manual
    invocation of `scripts/generate_help_docs.py`. It is idempotent -- if the
    generated output already matches what's on disk, no files are written.

    Fails silently (with a warning log) in environments where the client
    source tree is not writable (e.g. a read-only production filesystem).
    """
    try:
        from server.services.help_docs import regenerate_all
        result = regenerate_all(HELP_LOCALE)
        if result.help_md_changed or result.ts_constants_changed:
            logger.info(
                "Help docs regenerated (locale=%s): HELP.md=%s, helpTopics.ts=%s",
                result.locale,
                "updated" if result.help_md_changed else "unchanged",
                "updated" if result.ts_constants_changed else "unchanged",
            )
        else:
            logger.debug(
                "Help docs already in sync (locale=%s, %d topics)",
                result.locale, result.topics_loaded,
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

# CORS for frontend dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5175", "http://localhost:5173"],
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

app.include_router(runs_router)
app.include_router(controls_router)
app.include_router(memory_router)
app.include_router(admin_router)
app.include_router(docs_router)
app.include_router(ws_router)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


# Serve static frontend files in production
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.isdir(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
