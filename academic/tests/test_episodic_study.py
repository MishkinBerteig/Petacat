import importlib.util
from pathlib import Path
import unittest


ACADEMIC = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("episodic_audit", ACADEMIC / "tools/audit_episodic_study.py")
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


class EpisodicStudyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = AUDIT.audit()
        cls.by_name = {r["problem"]: r for r in cls.report["results"]}

    def test_all_inputs_and_populations_are_retained(self):
        self.assertEqual(len(self.by_name), 19)
        self.assertTrue(all(set(r["definitions"]) == {"best_a", "best_b"} for r in self.by_name.values()))
        self.assertEqual(len(self.report["capped_frequency_comparisons"]), 10)

    def test_absent_oracle_is_not_zero_outside(self):
        r = self.by_name["misc4"]["definitions"]
        self.assertIsNone(r["best_a"]["outside_occurrences"])
        self.assertEqual(r["best_b"]["outside_occurrences"], 0)
        self.assertFalse(r["best_b"]["coverage_qualified"])

    def test_qualified_populations_include_zero_outside_checks(self):
        qualified = self.report["qualified_populations"]
        self.assertEqual(len(qualified), 8)
        nonzero = [r for r in qualified if r["outside_occurrences"]]
        self.assertEqual(nonzero, [{"problem": "misc3", "definition": "best_a", "port_N": 100,
                                   "outside_occurrences": 24}])

    def test_copy5_answerless_episodes_are_not_winners(self):
        r = self.by_name["copy5"]
        self.assertEqual(r["port"]["answerless_episodes"], 4)
        self.assertEqual([r["definitions"][d]["port_N"] for d in AUDIT.DEFINITIONS], [96, 96])
        self.assertEqual([r["definitions"][d]["outside_occurrences"] for d in AUDIT.DEFINITIONS], [2, 3])

    def test_inner_runs_and_partial_error_are_retained(self):
        totals = self.report["totals"]
        self.assertEqual(sum(t["attempted_runs"] for t in totals.values()), 207791)
        self.assertEqual(sum(t["episodes"] for t in totals.values()), 25974)
        self.assertEqual(totals["construction"]["answered_episodes"], 10073)
        self.assertEqual(totals["construction"]["error_runs"], 1)
        self.assertEqual(totals["port"]["capped_runs"], 1997)
        self.assertEqual(totals["port"]["episodes_with_cap"], 863)
        for t in totals.values():
            self.assertEqual(t["attempted_runs"], sum(t[k] for k in (*AUDIT.RUN_FIELDS[1:], "error_runs")))

    def test_capped_frequencies_use_all_construction_not_frozen_prefix(self):
        r = self.by_name["misc4"]["definitions"]["best_b"]["frequency_comparison"]
        self.assertEqual(r["reference_N"], 2000)
        self.assertEqual(next(x for x in r["frequencies"] if x["answer"] == "b")["reference_count"], 16)
        r = self.by_name["run4"]["definitions"]["best_a"]["frequency_comparison"]
        self.assertEqual(r["reference_N"], 1999)

    def test_tv_uses_all_answers_and_largest_gap_ties_are_stable(self):
        r = AUDIT.frequency_summary({"a": 3, "b": 1}, {"b": 1, "c": 3})
        self.assertEqual(r["empirical_tv"], 0.75)
        self.assertEqual(r["largest_gap"]["answer"], "a")
        self.assertEqual(len(r["frequencies"]), 3)

    def test_changed_population_is_rejected(self):
        saved = {"N": 1, "answer_counts": {"wrong": 1}, "assigned_episodes": 0,
                 "answerless_episodes": 0, "engine_error_episodes": 0}
        with self.assertRaises(AssertionError):
            AUDIT.check_population(saved, [], "best_a")


if __name__ == "__main__":
    unittest.main()
