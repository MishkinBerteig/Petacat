"""C13: the History views of the journal (configuration plan 3.10.6, 3.11, 3.16.1).

Against a scratch database (``C13_DATABASE_URL``; default: the harness server, database
``petacat_c13_a``), skipped when Postgres is unreachable.  Covers the filtered journal, one
entry in full, as-of for the global configuration and for a session's, restore and undo as new
entries whose result equals the target state, "where did this name go" after delete, rename and
merge, the names a configuration lacks, and a live session's pending entries merged in (a fake
live source stands in for the session service).
"""

from __future__ import annotations

import os
import socket
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

pytest.importorskip("sqlalchemy", reason="sqlalchemy not available locally")

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from tests.integration.equivalence_harness import SEED_DIR, ensure_database, harness_db_url


def scratch_url() -> str:
    default = harness_db_url().rsplit("/", 1)[0] + "/petacat_c13_a"
    return os.environ.get("C13_DATABASE_URL", default)


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

LOCK_KEY = 0x7E7AC013


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
    from server.services.configuration_startup import first_load

    async with AsyncSession(engine, expire_on_commit=False) as session:
        await first_load(session, SEED_DIR)
        await session.commit()
    return engine


@pytest.fixture(autouse=True)
def no_live_source():
    from server.services.configuration_store import set_live_source

    set_live_source(None)
    yield
    set_live_source(None)


def _s(engine) -> AsyncSession:
    return AsyncSession(engine, expire_on_commit=False)


def node(name: str) -> dict:
    return {"op": "insert", "table": "slipnet_node_defs",
            "row": {"name": name, "short_name": name[-4:], "conceptual_depth": 50}}


def batch(*ops, configuration_id: int = 1, **envelope) -> dict:
    return {"source": "admin", "actor": "admin", "base_version": "head", "ops": list(ops),
            "configuration_id": configuration_id, **envelope}


async def apply(engine, b):
    from server.services.configuration_writer import ChangeService

    async with _s(engine) as session:
        return await ChangeService.apply(session, b)


async def make_session_config(engine, name="S", base="standard") -> tuple[int, int]:
    from server.models.training_mode_session import TrainingModeSession
    from server.services.configurations import create_session_configuration

    async with _s(engine) as session:
        row = TrainingModeSession(name=name, backend="single", policy={})
        session.add(row)
        await session.commit()
        sid = row.id
    async with _s(engine) as session:
        cid = await create_session_configuration(session, sid, base, None)
        await session.commit()
    return sid, cid


async def story_history(engine) -> None:
    """Revisions 2-7: three nodes made, one renamed, one merged away, the renamed one deleted."""
    await apply(engine, batch(node("c13-a"), node("c13-b"), node("c13-keep"), group_id="g-make"))
    await apply(engine, batch({"op": "rename_node", "old": "c13-a", "new": "c13-a2"}, actor="carol"))
    await apply(engine, batch({"op": "merge_nodes", "keep": "c13-keep", "drop": "c13-b"},
                              actor="dave", note="b was a duplicate"))
    await apply(engine, batch({"op": "remove_node", "name": "c13-a2"}, group_id="g-del", actor="erin"))


# ---------------------------------------------------------------------------
# The filtered journal
# ---------------------------------------------------------------------------


async def test_list_filters_and_orders_the_journal(loaded):
    from server.services.journal_views import list_entries

    await story_history(loaded)
    async with _s(loaded) as session:
        everything = await list_entries(session, configuration_id=1)
        revisions = [e["revision"] for e in everything["entries"]]
        assert revisions == sorted(revisions, reverse=True) and everything["total"] == 5
        first = everything["entries"][-1]
        assert first["source"] == "standard_load" and first["pending"] is False and first["label"] == ""
        assert "resolved" not in first and first["counts"]["insert"] > 100

        by_actor = await list_entries(session, configuration_id=1, actor="carol")
        assert [e["revision"] for e in by_actor["entries"]] == [3]
        by_group = await list_entries(session, configuration_id=1, group_id="g-del")
        assert [e["revision"] for e in by_group["entries"]] == [5]
        by_source = await list_entries(session, configuration_id=1, source="standard_load")
        assert by_source["total"] == 1
        ranged = await list_entries(session, configuration_id=1, revision_from=3, revision_to=4)
        assert [e["revision"] for e in ranged["entries"]] == [4, 3]
        paged = await list_entries(session, configuration_id=1, limit=2, offset=1)
        assert [e["revision"] for e in paged["entries"]] == [4, 3] and paged["total"] == 5


async def test_list_filters_by_table_and_key_including_a_rename(loaded):
    from server.services.journal_views import list_entries

    await story_history(loaded)
    async with _s(loaded) as session:
        # c13-a2 is the new key of the rename (revision 3) and the deleted row (revision 5)
        got = await list_entries(session, configuration_id=1, table="slipnet_node_defs",
                                 key={"name": "c13-a2"})
        assert [e["revision"] for e in got["entries"]] == [5, 3]
        old = await list_entries(session, configuration_id=1, table="slipnet_node_defs",
                                 key={"name": "c13-a"})
        assert [e["revision"] for e in old["entries"]] == [3, 2]
        assert (await list_entries(session, configuration_id=1, table="engine_params"))["total"] == 1
        with pytest.raises(Exception):
            await list_entries(session, configuration_id=1, key={"name": "x"})  # a key needs its table
        with pytest.raises(Exception):
            await list_entries(session, table="slipnet_node_defs", key={"bogus": "x"})


async def test_list_filters_by_time_and_across_configurations(loaded):
    from server.services.journal_views import list_entries

    await story_history(loaded)
    sid, cid = await make_session_config(loaded)
    await apply(loaded, batch(node("c13-s"), configuration_id=cid, source="external", actor="x"))
    async with _s(loaded) as session:
        across = await list_entries(session)
        assert {e["configuration_id"] for e in across["entries"]} == {1, cid}
        stamps = [e["occurred_at"] for e in across["entries"]]
        assert stamps == sorted(stamps, reverse=True)
        mine = await list_entries(session, configuration_id=cid)
        assert [e["source"] for e in mine["entries"]] == ["external"]
        future = datetime.now(timezone.utc) + timedelta(days=1)
        assert (await list_entries(session, time_from=future))["total"] == 0
        assert (await list_entries(session, time_to=future))["total"] == across["total"]


async def test_get_entry_has_the_three_bodies(loaded):
    from server.services.journal_views import get_entry, list_entries

    await story_history(loaded)
    async with _s(loaded) as session:
        merge = (await list_entries(session, configuration_id=1, actor="dave"))["entries"][0]
        full = await get_entry(session, merge["id"])
        assert full["proposed"][0]["op"] == "merge_nodes"
        assert len(full["resolved"]) == len(full["before"]) and full["resolved"]
        assert any(op["op"] == "delete" and op["key"] == {"name": "c13-b"} for op in full["resolved"])
        with pytest.raises(Exception):
            await get_entry(session, 10 ** 9)


# ---------------------------------------------------------------------------
# As-of, restore and undo
# ---------------------------------------------------------------------------


async def test_as_of_by_time_picks_the_last_entry_that_happened_by_then(loaded):
    from server.services.journal_views import list_entries, revision_at_time

    await story_history(loaded)
    async with _s(loaded) as session:
        entries = (await list_entries(session, configuration_id=1))["entries"]
        by_rev = {e["revision"]: e["occurred_at"] for e in entries}
        assert await revision_at_time(session, 1, by_rev[3]) == 3
        assert await revision_at_time(session, 1, by_rev[3] - timedelta(microseconds=1)) == 2
        assert await revision_at_time(session, 1, by_rev[1] - timedelta(days=1)) == 0


async def test_restore_a_deleted_node_is_a_new_entry_and_equals_the_target(loaded):
    from server.services.journal_views import as_of, current_state, read_entries, restore_entity, verify_journal

    await story_history(loaded)
    async with _s(loaded) as session:
        n = len(await read_entries(session))
        target = await as_of(session, 1, 4)  # c13-a2 exists, c13-b is gone
        assert ("c13-a2",) in target["slipnet_node_defs"]
        result = await restore_entity(session, 1, "slipnet_node_defs", {"name": "c13-a2"}, 4,
                                      actor="admin", note="bring it back")
        assert result.changed and result.revision == n + 1
        entries = await read_entries(session)
        assert len(entries) == n + 1 and entries[-1]["source"] == "restore"
        assert entries[-1]["channel"] == "admin_restore" and entries[-1]["note"] == "bring it back"
        now = await current_state(session)
        assert now["slipnet_node_defs"][("c13-a2",)] == target["slipnet_node_defs"][("c13-a2",)]
        assert (await verify_journal(session)).ok
        # restoring what is already there changes nothing
        again = await restore_entity(session, 1, "slipnet_node_defs", {"name": "c13-a2"}, 4, actor="admin")
        assert not again.changed and again.revision == n + 1


async def test_undo_a_batch_and_a_group_are_new_entries(loaded):
    from server.services.journal_views import as_of, current_state, list_entries, read_entries, undo, verify_journal

    await story_history(loaded)
    async with _s(loaded) as session:
        n = len(await read_entries(session))
        before_delete = await as_of(session, 1, 4)
        undone = await undo(session, 1, group_id="g-del", actor="admin")
        assert undone.revision == n + 1
        assert await current_state(session) == before_delete
        merge = (await list_entries(session, configuration_id=1, actor="dave"))["entries"][0]
        before_merge = await as_of(session, 1, merge["revision"] - 1)
        # undo the merge: the later entries (rename kept, delete undone) leave c13-b back
        await undo(session, 1, entry_id=merge["id"], actor="admin", note="undo the merge")
        now = await current_state(session)
        assert ("c13-b",) in now["slipnet_node_defs"]
        assert now["slipnet_node_defs"][("c13-b",)] == before_merge["slipnet_node_defs"][("c13-b",)]
        assert [e["source"] for e in (await read_entries(session))[-2:]] == ["restore", "restore"]
        assert (await verify_journal(session)).ok


async def test_as_of_restore_and_undo_work_on_a_session_configuration(loaded):
    from server.services.journal_views import as_of, current_state_for, read_entries, restore_entity, undo

    sid, cid = await make_session_config(loaded)
    await apply(loaded, batch(node("c13-s1"), node("c13-s2"), configuration_id=cid,
                              source="external", actor="x"))
    await apply(loaded, batch({"op": "remove_node", "name": "c13-s1"}, configuration_id=cid,
                              source="external", actor="x", group_id="sg"))
    async with _s(loaded) as session:
        r0 = await as_of(session, cid, 0)
        r1 = await as_of(session, cid, 1)
        assert ("c13-s1",) not in r0["slipnet_node_defs"] and ("c13-s1",) in r1["slipnet_node_defs"]
        assert await as_of(session, cid, 1, table="slipnet_node_defs", key={"name": "c13-s2"}) is not None
        undone = await undo(session, cid, group_id="sg", actor="admin")
        assert undone.changed
        assert (await current_state_for(session, cid))["slipnet_node_defs"][("c13-s1",)] == \
            r1["slipnet_node_defs"][("c13-s1",)]
    await apply(loaded, batch({"op": "update", "table": "slipnet_node_defs", "key": {"name": "c13-s2"},
                               "fields": {"conceptual_depth": 7}},
                              configuration_id=cid, source="external", actor="x"))
    async with _s(loaded) as session:
        result = await restore_entity(session, cid, "slipnet_node_defs", {"name": "c13-s2"}, 1,
                                      actor="admin")
        assert result.changed
        now = await current_state_for(session, cid)
        assert now["slipnet_node_defs"][("c13-s2",)] == r1["slipnet_node_defs"][("c13-s2",)]
        entries = await read_entries(session, cid)
        assert [e["source"] for e in entries] == ["external", "external", "restore", "external", "restore"]
        from server.services.configuration_admin import verify_journal as verify_session

        assert (await verify_session(session, cid))["ok"]


# ---------------------------------------------------------------------------
# Where did the name go
# ---------------------------------------------------------------------------


async def test_name_story_after_delete_rename_and_merge(loaded):
    from server.services.journal_views import name_story

    await story_history(loaded)
    async with _s(loaded) as session:
        a = await name_story(session, "c13-a")  # created, renamed to c13-a2, then c13-a2 deleted
        assert [e["event"] for e in a["events"]] == ["created", "renamed"]
        assert a["resolves"] is False and a["current_name"] is None
        assert a["events"][1]["to"] == "c13-a2" and a["events"][1]["actor"] == "carol"
        assert a["restorable"]["table"] == "slipnet_node_defs" and a["restorable"]["as_of_revision"] == 2

        a2 = await name_story(session, "c13-a2")
        assert [e["event"] for e in a2["events"]] == ["renamed_from", "deleted"]
        assert a2["events"][1]["actor"] == "erin" and a2["events"][1]["group_id"] == "g-del"
        assert a2["resolves"] is False and a2["restorable"]["as_of_revision"] == 4
        assert "deleted" in a2["text"] and "erin" in a2["text"]

        b = await name_story(session, "c13-b")
        assert [e["event"] for e in b["events"]] == ["created", "merged_into"]
        assert b["events"][1]["into"] == "c13-keep" and b["events"][1]["note"] == "b was a duplicate"
        assert b["resolves"] is False and b["current_name"] == "c13-keep"
        assert "now 'c13-keep'" in b["text"]

        keep = await name_story(session, "c13-keep")
        assert keep["resolves"] is True and keep["current_name"] == "c13-keep"

        nobody = await name_story(session, "c13-never")
        assert nobody["events"] == [] and nobody["resolves"] is False and "no record" in nobody["text"]


async def test_a_node_rename_is_not_a_delete_of_the_relation_that_names_it(loaded):
    from server.services.journal_views import name_story

    async with _s(loaded) as session:
        node_name = (await session.execute(text(
            "SELECT node_name FROM theme_relations WHERE name = 'opposite'"))).scalar_one()
    await apply(loaded, batch({"op": "rename_node", "old": node_name, "new": node_name + "-x"}))
    async with _s(loaded) as session:
        story = await name_story(session, "opposite")
        assert story["resolves"] is True
        assert [e["event"] for e in story["events"]] == ["created", "edited"]  # standard_load, then the rename
        assert story["events"][1]["columns"] == ["node_name"]


async def test_check_names_lists_only_the_names_the_configuration_lacks(loaded):
    from server.services.journal_views import check_names

    await story_history(loaded)
    async with _s(loaded) as session:
        got = await check_names(session, ["c13-a", "c13-keep", "identity", "c13-b", "c13-never", "c13-a", ""])
        assert got["checked"] == 5
        assert [u["name"] for u in got["unresolved"]] == ["c13-a", "c13-b", "c13-never"]
        assert got["unresolved"][1]["current_name"] == "c13-keep"


# ---------------------------------------------------------------------------
# A live session: pending entries merged, labelled "not yet saved"
# ---------------------------------------------------------------------------


def _live_source(document, pending, saved_through):
    live = SimpleNamespace(state="running", document=document, revision=saved_through + len(pending),
                           saved_through=saved_through, unsaved=len(pending), pending=pending)
    return lambda session_id: live


async def test_a_live_sessions_pending_entries_are_merged_and_labelled(loaded):
    from server.services import configurations
    from server.services.configuration_store import set_live_source
    from server.services.journal import PendingEntry
    from server.services.journal_views import list_entries, name_story

    sid, cid = await make_session_config(loaded)
    await apply(loaded, batch(node("c13-stored"), configuration_id=cid, source="external", actor="x"))
    async with _s(loaded) as session:
        document = await configurations.current_document(session, cid)
        saved = (await configurations.get_row(session, cid))["revision"]
    when = datetime.now(timezone.utc)
    pending = [PendingEntry(
        revision=saved + 1, source="learner", actor="learner-1", proposed=[],
        resolved=[{"op": "delete", "table": "slipnet_node_defs", "key": {"name": "c13-stored"}}],
        before=[{"name": "c13-stored", "short_name": "ored", "conceptual_depth": 50}],
        occurred_at=when, channel="learner", note="forget it",
    )]
    set_live_source(_live_source(document, pending, saved))
    async with _s(loaded) as session:
        got = await list_entries(session, configuration_id=cid)
        assert [(e["revision"], e["pending"], e["label"], e["id"]) for e in got["entries"]][0] == (
            saved + 1, True, "not yet saved", None)
        assert all(not e["pending"] for e in got["entries"][1:])
        assert got["live"] == {"state": "running", "revision": saved + 1, "saved_through": saved, "unsaved": 1}
        only_learner = await list_entries(session, configuration_id=cid, source="learner")
        assert [e["pending"] for e in only_learner["entries"]] == [True]
        by_key = await list_entries(session, configuration_id=cid, table="slipnet_node_defs",
                                    key={"name": "c13-stored"})
        assert [e["pending"] for e in by_key["entries"]] == [True, False]
        # a pending entry already stored (the Stop write landed) is not repeated
        stale = [PendingEntry(**{**pending[0].__dict__, "revision": saved})]
        set_live_source(_live_source(document, stale, saved))
        assert all(not e["pending"] for e in (await list_entries(session, configuration_id=cid))["entries"])
    set_live_source(None)
    async with _s(loaded) as session:
        again = await list_entries(session, configuration_id=cid)
        assert again["live"] is None and all(not e["pending"] for e in again["entries"])
        assert (await name_story(session, "c13-stored", cid))["resolves"] is True
