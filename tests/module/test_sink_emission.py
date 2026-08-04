"""The engine emits a complete run record to its sink (WP3.3, engine half).

Audit mode reconstructs every intermediate state from the Run-start state plus the
stream of state-changing actions, and Normal re-executes a Run from its recorded start
state.  Both rest on the same property: the sink is told *everything*, in order, and
attaching one changes nothing about what the engine does.

So there are two families of test here.  One checks that the events arrive, are
ordered, and are complete against the Workspace they describe.  The other checks that
a run with a recording sink is identical to a run without one — because a sink that
perturbed cognition would invalidate every mode comparison built on top of it.
"""

from __future__ import annotations

import os

import pytest

from server.engine.metadata import MetadataProvider
from server.engine.runner import EngineRunner
from server.engine.sink import STRUCTURE_BROKEN, STRUCTURE_BUILT, NullSink

# Every test here executes arithmetic the numeric substrate owns, so each one runs
# once per backend in the matrix. See tests/conftest.py.
pytestmark = pytest.mark.numeric_matrix

SEED_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "seed_data",
)


@pytest.fixture(scope="module")
def meta() -> MetadataProvider:
    return MetadataProvider.from_seed_data(SEED_DIR)


class RecordingSink:
    """Records the event stream. Structural typing — it does not inherit anything."""

    def __init__(self) -> None:
        self.events: list[tuple] = []

    def on_run_created(self, ctx):
        self.events.append(("run_created", ctx.codelet_count))

    def on_codelet(self, ctx, codelet, result):
        self.events.append(("codelet", codelet.codelet_type, result.codelet_count))

    def on_trace_event(self, ctx, event):
        self.events.append(("trace_event", event.event_type, event.event_number))

    def on_structure_change(self, ctx, structure, change):
        self.events.append(("structure", change, type(structure).__name__))

    def on_answer(self, ctx, answer, quality):
        self.events.append(("answer", answer, quality))

    def on_valence(self, ctx, signal, strength):
        self.events.append(("valence", signal, strength))

    def on_turn_end(self, ctx):
        self.events.append(("turn_end", ctx.codelet_count))

    def kinds(self) -> list[str]:
        return [e[0] for e in self.events]


def _run(meta, sink=None, steps=800, problem=("abc", "abd", "mrrjjj")):
    runner = EngineRunner(meta)
    runner.init_mcat(*problem, seed=42, sink=sink)
    result = runner.run_mcat(max_steps=steps)
    return runner, result


# --- the record is complete and ordered ------------------------------------


def test_run_created_is_first_and_turn_end_is_last(meta):
    sink = RecordingSink()
    _run(meta, sink)
    kinds = sink.kinds()
    assert kinds[0] == "run_created"
    assert kinds[-1] == "turn_end"


def test_turn_end_is_emitted_exactly_once(meta):
    """It is Normal's second capture and Audit's flush, so twice would double a record.

    A Run can stop in three places — answer, give-up, budget exhausted — and the
    service layer can also end one itself, so the guard matters.
    """
    sink = RecordingSink()
    runner, _ = _run(meta, sink)
    runner.finish()
    runner.finish()
    assert sink.kinds().count("turn_end") == 1


def test_every_codelet_is_reported(meta):
    sink = RecordingSink()
    runner, result = _run(meta, sink)
    codelets = [e for e in sink.events if e[0] == "codelet"]
    assert len(codelets) == result.codelet_count
    # Reported in execution order, with no gaps.
    assert [e[2] for e in codelets] == list(range(1, result.codelet_count + 1))


def test_every_trace_event_is_reported_exactly_once(meta):
    """Emission diffs the Trace rather than hooking ``record_event``.

    That catches events recorded by the Trace's own lifecycle methods, which have no
    context to emit from — the reason the diffing approach was chosen. If it were
    hooked at the recording site instead, clamp and snag events would go missing.
    """
    sink = RecordingSink()
    runner, _ = _run(meta, sink)
    reported = [e[2] for e in sink.events if e[0] == "trace_event"]
    actual = [e.event_number for e in runner.ctx.trace.events]
    assert reported == actual
    assert len(reported) == len(set(reported))


def test_structure_changes_account_for_the_final_workspace(meta):
    """Built minus broken must equal what is in the Workspace at the end.

    This is the property Audit needs and the one a missed emission breaks: if any
    build or break went unreported, forward reconstruction would drift from reality.

    Counted per structure type, and **descriptions are excluded** — not because they
    are unimportant but because they do not all arrive through ``build_structure``.
    Two other paths create them already built: ``init_mcat`` attaches letter-category,
    object-category and string-position descriptions to every letter, and a Group
    describes itself the moment it is constructed. Neither is a gap in the record. The
    first belongs to the Run-start state, which Normal captures and Audit starts from;
    the second is part of building the group, and replaying the group's construction
    reproduces it. Asserting over descriptions anyway would only pin how many the
    engine happens to create up front.

    The **answer string is excluded for the same reason**, and this became visible
    only when the phase-5 rule work made this seed answer inside its step budget
    where it used to halt. ``make_translated_string`` (``answers.ss:1035-1071``)
    creates the answer string's letters, its groups, those groups' bonds and the
    bridges drawn to it in one go, at answer time — none of them through
    ``build_structure``. They are not a gap in the record either: the answer event is
    the recorded action, and replaying it reconstructs the whole translated string
    from the rule. In discovery mode every bottom bridge comes from that same call,
    so they go with it.
    """
    sink = RecordingSink()
    runner, _ = _run(meta, sink)
    ws = runner.ctx.workspace

    tracked = {"Bond", "Group", "Bridge", "Rule"}
    built = sum(
        1 for e in sink.events
        if e[0] == "structure" and e[1] == STRUCTURE_BUILT and e[2] in tracked
    )
    broken = sum(
        1 for e in sink.events
        if e[0] == "structure" and e[1] == STRUCTURE_BROKEN and e[2] in tracked
    )
    assert built > 0 and broken > 0, "the run must both build and break structures"

    codelet_built_strings = [
        s for s in ws.all_strings if s is not ws.answer_string
    ]
    live = (
        sum(len([b for b in s.bonds if b.is_built]) for s in codelet_built_strings)
        + sum(len([g for g in s.groups if g.is_built]) for s in codelet_built_strings)
        + len([b for b in ws.top_bridges if b.is_built])
        + len([b for b in ws.vertical_bridges if b.is_built])
        + len([r for r in ws.top_rules if r.is_built])
        + len([r for r in ws.bottom_rules if r.is_built])
    )
    assert built - broken == live


def test_descriptions_built_by_codelets_are_reported(meta):
    """The description path through ``build_structure`` does emit.

    The exclusion above is about descriptions created at initialisation and by group
    construction. A description a description-scout proposes and a builder builds is
    an ordinary state-changing action and must appear in the record like any other.
    """
    # A longer budget than the other tests here: this seed's first description
    # builder now lands after codelet 800.  The temperature no longer collapses
    # as soon as the strings are bonded (it carries the mapping deficit, per
    # ``workspace.ss:581-585``), so the run explores for longer before any
    # proposal survives its evaluator.
    sink = RecordingSink()
    _run(meta, sink, steps=1500)
    described = [
        e for e in sink.events
        if e[0] == "structure" and e[2] == "Description"
    ]
    assert described, "no description was reported at all"


def test_an_answer_is_reported_before_the_turn_ends(meta):
    sink = RecordingSink()
    runner, result = _run(meta, sink, steps=3000, problem=("abc", "abd", "xyz"))
    if result.status != "answer_found":
        pytest.skip("this seed did not answer within the budget")
    kinds = sink.kinds()
    assert "answer" in kinds
    assert kinds.index("answer") < kinds.index("turn_end")


# --- attaching a sink changes nothing --------------------------------------


def test_a_recording_sink_does_not_change_the_run(meta):
    """The rule the three modes rest on: mode must not change results."""
    plain_runner, plain = _run(meta)
    sunk_runner, sunk = _run(meta, RecordingSink())

    assert plain.status == sunk.status
    assert plain.answers == sunk.answers
    assert plain.codelet_count == sunk.codelet_count
    assert plain_runner.ctx.rng.call_count == sunk_runner.ctx.rng.call_count
    assert [e.event_number for e in plain_runner.ctx.trace.events] == [
        e.event_number for e in sunk_runner.ctx.trace.events
    ]


def test_the_default_sink_is_the_null_sink(meta):
    runner, _ = _run(meta, steps=30)
    assert isinstance(runner.ctx.sink, NullSink)
