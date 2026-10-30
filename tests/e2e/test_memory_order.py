"""Episodic Memory lists answers in Metacat's order, from memory and after a restart.

Metacat conses each new description onto the front of ``answer-descriptions`` and
``snag-descriptions`` (``memory.ss:101-111``), so ``get-answers`` is newest first, the
reminding loop and ``get-equivalent-snag`` walk it that way, and the Memory window draws
it oldest first.  The database rows come back in whatever order they were written, which
concurrent runs do not guarantee is the order the memory made them in, so a restart
orders them by the memory's own identifier.

Requires: a local Postgres -- start it with `scripts/dev.sh db`.
"""

import os

import pytest


def _service():
    from server.engine.metadata import MetadataProvider
    from server.services.run_service import RunService

    seed_dir = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")
    return RunService(MetadataProvider.from_seed_data(seed_dir))


def _answer_row(answer_id, text):
    from server.models.run import AnswerDescriptionRow

    return AnswerDescriptionRow(
        answer_id=answer_id, run_id=1, problem=["abc", "abd", "xyz", text],
        top_rule_description=f"rule {text}", bottom_rule_description="",
        top_rule_signature=[["intrinsic", text]], bottom_rule_signature=[["intrinsic", text]],
    )


@pytest.mark.asyncio
async def test_rehydrating_restores_newest_first_whatever_order_the_rows_were_written_in(db_session):
    from server.services.run_service import _global_memory

    # Written out of order, and one from before identifiers were recorded (oldest).
    db_session.add_all([
        _answer_row(3, "c"), _answer_row(1, "a"), _answer_row(None, "z"), _answer_row(2, "b"),
    ])
    await db_session.commit()

    service = _service()
    await service.rehydrate_memory(db_session)

    assert [a.problem[3] for a in _global_memory.answers] == ["c", "b", "a", "z"]
    assert [a.problem[3] for a in _global_memory.answers_oldest_first] == ["z", "a", "b", "c"]
    # Both projections list them the way the Memory window does: oldest first.
    live = [a["problem"][3] for a in service.get_memory_state()["answers"]]
    stored = [a["problem"][3] for a in (await service.get_memory_state_from_db(db_session))["answers"]]
    assert live == stored == ["z", "a", "b", "c"]


@pytest.mark.asyncio
async def test_a_forgotten_answer_leaves_the_rest_in_order(db_session):
    from server.services.run_service import _global_memory

    db_session.add_all([_answer_row(1, "a"), _answer_row(2, "b"), _answer_row(3, "c")])
    await db_session.commit()
    service = _service()
    await service.rehydrate_memory(db_session)

    assert await service.forget_answer(db_session, 2)
    assert [a.problem[3] for a in _global_memory.answers] == ["c", "a"]
