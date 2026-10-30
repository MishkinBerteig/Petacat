"""Which snags a run records: the ones it adds to the shared memory, once each.

Episodic Memory is shared by episodic runs, so a run starts out holding every
earlier run's snags.  The recording sink used to find a run's new snags by comparing
the memory's length with its own buffer's, and ``flush`` empties that buffer.  So every
run that snagged wrote all of the memory's earlier snags again under its own id, and
again after each flush, and relabelled the memory's copies with its own run id.

No database is needed: ``flush`` only stages rows on the session it is given.
"""

import os

import pytest

from server.engine.memory import EpisodicMemory, SnagDescription
from server.engine.metadata import MetadataProvider
from server.engine.runner import STATUS_RUNNING, EngineRunner
from server.models.run import RunStateCapture, SnagDescriptionRow
from server.services.sinks import AuditSink, NormalSink

# The runs here execute arithmetic the numeric substrate owns, so each test runs once
# per backend in the matrix. See tests/conftest.py.
pytestmark = pytest.mark.numeric_matrix

SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")

#: ``xyz`` has no successor to the ``z``, the snag §4.7.2 is written about.  Seed 34
#: is the one ``tests/e2e/test_snag_identity.py`` uses because it snags.
PROBLEM = ("abc", "abd", "xyz")
SEED = 34
RUN_ID = 2
EARLIER_RUN_ID = 1


class _StagingSession:
    """What ``flush`` needs of an ``AsyncSession``: somewhere to stage rows."""

    def __init__(self) -> None:
        self.rows: list = []

    def add(self, row) -> None:
        self.rows.append(row)

    def of(self, kind: type) -> list:
        return [r for r in self.rows if isinstance(r, kind)]


@pytest.fixture
def meta():
    return MetadataProvider.from_seed_data(SEED_DIR)


def _inherited_memory() -> tuple[EpisodicMemory, SnagDescription]:
    """A session memory holding one snag an earlier run recorded."""
    memory = EpisodicMemory()
    earlier = SnagDescription(
        problem=("abc", "abd", "ijk"),
        codelet_count=421,
        temperature=100.0,
        theme_pattern={},
        description="an earlier run's snag",
        run_id=EARLIER_RUN_ID,
    )
    memory.store_snag(earlier)
    return memory, earlier


async def _run_with_flushes(meta, memory, sink) -> _StagingSession:
    """Step in batches of 100 codelets with a flush after each, as the service does."""
    session = _StagingSession()
    runner = EngineRunner(meta)
    runner.init_mcat(*PROBLEM, seed=SEED, memory=memory, sink=sink)
    done = False
    while not done and runner.ctx.codelet_count < 3000:
        for _ in range(100):
            runner.status = STATUS_RUNNING
            result = runner.step_mcat()
            if result.answer_found or result.gave_up:
                done = True
                break
        await sink.flush(session, RUN_ID)
    runner.finish()
    await sink.flush(session, RUN_ID)
    return session


@pytest.mark.parametrize("sink_type", [NormalSink, AuditSink])
async def test_a_run_records_the_snags_it_adds_and_none_it_inherited(meta, sink_type):
    memory, earlier = _inherited_memory()

    session = await _run_with_flushes(meta, memory, sink_type())

    added = [s for s in memory.snags if s is not earlier]
    assert added, "the run added no snag, so this test proves nothing"
    rows = session.of(SnagDescriptionRow)
    # Each snag the run added, once, however many flushes and snag events there were.
    assert [r.snag_id for r in rows] == [s.snag_id for s in added]
    assert {r.run_id for r in rows} == {RUN_ID}
    # The inherited snag keeps the run that found it.
    assert earlier.run_id == EARLIER_RUN_ID
    assert all(s.run_id == RUN_ID for s in added)


async def test_a_rediscovered_snag_is_not_written_again(meta):
    """A run that only meets snags the memory already holds writes no snag rows.

    The second run has the same problem and seed, so it meets the same impasses, and
    ``snag_present`` keeps the memory from storing them twice.  Its snag events still
    fire, which is what used to make the sink write every snag in the memory again.
    """
    memory = EpisodicMemory()
    first = await _run_with_flushes(meta, memory, NormalSink())
    assert first.of(SnagDescriptionRow), "the first run recorded no snag"
    held = list(memory.snags)

    second = await _run_with_flushes(meta, memory, NormalSink())

    assert memory.snags == held
    assert second.of(SnagDescriptionRow) == []


async def test_a_run_still_takes_its_start_capture(meta):
    """Taking the inherited snags at run start leaves Normal's start capture in place."""
    memory, _ = _inherited_memory()

    session = await _run_with_flushes(meta, memory, NormalSink())

    assert [c.boundary for c in session.of(RunStateCapture)] == ["start", "end"]


async def test_a_snag_row_carries_metacats_explanation_and_the_translated_rule(meta):
    """``abstract-snag-description`` (``memory.ss:468-477``) keeps the snag event's
    explanation and the translated rule's English, and so does the row staged for them.

    ``abc -> abd; xyz`` fails on the ``z`` or on a group ending in it; either way the
    sentence is the reference's ``get-explanation`` (``trace.ss:1097``), recorded from
    Metacat 1.2 in ``tests/lockstep/snag_explanations_metacat.tsv``.
    """
    memory = EpisodicMemory()
    session = await _run_with_flushes(meta, memory, NormalSink())

    rows = session.of(SnagDescriptionRow)
    assert rows, "the run recorded no snag"
    for row, snag in zip(rows, memory.snags):
        assert row.explanation == snag.explanation
        assert row.translated_rule_description == snag.translated_rule_description
        assert row.explanation.startswith("changing the letter-category of the ")
        assert row.explanation.endswith(" to its successor is not possible in xyz")
        assert row.translated_rule_description
