"""The parsing and comparison logic of the snag and answer-check tools, without Docker.

Covers ``tests/lockstep/metacat/record_snags.py`` and ``record_answers.py`` (driver text),
``scripts/compare_snags.py``, ``scripts/compare_episode_answers.py``, ``scripts/sweep_snags.py``,
``scripts/sweep_fidelity.py`` and the problem lists in ``tests/lockstep/data/``.  What needs
Metacat (the recordings themselves) is run by those tools; see ``tests/lockstep/README.md``,
"Snag explanations, snag sweep and fidelity net".
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests" / "lockstep" / "metacat"))
import compare_episode_answers as cea  # noqa: E402
import compare_snags as cs  # noqa: E402
import record_answers  # noqa: E402
import record_snags  # noqa: E402
import sweep_fidelity as sf  # noqa: E402
import wrap  # noqa: E402

pytestmark = pytest.mark.lockstep

DATA = REPO / "tests" / "lockstep" / "data"

METACAT_SNAGS = [
    "SNAG\t3\t825\tCONFLICT\tchanging a conflicts with b in xyz",
    "CMT\t3\t825\tUh-oh.  Changing a.\tHit a snag:  Changing a.",
    "SNAG\t3\t1095\tCHANGE\tchanging c to its successor is not possible in xyz",
    "CMT\t3\t1095\tUh-oh again.  Changing c.\tHit another snag:  Changing c.",
    "END\t3\t2085\tsuspended",
    "END\t4\t99\txyz",
]


# --- wrap.py ------------------------------------------------------------------


def test_parse_seeds_takes_lists_and_ranges_in_order_without_duplicates():
    assert wrap.parse_seeds("1-3,9,2,20-21") == [1, 2, 3, 9, 20, 21]
    assert wrap.parse_seeds("7") == [7]


def test_slug_problem_drops_a_justify_answer():
    assert wrap.slug_problem("abc-abd-xyz") == ["abc", "abd", "xyz"]
    assert wrap.slug_problem("abc-abd-xyz-wyz") == ["abc", "abd", "xyz"]


def test_a_problem_list_skips_comments_and_duplicates(tmp_path):
    f = tmp_path / "p.txt"
    f.write_text("# header\nabc abd xyz  # trailing\n\nabc abd xyz\nab ba cd\n")
    assert wrap.read_problem_list(f) == [["abc", "abd", "xyz"], ["ab", "ba", "cd"]]


def test_a_problem_list_line_with_the_wrong_number_of_strings_is_an_error(tmp_path):
    f = tmp_path / "p.txt"
    f.write_text("abc abd\n")
    with pytest.raises(ValueError):
        wrap.read_problem_list(f)


# --- the Scheme drivers ---------------------------------------------------------


def test_the_snag_driver_names_the_problem_the_cap_and_one_run_per_seed():
    text = record_snags.driver(["abc", "zyx", "xyz"], [9, 10], 6000)
    assert "(init-mcat 'abc 'zyx 'xyz #f run-seed)" in text
    assert "(set! *break-time* 6000)" in text
    assert text.count("(one-run ") == 2 + 1  # two calls and the definition
    assert "(one-run 9)\n(one-run 10)\n(exit 0)" in text
    assert "CAP" not in text.replace("*CAP*", "")


def test_the_snag_driver_clears_memory_in_every_run_but_the_answer_driver_once_before_them():
    clear = "(tell *memory* 'clear)"
    snags = record_snags.driver(["abc", "abd", "xyz"], [1, 2], 100)
    answers = record_answers.driver(["abc", "abd", "xyz"], [1, 2], 100)
    assert snags.count(clear) == answers.count(clear) == 1
    assert snags.index(clear) < snags.index("(call/cc")        # inside one-run
    assert answers.index(clear) > answers.index("(call/cc")    # after its definition, before the runs
    assert answers.index(clear) < answers.index("(one-run 1)\n")
    assert answers.rstrip().endswith("(dump)\n(exit 0)")


# --- compare_snags --------------------------------------------------------------


def test_parse_metacat_groups_lines_by_seed():
    runs = cs.parse_metacat(METACAT_SNAGS)
    assert list(runs) == ["3", "4"]
    assert runs["3"]["snags"] == [(825, "CONFLICT", "changing a conflicts with b in xyz"),
                                  (1095, "CHANGE", "changing c to its successor is not possible in xyz")]
    assert runs["3"]["comments"][1] == (1095, "Uh-oh again.  Changing c.", "Hit another snag:  Changing c.")
    assert runs["3"]["end"] == (2085, "suspended")
    assert runs["4"]["snags"] == []


def test_fixture_rows_pair_each_snag_with_the_comment_of_its_codelet():
    rows = cs.fixture_rows("abc-zyx-xyz", cs.parse_metacat(METACAT_SNAGS))
    assert rows[0] == ("abc-zyx-xyz", "3", "825", "CONFLICT", "changing a conflicts with b in xyz",
                       "Uh-oh.  Changing a.", "Hit a snag:  Changing a.")
    assert [r[2] for r in rows] == ["825", "1095"]


def test_a_fixture_written_reads_back_identically(tmp_path):
    rows = cs.fixture_rows("abc-zyx-xyz", cs.parse_metacat(METACAT_SNAGS))
    path = tmp_path / "f.tsv"
    cs.write_fixture(path, rows)
    assert cs.read_fixture(path) == rows
    assert path.read_text().startswith("# Metacat 1.2's snags, recorded")


def test_the_committed_fixture_parses_and_its_header_names_the_command():
    rows = cs.read_fixture()
    assert rows and all(len(r) == 7 for r in rows)
    header = [l for l in cs.FIXTURE.read_text(encoding="utf-8").splitlines() if l.startswith("#")]
    assert any("compare_snags.py --regenerate-fixture" in l for l in header)
    assert any("record_snags.py" in l for l in header)
    assert cs.FIXTURE.read_text(encoding="utf-8").startswith(cs.FIXTURE_HEADER)


def test_compare_run_counts_matches_and_names_the_first_difference():
    expected = cs.parse_metacat(METACAT_SNAGS)["3"]
    same = cs.compare_run(expected, expected["snags"], expected["comments"])
    assert same["identical"] and same["snags_matched"] == 2 and same["comments_matched"] == 2
    wrong = [expected["snags"][0], (1095, "CHANGE", "something else")]
    r = cs.compare_run(expected, wrong, expected["comments"])
    assert not r["identical"] and r["first"] == 1 and r["snags_matched"] == 1
    assert r["want_snag"][2].startswith("changing c") and r["got_snag"][2] == "something else"


def test_a_missing_snag_is_a_difference():
    expected = cs.parse_metacat(METACAT_SNAGS)["3"]
    r = cs.compare_run(expected, expected["snags"][:1], expected["comments"])
    assert not r["identical"] and r["first"] == 1 and r["got_snag"] is None


def test_a_desynced_replay_is_compared_only_before_its_stop():
    expected = cs.parse_metacat(METACAT_SNAGS)["3"]
    r = cs.compare_run(expected, expected["snags"][:1], expected["comments"][:1], stop=1000)
    assert r["identical"] and r["desynced"] and r["snags"] == 1


# --- compare_episode_answers ----------------------------------------------------

EPISODE = [
    "END\t1\t100\tsuspended",
    "ANS\tabd|Change string\t",
    "ANS\twyz|Change z\tcannot change z",
    "EXPL\tabd|Change string\tEliza one\tTech one",
    "EXPL\twyz|Change z\tEliza two\tTech two",
    "CMP\tabd|Change string\twyz|Change z\tThey differ",
    "CMP\twyz|Change z\tabd|Change string\tThey differ the other way",
]


def _swap_first_two(lines, kind):
    idx = [i for i, l in enumerate(lines) if l.startswith(kind + "\t")]
    out = list(lines)
    out[idx[0]], out[idx[1]] = out[idx[1]], out[idx[0]]
    return out


def test_parse_lines_keeps_each_kind_in_the_order_given():
    p = cea.parse_lines(EPISODE)
    assert p["ANS"] == [("abd|Change string", ""), ("wyz|Change z", "cannot change z")]
    assert p["CMP"][1][:2] == ("wyz|Change z", "abd|Change string")
    assert p["END"] == [("1", "100", "suspended")]


def test_identical_episodes_match_in_every_kind():
    r = cea.compare_answers(cea.parse_lines(EPISODE), cea.parse_lines(EPISODE))
    assert r["ok"] and r["matched"] == r["total"] == {"ANS": 2, "EXPL": 2, "CMP": 2}


def test_a_different_text_is_reported_with_both_sides():
    other = [l.replace("Eliza two", "Eliza 2") for l in EPISODE]
    r = cea.compare_answers(cea.parse_lines(EPISODE), cea.parse_lines(other))
    assert not r["ok"] and r["matched"]["EXPL"] == 1
    assert any("Eliza two" in p and "Eliza 2" in p for p in r["problems"])


def test_answer_order_matters_by_default():
    swapped = _swap_first_two(EPISODE, "ANS")
    r = cea.compare_answers(cea.parse_lines(EPISODE), cea.parse_lines(swapped))
    assert not r["ok"] and r["order"]["ANS"] is False
    assert r["matched"]["ANS"] == 2  # every text still matches by key
    assert any(p.startswith("ORDER ANS") for p in r["problems"])


def test_ignore_order_accepts_the_same_answers_in_another_order():
    swapped = _swap_first_two(_swap_first_two(EPISODE, "ANS"), "CMP")
    r = cea.compare_answers(cea.parse_lines(EPISODE), cea.parse_lines(swapped), ignore_order=True)
    assert r["ok"] and r["order"]["ANS"] is False and r["order"]["CMP"] is False


def test_an_answer_only_one_side_has_is_a_problem_even_when_order_is_ignored():
    fewer = [l for l in EPISODE if "wyz" not in l]
    r = cea.compare_answers(cea.parse_lines(EPISODE), cea.parse_lines(fewer), ignore_order=True)
    assert not r["ok"] and r["matched"]["ANS"] == 1
    r2 = cea.compare_answers(cea.parse_lines(fewer), cea.parse_lines(EPISODE), ignore_order=True)
    assert any("only in Petacat" in p for p in r2["problems"])


def test_the_same_comparison_text_twice_must_be_there_twice():
    doubled = EPISODE + [EPISODE[5]]
    r = cea.compare_answers(cea.parse_lines(doubled), cea.parse_lines(EPISODE), ignore_order=True)
    assert not r["ok"] and r["matched"]["CMP"] == 2 and r["total"]["CMP"] == 3


# --- sweep_fidelity ---------------------------------------------------------------

TABLE = """problem                              seed    reach   length   agree  errors  snaps  first fatal
abc-abd-ijkk                            1     1500     1500  1.0000       0      0  -
abc-abd-ijkk                            2      900     1200  0.9990       0      0  rule-builder
abc-abd-ijkk                            3     1000     1000  1.0000       0      4  -
abc-abd-ijkk                            4     1000     1000  1.0000       1      0  -
snaps: update-cycle snapshots that differ outside x, y
"""


def test_parse_table_reads_one_row_per_trace_and_skips_the_header_and_footer():
    rows = sf.parse_table(TABLE)
    assert [r["seed"] for r in rows] == ["1", "2", "3", "4"]
    assert rows[1]["reach"] == 900 and rows[1]["length"] == 1200 and rows[1]["fatal"] == "rule-builder"


def test_short_rows_flags_short_reach_errors_and_differing_snapshots():
    assert [r["seed"] for r in sf.short_rows(sf.parse_table(TABLE))] == ["2", "3", "4"]


def test_parse_record_log_reads_the_outcome_of_each_seed():
    log = "seed 2: ijll 1234 codelets, 3.0s, 9.9 MB raw, 0.22 MB gz\nseed 1: *NONE* 4000 codelets, 5s\nnoise\n"
    parsed = sf.parse_record_log(log)
    assert parsed == {2: ("ijll", 1234), 1: ("*NONE*", 4000)}
    assert sf.outcome_tally(parsed) == {"ijll": 1, "*NONE*": 1}


# --- the committed problem lists ----------------------------------------------------


def test_the_fidelity_lists_hold_84_problems_and_660_single_runs_plus_24_episodes():
    widen = wrap.read_problem_list(DATA / "fidelity_widen.txt")
    widen2 = wrap.read_problem_list(DATA / "fidelity_widen2.txt")
    episodes = wrap.read_problem_list(DATA / "fidelity_episodes.txt")
    assert (len(widen), len(widen2), len(episodes)) == (48, 36, 8)
    assert not [p for p in widen if p in widen2]
    seeds = lambda net: len(wrap.parse_seeds(sf.NETS[net][1]))  # noqa: E731
    assert len(widen) * seeds("widen") + len(widen2) * seeds("widen2") == 480 + 180
    assert len(episodes) * seeds("episodes") == 24 and sf.NETS["episodes"][3] == 8
    assert {sf.NETS[n][2] for n in ("widen", "widen2")} == {4000} and sf.NETS["episodes"][2] == 5000


def test_the_snag_sweep_list_contains_the_28_problems_that_had_snags():
    everything = wrap.read_problem_list(DATA / "snag_sweep_problems.txt")
    with_snags = wrap.read_problem_list(DATA / "snag_sweep_with_snags.txt")
    assert len(with_snags) == 28 and len(everything) == 87
    assert all(p in everything for p in with_snags)
    assert all(len(p) == 3 and all(s.isalpha() and s.islower() for s in p) for p in everything)


def test_the_sweeps_default_to_the_gitignored_output_directory():
    assert wrap.DEFAULT_OUT == REPO / "tests" / "lockstep" / "out"
    ignore = (REPO / ".gitignore").read_text()
    assert "tests/lockstep/out/" in ignore
