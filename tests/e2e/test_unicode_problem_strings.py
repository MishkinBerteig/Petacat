"""Any Unicode text is a valid problem string, in Training Mode and in Metacat Mode, end to end.

A Training Mode Session whose problems use a broad corpus (spaces, separators, an arrow, digits, NFC and
NFD, Greek, Cyrillic, Hebrew, CJK, Devanagari, emoji and ZWJ and flag sequences, a tab, a line break, a
BOM, a bidirectional override, a 1,000-character string) is created, run with a small codelet cap,
Stopped, and its problems read back from the database exactly equal.  A Metacat Mode run created with
the same strings stores and returns them exactly, and appears in Run History and Review unchanged.
Demo Problems (Admin view) take them too.  U+0000 and a lone surrogate, the two things a database
cannot store, are refused with a 422 that names the field and the reason, never a 500.

Whether the engine behaves well on every string is not what these tests assert: a run that errors on
a string is recorded in the session's problem row (``first_error``), and the strings are stored regardless.
"""

from __future__ import annotations

import json
import unicodedata

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from server.models.metadata import DemoProblem
from server.models.run import Run
from server.models.training_mode_session import TrainingModeSessionProblem
from tests.e2e.test_session_configuration import serial_sessions, sessions  # noqa: F401 - the fixtures
from tests.e2e.test_training_mode_sessions_api import stop, until_state

NFC = unicodedata.normalize("NFC", "é")
NFD = unicodedata.normalize("NFD", "é")

CORPUS = [
    "a b", "a,b;c", "x->y", "ABC", "1 2 3", NFC, NFD, "αβγ", "абв", "אבג", "漢字", "नमस्ते",
    "😀", "👨‍👩‍👧", "🇨🇦", "\t", "a\nb", "﻿", "‮", "x" * 1000,
]


def corpus_problems() -> list[dict]:
    """One problem per corpus string; the strings rotate through the fields; some justify an answer."""
    n = len(CORPUS)
    out = []
    for i, s in enumerate(CORPUS):
        p = {"initial": s, "modified": CORPUS[(i + 1) % n], "target": CORPUS[(i + 2) % n]}
        if i % 3 == 2:
            p["answer"] = s
        out.append(p)
    return out


async def post_ascii(client, path: str, body: dict):
    """POST JSON written with ``\\uXXXX`` escapes: a lone surrogate can only travel that way (httpx
    encodes its own ``json=`` as UTF-8, which has no lone surrogates)."""
    return await client.post(path, content=json.dumps(body), headers={"Content-Type": "application/json"})


def exact(p: dict) -> tuple:
    return (p["initial"], p["modified"], p["target"], p.get("answer"))


async def stored_problems(engine, tid: int) -> list[tuple]:
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        rows = (await s.execute(
            select(TrainingModeSessionProblem).where(TrainingModeSessionProblem.session_id == tid)
            .order_by(TrainingModeSessionProblem.problem_id)
        )).scalars().all()
    return [(r.initial, r.modified, r.target, r.answer) for r in rows]


@pytest.mark.asyncio
async def test_a_session_of_unicode_problems_is_run_stopped_and_read_back_exactly(app_client, sessions, test_engine):
    problems = corpus_problems()
    resp = await app_client.post("/api/training-mode/sessions", json={
        "name": "unicode: 漢字 😀 / a b",
        "settings": {"seeds_per_problem": 1, "max_codelets": 60},
        "problems": problems,
    })
    assert resp.status_code == 201, resp.text
    tid = resp.json()["session"]["id"]
    assert resp.json()["added"] == len(problems)
    # The two spellings of é are two problems' strings, never merged.
    assert NFC in [p["initial"] for p in problems] and NFD in [p["initial"] for p in problems]

    started = await app_client.post(f"/api/training-mode/sessions/{tid}/start")
    assert started.status_code == 200, started.text
    await until_state(app_client, tid, "finished", timeout=120)
    await stop(app_client, tid)

    assert await stored_problems(test_engine, tid) == [exact(p) for p in problems]

    # The API returns them exactly too, and an error in a run (if the engine has one) is recorded, not hidden.
    listed = (await app_client.get(f"/api/training-mode/sessions/{tid}/problems", params={"limit": 500})).json()
    assert [exact(p) for p in listed["problems"]] == [exact(p) for p in problems]
    for p in listed["problems"]:
        assert p["status"] in {"finished", "cancelled"}, p
    # Visible with ``-s``: which strings the engine errored on, if any.
    print("session problems with run errors:", [(p["initial"][:12], p["first_error"]) for p in listed["problems"] if p["errors"]])


@pytest.mark.asyncio
async def test_unicode_problems_can_be_added_to_a_session_and_are_not_deduplicated_across_normal_forms(app_client, sessions, test_engine):
    made = await app_client.post("/api/training-mode/sessions", json={
        "name": "add", "settings": {"seeds_per_problem": 1, "max_codelets": 30}, "problems": [],
    })
    tid = made.json()["session"]["id"]
    two = [{"initial": NFC, "modified": "b", "target": "c"}, {"initial": NFD, "modified": "b", "target": "c"}]
    resp = await app_client.post(f"/api/training-mode/sessions/{tid}/problems", json={"problems": two})
    assert resp.status_code == 201 or resp.status_code == 200, resp.text
    assert await stored_problems(test_engine, tid) == [exact(p) for p in two]


@pytest.mark.asyncio
async def test_the_two_unstorable_cases_are_refused_with_a_422_that_says_why(app_client, sessions):
    ok = {"initial": "abc", "modified": "abd", "target": "xyz"}
    for field in ("initial", "modified", "target", "answer"):
        for bad, words in (("a\x00b", "U+0000"), ("\ud800", "not valid Unicode")):
            resp = await post_ascii(app_client, "/api/training-mode/sessions", {
                "name": "bad", "problems": [{**ok, field: bad}],
            })
            assert resp.status_code == 422, (field, resp.text)
            assert field in resp.json()["detail"] and words in str(resp.json()["detail"]), resp.text
    # The same refusals from Metacat Mode's run creation and the Admin view's Demo Problems.
    for bad, words in (("a\x00b", "U+0000"), ("\ud800", "not valid Unicode")):
        resp = await post_ascii(app_client, "/api/runs", {**ok, "answer": bad})
        assert resp.status_code == 422 and words in str(resp.json()["detail"]), resp.text
        resp = await post_ascii(app_client, "/api/admin/demos", {**ok, "name": "bad", "initial": bad})
        assert resp.status_code == 422 and words in str(resp.json()["detail"]), resp.text


@pytest.mark.asyncio
async def test_metacat_mode_refuses_empty_strings_with_a_422_not_a_crash(app_client):
    ok = {"initial": "abc", "modified": "abd", "target": "xyz"}
    for field, words in (("initial", "initial must not be empty"), ("modified", "modified must not be empty"),
                         ("target", "target must not be empty"), ("answer", "answer must not be empty")):
        resp = await app_client.post("/api/runs", json={**ok, field: ""})
        assert resp.status_code == 422 and words in str(resp.json()["detail"]), (field, resp.text)
        resp = await app_client.post("/api/swarm", json={**ok, field: "", "count": 1})
        assert resp.status_code == 422 and words in str(resp.json()["detail"]), (field, resp.text)


@pytest.mark.asyncio
async def test_metacat_mode_runs_with_unicode_strings_store_and_return_them_exactly(app_client, test_engine):
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    steps: dict[int, int] = {}
    for i, p in enumerate(corpus_problems()):
        resp = await app_client.post("/api/runs", json={**p, "seed": 1})
        assert resp.status_code == 200, (i, resp.text)
        body = resp.json()
        assert exact({**body}) == exact(p), i
        run_id = body["run_id"]
        assert exact((await app_client.get(f"/api/runs/{run_id}")).json()) == exact(p)
        async with factory() as s:
            row = (await s.execute(select(Run).where(Run.id == run_id))).scalar_one()
        assert (row.initial_string, row.modified_string, row.target_string, row.answer_string) == exact(p)
        # Run History and Review show them unchanged.
        assert exact((await app_client.get(f"/api/review/runs/{run_id}")).json()) == exact(p)
        # A few codelets, with a small cap: the strings must still be there afterwards.  An engine
        # error on a string is the engine's, and is recorded by the investigation, not asserted here.
        step = await app_client.post(f"/api/runs/{run_id}/step", json={"n": 3})
        steps[i] = step.status_code
    print("Metacat Mode step status by corpus index:", steps)
    listed = (await app_client.get("/api/runs", params={"limit": 200})).json()["runs"]
    shown = {exact(r) for r in listed}
    assert {exact(p) for p in corpus_problems()} <= shown


@pytest.mark.asyncio
async def test_demo_problems_take_any_unicode_text(app_client, test_engine):
    p = {"name": "unicode demo " + "n" * 100, "section": "s" * 50, "initial": "a b\nc", "modified": "x" * 500, "target": "漢字 😀", "answer": "é\t"}
    resp = await app_client.post("/api/admin/demos", json=p)
    assert resp.status_code == 201, resp.text
    demo_id = resp.json()["id"]
    got = (await app_client.get("/api/admin/demos")).json()
    mine = next(d for d in got if d["id"] == demo_id)
    assert (mine["name"], mine["section"]) == (p["name"], p["section"])  # no 64/16-character caps
    assert (mine["initial"], mine["modified"], mine["target"], mine["answer"]) == (p["initial"], p["modified"], p["target"], p["answer"])
    assert (await app_client.delete(f"/api/admin/demos/{demo_id}")).status_code == 200
