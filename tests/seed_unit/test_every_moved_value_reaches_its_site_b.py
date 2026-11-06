"""Every value stage 5 (group B) moved into the database reaches the site it came from.

Group B: the run, the codelet bodies' builtins, self-watching, memory, justify, the random
stream, the services and the client.  Each key below was a literal in the engine.  Three
claims are made for every one:

1. **It reaches a run.**  A table-driven mutation: the Metacat Standard Configuration with
   the one key changed, against the unchanged configuration, on a (problem, seed) that reaches
   the site.  Their fingerprints (the codelet sequence, the draws, the final state, the Trace
   and the Episodic Memory) must differ.  A site that goes back to its literal ignores the key
   and the two runs are identical, so the row fails.  ``cap`` stops a run just past the first
   codelet at which the two part (``probe_keys.py`` found it), or lets it finish when they part
   only in the Trace or the state.
2. **Today's value is the old literal, in its old form** (an int stays an int, a float a
   float; ruling 8).  ``test_every_moved_key_carries_the_old_literal_and_its_type``.
3. **Removing the key stops the run**: ``test_declared_names_stop_the_run.py`` walks the
   declared read list, which this stage extended.

The sites no run in reasonable time reaches are tested directly, below the table, with the
reason beside each.
"""

from __future__ import annotations

import dataclasses
import os

import pytest

from server.engine.metadata import MetadataProvider
from server.engine.start_check import check_run_start
from tests.support import golden_baseline as gb

SEED = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")

#: (key, table, mutated value, problem, answer, first seed, episode length, cap)
#: ``episode`` > 0 runs that many seeds in a row on one Episodic Memory and compares the last.
RUN_ROWS = [
    ('perturb_up_probability', 'params', 0.05, ('abc', 'abd', 'mrrjjj'), None, 1, 0, 557),
    ('perturb_delta_exponent', 'coeff', 1.0, ('abc', 'abd', 'mrrjjj'), None, 1, 0, 18),
    ('bond_scan_exponent', 'coeff', 1, ('abc', 'abd', 'mrrjjj'), None, 2, 0, 417),
    ('spanning_bridge_theme_boost_factor', 'coeff', 6, ('rst', 'rsu', 'xyz'), None, 2, 0, 6000),
    ('slippage_importance_unlabelled_depth', 'coeff', 0.0, ('ab', 'c', 'ab'), None, 1, 0, 6000),
    ('slippage_importance_spanning_term', 'coeff', 0.0, ('rst', 'rsu', 'xyz'), None, 2, 0, 1817),
    ('slippage_importance_weight_dimension_depth', 'coeff', 40.0, ('abc', 'abd', 'mrrjjj'), None, 1, 0, 6000),
    ('slippage_importance_weight_spanning', 'coeff', 20.0, ('abc', 'abd', 'xyz'), None, 2, 0, 2168),
    ('slippage_importance_weight_descriptor_depth', 'coeff', 20.0, ('rst', 'rsu', 'xyz'), None, 2, 0, 1817),
    ('slippage_importance_weight_label_depth', 'coeff', 30.0, ('rst', 'rsu', 'xyz'), None, 1, 0, 1635),
    ('group_special_importance', 'params', 0.0, ('abc', 'abd', 'mrrjjj'), None, 2, 0, 6000),
    ('thematic_slippage_importance', 'params', 0.0, ('abc', 'abd', 'mrrjjj'), 'mrrjjjj', 1, 0, 1884),
    ('uniform_rule_importance', 'params', 0.0, ('abc', 'abd', 'mrrjjj'), None, 1, 0, 6000),
    ('perfect_rule_uniformity', 'params', 101, ('rst', 'rsu', 'xyz'), None, 1, 0, 6000),
    ('bond_facet_choice_local_support_weight', 'coeff', 0.0, ('eeqee', 'qeeq', 'xxixx'), None, 1, 0, 962),
    ('bond_facet_choice_activation_weight', 'coeff', 0.0, ('eeqee', 'qeeq', 'xxixx'), None, 1, 0, 857),
    ('scout_string_choice_relevance_weight', 'coeff', 0.0, ('abc', 'abd', 'mrrjjj'), None, 1, 0, 56),
    ('scout_string_choice_unhappiness_weight', 'coeff', 0.0, ('abc', 'abd', 'mrrjjj'), None, 1, 0, 47),
    ('answer_distance_base', 'coeff', 9.0, ('abc', 'abd', 'mrrjjj'), None, 1, 3, 6000),
    ('new_answer_activation', 'params', 40.0, ('abc', 'abd', 'mrrjjj'), None, 1, 0, 6000),
    ('jootsing_recurring_clamps_min', 'params', 1, ('rst', 'rsu', 'xyz'), None, 1, 0, 1150),
    ('jootsing_recurring_snags_min', 'params', 1, ('rst', 'rsu', 'xyz'), None, 1, 0, 544),
    ('justify_retention_string_position', 'params', 0.0, ('abc', 'abd', 'mrrjjj'), 'mrrjjjj', 1, 0, 1580),
    ('justify_retention_non_identity_percent', 'params', 5.0, ('abc', 'abd', 'mrrjjj'), 'mrrjjjj', 1, 0, 1580),
    ('fight_bond_vs_bond_proposer_weight', 'coeff', 0.0, ('xqc', 'xqd', 'mrrjjj'), None, 1, 0, 392),
    ('fight_bond_vs_bond_opponent_weight', 'coeff', 9.0, ('xqc', 'xqd', 'mrrjjj'), None, 1, 0, 392),
    ('fight_bond_vs_group_proposer_weight', 'coeff', 0.0, ('rst', 'rsu', 'xyz'), None, 1, 0, 514),
    ('fight_bond_vs_bridge_proposer_weight', 'coeff', 0.0, ('rst', 'rsu', 'xyz'), None, 1, 0, 517),
    ('fight_bond_vs_bridge_opponent_weight', 'coeff', 30.0, ('rst', 'rsu', 'xyz'), None, 1, 0, 1687),
    ('fight_group_vs_flipped_bond_opponent_weight', 'coeff', 30.0, ('rst', 'rsu', 'xyz'), None, 1, 0, 586),
    ('fight_group_vs_group_proposer_weight', 'coeff', 0.0, ('abc', 'abd', 'glz'), None, 1, 0, 271),
    ('fight_group_vs_group_opponent_weight', 'coeff', 30.0, ('abc', 'abd', 'glz'), None, 1, 0, 271),
    ('fight_group_vs_bridge_proposer_weight', 'coeff', 0.0, ('rst', 'rsu', 'xyz'), None, 1, 0, 1771),
    ('fight_group_vs_bridge_opponent_weight', 'coeff', 30.0, ('rst', 'rsu', 'xyz'), None, 1, 0, 1771),
    ('fight_bridge_vs_bond_proposer_weight', 'coeff', 0.0, ('rst', 'rsu', 'xyz'), None, 1, 0, 1229),
    ('fight_bridge_vs_bond_opponent_weight', 'coeff', 30.0, ('rst', 'rsu', 'xyz'), None, 1, 0, 1229),
    ('fight_bridge_vs_enclosing_group_proposer_weight', 'coeff', 0.0, ('rst', 'rsu', 'xyz'), None, 1, 0, 1337),
    ('fight_bridge_vs_enclosing_group_opponent_weight', 'coeff', 30.0, ('rst', 'rsu', 'xyz'), None, 1, 0, 1337),
    ('fight_bridge_vs_flipped_group_proposer_weight', 'coeff', 0.0, ('rst', 'rsu', 'xyz'), 'uyz', 1, 0, 1931),
    ('fight_bridge_vs_flipped_group_opponent_weight', 'coeff', 30.0, ('rst', 'rsu', 'xyz'), 'uyz', 1, 0, 1931),
]

#: The old literal of every moved key and its type: (key, table, value).
OLD_LITERALS = [
    ("perturb_up_probability", "params", 0.5),
    ("perturb_delta_exponent", "coeff", 0.5),
    ("bond_scan_exponent", "coeff", 2),
    ("spanning_bridge_theme_boost_factor", "coeff", 2),
    ("slippage_importance_unlabelled_depth", "coeff", 50.0),
    ("slippage_importance_spanning_term", "coeff", 100.0),
    ("slippage_importance_weight_dimension_depth", "coeff", 4.0),
    ("slippage_importance_weight_spanning", "coeff", 2.0),
    ("slippage_importance_weight_descriptor_depth", "coeff", 2.0),
    ("slippage_importance_weight_label_depth", "coeff", 3.0),
    ("group_special_importance", "params", 100.0),
    ("thematic_slippage_importance", "params", 100.0),
    ("uniform_rule_importance", "params", 100.0),
    ("perfect_rule_uniformity", "params", 100),
    ("bond_facet_choice_local_support_weight", "coeff", 1.0),
    ("bond_facet_choice_activation_weight", "coeff", 1.0),
    ("scout_string_choice_relevance_weight", "coeff", 1.0),
    ("scout_string_choice_unhappiness_weight", "coeff", 1.0),
    ("answer_distance_base", "coeff", 1.0),
    ("answer_distance_differing_theme_weight", "coeff", 1.0),
    ("answer_distance_justification_weight", "coeff", 1.0),
    ("answer_distance_coherence_weight", "coeff", 1.0),
    ("answer_incoherent_theme_abstractness_min", "params", 50.0),
    ("answer_incoherent_abstractness_gap_min", "params", 25.0),
    ("new_answer_activation", "params", 100.0),
    ("jootsing_recurring_clamps_min", "params", 3),
    ("jootsing_recurring_snags_min", "params", 3),
    ("jootsing_elapsed_weight_at_start", "params", 100.0),
    ("justify_retention_string_position", "params", 1.0),
    ("justify_retention_non_identity_percent", "params", 100.0),
    ("default_max_codelets", "params", 20000),
    ("fight_bond_vs_bond_proposer_weight", "coeff", 1.0),
    ("fight_bond_vs_bond_opponent_weight", "coeff", 1.0),
    ("fight_bond_vs_group_proposer_weight", "coeff", 1.0),
    ("fight_bond_vs_bridge_proposer_weight", "coeff", 2.0),
    ("fight_bond_vs_bridge_opponent_weight", "coeff", 3.0),
    ("fight_group_vs_flipped_bond_opponent_weight", "coeff", 1.0),
    ("fight_group_vs_group_proposer_weight", "coeff", 1.0),
    ("fight_group_vs_group_opponent_weight", "coeff", 1.0),
    ("fight_group_vs_bridge_proposer_weight", "coeff", 1.0),
    ("fight_group_vs_bridge_opponent_weight", "coeff", 1.0),
    ("fight_bridge_vs_bond_proposer_weight", "coeff", 3.0),
    ("fight_bridge_vs_bond_opponent_weight", "coeff", 2.0),
    ("fight_bridge_vs_enclosing_group_proposer_weight", "coeff", 1.0),
    ("fight_bridge_vs_enclosing_group_opponent_weight", "coeff", 1.0),
    ("fight_bridge_vs_flipped_group_proposer_weight", "coeff", 1.0),
    ("fight_bridge_vs_flipped_group_opponent_weight", "coeff", 1.0),
]


@pytest.fixture(scope="module")
def meta() -> MetadataProvider:
    return MetadataProvider.from_standard_configuration(SEED)


def _with(meta: MetadataProvider, table: str, key: str, value):
    if table == "params":
        assert key in meta.params, key
        return dataclasses.replace(meta, params={**meta.params, key: value})
    assert key in meta.formula_coefficients, key
    return dataclasses.replace(
        meta, formula_coefficients={**meta.formula_coefficients, key: value}
    )


def _fingerprint(meta, problem, answer, seed, episode, cap):
    from server.engine.hashing import memory_hash
    from server.engine.memory import EpisodicMemory

    memory = EpisodicMemory()
    seeds = [seed] if not episode else list(range(seed, seed + episode))
    for s in seeds:
        runner, _rng, draws, types, _init = gb.run_observed(
            meta, problem, s, answer, memory, False, None, cap, "numpy"
        )
        ctx = runner.ctx
        last = (
            gb.sha(",".join(types)),
            gb.sha(",".join(map(str, draws))),
            gb.state_digest(ctx),
            gb.sha(gb.canonical(gb._trace_summary(ctx.trace.events))),
            memory_hash(memory),
        )
    return last


@pytest.mark.numeric_matrix
@pytest.mark.parametrize(
    "key,table,value,problem,answer,seed,episode,cap",
    RUN_ROWS,
    ids=[r[0] for r in RUN_ROWS],
)
def test_changing_a_moved_key_changes_a_run_that_reaches_its_site(
    meta, key, table, value, problem, answer, seed, episode, cap
):
    base = _fingerprint(meta, problem, answer, seed, episode, cap)
    changed = _fingerprint(_with(meta, table, key, value), problem, answer, seed, episode, cap)
    assert changed != base, f"{key} = {value!r} changed nothing on {problem} seed {seed}"


def test_every_moved_key_carries_the_old_literal_and_its_type(meta):
    for key, table, want in OLD_LITERALS:
        got = (meta.params if table == "params" else meta.formula_coefficients)[key]
        assert got == want and type(got) is type(want), f"{key}: {got!r} is not {want!r}"


def test_every_key_with_a_row_or_a_direct_test_is_on_the_declared_read_list(meta):
    from server.engine import start_check as sc

    declared = {n for n, _ in sc.REQUIRED_ENGINE_PARAMETERS} | {
        n for n, _ in sc.REQUIRED_FORMULA_COEFFICIENTS
    }
    for key, _table, _want in OLD_LITERALS:
        assert key in declared, key
        table = "params" if key in meta.params else "coeff"
        stripped = (
            dataclasses.replace(meta, params={k: v for k, v in meta.params.items() if k != key})
            if table == "params"
            else dataclasses.replace(
                meta,
                formula_coefficients={
                    k: v for k, v in meta.formula_coefficients.items() if k != key
                },
            )
        )
        assert any(p.name == key for p in check_run_start(stripped)), key


# ---------------------------------------------------------------------------
# Rows that need a chain of runs on one Episodic Memory
# ---------------------------------------------------------------------------

CHAIN = [
    ("abc", "abd", "ijk"),
    ("abc", "abd", "xyz"),
    ("abc", "abd", "mrrjjj"),
    ("abc", "abd", "ijkk"),
    ("rst", "rsu", "xyz"),
]


@pytest.mark.numeric_matrix
def test_a_differing_theme_weight_reaches_the_reminding_of_a_chain_of_runs(meta):
    """``answer_distance_differing_theme_weight``: answers of different problems that hold a
    theme in different relations are closer or further apart, which moves how strongly the
    next answer reminds the program of them (the activations in the Episodic Memory)."""
    from server.engine.hashing import memory_hash
    from server.engine.memory import EpisodicMemory

    def chain(m):
        memory = EpisodicMemory()
        marks = []
        for i, problem in enumerate(CHAIN):
            gb.run_observed(m, problem, 1 + i, None, memory, False, None, 4000, "numpy")
            marks.append((memory_hash(memory), tuple(a.activation for a in memory.answers)))
        return marks

    base = chain(meta)
    changed = chain(_with(meta, "coeff", "answer_distance_differing_theme_weight", -9.0))
    assert changed != base


# ---------------------------------------------------------------------------
# Sites no run in reasonable time reaches: a direct test of the site
# ---------------------------------------------------------------------------


def _answer(problem, top_abstractness, theme_abstractness, **kw):
    from server.engine.memory import AnswerDescription

    return AnswerDescription(
        problem=problem,
        top_rule_description="r",
        bottom_rule_description="r",
        top_rule_quality=50.0,
        bottom_rule_quality=50.0,
        quality=50.0,
        temperature=50.0,
        themes={},
        unjustified_slippages=[],
        top_rule_abstractness=top_abstractness,
        theme_abstractness=theme_abstractness,
        top_rule_signature=kw.pop("sig", [["x"]]),
        bottom_rule_signature=[["y"]],
        **kw,
    )


@pytest.mark.parametrize(
    "key,table,value",
    [
        ("answer_incoherent_theme_abstractness_min", "params", 60.0),
        ("answer_incoherent_abstractness_gap_min", "params", 50.0),
    ],
)
def test_the_two_cut_offs_of_an_incoherent_answer_are_read(meta, key, table, value):
    """Metacat's ``answer-incoherent?`` (answers.ss:909-916): themes above 50, a rule that is
    more literal, by more than 25.  In the standard configuration this answer is incoherent;
    raising either cut-off past it makes it coherent."""
    a = _answer(("a", "b", "c", "d"), top_abstractness=10.0, theme_abstractness=60.0)
    assert a.is_coherent(meta) is False
    assert a.is_coherent(_with(meta, table, key, value)) is True


def test_the_literal_cut_offs_are_exactly_the_old_ones(meta):
    """The old test, ``> 50.0 and rule < theme and (theme - rule) > 25.0``, against the
    configured one, over the whole grid of whole-number abstractness values."""

    def old(theme, rule):
        return not (theme > 50.0 and rule < theme and (theme - rule) > 25.0) if theme > 0.0 else True

    for theme in range(0, 101):
        for rule in range(0, 101, 5):
            a = _answer(("a", "b", "c", "d"), float(rule), float(theme))
            assert a.is_coherent(meta) is old(float(theme), float(rule)), (theme, rule)


class _StubComparison:
    """What ``AnswerComparison`` hands ``EpisodicMemory.distance``, set by the test."""

    fields: dict = {}

    def __init__(self, *args, **kwargs):
        for name, value in self.fields.items():
            setattr(self, name, value)
        self.unresolved_names = set()


def _stub(monkeypatch, **fields):
    import server.engine.answer_comparison as ac

    base = dict(
        differing_dimensions=[],
        unique1=[],
        unique2=[],
        num_rule_differences=0,
        common_a_only_unjustified=[],
        common_b_only_unjustified=[],
    )
    base.update(fields)
    _StubComparison.fields = base
    monkeypatch.setattr(ac, "AnswerComparison", _StubComparison)


def _distance(meta, a, b):
    from server.engine.memory import EpisodicMemory

    return EpisodicMemory().distance(a, b, meta)


def test_the_distance_of_two_answers_reads_each_of_its_five_terms(meta, monkeypatch):
    a = _answer(("a", "b", "c", "d"), 10.0, 60.0)  # incoherent in the standard configuration
    b = _answer(("a", "b", "c", "e"), 90.0, 60.0, sig=[["z"]])  # coherent
    _stub(
        monkeypatch,
        differing_dimensions=[1, 2],
        unique1=[1],
        unique2=[],
        num_rule_differences=3,
        common_a_only_unjustified=[1, 2],
        common_b_only_unjustified=[1],
    )
    base = _distance(meta, a, b)
    # 1.0 + (2*1 + 2*(1+0)) + 2*3 + (2+1) + 1.0 (the coherence mismatch)
    assert base == 1.0 + (2 * 1.0 + 2.0 * 1) + 2.0 * 3 + 3 + 1.0
    for key, delta in [
        ("answer_distance_base", 4.0),
        ("answer_distance_differing_theme_weight", 2 * 4.0),
        ("answer_distance_justification_weight", 3 * 4.0),
        ("answer_distance_coherence_weight", 4.0),
    ]:
        moved = _distance(_with(meta, "coeff", key, meta.formula_coefficients[key] + 4.0), a, b)
        assert moved == base + delta, key


def test_the_distance_is_the_old_sum_over_a_grid_of_counts(meta, monkeypatch):
    """With the standard coefficients the configured terms are the old literals:
    ``1.0 + (n_diff + 2*(u1+u2)) + 2*rules + (j_a + j_b) + (1.0 if coherence mismatch)``."""
    coherent = _answer(("a", "b", "c", "d"), 90.0, 60.0)
    other_coherent = _answer(("a", "b", "c", "f"), 90.0, 60.0, sig=[["w"]])
    incoherent = _answer(("a", "b", "c", "e"), 10.0, 60.0, sig=[["z"]])
    for n_diff in range(0, 4):
        for u1 in range(0, 3):
            for u2 in range(0, 3):
                for rules in (0, 1, 4):
                    for ja in range(0, 3):
                        for jb in range(0, 2):
                            _stub(
                                monkeypatch,
                                differing_dimensions=[0] * n_diff,
                                unique1=[0] * u1,
                                unique2=[0] * u2,
                                num_rule_differences=rules,
                                common_a_only_unjustified=[0] * ja,
                                common_b_only_unjustified=[0] * jb,
                            )
                            for a, b, mismatch in (
                                (coherent, other_coherent, False),
                                (coherent, incoherent, True),
                            ):
                                old = 1.0
                                old += float(n_diff + 2.0 * u1 + 2.0 * u2)
                                old += 2.0 * rules
                                old += float(ja + jb)
                                if mismatch:
                                    old += 1.0
                                assert _distance(meta, a, b) == old


def test_a_clamp_made_before_the_first_codelet_weighs_what_the_configuration_says(meta):
    """``jootsing_elapsed_weight_at_start``: ``get-clamp-jootsing-probability`` weights a clamp
    by when it happened as a percent of the run; with no codelet yet (jootsing.ss:127) every
    weight is the configured full weight.  No run reaches it (a jootser is a codelet), so the
    site is called directly.

    Every clamp then carries the same weight, so the weighted average of their progress is the
    same for any weight above zero (the weights cancel); the key shows only at zero, where the
    weights sum to nothing and the average is 0 instead of the progress.  That is the reason a
    mutation to another positive value changes nothing, and the test says so."""
    from server.engine.jootsing import get_clamp_jootsing_probability
    from server.engine.trace import ClampEvent

    clamp = ClampEvent(0, 50.0, clamp_type="snag_response_clamp")
    clamp.progress_achieved = 40.0
    clamps = [clamp, clamp, clamp]

    base = get_clamp_jootsing_probability(clamps, 0, None, meta=meta)
    # (1 - 40/100) * min(1, 10 * 3 / 100) * 1.0 (a snag response clamp)
    assert base == (1.0 - 40.0 / 100.0) * min(1.0, 10 * 3 / 100.0) * 1.0

    seven = get_clamp_jootsing_probability(
        clamps, 0, None, meta=_with(meta, "params", "jootsing_elapsed_weight_at_start", 7.0)
    )
    assert seven == base  # equal weights cancel

    zero = get_clamp_jootsing_probability(
        clamps, 0, None, meta=_with(meta, "params", "jootsing_elapsed_weight_at_start", 0.0)
    )
    assert zero != base


# ---------------------------------------------------------------------------
# The random stream: both generators, the exact square root
# ---------------------------------------------------------------------------


def test_pow_exact_is_the_correctly_rounded_square_root_at_one_half_and_a_power_otherwise():
    """``pow(x, 0.5)`` and ``sqrt(x)`` part in the last bit for some ``x``; the helper must
    be ``math.sqrt`` at exactly 0.5 (ruling 4) and ``**`` for any other exponent."""
    import math

    from server.engine.formulas import pow_exact

    parted = 0
    for n in range(1, 4000):
        x = n * 0.37 + 0.001 * n * n
        assert pow_exact(x, 0.5) == math.sqrt(x)
        parted += x**0.5 != math.sqrt(x)
    assert parted > 0, "the sample should include numbers where ** and sqrt differ"
    assert pow_exact(7, 2) == 49 and type(pow_exact(7, 2)) is int
    assert pow_exact(2.0, 3) == 8.0 and pow_exact(9.0, 1.5) == 27.0


def test_the_splittable_generators_tilde_is_the_old_one_with_the_standard_configuration():
    """``SplittableRNG.perturb`` (the stream the speculative and update-cycle workers draw
    from) reads ``perturb_up_probability`` and ``perturb_delta_exponent``.  With the standard
    values it draws exactly what ``n + delta if prob(0.5) else n - delta`` with
    ``delta = randint(1 + round(sqrt n))`` drew; the two configured values change it."""
    import math

    from server.engine.run_binding import RunBinding, use_run
    from server.engine.splittable_rng import SplittableRNG

    def old(rng, n):
        if n <= 0:
            return n
        delta = rng.randint(1 + round(math.sqrt(abs(n))))
        return n + delta if rng.prob(0.5) else n - delta

    for seed in range(1, 9):
        a, b = SplittableRNG(seed, 7), SplittableRNG(seed, 7)
        for n in (0, -1, 0.1, 1, 2, 3, 4, 6.25, 12.25, 50, 100):
            assert a.perturb(n) == old(b, n), (seed, n)

    def drawn(meta):
        binding = RunBinding.for_meta(meta)
        with use_run(binding):
            rng = SplittableRNG(3, 5)
            return [rng.perturb(n) for n in (4, 9, 16, 25, 36, 49) for _ in range(20)]

    base_meta = MetadataProvider.from_standard_configuration(SEED)
    base = drawn(base_meta)
    never_up = drawn(_with(base_meta, "params", "perturb_up_probability", 0.0))
    assert all(v <= n for v, n in zip(never_up, [n for n in (4, 9, 16, 25, 36, 49) for _ in range(20)]))
    assert never_up != base
    assert drawn(_with(base_meta, "coeff", "perturb_delta_exponent", 1.0)) != base
