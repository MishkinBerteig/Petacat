"""Clicking a Trace event, an answer or a snag redisplays the moment.

Metacat's ``display`` methods (``trace.ss:405-1250``, ``memory.ss:268-395``) redraw the
Workspace for the moment, show its concept pattern in the Slipnet, blank the Coderack and
show its temperature.  Petacat takes the picture when the thing is recorded and serves it:
with the event (``GET /trace/{n}``, which falls back to the stored row once the run is no
longer loaded), and from each ``display`` call.  A row stored before pictures were kept
has none and still works: it imposes its theme pattern, as it always did.

Requires: a local Postgres — start it with `scripts/dev.sh db`.
"""

import pytest
from sqlalchemy import update

from server.api.runs import get_run_service
from server.models.run import AnswerDescriptionRow, SnagDescriptionRow, TraceEventRow

SNAGGING = {"initial": "abc", "modified": "abd", "target": "xyz", "seed": 34}
ANSWERING = {"initial": "abc", "modified": "abd", "target": "ijk", "seed": 3}


async def _run(app_client, problem: dict, steps: int) -> int:
    run_id = (await app_client.post("/api/runs", json=problem)).json()["run_id"]
    await app_client.post(f"/api/runs/{run_id}/run", json={"max_steps": steps})
    return run_id


@pytest.mark.asyncio
async def test_the_trace_lists_events_by_metacats_print_names(app_client):
    run_id = await _run(app_client, ANSWERING, 3000)
    events = (await app_client.get(f"/api/runs/{run_id}/trace")).json()["events"]
    names = [e["print_name"] for e in events]
    assert names[0] == "(Identity)"
    assert ">i-j-k>" in names and "[Top Rule]" in names
    assert names[-1] == "[Answer ijl]"
    # The prose stays, as the longer description.
    assert all(e["description"] for e in events)


@pytest.mark.asyncio
async def test_displaying_an_event_serves_its_picture_and_toggles(app_client):
    run_id = await _run(app_client, ANSWERING, 3000)
    events = (await app_client.get(f"/api/runs/{run_id}/trace")).json()["events"]
    group = next(e for e in events if e["event_type"] == "group_built")

    detail = (await app_client.get(f"/api/runs/{run_id}/trace/{group['event_number']}")).json()
    assert detail["print_name"] == group["print_name"]
    assert detail["picture"]["header"] == "Built successor-group"

    shown = (
        await app_client.post(f"/api/runs/{run_id}/trace/{group['event_number']}/display")
    ).json()
    assert shown["displaying"] == group["event_number"]
    assert shown["picture"] == detail["picture"]
    assert shown["picture"]["slipnet"]["title"] == "Group Descriptors"

    # Another event switches to it without restoring in between; the same one restores.
    other = next(e for e in events if e["event_type"] == "rule_built")
    switched = (
        await app_client.post(f"/api/runs/{run_id}/trace/{other['event_number']}/display")
    ).json()
    assert switched["displaying"] == other["event_number"]
    assert switched["picture"]["header"] == "Built rule"
    restored = (
        await app_client.post(f"/api/runs/{run_id}/trace/{other['event_number']}/display")
    ).json()
    assert restored["displaying"] is None and restored["picture"] is None


@pytest.mark.asyncio
async def test_a_stored_event_is_served_with_its_picture_after_the_run_is_unloaded(app_client):
    run_id = await _run(app_client, ANSWERING, 3000)
    events = (await app_client.get(f"/api/runs/{run_id}/trace")).json()["events"]
    number = events[1]["event_number"]
    live = (await app_client.get(f"/api/runs/{run_id}/trace/{number}")).json()

    get_run_service()._runners.pop(run_id)

    stored = await app_client.get(f"/api/runs/{run_id}/trace/{number}")
    assert stored.status_code == 200
    assert stored.json()["picture"] == live["picture"]
    shown = (await app_client.post(f"/api/runs/{run_id}/trace/{number}/display")).json()
    assert shown["displaying"] == number
    assert shown["picture"] == live["picture"]


@pytest.mark.asyncio
async def test_an_answer_displays_its_description_picture(app_client):
    run_id = await _run(app_client, ANSWERING, 3000)
    answers = (await app_client.get("/api/memory")).json()["answers"]
    assert answers and all(a["has_picture"] for a in answers)
    answer_id = answers[-1]["answer_id"]

    shown = (
        await app_client.post(f"/api/memory/answers/{answer_id}/display?run_id={run_id}")
    ).json()
    assert shown["displaying"] == answer_id
    assert shown["picture"]["header"] == "Answer Description"
    assert shown["picture"]["workspace"]["answer"] == "ijl"
    assert shown["temperature"] == answers[-1]["temperature"]

    again = (
        await app_client.post(f"/api/memory/answers/{answer_id}/display?run_id={run_id}")
    ).json()
    assert again["displaying"] is None and again["picture"] is None


@pytest.mark.asyncio
async def test_a_snag_displays_its_description_picture_at_temperature_100(app_client):
    run_id = await _run(app_client, SNAGGING, 3000)
    snags = (await app_client.get("/api/memory")).json()["snags"]
    assert snags, "the run recorded no snag, so this test proves nothing"
    assert all(s["has_picture"] for s in snags)
    snag_id = snags[0]["snag_id"]

    shown = await app_client.post(f"/api/memory/snags/{snag_id}/display?run_id={run_id}")
    assert shown.status_code == 200
    body = shown.json()
    assert body["displaying"] == snag_id
    assert body["picture"]["header"] == "Snag Description"
    assert body["picture"]["question_mark"] is True
    assert body["temperature"] == 100.0

    assert (
        await app_client.post(f"/api/memory/snags/999999/display?run_id={run_id}")
    ).status_code == 404
    again = (
        await app_client.post(f"/api/memory/snags/{snag_id}/display?run_id={run_id}")
    ).json()
    assert again["displaying"] is None


@pytest.mark.asyncio
async def test_rows_written_without_pictures_still_display(app_client, db_session):
    """An answer, snag or event stored before pictures were kept has none: the display
    call still answers, imposing the theme pattern, with no picture to draw."""
    run_id = await _run(app_client, SNAGGING, 3000)
    await db_session.execute(update(TraceEventRow).values(picture=None, print_name=None))
    await db_session.execute(update(AnswerDescriptionRow).values(picture=None))
    await db_session.execute(update(SnagDescriptionRow).values(picture=None))
    await db_session.commit()

    get_run_service()._runners.pop(run_id)
    events = (await app_client.get(f"/api/runs/{run_id}/trace")).json()["events"]
    assert events
    assert all(e["print_name"] == "" for e in events), "the label falls back to the description"
    number = events[0]["event_number"]
    detail = await app_client.get(f"/api/runs/{run_id}/trace/{number}")
    assert detail.status_code == 200
    assert detail.json()["picture"] is None
    shown = (await app_client.post(f"/api/runs/{run_id}/trace/{number}/display")).json()
    assert shown["displaying"] == number
    assert shown["picture"] is None

    # The memory still lists the answers and snags, and reports there is nothing to draw.
    memory = (await app_client.get(f"/api/runs/{run_id}/memory")).json()
    assert memory["snags"] and not any(s["has_picture"] for s in memory["snags"])
