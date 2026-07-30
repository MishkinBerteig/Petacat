"""A recorded capture renders exactly as the same state renders live (WP3.9).

The review surfaces reuse ``WorkspaceView``, ``SlipnetView``, ``ThemespaceView`` and
``TraceView`` against *recorded* state, which only works if a projected capture is
indistinguishable from what those components are fed by a live run.  That is a
property, not a hope, so it is checked as one.

The decisive test is ``test_a_projected_capture_matches_the_live_serializer``.  It
takes one state two ways — projected straight from the record, and restored into a
fresh runner and serialized by ``server/engine/serialization.py`` — and requires the
two to be equal field for field.  Nothing else in this file would catch a display
field drifting in the serializer while the projection kept emitting the old one, which
is the way a second representation rots.

Why the capture point is 750 codelets, and not the end of a run
---------------------------------------------------------------
The comparison needs a state rich enough to be worth comparing — bonds, groups,
bridges and rules all present — *and* one that ``restore_run_state`` can actually
load.  Today those two requirements conflict at the end of a run: ``GRAPH_TYPES``
lists ``TraceEvent`` but none of ``AnswerEvent``, ``ClampEvent`` or ``SnagEvent``, so
restoring any capture taken after an answer, a snag or a clamp raises
``StateGraphError``.  ``abc→abd; mrrjjj`` at seed 12345 has seven bonds, two groups,
four bridges and a built rule at 750 codelets — it answers at 783 — and has recorded
none of those three event types yet, so it satisfies both.

``test_the_projection_does_not_need_the_restore_path`` pins the reason that matters:
the projection renders the end-of-run captures the restore path currently refuses,
which is why the review surface reads the record rather than rebuilding objects from
it.
"""

from __future__ import annotations

import json
import os

import pytest

from server.engine.metadata import MetadataProvider
from server.engine.runner import EngineRunner
from server.engine.serialization import (
    serialize_themespace_state,
    serialize_workspace_state,
)
from server.engine.state_graph import (
    StateGraphError,
    capture_run_state,
    restore_run_state,
)
from server.services.capture_projection import (
    CaptureFormatError,
    project_capture,
    project_coderack,
    project_memory,
    project_slipnet,
    project_themespace,
    project_trace,
    project_workspace,
)

SEED_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "seed_data",
)

PROBLEM = ("abc", "abd", "mrrjjj")
SEED = 12345

#: Far enough in for the Workspace to hold structures of every kind — a built rule
#: included, so the rule projection is inside the equality check rather than beside it
#: — and early enough that no ``AnswerEvent``/``SnagEvent``/``ClampEvent`` has been
#: recorded.  See the module docstring for why the second half of that matters.
RESTORABLE_POINT = 750


@pytest.fixture(scope="module")
def meta() -> MetadataProvider:
    return MetadataProvider.from_seed_data(SEED_DIR)


def _run_to(meta: MetadataProvider, codelets: int) -> EngineRunner:
    runner = EngineRunner(meta)
    runner.init_mcat(*PROBLEM, seed=SEED)
    while runner.ctx.codelet_count < codelets:
        runner.step_mcat()
    return runner


@pytest.fixture(scope="module")
def mid_run_capture(meta: MetadataProvider) -> dict:
    """A capture round-tripped through JSON, as a stored one has been."""
    return json.loads(json.dumps(capture_run_state(_run_to(meta, RESTORABLE_POINT).ctx)))


@pytest.fixture(scope="module")
def end_of_run_capture(meta: MetadataProvider) -> dict:
    runner = EngineRunner(meta)
    runner.init_mcat(*PROBLEM, seed=SEED)
    runner.run_mcat(max_steps=1500)
    return json.loads(json.dumps(capture_run_state(runner.ctx)))


# ─────────────────────────────────────────────────────────────────────────────
# The decisive test
# ─────────────────────────────────────────────────────────────────────────────


def test_a_projected_capture_matches_the_live_serializer(meta, mid_run_capture):
    """The record renders as the live state does — every field, not a summary.

    If this fails, the review surfaces are showing something the dashboard would not,
    and reusing the components is no longer justified.
    """
    live = EngineRunner(meta)
    live.init_mcat(*PROBLEM, seed=SEED)
    restore_run_state(live, mid_run_capture)

    assert project_workspace(mid_run_capture, meta) == serialize_workspace_state(live.ctx)
    assert project_themespace(mid_run_capture, meta) == serialize_themespace_state(live.ctx)

    # The Slipnet and Coderack endpoints build their shapes inline in ``RunService``
    # rather than through ``serialization.py``, so the comparison is against that.
    assert project_slipnet(mid_run_capture, meta) == {
        name: {
            "activation": node.activation,
            "conceptual_depth": node.conceptual_depth,
            "frozen": node.frozen,
        }
        for name, node in live.ctx.slipnet.nodes.items()
    }
    assert project_coderack(mid_run_capture) == {
        "total_count": live.ctx.coderack.total_count,
        "type_counts": live.ctx.coderack.get_codelet_type_counts(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# What the projection has to survive
# ─────────────────────────────────────────────────────────────────────────────


def test_the_projection_does_not_need_the_restore_path(meta, end_of_run_capture):
    """It renders the captures ``restore_run_state`` currently refuses.

    ``GRAPH_TYPES`` omits ``TraceEvent``'s three subclasses, so a Run-end capture from
    a run that answered cannot be restored.  Reading the record rather than rebuilding
    objects from it is what keeps the review surface working meanwhile — and this test
    is where that stops being an assertion in a docstring.

    It is written to keep passing once the engine adds those types: it requires the
    projection to work, and only records the restore failure if there still is one.
    """
    projected = project_capture(end_of_run_capture, meta)
    assert projected["workspace"]["initial"] == PROBLEM[0]
    assert projected["trace"], "an end-of-run capture has trace events"

    replay = EngineRunner(meta)
    replay.init_mcat(*PROBLEM, seed=SEED)
    try:
        restore_run_state(replay, end_of_run_capture)
    except StateGraphError as exc:
        assert "unknown graph type" in str(exc)


def test_only_built_structures_are_shown(meta, mid_run_capture):
    """As the live serializer does: proposed and evaluated structures are not on
    screen, so a recorded view that showed them would not be the same view."""
    workspace = project_workspace(mid_run_capture, meta)
    for by_string in (workspace["bonds"], workspace["groups"]):
        for structures in by_string.values():
            assert all(s["built"] for s in structures)
    for key in ("top_bridges", "vertical_bridges", "bottom_bridges"):
        assert all(b["built"] for b in workspace[key])


def test_a_bridge_carries_its_slippages(meta, mid_run_capture):
    """The slippages are the substance of a bridge, and identity is decided by node
    name because that is what the capture stores instead of the node."""
    workspace = project_workspace(mid_run_capture, meta)
    bridges = workspace["top_bridges"] + workspace["vertical_bridges"]
    assert bridges, "the fixture point has bridges"
    mappings = [cm for b in bridges for cm in b["concept_mappings"]]
    assert mappings
    for cm in mappings:
        assert cm["is_slippage"] == (cm["from"] != cm["to"])


def test_a_rule_reports_the_english_the_run_produced(meta, mid_run_capture):
    """Transcription is cached on the Rule as it is built, so the review shows the
    run's own words rather than re-deriving them from the clauses."""
    workspace = project_workspace(mid_run_capture, meta)
    rules = workspace["top_rules"] + workspace["bottom_rules"]
    assert rules, "the fixture point has built rules"
    assert all(r["english"] for r in rules)


def test_the_trace_and_memory_come_back_whole(meta, mid_run_capture):
    events = project_trace(mid_run_capture)
    assert [e["event_number"] for e in events] == sorted(
        e["event_number"] for e in events
    )
    assert all(e["event_type"] for e in events)

    memory = project_memory(mid_run_capture)
    assert set(memory) == {"answers", "snags"}


def test_an_unrenderable_format_version_is_refused(meta, mid_run_capture):
    """Refusing beats rendering plausible nonsense from a format this build predates."""
    future = dict(mid_run_capture, format_version=99)
    with pytest.raises(CaptureFormatError) as exc:
        project_capture(future, meta)
    assert "99" in str(exc.value)


def test_a_start_capture_renders_as_an_untouched_workspace(meta):
    """Normal's first capture is taken before the first codelet, and a review that
    could not render it would have nothing to compare the end against."""
    runner = EngineRunner(meta)
    runner.init_mcat(*PROBLEM, seed=SEED)
    projected = project_capture(capture_run_state(runner.ctx), meta)

    assert projected["codelet_count"] == 0
    assert projected["temperature"] == 100.0
    assert projected["workspace"]["bonds_per_string"] == {t: 0 for t in PROBLEM}
    assert projected["coderack"]["total_count"] > 0
