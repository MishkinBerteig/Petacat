"""E2E (C9b): the Admin scope picker's flow, with the request shapes the client sends.

The Params editor saves an engine parameter with the scope "chosen configurations": the client
reads ``GET /api/configurations`` for the revisions (string keys), previews an ``update`` op by
natural key with ``expect`` (the value the editor showed), and commits with a reason.  The
targets are the global configuration (Metacat Mode's) and a Stopped Training Mode Session; the
commit is then undone by its group, so Metacat Mode's configuration is back where it started.
"""

from __future__ import annotations

import pytest

from tests.e2e.test_configuration_edits_api import (  # noqa: F401  (fixtures and helpers)
    PARAM, base_value, make, manual, revision, undo_group,
)


@pytest.mark.asyncio
async def test_preview_then_commit_to_global_and_a_stopped_session_then_undo(manual, app_client):
    v0 = base_value()
    _, stopped = await make(app_client, "c9b stopped")
    listing = (await app_client.get("/api/configurations")).json()["configurations"]
    revisions = {str(c["id"]): c.get("live_revision", c["revision"]) for c in listing}

    ops = [{"op": "update", "table": "engine_params", "key": {"name": PARAM},
            "fields": {"value": str(v0 + 5)}, "expect": {"value": str(v0)}}]
    resp = await app_client.post("/api/configurations/edits/preview", json={
        "ops": ops, "targets": {"ids": [1, stopped]}, "base_revisions": revisions, "note": ""})
    assert resp.status_code == 200, resp.text
    pre = resp.json()
    results = {t["configuration_id"]: t["result"] for t in pre["targets"]}
    assert results == {1: "apply", stopped: "apply"}
    assert base_value() == v0  # a preview writes nothing

    resp = await app_client.post("/api/configurations/edits", json={
        "preview_token": pre["preview_token"], "overwrite": [], "apply_rest": [],
        "all_or_nothing": False, "reason": "ui flow"})
    assert resp.status_code == 200, resp.text
    done = resp.json()
    assert done["committed"] is True
    assert {t["configuration_id"]: t["result"] for t in done["targets"]} == {1: "apply", stopped: "apply"}
    assert await revision(app_client, stopped) == 1
    assert base_value() == v0 + 5

    await undo_group(app_client, 1, done["group_id"])
    await undo_group(app_client, stopped, done["group_id"])
    assert base_value() == v0
