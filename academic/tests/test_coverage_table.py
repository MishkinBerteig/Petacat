import importlib.util
import json
from copy import deepcopy
from pathlib import Path
import unittest


ACADEMIC = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("converter", ACADEMIC / "tools/convert_manuscript.py")
CONVERTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONVERTER)


class CoverageTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.analysis = json.loads(CONVERTER.COVERAGE.read_text())
        cls.rows = {r[0]: r[1:] for r in CONVERTER.coverage_rows(cls.analysis)}

    def row(self, name):
        return self.rows[CONVERTER.code(name)]

    def test_all_problems_and_outcomes_are_reported(self):
        self.assertEqual(len(self.rows), 19)
        self.assertEqual(sum(r[-1] == "A,B" for r in self.rows.values()), 3)
        self.assertEqual(sum(r[-1] == "not tested" for r in self.rows.values()), 5)
        self.assertEqual(sum(r[-1] == "none" for r in self.rows.values()), 9)

    def test_early_freeze_and_large_validation_miss_counts(self):
        self.assertEqual(self.row("misc5"), ["2", "2", "2", "1,000", "480", "591", "none"])

    def test_skipped_validation_is_not_zero_misses(self):
        self.assertEqual(self.row("misc4"), ["2,000", "--", "1,000", "--", "--", "--", "not tested"])

    def test_individual_population_can_pass_when_its_partner_fails(self):
        self.assertEqual(self.row("misc3")[-3:], ["0", "99", "A"])
        self.assertEqual(self.row("copy4")[-3:], ["2", "0", "B"])

    def test_answerless_episodes_reduce_answered_denominator(self):
        self.assertEqual(self.row("copy5")[-4:], ["995", "36", "29", "none"])

    def test_mismatched_denominators_are_rejected(self):
        data = deepcopy(self.analysis)
        row = next(r for r in data["results"] if r["problem"] == "misc5")
        row["definitions"]["best_b"]["validation"]["N"] = 999
        with self.assertRaisesRegex(ValueError, "denominators differ"):
            CONVERTER.coverage_rows(data)

    def test_misc3_table_keeps_freeze_and_validation_counts_separate(self):
        audit = json.loads(CONVERTER.MISC3_AUDIT.read_text())
        rows = {r[0]: r[1:] for r in CONVERTER.misc3_rows(audit)}
        self.assertEqual(len(rows), 27)
        self.assertEqual(rows[CONVERTER.code("kji")], ["3", "2", "466", "380", "25", "28"])
        self.assertEqual(rows[CONVERTER.code("kkkjjiii")], ["0", "0", "0", "10", "4", "7"])

    def test_single_run_check_table_includes_errors_in_outside_draws(self):
        audit = json.loads(CONVERTER.SUPPORT_AUDIT.read_text())
        rows = {r[0]: r[1:] for r in CONVERTER.single_check_rows(audit)}
        self.assertEqual(rows["Outside draws (including errors)"], ["124", "8"])
        self.assertEqual(rows["Engine-error observations"], ["3", "0"])
        self.assertEqual(rows["100-run checks"], ["5,700", "190"])

    def test_episodic_port_table_reports_all_inputs_and_missing_oracles(self):
        audit = json.loads(CONVERTER.EPISODIC_AUDIT.read_text())
        rows = {r[0]: r[1:] for r in CONVERTER.episodic_port_rows(audit)}
        self.assertEqual(len(rows), 19)
        self.assertEqual(rows[CONVERTER.code("misc4")][-3:], ["--", "0", "not tested"])
        self.assertEqual(rows[CONVERTER.code("misc3")][-3:], ["24", "26", "A"])
        self.assertEqual(rows[CONVERTER.code("copy5")][:2], ["96", "4"])

    def test_capped_frequency_table_reports_both_populations(self):
        audit = json.loads(CONVERTER.EPISODIC_AUDIT.read_text())
        rows = CONVERTER.episodic_frequency_rows(audit)
        self.assertEqual(len(rows), 10)
        self.assertEqual({r[0] for r in rows}, {CONVERTER.code(n) for n in
                         ("misc4", "run1", "run4", "fig5.4-top", "eqe-baaab")})


if __name__ == "__main__":
    unittest.main()
