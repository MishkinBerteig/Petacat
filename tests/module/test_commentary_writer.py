"""Commentary is an injected writer, and every Run gets a real one.

``CommentaryLog`` accumulates formatted prose for the API: the engine calls
``emit_*`` → ``add_comment``, and ``render``, ``get_paragraphs`` and ``count`` serve
``GET /commentary``.

Injection keeps the persistence modes on one code path, which is what makes comparing
them meaningful.  Mode chooses where a Run is recorded, so a Run narrates itself
identically in each.

These tests hold three things: that the injected writer receives the commentary, that
a Run always produces some, and that the service layer hands every mode a real log.
"""

from __future__ import annotations

import os

import pytest

from server.engine.commentary import CommentaryLog, CommentaryWriter
from server.engine.metadata import MetadataProvider
from server.engine.runner import EngineRunner

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


def _run(meta, commentary=None):
    runner = EngineRunner(meta)
    runner.init_mcat("abc", "abd", "mrrjjj", seed=42, commentary=commentary)
    result = runner.run_mcat(max_steps=600)
    return runner, result


# --- the protocol -----------------------------------------------------------

def test_the_accumulating_log_satisfies_the_protocol():
    assert isinstance(CommentaryLog(), CommentaryWriter)


def test_the_writer_answers_the_whole_api_surface():
    """``render``, ``get_paragraphs`` and ``count`` are the API's half of the protocol."""
    writer = CommentaryLog()
    writer.add_comment("eliza", "technical", codelet_count=1, event_type="snag")

    assert writer.count == 1
    assert len(writer.get_paragraphs()) == 1
    assert "eliza" in writer.render(eliza_mode=True)
    assert "technical" in writer.render(eliza_mode=False)

    writer.clear()
    assert writer.count == 0
    assert writer.render() == ""


# --- injection --------------------------------------------------------------

def test_the_injected_writer_receives_the_run_s_commentary(meta):
    """The engine writes to the writer it was given."""
    injected = CommentaryLog()
    runner, _ = _run(meta, injected)

    assert injected.count > 0
    assert runner.ctx.commentary is injected


def test_a_run_with_no_writer_supplied_still_narrates_itself(meta):
    """The default is a real log."""
    runner, _ = _run(meta)

    assert isinstance(runner.ctx.commentary, CommentaryLog)
    assert runner.ctx.commentary.count > 0


def test_the_writer_does_not_change_the_run(meta):
    """Two Runs sharing a problem and seed reach the same result.

    Commentary is output, so the writer is outside the loop this asserts on.
    """
    first_runner, first = _run(meta, CommentaryLog())
    second_runner, second = _run(meta, CommentaryLog())

    assert first.answers == second.answers
    assert first.codelet_count == second.codelet_count
    assert (
        first_runner.ctx.temperature.value == second_runner.ctx.temperature.value
    )


def test_eliza_mode_re_renders_the_same_paragraphs(meta):
    """§4.6: the two voices are isomorphic — one set of paragraphs, two renderings."""
    runner, _ = _run(meta, CommentaryLog())
    log = runner.ctx.commentary

    eliza = log.render(eliza_mode=True)
    technical = log.render(eliza_mode=False)

    assert eliza and technical
    assert len(eliza.split("\n\n")) == len(technical.split("\n\n"))


# --- every persistence mode gets a real writer ------------------------------

def test_every_persistence_mode_is_given_a_real_commentary_log():
    """Mode chooses where a Run is recorded.

    A Fast Run narrates itself exactly as Normal and Audit do; the mode governs the
    database.  Asserted against the source that constructs Runs, which is where a
    Run's writer is chosen.
    """
    import inspect

    from server.services import run_service

    source = inspect.getsource(run_service)

    assert source.count("CommentaryLog()") >= 2, (
        "both Run construction paths should build a real CommentaryLog"
    )


def test_the_engine_exposes_exactly_one_commentary_writer():
    """The engine offers exactly one commentary writer."""
    from server.engine import commentary

    writers = [
        name
        for name in dir(commentary)
        if name.endswith("CommentaryLog") and isinstance(getattr(commentary, name), type)
    ]
    assert writers == ["CommentaryLog"]
