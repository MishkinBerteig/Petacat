"""``ChangeService.apply``, the validation funnel, against a real database (C5).

Uses ``C5_DATABASE_URL`` (default: the harness server, database ``petacat_c5``) and skips when
Postgres is unreachable.  The G6 input-validation suite runs through the funnel and needs the
real ``resolve`` of ``change_resolve`` (C14a); those tests skip until it exists.
"""

from __future__ import annotations

import importlib.util
import os
import socket

import pytest

pytest.importorskip("sqlalchemy", reason="sqlalchemy not available locally")

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from tests.integration.equivalence_harness import SEED_DIR, ensure_database, harness_db_url


def scratch_url() -> str:
    default = harness_db_url().rsplit("/", 1)[0] + "/petacat_c5"
    return os.environ.get("C5_DATABASE_URL", default)


def _reachable() -> bool:
    try:
        authority = scratch_url().split("@")[1].split("/")[0]
        host, _, port = authority.partition(":")
        socket.create_connection((host, int(port or 5432)), timeout=2).close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _reachable(), reason="the scratch Postgres is not reachable (start it with scripts/dev.sh db)"
)

REAL_RESOLVE = importlib.util.find_spec("server.services.change_resolve") is not None
needs_resolve = pytest.mark.skipif(not REAL_RESOLVE, reason="change_resolve (C14a) has not landed")

LOCK_KEY = 0x7E7AC005


@pytest.fixture
async def engine():
    import server.models.run  # noqa: F401
    import server.models.configuration_state  # noqa: F401
    from server.models.metadata import Base

    url = scratch_url()
    await ensure_database(url)
    eng = create_async_engine(url, poolclass=NullPool)
    lock = await eng.connect()
    await lock.execute(text("SELECT pg_advisory_lock(:k)"), {"k": LOCK_KEY})
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield eng
    finally:
        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await lock.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
        await lock.close()
        await eng.dispose()


@pytest.fixture
async def loaded(engine):
    from server.services.standard_configuration import seed_metadata_from_json

    async with AsyncSession(engine, expire_on_commit=False) as session:
        await seed_metadata_from_json(session, SEED_DIR)
        await session.commit()
    return engine


def _s(engine) -> AsyncSession:
    return AsyncSession(engine, expire_on_commit=False)


def node(name: str, **extra) -> dict:
    return {
        "op": "insert", "table": "slipnet_node_defs",
        "row": {"name": name, "short_name": name[:4], "conceptual_depth": 50, **extra},
    }


def batch(*ops, **envelope) -> dict:
    return {"source": "admin", "actor": "admin", "base_version": "head", "ops": list(ops), **envelope}


async def apply(engine, b):
    from server.services.configuration_writer import ChangeService

    async with _s(engine) as session:
        return await ChangeService.apply(session, b)


async def revision(engine) -> int:
    async with _s(engine) as session:
        return (await session.execute(text("SELECT revision FROM configurations WHERE id = 1"))).scalar_one()


async def entries(engine) -> list[dict]:
    from server.services.journal_views import read_entries

    async with _s(engine) as session:
        return await read_entries(session)


async def refused(engine, b):
    from server.services.configuration_writer import ChangeError

    before = await revision(engine)
    with pytest.raises(ChangeError) as caught:
        await apply(engine, b)
    assert await revision(engine) == before, "a refused batch wrote something"
    return caught.value


# --- the write ----------------------------------------------------------------


async def test_a_batch_is_written_and_the_report_says_so(loaded):
    before = await revision(loaded)
    report = await apply(loaded, batch(node("c5-new"), base_version=before, note="why", channel="admin_editor",
                                       group_id="g-1"))
    assert report["persisted"] is True and report["ok"] is True
    assert (report["version_before"], report["version_after"]) == (before, before + 1)
    assert report["configuration_id"] == 1
    last = (await entries(loaded))[-1]
    assert report["batch_id"] == last["id"]
    assert (last["source"], last["actor"], last["channel"], last["note"], last["group_id"]) == (
        "admin", "admin", "admin_editor", "why", "g-1")


async def test_the_entry_carries_the_proposed_and_the_resolved_ops(loaded):
    submitted = node("c5-two")
    await apply(loaded, batch(submitted))
    last = (await entries(loaded))[-1]
    assert last["proposed"] == [submitted]
    resolved = last["resolved"]
    assert [(op["op"], op["table"]) for op in resolved] == [("insert", "slipnet_node_defs")]
    assert resolved[0]["row"]["name"] == "c5-two"
    assert "conceptual_depth" in resolved[0]["row"]


async def test_the_run_start_check_lists_what_a_run_would_stop_at_and_never_refuses(loaded):
    from server.engine.start_check import REQUIRED_ENGINE_PARAMETERS

    name = REQUIRED_ENGINE_PARAMETERS[0][0]
    before = await revision(loaded)
    report = await apply(loaded, batch({"op": "delete", "table": "engine_params", "key": {"name": name}}))
    assert report["persisted"] is True and report["version_after"] == before + 1
    stops = [e for e in report["effects"] if e.get("effect") == "run_start_check"]
    assert any(e["name"] == name and e["check"] == "I-1" for e in stops)


async def test_a_batch_that_changes_nothing_is_not_persisted(loaded):
    before = await revision(loaded)
    report = await apply(loaded, batch())
    assert report["persisted"] is False and report["batch_id"] is None
    assert report["version_after"] == before == report["version_before"]


# --- compare-and-set ----------------------------------------------------------


async def test_strict_refuses_a_stale_base_and_writes_nothing(loaded):
    current = await revision(loaded)
    error = await refused(loaded, batch(node("c5-stale"), base_version=current - 1, base_mode="strict"))
    assert error.code == "stale" and error.status == 409
    assert error.problems[0]["field"] == "base_version"


async def test_strict_is_the_default_and_needs_a_base_version(loaded):
    current = await revision(loaded)
    b = batch(node("c5-default"), base_version=current - 1)
    assert (await refused(loaded, b)).code == "stale"
    del b["base_version"]
    assert (await refused(loaded, b)).code == "malformed"


async def test_strict_with_the_current_base_proceeds(loaded):
    current = await revision(loaded)
    report = await apply(loaded, batch(node("c5-fresh"), base_version=current, base_mode="strict"))
    assert report["persisted"] is True


async def test_rebase_and_head_proceed_from_an_old_base(loaded):
    current = await revision(loaded)
    first = await apply(loaded, batch(node("c5-r1"), base_version=current - 1, base_mode="rebase"))
    second = await apply(loaded, batch(node("c5-r2"), base_version="head"))
    assert (first["version_after"], second["version_after"]) == (current + 1, current + 2)


async def test_the_journal_rechecks_the_revision_under_its_lock(loaded):
    from server.services.journal import StaleRevision, write_immediate

    current = await revision(loaded)
    async with _s(loaded) as session:
        with pytest.raises(StaleRevision):
            await write_immediate(session, ops=[node("c5-cas")], source="admin", actor="admin",
                                  expected_revision=current - 1)
    assert await revision(loaded) == current


# --- dry_run ------------------------------------------------------------------


async def test_dry_run_returns_the_report_and_writes_nothing(loaded):
    before = await revision(loaded)
    count = len(await entries(loaded))
    report = await apply(loaded, batch(node("c5-dry"), dry_run=True))
    assert report["persisted"] is False and report["batch_id"] is None
    assert report["version_before"] == report["version_after"] == before
    assert await revision(loaded) == before and len(await entries(loaded)) == count
    async with _s(loaded) as session:
        found = await session.execute(text("SELECT count(*) FROM slipnet_node_defs WHERE name = 'c5-dry'"))
        assert found.scalar_one() == 0


async def test_dry_run_still_reports_run_start_effects(loaded):
    from server.engine.start_check import REQUIRED_ENGINE_PARAMETERS

    name = REQUIRED_ENGINE_PARAMETERS[1][0]
    report = await apply(loaded, batch({"op": "delete", "table": "engine_params", "key": {"name": name}},
                                       dry_run=True))
    assert any(e["name"] == name for e in report["effects"])


# --- M2 and the target --------------------------------------------------------


@pytest.mark.parametrize("source", ["learner", "external"])
async def test_a_learner_shaped_call_is_refused_on_the_global_configuration(loaded, source):
    actor = "learner:test" if source == "learner" else "external:client"
    for dry in (False, True):
        error = await refused(loaded, batch(node("c5-m2"), source=source, actor=actor, dry_run=dry))
        assert error.code == "source_refused" and error.status == 403


@pytest.mark.parametrize("source", ["admin", "import", "restore", "reset"])
async def test_the_other_sources_are_accepted_on_the_global_configuration(loaded, source):
    report = await apply(loaded, batch(node(f"c5-{source}"), source=source))
    assert report["persisted"] is True


async def test_a_session_configuration_without_stored_state_is_not_written(loaded):
    """A session configuration is written through the funnel (C8, tests/integration/
    test_session_configurations.py); a bare row with no stored current state is not."""
    from server.services.configuration_writer import ChangeService
    from server.services.configurations import ConfigurationError

    async with _s(loaded) as session:
        await session.execute(text("INSERT INTO configurations (id, kind, revision) VALUES (7, 'session', 0)"))
        await session.commit()
        with pytest.raises(ConfigurationError):
            await ChangeService.apply(session, batch(node("c5-sess"), configuration_id=7, source="creation"))


async def test_an_unknown_configuration_is_404(loaded):
    error = await refused(loaded, batch(node("c5-none"), configuration_id=99))
    assert error.code == "unknown_configuration" and error.status == 404


# --- G6: the input-validation suite, through the funnel -------------------------


@needs_resolve
@pytest.mark.parametrize(
    "bad,field",
    [
        ({"op": "frobnicate", "table": "slipnet_node_defs"}, "op"),
        ({"op": "insert", "table": "no_such_table", "row": {"name": "x"}}, "table"),
        ({"op": "insert", "table": "slipnet_node_defs", "row": {"name": "x", "bogus_column": 1}}, None),
        ({"op": "update", "table": "slipnet_node_defs", "key": {"name": "plato-a"}}, "fields"),
    ],
)
async def test_malformed_is_400_and_names_the_op(loaded, bad, field):
    error = await refused(loaded, batch(node("c5-ok"), bad))
    assert error.code == "malformed" and error.status == 400
    assert error.problems[0]["op_index"] == 1
    if field:
        assert error.problems[0]["field"] == field


@needs_resolve
async def test_an_update_or_delete_of_a_missing_key_is_unknown_reference(loaded):
    for op in (
        {"op": "update", "table": "slipnet_node_defs", "key": {"name": "nope"}, "fields": {"conceptual_depth": 5}},
        {"op": "delete", "table": "slipnet_node_defs", "key": {"name": "nope"}},
    ):
        error = await refused(loaded, batch(op))
        assert error.code == "unknown_reference" and error.status == 422
        assert error.problems[0]["op_index"] == 0


@needs_resolve
async def test_a_link_to_a_node_that_does_not_exist_is_unknown_reference(loaded):
    link = {"op": "insert", "table": "slipnet_link_defs",
            "row": {"from_node": "plato-a", "to_node": "ghost", "link_type": "lateral", "label_node": None}}
    error = await refused(loaded, batch(link))
    assert error.code == "unknown_reference"
    assert error.problems[0]["op_index"] == 0


@needs_resolve
async def test_a_node_and_its_link_may_arrive_in_either_order(loaded):
    link = {"op": "insert", "table": "slipnet_link_defs",
            "row": {"from_node": "plato-a", "to_node": "c5-late", "link_type": "lateral", "label_node": None}}
    report = await apply(loaded, batch(link, node("c5-late")))
    assert report["persisted"] is True


@needs_resolve
async def test_code_that_does_not_compile_is_422_with_line_and_column(loaded):
    bad = {"op": "update", "table": "codelet_type_defs", "key": {"name": "bottom-up-bond-scout"},
           "fields": {"execute_body": "x = 1\ny = (\n"}}
    error = await refused(loaded, batch(bad))
    assert error.code == "does_not_compile" and error.status == 422
    problem = error.problems[0]
    assert problem["op_index"] == 0 and problem["line"] >= 1 and problem["column"] >= 1

    predicate = node("c5-pred", descriptor_predicate="obj.")
    error = await refused(loaded, batch(predicate))
    assert error.code == "does_not_compile" and error.problems[0]["op_index"] == 0


@needs_resolve
async def test_an_insert_of_an_existing_key_is_409_key_exists(loaded):
    error = await refused(loaded, batch(node("plato-a")))
    assert error.code == "key_exists" and error.status == 409
    assert error.problems[0]["op_index"] == 0


@needs_resolve
async def test_an_expect_that_differs_is_409_stale(loaded):
    op = {"op": "update", "table": "slipnet_node_defs", "key": {"name": "plato-a"},
          "fields": {"conceptual_depth": 11}, "expect": {"conceptual_depth": 99}}
    error = await refused(loaded, batch(op))
    assert error.code == "stale" and error.problems[0]["op_index"] == 0


@needs_resolve
async def test_skip_applies_the_rest_and_reports_what_it_skipped(loaded):
    missing = {"op": "delete", "table": "slipnet_node_defs", "key": {"name": "nope"}}
    report = await apply(loaded, batch(missing, node("c5-skip"), on_op_failure="skip"))
    assert report["persisted"] is True and len(report["skipped"]) == 1


@needs_resolve
async def test_abort_is_all_or_nothing(loaded):
    missing = {"op": "delete", "table": "slipnet_node_defs", "key": {"name": "nope"}}
    await refused(loaded, batch(node("c5-abort"), missing, on_op_failure="abort"))
    async with _s(loaded) as session:
        found = await session.execute(text("SELECT count(*) FROM slipnet_node_defs WHERE name = 'c5-abort'"))
        assert found.scalar_one() == 0


@needs_resolve
@pytest.mark.parametrize(
    "op",
    [
        {"op": "delete", "table": "slipnet_node_defs", "key": {"name": "plato-a"}},  # a letter
        {"op": "delete", "table": "slipnet_node_defs", "key": {"name": "plato-letter-category"}},
        {"op": "delete", "table": "formula_coefficients", "key": {"name": "temp_exponent_base"}},
        {"op": "delete", "table": "engine_params", "key": {"name": "initial_temperature"}},
        {"op": "delete", "table": "urgency_levels", "key": {"name": "low"}},
        {"op": "delete", "table": "slipnet_node_roles", "key": {"role": "dimension.direction", "ordinal": 0}},
    ],
)
async def test_changes_that_must_not_be_refused_are_accepted(loaded, op):
    # Which of these keys exist depends on the Metacat Standard Configuration; a missing key is
    # the one thing that is refused, so skip is used only to tell "absent" from "refused".
    async with _s(loaded) as session:
        table, key = op["table"], op["key"]
        where = " AND ".join(f"{col} = :{col}" for col in key)
        present = (await session.execute(text(f"SELECT count(*) FROM {table} WHERE {where}"), key)).scalar_one()
    if not present:
        pytest.skip(f"{table} {key} is not in this configuration")
    report = await apply(loaded, batch(op))
    assert report["persisted"] is True


@needs_resolve
async def test_a_convenience_op_is_journaled_as_proposed_and_as_its_resolved_expansion(loaded):
    submitted = {"op": "remove_node", "name": "plato-a"}
    report = await apply(loaded, batch(submitted))
    assert report["persisted"] is True and report["cascaded"]
    last = (await entries(loaded))[-1]
    assert last["proposed"] == [submitted]
    assert all(op["op"] in ("insert", "update", "delete") for op in last["resolved"])
    assert {op["table"] for op in last["resolved"]} >= {"slipnet_node_defs", "slipnet_link_defs"}
