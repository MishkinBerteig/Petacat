"""A captured run restores to a state that continues identically (WP3.4, defect D1).

The claim Normal mode makes is *reproducibility by re-execution*: reload a recorded
state, run on, and arrive where the uninterrupted run arrived.  That is a strong claim
and it is checkable exactly, so these tests check it exactly rather than comparing
summaries — an incomplete capture usually still produces a plausible-looking run.

The decisive test is ``test_a_restored_run_continues_identically``.  Everything above
it exists to localise a failure when it fires.
"""

from __future__ import annotations

import json
import os

import pytest

from server.engine.metadata import MetadataProvider
from server.engine.runner import EngineRunner
from server.engine.state_graph import (
    FORMAT_VERSION,
    StateGraphError,
    capture_run_state,
    restore_run_state,
)

# Every test here executes arithmetic the numeric substrate owns, so each one runs
# once per backend in the matrix. See tests/conftest.py.
pytestmark = pytest.mark.numeric_matrix

SEED_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "seed_data",
)

PROBLEM = ("abc", "abd", "mrrjjj")
SEED = 42

#: A problem and seed that reaches an answer *and* snags and clamps on the way, so its
#: trace contains AnswerEvent, ClampEvent and SnagEvent rather than only the base type.
#: The ordinary round-trip fixture above does not, which is how a whole class of event
#: went unrestorable without any test noticing.
#:
#: Reseeded from 12345 to 34 when the snag response gained its restart
#: (``answers.ss:1189-1191``), and from 34 to 12 when the bond round replaced the
#: local-density walk and the neighbour candidate set (``bonds.ss:136-160``,
#: ``workspace-objects.ss:375-423``).  Both times for the same reason: which answer a
#: given seed reaches is not a gate — the standard is expected-range agreement — but
#: this test needs *some* seed whose trace carries all three rich event types.  12
#: answers, snags *and* clamps inside 3,000 codelets under all three numeric backends.
ANSWERING_PROBLEM = ("abc", "abd", "xyz")
ANSWERING_SEED = 12


@pytest.fixture(scope="module")
def meta() -> MetadataProvider:
    return MetadataProvider.from_seed_data(SEED_DIR)


def _fresh(meta) -> EngineRunner:
    runner = EngineRunner(meta)
    runner.init_mcat(*PROBLEM, seed=SEED)
    return runner


def _fresh_answering(meta) -> EngineRunner:
    runner = EngineRunner(meta)
    runner.init_mcat(*ANSWERING_PROBLEM, seed=ANSWERING_SEED)
    return runner


def _fingerprint(runner: EngineRunner) -> dict:
    """Everything that must agree for two runs to be in the same state.

    Structures are fingerprinted by their content rather than their Python identity,
    since a restored run holds different objects by construction.
    """
    ctx = runner.ctx
    ws = ctx.workspace

    def structures(items):
        return sorted(
            (type(s).__name__, s.proposal_level, round(s.strength), s.time_stamp)
            for s in items
        )

    return {
        "status": runner.status,
        "codelet_count": ctx.codelet_count,
        "rng_calls": ctx.rng.call_count,
        "temperature": round(ctx.temperature.value, 6),
        "answer": ws.answer_string.text if ws.answer_string else None,
        "bonds": structures(b for s in ws.all_strings for b in s.bonds),
        "groups": structures(g for s in ws.all_strings for g in s.groups),
        "bridges": structures(
            ws.top_bridges + ws.bottom_bridges + ws.vertical_bridges
        ),
        "rules": structures(ws.top_rules + ws.bottom_rules),
        "objects": sorted(
            (o.left_string_pos, o.right_string_pos, len(o.descriptions))
            for o in ws.all_objects
        ),
        "coderack": sorted(
            (c.codelet_type, c.urgency, c.time_stamp)
            for b in ctx.coderack.bins
            for c in b.codelets
        ),
        "trace": [(e.event_number, e.event_type) for e in ctx.trace.events],
        "slipnet": {n: round(x.activation, 6) for n, x in ctx.slipnet.nodes.items()},
        "themes": sorted(
            (c.theme_type, c.dimension, t.relation, round(t.activation, 6))
            for c in ctx.themespace.clusters
            for t in c.themes
        ),
        "ids": ctx.ids.snapshot(),
    }


# --- the capture is well-formed --------------------------------------------


def test_capture_is_json_serialisable(meta):
    """The format is meant to be inspectable and versionable, which means real JSON."""
    runner = _fresh(meta)
    runner.run_mcat(max_steps=600)
    blob = json.dumps(capture_run_state(runner.ctx))
    assert json.loads(blob)["format_version"] == FORMAT_VERSION


def test_capture_keeps_object_valued_codelet_arguments(meta):
    """The specific thing the old serializer threw away.

    ``serialize_coderack_state`` filtered arguments with
    ``if not hasattr(v, '__dict__')``, which discarded exactly the ones that matter: a
    live rack holds ``Bond``, ``Bridge``, ``Rule`` and ``SlipnetNode`` arguments, and an
    evaluator restored without its structure has nothing to evaluate.
    """
    runner = _fresh(meta)
    runner.run_mcat(max_steps=900)
    state = capture_run_state(runner.ctx)

    live = [
        (c.codelet_type, k, type(v).__name__)
        for b in runner.ctx.coderack.bins
        for c in b.codelets
        for k, v in c.arguments.items()
        if hasattr(v, "__dict__") or hasattr(v, "conceptual_depth")
    ]
    assert live, "the rack must hold object-valued arguments for this to test anything"

    restored = EngineRunner(meta)
    restored.init_mcat(*PROBLEM, seed=SEED)
    restore_run_state(restored, state)

    recovered = [
        (c.codelet_type, k, type(v).__name__)
        for b in restored.ctx.coderack.bins
        for c in b.codelets
        for k, v in c.arguments.items()
        if hasattr(v, "__dict__") or hasattr(v, "conceptual_depth")
    ]
    assert sorted(recovered) == sorted(live)


def test_restored_slipnet_nodes_are_the_live_ones(meta):
    """Nodes are referenced by name, not copied.

    A capture that copied them would leave a restored bond pointing at a *different*
    ``plato-successor`` from the one the Slipnet spreads activation through, and the
    run would drift in a way that is very hard to see.
    """
    runner = _fresh(meta)
    runner.run_mcat(max_steps=600)
    state = capture_run_state(runner.ctx)

    restored = EngineRunner(meta)
    restored.init_mcat(*PROBLEM, seed=SEED)
    restore_run_state(restored, state)

    for s in restored.ctx.workspace.all_strings:
        for bond in s.bonds:
            assert bond.bond_category is restored.ctx.slipnet.nodes[bond.bond_category.name]


def test_cycles_and_cross_references_survive(meta):
    """The graph is cyclic; restoring must reproduce the cycles, not break them."""
    runner = _fresh(meta)
    runner.run_mcat(max_steps=900)
    state = capture_run_state(runner.ctx)

    restored = EngineRunner(meta)
    restored.init_mcat(*PROBLEM, seed=SEED)
    restore_run_state(restored, state)
    ws = restored.ctx.workspace

    for s in ws.all_strings:
        for bond in s.bonds:
            # A bond's objects must be the very objects in the string, and each must
            # be a string this Workspace owns.
            assert bond.from_object in bond.from_object.string.objects
            assert bond.from_object.string in ws.all_strings
            assert bond.to_object.string in ws.all_strings

    for bridge in ws.top_bridges + ws.bottom_bridges + ws.vertical_bridges:
        assert bridge.object1.string in ws.all_strings
        assert bridge.object2.string in ws.all_strings

    for s in ws.all_strings:
        for group in s.groups:
            for member in group.objects:
                assert member.string is s


def test_a_new_field_cannot_be_silently_dropped(meta):
    """Reflection is the point: an uncapturable value raises rather than vanishing.

    The display serializer this replaces enumerated fields by hand, so a field added
    to a structure was simply absent and nothing failed. Here the default is
    "captured", and something genuinely unrepresentable is an error.
    """
    runner = _fresh(meta)
    runner.run_mcat(max_steps=200)
    bond = next(b for s in runner.ctx.workspace.all_strings for b in s.bonds)
    bond.surprise = object()
    with pytest.raises(StateGraphError, match="cannot capture"):
        capture_run_state(runner.ctx)


def test_a_foreign_format_version_is_refused(meta):
    runner = _fresh(meta)
    runner.run_mcat(max_steps=100)
    state = capture_run_state(runner.ctx)
    state["format_version"] = FORMAT_VERSION + 1

    other = EngineRunner(meta)
    other.init_mcat(*PROBLEM, seed=SEED)
    with pytest.raises(StateGraphError, match="format version"):
        restore_run_state(other, state)


# --- the decisive one ------------------------------------------------------


def test_restoring_reproduces_the_captured_state(meta):
    """Capture, restore, and the two runs must be indistinguishable *before* continuing."""
    runner = _fresh(meta)
    runner.run_mcat(max_steps=900)
    state = json.loads(json.dumps(capture_run_state(runner.ctx)))

    restored = EngineRunner(meta)
    restored.init_mcat(*PROBLEM, seed=SEED)
    restore_run_state(restored, state)
    restored.status = runner.status

    assert _fingerprint(restored) == _fingerprint(runner)


def test_a_restored_run_continues_identically(meta):
    """The property Normal mode's promise rests on.

    Run to a mid-point, capture, and let the original run on.  Separately, restore the
    capture into a *fresh* runner and run it on by the same amount.  The two must end
    in the same state — not merely reach the same answer, which a badly incomplete
    capture can still manage by luck.

    Passing through ``json`` on the way is deliberate: it is how the state will
    actually travel, and it catches anything that survives in memory but not through
    serialisation.
    """
    original = _fresh(meta)
    original.run_mcat(max_steps=700)
    state = json.loads(json.dumps(capture_run_state(original.ctx)))

    restored = EngineRunner(meta)
    restored.init_mcat(*PROBLEM, seed=SEED)
    restore_run_state(restored, state)

    original.run_mcat(max_steps=700)
    restored.run_mcat(max_steps=700)

    assert _fingerprint(restored) == _fingerprint(original)


def test_an_end_of_run_capture_restores_after_the_run_answered(meta):
    """The capture Normal mode's whole promise depends on, and the one that was broken.

    ``GRAPH_TYPES`` listed ``TraceEvent`` but not its three subclasses. ``isinstance``
    matches the base class, so *capture* worked; the reader keys on the concrete type
    name, so *restore* raised on any run that had answered, snagged or clamped — which
    is nearly every interesting Normal run, and precisely the end-of-run capture.

    Two things hid it. The existing round-trip tests use ``abc→abd; mrrjjj`` and stop at
    or before 1,100 codelets, which produces no rich event type; and the mode tests
    restore only the *start* capture, where the trace is empty by construction. So the
    defect sat behind a run that answered — the ordinary case.

    A second bug sat directly behind it: a run that answered has created an answer
    string, which a runner freshly initialised in discovery mode does not have, and
    references to it resolve by role.
    """
    runner = _fresh_answering(meta)
    result = runner.run_mcat(max_steps=3000)
    assert result.status == "answer_found", "this seed must answer for the test to bite"

    event_types = {type(e).__name__ for e in runner.ctx.trace.events}
    assert {"AnswerEvent", "SnagEvent"} <= event_types, (
        f"expected rich event types in the trace, got {sorted(event_types)}"
    )

    state = json.loads(json.dumps(capture_run_state(runner.ctx)))
    restored = EngineRunner(meta)
    restored.init_mcat(*ANSWERING_PROBLEM, seed=ANSWERING_SEED)
    restore_run_state(restored, state)
    restored.status = runner.status

    assert restored.ctx.workspace.answer_string is not None
    assert (
        restored.ctx.workspace.answer_string.text
        == runner.ctx.workspace.answer_string.text
    )
    assert _fingerprint(restored) == _fingerprint(runner)
    assert {type(e).__name__ for e in restored.ctx.trace.events} == event_types


def test_every_trace_event_subclass_is_a_known_graph_type(meta):
    """Guards the same gap structurally, so a *new* event subclass cannot reopen it.

    The round-trip test above only fails if some run happens to produce the missing
    type. This fails as soon as a subclass exists that the reader could not name.
    """
    from server.engine.trace import TraceEvent as BaseTraceEvent

    from server.engine import state_graph

    known = {cls.__name__ for cls in state_graph.GRAPH_TYPES}
    subclasses = {cls.__name__ for cls in BaseTraceEvent.__subclasses__()}
    assert subclasses <= known, (
        f"TraceEvent subclasses missing from GRAPH_TYPES: {sorted(subclasses - known)}. "
        f"Capture would succeed and restore would fail."
    )


@pytest.mark.parametrize("stop_at", [15, 150, 450, 1100])
def test_continuation_holds_at_several_capture_points(meta, stop_at):
    """One capture point can agree by accident; four at different phases cannot.

    The points straddle an update cycle, early bond-building, group and bridge
    formation, and rule discovery — the run is in a materially different condition at
    each.
    """
    original = _fresh(meta)
    original.run_mcat(max_steps=stop_at)
    state = json.loads(json.dumps(capture_run_state(original.ctx)))

    restored = EngineRunner(meta)
    restored.init_mcat(*PROBLEM, seed=SEED)
    restore_run_state(restored, state)

    original.run_mcat(max_steps=300)
    restored.run_mcat(max_steps=300)

    assert _fingerprint(restored) == _fingerprint(original)
