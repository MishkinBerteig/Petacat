"""E2E tests for the help topics API.

Validates that:
1. GET /api/docs/components/{key} returns 200 for every component topic in the JSON.
2. GET /api/docs/glossary/{term} returns 200 for every glossary topic in the JSON.
3. GET /api/docs/glossary returns all glossary entries.
4. Unknown keys return 404.

These tests exercise the full SSOT path: JSON file → DB (via idempotent upsert
at startup) → API → response. Requires the backend to have been started with
the current help_topics.en.json.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SEED_DIR = REPO_ROOT / "seed_data"


def _load_topics() -> list[dict]:
    path = SEED_DIR / "help_topics.en.json"
    if not path.exists():
        path = SEED_DIR / "help_topics.json"
    with path.open() as f:
        return json.load(f)


@pytest.mark.asyncio
async def test_every_component_is_fetchable(app_client):
    """Every topic_type='component' in the JSON must be served by the API."""
    topics = _load_topics()
    component_keys = [t["topic_key"] for t in topics if t["topic_type"] == "component"]
    assert len(component_keys) > 0, "No components in help_topics.en.json"

    for key in component_keys:
        resp = await app_client.get(f"/api/docs/components/{key}")
        assert resp.status_code == 200, (
            f"GET /api/docs/components/{key} returned {resp.status_code}. "
            f"Body: {resp.text[:200]}"
        )
        data = resp.json()
        assert data["topic_key"] == key
        assert data["name"]
        # At least one of the descriptions must be non-empty
        assert data["short_desc"] or data["description"]


@pytest.mark.asyncio
async def test_every_glossary_term_is_fetchable(app_client):
    """Every topic_type='glossary' in the JSON must be served by the API."""
    topics = _load_topics()
    glossary_keys = [t["topic_key"] for t in topics if t["topic_type"] == "glossary"]
    assert len(glossary_keys) > 0, "No glossary entries in help_topics.en.json"

    for key in glossary_keys:
        resp = await app_client.get(f"/api/docs/glossary/{key}")
        assert resp.status_code == 200, (
            f"GET /api/docs/glossary/{key} returned {resp.status_code}"
        )
        data = resp.json()
        assert data["term"] == key


@pytest.mark.asyncio
async def test_glossary_list_matches_json(app_client):
    """GET /api/docs/glossary should list every glossary term from the JSON."""
    topics = _load_topics()
    expected_keys = {
        t["topic_key"] for t in topics if t["topic_type"] == "glossary"
    }

    resp = await app_client.get("/api/docs/glossary")
    assert resp.status_code == 200
    data = resp.json()
    actual_keys = {item["term"] for item in data}

    missing = expected_keys - actual_keys
    assert not missing, (
        f"Glossary API is missing terms from JSON: {sorted(missing)}"
    )


@pytest.mark.asyncio
async def test_unknown_component_returns_404(app_client):
    resp = await app_client.get("/api/docs/components/this_does_not_exist")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_unknown_glossary_returns_404(app_client):
    resp = await app_client.get("/api/docs/glossary/this_does_not_exist")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_component_key_normalization(app_client):
    """Component lookups should normalize hyphens and spaces to underscores."""
    # The JSON key is `problem_input`; try variant spellings
    for variant in ["problem_input", "problem-input", "Problem Input"]:
        resp = await app_client.get(f"/api/docs/components/{variant}")
        assert resp.status_code == 200, f"variant '{variant}' failed"
        assert resp.json()["topic_key"] == "problem_input"


@pytest.mark.asyncio
async def test_component_response_includes_metadata(app_client):
    """The component API must return the metadata object from the JSON."""
    resp = await app_client.get("/api/docs/components/workspace")
    assert resp.status_code == 200
    data = resp.json()
    assert "metadata" in data
    # workspace topic has key_concepts metadata
    assert isinstance(data["metadata"], dict)
