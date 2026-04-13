"""E2E test fixtures — requires Postgres accessible via TEST_DATABASE_URL.

When running inside the dev container:
  docker compose -f docker-compose.dev.yml exec app pytest tests/e2e/ -v

The test DB URL is provided by the TEST_DATABASE_URL env var, which
points to a separate database on the same Postgres instance.

ALL e2e tests are deterministic: they use fixed seeds and produce
identical results on every run.
"""

import os
import asyncio
import pytest
import httpx

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://petacat:dev@db:5432/petacat_test",
)

# Fixed seed for deterministic e2e tests
E2E_SEED = 12345


def _db_available() -> bool:
    """Check if the test DB host is reachable."""
    import socket
    # Parse host and port from the URL
    # URL format: postgresql+asyncpg://user:pass@host:port/dbname
    try:
        parts = TEST_DB_URL.split("@")[1].split("/")[0]
        if ":" in parts:
            host, port = parts.split(":")
            port = int(port)
        else:
            host = parts
            port = 5432
        sock = socket.create_connection((host, port), timeout=2)
        sock.close()
        return True
    except Exception:
        return False


# Skip all e2e tests if DB isn't reachable
pytestmark = pytest.mark.skipif(
    not _db_available(),
    reason="Test Postgres not reachable. Run inside dev container: "
           "docker compose -f docker-compose.dev.yml exec app pytest tests/e2e/ -v",
)


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def test_engine():
    from sqlalchemy.pool import NullPool

    # First, ensure the test database exists
    admin_url = TEST_DB_URL.rsplit("/", 1)[0] + "/petacat"
    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    async with admin_engine.connect() as conn:
        result = await conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = 'petacat_test'")
        )
        if result.fetchone() is None:
            await conn.execute(text("CREATE DATABASE petacat_test"))
    await admin_engine.dispose()

    # Use NullPool to avoid connection sharing issues with ASGI transport
    engine = create_async_engine(TEST_DB_URL, echo=False, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture(scope="session")
async def setup_db(test_engine):
    """Create all tables and seed metadata once per session."""
    # Import all models so Base.metadata knows about them
    from server.models.metadata import Base  # noqa
    import server.models.run  # noqa — registers Run, CycleSnapshot, etc. on Base.metadata

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    # Seed metadata
    from sqlalchemy.pool import NullPool
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        await _seed_metadata(session)
        await session.commit()

    yield

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def _seed_metadata(session: AsyncSession):
    """Insert seed_data into the test DB."""
    import json
    seed_dir = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")

    from server.models.metadata import (
        BridgeOrientationDef, BridgeTypeDef, ClauseTypeDef, CodeletFamilyDef,
        CodeletPhaseDef, CodeletTypeDef, CommentaryTemplate,
        DemoModeDef, DemoProblem as DemoProblemRow, EngineParam,
        EventTypeDef, FormulaCoefficient, HelpTopic, LinkTypeDef,
        ParamValueTypeDef, PostingDirectionDef, PostingRule, ProposalLevelDef,
        RuleTypeDef, RunStatusDef, SlipnetLayoutPos, SlipnetLinkDef,
        SlipnetNodeDef, ThemeDimensionDef, ThemeTypeDef, UrgencyLevel,
    )

    def _load(fn):
        with open(os.path.join(seed_dir, fn)) as f:
            return json.load(f)

    # Seed enum lookup tables first (required by FK constraints)
    _enum_models = {
        "run_statuses": RunStatusDef,
        "event_types": EventTypeDef,
        "bridge_types": BridgeTypeDef,
        "bridge_orientations": BridgeOrientationDef,
        "clause_types": ClauseTypeDef,
        "rule_types": RuleTypeDef,
        "theme_types": ThemeTypeDef,
        "proposal_levels": ProposalLevelDef,
        "link_types": LinkTypeDef,
        "codelet_families": CodeletFamilyDef,
        "codelet_phases": CodeletPhaseDef,
        "posting_directions": PostingDirectionDef,
        "param_value_types": ParamValueTypeDef,
        "demo_modes": DemoModeDef,
    }
    enums_data = _load("enums.json")
    for table_name, model_cls in _enum_models.items():
        for row in enums_data.get(table_name, []):
            session.add(model_cls(
                name=row["name"],
                display_label=row["display_label"],
                sort_order=row["sort_order"],
                description=row.get("description", ""),
            ))
    await session.flush()  # Ensure enum PKs exist before FK references

    for n in _load("slipnet_nodes.json"):
        session.add(SlipnetNodeDef(name=n["name"], short_name=n["short_name"],
                                    conceptual_depth=n["conceptual_depth"]))
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
    posting_data = _load("posting_rules.json")
    for pr in posting_data.get("posting_rules", []):
        session.add(PostingRule(
            codelet_type=pr["codelet_type"], direction=pr["direction"],
            urgency_when_posted=pr.get("urgency_when_posted"),
            urgency_formula=pr.get("urgency_formula"),
            posting_formula=pr.get("posting_formula", ""),
            count_formula=pr.get("count_formula", ""),
            count_values=pr.get("count_values"),
            condition=pr.get("condition", "always"),
            triggering_slipnodes=pr.get("triggering_slipnodes"),
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

    # Help topics: prefer the locale-named file, fall back to legacy name.
    # Matches the production loader in server/main.py::_sync_help_topics.
    help_candidates = ["help_topics.en.json", "help_topics.json"]
    help_filename = next(
        (fn for fn in help_candidates if os.path.exists(os.path.join(seed_dir, fn))),
        None,
    )
    if help_filename:
        for t in _load(help_filename):
            session.add(HelpTopic(
                topic_type=t["topic_type"],
                topic_key=t["topic_key"],
                title=t["title"],
                short_desc=t.get("short_desc", ""),
                full_desc=t.get("full_desc", ""),
                metadata_json=t.get("metadata", {}),
            ))


@pytest.fixture
async def db_session(test_engine, setup_db):
    """Provide a fresh async session for each test."""
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest.fixture
async def app_client(setup_db, test_engine):
    """Provide an HTTPX async client pointing at the FastAPI app.

    Overrides the DB dependency to use the test database.
    """
    from server.main import app
    from server.db import get_session
    from server.engine.metadata import MetadataProvider
    from server.services.run_service import RunService
    from server.api import runs as runs_module

    seed_dir = os.environ.get(
        "SEED_DATA_DIR",
        os.path.join(os.path.dirname(__file__), "..", "..", "seed_data"),
    )
    meta = MetadataProvider.from_seed_data(seed_dir)
    run_service = RunService(meta)
    runs_module._run_service = run_service

    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async def _test_session():
        session = factory()
        try:
            yield session
        finally:
            await session.close()

    app.dependency_overrides[get_session] = _test_session

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client

    app.dependency_overrides.clear()
