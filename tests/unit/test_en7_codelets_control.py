"""EN7: codelets and control read roles (configuration-source plan 5.2, row EN7).

* the initial-description order, per string shape, equals the order recorded from the engine
  before EN7 (plan 4.2: the order feeds every stochastic description pick);
* the thematic phase posts the same list as before, and iterates every rule directed
  ``thematic`` in file order;
* the RNG draw count of every codelet is the golden baseline's (G3's per-codelet check on a
  representative pair of runs, in the quick suite);
* G9: with a role unbound, or its node removed, a run is built and stepped with no exception.
"""

from __future__ import annotations

import gzip
import json
from dataclasses import replace

import pytest

from tests.support import golden_baseline as gb
from tests.support import reduced_configurations as rc
from tests.support.role_table import SINGLE_ROLES

from server.engine.numeric.backend import use_backend
from server.engine.rng import RNG
from server.engine.roles import absent
from server.engine.runner import EngineRunner

pytestmark = pytest.mark.numeric_matrix

# Recorded from the engine before EN7 (agents-workspace/stage2-EN7/capture_today.py).
# A description is (description type, descriptor) with the ``plato-`` prefix left off.
DESCRIPTIONS_TODAY = {
    'a': [
        [('string-position-category', 'single'), ('letter-category', 'a'), ('object-category', 'letter')],
    ],
    'ab': [
        [('string-position-category', 'leftmost'), ('letter-category', 'a'), ('object-category', 'letter')],
        [('string-position-category', 'rightmost'), ('letter-category', 'b'), ('object-category', 'letter')],
    ],
    'abc': [
        [('string-position-category', 'leftmost'), ('letter-category', 'a'), ('object-category', 'letter')],
        [('string-position-category', 'middle'), ('letter-category', 'b'), ('object-category', 'letter')],
        [('string-position-category', 'rightmost'), ('letter-category', 'c'), ('object-category', 'letter')],
    ],
    'abcd': [
        [('string-position-category', 'leftmost'), ('letter-category', 'a'), ('object-category', 'letter')],
        [('letter-category', 'b'), ('object-category', 'letter')],
        [('letter-category', 'c'), ('object-category', 'letter')],
        [('string-position-category', 'rightmost'), ('letter-category', 'd'), ('object-category', 'letter')],
    ],
    'aab': [
        [('string-position-category', 'leftmost'), ('letter-category', 'a'), ('object-category', 'letter')],
        [('string-position-category', 'middle'), ('letter-category', 'a'), ('object-category', 'letter')],
        [('string-position-category', 'rightmost'), ('letter-category', 'b'), ('object-category', 'letter')],
    ],
    'aaa': [
        [('string-position-category', 'leftmost'), ('letter-category', 'a'), ('object-category', 'letter')],
        [('string-position-category', 'middle'), ('letter-category', 'a'), ('object-category', 'letter')],
        [('string-position-category', 'rightmost'), ('letter-category', 'a'), ('object-category', 'letter')],
    ],
    'mrrjjj': [
        [('string-position-category', 'leftmost'), ('letter-category', 'm'), ('object-category', 'letter')],
        [('letter-category', 'r'), ('object-category', 'letter')],
        [('letter-category', 'r'), ('object-category', 'letter')],
        [('letter-category', 'j'), ('object-category', 'letter')],
        [('letter-category', 'j'), ('object-category', 'letter')],
        [('string-position-category', 'rightmost'), ('letter-category', 'j'), ('object-category', 'letter')],
    ],
    'abca': [
        [('string-position-category', 'leftmost'), ('letter-category', 'a'), ('object-category', 'letter')],
        [('letter-category', 'b'), ('object-category', 'letter')],
        [('letter-category', 'c'), ('object-category', 'letter')],
        [('string-position-category', 'rightmost'), ('letter-category', 'a'), ('object-category', 'letter')],
    ],
    'aabb': [
        [('string-position-category', 'leftmost'), ('letter-category', 'a'), ('object-category', 'letter')],
        [('letter-category', 'a'), ('object-category', 'letter')],
        [('letter-category', 'b'), ('object-category', 'letter')],
        [('string-position-category', 'rightmost'), ('letter-category', 'b'), ('object-category', 'letter')],
    ],
}
THEMATIC_POSTED_SEED_1 = [(1, 10, 30), (2, 10, 45), (4, 10, 75), (5, 10, 90), (6, 8, 105), (7, 8, 120), (10, 3, 165), (12, 3, 195), (14, 3, 225), (16, 3, 255), (17, 3, 270), (18, 6, 285), (19, 7, 300), (21, 7, 330), (22, 7, 345), (24, 5, 375), (26, 2, 400), (30, 2, 450), (31, 3, 465), (36, 2, 540), (40, 2, 600), (41, 2, 615), (44, 6, 660), (45, 5, 675), (46, 5, 690), (47, 6, 705), (48, 6, 720), (49, 6, 735), (50, 2, 750), (51, 2, 765), (52, 2, 780), (53, 2, 795)]


@pytest.fixture(scope="module")
def meta():
    return gb.load_meta()


def _runner(meta, initial, modified="abd", target="xyz", seed=1):
    runner = EngineRunner(meta)
    with use_backend(gb.BACKEND):
        runner.init_mcat(initial, modified, target, seed=seed, rng=RNG(seed))
    return runner


@pytest.mark.parametrize("shape", sorted(DESCRIPTIONS_TODAY))
def test_initial_descriptions_keep_today_order(meta, shape) -> None:
    runner = _runner(meta, shape, "abd", "xyz" if len(shape) != 1 else "xx")
    got = [
        [(d.description_type.name[6:], d.descriptor.name[6:]) for d in o.descriptions]
        for o in runner.ctx.workspace.initial_string.objects
    ]
    assert got == DESCRIPTIONS_TODAY[shape]


def test_the_shapes_cover_single_two_three_and_repeated_letters() -> None:
    lengths = {len(s) for s in DESCRIPTIONS_TODAY}
    assert {1, 2, 3} <= lengths and any(len(set(s)) < len(s) for s in DESCRIPTIONS_TODAY)


def _thematic_posts(meta, seed=1, steps=800):
    runner = EngineRunner(meta)
    rng = RNG(seed)
    out: list[tuple[int, int, int]] = []
    real = runner._post_thematic_codelets
    count = [0]

    def wrapped(batch=None):
        n = len(batch)
        real(batch)
        added = batch[n:]
        if added:
            out.append((count[0], len(added), added[0].time_stamp))
        count[0] += 1

    runner._post_thematic_codelets = wrapped
    always = EngineRunner._rule_condition_holds
    probability = runner._compute_posting_probability
    runner._rule_condition_holds = (
        lambda rule: True if rule and rule.direction == "thematic" else always(runner, rule)
    )
    runner._compute_posting_probability = (
        lambda rule: 0.6 if rule and rule.direction == "thematic" else probability(rule)
    )
    with use_backend(gb.BACKEND):
        runner.init_mcat("abc", "abd", "ijk", seed=seed, rng=rng)
        for _ in range(steps):
            runner.step_mcat()
    return out


def test_the_thematic_phase_posts_todays_list(meta) -> None:
    assert _thematic_posts(meta) == THEMATIC_POSTED_SEED_1


def test_thematic_rules_are_iterated_by_direction_in_file_order(meta) -> None:
    (rule,) = [r for r in meta.posting_rules if r.direction == "thematic"]
    other = replace(rule, rule_key="second-thematic", codelet_type="bottom-up-bridge-scout")
    plain = next(r for r in meta.posting_rules if r.direction == "bottom_up")
    runner = _runner(meta, "abc")
    runner._rule_condition_holds = lambda r: True
    runner._compute_posting_probability = lambda r: 1.0
    runner._compute_num_to_post = lambda r: 1

    runner.meta = replace(meta, posting_rules=[plain, rule, other])
    batch: list = []
    runner._post_thematic_codelets(batch)
    assert [c.codelet_type for c in batch] == [rule.codelet_type, "bottom-up-bridge-scout"]

    runner.meta = replace(meta, posting_rules=[plain, other, rule])
    batch = []
    runner._post_thematic_codelets(batch)
    assert [c.codelet_type for c in batch] == ["bottom-up-bridge-scout", rule.codelet_type]

    runner.meta = replace(meta, posting_rules=[plain])
    batch = []
    runner._post_thematic_codelets(batch)
    assert batch == []


def test_rng_draws_per_codelet_are_the_golden_baselines(meta) -> None:
    records = [json.loads(line) for line in gb.BASELINE_PATH.read_text().splitlines()[1:]]
    sidecar = json.loads(gzip.decompress(gb.RNG_DETAIL_PATH.read_bytes()))
    picked = sorted(
        (r for r in records if r["kind"] == "discovery" and r["seed"] == 1),
        key=lambda r: r["codelets"],
    )[:2]
    assert picked
    for r in picked:
        problem = tuple(r["problem"])
        _, _, draws, _types, init = _observe(meta, problem, r["seed"])
        assert init == sidecar[r["id"]]["init"], r["id"]
        assert draws == sidecar[r["id"]]["per_codelet"], r["id"]


def _observe(meta, problem, seed):
    from server.engine.memory import EpisodicMemory

    runner, rng, draws, types, init = gb.run_observed(meta, problem, seed, None, EpisodicMemory(), False)
    return runner, rng, draws, types, init


# --- G9 -----------------------------------------------------------------------------------

#: The roles EN7 converts (node roles whose literal the codelets or the runner named).
CONVERTED_NODE_ROLES = (
    "direction.left", "direction.right", "dimension.bond_category",
    "dimension.letter_category", "dimension.length", "dimension.object_category",
    "dimension.string_position", "position.leftmost", "position.rightmost", "position.middle",
    "position.single", "object.letter", "bond_category.sameness", "group_category.sameness",
)
CONVERTED_CODELET_ROLES = ("evaluator.bond", "evaluator.group", "evaluator.description")
#: ``workspace.py`` still reads ``plato-bond-facet`` by name (the workspace package, not EN7):
#: a run on a configuration without that node cannot start until that package lands.
WORKSPACE_PENDING = pytest.param(
    "dimension.bond_facet",
    marks=pytest.mark.xfail(reason="workspace.py names plato-bond-facet (not EN7's file)", strict=False),
)
G9_ROLES = (*CONVERTED_NODE_ROLES, WORKSPACE_PENDING)
G9_STEPS = 150


def _step(meta, problem, seed=1, steps=G9_STEPS):
    runner = EngineRunner(meta)
    with use_backend(gb.BACKEND):
        runner.init_mcat(*problem, seed=seed, rng=RNG(seed))
        for _ in range(steps):
            if runner.step_mcat().codelet_type is None:
                break
    return runner


def _demo_problems():
    triples, _ = gb.demo_problems()
    return triples


@pytest.mark.slow
@pytest.mark.parametrize("role", G9_ROLES)
def test_g9_node_roles_unbound_run_on_every_demo_problem(role) -> None:
    provider = rc.provider(rc.role_unbound(role))
    for problem in _demo_problems():
        _step(provider, problem)


@pytest.mark.slow
@pytest.mark.parametrize("role", G9_ROLES)
def test_g9_node_removed_runs(role) -> None:
    provider = rc.provider(rc.node_removed(SINGLE_ROLES[role]))
    for problem in _demo_problems()[:4]:
        _step(provider, problem)


@pytest.mark.slow
@pytest.mark.parametrize("role", CONVERTED_CODELET_ROLES)
def test_g9_codelet_roles_unbound_run_on_every_demo_problem(role) -> None:
    provider = rc.provider(rc.role_unbound(role))
    for problem in _demo_problems():
        _step(provider, problem)


def test_an_absent_evaluator_role_posts_nothing(meta) -> None:
    from server.engine.codelet_dsl.builtins import post_codelet

    runner = _runner(meta, "abc")
    ctx = runner.ctx
    before = len(list(ctx.coderack.codelets)) if hasattr(ctx.coderack, "codelets") else None
    post_codelet(ctx, absent("evaluator.bond"), 50, structure=None)
    if before is not None:
        assert len(list(ctx.coderack.codelets)) == before


def test_single_letter_group_probability_with_length_absent() -> None:
    from server.engine.codelet_dsl.builtins import single_letter_group_probability

    runner = _runner(rc.provider(rc.role_unbound("dimension.length")), "abc")
    assert runner.ctx.slipnet.roles.dimension_length is absent("dimension.length")

    class _Group:
        def get_num_of_local_supporting_groups(self):
            return 1

        def _local_support(self, rng):
            return 80.0

    assert single_letter_group_probability(runner.ctx, _Group()) == 0.0


def test_single_letter_group_probability_with_length_node_removed() -> None:
    from server.engine.codelet_dsl.builtins import single_letter_group_probability

    runner = _runner(rc.provider(rc.node_removed("plato-length")), "abc")

    class _Group:
        def get_num_of_local_supporting_groups(self):
            return 2

        def _local_support(self, rng):
            return 50.0

    assert single_letter_group_probability(runner.ctx, _Group()) == 0.0
