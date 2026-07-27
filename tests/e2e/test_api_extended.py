"""E2E tests for extended runs, memory, docs, and admin endpoints.

ALL tests are deterministic.
Requires: docker compose -f docker-compose.dev.yml up -d
"""

import pytest

SEED = 99999


@pytest.mark.asyncio
async def test_list_runs(app_client):
    # Create a run first
    await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    resp = await app_client.get("/api/runs?limit=10&offset=0")
    assert resp.status_code == 200
    data = resp.json()
    assert "runs" in data
    assert "total" in data
    assert data["total"] >= 1


@pytest.mark.asyncio
async def test_run_to_completion(app_client):
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    resp = await app_client.post(f"/api/runs/{run_id}/run", json={"max_steps": 50})
    assert resp.status_code == 200
    data = resp.json()
    assert data["codelet_count"] == 50


@pytest.mark.asyncio
async def test_reset_run(app_client):
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    # Step some codelets
    await app_client.post(f"/api/runs/{run_id}/step", json={"n": 20})

    # Reset
    resp = await app_client.post(f"/api/runs/{run_id}/reset")
    assert resp.status_code == 200
    data = resp.json()
    assert data["codelet_count"] == 0
    assert data["status"] == "initialized"


@pytest.mark.asyncio
async def test_delete_run(app_client):
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    resp = await app_client.delete(f"/api/runs/{run_id}")
    assert resp.status_code == 200

    # Should be gone
    resp = await app_client.get(f"/api/runs/{run_id}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_themespace_endpoint(app_client):
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    resp = await app_client.get(f"/api/runs/{run_id}/themespace")
    assert resp.status_code == 200
    data = resp.json()
    assert "clusters" in data
    assert "active_theme_types" in data

    # Theme types must be lowercase
    for cluster in data["clusters"]:
        assert cluster["theme_type"] == cluster["theme_type"].lower(), (
            f"theme_type should be lowercase, got {cluster['theme_type']!r}"
        )
    for at in data["active_theme_types"]:
        assert at == at.lower(), (
            f"active_theme_type should be lowercase, got {at!r}"
        )


@pytest.mark.asyncio
async def test_trace_endpoint(app_client):
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    # Step to generate events
    await app_client.post(f"/api/runs/{run_id}/step", json={"n": 30})

    resp = await app_client.get(f"/api/runs/{run_id}/trace?limit=50")
    assert resp.status_code == 200
    data = resp.json()
    assert "events" in data or isinstance(data, list)


@pytest.mark.asyncio
async def test_memory_endpoint(app_client):
    resp = await app_client.get("/api/memory")
    assert resp.status_code == 200
    data = resp.json()
    assert "answers" in data
    assert "snags" in data


@pytest.mark.asyncio
async def test_spreading_threshold_changes_the_run_and_survives_reset(app_client):
    """The threshold has to actually reach the engine, and outlast a Reset.

    Reset means "this same problem and seed again", so the run's settings belong
    with it. ``init_mcat`` re-reads the metadata default, which silently threw
    away whatever the user had chosen — and since a fresh run also starts at the
    default, a chosen value could easily never reach a run at all.
    """
    async def run_with(threshold: int) -> dict:
        resp = await app_client.post("/api/runs", json={
            "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
        })
        rid = resp.json()["run_id"]
        await app_client.post(
            f"/api/runs/{rid}/spreading-threshold", json={"threshold": threshold},
        )
        got = (await app_client.get(f"/api/runs/{rid}/spreading-threshold")).json()
        assert got["spreading_activation_threshold"] == threshold
        result = (await app_client.post(
            f"/api/runs/{rid}/run", json={"max_steps": 4000},
        )).json()
        return {"run_id": rid, **result}

    # It is not decorative: the same problem and seed run differently.
    strict = await run_with(100)
    loose = await run_with(0)
    assert strict["codelet_count"] != loose["codelet_count"], (
        "threshold made no difference to the run, so it is not reaching the engine"
    )

    # And Reset keeps it rather than reverting to the default.
    await app_client.post(f"/api/runs/{loose['run_id']}/reset")
    after = (await app_client.get(
        f"/api/runs/{loose['run_id']}/spreading-threshold",
    )).json()
    assert after["spreading_activation_threshold"] == 0

    # The value each run used is recorded on the run itself, so the run list can
    # say which runs are comparable with the dissertation's (100) and which are
    # not. Read back from the row rather than from the live engine.
    listed = {r["run_id"]: r for r in (
        await app_client.get("/api/runs?limit=50")
    ).json()["runs"]}
    assert listed[strict["run_id"]]["spreading_threshold"] == 100
    assert listed[loose["run_id"]]["spreading_threshold"] == 0


@pytest.mark.asyncio
async def test_spreading_threshold_can_be_set_when_the_run_is_created(app_client):
    """Supplied at creation, so the engine is initialised with it.

    Applying it afterwards meant the opening codelets had already executed at
    the default.
    """
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
        "spreading_threshold": 30,
    })
    assert resp.status_code == 200
    run_id = resp.json()["run_id"]
    assert resp.json()["spreading_threshold"] == 30

    # Engine and stored row agree, before a single codelet has run.
    live = (await app_client.get(f"/api/runs/{run_id}/spreading-threshold")).json()
    assert live["spreading_activation_threshold"] == 30
    assert (await app_client.get(f"/api/runs/{run_id}")).json()["spreading_threshold"] == 30

    # Out-of-range input is clamped rather than stored raw.
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
        "spreading_threshold": 900,
    })
    assert resp.json()["spreading_threshold"] == 100


@pytest.mark.asyncio
async def test_run_list_carries_the_answer_and_how_it_was_obtained(app_client):
    """The run list has to say what a run answered, and whether it found it.

    A justification run is *given* its answer at creation, so ``answer`` alone
    cannot distinguish "the engine found xyd" from "the engine was asked to
    justify xyd". ``justify_mode`` travels alongside it so a display can.
    """
    # Discovery: no answer supplied.
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    discovered_id = resp.json()["run_id"]
    assert resp.json()["justify_mode"] is False
    await app_client.post(f"/api/runs/{discovered_id}/run", json={"max_steps": 4000})

    # Justification: the answer is handed over up front.
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz",
        "answer": "wyz", "seed": SEED,
    })
    given_id = resp.json()["run_id"]
    assert resp.json()["justify_mode"] is True

    listed = (await app_client.get("/api/runs?limit=50")).json()["runs"]
    by_id = {r["run_id"]: r for r in listed}

    given = by_id[given_id]
    assert given["answer"] == "wyz"
    assert given["justify_mode"] is True

    discovered = by_id[discovered_id]
    assert discovered["justify_mode"] is False
    # Whatever it settled on, an answer found is reported as not-given.
    if discovered["answer"] is not None:
        assert discovered["answer"] != ""


@pytest.mark.asyncio
async def test_run_info_reports_live_progress_while_running(app_client):
    """Polling a run mid-flight must report where the engine actually is.

    ``run_to_completion`` writes ``codelet_count`` and ``temperature`` back to the
    row only once the run ends, so mid-run the row still holds its creation
    values: status ``running`` but 0 codelets and temperature 100. Serving those
    made the UI's own sampling loop set temperature to 100 on every tick — a
    visible spike, corrected a moment later by a live read — and pinned the
    displayed codelet count at 0.
    """
    import asyncio

    # A problem that does not resolve, so there is a run to observe.
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "aabbcc", "target": "ijk", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    runner = asyncio.create_task(
        app_client.post(f"/api/runs/{run_id}/run", json={"max_steps": 20000})
    )
    try:
        observations = []
        for _ in range(40):
            await asyncio.sleep(0.1)
            info = (await app_client.get(f"/api/runs/{run_id}")).json()
            if info["status"] == "running" and info["codelet_count"] > 0:
                observations.append(info)
                if len(observations) >= 2:
                    break
            if info["status"] != "running" and info["status"] != "initialized":
                break

        assert observations, "never caught the run in flight; cannot judge freshness"

        for info in observations:
            # The two symptoms, stated directly.
            assert info["codelet_count"] > 0, f"codelet count pinned at 0: {info}"
            assert info["temperature"] < 100, f"temperature reported as 100: {info}"

        # And progress is actually visible between samples.
        if len(observations) >= 2:
            assert observations[-1]["codelet_count"] >= observations[0]["codelet_count"]
    finally:
        await app_client.post(f"/api/runs/{run_id}/stop")
        await runner


@pytest.mark.asyncio
async def test_clearing_memory_clears_what_the_ui_reads_back(app_client):
    """DELETE has to empty the same store GET serves.

    Episodic memory lives twice over: as DB rows, and in the process-wide
    ``_global_memory`` that live runs write to.  ``GET /api/memory`` serves the
    rows, but DELETE used to clear only the in-process object — so the UI's
    refresh-after-clear showed every answer still sitting there.
    """
    # Produce something worth clearing.
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]
    await app_client.post(f"/api/runs/{run_id}/run", json={"max_steps": 3000})

    before = (await app_client.get("/api/memory")).json()
    assert before["answers"] or before["snags"], "nothing stored, test proves nothing"

    resp = await app_client.delete("/api/memory")
    assert resp.status_code == 200
    body = resp.json()
    assert body["cleared"] is True
    # It reports what it actually removed, rather than claiming success blindly.
    assert body["removed"]["answers"] == len(before["answers"])
    assert body["removed"]["snags"] == len(before["snags"])

    after = (await app_client.get("/api/memory")).json()
    assert after["answers"] == []
    assert after["snags"] == []


@pytest.mark.asyncio
async def test_commentary_endpoint(app_client):
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    resp = await app_client.get(f"/api/runs/{run_id}/commentary")
    assert resp.status_code == 200
    data = resp.json()
    assert "commentary" in data
    # Should contain the new-problem paragraph
    assert "abc" in data["commentary"]
    assert "abd" in data["commentary"]
    assert "paragraph_count" in data
    assert data["paragraph_count"] >= 1


@pytest.mark.asyncio
async def test_commentary_eliza_mode(app_client):
    """The eliza_mode query param should change the commentary output."""
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    # Normal commentary (technical)
    resp_normal = await app_client.get(f"/api/runs/{run_id}/commentary")
    assert resp_normal.status_code == 200
    normal_data = resp_normal.json()
    normal_text = normal_data.get("commentary", "")

    # Eliza mode commentary
    resp_eliza = await app_client.get(
        f"/api/runs/{run_id}/commentary?eliza_mode=true"
    )
    assert resp_eliza.status_code == 200
    eliza_data = resp_eliza.json()
    eliza_text = eliza_data.get("commentary", "")

    # Both should have content, and they should differ
    assert len(normal_text) > 0
    assert len(eliza_text) > 0
    assert normal_text != eliza_text

    # Technical should have "Beginning run", Eliza should have "Okay"
    assert "Beginning run" in normal_text
    assert "Okay" in eliza_text


@pytest.mark.asyncio
async def test_commentary_accumulates(app_client):
    """Commentary should grow as the run progresses."""
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]

    # Get initial commentary
    resp = await app_client.get(f"/api/runs/{run_id}/commentary")
    initial_count = resp.json()["paragraph_count"]
    assert initial_count >= 1

    # Step many codelets to trigger events
    await app_client.post(f"/api/runs/{run_id}/step", json={"n": 500})

    # Commentary should have at least as many paragraphs
    resp = await app_client.get(f"/api/runs/{run_id}/commentary")
    final_count = resp.json()["paragraph_count"]
    assert final_count >= initial_count


# --- Admin endpoints ---

@pytest.mark.asyncio
async def test_admin_list_slipnet_nodes(app_client):
    resp = await app_client.get("/api/admin/slipnet/nodes")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 59


@pytest.mark.asyncio
async def test_admin_list_codelet_types(app_client):
    resp = await app_client.get("/api/admin/codelets")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 27


@pytest.mark.asyncio
async def test_admin_list_params(app_client):
    resp = await app_client.get("/api/admin/params")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) > 10


@pytest.mark.asyncio
async def test_admin_list_urgency_levels(app_client):
    resp = await app_client.get("/api/admin/urgency-levels")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 7


@pytest.mark.asyncio
async def test_admin_list_formula_coefficients(app_client):
    resp = await app_client.get("/api/admin/formula-coefficients")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) > 50


@pytest.mark.asyncio
async def test_admin_list_demos(app_client):
    resp = await app_client.get("/api/admin/demos")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 30


@pytest.mark.asyncio
async def test_admin_export(app_client):
    resp = await app_client.get("/api/admin/export")
    assert resp.status_code == 200
    data = resp.json()
    assert "slipnet_nodes" in data
    assert "codelet_types" in data
    assert "urgency_levels" in data
    # WS2: export now includes all new entities
    assert "theme_dimensions" in data
    assert "posting_rules" in data
    assert "commentary_templates" in data
    assert "slipnet_layout" in data
    assert "help_topics" in data


# --- WS1: Enum table CRUD ---

@pytest.mark.asyncio
async def test_admin_list_enum_tables(app_client):
    resp = await app_client.get("/api/admin/enums")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["tables"]) == 14
    assert "run_statuses" in data["tables"]
    assert "event_types" in data["tables"]


@pytest.mark.asyncio
async def test_admin_list_enum_values(app_client):
    resp = await app_client.get("/api/admin/enums/run_statuses")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 6
    names = {v["name"] for v in data}
    assert "initialized" in names
    assert "running" in names
    assert "answer_found" in names


@pytest.mark.asyncio
async def test_admin_enum_values_event_types(app_client):
    resp = await app_client.get("/api/admin/enums/event_types")
    assert resp.status_code == 200
    data = resp.json()
    # 17: the 16 original types plus concept_activation, one of the seven
    # Temporal Trace event types of §4.4.  trace_events.event_type is a foreign
    # key onto this table, so every type the engine emits must appear here.
    assert len(data) == 17
    names = {v["name"] for v in data}
    assert "bond_built" in names
    assert "snag" in names
    assert "concept_activation" in names


@pytest.mark.asyncio
async def test_admin_enum_unknown_table_404(app_client):
    resp = await app_client.get("/api/admin/enums/nonexistent")
    assert resp.status_code == 404


# --- WS2: New CRUD endpoints ---

@pytest.mark.asyncio
async def test_admin_list_theme_dimensions(app_client):
    resp = await app_client.get("/api/admin/theme-dimensions")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 9


@pytest.mark.asyncio
async def test_admin_list_posting_rules(app_client):
    resp = await app_client.get("/api/admin/posting-rules")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) > 0


@pytest.mark.asyncio
async def test_admin_list_commentary_templates(app_client):
    resp = await app_client.get("/api/admin/commentary-templates")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) > 0


@pytest.mark.asyncio
async def test_admin_list_slipnet_layout(app_client):
    resp = await app_client.get("/api/admin/slipnet-layout")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 59


@pytest.mark.asyncio
async def test_admin_list_help_topics(app_client):
    resp = await app_client.get("/api/admin/help-topics")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_admin_slipnet_link_update(app_client):
    """PUT /api/admin/slipnet/links/{id} should update a link."""
    # Get an existing link
    resp = await app_client.get("/api/admin/slipnet/links")
    assert resp.status_code == 200
    links = resp.json()
    assert len(links) > 0
    link = links[0]

    # Update it (same data, just verify the endpoint works)
    resp = await app_client.put(
        f"/api/admin/slipnet/links/{link['id']}",
        json={
            "from_node": link["from_node"],
            "to_node": link["to_node"],
            "link_type": link["link_type"],
            "label_node": link["label_node"],
            "link_length": link["link_length"],
            "fixed_length": link["fixed_length"],
        },
    )
    assert resp.status_code == 200
    updated = resp.json()
    assert updated["id"] == link["id"]


# --- Docs endpoints ---

@pytest.mark.asyncio
async def test_docs_concept(app_client):
    resp = await app_client.get("/api/docs/concepts/plato-successor")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "plato-successor"


@pytest.mark.asyncio
async def test_docs_codelet(app_client):
    resp = await app_client.get("/api/docs/codelets/bottom-up-bond-scout")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "bottom-up-bond-scout"
    assert "execute_body" in data


@pytest.mark.asyncio
async def test_docs_component(app_client):
    resp = await app_client.get("/api/docs/components/workspace")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"].lower() == "workspace"


@pytest.mark.asyncio
async def test_docs_search(app_client):
    resp = await app_client.get("/api/docs/search?q=successor")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) > 0


@pytest.mark.asyncio
async def test_docs_missing_concept(app_client):
    resp = await app_client.get("/api/docs/concepts/nonexistent")
    assert resp.status_code == 404
