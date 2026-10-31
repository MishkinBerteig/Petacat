"""What a real run records for redisplay: print names, event pictures, snag and answer
pictures, and that they are kept in the rows.

Metacat's ``display`` methods (``trace.ss:405-1250``, ``memory.ss:268-395``) redraw the
Workspace *as it was* for a Trace event, an answer or a snag.  The Workspace moves on,
so Petacat takes the picture as the thing is recorded; these tests drive real runs and
read what was kept.  No database is needed: ``flush`` only stages rows.
"""

from __future__ import annotations

import json
import os

import pytest

from server.engine.memory import EpisodicMemory
from server.engine.metadata import MetadataProvider
from server.engine.runner import STATUS_RUNNING, EngineRunner
from server.engine.trace import (
    ANSWER_FOUND,
    CONCEPT_ACTIVATION,
    GROUP_BUILT,
    RULE_BUILT,
    SNAG,
)
from server.models.run import AnswerDescriptionRow, SnagDescriptionRow, TraceEventRow
from server.services.sinks import NormalSink

pytestmark = pytest.mark.numeric_matrix

SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")


@pytest.fixture
def meta():
    return MetadataProvider.from_standard_configuration(SEED_DIR)


class _Staging:
    def __init__(self) -> None:
        self.rows: list = []

    def add(self, row) -> None:
        self.rows.append(row)

    def of(self, kind):
        return [r for r in self.rows if isinstance(r, kind)]


def _run(meta, problem, seed, cap=4000, sink=None):
    runner = EngineRunner(meta)
    runner.init_mcat(*problem, seed=seed, memory=EpisodicMemory(), sink=sink)
    runner.status = STATUS_RUNNING
    runner.run_mcat(max_steps=cap)
    return runner


def test_every_event_has_a_print_name_and_a_picture(meta):
    runner = _run(meta, ("abc", "abd", "ijk"), 3)
    events = runner.ctx.trace.events
    assert events
    for event in events:
        assert event.print_name, event
        assert event.picture is not None, event
        assert event.picture["header"]
        # A picture is JSON: it is stored in a column and served by the API as it is.
        json.dumps(event.picture)


def test_the_events_are_named_as_metacat_names_them(meta):
    """Seed 3 of abc -> abd; ijk is recorded in ``tests/lockstep/event_names_metacat.tsv``;
    this is its Metacat output for the run (``trace.ss`` print names and headers)."""
    runner = _run(meta, ("abc", "abd", "ijk"), 3)
    names = [(e.event_type, e.print_name, e.picture["header"]) for e in runner.ctx.trace.events]
    assert names[0] == (CONCEPT_ACTIVATION, "(Identity)", "Activation of Identity concept")
    assert (GROUP_BUILT, ">a-b-c>", "Built successor-group") in names or (
        GROUP_BUILT, ">i-j-k>", "Built successor-group"
    ) in names
    assert names[-1] == (ANSWER_FOUND, "[Answer ijl]", "Found new answer")
    assert (RULE_BUILT, "[Top Rule]", "Built rule") in names


def test_an_event_pictures_the_workspace_as_it_was(meta):
    """The first group event is taken before the run has built anything else, so the
    Workspace it shows has that one group and no answer."""
    runner = _run(meta, ("abc", "abd", "ijk"), 3)
    group_events = [e for e in runner.ctx.trace.events if e.event_type == GROUP_BUILT]
    first = group_events[0].picture
    assert first["workspace"]["answer"] is None
    built = sum(len(v) for v in first["workspace"]["groups"].values())
    last = runner.ctx.trace.events[-1].picture
    assert built < sum(len(v) for v in last["workspace"]["groups"].values()), (
        "the early event shows the late Workspace: the picture was not taken when recorded"
    )
    assert first["faded"] is True
    # It highlights the group it is about, and shows the group's descriptors.
    assert first["highlights"]["groups"] and first["highlights"]["groups"][0]["role"] == "event"
    assert first["slipnet"]["title"] == "Group Descriptors"
    assert first["slipnet"]["entries"]
    # The Coderack is blank, as `blank-window "Coderack"`.
    assert first["coderack"]["blank"] is True


def test_an_answer_event_highlights_the_mappings_and_shows_both_rules(meta):
    # Seed 1: seed 3's answer is supported by no vertical bridge (its rules' reference
    # objects share none), which is a legitimate answer but not what this test draws.
    runner = _run(meta, ("abc", "abd", "ijk"), 1)
    answer = next(e for e in runner.ctx.trace.events if e.event_type == ANSWER_FOUND).picture
    roles = {h["role"] for h in answer["highlights"]["bridges"]}
    assert {"vertical", "top"} <= roles
    assert answer["workspace"]["answer"] == "ijl"
    assert answer["workspace"]["top_rules"] and answer["workspace"]["bottom_rules"]
    # An answer's Slipnet is blank (`trace.ss:394`).
    assert answer["slipnet"]["blank"] is True


def test_a_stored_answer_keeps_its_description_picture(meta):
    runner = _run(meta, ("abc", "abd", "ijk"), 3)
    answer = runner.ctx.memory.answers[0]
    picture = answer.picture
    assert picture is not None
    assert picture["kind"] == "description"
    assert picture["header"] == "Answer Description"
    assert picture["workspace"]["answer"] == "ijl"
    assert picture["temperature"] == answer.temperature
    # A description draws only what supports the answer, not the whole Workspace.
    assert picture["workspace"]["vertical_bridges"]
    assert picture["slipnet"]["blank"] is True


def test_a_stored_snag_keeps_its_description_picture(meta):
    """``abc -> abd; xyz`` snags on the ``z`` (seed 34, as ``test_snag_records.py``)."""
    runner = _run(meta, ("abc", "abd", "xyz"), 34, cap=3000)
    snag_events = [e for e in runner.ctx.trace.events if e.event_type == SNAG]
    assert snag_events, "the run met no snag, so this proves nothing"
    event = snag_events[0]
    assert event.print_name == "[Snag]"
    assert event.picture["header"] == "Snag"
    assert event.picture["question_mark"] is True
    assert event.picture["temperature"] == 100.0
    roles = {o["role"] for o in event.picture["highlights"]["objects"]}
    assert "snag" in roles, "the snag's objects are not highlighted"
    assert {r["role"] for r in event.picture["workspace"]["bottom_rules"]} == {"snag"}

    snag = runner.ctx.memory.snags[0]
    assert snag.picture is not None
    assert snag.picture["header"] == "Snag Description"
    assert snag.picture["question_mark"] is True
    assert snag.picture["temperature"] == 100.0


def test_recording_a_picture_does_not_change_what_the_run_does(meta):
    """The picture only reads.  These are `tests/lockstep/test_seam.py`'s figures for the
    run, taken before pictures existed: codelets run, draws consumed, answer."""
    runner = _run(meta, ("abc", "abd", "ijk"), 3, cap=2000)
    assert runner.ctx.codelet_count == 757
    assert runner.ctx.rng.call_count == 7416
    assert runner.ctx.memory.answers[0].problem[3] == "ijl"


async def test_the_rows_keep_the_names_and_the_pictures(meta):
    sink = NormalSink()
    runner = _run(meta, ("abc", "abd", "xyz"), 34, cap=3000, sink=sink)
    runner.finish()
    session = _Staging()
    await sink.flush(session, 7)

    events = session.of(TraceEventRow)
    assert events
    assert all(r.print_name for r in events)
    assert all(r.picture and r.picture["header"] for r in events)
    assert session.of(SnagDescriptionRow) and all(
        r.picture for r in session.of(SnagDescriptionRow)
    )
    answers = session.of(AnswerDescriptionRow)
    assert all(r.picture for r in answers)
