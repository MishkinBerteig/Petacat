"""The configuration stamp (plan 3.8), before the configuration entity exists.

Every stored artefact reaches the ``config_hash`` of the configuration that made it through its
run row (``answer_descriptions``, ``snag_descriptions``, ``run_state_captures``) or its Training Mode Session
row (``training_mode_session_runs``, and ``training_memory_merges`` through ``(session_id, problem_id, seed)``).
So no column is added: the link is the stamp.  This test runs a Normal Run and an Audit Run, and
checks that every row the sinks wrote has a ``run_id`` whose run carries a ``config_hash``.

Requires: a local Postgres named by TEST_DATABASE_URL.
"""

import os

import pytest
from sqlalchemy import func, select

from server.models.run import AnswerDescriptionRow, Run, RunStateCapture, SnagDescriptionRow
from server.models.training_mode_session import TrainingModeSession, TrainingModeSessionRun


def _service():
    from server.engine.metadata import MetadataProvider
    from server.services.configuration_store import ConfigurationStore
    from server.services.run_service import RunService

    seed_dir = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")
    return RunService(ConfigurationStore(MetadataProvider.from_standard_configuration(seed_dir)))


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["normal", "audit"])
async def test_every_artefact_a_run_stores_reaches_the_runs_config_hash(db_session, mode):
    service = _service()
    info = await service.create_run(db_session, "abc", "abd", "ijk", seed=3, mode=mode)
    await service.run_to_completion(db_session, info.run_id, max_steps=3000)
    await db_session.commit()

    run = await db_session.get(Run, info.run_id)
    assert run.config_hash

    # No write path stores a row without a run.  (The whole table is checked for that alone:
    # other tests in this database delete run rows directly, leaving their artefacts behind.)
    for model in (AnswerDescriptionRow, SnagDescriptionRow, RunStateCapture):
        unlinked = (await db_session.execute(
            select(func.count()).select_from(model).where(model.run_id.is_(None))
        )).scalar_one()
        assert unlinked == 0, f"{model.__tablename__} has rows with no run_id"

    # This run's own rows reach its config_hash, and there are some (the check is not vacuous).
    for model in (AnswerDescriptionRow, RunStateCapture):
        hashes = (await db_session.execute(
            select(Run.config_hash).select_from(model)
            .join(Run, Run.id == model.run_id).where(model.run_id == info.run_id)
        )).scalars().all()
        assert hashes and all(h == run.config_hash for h in hashes), model.__tablename__


def test_the_session_tables_carry_the_link_by_construction():
    """A Training Mode Session and each of its runs record a config_hash that cannot be null; a memory merge
    names its run by (session_id, problem_id, seed), the unique key of ``training_mode_session_runs``."""
    assert not TrainingModeSession.__table__.c.config_hash.nullable
    assert not TrainingModeSessionRun.__table__.c.config_hash.nullable
    from server.models.training_mode_session import SessionMemoryMerge

    merge = SessionMemoryMerge.__table__.c
    assert {"session_id", "problem_id", "seed"} <= set(merge.keys())
