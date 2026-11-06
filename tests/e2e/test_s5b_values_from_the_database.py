"""Stage 5, group B: the services and the API read the database, not a number of their own.

Each test changes one configuration value through the Admin API and shows the route follows
it, so a default that went back to a literal in the route would fail:

* the spreading-threshold clip is ``max_activation`` (rulings 1 and 25);
* a theme clamp that states no activation takes ``max_theme_activation`` (ruling 25);
* the run-parameter catalogue serves ``max_theme_activation`` (the Themespace window reads it);
* bulk work has one default run length, ``default_max_codelets`` (ruling 26): the Swarm and a
  Training Mode Session's creation take it, and the Swarm's status serves it to the client;
* a slipnet link states ``fixed_length`` and a posting rule states its ``posting_formula``,
  ``count_formula`` and ``condition`` (ruling 27).
"""

import pytest

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from server.services import training_mode_session_service as bs
from server.services.training_mode_session_executor import create_executor

SEED = 4242


async def _set_param(client, name: str, value, value_type: str = "int") -> None:
    resp = await client.put(
        f"/api/admin/params/{name}", json={"value": str(value), "value_type": value_type}
    )
    assert resp.status_code == 200, resp.text


async def _catalogue(client) -> dict:
    body = (await client.get("/api/runs/parameters/catalogue")).json()
    return {s["name"]: s for s in body["parameters"]}


@pytest.mark.asyncio
async def test_the_spreading_threshold_is_clipped_to_the_configured_activation_ceiling(app_client):
    await _set_param(app_client, "max_activation", 80)
    try:
        created = await app_client.post("/api/runs", json={
            "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
            "spreading_threshold": 95,
        })
        assert created.status_code == 200, created.text
        assert created.json()["spreading_threshold"] == 80
        run_id = created.json()["run_id"]
        moved = await app_client.post(
            f"/api/runs/{run_id}/spreading-threshold", json={"threshold": 90}
        )
        assert moved.status_code == 200, moved.text
        assert moved.json()["spreading_activation_threshold"] == 80
    finally:
        await _set_param(app_client, "max_activation", 100)
    created = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
        "spreading_threshold": 95,
    })
    assert created.json()["spreading_threshold"] == 95


@pytest.mark.asyncio
async def test_a_run_made_with_no_threshold_takes_the_configurations(app_client):
    await _set_param(app_client, "spreading_activation_threshold", 60)
    try:
        created = await app_client.post("/api/runs", json={
            "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
        })
        assert created.json()["spreading_threshold"] == 60
    finally:
        await _set_param(app_client, "spreading_activation_threshold", 100)


@pytest.mark.asyncio
async def test_a_theme_clamp_that_states_no_activation_takes_the_configured_ceiling(app_client):
    await _set_param(app_client, "max_theme_activation", 70)
    try:
        run_id = (await app_client.post("/api/runs", json={
            "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED,
        })).json()["run_id"]
        resp = await app_client.post(f"/api/runs/{run_id}/clamp-themes", json={
            "themes": [{
                "type": "top_bridge", "dimension": "plato-direction-category",
                "relation": "identity",
            }],
        })
        assert resp.status_code == 200, resp.text
        activations = {t["activation"] for t in resp.json()["clamped_themes"]}
        assert 70.0 in activations
    finally:
        await _set_param(app_client, "max_theme_activation", 100)


@pytest.mark.asyncio
async def test_the_catalogue_serves_the_theme_ceiling_and_the_activation_ceiling(app_client):
    specs = await _catalogue(app_client)
    assert specs["max_theme_activation"]["default"] == 100
    assert specs["max_activation"]["default"] == 100
    assert specs["spreading_activation_threshold"]["default"] == 100
    await _set_param(app_client, "max_theme_activation", 150)
    try:
        specs = await _catalogue(app_client)
        assert specs["max_theme_activation"]["default"] == 150
    finally:
        await _set_param(app_client, "max_theme_activation", 100)


@pytest.mark.asyncio
async def test_the_swarm_and_its_status_take_the_one_bulk_default_run_length(app_client):
    from server.parallel.swarm import shutdown_default

    try:
        status = (await app_client.get("/api/swarm")).json()
        assert status["limits"]["default_max_codelets"] == 20000
        await _set_param(app_client, "default_max_codelets", 40)
        status = (await app_client.get("/api/swarm")).json()
        assert status["limits"]["default_max_codelets"] == 40
        resp = await app_client.post("/api/swarm", json={
            "initial": "abc", "modified": "abd", "target": "ijk", "seeds": [1, 2],
            "backend": "numpy",
        })
        assert resp.status_code == 200, resp.text
        assert all(r["codelets"] <= 40 for r in resp.json()["runs"])
        explicit = await app_client.post("/api/swarm", json={
            "initial": "abc", "modified": "abd", "target": "ijk", "seeds": [1, 2],
            "backend": "numpy", "max_steps": 3000,
        })
        assert any(r["codelets"] > 40 for r in explicit.json()["runs"])
    finally:
        await _set_param(app_client, "default_max_codelets", 20000)
        shutdown_default()


@pytest.fixture
async def live_sessions(app_client, test_engine):
    """A session service on the test database whose configuration is the run service's *current*
    one, as the application's is: an edit made through the Admin API reaches it."""
    from server.api.runs import get_run_service

    async with test_engine.begin() as conn:
        await conn.execute(text("DELETE FROM training_mode_sessions"))
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    service = bs.TrainingModeSessionService(
        factory, lambda: get_run_service().meta, executor=create_executor()
    )
    await service.start()
    bs.set_training_mode_session_service(service)
    yield service
    bs.set_training_mode_session_service(None)
    await service.stop()


@pytest.mark.asyncio
async def test_a_session_created_with_no_max_codelets_takes_the_configured_default(
    app_client, live_sessions
):
    top = (await app_client.get("/api/training-mode/sessions")).json()
    assert top["defaults"]["settings"]["max_codelets"] == 20000
    await _set_param(app_client, "default_max_codelets", 1234)
    try:
        top = (await app_client.get("/api/training-mode/sessions")).json()
        assert top["defaults"]["settings"]["max_codelets"] == 1234
        made = (await app_client.post("/api/training-mode/sessions", json={"name": "bare"})).json()
        assert made["session"]["settings"]["max_codelets"] == 1234
    finally:
        await _set_param(app_client, "default_max_codelets", 20000)


@pytest.mark.asyncio
async def test_a_slipnet_link_must_state_fixed_length(app_client):
    resp = await app_client.post("/api/admin/slipnet/links", json={
        "from_node": "plato-a", "to_node": "plato-c", "link_type": "lateral",
        "label_node": None, "link_length": 50,
    })
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["posting_formula", "count_formula", "condition"])
async def test_a_posting_rule_must_state_what_it_posts_with(app_client, missing):
    body = {"codelet_type": "smoke-test-scout", "direction": "bottom_up",
            "urgency_level": "extremely_low", "posting_formula": "temperature / 100",
            "count_formula": "fixed", "count_values": {"fixed": 1}, "condition": "always"}
    del body[missing]
    resp = await app_client.post("/api/admin/posting-rules", json=body)
    assert resp.status_code == 422, resp.text
