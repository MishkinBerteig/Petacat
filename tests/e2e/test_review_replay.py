"""Review replays what the Run did (round 2, stage R).

The Audit inspector rebuilds a Run by re-executing it from its start capture.  It used to do
that under *today's* configuration and without what the person did to the live Run (a
clamp, an Undo, a threshold change), so it could present something that never happened.
These tests prove the replay is the Run.

The proof is a comparison at every codelet, over real HTTP.  While an Audit Run is live,
the test steps it one codelet at a time and, after each codelet (and after whatever the
person did at that codelet), reads the live views: Workspace, Slipnet, Coderack,
Themespace, EEG and temperature.  Afterwards it opens the inspector and steps it through
the same codelets, reading the same views from the replay.  The two must be equal at
every tick, not only at the end.

The cases cover each kind of action a person can take on a live Run, several in one
Run, each kind of edit to the global configuration made after the Run (a coefficient, a
node, a link, a codelet body, a posting rule, a reset to the Metacat Standard Configuration),
and a server restart between the Run and its review.  A configuration that cannot be
reconstructed makes the inspector refuse, and a replay that disagrees with the log says so.

Requires a local Postgres, as every e2e test does.
"""

from __future__ import annotations

import pytest

from tests.e2e.test_api_review import review_client  # noqa: F401  (fixture)

PROBLEM = {"initial": "abc", "modified": "abd", "target": "xyz"}
SEED = 5
TICKS = 220

VIEWS = ("workspace", "slipnet", "coderack", "themespace")


async def _live(client, run_id: int) -> dict:
    """The live Run's views, as the dashboard reads them."""
    out = {}
    for view in VIEWS:
        resp = await client.get(f"/api/runs/{run_id}/{view}")
        assert resp.status_code == 200, resp.text
        out[view] = resp.json()
    eeg = (await client.get(f"/api/runs/{run_id}/eeg")).json()
    eeg.pop("run_id", None)
    out["eeg"] = eeg
    out["temperature"] = (await client.get(f"/api/runs/{run_id}/temperature")).json()["temperature"]
    return out


def _replayed(state: dict) -> dict:
    return {view: state[view] for view in (*VIEWS, "eeg", "temperature")}


# ─── what a person can do to a live Run ─────────────────────────────────────


async def _a_theme(client, run_id):
    clusters = (await client.get(f"/api/runs/{run_id}/themespace")).json()["clusters"]
    cluster = clusters[0]
    return cluster["theme_type"], cluster["dimension"]


def post(path, body=None):
    async def act(client, run_id):
        resp = await client.post(f"/api/runs/{run_id}/{path}", json=body)
        assert resp.status_code == 200, (path, resp.text)

    return act


def put(path, body):
    async def act(client, run_id):
        resp = await client.put(f"/api/runs/{run_id}/{path}", json=body)
        assert resp.status_code == 200, (path, resp.text)

    return act


def delete(path, body=None):
    async def act(client, run_id):
        resp = await client.request("DELETE", f"/api/runs/{run_id}/{path}", json=body)
        assert resp.status_code == 200, (path, resp.text)

    return act


async def clamp_a_node(client, run_id):
    names = list((await client.get(f"/api/runs/{run_id}/slipnet")).json())
    resp = await client.post(
        f"/api/runs/{run_id}/clamp-node", json={"node_name": names[12], "cycles": 8}
    )
    assert resp.status_code == 200, resp.text


async def clamp_a_theme(client, run_id):
    theme_type, dimension = await _a_theme(client, run_id)
    resp = await client.post(
        f"/api/runs/{run_id}/clamp-themes",
        json={"themes": [{"type": theme_type, "dimension": dimension,
                          "relation": "successor", "activation": 100}]},
    )
    assert resp.status_code == 200, resp.text


async def clamp_a_theme_pattern(client, run_id):
    theme_type, dimension = await _a_theme(client, run_id)
    resp = await client.post(
        f"/api/runs/{run_id}/clamp-theme-pattern",
        json={"patterns": [{"type": theme_type,
                            "themes": [{"dimension": dimension, "relation": "identity",
                                        "activation": 100}]}]},
    )
    assert resp.status_code == 200, resp.text


async def impose_an_event(client, run_id):
    events = (await client.get(f"/api/runs/{run_id}/trace?limit=50")).json()["events"]
    resp = await client.post(f"/api/runs/{run_id}/trace/{events[-1]['event_number']}/display")
    assert resp.status_code == 200, resp.text


async def impose_an_answer(client, run_id):
    answers = (await client.get("/api/memory")).json()["answers"]
    resp = await client.post(
        f"/api/memory/answers/{answers[0]['answer_id']}/display?run_id={run_id}"
    )
    assert resp.status_code == 200, resp.text


async def impose_a_snag(client, run_id):
    snags = (await client.get("/api/memory")).json().get("snags") or []
    if not snags:
        pytest.skip("no snag in memory to impose")
    resp = await client.post(f"/api/memory/snags/{snags[0]['snag_id']}/display?run_id={run_id}")
    assert resp.status_code == 200, resp.text


ACTIONS = {
    "temperature_clamp": {40: post("clamp-temperature", {"value": 30, "cycles": 40}),
                          100: delete("clamp-temperature")},
    "node_clamp": {50: clamp_a_node},
    "theme_clamp": {60: clamp_a_theme, 120: delete("clamp-themes")},
    "theme_pattern_clamp": {60: clamp_a_theme_pattern, 140: post("undo-last-clamp")},
    "codelet_clamp": {50: post("clamp-codelets", {"codelet_type": "bond-builder", "urgency": 90}),
                      110: delete("clamp-codelets", {"codelet_type": "bond-builder"})},
    "codelet_pattern_clamp": {50: post("clamp-codelet-pattern", {"pattern": "bridge"}),
                              120: delete("clamp-codelet-pattern", {"pattern": "bridge"})},
    "undo": {30: post("clamp-codelet-pattern", {"pattern": "rule"}), 70: post("undo-last-clamp")},
    "self_watching": {45: put("self-watching", {"enabled": False}),
                      90: put("self-watching", {"enabled": True})},
    "spreading_threshold": {70: post("spreading-threshold", {"threshold": 60})},
    "impose_event": {80: impose_an_event, 110: post("themespace/restore")},
    "verbose_is_neutral": {20: put("verbose", {"enabled": True}),
                           60: put("verbose", {"enabled": False})},
    "several_in_one_run": {
        30: post("clamp-temperature", {"value": 25, "cycles": 30}),
        50: clamp_a_node,
        70: post("spreading-threshold", {"threshold": 70}),
        90: clamp_a_theme_pattern,
        90.5: post("clamp-codelet-pattern", {"pattern": "group"}),
        130: post("undo-last-clamp"),
        150: put("self-watching", {"enabled": False}),
        170: put("self-watching", {"enabled": True}),
        190: post("spreading-threshold", {"threshold": 100}),
    },
}


async def record_run(client, actions: dict | None = None, ticks: int = TICKS, problem=None) -> dict:
    """An Audit Run stepped one codelet at a time, with the live views read at every tick.

    ``actions`` maps a codelet count to what the person does once the Run has reached it.
    Returns the Run's id and its views at every tick.
    """
    actions = dict(actions or {})
    created = await client.post(
        "/api/runs", json={**(problem or PROBLEM), "seed": SEED, "mode": "audit"}
    )
    assert created.status_code == 200, created.text
    run_id = created.json()["run_id"]
    seen = {0: await _live(client, run_id)}
    for tick in range(1, ticks + 1):
        stepped = await client.post(f"/api/runs/{run_id}/step", json={"n": 1})
        assert stepped.status_code == 200, stepped.text
        results = stepped.json()
        if not results:
            break
        for at in sorted(k for k in actions if tick <= k < tick + 1):
            await actions.pop(at)(client, run_id)
        seen[tick] = await _live(client, run_id)
        if results[-1]["answer_found"] or results[-1]["gave_up"]:
            break
    return {"run_id": run_id, "views": seen}


async def replay_differences(client, recorded: dict) -> dict:
    """Open the inspector and compare its views with the live ones at every tick.

    Returns ``{"first": (tick, view) or None, "ticks": n, "state": last state}``.
    """
    run_id = recorded["run_id"]
    opened = await client.post(f"/api/review/runs/{run_id}/inspector")
    assert opened.status_code == 200, opened.text
    state = opened.json()
    first = None
    ticks = 0
    for tick in sorted(recorded["views"]):
        if tick:
            resp = await client.post(
                f"/api/review/runs/{run_id}/inspector/advance", json={"to_codelet": tick}
            )
            assert resp.status_code == 200, resp.text
            state = resp.json()
        assert state["codelet_count"] == tick
        ticks += 1
        mine, live = _replayed(state), recorded["views"][tick]
        for view in live:
            if mine[view] != live[view] and first is None:
                first = (tick, view)
    await client.delete(f"/api/review/runs/{run_id}/inspector")
    return {"first": first, "ticks": ticks, "state": state}


def _assert_the_replay_is_the_run(result: dict, recorded: dict) -> None:
    assert result["first"] is None, (
        f"the replay first differs from the live Run at tick {result['first']}"
    )
    assert result["ticks"] == len(recorded["views"]) > 100
    replay = result["state"]["replay"]
    assert replay["faithful"] is True, replay
    assert replay["first_difference"] is None


# ─── each kind of action ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_replay_with_no_action_and_no_edit_is_the_run(review_client):
    recorded = await record_run(review_client)
    _assert_the_replay_is_the_run(await replay_differences(review_client, recorded), recorded)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", sorted(ACTIONS))
async def test_a_replay_applies_what_the_person_did_at_the_same_codelet(review_client, case):
    recorded = await record_run(review_client, ACTIONS[case])
    result = await replay_differences(review_client, recorded)
    _assert_the_replay_is_the_run(result, recorded)
    applied = result["state"]["replay"]["interventions_applied"]
    # Verbose mode changes only what is narrated; it is not recorded, and the replay still matches.
    expected = 0 if case == "verbose_is_neutral" else len(ACTIONS[case])
    # The Step after the display puts the moment away itself and that is recorded too
    # (round 2, stage D), so the explicit restore at 110 is the third action.
    expected += 1 if case == "impose_event" else 0
    assert applied == expected, (applied, expected)


@pytest.mark.asyncio
async def test_a_displayed_event_that_a_step_puts_away_replays_at_every_tick(review_client):
    """A moment on show, then a Step with no click to put it back (round 2, stage D).

    The Step restores the live Themespace itself (Metacat's ``go``, ``run.ss:132``), through the
    recorded ``restore_themespace``, so the replay, which steps the engine and not the service,
    puts it back at the same codelet; a replay without that would show the displayed pattern
    where the run had the live one.
    """
    recorded = await record_run(review_client, {80: impose_an_event})
    result = await replay_differences(review_client, recorded)
    _assert_the_replay_is_the_run(result, recorded)
    # The display, and the restore the next Step made: two actions at codelet 80.
    assert result["state"]["replay"]["interventions_applied"] == 2


@pytest.mark.asyncio
async def test_an_imposed_answer_replays_even_after_the_memory_is_cleared(review_client):
    done = await review_client.post(
        "/api/runs", json={**PROBLEM, "target": "ijk", "seed": 3, "mode": "fast"}
    )
    await review_client.post(f"/api/runs/{done.json()['run_id']}/run", json={"max_steps": 3000})
    assert (await review_client.get("/api/memory")).json()["answers"], "needs an answer in memory"
    recorded = await record_run(
        review_client, {60: impose_an_answer, 100: post("themespace/restore")}
    )
    cleared = await review_client.delete("/api/memory")
    assert cleared.status_code == 200, cleared.text
    _assert_the_replay_is_the_run(await replay_differences(review_client, recorded), recorded)


@pytest.mark.asyncio
async def test_a_reset_after_a_threshold_change_replays_the_threshold(review_client):
    created = await review_client.post(
        "/api/runs", json={**PROBLEM, "seed": SEED, "mode": "audit"}
    )
    run_id = created.json()["run_id"]
    await review_client.post(f"/api/runs/{run_id}/step", json={"n": 20})
    await review_client.post(f"/api/runs/{run_id}/spreading-threshold", json={"threshold": 55})
    reset = await review_client.post(f"/api/runs/{run_id}/reset")
    assert reset.status_code == 200, reset.text
    views = {0: await _live(review_client, run_id)}
    for tick in range(1, 160):
        await review_client.post(f"/api/runs/{run_id}/step", json={"n": 1})
        views[tick] = await _live(review_client, run_id)
    recorded = {"run_id": run_id, "views": views}
    _assert_the_replay_is_the_run(await replay_differences(review_client, recorded), recorded)


@pytest.mark.asyncio
async def test_a_run_paused_with_run_and_continued_replays(review_client):
    """``POST /run`` ends in ``finish``, which hands the sink the trace events seen so far;
    where that falls is recorded and replayed."""
    created = await review_client.post(
        "/api/runs", json={**PROBLEM, "seed": SEED, "mode": "audit"}
    )
    run_id = created.json()["run_id"]
    views = {0: await _live(review_client, run_id)}
    await review_client.post(f"/api/runs/{run_id}/run", json={"max_steps": 90})
    for tick in range(91, 160):
        await review_client.post(f"/api/runs/{run_id}/step", json={"n": 1})
        views[tick] = await _live(review_client, run_id)
    # Only the ticks stepped one at a time have live views to compare with.
    recorded = {"run_id": run_id, "views": views}
    opened = await review_client.post(f"/api/review/runs/{run_id}/inspector")
    assert opened.status_code == 200
    for tick in sorted(views):
        if not tick:
            continue
        state = (
            await review_client.post(
                f"/api/review/runs/{run_id}/inspector/advance", json={"to_codelet": tick}
            )
        ).json()
        assert _replayed(state) == views[tick], tick
    assert state["replay"]["faithful"] is True, state["replay"]


# ─── each kind of edit to the configuration after the Run ───────────────────


async def _edit_a_coefficient(client):
    resp = await client.put("/api/admin/formula-coefficients/rule_factor_weight", json={"value": "20"})
    assert resp.status_code == 200, resp.text


async def _edit_a_node(client):
    nodes = (await client.get("/api/admin/slipnet/nodes")).json()
    node = next(n for n in nodes if n["name"] == "plato-successor") if any(
        n["name"] == "plato-successor" for n in nodes) else nodes[10]
    body = {k: node[k] for k in ("name", "short_name", "description", "descriptor_predicate")}
    body["conceptual_depth"] = max(1, int(node["conceptual_depth"]) - 20)
    resp = await client.put(f"/api/admin/slipnet/nodes/{node['name']}", json=body)
    assert resp.status_code == 200, resp.text


async def _edit_every_node(client):
    for node in (await client.get("/api/admin/slipnet/nodes")).json():
        body = {k: node[k] for k in ("name", "short_name", "description", "descriptor_predicate")}
        body["conceptual_depth"] = int(node["conceptual_depth"]) // 2 + 1
        resp = await client.put(f"/api/admin/slipnet/nodes/{node['name']}", json=body)
        assert resp.status_code == 200, resp.text


async def _edit_links(client):
    for link in (await client.get("/api/admin/slipnet/links")).json():
        if link["link_length"] is None:
            continue
        body = {k: link[k] for k in ("from_node", "to_node", "link_type", "label_node",
                                      "fixed_length")}
        body["link_length"] = max(1, int(link["link_length"]) // 2)
        resp = await client.put(f"/api/admin/slipnet/links/{link['id']}", json=body)
        assert resp.status_code == 200, resp.text


async def _edit_a_codelet_body(client):
    codelets = (await client.get("/api/admin/codelets")).json()
    codelet = next(c for c in codelets if c["name"] == "bond-evaluator")
    body = {k: codelet[k] for k in ("name", "family", "phase", "description", "source_file",
                                     "source_line")}
    body["execute_body"] = ""
    resp = await client.put(f"/api/admin/codelets/{codelet['name']}", json=body)
    assert resp.status_code == 200, resp.text


async def _edit_a_theme_dimension(client):
    dims = (await client.get("/api/admin/theme-dimensions")).json()
    dim = dims[0]
    body = {k: dim[k] for k in dim if k != "id"}
    body["valid_relations"] = ["identity"]
    resp = await client.put(f"/api/admin/theme-dimensions/{dim['id']}", json=body)
    assert resp.status_code == 200, resp.text


async def _edit_the_posting_rules(client):
    levels = {l["name"]: l["value"] for l in (await client.get("/api/admin/urgency-levels")).json()}
    for rule in (await client.get("/api/admin/posting-rules")).json():
        body = {k: rule[k] for k in ("codelet_type", "direction", "urgency_level",
                                      "urgency_formula", "posting_formula", "count_formula",
                                      "count_values", "condition", "triggering_slipnodes")}
        body["urgency_level"] = "very_high" if body["urgency_level"] != "very_high" else "low"
        assert body["urgency_level"] in levels
        resp = await client.put(f"/api/admin/posting-rules/{rule['id']}", json=body)
        assert resp.status_code == 200, resp.text


async def _reset_to_standard(client):
    resp = await client.post(
        "/api/configurations/1/reset-to-standard",
        json={"confirm": _confirmation(), "note": "test"},
    )
    assert resp.status_code == 200, resp.text


def _confirmation() -> str:
    from server.api.configurations import RESET_CONFIRMATION

    return RESET_CONFIRMATION


EDITS = {
    "coefficient": _edit_a_coefficient,
    "node": _edit_a_node,
    "every_node": _edit_every_node,
    "links": _edit_links,
    "codelet_body": _edit_a_codelet_body,
    "posting_rules": _edit_the_posting_rules,
    "theme_dimension": _edit_a_theme_dimension,
}


@pytest.mark.asyncio
@pytest.mark.parametrize("edit", sorted(EDITS))
async def test_a_replay_runs_under_the_configuration_the_run_used(review_client, edit):
    recorded = await record_run(review_client, ACTIONS["temperature_clamp"])
    await EDITS[edit](review_client)
    result = await replay_differences(review_client, recorded)
    _assert_the_replay_is_the_run(result, recorded)
    configuration = result["state"]["replay"]["configuration"]
    assert configuration["faithful"] is True
    assert configuration["edited_since"] is True


@pytest.mark.asyncio
async def test_a_replay_survives_an_import_that_edited_and_restored_a_theme_dimension(review_client):
    """A table that declares no order is read in the order its rows were inserted, and the
    configuration hash covers that order.  Importing an edit to its first row and then the
    original moves that row in the database; reconstructing the configuration from the journal
    must still give the order the Run used (it once put the updated row last)."""
    original = (await review_client.get("/api/admin/export")).json()
    edited = {**original, "theme_dimensions": [dict(r) for r in original["theme_dimensions"]]}
    edited["theme_dimensions"][0]["valid_relations"] = ["identity"]
    assert (await review_client.post("/api/admin/import", json=edited)).status_code == 200
    assert (await review_client.post("/api/admin/import", json=original)).status_code == 200
    recorded = await record_run(review_client, ACTIONS["node_clamp"])
    await _edit_a_coefficient(review_client)
    await _edit_a_theme_dimension(review_client)
    _assert_the_replay_is_the_run(await replay_differences(review_client, recorded), recorded)


@pytest.mark.asyncio
async def test_a_run_under_an_edited_configuration_replays_after_a_reset_to_standard(review_client):
    await _edit_a_coefficient(review_client)
    await _edit_a_node(review_client)
    recorded = await record_run(review_client, ACTIONS["several_in_one_run"])
    await _reset_to_standard(review_client)
    result = await replay_differences(review_client, recorded)
    _assert_the_replay_is_the_run(result, recorded)
    assert result["state"]["replay"]["configuration"]["edited_since"] is True


@pytest.mark.asyncio
async def test_a_run_made_after_an_edit_replays_under_the_edit_and_after_its_reversal(review_client):
    await _edit_a_coefficient(review_client)
    recorded = await record_run(review_client, ACTIONS["several_in_one_run"])
    await review_client.put(
        "/api/admin/formula-coefficients/rule_factor_weight", json={"value": "30"}
    )
    await _edit_every_node(review_client)
    result = await replay_differences(review_client, recorded)
    _assert_the_replay_is_the_run(result, recorded)


@pytest.mark.asyncio
async def test_runs_under_different_configurations_each_replay_under_their_own(review_client):
    first = await record_run(review_client, ACTIONS["node_clamp"])
    await _edit_a_coefficient(review_client)
    second = await record_run(review_client, ACTIONS["theme_pattern_clamp"])
    await _edit_a_codelet_body(review_client)
    for recorded in (first, second):
        _assert_the_replay_is_the_run(await replay_differences(review_client, recorded), recorded)


# ─── a server restart between the Run and its review ────────────────────────


async def _restart_the_server(client, test_engine) -> None:
    """What a restart leaves: a configuration store rebuilt from the database, a new run
    service holding no run, no open inspection, and an Episodic Memory read back from the
    database."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from server.api import review as review_module
    from server.api import runs as runs_module
    from server.services.configuration_store import (
        ConfigurationStore,
        read_revision,
        set_configuration_store,
    )
    from server.services.metadata_service import load_metadata_from_db
    from server.services.review_service import ReviewService
    from server.services.run_service import RunService, _global_memory

    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        store = ConfigurationStore(await load_metadata_from_db(session), await read_revision(session))
    set_configuration_store(store)
    runs_module._run_service = RunService(store)
    review_module._review_service = ReviewService(store)
    _global_memory.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("edit_first", [False, True])
async def test_a_replay_survives_a_server_restart(review_client, test_engine, edit_first):
    recorded = await record_run(review_client, ACTIONS["several_in_one_run"])
    if edit_first:
        await _edit_a_coefficient(review_client)
    await _restart_the_server(review_client, test_engine)
    _assert_the_replay_is_the_run(await replay_differences(review_client, recorded), recorded)


# ─── when the Run cannot be replayed faithfully ─────────────────────────────


@pytest.mark.asyncio
async def test_a_run_whose_configuration_was_changed_outside_the_journal_is_refused(
    review_client, test_engine
):
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    recorded = await record_run(review_client, None, ticks=60)
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        # Behind the journal's back: no revision, no before-image.
        await session.execute(
            text("UPDATE formula_coefficients SET value = '20.0' WHERE name = 'rule_factor_weight'")
        )
        await session.commit()
    await _restart_the_server(review_client, test_engine)
    # A second edit through the journal moves the revision on, so the Run's revision is
    # now reconstructed from before-images that do not know about the first one.
    await _edit_a_node(review_client)
    refused = await review_client.post(f"/api/review/runs/{recorded['run_id']}/inspector")
    assert refused.status_code == 422, refused.text
    assert "cannot be replayed faithfully" in refused.text
    assert "recorded actions and captures are still available" in refused.text


@pytest.mark.asyncio
async def test_a_run_with_no_recorded_revision_is_refused(review_client, db_session):
    from sqlalchemy import update

    from server.models.run import Run

    recorded = await record_run(review_client, None, ticks=40)
    await db_session.execute(
        update(Run).where(Run.id == recorded["run_id"]).values(configuration_revision=None)
    )
    await db_session.commit()
    refused = await review_client.post(f"/api/review/runs/{recorded['run_id']}/inspector")
    assert refused.status_code == 422
    assert "configuration revision" in refused.text


@pytest.mark.asyncio
async def test_a_replay_that_disagrees_with_the_log_says_so(review_client, db_session):
    """If anything the replay produces differs from what the Run recorded, the inspector
    reports the first difference and ``faithful`` turns false and stays false."""
    from sqlalchemy import select

    from server.models.run import AuditAction

    recorded = await record_run(review_client, None, ticks=80)
    run_id = recorded["run_id"]
    row = (
        await db_session.execute(
            select(AuditAction).where(
                AuditAction.run_id == run_id,
                AuditAction.action_type == "codelet",
                AuditAction.codelet_count == 30,
            )
        )
    ).scalars().first()
    row.payload = {**row.payload, "codelet_type": "not-the-codelet-that-ran"}
    await db_session.commit()

    await review_client.post(f"/api/review/runs/{run_id}/inspector")
    early = (
        await review_client.post(
            f"/api/review/runs/{run_id}/inspector/advance", json={"to_codelet": 29}
        )
    ).json()
    assert early["replay"]["faithful"] is True
    late = (
        await review_client.post(
            f"/api/review/runs/{run_id}/inspector/advance", json={"to_codelet": 60}
        )
    ).json()
    assert late["replay"]["faithful"] is False
    assert late["replay"]["first_difference"]["tick"] == 30
    assert "not-the-codelet-that-ran" in str(late["replay"]["first_difference"]["recorded"])


# ─── the other review surfaces, and the other modes ─────────────────────────


@pytest.mark.asyncio
async def test_a_capture_is_projected_under_the_configuration_the_run_used(review_client):
    created = await review_client.post(
        "/api/runs", json={**PROBLEM, "seed": SEED, "mode": "normal"}
    )
    run_id = created.json()["run_id"]
    await review_client.post(f"/api/runs/{run_id}/run", json={"max_steps": 60})
    await _edit_a_coefficient(review_client)
    capture = (await review_client.get(f"/api/review/runs/{run_id}/captures/end")).json()
    assert capture["configuration"]["faithful"] is True
    assert capture["configuration"]["edited_since"] is True
    comparison = (await review_client.get(f"/api/review/runs/{run_id}/comparison")).json()
    assert comparison["configuration"]["revision"] == capture["configuration"]["revision"]


@pytest.mark.asyncio
async def test_only_an_audit_run_can_open_an_inspector(review_client):
    for mode in ("normal", "fast"):
        created = await review_client.post(
            "/api/runs", json={**PROBLEM, "seed": SEED, "mode": mode}
        )
        run_id = created.json()["run_id"]
        await review_client.post(f"/api/runs/{run_id}/run", json={"max_steps": 40})
        refused = await review_client.post(f"/api/review/runs/{run_id}/inspector")
        assert refused.status_code == 404, (mode, refused.text)


@pytest.mark.asyncio
async def test_recording_what_a_person_did_belongs_to_audit_only(review_client, db_session):
    from sqlalchemy import func, select

    from server.models.run import AuditAction

    created = await review_client.post(
        "/api/runs", json={**PROBLEM, "seed": SEED, "mode": "normal"}
    )
    run_id = created.json()["run_id"]
    await review_client.post(f"/api/runs/{run_id}/step", json={"n": 5})
    await review_client.post(f"/api/runs/{run_id}/clamp-temperature", json={"value": 30})
    await review_client.post(f"/api/runs/{run_id}/step", json={"n": 5})
    total = (
        await db_session.execute(
            select(func.count()).select_from(AuditAction).where(AuditAction.run_id == run_id)
        )
    ).scalar()
    assert total == 0

    audit = await record_run(review_client, {10: post("clamp-temperature", {"value": 30})}, ticks=20)
    kinds = (
        await db_session.execute(
            select(AuditAction.payload).where(
                AuditAction.run_id == audit["run_id"], AuditAction.action_type == "intervention"
            )
        )
    ).scalars().all()
    assert [k["method"] for k in kinds] == ["clamp_temperature"]
    assert kinds[0]["args"] == {"value": 30, "cycles": 0}
