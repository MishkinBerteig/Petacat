"""An answer's unjustified theme pattern is Metacat's list, and it survives the database.

``get-unjustified-theme-pattern`` (``answers.ss:239-264``) returns a list of
``(dimension relation)`` entries that can hold two entries for one dimension.  It is
stored as a JSON list of pairs, comes back as a list of tuples, and is served as a list.
A row stored when the pattern was a mapping (one relation per dimension) is not read: this
is a development system with no migration, and the Episodic Memory is cleared instead.

Requires: a local Postgres -- start it with `scripts/dev.sh db`.
"""

import os

import pytest

DIRECTION = "plato-direction-category"
STRING_POSITION = "plato-string-position-category"


def _service():
    from server.engine.metadata import MetadataProvider
    from server.services.configuration_store import ConfigurationStore
    from server.services.run_service import RunService

    seed_dir = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")
    return RunService(ConfigurationStore(MetadataProvider.from_standard_configuration(seed_dir)))


def _answer_row(unjustified):
    from server.models.run import AnswerDescriptionRow

    return AnswerDescriptionRow(
        answer_id=1, run_id=1, problem=["abc", "abd", "xyz", "wyz"],
        top_rule_description="rule", bottom_rule_description="",
        top_rule_signature=[["intrinsic", "x"]], bottom_rule_signature=[["intrinsic", "x"]],
        unjustified_themes=unjustified,
    )


@pytest.mark.asyncio
async def test_two_entries_for_one_dimension_survive_a_restart_and_are_served_as_a_list(db_session):
    from server.services.run_service import _global_memory

    stored = [[STRING_POSITION, "opposite"], [STRING_POSITION, "identity"], [DIRECTION, "identity"]]
    db_session.add(_answer_row(stored))
    await db_session.commit()

    service = _service()
    await service.rehydrate_memory(db_session)

    assert _global_memory.answers[0].unjustified_themes == [
        (STRING_POSITION, "opposite"), (STRING_POSITION, "identity"), (DIRECTION, "identity"),
    ]
    live = service.get_memory_state()["answers"][0]["unjustified_themes"]
    from_db = (await service.get_memory_state_from_db(db_session))["answers"][0]["unjustified_themes"]
    assert [list(e) for e in live] == [list(e) for e in from_db] == stored


@pytest.mark.asyncio
async def test_a_row_stored_in_the_old_mapping_form_is_not_read(db_session):
    db_session.add(_answer_row({STRING_POSITION: "opposite"}))
    await db_session.commit()

    with pytest.raises(ValueError, match="clear the Episodic Memory"):
        await _service().rehydrate_memory(db_session)
