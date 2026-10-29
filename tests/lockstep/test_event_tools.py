"""The trace-event recorder and comparer, without Docker.

``metacat/record_events.py`` logs the print-name and header of every Temporal Trace event
Metacat makes, ``scripts/compare_events.py`` checks Petacat's replay of the same run
against it.  These tests cover the run list, the parsing and type mapping, truncation to
the codelet Petacat reached, the comparison, the greedy cover that chose the fixture's runs
and the fixture's table format.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.lockstep

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "lockstep" / "metacat"))


def _load(path: str):
    spec = importlib.util.spec_from_file_location(Path(path).stem, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


recorder = _load("tests/lockstep/metacat/record_events.py")
compare = _load("scripts/compare_events.py")

FIXTURE = ROOT / "tests" / "lockstep" / "event_names_metacat.tsv"
RUNS = ROOT / "tests" / "lockstep" / "event_names_runs.txt"


def test_run_list_matches_the_fixtures_runs():
    runs = compare.parse_runs_file(RUNS.read_text())
    assert len(runs) == 8 and ("justify", "abc-abd-xyz-wyz", 1) in runs
    in_fixture = {tuple(l.split("\t")[:3]) for l in FIXTURE.read_text().splitlines() if l[0] != "#"}
    assert {(k, s, str(n)) for k, s, n in runs} == in_fixture
    with pytest.raises(ValueError):
        compare.parse_runs_file("sideways abc-abd-xyz 1")


def test_parse_events_maps_metacat_types_to_petacat_types():
    runs = compare.parse_events([
        "EV\t2\t1\tconcept-activation\t17\t0.5\t(Identity)\tActivation of Identity concept",
        "EV\t2\t2\tgroup\t40\t0.5\t>a-b-c>\tBuilt successor-group",
        "END\t2\t45\tanswer",
        "END\t3\t5\tcapped",
    ])
    assert runs[2] == [(1, "concept_activation", 17, "(Identity)", "Activation of Identity concept"),
                       (2, "group_built", 40, ">a-b-c>", "Built successor-group")]
    assert runs[3] == []


def test_truncate_and_first_difference():
    ev = [(1, "snag", 10, "[Snag]", "Snag"), (2, "snag", 30, "[Snag]", "Snag")]
    assert compare.truncate(ev, 10) == ev[:1]
    a = compare.comparable(ev)
    assert compare.first_difference(a, a) is None
    assert compare.first_difference(a, a[:1]) == 1
    assert compare.first_difference(a, [a[0], ("snag", 30, "[Snag]", "Snagged")]) == 1


def test_cover_picks_the_smallest_run_with_each_feature_per_limit():
    big = [(1, "group_built", 5, ">a-b-c>", "Built successor-group"),
           (2, "snag", 9, "[Snag]", "Snag")]
    small = [(1, "group_built", 5, ">a-b-c>", "Built successor-group")]
    other = [(1, "answer_found", 8, "[Answer xyz]", "Found new answer")]
    cands = [(("main", "p", 1), 100, big), (("main", "p", 2), 20, small), (("main", "p", 3), 3000, other)]
    keys = [k for k, _lim, _ev in compare.pick_cover(cands, [200])]
    assert keys == [("main", "p", 1)]
    keys = [k for k, _lim, _ev in compare.pick_cover(cands, [200, 5000])]
    assert keys == [("main", "p", 1), ("main", "p", 3)]
    assert compare.pick_cover(cands, [1]) == []


def test_table_format_matches_the_committed_fixture():
    text = FIXTURE.read_text()
    assert text.startswith(compare.TABLE_HEADER)
    rows = []
    for line in text[len(compare.TABLE_HEADER):].splitlines():
        kind, slug, seed, n, etype, codelet, name, header = line.split("\t")
        rows.append((kind, slug, int(seed), int(n), etype, int(codelet), name, header))
    assert len(rows) == 131
    regrouped = {}
    for kind, slug, seed, n, etype, codelet, name, header in rows:
        regrouped.setdefault((kind, slug, seed), []).append((n, etype, codelet, name, header))
    rebuilt = compare.format_table([(k[0], k[1], k[2], ev) for k, ev in regrouped.items()])
    assert rebuilt == text


def test_driver_runs_justify_mode_only_with_an_answer():
    plain = recorder.driver_text(["abc", "abd", "xyz"], [1, 2], None, 100000)
    justify = recorder.driver_text(["abc", "abd", "mrrjjj"], [4], "mrrkkk", 100000)
    assert "(init-mcat 'abc 'abd 'xyz #f run-seed)" in plain and "%justify-mode%" not in plain
    assert "(set! %justify-mode% #t)" in justify and "'mrrkkk run-seed" in justify
    assert "(tell *memory* 'clear)" in plain
