"""The display data the Metacat windows need: coderack, EEG, themespace names."""

import pytest

SEED = 4242


async def _new_run(app_client, steps=0):
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
    })
    run_id = resp.json()["run_id"]
    if steps:
        await app_client.post(f"/api/runs/{run_id}/step", json={"n": steps})
    return run_id


@pytest.mark.asyncio
async def test_coderack_serves_probabilities_and_the_last_codelet_type(app_client):
    run_id = await _new_run(app_client, steps=30)
    data = (await app_client.get(f"/api/runs/{run_id}/coderack")).json()
    assert data["last_codelet_type"] in data["codelet_types"]
    assert sum(data["type_probabilities"].values()) == pytest.approx(1.0)
    assert set(data["type_probabilities"]) <= set(data["type_counts"])
    assert data["clamped_urgencies"] == {}


@pytest.mark.asyncio
async def test_coderack_before_any_step_has_no_last_codelet_type(app_client):
    run_id = await _new_run(app_client)
    data = (await app_client.get(f"/api/runs/{run_id}/coderack")).json()
    assert data["last_codelet_type"] is None


@pytest.mark.asyncio
async def test_eeg_endpoint_serves_one_sample_per_update_cycle(app_client):
    run_id = await _new_run(app_client, steps=47)
    resp = await app_client.get(f"/api/runs/{run_id}/eeg")
    assert resp.status_code == 200
    data = resp.json()
    assert [s["key"] for s in data["series"]] == ["average_activity", "temperature"]
    assert data["initial_value"] == 100
    # 47 codelets cross the 15-codelet cycle boundary three times.
    assert [s["codelet_count"] for s in data["samples"]] == [15, 30, 45]
    temperature = (await app_client.get(f"/api/runs/{run_id}/temperature")).json()
    assert 0 <= temperature["temperature"] <= 100


@pytest.mark.asyncio
async def test_eeg_of_an_unknown_run_is_404(app_client):
    assert (await app_client.get("/api/runs/99999/eeg")).status_code == 404


@pytest.mark.asyncio
async def test_themespace_carries_metacats_dimension_and_relation_names(app_client):
    run_id = await _new_run(app_client)
    data = (await app_client.get(f"/api/runs/{run_id}/themespace")).json()
    labels = data["dimension_labels"]
    assert labels["plato-letter-category"] == {
        "name": "Letter Category", "abbreviation": "Letter Ctgy.",
    }
    assert labels["plato-alphabetic-position-category"]["abbreviation"] == "Alpha. Pos."
    assert labels["plato-string-position-category"]["name"] == "String Position"
    assert labels["plato-group-category"]["name"] == "Group Type"
    assert labels["plato-object-category"]["name"] == "Object Type"
    assert labels["plato-bond-category"]["name"] == "Bond Type"
    assert data["relation_labels"] == {
        "identity": "iden", "opposite": "opp", "successor": "succ",
        "predecessor": "pred", "diff": "diff",
    }
    for cluster in data["clusters"]:
        assert cluster["dimension"] in labels
