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

logger = logging.getLogger("petacat")




# Seed files whose contents the DB copy of the bulk metadata mirrors.  Help
# topics are excluded: they are upserted separately on every startup.
_BULK_SEED_FILES = (
    "enums.json",
    "slipnet_nodes.json",
    "slipnet_links.json",
    "slipnet_layout.json",
    "codelet_types.json",
    "engine_params.json",
    "urgency_levels.json",
    "formula_coefficients.json",
    "theme_dimensions.json",
    "demo_problems.json",
    "commentary_templates.json",
    "posting_rules.json",
)

# EngineParam row that records which seed data the DB was last loaded from.
_SEED_FINGERPRINT_PARAM = "__seed_data_fingerprint__"


def _seed_data_fingerprint() -> str:
    """A digest of the checked-in bulk seed files."""
    import hashlib

    digest = hashlib.sha256()
    for filename in _BULK_SEED_FILES:
        path = os.path.join(SEED_DATA_DIR, filename)
        digest.update(filename.encode())
        try:
            with open(path, "rb") as f:
                digest.update(f.read())
        except FileNotFoundError:
            digest.update(b"<missing>")
    return digest.hexdigest()


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


# Metadata tables that are *not* derived from the bulk seed files.
_NON_DERIVED_TABLES = frozenset({"help_topics"})


def _derived_metadata_tables() -> list:
    """Derived metadata tables, in safe deletion order (children first).

    Restricted to classes declared in ``server.models.metadata``: the runtime
    models in ``server.models.run`` share the same declarative ``Base``, so
    walking ``Base.metadata`` wholesale would have swept up ``runs``,
    ``trace_events``, ``cycle_snapshots`` and the episodic-memory tables and
    deleted a user's saved work.

    Ordering comes from SQLAlchemy's own foreign-key sort rather than a
    hand-written list — hand-listing meant playing whack-a-mole with dependencies
    (``posting_rules`` → ``posting_directions``, …) and getting it wrong twice.
    """
    import inspect

    from server.models import metadata as metadata_models
    from server.models.metadata import Base

    derived_names = {
        cls.__tablename__
        for _, cls in inspect.getmembers(metadata_models, inspect.isclass)
        if getattr(cls, "__module__", "") == metadata_models.__name__
        and hasattr(cls, "__tablename__")
        and cls.__tablename__ not in _NON_DERIVED_TABLES
    }

    protected = _tables_referenced_by_runtime(derived_names)
    ordered = [
        t
        for t in Base.metadata.sorted_tables
        if t.name in derived_names and t.name not in protected
    ]
    ordered.reverse()  # children first, so foreign keys stay satisfied
    return ordered


def _tables_referenced_by_runtime(derived_names: set[str]) -> frozenset[str]:
    """Derived tables that runtime data holds foreign keys into.

    ``runs.status`` points at ``run_statuses`` and ``trace_events.event_type`` at
    ``event_types``, so clearing those rows while a user's runs exist is refused
    by the database.  They are stable enum tables, so they get seeded
    insert-if-missing instead of being cleared.  Computed from the schema rather
    than hard-coded, so a new runtime foreign key protects itself.
    """
    import server.models.run  # noqa: F401 — registers the runtime tables

    from server.models.metadata import Base

    protected: set[str] = set()
    for table in Base.metadata.sorted_tables:
        if table.name in derived_names:
            continue  # only runtime / non-derived tables count as referrers
        for fk in table.foreign_keys:
            target = fk.column.table.name
            if target in derived_names:
                protected.add(target)
    return frozenset(protected)


def _protected_enum_tables() -> frozenset[str]:
    """Public wrapper used by the seeding path."""
    import inspect

    from server.models import metadata as metadata_models

    derived_names = {
        cls.__tablename__
        for _, cls in inspect.getmembers(metadata_models, inspect.isclass)
        if getattr(cls, "__module__", "") == metadata_models.__name__
        and hasattr(cls, "__tablename__")
        and cls.__tablename__ not in _NON_DERIVED_TABLES
    }
    return _tables_referenced_by_runtime(derived_names)


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


#: The help topics ship in one file, which the `en` suffix names.
HELP_TOPICS_FILENAME = "help_topics.en.json"


async def _sync_help_topics(session) -> None:
    """Upsert all help topics from the topics JSON into the `help_topics` table.

    Unlike the bulk seeding, this is idempotent — it runs on every startup and
    keeps the DB in sync with the JSON source of truth. Existing rows are
    updated by `topic_key`; new rows are inserted.
    """
    import json
    from sqlalchemy import select
    from server.models.metadata import HelpTopic

    help_file = os.path.join(SEED_DATA_DIR, HELP_TOPICS_FILENAME)
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
        "Help topics synced: %d in file, %d pre-existing",
        len(topics), len(existing),
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
                await _sync_help_topics(session)
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
            protected_tables = _protected_enum_tables()
            for table_name, model_cls in _enum_models.items():
                rows = enums_data.get(table_name, [])
                if model_cls.__tablename__ in protected_tables:
                    # Never cleared, so add only what is missing rather than
                    # colliding on the primary key.
                    present = set(
                        (await session.execute(select(model_cls.name))).scalars().all()
                    )
                    rows = [r for r in rows if r["name"] not in present]
                for row in rows:
                    session.add(model_cls(
                        name=row["name"], display_label=row["display_label"],
                        sort_order=row["sort_order"], description=row.get("description", ""),
                    ))
            await session.flush()

            for n in _load("slipnet_nodes.json"):
                session.add(SlipnetNodeDef(name=n["name"], short_name=n["short_name"],
                                            conceptual_depth=n["conceptual_depth"],
                                            description=n.get("description", ""),
                                            descriptor_predicate=n.get("descriptor_predicate")))
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
            session.add(EngineParam(
                name=_SEED_FINGERPRINT_PARAM, value=fingerprint, value_type="string",
            ))
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

            # Sync help topics from the topics JSON (idempotent upsert)
            await _sync_help_topics(session)

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
