"""Metacat Mode's three doors read a problem through Metacat's input parser, end to end.

The doors are ``POST /api/runs`` (``RunService.create_run``), ``POST /api/swarm`` and the Admin
view's Demo Problems.  One case per row of the table in ``THE-THREE-SYSTEMS.md``, a Fast run with no
database statement, Swarm, the demos, and the shipped demo problems.  A Training Mode Session does not
come through here: its problems are any UTF-8 text kept exactly (``test_unicode_problem_strings.py``
and the last test of this file).

The fields are read left to right as one line, ``initial modified target [answer] [seed]``.  A refusal
is a 400 whose detail is exactly ``Invalid input!``, and nothing is created.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from server.models.metadata import DemoProblem
from server.models.run import Run
from tests.e2e.test_persistence_modes import _statements_issued
from tests.e2e.test_session_configuration import serial_sessions, sessions  # noqa: F401 - the fixtures

INVALID = "Invalid input!"
SEED = 12345
SEED_MAX = 4294967295
ROOT = Path(__file__).resolve().parents[2]


async def _run_count(test_engine) -> int:
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        return (await s.execute(select(func.count()).select_from(Run))).scalar_one()


# One case per row of THE-THREE-SYSTEMS.md's table, plus the shape rules around them.
READ = [
    pytest.param({"initial": "abc", "modified": "abd", "target": "xyz"}, ("abc", "abd", "xyz", None), id="a-to-z"),
    pytest.param({"initial": "abc", "modified": "abd", "target": "xyZ"}, ("abc", "abd", "xyz", None), id="uppercase-lowered"),
    pytest.param({"initial": "ABC", "modified": "ABD", "target": "XYZ"}, ("abc", "abd", "xyz", None), id="all-uppercase"),
    pytest.param({"initial": "abc", "modified": "abd", "target": "x-z"}, ("abc", "abd", "x", "z"), id="punctuation-separates"),
    pytest.param({"initial": "abc", "modified": "abd", "target": "x z"}, ("abc", "abd", "x", "z"), id="space-separates"),
    pytest.param({"initial": "abc", "modified": "abd", "target": "x😀z"}, ("abc", "abd", "x", "z"), id="emoji-separates"),
    pytest.param({"initial": "abc", "modified": "abd", "target": "x́z"}, ("abc", "abd", "x", "z"), id="combining-mark-separates"),
    pytest.param({"initial": "abc", "modified": "abd", "target": "xyz", "answer": "wyz"}, ("abc", "abd", "xyz", "wyz"), id="answer"),
    pytest.param({"initial": "abc", "modified": "abd", "target": "xyz 5"}, ("abc", "abd", "xyz", None), id="seed-in-fourth-place"),
]
REFUSED = [
    pytest.param({"initial": "abc", "modified": "abd", "target": "xy1"}, id="digit-inside-a-string"),
    pytest.param({"initial": "abc", "modified": "abd", "target": "é"}, id="non-english-letter-e-acute"),
    pytest.param({"initial": "abc", "modified": "abd", "target": "日本"}, id="non-english-letters-cjk"),
    pytest.param({"initial": "5", "modified": "abd", "target": "xyz"}, id="digits-alone-in-first-place"),
    pytest.param({"initial": "abc", "modified": "5", "target": "xyz"}, id="digits-alone-in-second-place"),
    pytest.param({"initial": "abc", "modified": "abd", "target": "5"}, id="digits-alone-in-third-place"),
    pytest.param({"initial": "abc", "modified": "abd", "target": ""}, id="empty-target"),
    pytest.param({"initial": "", "modified": "abd", "target": "xyz"}, id="empty-initial"),
    pytest.param({"initial": "abc", "modified": "abd", "target": "xyz", "seed": 0}, id="seed-zero"),
    pytest.param({"initial": "abc", "modified": "abd", "target": "xyz", "seed": -3}, id="seed-negative"),
    pytest.param({"initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED_MAX + 1}, id="seed-too-large"),
    pytest.param({"initial": "abc", "modified": "abd", "target": "xyz", "answer": "wy1"}, id="digit-in-the-answer"),
    pytest.param({"initial": "abc", "modified": "abd", "target": "xyz 7", "seed": 3}, id="two-seeds"),
    pytest.param({"initial": "abc", "modified": "abd", "target": "xyz", "answer": "a\x00b"}, id="nul-separates-then-too-many-tokens"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("fields,expected", READ)
async def test_run_creation_reads_the_fields_through_metacats_parser(app_client, fields, expected):
    on_the_line = "5" in fields["target"].split()
    resp = await app_client.post("/api/runs", json=fields if on_the_line else {**fields, "seed": SEED})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["initial"], body["modified"], body["target"], body["answer"]) == expected
    assert body["justify_mode"] == (expected[3] is not None)
    # The run holds the strings the parser read, and shows them again.
    got = (await app_client.get(f"/api/runs/{body['run_id']}")).json()
    assert (got["initial"], got["modified"], got["target"], got["answer"]) == expected
    assert body["seed"] == (5 if on_the_line else SEED)


@pytest.mark.asyncio
@pytest.mark.parametrize("fields", REFUSED)
async def test_input_the_parser_refuses_is_a_400_saying_exactly_invalid_input_and_creates_nothing(
    app_client, test_engine, fields,
):
    before = await _run_count(test_engine)
    for mode in ("normal", "fast"):
        resp = await app_client.post("/api/runs", json={"mode": mode, "seed": SEED, **fields})
        assert resp.status_code == 400, (mode, resp.text)
        assert resp.json()["detail"] == INVALID
    assert await _run_count(test_engine) == before


@pytest.mark.asyncio
async def test_a_lone_surrogate_is_invalid_input_not_a_crash(app_client, test_engine):
    before = await _run_count(test_engine)
    body = json.dumps({"initial": "abc", "modified": "abd", "target": "x\ud800z", "seed": SEED})
    resp = await app_client.post("/api/runs", content=body, headers={"Content-Type": "application/json"})
    assert resp.status_code in (400, 422), resp.text
    if resp.status_code == 400:
        assert resp.json()["detail"] == INVALID
    assert await _run_count(test_engine) == before


@pytest.mark.asyncio
async def test_no_seed_picks_a_random_seed_that_the_run_records_and_shows(app_client, db_session):
    seeds = set()
    for _ in range(3):
        resp = await app_client.post("/api/runs", json={"initial": "abc", "modified": "abd", "target": "xyz"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert 1 <= body["seed"] <= SEED_MAX
        seeds.add(body["seed"])
        row = (await db_session.execute(select(Run).where(Run.id == body["run_id"]))).scalar_one()
        assert row.seed == body["seed"]
        assert (await app_client.get(f"/api/runs/{body['run_id']}")).json()["seed"] == body["seed"]
    assert len(seeds) > 1
    # The largest seed is allowed, and a seed written on the line is the run's seed.
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED_MAX})
    assert resp.status_code == 200 and resp.json()["seed"] == SEED_MAX
    resp = await app_client.post("/api/runs", json={"initial": "abc", "modified": "abd", "target": "xyz 77"})
    assert resp.status_code == 200 and resp.json()["seed"] == 77


@pytest.mark.asyncio
async def test_a_fast_run_is_read_through_the_parser_with_no_database_statement(app_client, test_engine):
    """The parser reads the configuration the service already holds, so Fast creation touches no database."""
    with _statements_issued(test_engine) as statements:
        resp = await app_client.post("/api/runs", json={
            "initial": "ABC", "modified": "abd", "target": "x-z", "mode": "fast"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["initial"], body["target"], body["answer"]) == ("abc", "x", "z")
    assert 1 <= body["seed"] <= SEED_MAX
    assert statements == []
    bad = []
    with _statements_issued(test_engine) as statements:
        bad = await app_client.post("/api/runs", json={
            "initial": "abc", "modified": "abd", "target": "é", "mode": "fast"})
    assert bad.status_code == 400 and bad.json()["detail"] == INVALID and statements == []


@pytest.mark.asyncio
async def test_a_justification_problem_written_on_one_line_runs(app_client):
    resp = await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "mrrjjj-mrrjjjj", "seed": SEED, "mode": "fast"})
    assert resp.status_code == 200, resp.text
    run = resp.json()
    assert (run["target"], run["answer"], run["justify_mode"]) == ("mrrjjj", "mrrjjjj", True)
    done = await app_client.post(f"/api/runs/{run['run_id']}/step", json={"n": 20})
    assert done.status_code == 200, done.text


# ----------------------------------------------------------------------------- Swarm


@pytest.fixture(scope="module", autouse=True)
def _stop_default_swarm():
    yield
    from server.parallel.swarm import shutdown_default

    shutdown_default()


@pytest.mark.asyncio
async def test_swarm_reads_its_problem_through_the_parser(app_client):
    resp = await app_client.post("/api/swarm", json={
        "initial": "ABC", "modified": "abd", "target": "xyZ", "seeds": [1, 2], "max_steps": 300,
        "backend": "numpy"})
    assert resp.status_code == 200, resp.text
    plain = await app_client.post("/api/swarm", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seeds": [1, 2], "max_steps": 300,
        "backend": "numpy"})
    assert [(r["seed"], r["codelets"], r["answer"]) for r in resp.json()["runs"]] == [
        (r["seed"], r["codelets"], r["answer"]) for r in plain.json()["runs"]]


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [
    pytest.param({"initial": "abc", "modified": "abd", "target": "xy1", "seeds": [1]}, id="digit-in-a-string"),
    pytest.param({"initial": "abc", "modified": "abd", "target": "日本", "seeds": [1]}, id="non-english-letters"),
    pytest.param({"initial": "abc", "modified": "abd", "target": "xyz", "seeds": [0]}, id="seed-zero"),
    pytest.param({"initial": "abc", "modified": "abd", "target": "xyz", "seeds": [1, -4]}, id="seed-negative"),
    pytest.param({"initial": "abc", "modified": "abd", "target": "xyz", "seeds": [SEED_MAX + 1]}, id="seed-too-large"),
    pytest.param({"initial": "abc", "modified": "abd", "target": "xyz", "count": 2, "seed_start": 0}, id="count-from-zero"),
    pytest.param({"initial": "abc", "modified": "abd", "target": "xyz", "count": 2, "seed_start": SEED_MAX}, id="count-past-the-largest"),
    pytest.param({"initial": "abc", "modified": "abd", "target": "xyz 5", "seeds": [1]}, id="seed-on-the-line"),
    pytest.param({"initial": "abc", "modified": "abd", "target": "", "seeds": [1]}, id="empty-target"),
])
async def test_swarm_refuses_what_the_parser_refuses(app_client, body):
    resp = await app_client.post("/api/swarm", json=body)
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"] == INVALID


# ----------------------------------------------------------------------------- Admin's demo problems


@pytest.mark.asyncio
async def test_a_demo_problem_is_stored_as_the_parser_read_it(app_client, test_engine):
    resp = await app_client.post("/api/admin/demos", json={
        "name": "parser demo", "section": "q", "initial": "ABC", "modified": "Abd", "target": "x-z"})
    assert resp.status_code == 201, resp.text
    demo = resp.json()
    try:
        assert (demo["initial"], demo["modified"], demo["target"], demo["answer"]) == ("abc", "abd", "x", "z")
        assert 1 <= demo["seed"] <= SEED_MAX  # none given: a random seed, stored
        resp = await app_client.put(f"/api/admin/demos/{demo['id']}", json={
            "name": "parser demo", "initial": "abc", "modified": "abd", "target": "xyz", "seed": 9})
        assert resp.status_code == 200 and (resp.json()["target"], resp.json()["seed"]) == ("xyz", 9)
        # The stored demo runs.
        run = await app_client.post("/api/runs", json={
            "initial": "abc", "modified": "abd", "target": "xyz", "seed": resp.json()["seed"], "mode": "fast"})
        assert run.status_code == 200
    finally:
        await app_client.delete(f"/api/admin/demos/{demo['id']}")


@pytest.mark.asyncio
@pytest.mark.parametrize("fields", [
    {"initial": "abc", "modified": "abd", "target": "xy1"},
    {"initial": "abc", "modified": "abd", "target": "é"},
    {"initial": "abc", "modified": "abd", "target": "xyz", "seed": 0},
    {"initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED_MAX + 1},
])
async def test_an_unreadable_demo_problem_is_refused_and_stores_nothing(app_client, test_engine, fields):
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        before = (await s.execute(select(func.count()).select_from(DemoProblem))).scalar_one()
    resp = await app_client.post("/api/admin/demos", json={"name": "never stored", **fields})
    assert resp.status_code == 400 and resp.json()["detail"] == INVALID
    async with factory() as s:
        assert (await s.execute(select(func.count()).select_from(DemoProblem))).scalar_one() == before


@pytest.mark.asyncio
async def test_every_shipped_demo_problem_is_readable_and_runs(app_client):
    demos = json.loads((ROOT / "seed_data" / "demo_problems.json").read_text())
    assert demos
    for d in demos:
        resp = await app_client.post("/api/runs", json={
            "initial": d["initial"], "modified": d["modified"], "target": d["target"],
            "answer": d.get("answer"), "seed": d["seed"], "mode": "fast"})
        assert resp.status_code == 200, (d["name"], resp.text)
        body = resp.json()
        assert (body["initial"], body["modified"], body["target"], body["answer"], body["seed"]) == (
            d["initial"], d["modified"], d["target"], d.get("answer"), d["seed"]), d["name"]
        step = await app_client.post(f"/api/runs/{body['run_id']}/step", json={"n": 5})
        assert step.status_code == 200, (d["name"], step.text)


# ----------------------------------------------------------------------------- Training Mode is untouched


@pytest.mark.asyncio
async def test_training_mode_sessions_keep_the_same_text_exactly(app_client, sessions):
    problems = [
        {"initial": "abC", "modified": "abd", "target": "xyz"},
        {"initial": "abc", "modified": "abd", "target": "xy1"},
        {"initial": "é", "modified": "è", "target": "ê", "answer": "ë"},
        {"initial": "日本", "modified": "日本語", "target": "本"},
        {"initial": "😀", "modified": "😀😀", "target": "😀😀😀", "answer": "x-z"},
        {"initial": "abc", "modified": "abd", "target": "x-z"},
    ]
    resp = await app_client.post("/api/training-mode/sessions", json={
        "name": "parser stays out", "settings": {"seeds_per_problem": 1, "max_codelets": 30},
        "problems": problems})
    assert resp.status_code == 201, resp.text
    tid = resp.json()["session"]["id"]
    assert resp.json()["added"] == len(problems)
    listed = (await app_client.get(f"/api/training-mode/sessions/{tid}/problems", params={"limit": 50})).json()
    assert [(p["initial"], p["modified"], p["target"], p.get("answer")) for p in listed["problems"]] == [
        (p["initial"], p["modified"], p["target"], p.get("answer")) for p in problems]
    await app_client.delete(f"/api/training-mode/sessions/{tid}")


# ----------------------------------------------------------------------------- the configuration, through Admin


@pytest.fixture
async def clean_configuration(app_client):
    async def reset():
        resp = await app_client.post("/api/configurations/1/reset-to-standard", json={"confirm": "reset"})
        assert resp.status_code == 200, resp.text

    await reset()
    yield app_client
    await reset()


@pytest.mark.asyncio
async def test_a_scenario_changes_what_metacat_mode_perceives_through_admin_with_no_code_change(clean_configuration):
    client = clean_configuration
    problem = {"initial": "abc", "modified": "abd", "target": "XYZ", "seed": SEED}
    assert (await client.post("/api/runs", json=problem)).json()["target"] == "xyz"

    # The lowering of A to Z is a row: change it, and capitals are no longer lowered letters.
    rows = (await client.get("/api/admin/input-lowering-ranges")).json()
    upper = next(r for r in rows if (r["first"], r["last"]) == (65, 90))
    resp = await client.put(f"/api/admin/input-lowering-ranges/{upper['id']}", json={
        "first": 65, "last": 90, "step": 1, "delta": 0})
    assert resp.status_code == 200, resp.text
    refused = await client.post("/api/runs", json=problem)
    assert refused.status_code == 400 and refused.json()["detail"] == INVALID

    # The largest seed is an engine parameter.
    await client.post("/api/configurations/1/reset-to-standard", json={"confirm": "reset"})
    resp = await client.put("/api/admin/params/largest_seed", json={"value": "100", "value_type": "int"})
    assert resp.status_code == 200, resp.text
    assert (await client.post("/api/runs", json={**problem, "seed": 101})).status_code == 400
    assert (await client.post("/api/runs", json={**problem, "seed": 100})).status_code == 200

    # Removing a row of the character classes is a row removed: the digits stop being digits.
    await client.post("/api/configurations/1/reset-to-standard", json={"confirm": "reset"})
    chars = (await client.get("/api/admin/input-character-ranges")).json()
    digits = next(r for r in chars if r["kind"] == "numeric" and r["first"] == 48)
    assert (await client.delete(f"/api/admin/input-character-ranges/{digits['id']}")).status_code == 200
    seeded = await client.post("/api/runs", json={"initial": "abc", "modified": "abd", "target": "xyz 5"})
    # "5" is now a separator, not a seed: the line is three strings, and the seed is a random one.
    assert seeded.status_code == 200 and seeded.json()["seed"] != 5


@pytest.mark.asyncio
async def test_the_run_history_list_shows_the_recorded_seed_of_a_run_created_with_none(app_client):
    made = (await app_client.post("/api/runs", json={"initial": "abc", "modified": "abd", "target": "xyz"})).json()
    explicit = (await app_client.post("/api/runs", json={
        "initial": "abc", "modified": "abd", "target": "xyz", "seed": SEED})).json()
    listed = {r["run_id"]: r for r in (await app_client.get("/api/runs", params={"limit": 200})).json()["runs"]}
    assert 1 <= made["seed"] <= SEED_MAX
    assert listed[made["run_id"]]["seed"] == made["seed"]
    assert listed[explicit["run_id"]]["seed"] == SEED
