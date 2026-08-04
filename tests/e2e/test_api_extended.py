"""E2E tests for extended runs, memory, docs, and admin endpoints.

ALL tests are deterministic.
Requires: a local Postgres — start it with `scripts/dev.sh db`.
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
    #: A seed of this test's own rather than the module's.  The module ``SEED`` no
    #: longer reaches a stopping state on this problem inside 4,000 codelets under
    #: either threshold, so both runs hit the cap and their codelet counts agree —
    #: which reads as "the threshold made no difference" when what happened is that
    #: neither run finished.  26 answers in 641 at the strict threshold and does not
    #: finish at the loose one, which is the difference this test is asserting.
    threshold_seed = 26

    async def run_with(threshold: int) -> dict:
        resp = await app_client.post("/api/runs", json={
            "initial": "abc", "modified": "abd", "target": "xyz",
            "seed": threshold_seed,
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


#: The twelve collections the configuration is made of.
_CONFIG_COLLECTIONS = (
    "slipnet_nodes",
    "slipnet_links",
    "codelet_types",
    "engine_params",
    "urgency_levels",
    "formula_coefficients",
    "demo_problems",
    "theme_dimensions",
    "posting_rules",
    "commentary_templates",
    "slipnet_layout",
    "help_topics",
)


@pytest.mark.asyncio
async def test_export_writes_every_collection(app_client):
    """Export is the whole configuration, and every collection has rows."""
    data = (await app_client.get("/api/admin/export")).json()

    assert set(_CONFIG_COLLECTIONS) <= set(data)
    for name in _CONFIG_COLLECTIONS:
        assert data[name], f"{name} exported empty"


@pytest.mark.asyncio
async def test_import_reports_every_collection_it_was_given(app_client):
    """Import applies all twelve and names each one with its row count.

    The reply is what a caller reads to know what was written, so it accounts for the
    payload it received.
    """
    exported = (await app_client.get("/api/admin/export")).json()

    resp = await app_client.post("/api/admin/import", json=exported)

    assert resp.status_code == 200, resp.text
    imported = resp.json()["imported"]
    assert set(imported) == set(_CONFIG_COLLECTIONS)
    for name in _CONFIG_COLLECTIONS:
        assert imported[name] == len(exported[name]), name


@pytest.mark.asyncio
async def test_an_export_import_round_trip_leaves_the_configuration_identical(app_client):
    """Export, import it back, export again: the two exports agree, collection by
    collection.

    This is the property a configuration backup is taken for.
    """
    before = (await app_client.get("/api/admin/export")).json()

    assert (await app_client.post("/api/admin/import", json=before)).status_code == 200

    after = (await app_client.get("/api/admin/export")).json()

    for name in _CONFIG_COLLECTIONS:
        assert after[name] == before[name], f"{name} changed across a round trip"


@pytest.mark.asyncio
async def test_import_restores_an_edit_in_each_collection(app_client):
    """A changed value in every collection is restored by importing the earlier export.

    One field per collection is enough to show the collection is genuinely written
    rather than counted.
    """
    original = (await app_client.get("/api/admin/export")).json()

    # A distinguishable edit in each of the twelve.
    edited = {name: [dict(row) for row in original[name]] for name in _CONFIG_COLLECTIONS}
    edited["slipnet_nodes"][0]["description"] = "edited node"
    edited["slipnet_links"][0]["link_length"] = 42
    edited["codelet_types"][0]["description"] = "edited codelet"
    edited["engine_params"][0]["value"] = "1"
    edited["urgency_levels"][0]["value"] = 11
    edited["formula_coefficients"][0]["value"] = 0.5
    edited["demo_problems"][0]["description"] = "edited demo"
    edited["theme_dimensions"][0]["valid_relations"] = ["identity"]
    edited["posting_rules"][0]["condition"] = "never"
    edited["commentary_templates"][0]["template_data"] = {"edited": True}
    edited["slipnet_layout"][0]["grid_row"] = 12
    edited["help_topics"][0]["title"] = "edited topic"

    assert (await app_client.post("/api/admin/import", json=edited)).status_code == 200

    changed = (await app_client.get("/api/admin/export")).json()
    for name in _CONFIG_COLLECTIONS:
        assert changed[name] == edited[name], f"{name} did not take the edit"

    # And the original import puts every one of them back.
    assert (await app_client.post("/api/admin/import", json=original)).status_code == 200

    restored = (await app_client.get("/api/admin/export")).json()
    for name in _CONFIG_COLLECTIONS:
        assert restored[name] == original[name], f"{name} was not restored"


@pytest.mark.asyncio
async def test_import_accepts_a_partial_payload(app_client):
    """A payload naming some collections applies those, and reports those."""
    exported = (await app_client.get("/api/admin/export")).json()
    partial = {"urgency_levels": exported["urgency_levels"]}

    imported = (await app_client.post("/api/admin/import", json=partial)).json()["imported"]

    assert imported == {"urgency_levels": len(exported["urgency_levels"])}


@pytest.mark.asyncio
async def test_a_row_missing_its_key_fails_the_whole_import(app_client):
    """One transaction: a payload that cannot be applied leaves the database as it was."""
    exported = (await app_client.get("/api/admin/export")).json()
    broken = {
        "urgency_levels": [{"value": 99}],  # no ``name``
    }

    resp = await app_client.post("/api/admin/import", json=broken)

    assert resp.status_code == 400
    after = (await app_client.get("/api/admin/export")).json()
    assert after["urgency_levels"] == exported["urgency_levels"]


# ---------------------------------------------------------------------------
# Every configuration collection is writable, not only readable.
#
# The Configuration screen offers a tab per collection, and each tab creates, updates
# and deletes rows through these routes. Each case below takes one collection through
# that whole cycle and checks the row is really gone at the end.
# ---------------------------------------------------------------------------

#: (collection path, key field, a row to create, the field an update changes, its value)
_WRITABLE_COLLECTIONS = [
    (
        "demos", "id",
        {
            "name": "e2e demo", "section": "test", "initial": "abc", "modified": "abd",
            "target": "pqr", "answer": None, "seed": 3, "mode": "discovery",
            "description": "created by a test",
        },
        "name", "e2e demo renamed",
    ),
    (
        "theme-dimensions", "id",
        {"slipnet_node": "plato-e2e-dimension", "valid_relations": ["identity"]},
        "valid_relations", ["identity", "opposite"],
    ),
    (
        "posting-rules", "id",
        {
            "codelet_type": "e2e-scout", "direction": "bottom_up",
            "urgency_when_posted": 30, "urgency_formula": None,
            "posting_formula": "", "count_formula": "", "count_values": None,
            "condition": "always", "triggering_slipnodes": None,
        },
        "condition", "never",
    ),
    (
        "commentary-templates", "id",
        {"template_key": "e2e_template", "template_data": {"greeting": "hello"}},
        "template_data", {"greeting": "good day"},
    ),
    (
        "slipnet-layout", "node_name",
        {"node_name": "plato-e2e-node", "grid_row": 9, "grid_col": 4},
        "grid_row", 11,
    ),
    (
        "help-topics", "id",
        {
            "topic_type": "concept", "topic_key": "e2e_topic", "title": "E2E Topic",
            "short_desc": "short", "full_desc": "full",
        },
        "title", "E2E Topic, renamed",
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path,key_field,row,update_field,update_value",
    _WRITABLE_COLLECTIONS,
    ids=[c[0] for c in _WRITABLE_COLLECTIONS],
)
async def test_a_configuration_collection_can_be_created_updated_and_deleted(
    app_client, path, key_field, row, update_field, update_value
):
    created = await app_client.post(f"/api/admin/{path}", json=row)
    assert created.status_code in (200, 201), created.text
    key = created.json()[key_field]

    updated = await app_client.put(
        f"/api/admin/{path}/{key}", json={**row, update_field: update_value}
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()[update_field] == update_value

    listed = (await app_client.get(f"/api/admin/{path}")).json()
    assert any(r[key_field] == key for r in listed)
    assert next(r for r in listed if r[key_field] == key)[update_field] == update_value

    deleted = await app_client.delete(f"/api/admin/{path}/{key}")
    assert deleted.status_code == 200, deleted.text

    remaining = (await app_client.get(f"/api/admin/{path}")).json()
    assert not any(r[key_field] == key for r in remaining)


@pytest.mark.asyncio
async def test_an_engine_parameter_can_be_created_and_deleted(app_client):
    """`POST` and `DELETE` for parameters, alongside the `PUT` already in use."""
    created = await app_client.post(
        "/api/admin/params",
        json={"name": "e2e_param", "value": "5", "value_type": "int"},
    )
    assert created.status_code in (200, 201), created.text

    updated = await app_client.put(
        "/api/admin/params/e2e_param", json={"value": "6", "value_type": "int"}
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["value"] == "6"

    assert (await app_client.delete("/api/admin/params/e2e_param")).status_code == 200
    names = [p["name"] for p in (await app_client.get("/api/admin/params")).json()]
    assert "e2e_param" not in names


@pytest.mark.asyncio
async def test_a_codelet_type_can_be_created_and_deleted(app_client):
    """`POST /codelets`, so a codelet type can be added as well as edited.

    A codelet's behaviour is Python source in `execute_body`, so creating one is how a
    new kind of codelet enters the program.
    """
    created = await app_client.post(
        "/api/admin/codelets",
        json={
            "name": "e2e-scout", "family": "bond", "phase": "scout",
            "default_urgency": 30, "description": "created by a test",
            "source_file": "", "source_line": 0, "execute_body": "fizzle()",
        },
    )
    assert created.status_code in (200, 201), created.text
    assert created.json()["name"] == "e2e-scout"

    listed = [c["name"] for c in (await app_client.get("/api/admin/codelets")).json()]
    assert "e2e-scout" in listed

    assert (await app_client.delete("/api/admin/codelets/e2e-scout")).status_code == 200
    remaining = [c["name"] for c in (await app_client.get("/api/admin/codelets")).json()]
    assert "e2e-scout" not in remaining


@pytest.mark.asyncio
async def test_an_unknown_codelet_family_is_answered_with_the_ones_that_exist(app_client):
    """Family and phase are foreign keys, and the reply names the available values."""
    resp = await app_client.post(
        "/api/admin/codelets",
        json={
            "name": "e2e-bad-family", "family": "not-a-family", "phase": "scout",
            "default_urgency": 30, "description": "", "source_file": "",
            "source_line": 0, "execute_body": "fizzle()",
        },
    )

    assert resp.status_code == 400
    assert "bond" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_the_websocket_pushes_a_flat_run_snapshot(app_client):
    """`WS /ws/runs/{id}` sends the run's own fields at the top level, on each tick.

    The live displays read these directly, so the frame is the snapshot rather than an
    envelope around one.
    """
    from server.main import app

    create = await app_client.post(
        "/api/runs",
        json={"initial": "abc", "modified": "abd", "target": "xyz", "seed": 0},
    )
    run_id = create.json()["run_id"]

    from fastapi.testclient import TestClient

    with TestClient(app).websocket_connect(f"/ws/runs/{run_id}") as ws:
        frame = ws.receive_json()

    assert frame["run_id"] == run_id
    for field in (
        "status",
        "codelet_count",
        "temperature",
        "temperature_clamped",
        "coderack_count",
        "trace_event_count",
        "snag_count",
        "within_clamp_period",
    ):
        assert field in frame, f"{field} missing from the snapshot"


# ---------------------------------------------------------------------------
# The three ways an answer is served describe the same object.
# ---------------------------------------------------------------------------

#: What §4.7.3 and §4.7.5 read off an answer, and what every projection therefore sends.
_ANSWER_JUDGEMENT_FIELDS = (
    "top_rule_abstractness",
    "bottom_rule_abstractness",
    "theme_abstractness",
    "is_coherent",
    "activation",
)


@pytest.mark.asyncio
async def test_the_session_and_run_memory_describe_an_answer_the_same_way(app_client):
    """`GET /api/memory` and `GET /runs/{id}/memory` are two reads of one memory.

    §4.7.3 weighs answers by how abstract their rules and themes are, so a reader gets
    the same judgement whichever route it arrives by.
    """
    create = await app_client.post(
        "/api/runs",
        json={"initial": "abc", "modified": "abd", "target": "xyz", "seed": 0},
    )
    run_id = create.json()["run_id"]
    await app_client.post(f"/api/runs/{run_id}/run", json={"max_steps": 3000})

    shared = (await app_client.get("/api/memory")).json()["answers"]
    per_run = (await app_client.get(f"/api/runs/{run_id}/memory")).json()["answers"]
    assert shared, "the run contributed no answer to the session memory"

    for answer in shared + per_run:
        for field in _ANSWER_JUDGEMENT_FIELDS:
            assert field in answer, f"{field} missing from an answer"

    by_rule = {(tuple(a["problem"]), a["top_rule_description"]): a for a in per_run}
    for answer in shared:
        twin = by_rule.get((tuple(answer["problem"]), answer["top_rule_description"]))
        if twin is None:
            continue
        for field in _ANSWER_JUDGEMENT_FIELDS:
            assert answer[field] == twin[field], field


@pytest.mark.asyncio
async def test_a_comparison_carries_its_abstractness_and_its_verdict(app_client):
    """§4.7.4: the comparison reports which answer the program prefers, and why."""
    from server.services.run_service import _global_memory

    if len(_global_memory.answers) < 2:
        for target in ("xyz", "mrrjjj"):
            create = await app_client.post(
                "/api/runs",
                json={
                    "initial": "abc", "modified": "abd", "target": target, "seed": 0,
                },
            )
            await app_client.post(
                f"/api/runs/{create.json()['run_id']}/run", json={"max_steps": 4000}
            )

    answers = (await app_client.get("/api/memory")).json()["answers"]
    if len(answers) < 2:
        pytest.skip("two stored answers are needed to compare")

    resp = await app_client.post(
        "/api/memory/compare",
        json={
            "answer_id_1": answers[0]["answer_id"],
            "answer_id_2": answers[1]["answer_id"],
        },
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    comparison = body["comparison"]
    for field in ("a_abstractness", "b_abstractness", "preferred"):
        assert field in comparison
    assert set(comparison["preferred"]) == {"answer", "reason"}
    # §4.7.4's commentary arrives in its seven pieces as well as joined.
    assert body["commentary"]["segments"]
    assert "".join(body["commentary"]["segments"]) == body["commentary"]["text"]


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


@pytest.mark.asyncio
async def test_a_single_answer_can_be_forgotten(app_client):
    """MetaCat can forget one answer without forgetting all of them.

    ``memory.ss:42-54`` deletes a single answer description, and §5.2.3's experiment
    depends on it — it works by manually deleting the just-found answer and re-running.
    With only clear-all that experiment is unreproducible, and since ``answer_present``
    stops the program rediscovering a stored answer, deleting one is now also how a user
    asks for it again.
    """
    create = await app_client.post(
        "/api/runs",
        json={"initial": "abc", "modified": "abd", "target": "ijk", "seed": 3},
    )
    run_id = create.json()["run_id"]
    await app_client.post(f"/api/runs/{run_id}/run", json={"max_steps": 3000})

    listing = (await app_client.get("/api/memory")).json()
    assert listing["answers"], "the run stored no answer to forget"
    answer_id = listing["answers"][0]["answer_id"]

    resp = await app_client.delete(f"/api/memory/answers/{answer_id}")
    assert resp.status_code == 200
    assert resp.json()["forgotten"] == answer_id

    remaining = (await app_client.get("/api/memory")).json()["answers"]
    assert answer_id not in [a["answer_id"] for a in remaining]

    # Forgetting something that is not there is a 404, not a silent success.
    assert (await app_client.delete("/api/memory/answers/999999")).status_code == 404


@pytest.mark.asyncio
async def test_a_trace_event_can_be_addressed_and_displayed(app_client):
    """§2.4.3 makes Trace events "themselves subject to examination".

    MetaCat's Trace window makes them examinable by the user too: clicking one imposes
    the theme-pattern that was current when it happened and highlights its structures
    (`trace-graphics.ss:66-79` -> the `display` message every event answers). A log with
    no addressable events is the one thing the Trace display exists not to be.
    """
    create = await app_client.post(
        "/api/runs",
        json={"initial": "abc", "modified": "abd", "target": "xyz", "seed": 0},
    )
    run_id = create.json()["run_id"]
    await app_client.post(f"/api/runs/{run_id}/run", json={"max_steps": 3000})

    events = (await app_client.get(f"/api/runs/{run_id}/trace")).json()["events"]
    assert events, "the run recorded no trace events"
    number = events[0]["event_number"]

    detail = (await app_client.get(f"/api/runs/{run_id}/trace/{number}")).json()
    assert detail["event_number"] == number
    # The fields the display needs, which a bare log row does not carry.
    for field in ("structures", "theme_pattern", "strength", "temperature"):
        assert field in detail

    # Displaying it imposes over the live Themespace; displaying again restores.
    first = (await app_client.post(f"/api/runs/{run_id}/trace/{number}/display")).json()
    assert first["displaying"] == number
    second = (await app_client.post(f"/api/runs/{run_id}/trace/{number}/display")).json()
    assert second["displaying"] is None

    assert (await app_client.get(f"/api/runs/{run_id}/trace/999999")).status_code == 404


@pytest.mark.asyncio
async def test_the_trace_exports_as_a_downloadable_file(app_client):
    """`GET /trace/export` answers with the whole Trace and a download disposition.

    The literal ``export`` path is registered ahead of ``/{event_number}``, so it is the
    handler that runs. This asserts against the served application, which is the only
    place route ordering is observable.
    """
    create = await app_client.post(
        "/api/runs",
        json={"initial": "abc", "modified": "abd", "target": "xyz", "seed": 0},
    )
    run_id = create.json()["run_id"]
    await app_client.post(f"/api/runs/{run_id}/run", json={"max_steps": 1500})

    resp = await app_client.get(f"/api/runs/{run_id}/trace/export")

    assert resp.status_code == 200
    assert resp.headers["content-disposition"] == (
        f"attachment; filename=trace_run_{run_id}.json"
    )
    body = resp.json()
    assert body["run_id"] == run_id
    assert isinstance(body["events"], list)


@pytest.mark.asyncio
async def test_export_and_the_numbered_event_are_different_endpoints(app_client):
    """One literal path and one parameterised path sharing a prefix, both reachable.

    ``export`` returns the whole Trace as a download; a number returns that one event in
    full. Asserting both in one test keeps the pair's registration order honest.
    """
    create = await app_client.post(
        "/api/runs",
        json={"initial": "abc", "modified": "abd", "target": "xyz", "seed": 0},
    )
    run_id = create.json()["run_id"]
    await app_client.post(f"/api/runs/{run_id}/run", json={"max_steps": 1500})

    events = (await app_client.get(f"/api/runs/{run_id}/trace")).json()["events"]
    assert events, "the run recorded no trace events"
    number = events[0]["event_number"]

    export = await app_client.get(f"/api/runs/{run_id}/trace/export")
    numbered = await app_client.get(f"/api/runs/{run_id}/trace/{number}")

    assert export.status_code == 200
    assert numbered.status_code == 200
    assert "content-disposition" in export.headers
    assert "content-disposition" not in numbered.headers
    assert numbered.json()["event_number"] == number
    assert len(export.json()["events"]) >= 1


@pytest.mark.asyncio
async def test_a_stored_answer_can_be_displayed_over_the_live_themespace(app_client):
    """`memory.ss:268-283` — clicking an answer re-enters that episode.

    Its vertical, top and bottom theme-patterns are imposed together; §4.7.1 keeps the
    three apart because they characterise different halves of the analogy.
    """
    create = await app_client.post(
        "/api/runs",
        json={"initial": "abc", "modified": "abd", "target": "ijk", "seed": 5},
    )
    run_id = create.json()["run_id"]
    await app_client.post(f"/api/runs/{run_id}/run", json={"max_steps": 3000})

    answers = (await app_client.get("/api/memory")).json()["answers"]
    assert answers, "the run stored no answer to display"
    answer_id = answers[0]["answer_id"]

    shown = await app_client.post(
        f"/api/memory/answers/{answer_id}/display?run_id={run_id}"
    )
    assert shown.status_code == 200
    assert shown.json()["displaying"] == answer_id

    restored = await app_client.post(
        f"/api/memory/answers/{answer_id}/display?run_id={run_id}"
    )
    assert restored.json()["displaying"] is None


@pytest.mark.asyncio
async def test_two_answers_in_one_session_can_be_compared_and_explained(app_client):
    """§4.7.3 – §4.7.4: the program is asked to compare two answers it has found.

    Two runs sharing one Training Session share one Episodic Memory, which is the only
    way two answers ever end up comparable — "asking the program to compare two answers
    is accomplished simply by clicking on graphical icons associated with the answers"
    (§4.6).  Asserted here is the shape MetaCat's own output has: one paragraph, an
    opening that names the problem, and a verdict beginning "All in all" or "Overall,
    though" (``answers.ss:806-882``).

    ``explain`` (``answers.ss:310-333``) is the single-answer counterpart, and the two
    voices it returns differ only in their last sentence — the isomorphism §4.6
    describes at pp. 183-184.
    """
    await app_client.delete("/api/memory")

    for target, seed in (("ijk", 11), ("xyz", 12)):
        create = await app_client.post(
            "/api/runs",
            json={"initial": "abc", "modified": "abd", "target": target, "seed": seed},
        )
        run_id = create.json()["run_id"]
        await app_client.post(f"/api/runs/{run_id}/run", json={"max_steps": 4000})

    answers = (await app_client.get("/api/memory")).json()["answers"]
    assert len(answers) >= 2, "two runs stored fewer than two answers"
    first, second = answers[0]["answer_id"], answers[1]["answer_id"]

    resp = await app_client.post(
        "/api/memory/compare",
        json={"answer_id_1": first, "answer_id_2": second},
    )
    assert resp.status_code == 200
    commentary = resp.json()["commentary"]
    # Which opening MetaCat uses depends on what the two answers turn out to share
    # (``answers.ss:670-735``); either way the paragraph opens by naming an answer.
    assert commentary["text"].startswith(
        ("The answer ", "The only essential difference between the answer ")
    )
    assert commentary["verdict"].startswith(("All in all", "Overall, though"))
    # Footnote 16: comparison commentary is the same in either linguistic mode.
    assert commentary["eliza_text"] == commentary["technical_text"]

    explained = await app_client.get(f"/api/memory/answers/{first}/explanation")
    assert explained.status_code == 200
    body = explained.json()
    assert body["explanation"].startswith("This answer is based ")
    assert body["eliza_text"].startswith(body["explanation"])
    assert body["technical_text"].startswith(body["explanation"])
    assert body["eliza_text"] != body["technical_text"]
    assert body["text"] == body["technical_text"]

    eliza = await app_client.get(
        f"/api/memory/answers/{first}/explanation?eliza_mode=true"
    )
    assert eliza.json()["text"] == body["eliza_text"]

    assert (
        await app_client.get("/api/memory/answers/999999/explanation")
    ).status_code == 404
