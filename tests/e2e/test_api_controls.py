"""E2E tests for interactive control endpoints.

ALL tests are deterministic: same seed → same results.
Requires: a local Postgres — start it with `scripts/dev.sh db`.
"""

import pytest

SEED = 54321


@pytest.mark.asyncio
async def test_set_and_clear_breakpoint(app_client):
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    # Set breakpoint
    resp = await app_client.post(f"/api/runs/{run_id}/breakpoint", json={"codelet_count": 25})
    assert resp.status_code == 200
    assert resp.json()["breakpoint"] == 25

    # Clear breakpoint
    resp = await app_client.delete(f"/api/runs/{run_id}/breakpoint")
    assert resp.status_code == 200
    assert resp.json()["breakpoint"] is None


@pytest.mark.asyncio
async def test_set_step_size(app_client):
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    resp = await app_client.put(f"/api/runs/{run_id}/step-size", json={"step_size": 5})
    assert resp.status_code == 200
    assert resp.json()["step_size"] == 5


@pytest.mark.asyncio
async def test_clamp_and_unclamp_temperature(app_client):
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    # Clamp temperature
    resp = await app_client.post(f"/api/runs/{run_id}/clamp-temperature", json={
        "value": 50.0, "cycles": 10,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["clamped"] is True
    assert data["temperature"] == 50.0

    # Unclamp
    resp = await app_client.delete(f"/api/runs/{run_id}/clamp-temperature")
    assert resp.status_code == 200
    assert resp.json()["clamped"] is False


@pytest.mark.asyncio
async def test_temperature_endpoint_serves_the_clamp_state(app_client):
    """The temperature reads with the engine's clamp flag beside it.

    Clamping is engine state, as it is in the Scheme (``*temperature-clamped?*``,
    set during a snag response and cleared by ``undo-snag-condition``). Serving it
    with the value is what lets the gauge's clamped indicator report the engine
    rather than remember its own requests.
    """
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    resp = await app_client.get(f"/api/runs/{run_id}/temperature")
    assert resp.status_code == 200
    assert resp.json()["clamped"] is False

    await app_client.post(f"/api/runs/{run_id}/clamp-temperature", json={
        "value": 40.0, "cycles": 10,
    })

    resp = await app_client.get(f"/api/runs/{run_id}/temperature")
    assert resp.status_code == 200
    data = resp.json()
    assert data["clamped"] is True
    assert data["temperature"] == 40.0
    assert data["clamp_value"] == 40.0
    assert data["clamp_cycles_remaining"] == 10

    await app_client.delete(f"/api/runs/{run_id}/clamp-temperature")

    resp = await app_client.get(f"/api/runs/{run_id}/temperature")
    assert resp.json()["clamped"] is False


@pytest.mark.asyncio
async def test_clamp_and_unclamp_node(app_client):
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    # Clamp a slipnet node
    resp = await app_client.post(f"/api/runs/{run_id}/clamp-node", json={
        "node_name": "plato-successor", "cycles": 20,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["clamped"] is True
    assert data["activation"] == 100.0  # Clamped nodes go to max

    # Unclamp
    resp = await app_client.request("DELETE", f"/api/runs/{run_id}/clamp-node",
                                     content='{"node_name": "plato-successor"}',
                                     headers={"content-type": "application/json"})
    assert resp.status_code == 200
    assert resp.json()["clamped"] is False


@pytest.mark.asyncio
async def test_clamp_invalid_node(app_client):
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    resp = await app_client.post(f"/api/runs/{run_id}/clamp-node", json={
        "node_name": "nonexistent-node", "cycles": 10,
    })
    assert resp.status_code in (400, 404, 422, 500)


@pytest.mark.asyncio
async def test_clamp_and_unclamp_codelets(app_client):
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    # Clamp codelet urgency
    resp = await app_client.post(f"/api/runs/{run_id}/clamp-codelets", json={
        "codelet_type": "bottom-up-bond-scout", "urgency": 91,
    })
    assert resp.status_code == 200
    assert resp.json()["clamped"] is True

    # Unclamp
    resp = await app_client.request("DELETE", f"/api/runs/{run_id}/clamp-codelets",
                                     content='{"codelet_type": "bottom-up-bond-scout"}',
                                     headers={"content-type": "application/json"})
    assert resp.status_code == 200
    assert resp.json()["clamped"] is False


@pytest.mark.asyncio
async def test_clamp_themes(app_client):
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    resp = await app_client.post(f"/api/runs/{run_id}/clamp-themes", json={
        "themes": [{
            "type": "top_bridge",
            "dimension": "plato-direction-category",
            "relation": "identity",
            "activation": 100.0,
        }],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["clamped_themes"]) >= 1

    # Unclamp
    resp = await app_client.delete(f"/api/runs/{run_id}/clamp-themes")
    assert resp.status_code == 200
    assert resp.json()["unclamped"] is True


@pytest.mark.asyncio
async def test_set_and_get_spreading_threshold(app_client):
    """Test the spreading activation threshold control endpoint."""
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    # Default should be 100
    resp = await app_client.get(f"/api/runs/{run_id}/spreading-threshold")
    assert resp.status_code == 200
    assert resp.json()["spreading_activation_threshold"] == 100

    # Set to 50
    resp = await app_client.post(f"/api/runs/{run_id}/spreading-threshold",
                                  json={"threshold": 50})
    assert resp.status_code == 200
    assert resp.json()["spreading_activation_threshold"] == 50

    # Verify persistence
    resp = await app_client.get(f"/api/runs/{run_id}/spreading-threshold")
    assert resp.status_code == 200
    assert resp.json()["spreading_activation_threshold"] == 50

    # Set to 0 (most permissive)
    resp = await app_client.post(f"/api/runs/{run_id}/spreading-threshold",
                                  json={"threshold": 0})
    assert resp.status_code == 200
    assert resp.json()["spreading_activation_threshold"] == 0

    # Clamped to valid range
    resp = await app_client.post(f"/api/runs/{run_id}/spreading-threshold",
                                  json={"threshold": 200})
    assert resp.status_code == 200
    assert resp.json()["spreading_activation_threshold"] == 100


@pytest.mark.asyncio
async def test_spreading_threshold_affects_slipnet(app_client):
    """Verify that different thresholds produce different slipnet states."""
    # Run 1: threshold=100 (strict)
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id_strict = resp.json()["run_id"]
    await app_client.post(f"/api/runs/{run_id_strict}/spreading-threshold",
                           json={"threshold": 100})
    await app_client.post(f"/api/runs/{run_id_strict}/step", json={"n": 30})
    resp_strict = await app_client.get(f"/api/runs/{run_id_strict}/slipnet")
    strict_state = resp_strict.json()

    # Run 2: threshold=0 (permissive)
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id_perm = resp.json()["run_id"]
    await app_client.post(f"/api/runs/{run_id_perm}/spreading-threshold",
                           json={"threshold": 0})
    await app_client.post(f"/api/runs/{run_id_perm}/step", json={"n": 30})
    resp_perm = await app_client.get(f"/api/runs/{run_id_perm}/slipnet")
    perm_state = resp_perm.json()

    # The two should produce different slipnet activation patterns
    # (we can't predict exactly how, but they should diverge)
    assert strict_state != perm_state


# ---------------------------------------------------------------------------
# Codelet patterns — MetaCat's third manual clamp handle (`gui.ss:597-603`)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_five_codelet_patterns_are_listed(app_client):
    """`gui.ss:599-603` names five, and each says which codelet types it pins."""
    run = await app_client.post(
        "/api/runs",
        json={"initial": "abc", "modified": "abd", "target": "xyz", "seed": 0},
    )
    run_id = run.json()["run_id"]

    resp = await app_client.get(f"/api/runs/{run_id}/codelet-patterns")

    assert resp.status_code == 200, resp.text
    patterns = resp.json()["patterns"]
    assert [p["name"] for p in patterns] == [
        "top_down", "bottom_up", "rule", "bridge", "group",
    ]
    for pattern in patterns:
        assert pattern["entries"], pattern["name"]
        assert pattern["label"].endswith("codelet pattern")


@pytest.mark.asyncio
async def test_a_codelet_pattern_clamps_and_releases_every_entry(app_client):
    """`trace.ss:1583-1593` clamps and unclamps the whole pattern."""
    run = await app_client.post(
        "/api/runs",
        json={"initial": "abc", "modified": "abd", "target": "xyz", "seed": 0},
    )
    run_id = run.json()["run_id"]

    clamped = await app_client.post(
        f"/api/runs/{run_id}/clamp-codelet-pattern", json={"pattern": "rule"}
    )
    assert clamped.status_code == 200, clamped.text
    body = clamped.json()
    assert body["pattern"] == "rule"
    assert {e["codelet_type"] for e in body["clamped"]} == {
        "rule-scout", "rule-evaluator", "rule-builder",
    }
    # A scout is pinned at very-high and the evaluator and builder above it.
    urgencies = {e["codelet_type"]: e["urgency"] for e in body["clamped"]}
    assert urgencies["rule-evaluator"] > urgencies["rule-scout"]

    released = await app_client.request(
        "DELETE",
        f"/api/runs/{run_id}/clamp-codelet-pattern",
        json={"pattern": "rule"},
    )
    assert released.status_code == 200, released.text
    assert set(released.json()["unclamped"]) == {
        "rule-scout", "rule-evaluator", "rule-builder",
    }


@pytest.mark.asyncio
async def test_an_unknown_codelet_pattern_is_answered_with_the_ones_that_exist(app_client):
    run = await app_client.post(
        "/api/runs",
        json={"initial": "abc", "modified": "abd", "target": "xyz", "seed": 0},
    )
    run_id = run.json()["run_id"]

    resp = await app_client.post(
        f"/api/runs/{run_id}/clamp-codelet-pattern", json={"pattern": "not-a-pattern"}
    )

    assert resp.status_code == 400
    assert "bottom_up" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_clamped_themes_can_be_released(app_client):
    """`DELETE /clamp-themes` puts the Themespace back to building on evidence alone."""
    run = await app_client.post(
        "/api/runs",
        json={"initial": "abc", "modified": "abd", "target": "xyz", "seed": 0},
    )
    run_id = run.json()["run_id"]
    await app_client.post(f"/api/runs/{run_id}/run", json={"max_steps": 400})

    themespace = (await app_client.get(f"/api/runs/{run_id}/themespace")).json()
    cluster = themespace["clusters"][0]
    await app_client.post(
        f"/api/runs/{run_id}/clamp-themes",
        json={
            "themes": [
                {
                    "type": cluster["theme_type"],
                    "dimension": cluster["dimension"],
                    "relation": cluster["themes"][0]["relation"],
                    "activation": 100,
                }
            ]
        },
    )
    under_pressure = (await app_client.get(f"/api/runs/{run_id}/themespace")).json()
    assert under_pressure["thematic_pressure"]

    released = await app_client.delete(f"/api/runs/{run_id}/clamp-themes")

    assert released.status_code == 200, released.text
    after = (await app_client.get(f"/api/runs/{run_id}/themespace")).json()
    assert not any(
        theme["frozen"] for c in after["clusters"] for theme in c["themes"]
    )


# ---------------------------------------------------------------------------
# A breakpoint stops the run whichever way the run is being driven
# ---------------------------------------------------------------------------

BREAKPOINT_PROBLEM = {
    "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
}


@pytest.mark.asyncio
async def test_breakpoint_stops_a_step_batch(app_client):
    """A breakpoint below the requested count stops the step batch at it."""
    run = await app_client.post("/api/runs", json=BREAKPOINT_PROBLEM)
    run_id = run.json()["run_id"]
    await app_client.post(
        f"/api/runs/{run_id}/breakpoint", json={"codelet_count": 10}
    )

    resp = await app_client.post(f"/api/runs/{run_id}/step", json={"n": 30})

    assert resp.status_code == 200, resp.text
    steps = resp.json()
    assert len(steps) == 10
    assert steps[-1]["codelet_count"] == 10
    # The last entry names the breakpoint as the reason the batch is short.
    assert steps[-1]["breakpoint_hit"] is True
    assert all(step["breakpoint_hit"] is False for step in steps[:-1])

    info = (await app_client.get(f"/api/runs/{run_id}")).json()
    assert info["status"] == "paused"
    assert info["codelet_count"] == 10


@pytest.mark.asyncio
async def test_breakpoint_holds_the_run_until_it_is_cleared(app_client):
    """The breakpoint stays set, and holds the run at that codelet count."""
    run = await app_client.post("/api/runs", json=BREAKPOINT_PROBLEM)
    run_id = run.json()["run_id"]
    await app_client.post(
        f"/api/runs/{run_id}/breakpoint", json={"codelet_count": 10}
    )
    await app_client.post(f"/api/runs/{run_id}/step", json={"n": 30})

    held = await app_client.post(f"/api/runs/{run_id}/step", json={"n": 5})

    assert held.status_code == 200, held.text
    assert held.json() == []
    info = (await app_client.get(f"/api/runs/{run_id}")).json()
    assert info["status"] == "paused"
    assert info["codelet_count"] == 10

    await app_client.delete(f"/api/runs/{run_id}/breakpoint")
    resumed = await app_client.post(f"/api/runs/{run_id}/step", json={"n": 5})

    steps = resumed.json()
    assert len(steps) == 5
    assert steps[-1]["codelet_count"] == 15
    assert all(step["breakpoint_hit"] is False for step in steps)


@pytest.mark.asyncio
async def test_breakpoint_stops_step_and_run_at_the_same_place(app_client):
    """Stepping and running to completion stop at the breakpoint identically."""
    stepped = await app_client.post("/api/runs", json=BREAKPOINT_PROBLEM)
    stepped_id = stepped.json()["run_id"]
    await app_client.post(
        f"/api/runs/{stepped_id}/breakpoint", json={"codelet_count": 10}
    )
    await app_client.post(f"/api/runs/{stepped_id}/step", json={"n": 30})
    stepped_info = (await app_client.get(f"/api/runs/{stepped_id}")).json()

    ran = await app_client.post("/api/runs", json=BREAKPOINT_PROBLEM)
    ran_id = ran.json()["run_id"]
    await app_client.post(
        f"/api/runs/{ran_id}/breakpoint", json={"codelet_count": 10}
    )
    ran_resp = await app_client.post(
        f"/api/runs/{ran_id}/run", json={"max_steps": 200}
    )

    assert ran_resp.status_code == 200, ran_resp.text
    ran_info = ran_resp.json()
    assert ran_info["status"] == "paused"
    assert ran_info["codelet_count"] == 10
    # Same seed, same breakpoint, same stopping state.
    assert stepped_info["status"] == ran_info["status"]
    assert stepped_info["codelet_count"] == ran_info["codelet_count"]
    assert stepped_info["temperature"] == ran_info["temperature"]


@pytest.mark.asyncio
async def test_step_without_a_breakpoint_runs_the_full_count(app_client):
    """With no breakpoint set, a step batch runs every codelet asked for."""
    run = await app_client.post("/api/runs", json=BREAKPOINT_PROBLEM)
    run_id = run.json()["run_id"]

    resp = await app_client.post(f"/api/runs/{run_id}/step", json={"n": 30})

    assert resp.status_code == 200, resp.text
    steps = resp.json()
    assert len(steps) == 30
    assert steps[-1]["codelet_count"] == 30
    assert all(step["breakpoint_hit"] is False for step in steps)


@pytest.mark.asyncio
async def test_a_stepped_run_reports_running_then_paused(app_client):
    """A run being stepped reports what it is doing.

    ``step_mcat`` executes codelets exactly as ``run_mcat`` does, so a stepped run is
    running while a batch executes and paused between batches, waiting for the next
    request. The status is what every display and the WebSocket snapshot read.
    """
    create = await app_client.post(
        "/api/runs",
        json={"initial": "abc", "modified": "abd", "target": "mrrjjj", "seed": 42},
    )
    run_id = create.json()["run_id"]
    assert create.json()["status"] == "initialized"

    await app_client.post(f"/api/runs/{run_id}/step", json={"n": 20})

    info = (await app_client.get(f"/api/runs/{run_id}")).json()
    assert info["status"] == "paused"
    assert info["codelet_count"] == 20


@pytest.mark.asyncio
async def test_a_stepped_run_keeps_its_terminal_status(app_client):
    """A batch that reaches an answer reports the answer, not a pause."""
    create = await app_client.post(
        "/api/runs",
        json={"initial": "abc", "modified": "abd", "target": "xyz", "seed": 42},
    )
    run_id = create.json()["run_id"]

    await app_client.post(f"/api/runs/{run_id}/step", json={"n": 4000})

    info = (await app_client.get(f"/api/runs/{run_id}")).json()
    assert info["status"] in ("answer_found", "gave_up")
    assert info["answer"] or info["status"] == "gave_up"
