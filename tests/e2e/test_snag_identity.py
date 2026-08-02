"""A snag is the same snag whichever endpoint served it.

A snag description records a failure episode (§4.7.2), and Episodic Memory stamps each
one with an identifier of its own.  Two endpoints project a snag: ``GET /api/memory``
reads the live memory, and ``GET /api/runs/{id}/memory`` reads the stored rows for a
Normal Run.  Both report that one identifier, so a snag read from either is
recognisable as the same snag.

Requires: a local Postgres — start it with `scripts/dev.sh db`.
"""

import pytest

SEED = 99999

# ``xyz`` has no successor to the ``z``, which is the snag §4.7.2 is written about.
SNAGGING_PROBLEM = {"initial": "abc", "modified": "abd", "target": "xyz"}


async def _run_until_snagged(app_client) -> int:
    resp = await app_client.post("/api/runs", json={**SNAGGING_PROBLEM, "seed": SEED})
    run_id = resp.json()["run_id"]
    await app_client.post(f"/api/runs/{run_id}/run", json={"max_steps": 3000})
    return run_id


async def _both_projections(app_client, run_id: int) -> tuple[list, list]:
    live = (await app_client.get("/api/memory")).json()["snags"]
    stored = (await app_client.get(f"/api/runs/{run_id}/memory")).json()
    assert stored["scope"] == "shared", "the row-backed projection is the one under test"
    return live, stored["snags"]


def _assert_same_snags(live: list, stored: list) -> None:
    assert live, "the run recorded no snag, so this test proves nothing"
    assert stored, "the run's snags reached the database"
    assert [s["snag_id"] for s in stored] == [s["snag_id"] for s in live]

    # Resolving a snag by its id reaches the same episode through either projection.
    by_id = {s["snag_id"]: s for s in stored}
    for snag in live:
        row = by_id[snag["snag_id"]]
        assert row["problem"] == snag["problem"]
        assert row["codelet_count"] == snag["codelet_count"]
        assert row["description"] == snag["description"]


@pytest.mark.asyncio
async def test_snag_identifier_agrees_across_both_projections(app_client):
    run_id = await _run_until_snagged(app_client)

    live, stored = await _both_projections(app_client, run_id)
    _assert_same_snags(live, stored)
    # Episodic Memory numbers its snags from one, and that is what both projections show.
    assert [s["snag_id"] for s in live] == list(range(1, len(live) + 1))


@pytest.mark.asyncio
async def test_snag_identifier_survives_a_memory_clear(app_client):
    """The agreement holds where the two id spaces visibly differ.

    Clearing episodic memory ends the Training Session: the descriptions go and the
    memory's counter starts again at one, while the table's own key carries on from
    where it was.  The snags of the run after the clear are therefore numbered from one
    in the memory and from something larger in the table, and both projections report
    the memory's numbering.
    """
    first = await _run_until_snagged(app_client)
    before = (await app_client.get("/api/memory")).json()["snags"]
    assert before, "the run recorded no snag, so this test proves nothing"

    await app_client.delete("/api/memory")

    second = await _run_until_snagged(app_client)
    live, stored = await _both_projections(app_client, second)
    _assert_same_snags(live, stored)
    assert [s["snag_id"] for s in stored] == list(range(1, len(stored) + 1))
