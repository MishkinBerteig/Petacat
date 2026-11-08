"""The answer-frequency tools, without Docker: parsing, statistics and the shipped reference.

``tests/lockstep/metacat/record_frequencies.py`` (Metacat side) and
``scripts/compare_frequencies.py`` (Petacat side and statistics) are checked on the parts
that need neither the ``metacat:1.2`` container nor a long run: recording and seed
parsing, the chi-square and total-variation code against hand-computed values, the
reference-count reader on a small archive built here, and one tiny Petacat run.

No test here reads the support-v1a study, or a file derived from it (``measurements/reference/``,
``measurements/vs-metacat-support-v1a-lockstep.json``). That study was recorded on the Metacat build
without the known-failure fixes, so it is kept and used only when the user asks for it:
``compare_frequencies.py support-v1a`` refuses without ``--user-asked-for-support-v1a``, and a test
below shows the refusal without reading the study.
"""

from __future__ import annotations

import io
import json
import math
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests" / "lockstep" / "metacat"))
import compare_frequencies as cf  # noqa: E402
import record_frequencies as rf  # noqa: E402
import wrap  # noqa: E402

pytestmark = pytest.mark.lockstep


def test_seed_parsing_agrees_between_tools():
    for text, want in [("1-3", [1, 2, 3]), ("5", [5]), ("1-2,9,2-3", [1, 2, 9, 3])]:
        assert wrap.parse_seeds(text) == cf.parse_seeds(text) == want


def test_recorder_driver_names_problem_cap_and_seeds():
    text = rf.driver(["wxyz", "vxyz", "abcd"], [101, 102], 4000)
    assert "(init-mcat 'wxyz 'vxyz 'abcd #f run-seed)" in text
    assert "(set! *break-time* 4000)" in text
    assert text.count("(one-run 10") == 2 and text.rstrip().endswith("(exit 0)")


def test_recorder_rows_round_trip_through_the_comparer_reader(tmp_path):
    lines = ["noise", "FREQ\t2\tabce\t900\t31.5\t0\t-1", "FREQ\t1\t*CAP*\t4000\t64\t1\t7", "FREQ\t3\tbad"]
    rows = rf.parse_rows(lines)
    assert sorted(rows) == [1, 2]
    path = tmp_path / "x.tsv"
    path.write_text(rf.render(["abc", "abd", "xyz"], 1, 2, 4000, rows))
    read = cf.read_rows(path)
    assert read[1] == {"answer": "*CAP*", "codelets": 4000, "temperature": 64.0}
    assert read[2]["answer"] == "abce" and read[2]["temperature"] == 31.5
    assert path.read_text().splitlines()[0].startswith("# Metacat 1.2 answers: problem abc abd xyz")


def test_output_path_names_problem_range_and_cap():
    p = rf.output_path(Path("o"), ["a", "b", "c"], 101, 1100, 100000)
    assert p == Path("o/frequencies/a-b-c.101-1100.cap100000.metacat.tsv")


def test_chi2_sf_matches_the_textbook_critical_values():
    assert cf.chi2_sf(3.841458820694124, 1) == pytest.approx(0.05, abs=1e-9)
    assert cf.chi2_sf(5.991464547107979, 2) == pytest.approx(0.05, abs=1e-9)
    assert cf.chi2_sf(18.307038053275146, 10) == pytest.approx(0.05, abs=1e-9)
    assert cf.chi2_sf(0, 3) == 1.0


def test_total_variation_and_frequencies():
    a, b = {"x": 3, "y": 1}, {"x": 1, "z": 3}
    assert cf.total_variation(a, a) == 0
    assert cf.total_variation(a, b) == pytest.approx(0.5 * (0.5 + 0.25 + 0.75))
    assert list(cf.frequencies({"b": 1, "a": 1, "c": 5})) == ["c", "a", "b"]


def test_two_sample_chi2_identical_tables_have_zero_statistic():
    a = {"x": 600, "y": 300, "z": 100}
    stat, df, p = cf.two_sample_chi2(a, dict(a))
    assert stat == 0 and df == 2 and p == pytest.approx(1.0)


def test_two_sample_chi2_hand_computed_two_by_two():
    # 2x2 table [[30, 70], [50, 50]]: chi-square 8.333..., one degree of freedom.
    stat, df, p = cf.two_sample_chi2({"x": 30, "y": 70}, {"x": 50, "y": 50})
    assert stat == pytest.approx(8.3333333, rel=1e-6) and df == 1
    assert p == pytest.approx(0.003892, abs=1e-5)


def test_two_sample_chi2_pools_rare_answers():
    a = {"x": 500, "y": 495, "r1": 3, "r2": 2}
    b = {"x": 480, "y": 515, "r1": 2, "r3": 3}
    _, df, _ = cf.two_sample_chi2(a, b)
    assert df == 2          # x, y and the pooled rare bin
    assert cf.two_sample_chi2({"x": 10}, {"x": 10})[2] is None   # one bin: no test


def test_proportion_z_sign_and_degenerate_case():
    assert cf.proportion_z(60, 100, 40, 100) > 0
    assert cf.proportion_z(0, 100, 0, 100) == 0.0
    assert cf.proportion_z(60, 100, 40, 100) == pytest.approx(2.8284271, rel=1e-6)


def test_compare_samples_reports_common_answers_only():
    res = cf.compare_samples({"a": 90, "b": 9, "c": 1}, {"a": 80, "b": 10, "d": 10})
    assert set(res["z"]) == {"a", "b", "d"}      # c is under 5% on both sides
    assert res["n"] == [100, 100] and 0 < res["tv"] < 1


def test_compare_to_reference_reproduces_the_committed_pooled_chi_square():
    # copy1, 200 Petacat runs: fixed numbers written here, checked against the statistics code
    ref = {"c": 17269, "ab": 2731}
    got = cf.compare_to_reference(ref, ["c"] * 173 + ["ab"] * 27)
    assert got["tv"] == pytest.approx(0.00155, abs=1e-9)
    assert got["chi2_pooled"] == pytest.approx(0.004075346066747231, rel=1e-9)
    assert got["chi2_pooled_p"] == pytest.approx(0.9490988721869995, rel=1e-9)
    assert got["novel_answers"] == {}


def test_compare_to_reference_flags_novel_answers():
    got = cf.compare_to_reference({"c": 99, "ab": 1}, ["c"] * 9 + ["zz"])
    assert got["novel_answers"] == {"zz": 1}


def test_table_lists_the_most_common_answers_first():
    text = cf.table("M", {"a": 8, "b": 2}, "P", {"a": 5, "b": 5, "c": 0}, top=2)
    rows = text.splitlines()
    assert rows[1].startswith("a") and rows[2].startswith("b") and len(rows) == 3


def test_problem_strings_reads_the_names_and_strings_of_a_reference_file(tmp_path):
    path = tmp_path / "single-run-sets.json"
    path.write_text(json.dumps({"results": [
        {"name": "run4", "problem": ["run4", "abc", "abd", "xyz"]},
        {"name": "copy1", "problem": ["copy1", "abc", "abc", "xyz"]}]}))
    assert cf.problem_strings(path) == {"run4": ["abc", "abd", "xyz"], "copy1": ["abc", "abc", "xyz"]}


def _small_archive(path):
    """A tiny archive in the layout ``reference_counts`` reads: an admitted attempt per chunk
    (its ``complete.json``), a second attempt that was not admitted, a capped run and a repeated seed."""
    def add(tar, name, data):
        raw = data.encode()
        info = tarfile.TarInfo(name)
        info.size = len(raw)
        tar.addfile(info, io.BytesIO(raw))

    def row(problem, seed, state, termination="answered"):
        return json.dumps({"problem": problem, "seed": seed, "state": state, "termination": termination})

    with tarfile.open(path, "w:gz") as tar:
        base = "x/chunks/construction/p/000001"
        add(tar, f"{base}/complete.json", json.dumps({"attempt": "attempt-002"}))
        add(tar, f"{base}/attempt-001/runs.jsonl", row("p", 1, "NOT-ADMITTED") + "\n")
        add(tar, f"{base}/attempt-002/runs.jsonl", "\n".join([
            row("p", 1, "c"), row("p", 2, "c"), row("p", 3, "ab"), row("p", 3, "zz"),
            row("p", 4, "ignored", "capped")]) + "\n")
        add(tar, "x/chunks/validation/p/000001/complete.json", json.dumps({"attempt": "attempt-001"}))


def test_reference_counts_reads_the_admitted_attempt_once_per_seed(tmp_path):
    archive = tmp_path / "small.tar.gz"
    _small_archive(archive)
    assert cf.reference_counts(archive) == {"p": {"c": 2, "ab": 1, "*CAP*": 1}}


def test_the_support_v1a_mode_refuses_without_the_flag_and_reads_nothing(monkeypatch, capsys):
    def read(*args, **kwargs):
        raise AssertionError("the study or a derived file was read")

    monkeypatch.setattr(cf.tarfile, "open", read)
    monkeypatch.setattr(cf, "reference_counts", read)
    monkeypatch.setattr(cf, "problem_strings", read)
    monkeypatch.setattr(sys, "argv", ["compare_frequencies.py", "support-v1a", "--runs", "1"])
    with pytest.raises(SystemExit) as stop:
        cf.main()
    assert stop.value.code == 2
    err = capsys.readouterr().err
    assert "--user-asked-for-support-v1a" in err and "without the known-failure fixes" in err
    assert "used only when the user specifically asks" in err


def test_the_flag_has_the_same_name_in_all_three_tools():
    flag = "--user-asked-for-support-v1a"
    for command in (["compare_frequencies.py", "support-v1a", "--help"],
                    ["compare_to_metacat.py", "--help"],
                    ["make_reference_sets.py", "--help"]):
        done = subprocess.run([sys.executable, str(ROOT / "scripts" / command[0]), *command[1:]],
                              capture_output=True, text=True, cwd=ROOT)
        assert done.returncode == 0 and flag in done.stdout, command


def test_one_small_petacat_run_is_classified():
    cf._init()
    seed, answer, codelets, temperature = cf.petacat_run((("abc", "abd", "xyz"), 1, 5000))
    assert seed == 1 and 0 < codelets <= 5000 and math.isfinite(temperature)
    assert answer == "*CAP*" or answer == "*NONE*" or answer.isalpha()
    assert cf.petacat_run((("abc", "abd", "xyz"), 1, 5000)) == (seed, answer, codelets, temperature)
