import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "tools/audit_episodes.py"
SPEC = importlib.util.spec_from_file_location("audit_episodes", SCRIPT)
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


class EpisodeAuditTests(unittest.TestCase):
    def setUp(self):
        self.row = {"problem": "toy", "n": 3, "sequences": [["a", "*CAP*"], ["*NONE*", "*CAP*"], ["b", "c"]],
                    "produced": {"a": 1, "c": 1}, "episodes_never_answering": 1,
                    "reference_p50": ["a"], "missing_p50": [], "reference_f1_over_n": 0.01,
                    "novel": [{"member": "c", "count": 1}]}

    def test_last_answer_is_not_last_run(self):
        self.assertEqual(AUDIT.last_answer(["a", "*CAP*"]), "a")
        self.assertIsNone(AUDIT.last_answer(["*NONE*", "*CAP*"]))

    def test_nonanswer_episodes_and_cap_units_preserved(self):
        result = AUDIT.audit_problem(self.row, 2, 3, {"a", "c"})
        self.assertEqual(result["episodes_never_answering"], 1)
        self.assertEqual(result["endpoint_counts_including_no_answer"]["*NO_ANSWER*"], 1)
        self.assertEqual(result["capped_runs"], 2)
        self.assertEqual(result["episodes_with_cap"], 2)
        self.assertEqual(result["stored_novel_pairs"], 1)
        self.assertEqual(result["stored_novel_outside_single_pairs"], 0)

    def test_incomplete_sequence_rejected(self):
        self.row["sequences"][0].pop()
        with self.assertRaises(ValueError):
            AUDIT.audit_problem(self.row, 2, 3, {"a"})

    def test_inconsistent_produced_counts_rejected(self):
        self.row["produced"]["a"] = 2
        with self.assertRaises(ValueError):
            AUDIT.audit_problem(self.row, 2, 3, {"a"})

    def test_false_membership_annotation_rejected(self):
        self.row["novel"][0]["in_single_run_set"] = True
        with self.assertRaises(ValueError):
            AUDIT.audit_problem(self.row, 2, 3, {"a"})


if __name__ == "__main__":
    unittest.main()
