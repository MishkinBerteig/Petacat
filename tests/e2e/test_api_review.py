"""The review surfaces read back what the persistence modes wrote (WP3.9).

``test_persistence_modes.py`` establishes that Normal and Audit write the right rows.
These establish the other half of the claim — that something can read them — because
the failure this work package was convened to fix was not a bad writer but a writer
with no reader, and a writer with a reader that has no tests is the same failure one
release later.

The tests are organised the way the surfaces are: the Training Session browser, the
Normal start-against-end comparison, and the forward-only Audit inspector.  The two
that matter most are ``test_the_inspector_reconstructs_the_recorded_run``, which
requires the inspector's re-execution to agree with the recorded action log tick for
tick, and ``test_stepping_backwards_is_refused``, which pins the deliberate Phase 0
limit so that "we didn't build it" cannot quietly become "it half works".
"""

from __future__ import annotations

import pytest

from server.services.sinks import MODE_AUDIT, MODE_FAST, MODE_NORMAL

from tests.e2e.conftest import E2E_SEED as SEED

PROBLEM = {"initial": "abc", "modified": "abd", "target": "mrrjjj"}


@pytest.fixture
async def review_client(app_client):
    """``app_client`` with the review service wired in.

    The e2e client drives the app through ASGI, which does not run the lifespan that
    normally constructs the services, so ``conftest`` builds the ``RunService`` by
    hand.  The review service is built here rather than there so that the shared
    fixture — which also holds the advisory lock every e2e session serialises on —
    stays untouched.
    """
    from server.api import review as review_module
    from server.api.runs import get_run_service
    from server.services.review_service import ReviewService

    review_module._review_service = ReviewService(get_run_service().meta)
    yield app_client
    review_module._review_service = None


async def _run(client, mode: str, max_steps: int = 900, **kw):
    created = await client.post(
        "/api/runs", json={**PROBLEM, "seed": SEED, "mode": mode, **kw}
    )
    assert created.status_code == 200, created.text
    run = created.json()
    await client.post(f"/api/runs/{run['run_id']}/run", json={"max_steps": max_steps})
    return run["run_id"]


# ─────────────────────────────────────────────────────────────────────────────
# The Training Session browser
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sessions_list_with_their_run_counts(review_client):
    """The browser's top level: sessions, newest first, countable at a glance."""
    run_id = await _run(review_client, MODE_NORMAL, max_steps=200)

    resp = await review_client.get("/api/review/sessions")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] >= 1
    assert body["sessions"], "the run just created belongs to a session"

    current = body["sessions"][0]
    assert current["run_count"] >= 1
    assert current["first_run_at"] is not None
    assert current["last_run_at"] is not None
    # A session ends when Episodic Memory is cleared; nothing has cleared it here.
    assert current["is_open"] is True

    detail = await review_client.get(f"/api/review/sessions/{current['session_id']}")
    assert detail.status_code == 200
    runs = detail.json()["runs"]
    assert run_id in [r["run_id"] for r in runs]


@pytest.mark.asyncio
async def test_a_session_can_be_named(review_client):
    """The one editable thing about a Training Session.

    A session is not created deliberately — it is the span between two Episodic Memory
    clears — so a number and a date range is all that otherwise distinguishes one. The
    column has existed since WP3.0 and nothing could set it.
    """
    await _run(review_client, MODE_NORMAL, max_steps=100)
    sessions = (await review_client.get("/api/review/sessions")).json()["sessions"]
    session_id = sessions[0]["session_id"]

    saved = await review_client.put(
        f"/api/review/sessions/{session_id}/note",
        json={"note": "five-letter sweep"},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json() == {"session_id": session_id, "note": "five-letter sweep"}

    # Both places the browser reads it from have to agree, because it shows the note
    # in the list header and in the opened detail, and fetches them separately.
    listed = (await review_client.get("/api/review/sessions")).json()["sessions"]
    assert next(s for s in listed if s["session_id"] == session_id)["note"] == (
        "five-letter sweep"
    )
    detail = (await review_client.get(f"/api/review/sessions/{session_id}")).json()
    assert detail["note"] == "five-letter sweep"


@pytest.mark.asyncio
async def test_naming_a_session_that_does_not_exist_is_refused(review_client):
    """A 404 rather than a silent no-op.

    A note the caller believes was saved and was not is worse than an error, because
    it is discovered much later — when the record is being read rather than written.
    """
    resp = await review_client.put(
        "/api/review/sessions/999999/note", json={"note": "x"}
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_a_run_can_be_opened_by_id_without_knowing_its_session(review_client):
    """The route from the dashboard into the review surfaces.

    The browser is organised by Training Session, which is the wrong way round for a
    reader arriving from Run History: they know the run, and the session is precisely
    what they do not.
    """
    run_id = await _run(review_client, MODE_NORMAL, max_steps=200)

    resp = await review_client.get(f"/api/review/runs/{run_id}")
    assert resp.status_code == 200, resp.text
    run = resp.json()

    assert run["run_id"] == run_id
    assert run["mode"] == MODE_NORMAL
    assert run["seed"] == SEED
    # The session is what the caller could not have known, so it is answered.
    assert run["session_id"] is not None
    # The same projection the session listing gives, counts included.
    assert run["capture_count"] == 2
    assert run["action_count"] == 0

    detail = (
        await review_client.get(f"/api/review/sessions/{run['session_id']}")
    ).json()
    listed = next(r for r in detail["runs"] if r["run_id"] == run_id)
    assert {k: listed[k] for k in ("mode", "seed", "capture_count", "action_count")} == {
        k: run[k] for k in ("mode", "seed", "capture_count", "action_count")
    }


@pytest.mark.asyncio
async def test_opening_a_fast_run_by_id_says_why_there_is_nothing(review_client):
    """A Fast Run has no row, so it cannot be reviewed — and the message says so."""
    created = await review_client.post(
        "/api/runs", json={**PROBLEM, "seed": SEED, "mode": MODE_FAST}
    )
    run_id = created.json()["run_id"]

    resp = await review_client.get(f"/api/review/runs/{run_id}")
    assert resp.status_code == 404
    assert "Fast Run" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_a_run_in_a_session_carries_its_identity(review_client):
    """Mode, problem, status, codelet count, answer and the two hashes — enough to
    tell one recorded experiment from another without opening it."""
    run_id = await _run(review_client, MODE_NORMAL, max_steps=400)

    sessions = (await review_client.get("/api/review/sessions")).json()["sessions"]
    detail = (
        await review_client.get(f"/api/review/sessions/{sessions[0]['session_id']}")
    ).json()
    run = next(r for r in detail["runs"] if r["run_id"] == run_id)

    assert run["mode"] == MODE_NORMAL
    assert (run["initial"], run["modified"], run["target"]) == (
        PROBLEM["initial"], PROBLEM["modified"], PROBLEM["target"],
    )
    assert run["status"]
    assert run["codelet_count"] > 0
    assert run["seed"] == SEED
    assert run["config_hash"] and run["memory_hash"]
    # Normal writes exactly two captures and no actions; that is the mode's whole
    # difference from Fast, and the browser shows it.
    assert run["capture_count"] == 2
    assert run["action_count"] == 0


@pytest.mark.asyncio
async def test_a_fast_run_says_so_rather_than_looking_broken(review_client):
    """A Fast Run has nothing to review, which is the mode working, not failing.

    It is not even in a session — it has no database row at all — so the surface that
    has to behave well is the capture fetch, which must say "nothing was recorded"
    rather than erroring in a way that reads as a bug.
    """
    created = await review_client.post(
        "/api/runs", json={**PROBLEM, "seed": SEED, "mode": MODE_FAST}
    )
    run_id = created.json()["run_id"]
    assert run_id < 0

    captures = await review_client.get(f"/api/review/runs/{run_id}/captures")
    assert captures.status_code == 200
    assert captures.json()["captures"] == []

    start = await review_client.get(f"/api/review/runs/{run_id}/captures/start")
    assert start.status_code == 404
    assert "no 'start' state capture" in start.text


# ─────────────────────────────────────────────────────────────────────────────
# Normal review
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_both_captures_render_in_the_shapes_the_views_read(review_client):
    """The reused components are fed exactly what they are fed live.

    ``tests/module/test_capture_projection.py`` proves the projection equals the live
    serializer; this proves the endpoint actually serves it.
    """
    run_id = await _run(review_client, MODE_NORMAL, max_steps=900)

    listing = (await review_client.get(f"/api/review/runs/{run_id}/captures")).json()
    assert [c["boundary"] for c in listing["captures"]] == ["start", "end"]

    for boundary in ("start", "end"):
        resp = await review_client.get(
            f"/api/review/runs/{run_id}/captures/{boundary}"
        )
        assert resp.status_code == 200, resp.text
        view = resp.json()
        assert view["boundary"] == boundary
        # The shapes ``WorkspaceView``, ``SlipnetView``, ``ThemespaceView``,
        # ``CoderackView`` and ``TraceView`` destructure.
        assert set(view["workspace"]) >= {
            "initial", "modified", "target", "answer",
            "bonds", "groups", "bonds_per_string", "groups_per_string",
            "top_bridges", "vertical_bridges", "bottom_bridges",
            "top_rules", "bottom_rules",
        }
        assert len(view["slipnet"]) == 59
        assert set(next(iter(view["slipnet"].values()))) == {
            "activation", "conceptual_depth", "frozen",
        }
        assert set(view["coderack"]) == {"total_count", "type_counts"}
        assert view["themespace"]["clusters"]
        assert isinstance(view["trace"], list)

    end = (
        await review_client.get(f"/api/review/runs/{run_id}/captures/end")
    ).json()
    assert end["codelet_count"] > 0


@pytest.mark.asyncio
async def test_the_end_capture_of_a_run_that_answered_still_renders(review_client):
    """The captures that matter most are the ones a run ends on.

    ``state_graph.GRAPH_TYPES`` omits ``TraceEvent``'s three subclasses, so restoring
    such a capture raises. Reading the record instead of rebuilding objects from it is
    what keeps this working, and this is the test that would notice if the review
    surface ever started restoring.
    """
    run_id = await _run(review_client, MODE_NORMAL, max_steps=2500)

    info = (await review_client.get(f"/api/runs/{run_id}")).json()
    if info["status"] != "answer_found":
        pytest.skip("this seed did not answer within the budget")

    resp = await review_client.get(f"/api/review/runs/{run_id}/captures/end")
    assert resp.status_code == 200, resp.text
    assert any(
        e["event_type"] == "answer_found" for e in resp.json()["trace"]
    )


@pytest.mark.asyncio
async def test_the_comparison_shows_what_the_run_did(review_client):
    """Not both blobs: what changed.

    Structures built, how far the temperature moved, which concepts were recruited,
    which themes came to dominate, and what was added to the Training Session's
    Episodic Memory.
    """
    run_id = await _run(review_client, MODE_NORMAL, max_steps=1500)

    resp = await review_client.get(f"/api/review/runs/{run_id}/comparison")
    assert resp.status_code == 200, resp.text
    cmp = resp.json()

    assert cmp["run_id"] == run_id
    assert cmp["codelets"]["start"] == 0
    assert cmp["codelets"]["executed"] == cmp["codelets"]["end"]

    assert cmp["temperature"]["start"] == 100.0
    assert cmp["temperature"]["delta"] == pytest.approx(
        cmp["temperature"]["end"] - cmp["temperature"]["start"]
    )

    # A run of this length builds structure; the comparison names it rather than only
    # counting it.
    built_bonds = sum(cmp["structures"]["bonds"]["built"].values())
    assert built_bonds > 0
    assert sum(cmp["structures"]["bridges"]["built"].values()) > 0
    # Counts, not the structures: the bridges themselves are in the Run-end capture
    # the review renders beside this, and repeating them would ship them twice.
    assert "end_bridges" not in cmp["structures"]

    # The Slipnet moves, and the comparison ranks the movers rather than dumping 59.
    assert cmp["slipnet"]["moved_count"] > 0
    assert len(cmp["slipnet"]["moved"]) <= 15
    deltas = [abs(m["delta"]) for m in cmp["slipnet"]["moved"]]
    assert deltas == sorted(deltas, reverse=True)

    assert cmp["trace"]["events_at_start"] == 0
    assert cmp["trace"]["events_at_end"] >= 0
    assert isinstance(cmp["themes"]["dominant_at_end"], list)
    assert cmp["memory"]["answers_at_end"] >= cmp["memory"]["answers_at_start"]


@pytest.mark.asyncio
async def test_the_raw_capture_is_available_for_inspection(review_client):
    """"The format is inspectable and versionable" is a claim WP3.4 makes; something
    has to be able to look at it."""
    run_id = await _run(review_client, MODE_NORMAL, max_steps=200)

    resp = await review_client.get(f"/api/review/runs/{run_id}/captures/start/raw")
    assert resp.status_code == 200
    raw = resp.json()
    assert raw["format_version"] == 1
    assert set(raw) >= {"problem", "runner", "workspace", "coderack", "graph"}


@pytest.mark.asyncio
async def test_an_unknown_boundary_is_refused(review_client):
    run_id = await _run(review_client, MODE_NORMAL, max_steps=100)
    resp = await review_client.get(f"/api/review/runs/{run_id}/captures/middle")
    assert resp.status_code == 400
    assert "middle" in resp.text


# ─────────────────────────────────────────────────────────────────────────────
# Audit review
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_action_log_is_paginated(review_client):
    """A 2,000-codelet Audit Run records thousands of actions; returning them all in
    one response is how a review surface becomes something nobody opens twice."""
    run_id = await _run(review_client, MODE_AUDIT, max_steps=600)

    summary = (
        await review_client.get(f"/api/review/runs/{run_id}/actions/summary")
    ).json()
    assert summary["total"] > 0
    assert "codelet" in summary["by_type"]

    first = (
        await review_client.get(
            f"/api/review/runs/{run_id}/actions?limit=50&offset=0"
        )
    ).json()
    assert first["total"] == summary["total"]
    assert len(first["actions"]) == min(50, summary["total"])
    # ``sequence`` is dense from 1, so an offset is also a position in replay order.
    assert [a["sequence"] for a in first["actions"]] == list(
        range(1, len(first["actions"]) + 1)
    )

    second = (
        await review_client.get(
            f"/api/review/runs/{run_id}/actions?limit=50&offset=50"
        )
    ).json()
    if summary["total"] > 50:
        assert second["actions"][0]["sequence"] == 51

    filtered = (
        await review_client.get(
            f"/api/review/runs/{run_id}/actions?action_type=codelet&limit=10"
        )
    ).json()
    assert all(a["action_type"] == "codelet" for a in filtered["actions"])
    assert filtered["total"] == summary["by_type"]["codelet"]


@pytest.mark.asyncio
async def test_the_inspector_reconstructs_the_recorded_run(review_client):
    """The decisive Audit test: re-execution must agree with the record.

    The inspector restores the Run-start capture and steps a real engine forward,
    because the log records the codelet and the temperature at each tick but not the
    Slipnet and Themespace activations, and those are half of what the plan asks the
    inspector to show.  That is only legitimate if the reconstruction *is* the recorded
    run, so it is checked against the log tick by tick rather than assumed.
    """
    run_id = await _run(review_client, MODE_AUDIT, max_steps=400)

    opened = await review_client.post(f"/api/review/runs/{run_id}/inspector")
    assert opened.status_code == 200, opened.text
    state = opened.json()
    assert state["codelet_count"] == 0
    assert state["final_codelet_count"] > 0
    assert state["at_end"] is False

    recorded = (
        await review_client.get(
            f"/api/review/runs/{run_id}/actions?action_type=codelet&limit=25"
        )
    ).json()["actions"]
    assert recorded

    for action in recorded:
        tick = action["codelet_count"]
        resp = await review_client.post(
            f"/api/review/runs/{run_id}/inspector/advance",
            json={"to_codelet": tick},
        )
        assert resp.status_code == 200, resp.text
        at = resp.json()

        assert at["codelet_count"] == tick
        # The codelet the record says ran at this tick, and the codelet the
        # reconstruction ran, are the same codelet.
        assert at["codelet"]["payload"]["codelet_type"] == action["payload"]["codelet_type"]
        # And the temperature the reconstruction is at is the temperature recorded.
        assert at["temperature"] == pytest.approx(action["temperature"])

    await review_client.delete(f"/api/review/runs/{run_id}/inspector")


@pytest.mark.asyncio
async def test_the_inspector_shows_the_state_at_a_tick(review_client):
    """The codelet that ran, the structures that changed, and the activation and
    temperature at that instant — in the shapes the reused views read."""
    run_id = await _run(review_client, MODE_AUDIT, max_steps=400)
    await review_client.post(f"/api/review/runs/{run_id}/inspector")

    at = (
        await review_client.post(
            f"/api/review/runs/{run_id}/inspector/advance",
            json={"to_codelet": 200},
        )
    ).json()

    assert at["codelet_count"] == 200
    assert at["codelet"] is not None
    assert isinstance(at["structure_changes"], list)
    assert len(at["slipnet"]) == 59
    assert set(at["coderack"]) == {"total_count", "type_counts"}
    assert at["themespace"]["clusters"]
    assert at["workspace"]["initial"] == PROBLEM["initial"]
    assert 0 <= at["temperature"] <= 100

    await review_client.delete(f"/api/review/runs/{run_id}/inspector")


@pytest.mark.asyncio
async def test_stepping_backwards_is_refused(review_client):
    """Phase 0 is forward-only, deliberately, and says so rather than half-working.

    Backwards scrubbing means inverting actions from their recorded ``before`` state.
    WP3.8 kept the format open to it and did not build the machinery, so a request to
    step back is a conflict with the inspector's state — not a silent restart, which
    from outside would be indistinguishable from having actually stepped back.
    """
    run_id = await _run(review_client, MODE_AUDIT, max_steps=400)
    await review_client.post(f"/api/review/runs/{run_id}/inspector")
    await review_client.post(
        f"/api/review/runs/{run_id}/inspector/advance", json={"to_codelet": 150}
    )

    back = await review_client.post(
        f"/api/review/runs/{run_id}/inspector/advance", json={"to_codelet": 20}
    )
    assert back.status_code == 409
    assert "forward only" in back.text

    # The inspection is unharmed: it is still where it was.
    still = (await review_client.get(f"/api/review/runs/{run_id}/inspector")).json()
    assert still["codelet_count"] == 150

    # Re-opening restarts it, which is a different thing from scrubbing.
    reopened = (
        await review_client.post(f"/api/review/runs/{run_id}/inspector")
    ).json()
    assert reopened["codelet_count"] == 0

    await review_client.delete(f"/api/review/runs/{run_id}/inspector")


@pytest.mark.asyncio
async def test_the_inspector_stops_at_the_end_of_the_record(review_client):
    """Asked past the last recorded tick, it goes as far as the record goes."""
    run_id = await _run(review_client, MODE_AUDIT, max_steps=300)
    opened = (
        await review_client.post(f"/api/review/runs/{run_id}/inspector")
    ).json()
    final = opened["final_codelet_count"]

    at = (
        await review_client.post(
            f"/api/review/runs/{run_id}/inspector/advance",
            json={"to_codelet": final + 10_000},
        )
    ).json()
    assert at["codelet_count"] == final
    assert at["at_end"] is True

    await review_client.delete(f"/api/review/runs/{run_id}/inspector")


@pytest.mark.asyncio
async def test_a_normal_run_has_no_inspection_to_open(review_client):
    """Only an Audit Run records the per-tick actions the inspector reads, and the
    surface says which mode is needed rather than opening something empty."""
    run_id = await _run(review_client, MODE_NORMAL, max_steps=200)
    resp = await review_client.post(f"/api/review/runs/{run_id}/inspector")
    assert resp.status_code == 404
    assert "audit mode" in resp.text


@pytest.mark.asyncio
async def test_stepping_without_an_open_inspection_is_refused(review_client):
    run_id = await _run(review_client, MODE_AUDIT, max_steps=200)
    resp = await review_client.post(
        f"/api/review/runs/{run_id}/inspector/advance", json={"to_codelet": 10}
    )
    assert resp.status_code == 404
    assert "open one before stepping" in resp.text
