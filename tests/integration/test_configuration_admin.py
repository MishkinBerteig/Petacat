"""C4: status, diff, reset to the Metacat Standard Configuration, restore-selected, verify.

Start-up test 7 of the configuration plan (3.6) on a scratch database, plus the command line
run as a subprocess.  Uses ``C4_DATABASE_URL`` (default: database ``petacat_c4`` on the harness
server) and skips when Postgres is unreachable.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys

import pytest

pytest.importorskip("sqlalchemy", reason="sqlalchemy not available locally")

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from tests.integration.equivalence_harness import SEED_DIR, ensure_database, harness_db_url

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def scratch_url() -> str:
    default = harness_db_url().rsplit("/", 1)[0] + "/petacat_c4"
    return os.environ.get("C4_DATABASE_URL", default)


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

LOCK_KEY = 0x7E7AC004


@pytest.fixture
async def engine():
    import server.models.run  # noqa: F401
    import server.models.training_mode_session  # noqa: F401
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
        session.add(
            __import__("server.models.configuration_state", fromlist=["x"]).ConfigurationState(
                origin="metacat_standard", standard_hash="f" * 64, load_state="ready"
            )
        )
        await session.commit()
    return engine


def _s(engine) -> AsyncSession:
    return AsyncSession(engine, expire_on_commit=False)


@pytest.fixture(autouse=True)
def _reference(monkeypatch):
    from server.services import configuration_admin as admin

    monkeypatch.setattr(admin, "SEED_DATA_DIR", SEED_DIR)


async def _edit(engine):
    """Change one parameter, add a node, delete a link: three differing rows."""
    from server.services.journal import write_immediate

    async with _s(engine) as session:
        params = (await session.execute(text("SELECT name, value FROM engine_params ORDER BY name LIMIT 1"))).one()
        link = (await session.execute(text(
            "SELECT from_node, to_node, link_type FROM slipnet_link_defs ORDER BY from_node, to_node, link_type LIMIT 1"))).one()
        ops = [
            {"op": "update", "table": "engine_params", "key": {"name": params[0]},
             "set": {"value": "123456"}},
            {"op": "insert", "table": "slipnet_node_defs", "key": {},
             "row": {"name": "c4-extra-node", "short_name": "c4x", "conceptual_depth": 50}},
            {"op": "delete", "table": "slipnet_link_defs",
             "key": {"from_node": link[0], "to_node": link[1], "link_type": link[2],
                     "label_node": ""}},
        ]
        await write_immediate(session, ops=ops, source="admin", actor="admin")
    return params[0], link


async def _runtime_counts(engine) -> dict[str, int]:
    from server.models.metadata import Base
    from server.services.config_registry import configuration_table_names

    config = set(configuration_table_names()) | {
        "configurations", "configuration_journal", "configuration_state", "help_topics"}
    out = {}
    async with _s(engine) as session:
        for name in sorted(Base.metadata.tables):
            if name in config or name.endswith("_defs") and name.startswith(("bridge", "run_status")):
                continue
            out[name] = (await session.execute(text(f'SELECT count(*) FROM "{name}"'))).scalar_one()
    return out


async def test_status_of_an_unedited_database_equals_the_standard(loaded):
    from server.services import configuration_admin as admin

    async with _s(loaded) as session:
        st = await admin.status(session)
    assert st["differs_rows"] == 0 and st["equals_standard"]
    assert st["config_hash"] == st["standard_config_hash"]
    assert st["revision"] == 1 and st["origin"] == "metacat_standard"
    assert st["standard_hash"] == "f" * 64


async def test_diff_lists_exactly_the_changed_rows(loaded):
    from server.services import configuration_admin as admin

    param, link = await _edit(loaded)
    async with _s(loaded) as session:
        d = await admin.diff(session)
        st = await admin.status(session)
    assert (d["count"], d["added"], d["removed"], d["changed"]) == (3, 1, 1, 1)
    assert st["differs_rows"] == 3 and not st["equals_standard"]
    by = {(r["table"], r["change"]): r for r in d["rows"]}
    changed = by[("engine_params", "changed")]
    assert changed["key"] == {"name": param} and changed["columns"] == ["value"]
    assert changed["current"] == {"value": "123456"}
    assert by[("slipnet_node_defs", "added")]["key"] == {"name": "c4-extra-node"}
    assert by[("slipnet_link_defs", "removed")]["key"]["from_node"] == link[0]
    json.dumps(d, default=str)


async def test_reset_equals_the_standard_and_is_one_undoable_journal_entry(loaded):
    from server.services import configuration_admin as admin
    from server.services.journal_views import read_entries, undo, verify_journal

    await _edit(loaded)
    async with _s(loaded) as session:
        edited_hash = (await admin.status(session))["config_hash"]
        revision_before = (await admin.status(session))["revision"]
    runtime_before = await _runtime_counts(loaded)

    async with _s(loaded) as session:
        result = await admin.reset_to_standard(session)
    assert result["wrote"] and result["revision"] == revision_before + 1

    async with _s(loaded) as session:
        st = await admin.status(session)
        assert st["equals_standard"] and st["differs_rows"] == 0
        assert st["config_hash"] == st["standard_config_hash"]
        entries = await read_entries(session)
        last = entries[-1]
        assert (last["source"], last["revision"]) == ("reset", revision_before + 1)
        assert len(entries) == revision_before + 1
        assert (await verify_journal(session)).ok
        # resetting again changes nothing and writes nothing
        again = await admin.reset_to_standard(session)
        assert not again["wrote"] and again["revision"] == st["revision"]
    assert await _runtime_counts(loaded) == runtime_before

    # undo reverses the reset
    async with _s(loaded) as session:
        await undo(session, entry_id=last["id"], actor="admin")
    async with _s(loaded) as session:
        st = await admin.status(session)
        assert st["config_hash"] == edited_hash and st["differs_rows"] == 3
        assert (await verify_journal(session)).ok


async def test_reset_leaves_runs_and_episodic_memory_alone(loaded):
    from server.models.run import Run
    from server.services import configuration_admin as admin

    await _edit(loaded)
    async with _s(loaded) as session:
        session.add(Run(initial_string="abc", modified_string="abd", target_string="ijk", seed=1))
        await session.commit()
    before = await _runtime_counts(loaded)
    assert before["runs"] == 1
    async with _s(loaded) as session:
        await admin.reset_to_standard(session)
    assert await _runtime_counts(loaded) == before


async def test_restore_selected_restores_only_the_chosen_rows(loaded):
    from server.services import configuration_admin as admin
    from server.services.journal_views import read_entries, verify_journal

    param, link = await _edit(loaded)
    rows = [
        {"table": "engine_params", "key": {"name": param}},
        {"table": "slipnet_link_defs",
         "key": {"from_node": link[0], "to_node": link[1], "link_type": link[2], "label_node": ""}},
    ]
    async with _s(loaded) as session:
        result = await admin.restore_selected(session, rows)
        assert result["wrote"]
    async with _s(loaded) as session:
        d = await admin.diff(session)
        assert [(r["table"], r["change"]) for r in d["rows"]] == [("slipnet_node_defs", "added")]
        last = (await read_entries(session))[-1]
        assert last["source"] == "restore" and len(last["resolved"]) == 2
        assert (await verify_journal(session)).ok
        # restoring a row that already equals the standard is skipped, writes nothing
        again = await admin.restore_selected(session, rows[:1])
        assert not again["wrote"] and again["skipped"]


async def test_restore_selected_refuses_a_row_that_exists_nowhere(loaded):
    from server.services import configuration_admin as admin

    async with _s(loaded) as session:
        with pytest.raises(admin.UnknownRow):
            await admin.restore_selected(session, [{"table": "engine_params", "key": {"name": "nope"}}])
        with pytest.raises(admin.UnknownRow):
            await admin.restore_selected(session, [{"table": "not_a_table", "key": {}}])


async def test_a_reset_after_deleting_a_node_with_its_role_rows_succeeds(loaded):
    """Deleting a node cascades to the role rows naming it; the reset must put both back."""
    from server.services import configuration_admin as admin
    from server.services.journal import write_immediate

    async with _s(loaded) as session:
        name = (await session.execute(text(
            "SELECT node_name FROM slipnet_node_roles ORDER BY role, ordinal LIMIT 1"))).scalar_one()
        await write_immediate(session, ops=[{"op": "delete", "table": "slipnet_node_defs",
                                             "key": {"name": name}}], source="admin", actor="admin")
    async with _s(loaded) as session:
        assert (await admin.status(session))["differs_rows"] > 1
        await admin.reset_to_standard(session)
    async with _s(loaded) as session:
        assert (await admin.status(session))["equals_standard"]


async def test_a_missing_configuration_is_unknown(loaded):
    from server.services import configuration_admin as admin

    async with _s(loaded) as session:
        with pytest.raises(admin.UnknownConfiguration):
            await admin.status(session, 999)


def _cli(engine, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": engine.url.render_as_string(hide_password=False),
           "SEED_DATA_DIR": SEED_DIR}
    return subprocess.run(
        [sys.executable, "-m", "server.config", *args],
        cwd=REPO, env=env, capture_output=True, text=True, timeout=120,
    )


async def test_the_command_line_runs_every_command(loaded):
    await _edit(loaded)
    out = _cli(loaded, "--json", "status")
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout)["differs_rows"] == 3

    out = _cli(loaded, "diff")
    assert out.returncode == 0 and "3 row(s) differ" in out.stdout

    refused = _cli(loaded, "reset-to-standard")
    assert refused.returncode == 2 and "--yes" in refused.stderr

    out = _cli(loaded, "restore-selected", "--row", "slipnet_node_defs",
               json.dumps({"name": "c4-extra-node"}))
    assert out.returncode == 0 and "wrote one journal entry" in out.stdout, out.stderr

    out = _cli(loaded, "--json", "reset-to-standard", "--yes")
    assert out.returncode == 0 and json.loads(out.stdout)["wrote"]

    out = _cli(loaded, "--json", "status")
    assert json.loads(out.stdout)["equals_standard"]

    out = _cli(loaded, "verify-journal")
    assert out.returncode == 0 and out.stdout.startswith("ok")
