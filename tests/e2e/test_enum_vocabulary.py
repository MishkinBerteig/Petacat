"""E2E (stage 4, F-change-api): the Admin enum editor over the engine's vocabulary.

The role column is a pick from the engine's role list for the table; setting a role is checked
(a name of the table's vocabulary, held by no other row); a bound row cannot be deleted
(``422 role_bound``); a rename is the change API's ``rename_enum_value`` and rewrites every
column that names the row.  Every test that writes ends by resetting the global configuration
to the Metacat Standard Configuration.
"""

import pytest

from server.engine.roles import LINK_BEHAVIOURS, VOCABULARY
from tests.e2e.test_change_api_endpoints import made  # noqa: F401  (a Stopped session's configuration)
from server.services.config_registry import ENUM_REGISTRY


async def _reset(app_client):
    resp = await app_client.post("/api/configurations/1/reset-to-standard", json={"confirm": "reset"})
    assert resp.status_code == 200, resp.text


@pytest.fixture
async def clean(app_client):
    await _reset(app_client)
    yield app_client
    await _reset(app_client)


async def _rows(client, table) -> dict[str, dict]:
    resp = await client.get(f"/api/admin/enums/{table}")
    assert resp.status_code == 200, resp.text
    return {r["name"]: r for r in resp.json()}


@pytest.mark.asyncio
async def test_the_list_endpoint_returns_the_available_roles_per_table(app_client):
    data = (await app_client.get("/api/admin/enums")).json()
    assert sorted(data["tables"]) == sorted(ENUM_REGISTRY)
    roles = data["roles"]
    for table, entry in roles.items():
        if table == "link_types":
            assert entry == {"column": "behaviour", "roles": list(LINK_BEHAVIOURS), "unique": False}
        elif table in ENUM_REGISTRY:
            assert entry["column"] == "role" and entry["unique"]
            assert entry["roles"] == [s.name for s in VOCABULARY if s.table == table]
    assert roles["bridge_types"]["roles"] == ["bridge_type.top", "bridge_type.bottom", "bridge_type.vertical"]
    assert "run_statuses" not in roles  # the engine names none of its rows
    extra = {t: [c["name"] for c in cols] for t, cols in data["columns"].items()}
    assert extra["bridge_types"] == ["role"]
    assert extra["link_types"] == ["behaviour"]
    assert extra["codelet_families"] == ["serialised"]
    assert extra["progress_focuses"] == ["event_types"]
    assert extra["clamp_types"] == [
        "role", "codelet_background_level", "jootsing_factor", "jootsing_only_when_latest", "progress_focus",
        "codelet_patterns"]
    pick = {c["name"]: c["pick"] for c in data["columns"]["bridge_types"]}
    assert pick["role"] == roles["bridge_types"]["roles"]


@pytest.mark.asyncio
async def test_a_list_row_carries_every_column(app_client):
    rows = await _rows(app_client, "bridge_types")
    assert rows["top"]["role"] == "bridge_type.top"
    clamps = await _rows(app_client, "clamp_types")
    assert set(next(iter(clamps.values()))) >= {"jootsing_factor", "progress_focus", "codelet_background_level"}
    assert (await _rows(app_client, "link_types"))["lateral"]["behaviour"] == "lateral"


@pytest.mark.asyncio
async def test_an_unbound_row_is_added_updated_and_deleted_freely(clean):
    resp = await clean.post("/api/admin/enums/bridge_types", json={"name": "spare", "display_label": "Spare"})
    assert resp.status_code == 201, resp.text
    assert resp.json()["role"] is None
    resp = await clean.put("/api/admin/enums/bridge_types/spare", json={"display_label": "Spare 2"})
    assert resp.status_code == 200 and resp.json()["display_label"] == "Spare 2"
    assert (await clean.delete("/api/admin/enums/bridge_types/spare")).status_code == 200


@pytest.mark.asyncio
async def test_a_role_is_a_name_of_the_vocabulary_and_held_by_one_row(clean):
    resp = await clean.post("/api/admin/enums/bridge_types", json={
        "name": "spare", "display_label": "S", "role": "rule_type.top"})
    assert resp.status_code == 422 and "unknown_reference" in resp.json()["detail"]
    resp = await clean.post("/api/admin/enums/bridge_types", json={
        "name": "spare", "display_label": "S", "role": "bridge_type.top"})
    assert resp.status_code == 422 and "role_taken" in resp.json()["detail"]
    resp = await clean.post("/api/admin/enums/bridge_types", json={"name": "spare", "display_label": "S"})
    assert resp.status_code == 201
    resp = await clean.put("/api/admin/enums/bridge_types/spare", json={
        "display_label": "S", "role": "bridge_type.bottom"})
    assert resp.status_code == 422 and "role_taken" in resp.json()["detail"]
    resp = await clean.put("/api/admin/enums/bridge_types/spare", json={"display_label": "S", "nope": 1})
    assert resp.status_code == 422
    # a row's own role is not "taken" by itself
    resp = await clean.put("/api/admin/enums/bridge_types/top", json={
        "display_label": "Top", "role": "bridge_type.top"})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_a_bound_row_is_not_deleted_until_it_is_unbound(clean):
    resp = await clean.delete("/api/admin/enums/bridge_types/top")
    assert resp.status_code == 422 and "role_bound" in resp.json()["detail"]
    assert "top" in await _rows(clean, "bridge_types")
    resp = await clean.delete("/api/admin/enums/link_types/lateral")
    assert resp.status_code == 422 and "role_bound" in resp.json()["detail"]
    # unbind (role to null), then it is an ordinary row: the foreign keys still guard it
    resp = await clean.put("/api/admin/enums/bridge_types/top", json={"display_label": "Top", "role": None})
    assert resp.status_code == 200 and resp.json()["role"] is None
    assert (await clean.delete("/api/admin/enums/bridge_types/top")).status_code == 200
    assert "top" not in await _rows(clean, "bridge_types")


@pytest.mark.asyncio
async def test_a_referenced_row_that_is_unbound_is_still_guarded(clean):
    resp = await clean.put("/api/admin/enums/link_types/lateral", json={"display_label": "Lateral", "behaviour": None})
    assert resp.status_code == 200
    resp = await clean.delete("/api/admin/enums/link_types/lateral")
    assert resp.status_code == 409  # 84 links still have the type


@pytest.mark.asyncio
async def test_the_columns_that_name_another_table_are_checked(clean):
    resp = await clean.put("/api/admin/enums/clamp_types/justify_clamp", json={
        "display_label": "J", "progress_focus": "no-such-focus"})
    assert resp.status_code == 422 and "unknown_reference" in resp.json()["detail"]
    resp = await clean.put("/api/admin/enums/clamp_types/justify_clamp", json={
        "display_label": "J", "codelet_background_level": "no-such-level"})
    assert resp.status_code == 422
    focuses = await _rows(clean, "progress_focuses")
    used = (await _rows(clean, "clamp_types"))["justify_clamp"]["progress_focus"]
    assert used in focuses
    resp = await clean.delete(f"/api/admin/enums/progress_focuses/{used}")
    assert resp.status_code == 409  # a clamp type still names it


@pytest.mark.asyncio
async def test_a_rename_rewrites_every_column_that_names_the_row(clean):
    rules_before = (await clean.get("/api/admin/posting-rules")).json()
    n = sum(1 for r in rules_before if r["direction"] == "bottom_up")
    assert n > 0
    resp = await clean.post("/api/admin/enums/posting_directions/bottom_up/rename", json={"new_name": "bu"})
    assert resp.status_code == 200, resp.text
    report = resp.json()["report"]
    assert report["ok"] and report["persisted"]
    rows = await _rows(clean, "posting_directions")
    assert "bottom_up" not in rows and rows["bu"]["role"] == "posting_direction.bottom_up"
    assert list(rows) == ["bu", "top_down", "thematic"]  # the row keeps its place
    rules = (await clean.get("/api/admin/posting-rules")).json()
    assert sum(1 for r in rules if r["direction"] == "bu") == n
    assert not any(r["direction"] == "bottom_up" for r in rules)
    assert sum(1 for c in report["cascaded"] if c["table"] == "posting_rules") == n

    # a link type: 84 links are rewritten, and they keep their keys apart
    resp = await clean.post("/api/admin/enums/link_types/lateral/rename", json={"new_name": "lat"})
    assert resp.status_code == 200, resp.text
    links = (await clean.get("/api/admin/slipnet/links")).json()
    assert not any(l["link_type"] == "lateral" for l in links)
    assert sum(1 for l in links if l["link_type"] == "lat") == 84
    assert (await _rows(clean, "link_types"))["lat"]["behaviour"] == "lateral"

    # a list column: the progress focus names event types
    event = (await _rows(clean, "progress_focuses"))
    in_focus = next(f for f in event.values() if f["event_types"])
    old = in_focus["event_types"][0]
    resp = await clean.post(f"/api/admin/enums/event_types/{old}/rename", json={"new_name": "renamed_event"})
    assert resp.status_code == 200, resp.text
    again = (await _rows(clean, "progress_focuses"))[in_focus["name"]]["event_types"]
    assert again == ["renamed_event" if x == old else x for x in in_focus["event_types"]]


@pytest.mark.asyncio
async def test_a_rename_that_cannot_be_made_is_refused(clean):
    resp = await clean.post("/api/admin/enums/bridge_types/no-such/rename", json={"new_name": "x"})
    assert resp.status_code == 404
    resp = await clean.post("/api/admin/enums/bridge_types/top/rename", json={"new_name": "bottom"})
    assert resp.status_code == 409
    assert (await clean.post("/api/admin/enums/nope/top/rename", json={"new_name": "x"})).status_code == 404


@pytest.mark.asyncio
async def test_a_renamed_vocabulary_row_has_a_story_for_the_names_panel(clean):
    """Episodic Memory persists these names: the change API neither refuses nor rewrites, and the
    journal says what became of the old name (``where-did-name-go``, ``check-names``)."""
    resp = await clean.post("/api/admin/enums/theme_types/top_bridge/rename", json={"new_name": "tb"})
    assert resp.status_code == 200, resp.text
    story = (await clean.get("/api/journal/where-did-name-go", params={"name": "top_bridge"})).json()
    assert not story["resolves"] and story["current_name"] == "tb"
    assert story["events"][-1]["event"] == "renamed" and story["events"][-1]["kind"] == "theme type"
    assert story["events"][-1]["to"] == "tb"
    new = (await clean.get("/api/journal/where-did-name-go", params={"name": "tb"})).json()
    assert new["resolves"] and [e["event"] for e in new["events"]] == ["renamed_from"]
    checked = (await clean.post("/api/journal/check-names", json={"names": ["top_bridge", "tb", "plato-a"]})).json()
    assert [u["name"] for u in checked["unresolved"]] == ["top_bridge"]
    assert checked["unresolved"][0]["current_name"] == "tb"


@pytest.mark.asyncio
async def test_a_rename_is_undone_by_the_journal_as_one_entry(clean):
    before = await _rows(clean, "posting_directions")
    resp = await clean.post("/api/admin/enums/posting_directions/top_down/rename", json={"new_name": "td"})
    assert resp.status_code == 200, resp.text
    entry = resp.json()["report"]["batch_id"]
    undone = await clean.post("/api/configurations/1/restore", json={"undo_batch": entry})
    assert undone.status_code == 200, undone.text
    assert await _rows(clean, "posting_directions") == before
    rules = (await clean.get("/api/admin/posting-rules")).json()
    assert not any(r["direction"] == "td" for r in rules)
    assert (await clean.get("/api/configurations/1/verify-journal")).json()["ok"]


@pytest.mark.asyncio
async def test_a_session_configuration_renames_a_vocabulary_row_through_the_change_api(clean, made):
    """The Training Mode Session's own configuration is renamed by the change API (the Admin enum
    editor is the global configuration's only: the vocabulary tables exist there); the global
    configuration (Metacat Mode) is untouched."""
    resp = await clean.post(f"/api/configurations/{made}/changes", json={
        "source": "admin", "actor": "t", "base_mode": "rebase",
        "ops": [{"op": "rename_enum_value", "table": "posting_directions", "old": "bottom_up", "new": "bu"}]})
    assert resp.status_code == 200, resp.text
    rows = (await clean.get(f"/api/configurations/{made}/rows", params={"table": "posting_directions"})).json()
    names = [r["name"] for r in (rows["rows"] if isinstance(rows, dict) else rows)]
    assert "bu" in names and "bottom_up" not in names
    assert "bottom_up" in await _rows(clean, "posting_directions")
