"""Lockstep-pass fixes: scouts' scope, bond-builder order, aggregates, events.

Each test cites the Scheme it pins (DISCREPANCIES5.md D-6 to D-9, C-5, D-10).
"""

import os

import pytest

from server.engine import codelet_dsl as _dsl  # noqa: F401
from server.engine.bonds import Bond
from server.engine.bridges import BRIDGE_TOP, _propose_bridge_side_effects
from server.engine.codelet_dsl import builtins as B
from server.engine.codelet_dsl.interpreter import CodeletInterpreter, CodeletRegistry
from server.engine.groups import Group
from server.engine.metadata import MetadataProvider
from server.engine.runner import EngineRunner
from server.engine.workspace import Workspace

pytestmark = pytest.mark.numeric_matrix

SEED_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")


@pytest.fixture
def meta():
    return MetadataProvider.from_standard_configuration(SEED_DATA_DIR)


@pytest.fixture
def runner(meta):
    return EngineRunner(meta)


@pytest.fixture
def ctx_mrrjjj(runner):
    runner.init_mcat("abc", "abd", "mrrjjj", seed=42)
    ctx = runner.ctx
    target = ctx.workspace.target_string
    samegrp = ctx.slipnet.nodes["plato-samegrp"]
    lcat = ctx.slipnet.nodes["plato-letter-category"]
    letters = target.letters
    for members in (letters[1:3], letters[3:6]):
        group = Group(target, samegrp, lcat, None, list(members), [])
        group.proposal_level = Group.BUILT
        target.add_group(group)
    return ctx


def _posted(ctx, codelet_type):
    return [
        c for b in ctx.coderack.bins for c in b.codelets if c.codelet_type == codelet_type
    ]


# --- D-8: the scope a bridge hands its top-down scouts -------------------------


def test_bridge_recruits_scouts_scoped_to_the_objects_strings(ctx_mrrjjj):
    """bridges.ss:1124-1145: description scouts get each object's string, the
    group scout gets the *letter's* string, and the argument is on the codelet."""
    ctx = ctx_mrrjjj
    target = ctx.workspace.target_string
    initial = ctx.workspace.initial_string
    letter = initial.letters[0]
    group = target.groups[1]  # jjj
    ctx.coderack.clear()
    _propose_bridge_side_effects(BRIDGE_TOP, letter, group, ctx)

    desc = _posted(ctx, "top-down-description-scout")
    assert [c.arguments["scope"] for c in desc] == [initial, target]
    (grp,) = _posted(ctx, "top-down-group-scout:category")
    assert grp.arguments["scope"] is initial
    assert grp.arguments["slipnode"] is group.group_category


def test_group_scout_with_a_string_scope_draws_no_string(ctx_mrrjjj, meta):
    """groups.ss:424-425: ``(if (workspace-string? scope) scope (stochastic-pick ...))``."""
    ctx = ctx_mrrjjj
    target = ctx.workspace.target_string
    builtins = B.get_builtins()

    def boom(ctx, node):
        raise AssertionError("string re-picked despite a scope")

    builtins["choose_string_for"] = boom
    interp = CodeletInterpreter(builtins=builtins)
    compiled = CodeletRegistry.from_metadata(meta, interp).get_compiled(
        "top-down-group-scout:category"
    )
    chosen = []
    builtins["choose_string_object"] = lambda ctx, string, key="intra": (
        chosen.append(string) or None
    )
    interp.execute(
        compiled, ctx, slipnode=ctx.slipnet.nodes["plato-samegrp"], scope=target
    )
    assert chosen == [target]


def test_description_scout_with_a_string_scope_picks_within_that_string(ctx_mrrjjj, meta):
    """descriptions.ss:132: ``(tell scope 'choose-object 'get-average-salience)``."""
    ctx = ctx_mrrjjj
    initial = ctx.workspace.initial_string
    builtins = B.get_builtins()
    seen = []
    builtins["choose_string_object"] = lambda ctx, string, key="intra": (
        seen.append((string, key)) or None
    )
    interp = CodeletInterpreter(builtins=builtins)
    compiled = CodeletRegistry.from_metadata(meta, interp).get_compiled(
        "top-down-description-scout"
    )
    interp.execute(
        compiled, ctx, slipnode=ctx.slipnet.nodes["plato-length"], scope=initial
    )
    assert seen == [(initial, "average")]


# --- D-6: the bond builder's break order and guard -----------------------------


def test_bond_builder_breaks_groups_first_and_skips_vanished_groups(
    ctx_mrrjjj, monkeypatch
):
    """bonds.ss:396-402."""
    ctx = ctx_mrrjjj
    target = ctx.workspace.target_string
    slipnet = ctx.slipnet
    letters = target.letters
    proposed = Bond(
        letters[1], letters[2], slipnet.nodes["plato-sameness"],
        slipnet.nodes["plato-letter-category"],
        letters[1].letter_category, letters[2].letter_category, None,
    )
    existing = Bond(
        letters[3], letters[4], slipnet.nodes["plato-sameness"],
        slipnet.nodes["plato-letter-category"],
        letters[3].letter_category, letters[4].letter_category, None,
    )
    live_group, gone_group = target.groups[0], target.groups[1]
    target.remove_group(gone_group)
    monkeypatch.setattr(
        B,
        "_get_incompatible_structures",
        lambda ctx, s: [(existing, 1.0, 1.0), (gone_group, 1.0, 1.0), (live_group, 1.0, 1.0)],
    )
    monkeypatch.setattr(B, "_wins_fight", lambda *a, **k: True)
    broken = []
    monkeypatch.setattr(B, "_break_structure_locked", lambda ctx, s: broken.append(s))
    B.build_structure(ctx, proposed)
    assert broken == [live_group, existing]


# --- D-7: aggregates and the answer string --------------------------------------


def test_aggregates_exclude_a_found_answer_string_outside_justify_mode(runner):
    runner.init_mcat("abc", "abd", "xyz", seed=42)
    ws = runner.ctx.workspace
    n = len(ws.all_objects)
    from server.engine.workspace import WorkspaceString

    ws.answer_string = WorkspaceString("xyd", runner.ctx.slipnet, string_type="answer")
    ws.answer_string.workspace = ws
    assert not ws.justify_mode
    assert len(ws.all_objects) == n
    ws.justify_mode = True
    assert len(ws.all_objects) == n + 3


# --- D-9: flush and jump are monitored separately -------------------------------


def test_concept_activation_events_are_tested_per_change(runner):
    """slipnet.ss:140, 153, 167: 0->60 then 60->100 is two sub-threshold deltas."""
    runner.init_mcat("abc", "abd", "xyz", seed=42)
    ctx = runner.ctx
    node = next(n for n in ctx.slipnet.nodes.values() if n.conceptual_depth >= 90)
    before = {name: 0.0 for name in ctx.slipnet.nodes}
    flushed = {name: 0.0 for name in ctx.slipnet.nodes}
    flushed[node.name] = 60.0
    node.activation = 100.0
    # Combined delta of 100 * cd/100 >= 90 clears 85; 60 and 40 do not.
    events = []
    ctx.trace.record_event = events.append
    runner._record_concept_activation_events(before, flushed)
    assert [e for e in events if e.slipnode is node] == []
    runner._record_concept_activation_events(before)
    assert [e for e in events if e.slipnode is node]


# --- C-5: the answer-description dimension order --------------------------------


def test_answer_description_dimensions_follow_answers_ss_order():
    from server.engine.answers import _ANSWER_DESCRIPTION_THEME_TYPES as T

    assert T[:2] == (
        "plato-alphabetic-position-category",
        "plato-string-position-category",
    )
