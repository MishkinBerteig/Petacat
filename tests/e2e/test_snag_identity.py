"""A snag is the same snag whichever endpoint served it.

A snag description records a failure episode (§4.7.2), and Episodic Memory stamps each
one with an identifier of its own.  Two endpoints project a snag: ``GET /api/memory``
reads the live memory, and ``GET /api/runs/{id}/memory`` reads the stored rows for a
Normal Run.  Both report that one identifier, so a snag read from either is
recognisable as the same snag.

Requires: a local Postgres — start it with `scripts/dev.sh db`.
"""

import pytest

#: Reseeded from 99999 to 34 when the snag response gained its restart
#: (``answers.ss:1189-1191``): a snag now empties the Coderack and reposts, so the run
#: 99999 used to take no longer exists and that seed reaches 3,000 codelets without
#: snagging.  Which answers a seed reaches is outside the gates on purpose — the
#: standard is expected-range agreement — and what this file is about is snag
#: *identity*, which needs some seed that snags.
#:
#: The parity repair (b1fd7a8..c20abed) moved this seed's trajectory too, so the count
#: quoted here changed from five to four; 34 is kept because the precondition it has to
#: meet is "snags at all", and four against a floor of one is not a close thing.  The
#: run reaches the 3,000-codelet budget rather than a stopping state, so those snags are
#: not competing with an early answer for the budget either.
SEED = 34

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


@pytest.mark.asyncio
async def test_each_snag_is_written_once_however_many_runs_meet_it(app_client, db_session):
    """A run writes the snags it added to the session's memory, not the ones it met.

    The second run has the first one's problem and seed, so it meets the same impasses;
    ``snag_present`` keeps the memory from storing them again, but the snag events
    still fire.  Each of those used to write every snag in the memory again under the
    run that met it, so the table grew by the whole memory per snagging run.
    """
    from sqlalchemy import func, select

    from server.models.run import SnagDescriptionRow, TraceEventRow

    first = await _run_until_snagged(app_client)
    second = await _run_until_snagged(app_client)

    met_again = (
        await db_session.execute(
            select(func.count()).select_from(TraceEventRow).where(
                TraceEventRow.run_id == second, TraceEventRow.event_type == "snag"
            )
        )
    ).scalar()
    assert met_again, "the second run met no snag, so this test proves nothing"

    rows = (
        await db_session.execute(select(SnagDescriptionRow).order_by(SnagDescriptionRow.id))
    ).scalars().all()
    live = (await app_client.get("/api/memory")).json()["snags"]
    assert [r.snag_id for r in rows] == [s["snag_id"] for s in live]
    assert {r.run_id for r in rows} == {first}


@pytest.mark.asyncio
async def test_rehydrating_the_memory_keeps_one_row_per_snag(db_session):
    """Rows the old sink copied are dropped when the memory is loaded from the table.

    The first row is the one the run that found the snag wrote, so it is the one kept,
    with that run's id.  Rows from before the identifier was recorded have none, and are
    matched on what they describe.
    """
    import os

    from sqlalchemy import select

    from server.engine.metadata import MetadataProvider
    from server.models.run import SnagDescriptionRow
    from server.services.run_service import RunService, _global_memory

    def row(run_id: int, snag_id: int | None, codelet_count: int) -> SnagDescriptionRow:
        return SnagDescriptionRow(
            snag_id=snag_id,
            run_id=run_id,
            problem=list(SNAGGING_PROBLEM.values()),
            codelet_count=codelet_count,
            temperature=100.0,
            theme_pattern={},
            description="change LetterCtgy by succ",
        )

    db_session.add_all([
        row(9, 1, 421), row(10, 1, 421), row(11, 1, 421),
        row(18, 7, 1004), row(19, 1, 421), row(19, 7, 1004),
        row(3, None, 77), row(4, None, 77),
    ])
    await db_session.commit()

    seed_dir = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")
    await RunService(MetadataProvider.from_seed_data(seed_dir)).rehydrate_memory(db_session)

    assert sorted(
        (s.snag_id, s.run_id) for s in _global_memory.snags if s.run_id != 3
    ) == [(1, 9), (7, 18)]
    assert [s.run_id for s in _global_memory.snags].count(3) == 1
    kept = (
        await db_session.execute(select(SnagDescriptionRow).order_by(SnagDescriptionRow.id))
    ).scalars().all()
    assert [(r.snag_id, r.run_id) for r in kept] == [(1, 9), (7, 18), (None, 3)]


@pytest.mark.asyncio
async def test_rehydrating_keeps_the_explanation_and_falls_back_for_old_rows(db_session):
    """Rows carry Metacat's explanation (``memory.ss:332``) and the translated rule's
    English (``memory.ss:331``); a row written before they were stored has NULL for
    both and rehydrates with the older sentence, not an error."""
    import os

    from server.engine.answer_comparison import snag_explanation_for  # noqa: F401
    from server.engine.metadata import MetadataProvider
    from server.engine.snag_explanation import snag_explanation_text
    from server.models.run import SnagDescriptionRow
    from server.services.run_service import RunService, _global_memory

    explanation = (
        "changing the letter-category of the letter z to its successor "
        "is not possible in xyz"
    )
    db_session.add_all([
        SnagDescriptionRow(
            snag_id=1, run_id=1, problem=list(SNAGGING_PROBLEM.values()), codelet_count=273,
            temperature=100.0, theme_pattern={}, description="change LetterCtgy by succ",
            explanation=explanation,
            translated_rule_description="Change letter-category of letter `z' to its successor",
        ),
        SnagDescriptionRow(
            snag_id=2, run_id=1, problem=list(SNAGGING_PROBLEM.values()), codelet_count=421,
            temperature=100.0, theme_pattern={}, description="change LetterCtgy by pred",
        ),
    ])
    await db_session.commit()

    seed_dir = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")
    service = RunService(MetadataProvider.from_seed_data(seed_dir))
    await service.rehydrate_memory(db_session)

    new, old = sorted(_global_memory.snags, key=lambda s: s.snag_id)[:2]
    assert new.explanation == explanation
    assert new.translated_rule_description.startswith("Change letter-category")
    assert snag_explanation_text(new) == explanation
    assert old.explanation == ""
    assert snag_explanation_text(old).startswith('the rule "change LetterCtgy by pred" cannot be applied to ')

    served = service.get_memory_state()["snags"]
    assert [s["explanation"] for s in served][0] == explanation
    from_db = (await service.get_memory_state_from_db(db_session))["snags"]
    assert from_db[0]["explanation"] == explanation
    assert from_db[1]["explanation"].startswith('the rule "change LetterCtgy by pred"')
    assert from_db[1]["translated_rule_description"] == ""
