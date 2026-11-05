"""Two live runs held by one server do not touch each other (round 2, stage 2).

``WorkspaceStructure._meta`` and ``._themespace`` used to be class attributes, so creating a
second run rebound them for the first.  The server keeps every run it has created in
``RunService._runners`` and steps them one request at a time, so a client that creates run B
before it has finished run A changed A's cognition: with the same configuration, A's bridge
strengths were computed against B's themes; with another configuration, against B's
coefficients as well (and could crash).

These tests drive two runs the way the client does: create both, then step A in batches and
poll the views between batches, and compare it with the same run created alone.  Run A is
compared codelet by codelet and by its final Workspace, Slipnet and Themespace.

Requires a local Postgres, as every e2e test does.
"""

from __future__ import annotations

import json

import pytest

A = {"initial": "abc", "modified": "abd", "target": "xyz", "seed": 7}
B = {"initial": "aabc", "modified": "aabd", "target": "ijk", "seed": 8}
CAP = 4000


async def _drive(client, run_id: int, batch: int = 15) -> dict:
    """Step a run to its end in client-sized batches, polling the views between batches."""
    codelets: list[tuple[int, str]] = []
    while len(codelets) < CAP:
        resp = await client.post(f"/api/runs/{run_id}/step", json={"n": batch})
        assert resp.status_code == 200, resp.text
        steps = resp.json()
        codelets += [(s["codelet_count"], s["codelet_type"]) for s in steps]
        for view in ("workspace", "themespace", "coderack", "temperature"):
            polled = await client.get(f"/api/runs/{run_id}/{view}")
            assert polled.status_code == 200, (view, polled.text)
        if not steps or any(s["answer_found"] or s["gave_up"] for s in steps):
            break
    final = {
        view: (await client.get(f"/api/runs/{run_id}/{view}")).json()
        for view in ("workspace", "slipnet", "themespace")
    }
    return {"codelets": codelets, "final": json.dumps(final, sort_keys=True)}


async def _create(client, problem: dict, mode: str) -> int:
    resp = await client.post("/api/runs", json={**problem, "mode": mode})
    assert resp.status_code == 200, resp.text
    return resp.json()["run_id"]


def _forget_memory() -> None:
    from server.services.run_service import _global_memory

    _global_memory.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["normal", "fast"])
async def test_creating_a_second_run_with_the_same_configuration_does_not_change_the_first(
    app_client, mode
):
    _forget_memory()
    alone = await _drive(app_client, await _create(app_client, A, mode))

    _forget_memory()
    a = await _create(app_client, A, mode)
    await _create(app_client, B, mode)  # created before A has been stepped, as a second tab does
    together = await _drive(app_client, a)

    assert len(alone["codelets"]) > 100
    assert together["codelets"] == alone["codelets"]
    assert together["final"] == alone["final"]


@pytest.mark.asyncio
async def test_creating_a_second_run_under_another_configuration_does_not_change_the_first(
    app_client,
):
    name = "bond_degree_of_assoc_scale"
    _forget_memory()
    alone = await _drive(app_client, await _create(app_client, A, "normal"))

    _forget_memory()
    a = await _create(app_client, A, "normal")
    resp = await app_client.put(f"/api/admin/formula-coefficients/{name}", json={"value": "5"})
    assert resp.status_code == 200, resp.text
    try:
        await _create(app_client, B, "normal")  # B starts under the edited configuration
    finally:
        restored = await app_client.put(
            f"/api/admin/formula-coefficients/{name}", json={"value": "11"}
        )
        assert restored.status_code == 200, restored.text
    together = await _drive(app_client, a)

    assert together["codelets"] == alone["codelets"]
    assert together["final"] == alone["final"]


@pytest.mark.asyncio
async def test_stepping_two_runs_alternately_gives_each_the_run_it_has_alone(app_client):
    _forget_memory()
    alone_a = await _drive(app_client, await _create(app_client, A, "fast"))
    _forget_memory()
    alone_b = await _drive(app_client, await _create(app_client, B, "fast"))

    _forget_memory()
    a = await _create(app_client, A, "fast")
    b = await _create(app_client, B, "fast")
    seen: dict[int, list[tuple[int, str]]] = {a: [], b: []}
    live = {a, b}
    while live:
        for run_id in sorted(live):
            steps = (
                await app_client.post(f"/api/runs/{run_id}/step", json={"n": 7})
            ).json()
            seen[run_id] += [(s["codelet_count"], s["codelet_type"]) for s in steps]
            if not steps or any(s["answer_found"] or s["gave_up"] for s in steps):
                live.discard(run_id)
            if len(seen[run_id]) >= CAP:
                live.discard(run_id)

    # The two runs share the server's Episodic Memory, as every run in Metacat Mode does, so
    # B (stepped after A found its answer) may legitimately differ once A's answer is in
    # memory.  A is stepped first at every turn, so the codelets they run up to A's answer
    # are the comparison that must hold: A is identical to A alone.
    assert seen[a] == alone_a["codelets"]
    assert len(seen[b]) > 100
    assert alone_b["codelets"][:50] == seen[b][:50]


@pytest.fixture
async def review_client(app_client):
    """``app_client`` with the review service wired in (see ``test_api_review.py``)."""
    from server.api import review as review_module
    from server.services.configuration_store import get_configuration_store
    from server.services.review_service import ReviewService

    review_module._review_service = ReviewService(get_configuration_store())
    yield app_client
    review_module._review_service = None


@pytest.mark.asyncio
async def test_an_open_review_inspector_does_not_change_a_live_run(review_client):
    """An Audit inspector is a second engine, stepped while the live run is in flight.  It
    used to swap the process-wide Themespace binding around each call to stay out of the
    live run's way; there is no swap now, because nothing is process-wide."""
    client = review_client
    audit = await _create(client, {"initial": "abc", "modified": "abd", "target": "mrrjjj",
                                   "seed": 12345}, "audit")
    done = await client.post(f"/api/runs/{audit}/run", json={"max_steps": 400})
    assert done.status_code == 200, done.text

    _forget_memory()
    alone = await _drive(client, await _create(client, A, "fast"))

    _forget_memory()
    a = await _create(client, A, "fast")
    opened = await client.post(f"/api/review/runs/{audit}/inspector")
    assert opened.status_code == 200, opened.text
    final = opened.json()["final_codelet_count"]
    codelets: list[tuple[int, str]] = []
    tick = 0
    while len(codelets) < CAP:
        steps = (await client.post(f"/api/runs/{a}/step", json={"n": 15})).json()
        codelets += [(s["codelet_count"], s["codelet_type"]) for s in steps]
        tick = min(tick + 20, final)
        moved = await client.post(
            f"/api/review/runs/{audit}/inspector/advance", json={"to_codelet": tick}
        )
        assert moved.status_code == 200, moved.text
        if not steps or any(s["answer_found"] or s["gave_up"] for s in steps):
            break
    await client.delete(f"/api/review/runs/{audit}/inspector")

    assert codelets == alone["codelets"]


@pytest.mark.asyncio
async def test_no_run_is_bound_around_an_e2e_test(app_client):
    """The unit/module fixture's ambient run must not reach e2e: a server path that forgot
    to open its run's scope has to raise ``NoRunBound`` here, as it would in production."""
    from server.engine.run_binding import NoRunBound, current

    with pytest.raises(NoRunBound):
        current()
    created = await _create(app_client, A, "fast")
    resp = await app_client.post(f"/api/runs/{created}/step", json={"n": 5})
    assert resp.status_code == 200
    with pytest.raises(NoRunBound):  # and nothing a request opened is left bound
        current()
