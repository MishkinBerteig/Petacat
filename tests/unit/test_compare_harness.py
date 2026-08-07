"""The comparison harness's decision logic — what gets flagged, and how.

Pure functions only: no engine, no Slipnet, no runs. ``scripts/compare_to_metacat.py``
is where a divergence from MetaCat becomes a *reported* divergence, and every
defect in it is silent in the worst direction — a broken ``compare`` does not
crash, it stops flagging, and a cycle comes back clean because nothing looked.
That is the regression these pin.

The script is not a package. It is loaded by path here rather than made
importable, because being a script that runs from the command line is part of
what it is.
"""

from __future__ import annotations

import importlib.util
import os
from collections import Counter

import pytest

SCRIPT = os.path.join(
    os.path.dirname(__file__), "..", "..", "scripts", "compare_to_metacat.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("compare_to_metacat", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def harness():
    return _load()


def _ref(members, f1=0.0):
    return {"set": list(members), "f1_over_n": f1}


def _p50(members):
    return {"p50": [{"member": m} for m in members]}


# ── the two flags ──────────────────────────────────────────────────────────

def test_a_state_outside_the_reference_set_is_novel(harness):
    row = harness.compare(
        "copy5", Counter({"cc": 90, "aac": 1}), _ref(["cc", "*NONE*"]), _p50(["cc"]), 91
    )
    assert [e["member"] for e in row["novel"]] == ["aac"]
    assert row["novel"][0]["count"] == 1
    assert row["missing_p50"] == []


def test_a_p50_member_petacat_never_produced_is_missing(harness):
    row = harness.compare(
        "run3", Counter({"xyu": 100}), _ref(["xyu", "wyz"]), _p50(["xyu", "wyz"]), 100
    )
    assert row["missing_p50"] == ["wyz"]
    assert row["novel"] == []


def test_producing_every_reference_member_flags_nothing(harness):
    row = harness.compare(
        "copy2", Counter({"d": 100}), _ref(["d"]), _p50(["d"]), 100
    )
    assert row["novel"] == [] and row["missing_p50"] == []


# ── RC-E: the episodic split ───────────────────────────────────────────────

def test_an_episodic_novel_member_the_reference_reaches_in_single_runs_is_marked(harness):
    """The weaker of the two kinds of novelty, and by far the commoner.

    The convergence sets are deliberately unsaturated, so a convergence answer the
    reference *does* produce in single runs is the expected case rather than a
    finding. Without the split these outnumbered the findings 12 to 6.
    """
    row = harness.compare(
        "misc1",
        Counter({"jjjrrm": 90, "crraaa": 2, "zzzzzz": 1}),
        _ref(["jjjrrm"], f1=0.006),
        _p50(["jjjrrm"]),
        93,
        also_reached={"jjjrrm", "crraaa"},
    )
    by = {e["member"]: e for e in row["novel"]}
    assert by["crraaa"]["in_single_run_set"] is True
    assert by["zzzzzz"]["in_single_run_set"] is False


def test_single_mode_does_not_split_because_that_set_is_its_comparison(harness):
    """``also_reached`` is only meaningful for episodes.

    In single mode the single-run set *is* the set being compared against, so a
    member outside it has nowhere weaker to be filed. Marking one there would say
    a state is both novel and not.
    """
    row = harness.compare(
        "copy5", Counter({"aac": 1}), _ref(["cc"]), _p50(["cc"]), 1
    )
    assert "in_single_run_set" not in row["novel"][0]


def test_the_novel_column_holds_only_members_outside_both_sets(harness, capsys):
    """The split has to reach the report, not just the JSON.

    This is the behaviour RC-E bought: what the column shows is what is worth
    reading. The rest is listed below it, under what it is.
    """
    rows = [
        harness.compare(
            "misc1",
            Counter({"jjjrrm": 90, "crraaa": 2, "zzzzzz": 1}),
            _ref(["jjjrrm"], f1=0.006),
            _p50(["jjjrrm"]),
            93,
            also_reached={"jjjrrm", "crraaa"},
        )
    ]
    harness.report("EPISODES", rows)
    out = capsys.readouterr().out
    column = [ln for ln in out.splitlines() if ln.startswith("misc1")][0]
    assert "zzzzzz" in column
    assert "crraaa" not in column, "a member the reference reaches must leave the column"
    assert "crraaa" in out, "...but it must still be reported, below"
    assert "1 novel members." in out, "and must not be counted as one"


# ── RC-E: recurrence across cycles ─────────────────────────────────────────

def test_a_member_the_previous_cycle_produced_is_marked(harness):
    rows = [{"problem": "copy5", "novel": [{"member": "aac"}, {"member": "cbb"}]}]
    previous = {"single": [{"problem": "copy5", "novel": [{"member": "aac"}]}]}
    harness.mark_recurrences(rows, previous, "single")
    assert rows[0]["novel"][0]["also_last_cycle"] is True
    assert rows[0]["novel"][1]["also_last_cycle"] is False


def test_recurrence_is_read_per_problem_not_across_them(harness):
    """``aac`` on copy5 last cycle says nothing about ``aac`` on copy1."""
    rows = [{"problem": "copy1", "novel": [{"member": "aac"}]}]
    previous = {"single": [{"problem": "copy5", "novel": [{"member": "aac"}]}]}
    harness.mark_recurrences(rows, previous, "single")
    assert rows[0]["novel"][0]["also_last_cycle"] is False


def test_no_previous_cycle_is_not_an_error(harness):
    """A first run, or an unreadable file, leaves the marks off rather than failing."""
    rows = [{"problem": "copy5", "novel": [{"member": "aac"}]}]
    harness.mark_recurrences(rows, None, "single")
    assert "also_last_cycle" not in rows[0]["novel"][0]
    harness.mark_recurrences(rows, {}, "single")
    assert "also_last_cycle" not in rows[0]["novel"][0]


def test_a_problem_absent_from_the_previous_cycle_marks_nothing(harness):
    rows = [{"problem": "misc9", "novel": [{"member": "zzz"}]}]
    harness.mark_recurrences(rows, {"single": []}, "single")
    assert rows[0]["novel"][0]["also_last_cycle"] is False


# ── the convergence answer ─────────────────────────────────────────────────

def test_the_convergence_answer_is_the_last_run_that_answered(harness):
    assert harness.convergence_answer(["a", "b", "c"]) == "c"


def test_answerless_runs_are_skipped_looking_backwards(harness):
    """``*NONE*`` and ``*CAP*`` are not answers, so an episode ending in them
    converges on the last run that produced one."""
    assert harness.convergence_answer(["a", "b", "*CAP*", "*NONE*"]) == "b"


def test_an_episode_that_never_answered_has_no_convergence_answer(harness):
    assert harness.convergence_answer(["*NONE*", "*CAP*"]) is None
    assert harness.convergence_answer([]) is None


# ── RC-B: the cap ──────────────────────────────────────────────────────────

def test_the_working_cap_is_below_the_reference_and_both_are_declared(harness):
    assert harness.MAX_STEPS < harness.REFERENCE_MAX_STEPS
    assert harness.REFERENCE_MAX_STEPS == 100_000, (
        "the reference sampled at 100,000; resolving against any other number "
        "compares a run to a budget MetaCat never gave itself"
    )
