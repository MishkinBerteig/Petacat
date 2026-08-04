"""Module integration tests for EngineRunner."""

import os
import pytest
from server.engine.metadata import MetadataProvider
from server.engine.runner import EngineRunner, STATUS_HALTED
from server.engine.memory import EpisodicMemory

# Every test here executes arithmetic the numeric substrate owns, so each one runs
# once per backend in the matrix. See tests/conftest.py.
pytestmark = pytest.mark.numeric_matrix


SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")


@pytest.fixture
def meta():
    return MetadataProvider.from_seed_data(SEED_DIR)


@pytest.fixture
def runner(meta):
    return EngineRunner(meta)


def test_init_mcat(runner):
    runner.init_mcat("abc", "abd", "xyz", seed=42)
    assert runner.ctx is not None
    assert runner.ctx.workspace.initial_string.text == "abc"
    assert runner.ctx.workspace.modified_string.text == "abd"
    assert runner.ctx.workspace.target_string.text == "xyz"
    assert runner.ctx.codelet_count == 0
    assert not runner.ctx.justify_mode


def test_init_mcat_justify_mode(runner):
    runner.init_mcat("abc", "abd", "xyz", answer="wyz", seed=42)
    assert runner.ctx.justify_mode


def test_init_posts_codelets(runner):
    runner.init_mcat("abc", "abd", "xyz", seed=42)
    # ``post-initial-codelets`` (run.ss:275-283) runs ``2N`` iterations posting
    # *two* codelets each — 4N, so 36 for the nine objects of abc/abd/xyz.
    # Rebaselined from 18 with CR-4: Petacat ran N iterations, so every run
    # started with half the reference's opening population.
    assert runner.ctx.coderack.total_count == 36


def test_step_mcat(runner):
    runner.init_mcat("abc", "abd", "xyz", seed=42)
    result = runner.step_mcat()
    assert result.codelet_count == 1
    assert result.codelet_type != ""


def test_run_mcat_limited_steps(runner):
    runner.init_mcat("abc", "abd", "xyz", seed=42)
    result = runner.run_mcat(max_steps=100)
    assert result.codelet_count == 100
    assert result.status == STATUS_HALTED


def test_deterministic_replay(meta):
    """Same seed should produce identical codelet sequences."""
    runner1 = EngineRunner(meta)
    runner1.init_mcat("abc", "abd", "xyz", seed=12345)

    runner2 = EngineRunner(meta)
    runner2.init_mcat("abc", "abd", "xyz", seed=12345)

    for _ in range(50):
        r1 = runner1.step_mcat()
        r2 = runner2.step_mcat()
        assert r1.codelet_type == r2.codelet_type
        assert r1.codelet_count == r2.codelet_count


def test_update_cycle_fires(runner):
    """Update should fire every 15 codelets."""
    runner.init_mcat("abc", "abd", "xyz", seed=42)
    for _ in range(15):
        runner.step_mcat()
    # After 15 steps, temperature should have been updated
    assert runner.ctx.temperature.value <= 100


def test_slipnet_clamped_on_init(runner):
    runner.init_mcat("abc", "abd", "xyz", seed=42)
    lc = runner.ctx.slipnet.get_node("plato-letter-category")
    sp = runner.ctx.slipnet.get_node("plato-string-position-category")
    assert lc.frozen
    assert sp.frozen


def test_shared_memory_across_runs(meta):
    """Episodic memory persists across runs."""
    memory = EpisodicMemory()
    runner = EngineRunner(meta)

    runner.init_mcat("abc", "abd", "xyz", seed=42, memory=memory)
    runner.run_mcat(max_steps=10)

    runner.init_mcat("rst", "rsu", "xyz", seed=99, memory=memory)
    assert runner.ctx.memory is memory


# ======================================================================
#  Initial workspace values, initial activations, and posting counts
# ======================================================================


def test_init_runs_the_workspace_values_update(runner):
    """Scheme: ``update-workspace-values`` at ``run.ss:233``, before the first
    codelet.

    Objects used to enter the run at their constructor defaults — importance 0
    and every unhappiness and salience pinned at 100 — until the first update
    cycle 15 codelets later.  Note what the reference does *not* give them here:
    this runs before ``clamp-initial-slipnodes``, so no description type is
    active, no description is relevant, every raw importance is 0, and relative
    importance falls back to the uniform 100/n.
    """
    runner.init_mcat("abc", "abd", "xyz", seed=42)
    objects = runner.ctx.workspace.all_objects

    assert all(o.relative_importance > 0 for o in objects)
    assert len({o.relative_importance for o in objects}) == 1
    # The saliences are computed values now, not the constructor's 100.
    assert all(o.salience["average"] < 100 for o in objects)


def test_init_activates_every_initial_descriptor(runner):
    """``run.ss:227-232`` sets *every* descriptor of every initial description to
    100, which includes ``plato-letter`` via the object-category description."""
    runner.init_mcat("abc", "abd", "xyz", seed=42)
    slipnet = runner.ctx.slipnet
    assert slipnet.get_node("plato-letter").activation == 100
    assert slipnet.get_node("plato-a").activation == 100
    assert slipnet.get_node("plato-leftmost").activation == 100


def test_single_letter_string_activates_object_category(runner):
    """``run.ss:221-226``: a one-letter string can only map onto a longer one by
    treating a letter and a group as the same role, so the reference activates
    the concept before the run starts."""
    runner.init_mcat("abc", "abd", "z", seed=42)
    assert runner.ctx.slipnet.get_node("plato-object-category").activation == 100


def test_multi_letter_problem_leaves_object_category_alone(runner):
    runner.init_mcat("abc", "abd", "xyz", seed=42)
    assert runner.ctx.slipnet.get_node("plato-object-category").activation == 0


def test_thematic_scout_count_follows_the_mapping_deficit(runner):
    """Scheme: ``coderack.ss:547-549`` — ``round(10 · max-inter-string-unhappiness%)``.

    Ten scouts with nothing mapped, none once every mapping is made.  The floored
    intra-string reading gave 1 in the first case and 1 in the second: thematic
    scouts are the vehicle of clamped-theme pressure, and a clamp episode
    typically finds the strings well bonded and the mappings in ruins.
    """
    runner.init_mcat("abc", "abd", "xyz", seed=42)
    ws = runner.ctx.workspace
    ws.update_all_object_values()
    ws.update_average_unhappiness_values()
    assert runner._compute_num_to_post("thematic-bridge-scout") == 10

    for o in ws.all_objects:
        o.inter_string_unhappiness["horizontal"] = 0.0
        o.inter_string_unhappiness["vertical"] = 0.0
    ws.update_average_unhappiness_values()
    assert runner._compute_num_to_post("thematic-bridge-scout") == 0


def test_rule_scout_posting_is_gated_on_rule_possibility(runner):
    """Scheme: ``coderack.ss:488-491`` and ``542`` — half probability and one
    scout while no rule type is possible, full probability and two per possible
    type once one is.  Bonds have nothing to do with it."""
    runner.init_mcat("abc", "abd", "xyz", seed=42)
    ws = runner.ctx.workspace

    ws.top_rule_possible = False
    assert runner._compute_posting_probability("rule-scout") == 0.5
    assert runner._compute_num_to_post("rule-scout") == 1

    ws.top_rule_possible = True
    assert runner._compute_posting_probability("rule-scout") == 1.0
    assert runner._compute_num_to_post("rule-scout") == 2


def test_scout_counts_come_from_blurred_absolute_counts(runner):
    """The three scout families draw from ``rough-num-of-objects``, so a fresh
    workspace — nine unrelated, ungrouped, unmapped objects — always lands in
    ``many``."""
    runner.init_mcat("abc", "abd", "xyz", seed=42)
    assert runner._compute_num_to_post("bottom-up-bond-scout") == 6
    assert runner._compute_num_to_post("bottom-up-bridge-scout") == 6
    # No bonds anywhere yet, so group scouts are not posted at all.
    assert runner._compute_num_to_post("group-scout:whole-string") == 0
