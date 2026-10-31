"""C2: the database is the configuration source at start-up (start-up tests 1-6 of 3.6).

``server.services.configuration_startup.startup_configuration`` is what ``lifespan`` calls.
These tests run it against a scratch database (``petacat_c2``, own advisory lock, like the
C0 harness) and skip when Postgres is unreachable.  Tests 7 (reset, diff, restore) and 8
(the B4 regression) belong to C4 and C3, which build what they test.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil

import pytest

pytest.importorskip("sqlalchemy", reason="sqlalchemy not available locally")

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from server.engine.hashing import config_hash
from server.engine.metadata import MetadataProvider
from tests.integration.equivalence_harness import (
    SEED_DIR,
    ensure_database,
    harness_db_url,
    provider_differences,
)
from tests.integration.test_db_seed_equivalence import _classify

import socket


def _reachable() -> bool:
    try:
        authority = scratch_url().split("@")[1].split("/")[0]
        host, _, port = authority.partition(":")
        socket.create_connection((host, int(port or 5432)), timeout=2).close()
        return True
    except Exception:
        return False


def scratch_url() -> str:
    default = harness_db_url().rsplit("/", 1)[0] + "/petacat_c2"
    return os.environ.get("C2_DATABASE_URL", default)


pytestmark = pytest.mark.skipif(
    not _reachable(), reason="the scratch Postgres is not reachable (start it with scripts/dev.sh db)"
)

LOCK_KEY = 0x7E7ACC2


@pytest.fixture
async def scratch():
    """An empty scratch database, held under an advisory lock for the test."""
    import server.models.run  # noqa: F401
    import server.models.training  # noqa: F401
    from server.models.metadata import Base

    url = scratch_url()
    await ensure_database(url)
    engine = create_async_engine(url, poolclass=NullPool)
    lock = await engine.connect()
    await lock.execute(text("SELECT pg_advisory_lock(:k)"), {"k": LOCK_KEY})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    try:
        yield url, engine
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await lock.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
        await lock.close()
        await engine.dispose()


async def _start(url, seed_dir=SEED_DIR):
    from server.services.configuration_startup import startup_configuration

    return await startup_configuration(url, seed_dir)


def _int_param() -> tuple[str, str]:
    with open(os.path.join(SEED_DIR, "engine_params.json")) as f:
        for name, value in json.load(f).items():
            if isinstance(value, int) and not isinstance(value, bool):
                return name, str(value)
    raise AssertionError("no integer engine parameter in the seed files")


async def _edit_param(engine, name: str, value: str) -> None:
    from server.models.metadata import EngineParam

    async with AsyncSession(engine) as session:
        await session.execute(update(EngineParam).where(EngineParam.name == name).values(value=value))
        await session.commit()


async def _row_counts(engine) -> dict[str, int]:
    from server.models import metadata as models
    from server.services.seeding import _derived_names
    from server.services.configuration_startup import _configuration_classes

    async with AsyncSession(engine) as session:
        return {
            cls.__tablename__: (
                await session.execute(select(func.count()).select_from(cls))
            ).scalar_one()
            for cls in _configuration_classes(models, _derived_names())
        }


# 1 ----------------------------------------------------------------------------------


async def test_the_database_is_the_source_not_the_files(scratch):
    url, engine = scratch
    await _start(url)
    name, value = _int_param()
    edited = str(int(value) + 7)
    await _edit_param(engine, name, edited)

    meta = await _start(url)

    reference = MetadataProvider.from_standard_configuration(SEED_DIR)
    assert meta.params[name] == int(edited)
    assert reference.params[name] == int(value)
    assert config_hash(meta) != config_hash(reference)


# 2 ----------------------------------------------------------------------------------


async def test_an_empty_database_first_loads(scratch):
    from server.models.configuration_state import ConfigurationState

    url, engine = scratch
    meta = await _start(url)

    async with AsyncSession(engine) as session:
        rows = (await session.execute(select(ConfigurationState))).scalars().all()
    assert len(rows) == 1
    assert (rows[0].id, rows[0].origin, rows[0].load_state) == (1, "metacat_standard", "ready")
    assert len(rows[0].standard_hash) == 64 and rows[0].loaded_at is not None

    unexplained, _ = _classify(provider_differences(MetadataProvider.from_standard_configuration(SEED_DIR), meta))
    assert not unexplained, "\n".join(unexplained)


# 3 ----------------------------------------------------------------------------------


async def test_a_loaded_database_is_never_reseeded(scratch):
    from server.models.metadata import EngineParam

    url, engine = scratch
    await _start(url)
    name, value = _int_param()
    edited = str(int(value) + 3)
    await _edit_param(engine, name, edited)
    before = await _row_counts(engine)

    await _start(url)

    assert await _row_counts(engine) == before
    async with AsyncSession(engine) as session:
        stored = (
            await session.execute(select(EngineParam.value).where(EngineParam.name == name))
        ).scalar_one()
    assert stored == edited


async def test_an_edit_survives_a_restart_and_a_deleted_row_stays_deleted(scratch):
    """Run-time edits are kept: the load is not repeated even for a removed row."""
    from server.models.metadata import UrgencyLevel

    url, engine = scratch
    await _start(url)
    async with AsyncSession(engine) as session:
        victim = (await session.execute(select(UrgencyLevel.name).limit(1))).scalar_one()
        await session.execute(UrgencyLevel.__table__.delete().where(UrgencyLevel.name == victim))
        await session.commit()

    meta = await _start(url)

    assert victim not in meta.urgency_levels


# 4 ----------------------------------------------------------------------------------


async def test_changing_a_seed_file_does_nothing_to_a_loaded_database(scratch, tmp_path):
    url, engine = scratch
    seed_copy = tmp_path / "seed_data"
    shutil.copytree(SEED_DIR, seed_copy)
    first = await _start(url, str(seed_copy))
    hash_before = config_hash(first)
    before = await _row_counts(engine)

    params_file = seed_copy / "engine_params.json"
    params = json.loads(params_file.read_text())
    name, value = _int_param()
    params[name] = int(value) + 100
    params_file.write_text(json.dumps(params))

    second = await _start(url, str(seed_copy))

    assert config_hash(second) == hash_before
    assert second.params[name] == int(value)
    assert await _row_counts(engine) == before
    # ... but the start-up reference does read the files as they now are.
    from server.services.configuration_startup import standard_reference

    assert standard_reference().params[name] == int(value) + 100


# the reference ----------------------------------------------------------------------


async def test_the_reference_equals_the_seed_files_whatever_the_database_holds(scratch):
    from server.services.configuration_startup import standard_reference

    url, engine = scratch
    await _start(url)
    name, value = _int_param()
    await _edit_param(engine, name, str(int(value) + 1))

    meta = await _start(url)

    reference = standard_reference()
    assert not provider_differences(MetadataProvider.from_standard_configuration(SEED_DIR), reference)
    assert config_hash(reference) == config_hash(MetadataProvider.from_standard_configuration(SEED_DIR))
    assert reference is not meta
    assert reference.params[name] == int(value)


# 5 ----------------------------------------------------------------------------------


async def test_an_unreachable_database_refuses_to_start():
    from server.services.configuration_startup import ConfigurationStartupError

    url = "postgresql+asyncpg://petacat:dev@127.0.0.1:1/petacat_c2"
    with pytest.raises(ConfigurationStartupError, match="unreachable"):
        await _start(url)


async def test_configuration_rows_without_a_state_row_refuse(scratch):
    from server.models.configuration_state import ConfigurationState
    from server.services.configuration_startup import ConfigurationStartupError

    url, engine = scratch
    await _start(url)
    async with AsyncSession(engine) as session:
        await session.execute(ConfigurationState.__table__.delete())
        await session.commit()

    with pytest.raises(ConfigurationStartupError, match="clear it"):
        await _start(url)


async def test_a_state_that_is_not_ready_refuses(scratch):
    from server.models.configuration_state import ConfigurationState
    from server.services.configuration_startup import ConfigurationStartupError

    url, engine = scratch
    await _start(url)
    async with AsyncSession(engine) as session:
        await session.execute(update(ConfigurationState).values(load_state="loading"))
        await session.commit()

    with pytest.raises(ConfigurationStartupError, match="not a single 'ready' row"):
        await _start(url)


async def test_a_state_row_over_empty_tables_refuses(scratch):
    from server.models.metadata import Base
    from server.services.configuration_startup import ConfigurationStartupError, _configuration_classes
    from server.models import metadata as models
    from server.services.seeding import _derived_names

    url, engine = scratch
    await _start(url)
    async with engine.begin() as conn:
        for cls in _configuration_classes(models, _derived_names()):
            await conn.execute(text(f'TRUNCATE TABLE "{cls.__tablename__}" CASCADE'))

    with pytest.raises(ConfigurationStartupError, match="every configuration table is empty"):
        await _start(url)


async def test_an_unreadable_database_refuses_and_leaves_it_alone(scratch):
    """A database from an older schema (a column the models declare is missing)."""
    from server.services.configuration_startup import ConfigurationStartupError

    url, engine = scratch
    await _start(url)
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE slipnet_node_defs DROP COLUMN descriptor_predicate"))
    before = await _row_counts(engine)

    with pytest.raises(ConfigurationStartupError, match="clear it"):
        await _start(url)

    assert await _row_counts(engine) == before


async def test_an_unparseable_parameter_value_refuses(scratch):
    from server.services.configuration_startup import ConfigurationStartupError

    url, engine = scratch
    await _start(url)
    name, _ = _int_param()
    await _edit_param(engine, name, "not-a-number")

    with pytest.raises(ConfigurationStartupError):
        await _start(url)


async def test_an_unreadable_seed_file_refuses_to_start(scratch, tmp_path):
    from server.services.configuration_startup import ConfigurationStartupError

    url, engine = scratch
    seed_copy = tmp_path / "seed_data"
    shutil.copytree(SEED_DIR, seed_copy)
    await _start(url, str(seed_copy))
    (seed_copy / "slipnet_nodes.json").write_text("{not json")

    with pytest.raises(ConfigurationStartupError, match="cannot be read"):
        await _start(url, str(seed_copy))


# 6 ----------------------------------------------------------------------------------


async def test_two_simultaneous_start_ups_load_once(scratch):
    from server.models.configuration_state import ConfigurationState

    url, engine = scratch

    first, second = await asyncio.gather(_start(url), _start(url))

    assert config_hash(first) == config_hash(second)
    with open(os.path.join(SEED_DIR, "slipnet_nodes.json")) as f:
        node_count = len(json.load(f))
    counts = await _row_counts(engine)
    assert counts["slipnet_node_defs"] == node_count
    async with AsyncSession(engine) as session:
        assert (await session.execute(select(func.count()).select_from(ConfigurationState))).scalar_one() == 1


# nothing writes the seed files -------------------------------------------------------


async def test_start_up_does_not_modify_the_seed_files(scratch, tmp_path):
    url, engine = scratch
    seed_copy = tmp_path / "seed_data"
    shutil.copytree(SEED_DIR, seed_copy)

    def snapshot():
        return {p.name: (p.stat().st_mtime_ns, p.read_bytes()) for p in seed_copy.iterdir()}

    before = snapshot()
    await _start(url, str(seed_copy))
    await _start(url, str(seed_copy))
    assert snapshot() == before
