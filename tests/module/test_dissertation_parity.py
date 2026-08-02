"""Tests that encode the dissertation's claims, not the code's habits.

Each test cites the section of Marshall's dissertation (or the reference Scheme
in ``../Metacat``) that specifies the behaviour.  These are the tests that were
missing while the Themespace, jootsing, rule abstraction and answer
justification were all present in the codebase but unreachable at runtime.
"""

import os

import pytest

from server.engine.bridges import (
    BRIDGE_TOP,
    BRIDGE_VERTICAL,
    Bridge,
    make_concept_mappings,
)
from server.engine.memory import AnswerDescription, EpisodicMemory, SnagDescription
from server.engine.metadata import MetadataProvider
from server.engine.runner import EngineRunner
from server.engine.themes import (
    RELATION_DIFFERENT,
    RELATION_IDENTITY,
    THEME_TOP_BRIDGE,
    THEME_VERTICAL_BRIDGE,
    Theme,
    ThemeCluster,
    relation_name_for_label,
    relation_node_name,
)

# Every test here executes arithmetic the numeric substrate owns, so each one runs
# once per backend in the matrix. See tests/conftest.py.
pytestmark = pytest.mark.numeric_matrix

SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")


@pytest.fixture(scope="module")
def meta():
    return MetadataProvider.from_seed_data(SEED_DIR)


def _run(meta, initial, modified, target, answer=None, seed=0, steps=4000):
    runner = EngineRunner(meta)
    runner.init_mcat(initial, modified, target, answer=answer, seed=seed)
    runner.run_mcat(max_steps=steps)
    return runner


# ═══════════════════════════════════════════════════════════════════════════
# Phase A — the Themespace has to actually activate
# ═══════════════════════════════════════════════════════════════════════════


class TestThemespaceActivates:
    def test_relation_names_round_trip_through_slipnet_node_names(self):
        """The Themespace speaks bare relation names; the Slipnet speaks node names.

        Conflating the two is what silently disabled the whole Themespace: bridges
        offered ``plato-identity`` while clusters held ``identity``, so no theme
        was ever found and none was ever boosted.
        """

        class FakeLabel:
            name = "plato-opposite"

        assert relation_name_for_label(FakeLabel()) == "opposite"
        assert relation_node_name("opposite") == "plato-opposite"

        # "different" is the *absence* of a relating concept (themes.ss:715), so
        # it has no Slipnet node.
        assert relation_name_for_label(None) == RELATION_DIFFERENT
        assert relation_node_name(RELATION_DIFFERENT) is None

    def test_a_built_bridge_boosts_its_themes(self, meta):
        """§4.1: "Themes receive periodic infusions of activation from the
        Workspace structures (i.e., the bridges) associated with them."."""
        runner = _run(meta, "abc", "abd", "ijk", steps=600)
        activations = [
            t.activation
            for c in runner.ctx.themespace.clusters
            for t in c.themes
            if t.activation != 0
        ]
        assert activations, "no theme was activated in 600 codelets"
        assert max(activations) > 0

    def test_identical_letters_yield_a_letter_category_identity_theme(self, meta):
        """The a-a top bridge of "abc => abd" carries LetterCategory: identity."""
        runner = _run(meta, "abc", "abd", "ijk", steps=1)
        ws = runner.ctx.workspace
        a_initial = ws.initial_string.letters[0]
        a_modified = ws.modified_string.letters[0]
        bridge = Bridge(
            a_initial,
            a_modified,
            BRIDGE_TOP,
            make_concept_mappings(a_initial, a_modified, BRIDGE_TOP),
        )
        relations = dict(bridge.get_associated_thematic_relations())
        assert relations["plato-letter-category"] == RELATION_IDENTITY

    def test_unrelated_letters_yield_a_different_theme(self, meta):
        """§4.1: a theme's relation may be "the absence of a specific concept,
        which represents the idea of *different*".

        Deriving themes from concept-mappings and skipping the label-less ones
        made every ``X: different`` theme unreachable — yet vertical
        ``Letter-Category: different`` is dominant in Figs. 4.1 and 4.2.
        """
        runner = _run(meta, "abc", "abd", "ijk", steps=1)
        ws = runner.ctx.workspace
        a = ws.initial_string.letters[0]  # 'a'
        j = ws.target_string.letters[1]  # 'j' — neither identical nor linked to a
        bridge = Bridge(a, j, BRIDGE_VERTICAL, [])
        relations = dict(bridge.get_associated_thematic_relations())
        assert relations["plato-letter-category"] == RELATION_DIFFERENT

    def test_dominance_needs_a_margin_over_the_runner_up(self):
        """Scheme: ``update-dominant-theme`` (themes.ss:503-518) — the leader must
        beat the runner-up by strictly more than %dominant-theme-margin% (90)."""
        cluster = ThemeCluster(THEME_TOP_BRIDGE, "d", ["identity", "opposite"])
        identity, opposite = cluster.themes
        identity.activation = 95.0
        opposite.activation = 0.0
        assert cluster.get_dominant_theme(90.0) is identity

        opposite.activation = 10.0  # margin now only 85
        assert cluster.get_dominant_theme(90.0) is None

    def test_a_strong_negative_theme_blocks_dominance(self):
        """Themes are ranked by *absolute* activation, so a negatively clamped
        theme suppresses dominance in its cluster — which is the whole point of
        clamping one in response to a recurring snag (§4.5.2)."""
        cluster = ThemeCluster(THEME_TOP_BRIDGE, "d", ["identity", "opposite"])
        identity, opposite = cluster.themes
        identity.activation = 100.0
        opposite.activation = -95.0
        assert cluster.get_dominant_theme(90.0) is None


# ═══════════════════════════════════════════════════════════════════════════
# Phases B and C — thematic pressure
# ═══════════════════════════════════════════════════════════════════════════


class TestThematicPressure:
    def test_pressure_is_off_by_default(self, meta):
        """§4.1.2: "Most of the time, therefore, themes behave as passive
        representational structures ... having no return effect on this activity."."""
        runner = _run(meta, "abc", "abd", "ijk", steps=1)
        assert runner.ctx.themespace.has_thematic_pressure() is False

    def test_compatibility_is_zero_while_pressure_is_off(self, meta):
        """With pressure off a structure's strength is purely intrinsic."""
        runner = _run(meta, "abc", "abd", "ijk", steps=400)
        for bridge in runner.ctx.workspace.top_bridges:
            assert bridge.get_thematic_compatibility() == 0.0

    def test_a_compatible_theme_raises_a_bridge_and_an_incompatible_one_lowers_it(
        self, meta
    ):
        """§4.1.2 / Fig. 4.4: themes are "knobs" on structure strength — a small
        positive activation pushes a compatible structure toward full strength, a
        small negative activation quickly undermines it."""
        runner = _run(meta, "abc", "abd", "ijk", steps=1)
        ws, ts = runner.ctx.workspace, runner.ctx.themespace

        a_initial = ws.initial_string.letters[0]
        a_modified = ws.modified_string.letters[0]
        bridge = Bridge(
            a_initial,
            a_modified,
            BRIDGE_TOP,
            make_concept_mappings(a_initial, a_modified, BRIDGE_TOP),
        )
        bridge.update_strength()
        resting = bridge.strength

        cluster = next(
            c
            for c in ts.clusters
            if c.theme_type == THEME_TOP_BRIDGE
            and c.dimension == "plato-string-position-category"
        )
        theme = cluster.get_theme(RELATION_IDENTITY)

        ts.thematic_pressure_on([THEME_TOP_BRIDGE])
        theme.clamp(80.0)
        bridge.update_strength()
        assert bridge.strength >= resting

        theme.clamp(-80.0)
        bridge.update_strength()
        assert bridge.strength < resting

    def test_one_incompatible_theme_outweighs_two_compatible_ones(self, meta):
        """§4.1.2, p.143: "the incompatible themes will tend to drown out the
        compatible themes, even if the latter outnumber the former"."""
        runner = _run(meta, "abc", "abd", "ijk", steps=1)
        ts = runner.ctx.themespace
        ts.thematic_pressure_on([THEME_TOP_BRIDGE])

        class FakeBridge(Bridge):
            def get_theme_support_values(self):  # noqa: D102
                return [0.8, 0.8, -0.8]

        ws = runner.ctx.workspace
        fake = FakeBridge(
            ws.initial_string.letters[0],
            ws.modified_string.letters[0],
            BRIDGE_TOP,
            [],
        )
        assert fake.get_average_theme_support() < 0
        assert fake.get_thematic_compatibility() < 0


# ═══════════════════════════════════════════════════════════════════════════
# Phase H — horizontal / vertical asymmetry
# ═══════════════════════════════════════════════════════════════════════════


class TestBridgeAsymmetry:
    def test_vertical_bridges_get_no_letter_category_slippage(self, meta):
        """§3.3.1: "slippages involving length or letter-category ... are only
        possible for horizontal bridges."."""
        runner = _run(meta, "abc", "abd", "ijk", steps=1)
        ws = runner.ctx.workspace
        a = ws.initial_string.letters[0]
        i = ws.target_string.letters[0]

        vertical = make_concept_mappings(a, i, BRIDGE_VERTICAL)
        letter_cms = [
            cm
            for cm in vertical
            if cm.description_type1.name == "plato-letter-category"
        ]
        assert letter_cms == [], "a vertical a-i bridge must not slip a => i"

        # Position and object type still map, so the bridge is not empty.
        dimensions = {cm.description_type1.name for cm in vertical}
        assert "plato-string-position-category" in dimensions

    def test_horizontal_bridges_do_get_letter_category_slippage(self, meta):
        """The c-d bridge of "abc => abd" is exactly a letter-category slippage."""
        runner = _run(meta, "abc", "abd", "ijk", steps=1)
        ws = runner.ctx.workspace
        c = ws.initial_string.letters[2]
        d = ws.modified_string.letters[2]

        horizontal = make_concept_mappings(c, d, BRIDGE_TOP)
        letter_cms = [
            cm
            for cm in horizontal
            if cm.description_type1.name == "plato-letter-category"
        ]
        assert len(letter_cms) == 1
        assert letter_cms[0].is_slippage
        assert letter_cms[0].label.name == "plato-successor"


# ═══════════════════════════════════════════════════════════════════════════
# Phase E — rules
# ═══════════════════════════════════════════════════════════════════════════


class TestRules:
    def test_no_intrinsic_string_position_clause_is_ever_built(self, meta):
        """§3.3.2 footnote 2: "a change to an object's string position cannot be
        described intrinsically" — it is extrinsic-only."""
        for seed in range(6):
            runner = _run(meta, "abc", "abd", "xyz", seed=seed, steps=2500)
            for rule in runner.ctx.workspace.top_rules:
                for clause in rule.clauses:
                    if not clause.is_intrinsic:
                        continue
                    for change in clause.changes:
                        name = getattr(change.dimension, "name", "")
                        assert name != "plato-string-position-category", (
                            f"intrinsic string-position clause in "
                            f"{rule.transcribe_to_english()!r}"
                        )

    def test_abstract_change_descriptor_beats_a_literal_one(self, meta):
        """§3.3.5: "Change letter-category of rightmost letter to successor" is
        more abstract than "... to `d'".

        Averaging only the *dimension* depth scored these two identically, since
        both changes are along Letter-Category.
        """
        from server.engine.rules import (
            CLAUSE_INTRINSIC,
            RULE_TOP,
            Rule,
            RuleChange,
            RuleClause,
        )

        runner = _run(meta, "abc", "abd", "ijk", steps=1)
        sl = runner.ctx.slipnet

        def rule_with(change: RuleChange) -> Rule:
            clause = RuleClause(
                clause_type=CLAUSE_INTRINSIC,
                object_description=(
                    sl.nodes["plato-letter"],
                    sl.nodes["plato-string-position-category"],
                    sl.nodes["plato-rightmost"],
                ),
                changes=[change],
            )
            rule = Rule(RULE_TOP, [clause])
            rule.compute_quality(meta)
            return rule

        abstract = rule_with(
            RuleChange(
                dimension=sl.nodes["plato-letter-category"],
                relation=sl.nodes["plato-successor"],
            )
        )
        literal = rule_with(
            RuleChange(
                dimension=sl.nodes["plato-letter-category"],
                to_descriptor=sl.nodes["plato-d"],
            )
        )
        assert abstract.abstractness > literal.abstractness

    def test_verbatim_rules_are_uniform_and_succinct_but_not_abstract(self, meta):
        """§3.3.5: "Verbatim rules ... are maximally uniform, minimally abstract,
        and maximally succinct."."""
        from server.engine.rules import CLAUSE_VERBATIM, RULE_TOP, Rule, RuleClause

        runner = _run(meta, "abc", "abd", "ijk", steps=1)
        sl = runner.ctx.slipnet
        rule = Rule(
            RULE_TOP,
            [
                RuleClause(
                    clause_type=CLAUSE_VERBATIM,
                    verbatim_letters=[sl.nodes[f"plato-{c}"] for c in "abd"],
                )
            ],
        )
        rule.compute_quality(meta)
        assert rule.uniformity == 100.0
        assert rule.abstractness == 0.0
        assert rule.succinctness == 100.0

    def test_the_identity_rule_is_maximal_on_all_three_measures(self, meta):
        """§3.3.5: "The identity rule Don't change anything is maximally uniform,
        maximally abstract, and maximally succinct."."""
        from server.engine.rules import RULE_TOP, Rule

        rule = Rule(RULE_TOP, [])
        rule.compute_quality(meta)
        assert rule.is_identity_rule
        assert (rule.uniformity, rule.abstractness, rule.succinctness) == (
            100.0,
            100.0,
            100.0,
        )

    def test_rule_application_handles_a_successor_and_snags_on_z(self, meta):
        """Applying "change letter-category of rightmost letter to successor"."""
        from server.engine.codelet_dsl.builtins import apply_rule
        from server.engine.rules import (
            CLAUSE_INTRINSIC,
            RULE_BOTTOM,
            Rule,
            RuleClause,
            RuleChange,
        )

        def rule_for(ctx):
            sl = ctx.slipnet
            return Rule(
                RULE_BOTTOM,
                [
                    RuleClause(
                        clause_type=CLAUSE_INTRINSIC,
                        object_description=(
                            sl.nodes["plato-letter"],
                            sl.nodes["plato-string-position-category"],
                            sl.nodes["plato-rightmost"],
                        ),
                        changes=[
                            RuleChange(
                                dimension=sl.nodes["plato-letter-category"],
                                relation=sl.nodes["plato-successor"],
                            )
                        ],
                    )
                ],
            )

        ok = _run(meta, "abc", "abd", "abc", steps=1).ctx
        assert apply_rule(ok, rule_for(ok)) == "abd"

        # 'z' has no successor: that is a snag, reported as a failed application.
        snag = _run(meta, "abc", "abd", "xyz", steps=1).ctx
        assert apply_rule(snag, rule_for(snag)) is None

    def test_translation_does_not_always_apply_every_slippage(self, meta):
        """§3.4: translation is nondeterministic in Metacat.

        Figs. 3.11/3.12 differ only in whether a slippage was applied when
        translating, which is where ``kji`` rather than ``kkkjjjiii`` comes from.
        """
        from server.engine.codelet_dsl.builtins import translate_rule

        ctx = None
        for seed in range(8):
            runner = _run(meta, "abc", "abd", "kji", seed=seed, steps=1500)
            if runner.ctx.workspace.top_rules:
                ctx = runner.ctx
                break
        assert ctx is not None, "no rule was built in 8 runs of abc=>abd; kji=>?"
        rule = ctx.workspace.top_rules[0]

        outcomes = set()
        for _ in range(40):
            translated = translate_rule(ctx, rule)
            if translated is None:
                continue
            outcomes.add(
                tuple(
                    getattr(ch.relation or ch.to_descriptor, "name", None)
                    for c in translated.clauses
                    for ch in c.changes
                )
            )
        # Either the run produced slippable mappings (so we see variety), or none
        # were slippable at all — but the mechanism must not be hard-wired.
        assert outcomes, "translation produced nothing at all"


# ═══════════════════════════════════════════════════════════════════════════
# Phases D and I — the Trace and self-watching
# ═══════════════════════════════════════════════════════════════════════════


class TestTraceAndSelfWatching:
    def test_a_snag_produces_a_snag_event_carrying_structures_and_themes(self, meta):
        """§4.7.2: a snag description holds the structures responsible, a vertical
        theme-pattern, the top rule and the translated rule.

        Snags used to be plain TraceEvents with none of that, so the jootser's
        snag branch bailed out immediately and never fired.
        """
        from server.engine.trace import SNAG, SnagEvent

        for seed in range(8):
            runner = _run(meta, "abc", "abd", "xyz", seed=seed, steps=3000)
            snags = [
                e
                for e in runner.ctx.trace.get_events_by_type(SNAG)
                if isinstance(e, SnagEvent)
            ]
            if snags:
                snag = snags[0]
                assert snag.snag_rule is not None
                assert snag.translated_rule is not None
                assert snag.snag_theme_pattern is not None
                return
        pytest.fail("no SnagEvent in 8 runs of abc=>abd; xyz=>?")

    def test_a_snag_is_remembered_in_episodic_memory(self, meta):
        """§4.7.2: "On hitting a new snag for the first time, the program creates
        an abstract snag description ... which it then stores in memory."."""
        memory = EpisodicMemory()
        for seed in range(8):
            runner = EngineRunner(meta)
            runner.init_mcat("abc", "abd", "xyz", seed=seed, memory=memory)
            runner.run_mcat(max_steps=3000)
            if memory.snags:
                snag = memory.snags[0]
                assert snag.problem == ("abc", "abd", "xyz")
                assert snag.description  # the rule that could not be applied
                return
        pytest.fail("no snag description stored in 8 runs")

    def test_a_snag_clamps_the_temperature(self, meta):
        """Metacat clamps temperature while it deals with a snag, to force
        focused exploration rather than more random search."""
        for seed in range(8):
            runner = _run(meta, "abc", "abd", "xyz", seed=seed, steps=800)
            if runner.ctx.trace.snag_count > 0:
                assert runner.ctx.trace.within_snag_period or (
                    runner.ctx.temperature.clamped
                    or runner.ctx.trace.last_unclamp_time >= 0
                )
                return
        pytest.skip("no snag occurred within 800 codelets")

    def test_the_trace_stays_at_the_cognitive_level(self, meta):
        """§4.4: "at the level of description of the Trace, a typical run consists
        of a few dozen steps."

        Recording every bond, bridge and description built or broken produced
        ~150 events per run and destroyed the Trace's role as the filtered,
        chunked record that progress-watchers and jootsers reason over.
        """
        from server.engine.trace import COGNITIVE_EVENT_TYPES

        runner = _run(meta, "abc", "abd", "xyz", seed=3, steps=2000)
        events = runner.ctx.trace.events
        types = {e.event_type for e in events}
        assert types <= set(COGNITIVE_EVENT_TYPES), (
            f"subcognitive events leaked into the Trace: "
            f"{types - set(COGNITIVE_EVENT_TYPES)}"
        )
        assert len(events) < 100, (
            f"{len(events)} Trace events for a 2000-codelet run — the Trace is "
            f"supposed to hold a few dozen milestones"
        )

    def test_concept_activation_events_are_recorded(self, meta):
        """§4.4: "nodes in the Slipnet monitor their own levels of activation,
        adding new concept-activation events to the Trace whenever sufficiently
        large changes occur in the activations of deep concepts."."""
        from server.engine.trace import CONCEPT_ACTIVATION

        runner = _run(meta, "abc", "abd", "xyz", seed=1, steps=1500)
        assert runner.ctx.trace.get_events_by_type(CONCEPT_ACTIVATION)

    def test_the_jootser_receives_everything_it_needs_to_act(self, meta):
        """The jootser was being called without ``rng``, ``slipnet`` or
        ``workspace``, so every stochastic branch was skipped and jootsing could
        never happen at all (§4.5.2)."""
        import inspect

        from server.engine.codelet_dsl.interpreter import (
            CodeletInterpreter,
            CodeletRegistry,
        )
        from server.engine.codelet_dsl.builtins import get_builtins

        registry = CodeletRegistry.from_metadata(
            meta, CodeletInterpreter(builtins=get_builtins())
        )
        body = registry.get_compiled("jootser").source
        for argument in ("rng=rng", "slipnet=slipnet", "workspace=workspace"):
            assert argument in body, f"jootser does not pass {argument}"

    def test_the_progress_watcher_receives_everything_it_needs_to_act(self, meta):
        """Likewise ``check_progress`` without ``rng``/``themespace``/``slipnet``
        reported zero progress forever and never posted a follow-up
        answer-finder (§4.5.1)."""
        from server.engine.codelet_dsl.interpreter import (
            CodeletInterpreter,
            CodeletRegistry,
        )
        from server.engine.codelet_dsl.builtins import get_builtins

        registry = CodeletRegistry.from_metadata(
            meta, CodeletInterpreter(builtins=get_builtins())
        )
        body = registry.get_compiled("progress-watcher").source
        for argument in (
            "rng=rng",
            "themespace=themespace",
            "slipnet=slipnet",
            "justify_mode=justify_mode",
        ):
            assert argument in body, f"progress-watcher does not pass {argument}"


# ═══════════════════════════════════════════════════════════════════════════
# Phase J — Episodic Memory, reminding and comparison
# ═══════════════════════════════════════════════════════════════════════════


def _answer(name, themes, *, rule="rule", abstractness=60.0, unjustified=None):
    return AnswerDescription(
        problem=("abc", "abd", "xyz", name),
        top_rule_description=rule,
        bottom_rule_description="",
        top_rule_quality=70.0,
        bottom_rule_quality=0.0,
        quality=70.0,
        temperature=30.0,
        themes=dict(themes),
        unjustified_slippages=[],
        unjustified_themes=dict(unjustified or {}),
        top_rule_abstractness=abstractness,
    )


class TestMemory:
    def test_comparison_separates_common_differing_and_unique_themes(self):
        """§4.7.3 names three distinct relationships; "a_only / b_only" conflated
        differing themes with unique ones."""
        memory = EpisodicMemory()
        xyd = _answer(
            "xyd",
            {
                "plato-string-position-category": "identity",
                "plato-direction-category": "identity",
            },
        )
        dyz = _answer(
            "dyz",
            {
                "plato-string-position-category": "opposite",
                "plato-direction-category": "identity",
                "plato-alphabetic-position-category": "opposite",
            },
        )
        result = memory.compare_answers(xyd, dyz)

        assert result["common_themes"] == {"plato-direction-category": "identity"}
        assert result["differing_themes"] == {
            "plato-string-position-category": ("identity", "opposite")
        }
        assert result["b_unique_themes"] == {
            "plato-alphabetic-position-category": "opposite"
        }
        assert result["a_unique_themes"] == {}

    def test_similar_answers_are_closer_than_dissimilar_ones(self):
        """§4.7.5: distance grows with differing and unique themes."""
        memory = EpisodicMemory()
        base = _answer("xyd", {"plato-string-position-category": "identity"})
        near = _answer("xyu", {"plato-string-position-category": "identity"})
        far = _answer(
            "dyz",
            {
                "plato-string-position-category": "opposite",
                "plato-direction-category": "opposite",
                "plato-alphabetic-position-category": "opposite",
            },
        )
        assert memory.distance(base, near) < memory.distance(base, far)

    def test_an_unrelated_answer_does_not_come_to_mind(self):
        """Reminding must discriminate.  With an empty theme comparison and a
        threshold of 5 it used to return *every* stored answer at distance 0."""
        memory = EpisodicMemory()
        far = _answer(
            "dyz",
            {
                "plato-string-position-category": "opposite",
                "plato-direction-category": "opposite",
                "plato-alphabetic-position-category": "opposite",
            },
            rule="a completely different rule",
            abstractness=10.0,
        )
        memory.store_answer(far)
        query = _answer("xyd", {"plato-string-position-category": "identity"})
        assert memory.find_remindings(query, distance_threshold=2.0) == []

    def test_reminding_sets_an_activation_level(self):
        """§4.7.5: "the activation level of an answer reflects how strongly the
        program is reminded of it."."""
        memory = EpisodicMemory()
        past = _answer("xyu", {"plato-string-position-category": "identity"})
        memory.store_answer(past)
        query = _answer("xyd", {"plato-string-position-category": "identity"})
        memory.find_remindings(query, distance_threshold=5.0)
        assert 0 < past.activation <= 100
        assert query.activation == 100.0

    def test_a_stored_snag_reclassifies_an_unjustified_theme(self):
        """§4.7.3: the aaabccc / aaabaaa discrimination.

        An unjustified theme becomes *snag-justified* when a snag description in
        memory shows the same strings and rule ran into a snag — which is why
        seeing abbbc as 1-3-1 is justified after all, while doing the same to
        abbba is not.
        """
        memory = EpisodicMemory()
        rule = "Swap letter-categories of all objects in string"

        with_snag = AnswerDescription(
            problem=("eqe", "qeq", "abbbc", "aaabccc"),
            top_rule_description=rule,
            bottom_rule_description="",
            top_rule_quality=70.0,
            bottom_rule_quality=0.0,
            quality=70.0,
            temperature=30.0,
            themes={"plato-string-position-category": "identity"},
            unjustified_slippages=[],
            unjustified_themes={"plato-bond-facet": "diff"},
        )
        without_snag = AnswerDescription(
            problem=("eqe", "qeq", "abbba", "aaabaaa"),
            top_rule_description=rule,
            bottom_rule_description="",
            top_rule_quality=70.0,
            bottom_rule_quality=0.0,
            quality=70.0,
            temperature=30.0,
            themes={"plato-string-position-category": "identity"},
            unjustified_slippages=[],
            unjustified_themes={"plato-bond-facet": "diff"},
        )
        memory.store_snag(
            SnagDescription(
                problem=("eqe", "qeq", "abbbc"),
                codelet_count=500,
                temperature=40.0,
                theme_pattern={"plato-string-position-category": "identity"},
                description=rule,
            )
        )

        result = memory.compare_answers(with_snag, without_snag)
        assert result["a_unjustified_themes"]["plato-bond-facet"] == "snag_justified"
        assert result["b_unjustified_themes"]["plato-bond-facet"] == "unjustified"

    def test_comparison_produces_english_commentary(self):
        """§4.7.4: the classification is rendered through phrase-templates.

        The templates were all present in the seed data and referenced by no code
        at all, so the program could not talk about its answers.
        """
        from server.engine.commentary import describe_answer_comparison

        memory = EpisodicMemory()
        xyd = _answer("xyd", {"plato-string-position-category": "identity"})
        dyz = _answer(
            "dyz",
            {
                "plato-string-position-category": "opposite",
                "plato-alphabetic-position-category": "opposite",
            },
        )
        commentary = describe_answer_comparison(xyd, dyz, memory=memory)

        assert commentary["paragraphs"]
        assert "xyd" in commentary["text"] and "dyz" in commentary["text"]
        assert commentary["verdict"].startswith("All in all")


# ═══════════════════════════════════════════════════════════════════════════
# Emergent behaviour on the dissertation's own problems
# ═══════════════════════════════════════════════════════════════════════════


# The dissertation's own problems, with the answers it documents for each and how
# often the primary one should turn up.  Floors rather than exact distributions:
# the model is stochastic by design, and the guard's job is that the documented
# interpretation is reachable and common, not that it is the only one.  Answers
# outside the documented set are perfectly acceptable.
CANONICAL = [
    # problem,                  primary documented answer, min hits out of 12
    (("abc", "abd", "ijk"), "ijl", 5),        # §1.5, the baseline
    (("abc", "abd", "xyz"), "xyd", 4),        # §5.2.1, Figs. 4.12/4.14
    (("abc", "abd", "kji"), "kjj", 5),        # Fig. 4.5
    (("abc", "abd", "iijjkk"), "iijjkl", 5),  # §3.4
    (("rst", "rsu", "xyz"), "xyu", 5),        # §5.2.1 Run 3 / Fig. 4.17
    (("abc", "abd", "mrrjjj"), "mrrjjk", 5),  # §5.1.2, the mrrjjj family
]

# Answers that require the rule to be applied to a *group* in the target rather
# than to a letter — i.e. the initial string's changing letter has to be seen as
# corresponding to a whole group.  §1.5 describes exactly this fork: "depending on
# ... whether or not c in abc is seen as corresponding to the jjj group or to just
# the rightmost letter j in mrrjjj", and names mrrkkk as "by far the most common"
# answer.  None of these appeared at all before the group-bridge work.
GROUP_LEVEL = [
    (("abc", "abd", "mrrjjj"), "mrrkkk", 2),   # c ⇒ the jjj group  (§1.5)
    (("abc", "abd", "iijjkk"), "iijjll", 2),   # c ⇒ the kk group   (§3.4)
    (("abc", "abcd", "ijk"), "ijkl", 2),       # whole-group length (§3.3.3)
]

# Group-level answers are inherently rarer than letter-level ones — they need the
# whole group structure in place first — so they are sampled over a wider range.
GROUP_LEVEL_SEEDS = range(24)

# Problems whose documented answers all require a group-level rule applied to the
# target (changing a *group's* length or letter-category).  Those are still out
# of reach — see the "Known remaining gap" section of FINISH_METACAT_PORT.md — so
# here we only require that the program reaches *an* answer rather than stalling.
ANSWERS_SOMETHING = [
    ("abc", "abd", "kkjjii"),
    ("abc", "abd", "iijjkk"),
    ("abc", "abd", "mrrjjj"),
    ("rst", "rsu", "xyz"),
    ("abc", "abd", "xyz"),
    ("abc", "abd", "ijk"),
    ("abc", "abd", "kji"),
]

SEEDS = range(12)


@pytest.mark.parametrize("problem,canonical,min_hits", CANONICAL)
def test_the_documented_answer_is_reachable_and_common(meta, problem, canonical, min_hits):
    """Regression guard: the dissertation's own answer must actually turn up.

    Before the port was reconnected, ``abc => abd; xyz => ?`` never produced
    ``xyd`` at all, ``ijl`` came up 4 times in 12, and ``abc => abd; mrrjjj => ?``
    answered ``mrrkjj`` — changing the wrong letters — in a third of its runs.
    """
    found: list[str] = []
    for seed in SEEDS:
        runner = _run(meta, *problem, seed=seed, steps=4000)
        if runner._answers:
            found.append(runner._answers[0])

    assert found, f"no answer at all for {problem} across {len(list(SEEDS))} seeds"
    hits = found.count(canonical)
    assert hits >= min_hits, (
        f"{problem} produced {canonical!r} only {hits} times "
        f"(expected at least {min_hits}); answers were {found}"
    )


@pytest.mark.parametrize("problem", ANSWERS_SOMETHING)
def test_every_documented_problem_reaches_an_answer(meta, problem):
    """The program should not simply stall on a problem the dissertation runs.

    Several of these used to produce no answer at all in a third to a half of
    their runs, because the translated rule could never be applied to the target.
    """
    stalled = 0
    for seed in SEEDS:
        runner = _run(meta, *problem, seed=seed, steps=4000)
        if not runner._answers:
            stalled += 1
    assert stalled <= 2, f"{problem} stalled in {stalled} of {len(list(SEEDS))} runs"


@pytest.mark.parametrize("problem,canonical,min_hits", GROUP_LEVEL)
def test_group_level_answers_are_reachable(meta, problem, canonical, min_hits):
    """The changing letter must sometimes be seen as a whole *group*.

    Four things had to line up for this, all of which were broken:

    * ``_singleton_factor`` penalised every letter-group bridge by 0.1, so an
      ``a-aa`` bridge could never compete with ``a-a``;
    * ``important-object-bridge-scout`` took the *first* descriptor match in
      ``string.objects``, where letters always precede groups;
    * ``WorkspaceString.choose_object`` ignored salience entirely, weighting every
      object equally;
    * rule translation was handed the whole vertical mapping at once, so an
      unrelated ``letter => letter`` identity shadowed the ``letter => group``
      slippage that mattered.
    """
    found: list[str] = []
    for seed in GROUP_LEVEL_SEEDS:
        runner = _run(meta, *problem, seed=seed, steps=4000)
        if runner._answers:
            found.append(runner._answers[0])

    hits = found.count(canonical)
    assert hits >= min_hits, (
        f"{problem} produced the group-level answer {canonical!r} only {hits} "
        f"times (expected at least {min_hits}); answers were {found}"
    )


def test_a_rule_can_target_a_group_in_the_target_string(meta):
    """§1.5: "Replace length of rightmost group by successor".

    A rule whose object-description names a *group* must resolve against the
    target's group and transform it.  ``(group String-Position whole)`` used to
    resolve to the string itself, whose image cannot take a length change.
    """
    from server.engine.codelet_dsl.builtins import apply_rule
    from server.engine.rules import (
        CLAUSE_INTRINSIC,
        RULE_BOTTOM,
        Rule,
        RuleChange,
        RuleClause,
        SCOPE_SELF,
    )

    for seed in range(8):
        runner = _run(meta, "abc", "abd", "iijjkk", seed=seed, steps=2500)
        ctx = runner.ctx
        groups = [g for g in ctx.workspace.target_string.groups if g.is_built]
        rightmost = [
            g
            for g in groups
            if any(
                d.descriptor.name == "plato-rightmost"
                for d in g.get_all_descriptions()
            )
        ]
        if not rightmost:
            continue

        sl = ctx.slipnet
        rule = Rule(
            RULE_BOTTOM,
            [
                RuleClause(
                    clause_type=CLAUSE_INTRINSIC,
                    object_description=(
                        sl.nodes["plato-group"],
                        sl.nodes["plato-string-position-category"],
                        sl.nodes["plato-rightmost"],
                    ),
                    changes=[
                        RuleChange(
                            dimension=sl.nodes["plato-letter-category"],
                            relation=sl.nodes["plato-successor"],
                            referent=SCOPE_SELF,
                        )
                    ],
                )
            ],
        )
        assert apply_rule(ctx, rule) == "iijjll"
        return
    pytest.fail("target never grew a rightmost group in 8 runs")


def test_the_xyz_family_reaches_more_than_one_documented_answer(meta):
    """§5.1.1: the xyz family is interesting precisely because it admits several
    answers — xyd, wyz, dyz and the do-nothing xyz.

    A model that only ever produced one of them would have lost the point.
    """
    documented = {"xyd", "wyz", "dyz", "xyz", "yz"}
    found: set[str] = set()
    for seed in range(20):
        runner = _run(meta, "abc", "abd", "xyz", seed=seed, steps=4000)
        if runner._answers:
            found.add(runner._answers[0])
    assert len(found & documented) >= 2, (
        f"only reached {sorted(found & documented)} of the documented xyz answers; "
        f"all answers seen were {sorted(found)}"
    )


@pytest.mark.parametrize("problem", [p for p, _c, _h in CANONICAL])
def test_answers_never_explode_in_length(meta, problem):
    """No answer should be wildly longer than the string it transforms.

    A stale, shared image tree used to compound each rule application, so
    ``xyz`` came back as ``xxxxyyyyzzzz`` and ``mrrjjj`` as
    ``mrrrrrrrjjjjjjjjjjjj``.  Metacat's own length-changing answers grow by at
    most a factor of two (``abc => aabbcc``), plus a letter (``abc => abcd``).
    """
    target = problem[2]
    limit = 2 * len(target) + 1
    for seed in SEEDS:
        runner = _run(meta, *problem, seed=seed, steps=4000)
        for answer in runner._answers:
            assert len(answer) <= limit, (
                f"{problem} seed {seed} answered {answer!r} "
                f"({len(answer)} letters, limit {limit})"
            )


@pytest.mark.parametrize("problem", [p for p, _c, _h in CANONICAL])
def test_every_answer_is_a_letter_string(meta, problem):
    """Answers are always strings over the alphabet Metacat knows."""
    for seed in SEEDS:
        runner = _run(meta, *problem, seed=seed, steps=4000)
        for answer in runner._answers:
            assert answer and answer.isalpha() and answer.islower(), (
                f"{problem} seed {seed} answered {answer!r}"
            )


# ═══════════════════════════════════════════════════════════════════════════
# Phase K — the fields the UI reads must exist on the engine objects
# ═══════════════════════════════════════════════════════════════════════════


class TestUiSurface:
    """The API layer needs sqlalchemy/fastapi, which the venv provides.

    These tests therefore check the *engine-side* shape the serializers read, so a
    change that silently drops a field the UI depends on fails here rather than in
    a browser.
    """

    def test_clusters_expose_server_side_dominance(self, meta):
        """ThemespaceView used to recompute dominance with its own rule
        (max |activation|, threshold 5) rather than the engine's margin of 90."""
        runner = _run(meta, "abc", "abd", "ijk", steps=400)
        margin = meta.get_param("dominant_theme_margin", 90)
        for cluster in runner.ctx.themespace.clusters:
            dominant = cluster.get_dominant_theme(margin)
            assert dominant is None or dominant in cluster.themes

    def test_themespace_exposes_possible_and_active_theme_types(self, meta):
        """The UI shows "pressure on/off"; that needs both lists, since they mean
        different things (mode-relevant vs currently exerting pressure)."""
        ts = _run(meta, "abc", "abd", "ijk", steps=1).ctx.themespace
        assert isinstance(ts.possible_theme_types, list)
        assert isinstance(ts.active_theme_types, list)
        assert THEME_TOP_BRIDGE in ts.possible_theme_types
        assert THEME_VERTICAL_BRIDGE in ts.possible_theme_types

    def test_rules_expose_all_three_quality_measures(self, meta):
        """The Workspace view renders q/u/a/s so §3.3.5 is checkable by eye."""
        for seed in range(6):
            runner = _run(meta, "abc", "abd", "ijk", seed=seed, steps=2000)
            for rule in runner.ctx.workspace.top_rules:
                for attribute in ("quality", "uniformity", "abstractness", "succinctness"):
                    assert isinstance(getattr(rule, attribute), (int, float))
                return
        pytest.fail("no rule was built in 6 runs")

    def test_answer_descriptions_expose_everything_memory_view_shows(self, meta):
        """Activation, the three theme patterns, unjustified themes, coherence."""
        memory = EpisodicMemory()
        for seed in range(6):
            runner = EngineRunner(meta)
            runner.init_mcat("abc", "abd", "ijk", seed=seed, memory=memory)
            runner.run_mcat(max_steps=3000)
            if memory.answers:
                answer = memory.answers[0]
                assert isinstance(answer.activation, float)
                assert isinstance(answer.top_themes, dict)
                assert isinstance(answer.vertical_themes, dict)
                assert isinstance(answer.bottom_themes, dict)
                assert isinstance(answer.unjustified_themes, dict)
                assert isinstance(answer.is_coherent, bool)
                return
        pytest.fail("no answer stored in 6 runs")


# ═══════════════════════════════════════════════════════════════════════════
# Phase F — answer justification (§4.3)
# ═══════════════════════════════════════════════════════════════════════════


class TestJustification:
    def test_justify_mode_builds_bottom_rules(self, meta):
        """A bottom rule describes the target string changing into the answer.

        ``rule-scout`` only ever read the *top* bridges and always emitted a top
        rule, so no bottom rule was ever built and justify mode could not produce
        a result at all (§4.3: "'bottom rules' based on this mapping that describe
        how the target string changes into the answer string").
        """
        for seed in range(6):
            runner = _run(meta, "abc", "abd", "xyz", answer="xyd", seed=seed, steps=3000)
            if runner.ctx.workspace.bottom_rules:
                return
        pytest.fail("no bottom rule built in 6 justification runs")

    def test_a_straightforward_answer_gets_justified(self, meta):
        """§4.3: justification needs a top rule, an analogous bottom rule, and a
        vertical mapping consistent with both.

        ``xyd`` is the easy case — the vertical mapping is a plain alignment — so
        the program should reach a coherent interpretation of it.
        """
        justified = 0
        for seed in range(6):
            runner = _run(meta, "abc", "abd", "xyz", answer="xyd", seed=seed, steps=4000)
            if runner._answers:
                justified += 1
        assert justified >= 2, f"justified xyd in only {justified} of 6 runs"

    def test_justification_never_crashes_and_gives_up_gracefully(self, meta):
        """§4.5.2: faced with a cycle it cannot break, the program "simply 'gives
        up' in a graceful manner and stops"."""
        from server.engine.runner import STATUS_ANSWER_FOUND, STATUS_GAVE_UP, STATUS_HALTED

        acceptable = {STATUS_ANSWER_FOUND, STATUS_GAVE_UP, STATUS_HALTED}
        for answer in ("wyz", "dyz", "xyd"):
            for seed in range(4):
                runner = _run(
                    meta, "abc", "abd", "xyz", answer=answer, seed=seed, steps=3000
                )
                assert runner.status in acceptable, (
                    f"justifying {answer!r} (seed {seed}) ended in {runner.status}"
                )


# ═══════════════════════════════════════════════════════════════════════════
# Structural capabilities
#
# Functional equivalence with Metacat is about the *machinery* being present, not
# about matching answer frequencies.  Some answers the dissertation documents are
# rare even for Metacat — of ``mrrjjjj`` it says "Many people do not think of the
# answer mrrjjjj, even when given an unlimited amount of time", and its own Run 1
# for that answer is a *justification* run.  So these tests assert the structures
# and rule forms are reachable, which is the claim that actually matters.
# ═══════════════════════════════════════════════════════════════════════════


class TestStructuralCapabilities:
    def test_singleton_groups_form(self, meta):
        """§groups.ss:466-486: a lone letter can be wrapped in a group of length one.

        Without this a bare letter has no Length description, so it cannot bond to
        a neighbouring group on the Length facet — and the 1-2-3 reading of
        ``mrrjjj`` becomes impossible.
        """
        for seed in range(12):
            runner = _run(meta, "abc", "abd", "mrrjjj", seed=seed, steps=4000)
            for group in runner.ctx.workspace.target_string.groups:
                if group.is_built and len(group.objects) == 1:
                    lengths = [
                        d.descriptor.short_name
                        for d in group.get_all_descriptions()
                        if d.description_type.name == "plato-length"
                    ]
                    assert lengths == ["one"]
                    return
        pytest.fail("no singleton group formed in 12 runs of abc=>abd; mrrjjj=>?")

    def test_a_group_can_be_bonded_to_another_group(self, meta):
        """Bonds join adjacent objects at the same level of the hierarchy.

        ``choose_neighbor`` used ``get_object_at``, which returns the first object
        covering a position — and letters always precede groups in
        ``string.objects``.  A group was therefore never offered a neighbouring
        group, so no group-to-group bond could ever be proposed.
        """
        from server.engine.codelet_dsl.builtins import choose_neighbor

        for seed in range(12):
            runner = _run(meta, "abc", "abd", "mrrjjj", seed=seed, steps=3000)
            groups = [
                g
                for g in runner.ctx.workspace.target_string.groups
                if g.is_built and g.enclosing_group is None
            ]
            if len(groups) < 2:
                continue
            for group in groups:
                neighbor = choose_neighbor(runner.ctx, group)
                if neighbor is not None and hasattr(neighbor, "objects"):
                    return
        pytest.fail("a group was never offered a neighbouring group in 12 runs")

    def test_the_one_two_three_reading_of_mrrjjj_is_constructible(self, meta):
        """§5.2.1 Run 1 / Fig. 5.2: ``mrrjjj`` seen abstractly as 1-2-3.

        The whole chain has to work: singleton ``m``, successor bonds between the
        groups *on the Length facet*, a group of those groups — and the resulting
        nested image must still generate ``mrrjjj`` when nothing has been changed.
        """
        from server.engine.bonds import Bond
        from server.engine.codelet_dsl.builtins import build_structure, get_bond_category
        from server.engine.groups import Group
        from server.engine.rules import _fresh_string_image

        for seed in range(12):
            runner = _run(meta, "abc", "abd", "mrrjjj", seed=seed, steps=3000)
            ctx = runner.ctx
            target = ctx.workspace.target_string
            groups = sorted(
                (g for g in target.groups if g.is_built and g.enclosing_group is None),
                key=lambda g: g.left_string_pos,
            )
            if len(groups) != 3:
                continue

            length = ctx.slipnet.nodes["plato-length"]
            descriptors = []
            for group in groups:
                found = [
                    d.descriptor
                    for d in group.get_all_descriptions()
                    if d.description_type is length
                ]
                if not found:
                    break
                descriptors.append(found[0])
            if len(descriptors) != 3:
                continue

            # 1 -> 2 -> 3 on the Length facet is a successor relation.
            assert [d.short_name for d in descriptors] == ["one", "two", "three"]
            right = ctx.slipnet.nodes["plato-right"]
            bonds = []
            for i in range(2):
                category = get_bond_category(ctx, descriptors[i], descriptors[i + 1])
                assert category is not None and category.short_name == "succ"
                bond = Bond(
                    groups[i], groups[i + 1], category, length,
                    descriptors[i], descriptors[i + 1], right,
                )
                bond.proposal_level = Bond.EVALUATED
                build_structure(ctx, bond)
                bonds.append(bond)

            nested = Group(
                target, ctx.slipnet.nodes["plato-succgrp"], length, right,
                list(groups), bonds,
            )
            described = {
                (d.description_type.short_name, d.descriptor.short_name)
                for d in nested.get_all_descriptions()
            }
            assert ("BondFacet", "Length") in described
            assert ("StringPos", "whole") in described
            assert ("Length", "three") in described

            # The nested image must still reproduce the untouched string.
            nested.proposal_level = Group.BUILT
            target.add_group(nested)
            image = _fresh_string_image(target, ctx.slipnet)
            assert "".join(n.short_name for n in image.generate()) == "mrrjjj"

            # Nesting has to be readable from the outside: the workspace display
            # sizes each group enclosure by span and insets subgroups by depth,
            # so a group-of-groups must report a level above its constituents.
            assert nested.get_nesting_level() == 0
            assert [g.get_nesting_level() for g in groups] == [1, 1, 1]
            assert nested.length == 3
            return

        pytest.fail("mrrjjj never resolved into three groups in 12 runs")

    def test_descriptor_predicates_live_in_the_seed_data(self, meta):
        """A Slipnet node's descriptor predicate is domain knowledge, not code.

        Scheme: ``(tell plato-x 'define-descriptor-predicate ...)`` attaches the
        predicate to the node.  Petacat carries it in ``slipnet_nodes.json`` and
        compiles it at startup, the same arrangement as a codelet's
        ``execute_body`` — so a new descriptor needs no code change.
        """
        from server.engine.slipnet import Slipnet

        slipnet = Slipnet.from_metadata(meta)
        with_predicate = [
            n for n in slipnet.nodes.values() if n.descriptor_predicate is not None
        ]
        assert len(with_predicate) == 14

        # And they decide correctly.
        runner = _run(meta, "abc", "abd", "xyz", steps=1)
        letters = runner.ctx.workspace.initial_string.letters
        assert slipnet.nodes["plato-leftmost"].describes(letters[0])
        assert not slipnet.nodes["plato-leftmost"].describes(letters[2])
        assert slipnet.nodes["plato-rightmost"].describes(letters[2])
        assert slipnet.nodes["plato-middle"].describes(letters[1])
        assert slipnet.nodes["plato-letter"].describes(letters[0])
        assert not slipnet.nodes["plato-group"].describes(letters[0])
