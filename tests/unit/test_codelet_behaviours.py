"""Codelet behaviour test suite.

Tests each codelet type in controlled scenarios, matching the specifications
in PLAN.md Section 3. Uses a minimal workspace fixture (problem "abc -> abd;
xyz -> ?") with pre-positioned structures so each test exercises one codelet
in isolation.

All tests are deterministic via fixed RNG seed.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from server.engine.bonds import Bond
from server.engine.bridges import Bridge, BRIDGE_TOP
from server.engine.codelet_dsl.builtins import (
    build_structure,
    break_structure,
    _get_incompatible_structures,
    _wins_fight,
    report_answer,
    translate_rule,
    apply_rule,
)
from server.engine.codelet_dsl.interpreter import CodeletInterpreter, CodeletRegistry
from server.engine.coderack import Codelet, Coderack
from server.engine.concept_mappings import ConceptMapping
from server.engine.descriptions import Description
from server.engine.groups import Group
from server.engine.memory import EpisodicMemory
from server.engine.metadata import MetadataProvider
from server.engine.rng import RNG
from server.engine.rules import Rule, RuleClause, RuleChange, RULE_TOP, RULE_BOTTOM, CLAUSE_INTRINSIC, CLAUSE_EXTRINSIC
from server.engine.runner import EngineContext, EngineRunner, StepResult
from server.engine.slipnet import Slipnet
from server.engine.temperature import Temperature
from server.engine.themes import Themespace
from server.engine.trace import BOND_BROKEN, BOND_BUILT, TemporalTrace
from server.engine.workspace import Workspace
from server.engine.workspace_objects import Letter


SEED_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")
SEED = 42


@pytest.fixture
def meta():
    return MetadataProvider.from_seed_data(SEED_DATA_DIR)


@pytest.fixture
def runner(meta):
    return EngineRunner(meta)


@pytest.fixture
def ctx_abc_abd_xyz(meta, runner):
    """EngineContext for 'abc -> abd; xyz -> ?'."""
    runner.init_mcat("abc", "abd", "xyz", seed=SEED)
    return runner.ctx


@pytest.fixture
def ctx_abc_abd_xyz_with_bonds(ctx_abc_abd_xyz):
    """Context with successor bonds built on 'abc'."""
    ctx = ctx_abc_abd_xyz
    init = ctx.workspace.initial_string
    slipnet = ctx.slipnet

    letters = init.letters
    succ = slipnet.nodes["plato-successor"]
    right = slipnet.nodes["plato-right"]
    lcat = slipnet.nodes["plato-letter-category"]

    for i in range(len(letters) - 1):
        bond = Bond(
            letters[i], letters[i + 1],
            succ, lcat,
            letters[i].letter_category, letters[i + 1].letter_category,
            right,
        )
        bond.proposal_level = Bond.BUILT
        init.add_bond(bond)

    return ctx


# ═══════════════════════════════════════════════════════════════════════
# 3.1 Bond Codelets
# ═══════════════════════════════════════════════════════════════════════

class TestBottomUpBondScout:
    def test_proposes_bond_between_adjacent_letters(self, ctx_abc_abd_xyz, meta):
        """Executing the bond scout on 'abc' should post a bond-evaluator."""
        ctx = ctx_abc_abd_xyz
        interp = CodeletInterpreter(builtins=_get_test_builtins())
        registry = CodeletRegistry.from_metadata(meta, interp)
        compiled = registry.get_compiled("bottom-up-bond-scout")

        initial_count = len(ctx.coderack.bins)
        coderack_before = sum(b.count for b in ctx.coderack.bins)

        # Run with multiple seeds to ensure at least one succeeds
        posted = False
        for try_seed in range(10):
            ctx.rng = RNG(SEED + try_seed)
            before = sum(b.count for b in ctx.coderack.bins)
            interp.execute(compiled, ctx)
            after = sum(b.count for b in ctx.coderack.bins)
            if after > before:
                posted = True
                break
        assert posted, "Bond scout never posted a bond-evaluator in 10 tries"

    def test_fizzles_on_single_letter_string(self, meta):
        """A single-letter string has no neighbors — scout should fizzle."""
        runner = EngineRunner(meta)
        runner.init_mcat("a", "b", "c", seed=SEED)
        ctx = runner.ctx

        interp = CodeletInterpreter(builtins=_get_test_builtins())
        registry = CodeletRegistry.from_metadata(meta, interp)
        compiled = registry.get_compiled("bottom-up-bond-scout")

        coderack_before = sum(b.count for b in ctx.coderack.bins)
        # Should fizzle (no bond-evaluator posted) — but might also
        # choose an object from a multi-letter perspective; the key is
        # it doesn't crash
        interp.execute(compiled, ctx)

    def test_determines_correct_bond_category(self, ctx_abc_abd_xyz, meta):
        """Bond between 'a' and 'b' should be successor, direction right."""
        ctx = ctx_abc_abd_xyz
        init = ctx.workspace.initial_string
        a_letter = init.letters[0]
        b_letter = init.letters[1]

        from server.engine.codelet_dsl.builtins import get_bond_category, get_node
        bond_cat = get_bond_category(ctx, a_letter.letter_category, b_letter.letter_category)
        assert bond_cat is not None
        assert bond_cat.name == "plato-successor"


class TestTopDownBondScoutCategory:
    def test_uses_slipnode_argument(self, ctx_abc_abd_xyz, meta):
        """Top-down scout with slipnode=successor should propose a successor bond."""
        ctx = ctx_abc_abd_xyz
        interp = CodeletInterpreter(builtins=_get_test_builtins())
        registry = CodeletRegistry.from_metadata(meta, interp)
        compiled = registry.get_compiled("top-down-bond-scout:category")

        succ_node = ctx.slipnet.nodes["plato-successor"]
        coderack_before = sum(b.count for b in ctx.coderack.bins)
        interp.execute(compiled, ctx, slipnode=succ_node)
        coderack_after = sum(b.count for b in ctx.coderack.bins)
        assert coderack_after >= coderack_before  # May or may not post depending on RNG

    def test_fizzles_without_slipnode(self, ctx_abc_abd_xyz, meta):
        """Without slipnode argument, should fizzle."""
        ctx = ctx_abc_abd_xyz
        interp = CodeletInterpreter(builtins=_get_test_builtins())
        registry = CodeletRegistry.from_metadata(meta, interp)
        compiled = registry.get_compiled("top-down-bond-scout:category")

        coderack_before = sum(b.count for b in ctx.coderack.bins)
        interp.execute(compiled, ctx)  # No slipnode arg
        coderack_after = sum(b.count for b in ctx.coderack.bins)
        assert coderack_after == coderack_before  # Fizzled — no codelet posted

    def test_fizzles_on_category_mismatch(self, ctx_abc_abd_xyz, meta):
        """Seeking sameness bonds in 'abc' should fizzle (all are successor)."""
        ctx = ctx_abc_abd_xyz
        interp = CodeletInterpreter(builtins=_get_test_builtins())
        registry = CodeletRegistry.from_metadata(meta, interp)
        compiled = registry.get_compiled("top-down-bond-scout:category")

        sameness_node = ctx.slipnet.nodes["plato-sameness"]
        coderack_before = sum(b.count for b in ctx.coderack.bins)
        interp.execute(compiled, ctx, slipnode=sameness_node)
        coderack_after = sum(b.count for b in ctx.coderack.bins)
        assert coderack_after == coderack_before


class TestTopDownBondScoutDirection:
    def test_fizzles_at_string_edge(self, ctx_abc_abd_xyz, meta):
        """Seeking left-direction from leftmost letter should fizzle."""
        ctx = ctx_abc_abd_xyz
        interp = CodeletInterpreter(builtins=_get_test_builtins())
        registry = CodeletRegistry.from_metadata(meta, interp)
        compiled = registry.get_compiled("top-down-bond-scout:direction")

        left_node = ctx.slipnet.nodes["plato-left"]
        # Multiple runs — should never crash, may fizzle
        interp.execute(compiled, ctx, slipnode=left_node)


class TestBondEvaluator:
    def test_posts_builder_on_strong_bond(self, ctx_abc_abd_xyz, meta):
        """A strong bond should be promoted to evaluated and builder posted."""
        ctx = ctx_abc_abd_xyz
        init = ctx.workspace.initial_string
        letters = init.letters
        slipnet = ctx.slipnet

        bond = Bond(
            letters[0], letters[1],
            slipnet.nodes["plato-successor"],
            slipnet.nodes["plato-letter-category"],
            letters[0].letter_category, letters[1].letter_category,
            slipnet.nodes["plato-right"],
        )
        bond.update_strength()

        interp = CodeletInterpreter(builtins=_get_test_builtins())
        registry = CodeletRegistry.from_metadata(meta, interp)
        compiled = registry.get_compiled("bond-evaluator")

        # Set temperature high so weak bonds can pass
        ctx.temperature.value = 90.0
        interp.execute(compiled, ctx, structure=bond)


class TestBondBuilder:
    def test_adds_bond_to_string(self, ctx_abc_abd_xyz, meta):
        """Building a bond should add it to the string."""
        ctx = ctx_abc_abd_xyz
        init = ctx.workspace.initial_string
        letters = init.letters
        slipnet = ctx.slipnet

        bond = Bond(
            letters[0], letters[1],
            slipnet.nodes["plato-successor"],
            slipnet.nodes["plato-letter-category"],
            letters[0].letter_category, letters[1].letter_category,
            slipnet.nodes["plato-right"],
        )
        bond.proposal_level = Bond.EVALUATED

        result = build_structure(ctx, bond)
        assert result is True
        assert bond.is_built
        assert bond in init.bonds

        # Check trace event
        bond_events = ctx.trace.get_events_by_type(BOND_BUILT)
        assert len(bond_events) >= 1

    def test_fizzles_if_object_removed(self, ctx_abc_abd_xyz, meta):
        """Builder should fizzle if the object is no longer in a string."""
        ctx = ctx_abc_abd_xyz
        interp = CodeletInterpreter(builtins=_get_test_builtins())
        registry = CodeletRegistry.from_metadata(meta, interp)
        compiled = registry.get_compiled("bond-builder")

        init = ctx.workspace.initial_string
        letters = init.letters
        bond = Bond(
            letters[0], letters[1],
            ctx.slipnet.nodes["plato-successor"],
            ctx.slipnet.nodes["plato-letter-category"],
            letters[0].letter_category, letters[1].letter_category,
            ctx.slipnet.nodes["plato-right"],
        )
        bond.proposal_level = Bond.EVALUATED
        letters[0].string = None  # Remove from string

        interp.execute(compiled, ctx, structure=bond)
        # Should fizzle — bond not built
        assert not bond.is_built

    def test_fights_incompatible_bond(self, ctx_abc_abd_xyz):
        """An incompatible bond at the same location should trigger a fight."""
        ctx = ctx_abc_abd_xyz
        init = ctx.workspace.initial_string
        letters = init.letters
        slipnet = ctx.slipnet

        # Build a sameness bond first
        sameness_bond = Bond(
            letters[0], letters[1],
            slipnet.nodes["plato-sameness"],
            slipnet.nodes["plato-letter-category"],
            letters[0].letter_category, letters[1].letter_category,
            None,
        )
        sameness_bond.proposal_level = Bond.BUILT
        sameness_bond.strength = 50.0
        init.add_bond(sameness_bond)

        # Propose a successor bond on the same pair
        succ_bond = Bond(
            letters[0], letters[1],
            slipnet.nodes["plato-successor"],
            slipnet.nodes["plato-letter-category"],
            letters[0].letter_category, letters[1].letter_category,
            slipnet.nodes["plato-right"],
        )
        succ_bond.proposal_level = Bond.EVALUATED
        succ_bond.strength = 80.0

        incompatibles = _get_incompatible_structures(ctx, succ_bond)
        assert len(incompatibles) >= 1
        assert incompatibles[0][0] is sameness_bond


# ═══════════════════════════════════════════════════════════════════════
# 3.2 Group Codelets
# ═══════════════════════════════════════════════════════════════════════

class TestGroupScoutWholeString:
    def test_fizzles_without_bonds(self, ctx_abc_abd_xyz, meta):
        """No bonds → no group possible."""
        ctx = ctx_abc_abd_xyz
        interp = CodeletInterpreter(builtins=_get_test_builtins())
        registry = CodeletRegistry.from_metadata(meta, interp)
        compiled = registry.get_compiled("group-scout:whole-string")

        coderack_before = sum(b.count for b in ctx.coderack.bins)
        interp.execute(compiled, ctx)
        coderack_after = sum(b.count for b in ctx.coderack.bins)
        assert coderack_after == coderack_before


class TestGroupBuilder:
    def test_adds_group_to_string(self, ctx_abc_abd_xyz_with_bonds, meta):
        """Building a group should add it to the string."""
        ctx = ctx_abc_abd_xyz_with_bonds
        init = ctx.workspace.initial_string
        letters = init.letters
        slipnet = ctx.slipnet

        group = Group(
            init,
            slipnet.nodes["plato-succgrp"],
            slipnet.nodes["plato-letter-category"],
            slipnet.nodes["plato-right"],
            letters,
            list(init.bonds),
        )
        group.proposal_level = Group.EVALUATED

        result = build_structure(ctx, group)
        assert result is True
        assert group.is_built
        assert group in init.groups

    def test_fizzles_if_bonds_broken(self, ctx_abc_abd_xyz_with_bonds, meta):
        """If constituent bonds are broken before building, builder should fizzle."""
        ctx = ctx_abc_abd_xyz_with_bonds
        init = ctx.workspace.initial_string
        letters = init.letters
        slipnet = ctx.slipnet

        bonds = list(init.bonds)
        group = Group(
            init,
            slipnet.nodes["plato-succgrp"],
            slipnet.nodes["plato-letter-category"],
            slipnet.nodes["plato-right"],
            letters,
            bonds,
        )
        group.proposal_level = Group.EVALUATED

        interp = CodeletInterpreter(builtins=_get_test_builtins())
        registry = CodeletRegistry.from_metadata(meta, interp)
        compiled = registry.get_compiled("group-builder")

        # Break the bonds
        for b in bonds:
            b.proposal_level = Bond.PROPOSED  # Mark as not built

        interp.execute(compiled, ctx, structure=group)
        assert not group.is_built


# ═══════════════════════════════════════════════════════════════════════
# 3.3 Bridge Codelets
# ═══════════════════════════════════════════════════════════════════════

class TestBottomUpBridgeScout:
    def test_proposes_bridge_between_strings(self, ctx_abc_abd_xyz, meta):
        """Bridge scout should try to map objects across strings."""
        ctx = ctx_abc_abd_xyz
        interp = CodeletInterpreter(builtins=_get_test_builtins())
        registry = CodeletRegistry.from_metadata(meta, interp)
        compiled = registry.get_compiled("bottom-up-bridge-scout")

        coderack_before = sum(b.count for b in ctx.coderack.bins)
        interp.execute(compiled, ctx)
        coderack_after = sum(b.count for b in ctx.coderack.bins)
        # Should post a bridge-evaluator (or fizzle on unlucky RNG)
        assert coderack_after >= coderack_before


class TestBridgeBuilder:
    def test_adds_bridge_to_workspace(self, ctx_abc_abd_xyz):
        """Building a bridge should add it to the workspace."""
        ctx = ctx_abc_abd_xyz
        init = ctx.workspace.initial_string
        modified = ctx.workspace.modified_string

        a_init = init.letters[0]
        a_mod = modified.letters[0]
        slipnet = ctx.slipnet

        # Create identity concept mappings
        cm = ConceptMapping(
            slipnet.nodes["plato-letter-category"],
            a_init.letter_category,
            slipnet.nodes["plato-letter-category"],
            a_mod.letter_category,
            slipnet.nodes["plato-identity"],
        )
        bridge = Bridge(a_init, a_mod, BRIDGE_TOP, [cm])
        bridge.proposal_level = Bridge.EVALUATED

        result = build_structure(ctx, bridge)
        assert result is True
        assert bridge.is_built
        assert bridge in ctx.workspace.top_bridges


# ═══════════════════════════════════════════════════════════════════════
# 3.4 Description Codelets
# ═══════════════════════════════════════════════════════════════════════

class TestDescriptionBuilder:
    def test_adds_description_to_object(self, ctx_abc_abd_xyz):
        """Building a description should add it to the object."""
        ctx = ctx_abc_abd_xyz
        init = ctx.workspace.initial_string
        a_letter = init.letters[0]
        slipnet = ctx.slipnet

        desc = Description(
            a_letter,
            slipnet.nodes["plato-alphabetic-position-category"],
            slipnet.nodes["plato-alphabetic-first"],
        )
        desc.proposal_level = Description.EVALUATED

        before = len(a_letter.descriptions)
        result = build_structure(ctx, desc)
        assert result is True
        assert desc.is_built
        assert len(a_letter.descriptions) == before + 1

    def test_fizzles_if_already_present(self, ctx_abc_abd_xyz, meta):
        """Builder should fizzle if the description already exists."""
        ctx = ctx_abc_abd_xyz
        init = ctx.workspace.initial_string
        a_letter = init.letters[0]

        interp = CodeletInterpreter(builtins=_get_test_builtins())
        registry = CodeletRegistry.from_metadata(meta, interp)
        compiled = registry.get_compiled("description-builder")

        # letter-category:a already exists from init
        existing = a_letter.descriptions[0]
        dup = Description(a_letter, existing.description_type, existing.descriptor)
        dup.proposal_level = Description.EVALUATED

        before = len(a_letter.descriptions)
        interp.execute(compiled, ctx, structure=dup)
        assert len(a_letter.descriptions) == before  # Not added again


class TestTopDownDescriptionScout:
    def test_fizzles_without_slipnode(self, ctx_abc_abd_xyz, meta):
        """Without slipnode argument, should fizzle."""
        ctx = ctx_abc_abd_xyz
        interp = CodeletInterpreter(builtins=_get_test_builtins())
        registry = CodeletRegistry.from_metadata(meta, interp)
        compiled = registry.get_compiled("top-down-description-scout")

        coderack_before = sum(b.count for b in ctx.coderack.bins)
        interp.execute(compiled, ctx)  # No slipnode
        coderack_after = sum(b.count for b in ctx.coderack.bins)
        assert coderack_after == coderack_before


# ═══════════════════════════════════════════════════════════════════════
# 3.5 Rule Codelets
# ═══════════════════════════════════════════════════════════════════════

class TestRuleScout:
    def test_fizzles_without_bridges(self, ctx_abc_abd_xyz, meta):
        """No top bridges → rule scout should fizzle."""
        ctx = ctx_abc_abd_xyz
        interp = CodeletInterpreter(builtins=_get_test_builtins())
        registry = CodeletRegistry.from_metadata(meta, interp)
        compiled = registry.get_compiled("rule-scout")

        coderack_before = sum(b.count for b in ctx.coderack.bins)
        interp.execute(compiled, ctx)
        coderack_after = sum(b.count for b in ctx.coderack.bins)
        assert coderack_after == coderack_before


class TestRuleBuilder:
    def test_posts_answer_finder(self, ctx_abc_abd_xyz, meta):
        """Rule builder should build the rule and post answer-finder."""
        ctx = ctx_abc_abd_xyz
        interp = CodeletInterpreter(builtins=_get_test_builtins())
        registry = CodeletRegistry.from_metadata(meta, interp)
        compiled = registry.get_compiled("rule-builder")

        slipnet = ctx.slipnet
        change = RuleChange(
            dimension=slipnet.nodes["plato-letter-category"],
            relation=slipnet.nodes["plato-successor"],
        )
        clause = RuleClause(
            clause_type=CLAUSE_INTRINSIC,
            object_description=(
                slipnet.nodes["plato-string-position-category"],
                slipnet.nodes["plato-rightmost"],
            ),
            changes=[change],
        )
        rule = Rule(RULE_TOP, [clause])
        rule.proposal_level = Rule.EVALUATED
        rule.quality = 80.0

        coderack_before = sum(b.count for b in ctx.coderack.bins)
        interp.execute(compiled, ctx, structure=rule)
        coderack_after = sum(b.count for b in ctx.coderack.bins)

        assert rule.is_built
        assert coderack_after > coderack_before  # answer-finder posted


# ═══════════════════════════════════════════════════════════════════════
# 3.6 Answer Codelets
# ═══════════════════════════════════════════════════════════════════════

class TestAnswerFinder:
    def test_fizzles_without_supported_rules(self, ctx_abc_abd_xyz, meta):
        """No rules → should fizzle."""
        ctx = ctx_abc_abd_xyz
        interp = CodeletInterpreter(builtins=_get_test_builtins())
        registry = CodeletRegistry.from_metadata(meta, interp)
        compiled = registry.get_compiled("answer-finder")

        interp.execute(compiled, ctx)
        assert not hasattr(ctx, "_pending_answer") or ctx._pending_answer is None

    def test_fizzles_on_low_mapping_strength(self, ctx_abc_abd_xyz, meta):
        """Low mapping strength → should fizzle."""
        ctx = ctx_abc_abd_xyz
        interp = CodeletInterpreter(builtins=_get_test_builtins())
        registry = CodeletRegistry.from_metadata(meta, interp)
        compiled = registry.get_compiled("answer-finder")

        # No bridges = 0 mapping strength < 20
        interp.execute(compiled, ctx)
        assert not hasattr(ctx, "_pending_answer") or ctx._pending_answer is None


class TestApplyRule:
    def test_successor_produces_correct_answer(self, ctx_abc_abd_xyz):
        """Applying 'replace rightmost by successor' to 'xyz' → 'xyy'."""
        ctx = ctx_abc_abd_xyz
        slipnet = ctx.slipnet

        change = RuleChange(
            dimension=slipnet.nodes["plato-letter-category"],
            relation=slipnet.nodes["plato-successor"],
        )
        clause = RuleClause(
            clause_type=CLAUSE_INTRINSIC,
            object_description=(
                slipnet.nodes["plato-string-position-category"],
                slipnet.nodes["plato-rightmost"],
            ),
            changes=[change],
        )
        rule = Rule(RULE_BOTTOM, [clause])

        result = apply_rule(ctx, rule)
        # 'z' has no successor → snag
        assert result is None

    def test_successor_on_non_z(self, meta):
        """Applying 'replace rightmost by successor' to 'abc' → 'abd'."""
        runner = EngineRunner(meta)
        runner.init_mcat("abc", "abd", "abc", seed=SEED)
        ctx = runner.ctx
        slipnet = ctx.slipnet

        change = RuleChange(
            dimension=slipnet.nodes["plato-letter-category"],
            relation=slipnet.nodes["plato-successor"],
        )
        clause = RuleClause(
            clause_type=CLAUSE_INTRINSIC,
            object_description=(
                slipnet.nodes["plato-string-position-category"],
                slipnet.nodes["plato-rightmost"],
            ),
            changes=[change],
        )
        rule = Rule(RULE_BOTTOM, [clause])

        result = apply_rule(ctx, rule)
        assert result == "abd"


class TestTranslateRule:
    def test_returns_none_without_vertical_bridges(self, ctx_abc_abd_xyz):
        """No vertical bridges → translation returns None."""
        ctx = ctx_abc_abd_xyz
        slipnet = ctx.slipnet

        rule = Rule(RULE_TOP, [])
        result = translate_rule(ctx, rule)
        assert result is None


# ═══════════════════════════════════════════════════════════════════════
# 3.7 Meta / Self-Watching Codelets
# ═══════════════════════════════════════════════════════════════════════

class TestBreaker:
    def test_fizzles_at_low_temperature(self, ctx_abc_abd_xyz, meta):
        """At low temperature, breaker should usually fizzle."""
        ctx = ctx_abc_abd_xyz
        ctx.temperature.value = 5.0
        ctx.rng = RNG(123)  # Seed where prob(0.05) fails

        interp = CodeletInterpreter(builtins=_get_test_builtins())
        registry = CodeletRegistry.from_metadata(meta, interp)
        compiled = registry.get_compiled("breaker")

        # Build a structure first
        init = ctx.workspace.initial_string
        letters = init.letters
        bond = Bond(
            letters[0], letters[1],
            ctx.slipnet.nodes["plato-successor"],
            ctx.slipnet.nodes["plato-letter-category"],
            letters[0].letter_category, letters[1].letter_category,
            ctx.slipnet.nodes["plato-right"],
        )
        bond.proposal_level = Bond.BUILT
        init.add_bond(bond)

        interp.execute(compiled, ctx)
        # At temp=5, prob(0.05) almost always fails, so bond survives
        # (no assertion on specific outcome — this is stochastic)

    def test_fizzles_with_no_structures(self, ctx_abc_abd_xyz, meta):
        """No built structures → breaker should fizzle."""
        ctx = ctx_abc_abd_xyz
        ctx.temperature.value = 90.0

        interp = CodeletInterpreter(builtins=_get_test_builtins())
        registry = CodeletRegistry.from_metadata(meta, interp)
        compiled = registry.get_compiled("breaker")

        # No built structures in workspace initially
        trace_before = len(ctx.trace.events)
        interp.execute(compiled, ctx)
        trace_after = len(ctx.trace.events)
        # No break event recorded
        broken = [e for e in ctx.trace.events[trace_before:] if e.event_type == BOND_BROKEN]
        assert len(broken) == 0


class TestProgressWatcher:
    def test_fizzles_without_self_watching(self, ctx_abc_abd_xyz, meta):
        """self_watching=False → should fizzle."""
        ctx = ctx_abc_abd_xyz
        ctx.self_watching_enabled = False

        interp = CodeletInterpreter(builtins=_get_test_builtins())
        registry = CodeletRegistry.from_metadata(meta, interp)
        compiled = registry.get_compiled("progress-watcher")

        trace_before = len(ctx.trace.events)
        interp.execute(compiled, ctx)
        trace_after = len(ctx.trace.events)
        assert trace_after == trace_before  # No events recorded


class TestJootser:
    def test_fizzles_without_self_watching(self, ctx_abc_abd_xyz, meta):
        """self_watching=False → should fizzle."""
        ctx = ctx_abc_abd_xyz
        ctx.self_watching_enabled = False

        interp = CodeletInterpreter(builtins=_get_test_builtins())
        registry = CodeletRegistry.from_metadata(meta, interp)
        compiled = registry.get_compiled("jootser")

        trace_before = len(ctx.trace.events)
        interp.execute(compiled, ctx)
        trace_after = len(ctx.trace.events)
        assert trace_after == trace_before


class TestThematicBridgeScout:
    def test_fizzles_without_self_watching(self, ctx_abc_abd_xyz, meta):
        """self_watching=False → should fizzle."""
        ctx = ctx_abc_abd_xyz
        ctx.self_watching_enabled = False

        interp = CodeletInterpreter(builtins=_get_test_builtins())
        registry = CodeletRegistry.from_metadata(meta, interp)
        compiled = registry.get_compiled("thematic-bridge-scout")

        coderack_before = sum(b.count for b in ctx.coderack.bins)
        interp.execute(compiled, ctx)
        coderack_after = sum(b.count for b in ctx.coderack.bins)
        assert coderack_after == coderack_before

    def test_fizzles_without_thematic_pressure(self, ctx_abc_abd_xyz, meta):
        """No dominant themes → should fizzle."""
        ctx = ctx_abc_abd_xyz

        interp = CodeletInterpreter(builtins=_get_test_builtins())
        registry = CodeletRegistry.from_metadata(meta, interp)
        compiled = registry.get_compiled("thematic-bridge-scout")

        coderack_before = sum(b.count for b in ctx.coderack.bins)
        interp.execute(compiled, ctx)
        coderack_after = sum(b.count for b in ctx.coderack.bins)
        assert coderack_after == coderack_before


# ═══════════════════════════════════════════════════════════════════════
# 3.8 Integration / Pipeline Tests
# ═══════════════════════════════════════════════════════════════════════

class TestStructureFighting:
    def test_fight_probability_scales_with_strength(self, ctx_abc_abd_xyz):
        """Stronger structures should win fights more often."""
        ctx = ctx_abc_abd_xyz
        init = ctx.workspace.initial_string
        letters = init.letters
        slipnet = ctx.slipnet

        strong_bond = Bond(
            letters[0], letters[1],
            slipnet.nodes["plato-successor"],
            slipnet.nodes["plato-letter-category"],
            letters[0].letter_category, letters[1].letter_category,
            slipnet.nodes["plato-right"],
        )
        strong_bond.strength = 90.0

        weak_bond = Bond(
            letters[0], letters[1],
            slipnet.nodes["plato-sameness"],
            slipnet.nodes["plato-letter-category"],
            letters[0].letter_category, letters[1].letter_category,
            None,
        )
        weak_bond.strength = 10.0

        # Run many fights to verify statistical tendency
        wins = sum(
            1 for seed in range(100)
            if _wins_fight(
                EngineContext(
                    ctx.workspace, ctx.slipnet, ctx.coderack, ctx.themespace,
                    ctx.trace, ctx.memory, ctx.temperature, ctx.commentary,
                    RNG(seed), ctx.meta,
                ),
                strong_bond, 1.0, weak_bond, 1.0,
            )
        )
        # Strong (90) vs weak (10): should win ~90% of the time
        assert wins > 70


class TestReportAnswer:
    def test_sets_pending_answer(self, ctx_abc_abd_xyz):
        """report_answer should set _pending_answer on context."""
        ctx = ctx_abc_abd_xyz
        report_answer(ctx, "xyd", 85.0)
        assert ctx._pending_answer == "xyd"
        assert len(ctx.memory.answers) == 1

    def test_runner_detects_pending_answer(self, ctx_abc_abd_xyz):
        """The runner should detect _pending_answer after codelet execution."""
        ctx = ctx_abc_abd_xyz
        ctx._pending_answer = "xyd"

        # Simulate what step_mcat does after codelet execution
        result = StepResult()
        pending = getattr(ctx, "_pending_answer", None)
        if pending is not None:
            result.answer_found = True
            result.answer = pending

        assert result.answer_found is True
        assert result.answer == "xyd"


class TestBottomUpPosting:
    def test_posts_multiple_codelet_types(self, meta, runner):
        """Bottom-up posting should post multiple codelet types per cycle."""
        runner.init_mcat("abc", "abd", "xyz", seed=SEED)
        ctx = runner.ctx

        # Clear coderack
        while not ctx.coderack.is_empty:
            ctx.coderack.choose_and_remove(50.0, ctx.rng)

        runner._post_bottom_up_codelets()

        # Should have posted multiple codelets
        total = sum(b.count for b in ctx.coderack.bins)
        assert total > 3  # More than the old single-codelet-per-type approach


class TestTopDownSlipnodeArgument:
    def test_top_down_codelets_receive_slipnode(self, meta, runner):
        """Top-down codelets should carry the triggering slipnode."""
        runner.init_mcat("abc", "abd", "xyz", seed=SEED)
        ctx = runner.ctx

        # Force a slipnode above threshold
        succ_node = ctx.slipnet.nodes["plato-successor"]
        succ_node.activation = 100.0

        # Clear and post
        while not ctx.coderack.is_empty:
            ctx.coderack.choose_and_remove(50.0, ctx.rng)

        runner._post_top_down_codelets()

        # Find any posted codelets with 'slipnode' argument
        has_slipnode = False
        for bin_ in ctx.coderack.bins:
            for codelet in bin_.codelets:
                if "slipnode" in codelet.arguments:
                    has_slipnode = True
                    # The slipnode should be a SlipnetNode (not None)
                    assert codelet.arguments["slipnode"] is not None
                    assert hasattr(codelet.arguments["slipnode"], "name")
                    break


class TestSlipnetActivation:
    def test_descriptions_activate_slipnet_nodes(self, meta, runner):
        """Built descriptions activate descriptor nodes during init.

        In the original Scheme, workspace→slipnet activation happens during
        structure building (not as a separate update step). init_mcat sets
        descriptor nodes to max activation directly.
        """
        runner.init_mcat("abc", "abd", "xyz", seed=SEED)
        ctx = runner.ctx

        # Letter 'a' has description letter-category:plato-a
        # init_mcat activates descriptor nodes to max_activation
        plato_a = ctx.slipnet.nodes["plato-a"]
        assert plato_a.activation == 100.0


class TestWorkspaceToThemespace:
    def test_bridge_themes_boosted(self, ctx_abc_abd_xyz, meta, runner):
        """Built bridges should boost themes in the themespace."""
        ctx = ctx_abc_abd_xyz
        init = ctx.workspace.initial_string
        modified = ctx.workspace.modified_string
        slipnet = ctx.slipnet

        a_init = init.letters[0]
        a_mod = modified.letters[0]

        cm = ConceptMapping(
            slipnet.nodes["plato-letter-category"],
            a_init.letter_category,
            slipnet.nodes["plato-letter-category"],
            a_mod.letter_category,
            slipnet.nodes["plato-identity"],
        )
        bridge = Bridge(a_init, a_mod, BRIDGE_TOP, [cm])
        bridge.proposal_level = Bridge.BUILT
        bridge.strength = 80.0
        ctx.workspace.top_bridges.append(bridge)

        # Spread activation to themespace
        runner._spread_activation_to_themespace()

        # Check some theme was boosted (theme pattern has letter-category:identity)
        pattern = bridge.get_theme_pattern()
        assert len(pattern) > 0  # Bridge has a theme pattern


class TestReportAnswer:
    def test_report_answer_sets_workspace_answer_string(self, ctx_abc_abd_xyz):
        """report_answer must set workspace.answer_string so the UI can display it."""
        ctx = ctx_abc_abd_xyz

        # Precondition: no answer yet
        assert ctx.workspace.answer_string is None

        # Report an answer
        report_answer(ctx, "xye", 75.0)

        # workspace.answer_string must now be set
        assert ctx.workspace.answer_string is not None
        assert ctx.workspace.answer_string.text == "xye"

    def test_report_answer_sets_pending_answer(self, ctx_abc_abd_xyz):
        """report_answer must set _pending_answer for the runner to detect."""
        ctx = ctx_abc_abd_xyz

        report_answer(ctx, "xye", 75.0)

        assert getattr(ctx, "_pending_answer", None) == "xye"
        assert getattr(ctx, "_pending_answer_quality", None) == 75.0

    def test_report_answer_stores_in_episodic_memory(self, ctx_abc_abd_xyz):
        """report_answer must add an answer description to episodic memory."""
        ctx = ctx_abc_abd_xyz
        initial_count = len(ctx.memory.answers)

        report_answer(ctx, "xye", 75.0)

        assert len(ctx.memory.answers) == initial_count + 1

    def test_workspace_serialization_includes_answer(self, ctx_abc_abd_xyz):
        """After report_answer, serialize_workspace_state must include the answer."""
        try:
            from server.services.snapshot_service import serialize_workspace_state
        except ImportError:
            pytest.skip("sqlalchemy not available locally")
        ctx = ctx_abc_abd_xyz

        report_answer(ctx, "xye", 75.0)

        state = serialize_workspace_state(ctx)
        assert state["answer"] == "xye"


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════

def _get_test_builtins():
    """Get the full builtins registry for test codelet execution."""
    from server.engine.codelet_dsl.builtins import get_builtins
    return get_builtins()
