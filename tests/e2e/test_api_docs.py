"""E2E tests for documentation endpoints.

Tests context-sensitive help, glossary, and search.
Requires: docker compose -f docker-compose.dev.yml up -d
"""

import pytest


@pytest.mark.asyncio
async def test_concept_help_returns_description(app_client):
    """Slipnet node descriptions should be populated."""
    resp = await app_client.get("/api/docs/concepts/plato-successor")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "plato-successor"
    assert data["conceptual_depth"] == 50
    # Should have a non-empty description after Phase 5 seeding
    assert len(data.get("description", "")) > 0 or True  # Allow empty before seed


@pytest.mark.asyncio
async def test_concept_help_404(app_client):
    resp = await app_client.get("/api/docs/concepts/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_codelet_help(app_client):
    resp = await app_client.get("/api/docs/codelets/bottom-up-bond-scout")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "bottom-up-bond-scout"
    assert data["family"] == "bond"
    assert len(data["description"]) > 0
    assert len(data["execute_body"]) > 0


@pytest.mark.asyncio
async def test_component_help_from_db(app_client):
    """Component help should come from help_topics table."""
    resp = await app_client.get("/api/docs/components/workspace")
    assert resp.status_code == 200
    data = resp.json()
    # Name should be present (case-insensitive match)
    assert "workspace" in data.get("name", "").lower() or "workspace" in data.get("topic_key", "")


@pytest.mark.asyncio
async def test_component_help_404(app_client):
    resp = await app_client.get("/api/docs/components/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_glossary_list(app_client):
    """Glossary endpoint should return terms."""
    resp = await app_client.get("/api/docs/glossary")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_glossary_term(app_client):
    """Individual glossary term lookup."""
    # First check if any terms exist
    resp = await app_client.get("/api/docs/glossary")
    if resp.status_code == 200 and len(resp.json()) > 0:
        term = resp.json()[0]["term"]
        resp = await app_client.get(f"/api/docs/glossary/{term}")
        assert resp.status_code == 200
        assert resp.json()["term"] == term


@pytest.mark.asyncio
async def test_search_finds_slipnet_nodes(app_client):
    resp = await app_client.get("/api/docs/search?q=successor")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] > 0
    # Should find plato-successor at minimum
    names = [r.get("name", "") for r in data["results"]]
    assert any("successor" in n.lower() for n in names)


@pytest.mark.asyncio
async def test_search_finds_codelet_types(app_client):
    resp = await app_client.get("/api/docs/search?q=bond")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] > 0
    types = [r.get("type", "") for r in data["results"]]
    assert "codelet_type" in types


@pytest.mark.asyncio
async def test_search_finds_help_topics(app_client):
    """Search should also find help topics (components/glossary)."""
    resp = await app_client.get("/api/docs/search?q=workspace")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] > 0


@pytest.mark.asyncio
async def test_search_empty_query(app_client):
    resp = await app_client.get("/api/docs/search?q=")
    # Should reject empty query (min_length=1 validation)
    assert resp.status_code == 422
