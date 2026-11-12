"""E2E (C12): edit-all, one edit sent to chosen or all configurations, with a preview.

The matrix is the global configuration (Metacat Mode's) and Training Mode Sessions that are
running, paused, Stopped and frozen; a live and a Stopped target; a missing row, a differing
value and a removed node.  Also: M3 (every edit-all batch is ``actor = admin``, has the edit's
``group_id`` and exactly one ``configuration_id``), a stale preview re-previews that target,
all-or-nothing across stored and live targets, and undo by ``group_id``.

The commits that include the global configuration are undone by group at the end of the test
that makes them, so Metacat Mode's configuration is back where it started.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from server.models.journal import JournalEntry
from server.services import configuration_edits as edits
from server.services import configuration_store as store
from server.services import journal_views
from tests.e2e.test_session_configuration import (  # noqa: F401  (fixtures and helpers)
    PARAM, _stop_default_swarm, create_with, factory_of, journal_count, manual, set_param,
)
from tests.e2e.test_training_mode_sessions_api import stop

NODE = "c12-x"
INSERT_NODE = {"op": "insert", "table": "slipnet_node_defs",
               "row": {"name": NODE, "short_name": "c12", "conceptual_depth": 50}}
UPDATE_NODE = {"op": "update", "table": "slipnet_node_defs", "key": {"name": NODE},
               "fields": {"conceptual_depth": 60}}
REMOVE_NODE = {"op": "delete", "table": "slipnet_node_defs", "key": {"name": NODE}}


def base_value() -> int:
    from server.api.runs import get_run_service

    return get_run_service().meta.get_param(PARAM)


async def make(client, name: str) -> tuple[int, int]:
    """A Stopped session; ``(session_id, configuration_id)``."""
    body = {"name": name, "settings": {"seeds_per_problem": 100000, "max_codelets": 300,
                                       "configuration_base": "global"},  # these tests mean the global configuration
            "problems": [{"initial": "abc", "modified": "abd", "target": "abc"}]}
    resp = await client.post("/api/training-mode/sessions", json=body)
    assert resp.status_code == 201, resp.text
    made = resp.json()["session"]
    return made["id"], made["configuration"]["id"]


async def change(client, cid: int, *ops):
    resp = await client.post(f"/api/configurations/{cid}/changes", json={
        "source": "admin", "actor": "test", "base_version": "head", "ops": list(ops)})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def preview(client, ops, *, ids=None, all_=False, **extra):
    targets = {"all": True} if all_ else {"ids": ids}
    resp = await client.post("/api/configurations/edits/preview",
                             json={"ops": list(ops), "targets": targets, **extra})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    body["by_id"] = {t["configuration_id"]: t for t in body["targets"]}
    return body


async def commit(client, token, **extra):
    resp = await client.post("/api/configurations/edits", json={"preview_token": token, **extra})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    body["by_id"] = {t["configuration_id"]: t for t in body["targets"]}
    return body


async def revision(client, cid: int) -> int:
    return (await client.get(f"/api/configurations/{cid}")).json()["revision"]


async def entries(engine, cid: int, group_id: str | None = None) -> list[dict]:
    async with factory_of(engine)() as db:
        return await journal_views.read_entries(db, cid, group_id=group_id)


async def undo_group(client, cid: int, group_id: str):
    resp = await client.post(f"/api/configurations/{cid}/restore", json={"undo_group": group_id})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def start(client, tid: int, paused: bool):
    resp = await client.post(f"/api/training-mode/sessions/{tid}/start", json={"paused": paused})
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# The matrix
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_matrix_global_running_paused_stopped_frozen_and_differing(
        manual, app_client, test_engine):
    v0 = base_value()
    run_t, run_c = await make(app_client, "c12 running")
    pause_t, pause_c = await make(app_client, "c12 paused")
    stop_t, stop_c = await make(app_client, "c12 stopped")
    froz_t, froz_c = await make(app_client, "c12 frozen")
    diff_t, diff_c = await make(app_client, "c12 differs")
    await start(app_client, run_t, paused=False)
    await start(app_client, pause_t, paused=True)
    await app_client.patch(f"/api/configurations/{froz_c}", json={"frozen": True})
    await change(app_client, diff_c, set_param(v0 + 1))  # edited separately
    before = {c: await revision(app_client, c) for c in (1, stop_c, froz_c, diff_c)}

    ops = [{"op": "set_param", "name": PARAM, "to": v0 + 7, "expect": v0}]
    pre = await preview(app_client, ops, all_=True)
    r = pre["by_id"]
    assert [t["configuration_id"] for t in pre["targets"]] == sorted(r)  # global first, by id
    assert (r[1]["result"], r[1]["mode"]) == ("apply", "Metacat Mode")
    assert (r[run_c]["result"], r[run_c]["session_state"]) == ("apply", "running")
    assert (r[pause_c]["result"], r[pause_c]["session_state"]) == ("apply", "paused")
    assert (r[stop_c]["result"], r[stop_c]["session_state"]) == ("apply", "stopped")
    assert (r[froz_c]["result"], r[froz_c]["reason"]) == ("skipped_by_selection", "frozen")
    assert r[diff_c]["result"] == "differs"
    assert pre["counts"] == {"apply": 4, "no_change": 0, "differs": 1, "not_applicable": 0,
                             "stale": 0, "skipped_by_selection": 1}
    # a preview writes nothing, stored or live
    assert {c: await revision(app_client, c) for c in before} == before
    assert store.live_state(run_t).revision == 0 and store.live_state(pause_t).unsaved == 0
    assert all(t["persisted"] is False for t in pre["targets"] if "report" in t)

    done = await commit(app_client, pre["preview_token"], reason="edit all")
    gid = done["group_id"]
    r = done["by_id"]
    assert done["committed"] is True and gid
    assert [r[c]["result"] for c in (1, run_c, pause_c, stop_c)] == ["apply"] * 4
    assert r[froz_c]["result"] == "skipped_by_selection" and r[diff_c]["result"] == "differs"
    # stored targets: own entry, own revision bump; the skipped ones are untouched
    for cid in (1, stop_c):
        assert r[cid]["persisted"] is True and r[cid]["version_after"] == before[cid] + 1
        assert await revision(app_client, cid) == before[cid] + 1
    assert await revision(app_client, froz_c) == before[froz_c]
    # live targets: in memory, persisted false, a revision bump of their own
    for tid, cid in ((run_t, run_c), (pause_t, pause_c)):
        assert r[cid]["persisted"] is False and r[cid]["batch_id"] is None
        assert r[cid]["version_after"] == 1
        live = store.live_state(tid)
        assert live.unsaved == 1 and live.pending[0].group_id == gid
        assert manual._live[tid].config.provider.get_param(PARAM) == v0 + 7
        assert await journal_count(test_engine, cid) == 0
    # M3: actor admin, the edit's group_id, exactly one configuration_id each
    for cid in (1, stop_c):
        group = await entries(test_engine, cid, gid)
        assert len(group) == 1
        assert (group[0]["actor"], group[0]["source"], group[0]["group_id"]) == ("admin", "admin", gid)
        assert group[0]["configuration_id"] == cid and group[0]["note"] == "edit all"
    for tid in (run_t, pause_t):
        p = store.live_state(tid).pending[0]
        assert (p.actor, p.source, p.group_id) == ("admin", "admin", gid)
    # a Stop writes the held entries with the group id
    await stop(app_client, run_t)
    stored = await entries(test_engine, run_c, gid)
    assert len(stored) == 1 and stored[0]["actor"] == "admin" and stored[0]["configuration_id"] == run_c
    # undo by group_id on the edit-all group, per stored configuration
    for cid in (1, stop_c, run_c):
        undone = await undo_group(app_client, cid, gid)
        assert undone["changed"] is True
    assert (await app_client.get("/api/configurations/1/verify-journal")).json()["ok"]
    from server.api.runs import get_run_service

    assert get_run_service().meta.get_param(PARAM) == v0


@pytest.mark.asyncio
async def test_a_missing_row_and_a_removed_node_are_not_applicable_and_apply_rest_sends_the_rest(
        manual, app_client, test_engine):
    v0 = base_value()
    has_t, has_c = await make(app_client, "c12 has node")
    lacks_t, lacks_c = await make(app_client, "c12 lacks node")
    gone_t, gone_c = await make(app_client, "c12 removed node")
    await change(app_client, has_c, INSERT_NODE)
    await change(app_client, gone_c, INSERT_NODE)
    await change(app_client, gone_c, REMOVE_NODE)
    ops = [set_param(v0 + 3), UPDATE_NODE]
    pre = await preview(app_client, ops, ids=[has_c, lacks_c, gone_c])
    r = pre["by_id"]
    assert r[has_c]["result"] == "apply"
    assert r[lacks_c]["result"] == "not_applicable" and r[lacks_c]["reason"]
    assert r[gone_c]["result"] == "not_applicable"
    done = await commit(app_client, pre["preview_token"])
    assert done["by_id"][has_c]["result"] == "apply"
    assert done["by_id"][lacks_c]["result"] == "not_applicable"  # skipped, listed, nothing written
    before = await revision(app_client, lacks_c)
    # apply the rest: the ops that do apply (the parameter) go, the node update is skipped
    pre = await preview(app_client, ops, ids=[lacks_c, gone_c])
    done = await commit(app_client, pre["preview_token"], apply_rest=[lacks_c])
    r = done["by_id"]
    assert r[lacks_c]["result"] == "apply" and r[lacks_c]["report"]["skipped"]
    assert await revision(app_client, lacks_c) == before + 1
    assert r[gone_c]["result"] == "not_applicable"
    rows = (await app_client.get(f"/api/configurations/{lacks_c}/rows", params={"table": "slipnet_node_defs"})).json()
    assert not any(x["name"] == NODE for x in rows["rows"])


@pytest.mark.asyncio
async def test_no_change_overwrite_and_a_frozen_target_chosen_by_name(manual, app_client):
    v0 = base_value()
    a_t, a_c = await make(app_client, "c12 equal")
    b_t, b_c = await make(app_client, "c12 differing")
    f_t, f_c = await make(app_client, "c12 frozen chosen")
    await change(app_client, b_c, set_param(v0 + 2))
    await app_client.patch(f"/api/configurations/{f_c}", json={"frozen": True})
    # already equal
    pre = await preview(app_client, [set_param(v0)], ids=[a_c])
    assert pre["by_id"][a_c]["result"] == "no_change"
    done = await commit(app_client, pre["preview_token"])
    assert done["by_id"][a_c]["result"] == "no_change" and await revision(app_client, a_c) == 0
    # a differing value is skipped; overwrite re-sends without expect
    ops = [{"op": "set_param", "name": PARAM, "to": v0 + 9, "expect": v0}]
    pre = await preview(app_client, ops, ids=[b_c, f_c])
    assert pre["by_id"][b_c]["result"] == "differs"
    assert pre["by_id"][f_c]["result"] == "apply"  # naming a frozen one is the selection
    done = await commit(app_client, pre["preview_token"])
    assert done["by_id"][b_c]["result"] == "differs" and await revision(app_client, b_c) == 1
    pre = await preview(app_client, ops, ids=[b_c])
    done = await commit(app_client, pre["preview_token"], overwrite=[b_c])
    assert done["by_id"][b_c]["result"] == "apply" and await revision(app_client, b_c) == 2
    # "all" skips the frozen one
    pre = await preview(app_client, [set_param(v0 + 4)], all_=True)
    assert pre["by_id"][f_c]["result"] == "skipped_by_selection"


@pytest.mark.asyncio
async def test_a_session_changing_state_is_skipped_by_selection(
        manual, app_client, monkeypatch):
    v0 = base_value()
    t, c = await make(app_client, "c12 changing state")
    other_t, other_c = await make(app_client, "c12 other")
    real = edits.live_state
    monkeypatch.setattr(edits, "live_state", lambda sid: SimpleNamespace(state="stopping", revision=0)
                        if sid == t else real(sid))
    pre = await preview(app_client, [set_param(v0 + 1)], ids=[c, other_c])
    assert (pre["by_id"][c]["result"], pre["by_id"][c]["reason"]) == ("skipped_by_selection", "changing state")
    assert pre["by_id"][other_c]["result"] == "apply"  # a skipped target never blocks another
    done = await commit(app_client, pre["preview_token"])
    assert done["by_id"][c]["result"] == "skipped_by_selection" and done["by_id"][other_c]["result"] == "apply"
    assert await revision(app_client, c) == 0


# ---------------------------------------------------------------------------
# Stale previews
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_stale_preview_reprevews_that_target_and_writes_nothing_to_it(
        manual, app_client):
    v0 = base_value()
    a_t, a_c = await make(app_client, "c12 moved")
    b_t, b_c = await make(app_client, "c12 still")
    pre_revision = await revision(app_client, a_c)
    pre = await preview(app_client, [set_param(v0 + 5)], ids=[a_c, b_c])
    await change(app_client, a_c, set_param(v0 + 1))  # moves after the preview
    done = await commit(app_client, pre["preview_token"])
    stale = done["by_id"][a_c]
    assert stale["result"] == "stale" and stale["re_preview"]["result"] == "apply"
    moved = await revision(app_client, a_c)
    assert stale["re_preview"]["revision"] == moved and moved == pre_revision + 1
    assert done["by_id"][b_c]["result"] == "apply"  # the others are not held up
    # a base revision the editor read is checked at preview time
    pre = await preview(app_client, [set_param(v0 + 6)], ids=[a_c], base_revisions={a_c: pre_revision})
    assert pre["by_id"][a_c]["result"] == "stale" and pre["by_id"][a_c]["current_revision"] == moved


# ---------------------------------------------------------------------------
# All or nothing (3.16.3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_or_nothing_across_stored_and_live_targets(manual, app_client, test_engine):
    v0 = base_value()
    live_t, live_c = await make(app_client, "c12 live")
    s_t, s_c = await make(app_client, "c12 stored")
    d_t, d_c = await make(app_client, "c12 differs")
    await start(app_client, live_t, paused=True)
    await change(app_client, d_c, set_param(v0 + 1))
    ops = [{"op": "set_param", "name": PARAM, "to": v0 + 11, "expect": v0}]
    pre = await preview(app_client, ops, ids=[live_c, s_c, d_c])
    done = await commit(app_client, pre["preview_token"], all_or_nothing=True)
    assert done["committed"] is False and done["blocked_by"] == [d_c]
    assert [done["by_id"][c]["result"] for c in (live_c, s_c)] == ["apply", "apply"]
    assert all(done["by_id"][c]["committed"] is False for c in (live_c, s_c))
    assert await revision(app_client, s_c) == 0 and store.live_state(live_t).unsaved == 0
    # overwriting the blocker lets everything go: stored in one transaction, then the live one
    done = await commit(app_client, pre["preview_token"], all_or_nothing=True, overwrite=[d_c])
    assert done["committed"] is True and done["persisted_false"] == [live_c]
    assert [done["by_id"][c]["result"] for c in (live_c, s_c, d_c)] == ["apply"] * 3
    assert await revision(app_client, s_c) == 1 and await revision(app_client, d_c) == 2
    gid = done["group_id"]
    assert len(await entries(test_engine, s_c, gid)) == 1 and len(await entries(test_engine, d_c, gid)) == 1
    assert store.live_state(live_t).pending[0].group_id == gid
    assert done["by_id"][live_c]["persisted"] is False


# ---------------------------------------------------------------------------
# Metacat Mode and Training Mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_chosen_session_edit_never_touches_the_global_configuration(manual, app_client):
    v0 = base_value()
    t, c = await make(app_client, "c12 only")
    g_before = (await app_client.get("/api/configurations/1")).json()
    pre = await preview(app_client, [set_param(v0 + 8)], ids=[c])
    assert list(pre["by_id"]) == [c]
    await commit(app_client, pre["preview_token"])
    g_after = (await app_client.get("/api/configurations/1")).json()
    assert (g_after["revision"], g_after["config_hash"]) == (g_before["revision"], g_before["config_hash"])
    assert base_value() == v0


# ---------------------------------------------------------------------------
# Requests that are wrong
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bad_requests(manual, app_client):
    ops = [set_param(5)]
    post = app_client.post
    assert (await post("/api/configurations/edits/preview",
                       json={"ops": ops, "targets": {}})).status_code == 400
    assert (await post("/api/configurations/edits/preview",
                       json={"ops": ops, "targets": {"ids": [1], "all": True}})).status_code == 400
    assert (await post("/api/configurations/edits/preview",
                       json={"ops": ops, "targets": {"ids": [999999]}})).status_code == 404
    bad = await post("/api/configurations/edits/preview",
                     json={"ops": [{"op": "no_such_op"}], "targets": {"ids": [1]}})
    assert bad.status_code == 400 and bad.json()["error"] == "malformed"
    assert (await post("/api/configurations/edits", json={"preview_token": "nonsense"})).status_code == 400
