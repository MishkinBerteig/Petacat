"""The rule-English recorder and comparer, without Docker.

``metacat/record_rule_english.py`` logs Metacat's ``transcribe-to-english`` output and
``scripts/compare_rule_english.py`` checks Petacat's against it.  These tests cover the
parts that need no container: the problem list, the distinct-rows table (and that the
committed fixture is in its format), the driver text, the two comparison rules and the
clause key.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.lockstep

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "lockstep" / "metacat"))


def _load(path: str):
    spec = importlib.util.spec_from_file_location(Path(path).stem, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


recorder = _load("tests/lockstep/metacat/record_rule_english.py")
compare = _load("scripts/compare_rule_english.py")

FIXTURE = ROOT / "tests" / "seed_unit" / "rule_english_metacat.tsv"
PROBLEMS = ROOT / "tests" / "seed_unit" / "rule_english_problems.txt"


def test_problem_list_parses_and_covers_the_committed_entries():
    entries = recorder.parse_problems(PROBLEMS.read_text())
    assert len(entries) == 23
    assert (["abc", "abd", "xyz"], list(range(11, 31))) in entries
    assert all(len(p) == 3 and seeds for p, seeds in entries)
    assert recorder.parse_problems("# c\n\nab c ab 2,4-5  # tail\n") == [(["ab", "c", "ab"], [2, 4, 5])]


def test_table_rows_are_distinct_sorted_and_drop_plato():
    lines = [
        "RULE\t1\t10\tbottom\tI[plato-a/b/c][x:y:z]\tChange it",
        "RULE\t2\t99\tbottom\tI[plato-a/b/c][x:y:z]\tChange it",
        "RULE\t2\t99\ttop\tV[plato-a]\tline1|||line2",
        "END\t2\t99\tanswer",
    ]
    rows = recorder.table_rows(lines)
    assert rows == [("bottom", "I[a/b/c][x:y:z]", "Change it"), ("top", "V[a]", "line1|||line2")]
    text = recorder.format_table(rows)
    assert text.startswith("#") and text.endswith("line1|||line2\n")


def test_committed_fixture_is_in_the_recorders_table_format():
    text = FIXTURE.read_text()
    header, body = text[: len(recorder.TABLE_HEADER)], text[len(recorder.TABLE_HEADER):]
    assert header == recorder.TABLE_HEADER
    rows = [tuple(l.split("\t")) for l in body.splitlines()]
    assert len(rows) == 463 and rows == sorted(rows)
    assert all(len(r) == 3 and "plato-" not in r[1] for r in rows)


def test_driver_names_the_problem_seeds_and_cap_and_nothing_stray():
    drv = recorder.driver_text(["abc", "abd", "xyz"], [3, 5], 777)
    assert "(init-mcat 'abc 'abd 'xyz #f run-seed)" in drv
    assert "(set! *break-time* 777)" in drv
    assert drv.rstrip().endswith("(one-run 3)\n(one-run 5)\n(exit 0)")
    assert "CAP" not in drv and "'I 'M 'T" not in drv


def test_exact_comparison_pairs_by_codelet_type_and_structure():
    m = [(5, "top", "k1", "A"), (9, "top", "k2", "B"), (12, "bottom", "k3", "C")]
    p = [(5, "top", "k1", "A"), (9, "top", "k2", "X"), (40, "top", "k9", "Z")]
    total, matched, mism, unpaired, extra = compare.compare_exact(m, p)
    assert (total, matched, unpaired, extra) == (3, 1, 1, 1)
    assert mism == [((9, "top", "k2", "B"), ["X"])]
    assert compare.compare_exact(m, m)[:2] == (3, 3)


def test_set_comparison_ignores_codelets_and_flags_text_differences():
    m = [(1, "t", "k", "A"), (2, "t", "k", "B"), (3, "t", "only-m", "Q")]
    p = [(9, "t", "k", "B"), (8, "t", "k", "A"), (7, "t", "only-p", "R")]
    assert compare.compare_sets(m, p) == (1, [], 1)
    both, bad, _ = compare.compare_sets(m, [(1, "t", "k", "A")])
    assert both == 1 and bad == [(("t", "k"), {"A", "B"}, {"A"})]


def test_parse_rules_groups_by_seed_and_keeps_empty_runs():
    runs = compare.parse_rules(["RULE\t3\t7\ttop\tk\tt", "END\t3\t9\tanswer", "END\t4\t2\tcapped"])
    assert dict(runs) == {3: [(7, "top", "k", "t")], 4: []}


def test_clause_key_writes_each_clause_kind_as_the_recorder_does():
    node = lambda n: SimpleNamespace(name=n)  # noqa: E731
    od = (node("plato-group"), node("plato-letter-category"), node("plato-a"))
    verbatim = SimpleNamespace(is_verbatim=True, is_extrinsic=False, verbatim_letters=["c", "d"])
    extrinsic = SimpleNamespace(is_verbatim=False, is_extrinsic=True, object_descriptions=[od],
                                dimensions=[node("plato-length")])
    change = SimpleNamespace(referent="self", dimension=node("plato-length"),
                             relation=node("plato-successor"), to_descriptor=None)
    intrinsic = SimpleNamespace(is_verbatim=False, is_extrinsic=False, object_descriptions=[od],
                                changes=[change])
    assert compare.clause_key(verbatim) == "V[c,d]"
    assert compare.clause_key(extrinsic) == (
        "X[plato-group/plato-letter-category/plato-a][plato-length]")
    assert compare.clause_key(intrinsic) == (
        "I[plato-group/plato-letter-category/plato-a][self:plato-length:plato-successor]")
