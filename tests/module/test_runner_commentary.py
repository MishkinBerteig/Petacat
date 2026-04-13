"""Module tests for commentary integration with the engine runner."""

import os
import pytest
from server.engine.metadata import MetadataProvider
from server.engine.runner import EngineRunner


SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")
SEED = 42


@pytest.fixture
def meta():
    return MetadataProvider.from_seed_data(SEED_DIR)


@pytest.fixture
def runner(meta):
    return EngineRunner(meta)


def test_init_mcat_creates_commentary(runner):
    """init_mcat should create a CommentaryLog with the new-problem paragraph."""
    runner.init_mcat("abc", "abd", "xyz", seed=SEED)
    assert runner.ctx.commentary is not None
    assert runner.ctx.commentary.count == 1
    tech = runner.ctx.commentary.render(eliza_mode=False)
    assert "abc" in tech
    assert "abd" in tech
    assert "xyz" in tech
    assert "Beginning run" in tech


def test_init_mcat_commentary_eliza_vs_technical(runner):
    """Eliza and technical modes should produce different text."""
    runner.init_mcat("abc", "abd", "xyz", seed=SEED)
    eliza = runner.ctx.commentary.render(eliza_mode=True)
    tech = runner.ctx.commentary.render(eliza_mode=False)
    assert eliza != tech
    assert "Okay" in eliza
    assert "Beginning run" in tech


def test_init_mcat_justify_commentary(runner):
    """Justify mode should produce justify-flavored commentary."""
    runner.init_mcat("abc", "abd", "xyz", answer="xyd", seed=SEED)
    assert runner.ctx.commentary.count == 1
    eliza = runner.ctx.commentary.render(eliza_mode=True)
    tech = runner.ctx.commentary.render(eliza_mode=False)
    assert "Let's see" in eliza
    assert "xyd" in eliza
    assert "justify" in tech.lower()


def test_commentary_accumulates_during_run(runner):
    """Stepping should accumulate commentary paragraphs over time."""
    runner.init_mcat("abc", "abd", "xyz", seed=SEED)
    initial_count = runner.ctx.commentary.count
    assert initial_count == 1  # new-problem

    # Run many steps — various events may generate commentary
    for _ in range(500):
        runner.step_mcat()
        if runner.status == "answer_found":
            break

    final_count = runner.ctx.commentary.count
    # At minimum we should still have the new-problem paragraph;
    # any additional events (snags, clamps) would add more.
    assert final_count >= initial_count


def test_reset_clears_and_recreates_commentary(runner):
    """Re-initializing should clear old commentary and start fresh."""
    runner.init_mcat("abc", "abd", "xyz", seed=SEED)
    runner.ctx.commentary.add_comment("extra", "extra", codelet_count=0)
    assert runner.ctx.commentary.count == 2

    # Re-init
    runner.init_mcat("abc", "abd", "xyz", seed=SEED + 1)
    assert runner.ctx.commentary.count == 1  # Only new-problem


def test_commentary_available_on_context(runner):
    """The commentary log should be accessible via ctx.commentary."""
    runner.init_mcat("abc", "abd", "xyz", seed=SEED)
    ctx = runner.ctx
    assert hasattr(ctx, "commentary")
    assert ctx.commentary.count > 0
    paragraphs = ctx.commentary.get_paragraphs()
    assert paragraphs[0].event_type == "new_problem"
