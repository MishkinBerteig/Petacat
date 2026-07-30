"""Commentary is an injected writer, not a fixed log (WP3.10).

``CommentaryLog`` accumulates formatted prose that no part of cognition ever reads
back — the engine only calls ``emit_*`` → ``add_comment``, while ``render``,
``get_paragraphs`` and ``count`` are used solely by the API.  Fast Run's requirement
is that nothing storable is constructed, and a log of paragraphs destined for nobody
is exactly that.

The fix is injection rather than a mode check, because a mode check inside
``server/engine/`` would break the property the three persistence modes rest on: that
every mode runs the *same* code path, so comparing them means something.  These tests
hold both halves — that a discarding writer changes nothing about cognition, and that
it really does discard.
"""

from __future__ import annotations

import os

import pytest

from server.engine.commentary import (
    CommentaryLog,
    CommentaryWriter,
    DiscardingCommentaryLog,
)
from server.engine.metadata import MetadataProvider
from server.engine.runner import EngineRunner

SEED_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "seed_data",
)


@pytest.fixture(scope="module")
def meta() -> MetadataProvider:
    return MetadataProvider.from_seed_data(SEED_DIR)


def _run(meta, commentary=None):
    runner = EngineRunner(meta)
    runner.init_mcat("abc", "abd", "mrrjjj", seed=42, commentary=commentary)
    result = runner.run_mcat(max_steps=600)
    return runner, result


# --- both writers satisfy the protocol -------------------------------------


def test_both_writers_satisfy_the_protocol():
    assert isinstance(CommentaryLog(), CommentaryWriter)
    assert isinstance(DiscardingCommentaryLog(), CommentaryWriter)


def test_discarding_writer_answers_the_api_surface():
    """Fast means *not written down*, not *not observable*.

    ``GET /commentary`` is served in every mode, so the discarding writer has to
    answer ``render`` and ``count`` rather than raise — it answers with nothing.
    """
    writer = DiscardingCommentaryLog()
    writer.add_comment("eliza", "technical", 1, "answer")
    assert writer.render() == ""
    assert writer.render(eliza_mode=True) == ""
    assert writer.get_paragraphs() == []
    assert writer.count == 0
    writer.clear()


def test_discarding_writer_cannot_accumulate():
    """The failure mode this guards against is a collector nobody drains.

    A "buffer now, write later" implementation satisfies "nothing reaches the
    database" while still formatting and holding every paragraph, which is the
    opposite of what Fast Run asks for.  Empty ``__slots__`` leaves nowhere to put it.
    """
    writer = DiscardingCommentaryLog()
    assert DiscardingCommentaryLog.__slots__ == ()
    with pytest.raises(AttributeError):
        writer._paragraphs = []


# --- cognition is unaffected ------------------------------------------------


def test_discarding_commentary_does_not_change_the_run(meta):
    """The whole point: swapping the writer changes what is recorded, nothing else.

    Compared on the actual run — status, answer, codelet count and the full trace
    event sequence — rather than on a flag, because the flag is what a broken
    implementation would still report correctly.
    """
    logged_runner, logged = _run(meta, CommentaryLog())
    discarded_runner, discarded = _run(meta, DiscardingCommentaryLog())

    assert logged.status == discarded.status
    assert logged.answers == discarded.answers
    assert logged.codelet_count == discarded.codelet_count
    assert [e.event_number for e in logged_runner.ctx.trace.events] == [
        e.event_number for e in discarded_runner.ctx.trace.events
    ]
    assert [e.event_type for e in logged_runner.ctx.trace.events] == [
        e.event_type for e in discarded_runner.ctx.trace.events
    ]


def test_the_default_is_still_an_accumulating_log(meta):
    """Injecting nothing must behave exactly as before this package existed."""
    runner, _ = _run(meta)
    assert isinstance(runner.ctx.commentary, CommentaryLog)
    assert runner.ctx.commentary.count > 0
    assert runner.ctx.commentary.render().strip() != ""


def test_a_discarded_run_holds_no_paragraphs(meta):
    """The engine emitted commentary throughout; none of it was kept."""
    logged_runner, _ = _run(meta, CommentaryLog())
    assert logged_runner.ctx.commentary.count > 0, "the run must emit commentary at all"

    discarded_runner, _ = _run(meta, DiscardingCommentaryLog())
    assert discarded_runner.ctx.commentary.count == 0
    assert discarded_runner.ctx.commentary.render() == ""


def test_eliza_mode_re_render_still_works(meta):
    """Both voices are stored per paragraph so the UI can toggle without regenerating.

    Worth pinning here: the injection point is the writer, and a writer that dropped
    one voice would only show up when someone toggled Eliza mode.
    """
    runner, _ = _run(meta, CommentaryLog())
    technical = runner.ctx.commentary.render(eliza_mode=False)
    eliza = runner.ctx.commentary.render(eliza_mode=True)
    assert technical and eliza
    assert technical != eliza
    assert len(runner.ctx.commentary.get_paragraphs()) == runner.ctx.commentary.count
