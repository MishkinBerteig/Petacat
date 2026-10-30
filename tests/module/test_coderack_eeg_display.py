"""What the coderack window and the EEG window need from the engine.

``coderack-graphics.ss`` draws, per codelet type, the count, the selection probability
and which type ran last; ``eeg-graphics.ss`` plots average Workspace activity and
temperature, sampled once per update cycle by ``update-everything`` (``run.ss:320``).
These run the real engine -- serially and free-running -- and check the figures against
the rack they describe.
"""

from __future__ import annotations

import os

import pytest

from server.engine.coderack import coderack_display
from server.parallel.coderack_shards import LockedCoderack
from server.parallel.free_running import run_free
from server.engine.metadata import MetadataProvider
from server.engine.runner import EngineRunner

pytestmark = pytest.mark.numeric_matrix

SEED_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "seed_data",
)
PROBLEM = ("abc", "abd", "xyz")


@pytest.fixture(scope="module")
def meta() -> MetadataProvider:
    return MetadataProvider.from_seed_data(SEED_DIR)


def _runner(meta, seed=42) -> EngineRunner:
    runner = EngineRunner(meta)
    runner.init_mcat(*PROBLEM, seed=seed)
    return runner


def _display(ctx):
    return coderack_display(ctx.coderack, ctx.temperature.value, ctx.last_codelet_type)


def test_no_codelet_has_run_at_the_start(meta):
    d = _display(_runner(meta).ctx)
    assert d["last_codelet_type"] is None


def test_the_last_codelet_type_is_the_one_that_just_ran(meta):
    runner = _runner(meta)
    result = runner.step_mcat()
    assert runner.ctx.last_codelet_type == result.codelet_type
    assert _display(runner.ctx)["last_codelet_type"] == result.codelet_type


def test_probabilities_sum_to_one_and_cover_exactly_the_types_present(meta):
    runner = _runner(meta)
    for _ in range(40):
        runner.step_mcat()
    d = _display(runner.ctx)
    assert sum(d["type_probabilities"].values()) == pytest.approx(1.0)
    assert set(d["type_probabilities"]) == {k for k, v in d["type_counts"].items() if v}
    assert d["total_count"] == sum(d["type_counts"].values())
    # Every codelet type has a slot, present or not.
    assert set(d["type_counts"]) <= set(d["codelet_types"])
    assert len(d["codelet_types"]) == len(meta.codelet_specs)


def test_the_probability_is_the_chance_the_choice_picks_that_type(meta):
    """Same figure the draw uses: bin weight / total, split evenly within a bin."""
    runner = _runner(meta)
    for _ in range(40):
        runner.step_mcat()
    ctx = runner.ctx
    row = ctx.coderack.urgency_table.row(ctx.temperature.value)
    total = sum(len(b.codelets) * row[b.bin_number] for b in ctx.coderack.bins)
    expected: dict[str, float] = {}
    for b in ctx.coderack.bins:
        for c in b.codelets:
            expected[c.codelet_type] = expected.get(c.codelet_type, 0) + row[b.bin_number] / total
    got = _display(ctx)["type_probabilities"]
    assert got == pytest.approx(expected)


def test_a_clamped_type_is_reported_with_its_urgency(meta):
    runner = _runner(meta)
    runner.ctx.coderack.clamp_codelet_type("breaker", 91)
    assert _display(runner.ctx)["clamped_urgencies"] == {"breaker": 91}


def test_the_eeg_is_sampled_once_per_update_cycle(meta):
    runner = _runner(meta)
    cycle = meta.get_param("update_cycle_length", 15)
    for _ in range(cycle * 3 + 2):
        runner.step_mcat()
    samples = runner.ctx.eeg.history()["samples"]
    assert len(samples) == 3
    assert [s["codelet_count"] for s in samples] == [cycle, 2 * cycle, 3 * cycle]
    assert [s["cycle"] for s in samples] == [0, 1, 2]
    for s in samples:
        assert 0 <= s["temperature"] <= 100
        assert 0 <= s["activity"] <= 100
    assert samples[-1]["temperature"] == pytest.approx(runner.ctx.temperature.value)


def test_the_eeg_records_what_the_workspace_reported(meta):
    runner = _runner(meta)
    cycle = meta.get_param("update_cycle_length", 15)
    for _ in range(cycle):
        runner.step_mcat()
    ctx = runner.ctx
    sample = ctx.eeg.history()["samples"][0]
    assert sample["activity"] == ctx.workspace.get_activity(ctx.codelet_count, ctx.meta)


def test_a_free_running_rack_serves_the_same_display(meta):
    runner = _runner(meta)
    result = run_free(runner, workers=4, max_steps=300)
    assert result.codelet_count > 0
    ctx = runner.ctx
    assert isinstance(ctx.coderack, LockedCoderack)
    d = _display(ctx)
    assert d["last_codelet_type"] in meta.codelet_specs
    if d["total_count"]:
        assert sum(d["type_probabilities"].values()) == pytest.approx(1.0)
    assert len(ctx.eeg.history()["samples"]) >= 300 // meta.get_param("update_cycle_length", 15) - 1
