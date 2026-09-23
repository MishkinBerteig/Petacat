import importlib.util
from pathlib import Path
import unittest


ACADEMIC = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("misc3_audit", ACADEMIC / "tools/investigate_misc3.py")
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


class Misc3InvestigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = AUDIT.audit(ACADEMIC.parent / "studies/episodic-v3/results/main")

    def test_frozen_prefixes_remain_separate(self):
        frozen = self.report["frozen"]
        self.assertEqual(frozen["best_a"]["N"], 11)
        self.assertEqual(frozen["best_b"]["N"], 7)
        self.assertEqual(sum(frozen["best_b"]["answer_counts"].values()), 7)

    def test_selected_answers_are_not_cowinner_populations(self):
        validation = self.report["phases"]["validation"]["definitions"]
        self.assertEqual(validation["best_a"]["outside_occurrences"], 0)
        self.assertEqual(validation["best_b"]["outside_occurrences"], 99)
        self.assertEqual(validation["best_b"]["episodes_with_outside_cowinners"], 383)

    def test_diagnostic_groups_are_exhaustive_but_not_causal(self):
        summary = self.report["outside_best_a_summary"]
        self.assertEqual(summary["diagnostic_partitions_not_root_causes"], {
            "single-outside-winning-string": 21,
            "outside-only-quality-tie": 1,
            "inside-outside-quality-tie": 2,
        })
        ties = [e["episode_number"] for e in self.report["outside_best_a_events"]
                if e["inside_quality_cowinner_strings"]]
        self.assertEqual(ties, [74, 84])

    def test_capped_and_answerless_runs_are_not_dropped(self):
        summary = self.report["outside_best_a_summary"]
        self.assertEqual(summary["all_eight_runs_answered"], 9)
        self.assertEqual(summary["with_caps"], 15)
        self.assertEqual(summary["with_answerless_inner_runs"], 1)
        totals = self.report["phases"]["port"]["totals"]
        self.assertEqual((totals["answer_runs"], totals["capped_runs"], totals["answerless_runs"]),
                         (731, 66, 3))

    def test_score_summary_has_one_observation_per_episode(self):
        validation = self.report["phases"]["validation"]["best_a_quality"]
        port = self.report["phases"]["port"]["best_a_quality"]
        self.assertEqual((validation["median"], port["median"]), (94, 86))
        self.assertEqual((validation["above_90"], port["above_90"]), (988, 0))

    def test_full_answer_table_reconciles_all_four_populations(self):
        table = self.report["answer_table"]
        self.assertEqual(len(table), 27)
        for column, total in (("validation_best_a", 1000), ("validation_best_b", 1000),
                              ("port_best_a", 100), ("port_best_b", 100)):
            self.assertEqual(sum(r[column] for r in table), total)


if __name__ == "__main__":
    unittest.main()
