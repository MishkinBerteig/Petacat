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
    assert len(data) == 16
    names = {v["name"] for v in data}
    assert "bond_built" in names
    assert "snag" in names


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
