"""The staleness probe reads a Workspace that lags the live one (WP0.5).

These tests cover the instrument, not the finding.  What delay cognition tolerates
is measured by ``scripts/measure_staleness.py`` against the expected-range oracle;
what is asserted here is that the instrument does what it claims — that a codelet
really does see the Workspace of N codelets ago, and that with the delay switched
off nothing changes at all.

The second half matters as much as the first.  A staleness probe that silently ran
live would report "cognition tolerates any delay", which is the most misleading
answer it could give.
"""

from __future__ import annotations

import os

import pytest

from server.engine.metadata import MetadataProvider
from server.engine.runner import EngineRunner
from server.engine.staleness import StaleView, current_view

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


def _runner(meta: MetadataProvider, delay: int = 0) -> EngineRunner:
    runner = EngineRunner(meta)
    runner.init_mcat("abc", "abd", "mrrjjj", seed=42)
    if delay:
        runner.ctx.set_staleness_delay(delay)
    return runner


# --- switched off ----------------------------------------------------------


def test_no_view_is_captured_when_staleness_is_off(meta):
    runner = _runner(meta)
    runner.run_mcat(max_steps=60)
    assert runner.ctx.staleness_delay == 0
    assert not runner.ctx.view_history
    assert current_view(runner.ctx) is None


def test_zero_delay_reproduces_the_live_run_exactly(meta):
    """Switching the mechanism off must be indistinguishable from not having it.

    Compared on the full run outcome rather than on a flag, because the flag being
    0 is precisely what a broken guard would still report.
    """
    plain = _runner(meta)
    plain_result = plain.run_mcat(max_steps=400)

    explicit = _runner(meta)
    explicit.ctx.set_staleness_delay(0)
    explicit_result = explicit.run_mcat(max_steps=400)

    assert plain_result.status == explicit_result.status
    assert plain_result.answers == explicit_result.answers
    assert plain_result.codelet_count == explicit_result.codelet_count
    assert [e.event_number for e in plain.ctx.trace.events] == [
        e.event_number for e in explicit.ctx.trace.events
    ]


# --- switched on -----------------------------------------------------------


def test_history_depth_matches_the_configured_delay(meta):
    runner = _runner(meta, delay=5)
    runner.run_mcat(max_steps=60)
    assert runner.ctx.view_history.maxlen == 5
    assert len(runner.ctx.view_history) == 5


def test_the_view_lags_the_live_workspace_by_the_delay(meta):
    """The oldest view is the Workspace as of exactly ``delay`` codelets ago."""
    delay = 5
    runner = _runner(meta, delay=delay)
    runner.run_mcat(max_steps=60)

    view = current_view(runner.ctx)
    assert view is not None
    assert view.codelet_count == runner.ctx.codelet_count - delay


def test_during_warm_up_the_view_is_the_oldest_available(meta):
    """Before the history fills, the lag is however much history exists.

    Falling back to live during warm-up would make the first N codelets of every
    run special; falling back to the oldest available view keeps the mechanism
    uniform and simply ramps the lag up to N.
    """
    runner = _runner(meta, delay=20)
    runner.run_mcat(max_steps=5)
    view = current_view(runner.ctx)
    assert view is not None
    assert view.codelet_count == 0


def _built_bond_ids(ctx) -> set[int]:
    return {id(b) for s in ctx.workspace.all_strings for b in s.bonds if b.is_built}


def test_a_view_shows_the_built_set_as_it_was_when_captured(meta):
    """The property the whole probe rests on.

    Built-ness is captured at snapshot time rather than read live, so a view taken
    before a bond was built never shows it — and, symmetrically, a view taken before
    a bond was broken still does.  Both directions are checked, because capturing
    the *list* while reading ``is_built`` live would pass the first and fail the
    second, and that mixture is the plausible way to get this wrong.
    """
    runner = _runner(meta, delay=1)
    runner.run_mcat(max_steps=200)
    ctx = runner.ctx

    captured = StaleView(ctx)
    at_capture = _built_bond_ids(ctx)

    runner.run_mcat(max_steps=200)
    afterwards = _built_bond_ids(ctx)

    visible = {id(b) for s in ctx.workspace.all_strings for b in captured.string_bonds(s)}
    assert visible == at_capture

    built_since = afterwards - at_capture
    broken_since = at_capture - afterwards
    # The run has to have moved, or the test proves nothing.
    assert built_since or broken_since

    assert not (visible & built_since)
    assert broken_since <= visible


def test_a_stale_run_still_completes(meta):
    """Staleness must degrade cognition, not break it.

    Under free-running a codelet that acts on moved premises fizzles, which is an
    outcome the architecture already has.  If a stale run raised instead, the
    delayed-read model would be wrong about how the engine fails.
    """
    for delay in (1, 5, 15, 50):
        runner = _runner(meta, delay=delay)
        result = runner.run_mcat(max_steps=400)
        assert result.codelet_count > 0
        assert result.status in {
            "answer_found", "halted", "gave_up", "running",
        }


# --- the view object -------------------------------------------------------


def test_view_records_object_weights_at_capture_time(meta):
    """Salience is copied, not referenced, so weighting is stale too.

    Object choice is weighted by salience, and salience moves every update cycle.
    A view that held live objects but read their live salience would make
    membership stale and weighting current — a mixture that models nothing.
    """
    runner = _runner(meta, delay=1)
    runner.run_mcat(max_steps=100)
    ctx = runner.ctx

    obj = ctx.workspace.all_objects[0]
    view = StaleView(ctx)
    captured = view.object_weight(obj, "intra")

    obj.salience["intra"] = 99.0
    assert view.object_weight(obj, "intra") == captured
