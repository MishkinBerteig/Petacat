import importlib.util
import json
from copy import deepcopy
from pathlib import Path
import unittest


ACADEMIC = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("support_audit", ACADEMIC / "tools/audit_support_study.py")
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


class SupportStudyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = AUDIT.audit()

    def test_phase_totals_do_not_count_inherited_observations_twice(self):
        self.assertEqual(self.report["totals"], {"construction": 380000, "validation": 570000, "port": 19000})

    def test_errors_remain_inside_novelty_and_execution_denominators(self):
        validation = self.report["comparisons"]["validation"]
        self.assertEqual((validation["novel_draws"], validation["engine_error_runs"]), (124, 3))
        self.assertEqual({e["seed"] for e in self.report["errors"]}, {20713988, 20716342, 20226148})

    def test_batch_counts_are_not_input_or_draw_counts(self):
        for phase, expected in (("validation", (5700, 119, 4)), ("port", (190, 6, 31))):
            data = self.report["comparisons"][phase]
            self.assertEqual((data["batches"], data["novel_batches"], data["frequency_rejections_19_input_adjusted"]), expected)
            self.assertEqual(data["missing_batches"], 0)

    def test_held_out_discoveries_do_not_erase_port_flags(self):
        self.assertEqual(len(self.report["port_novelty"]), 5)
        self.assertEqual(sum(r["port_count"] for r in self.report["port_novelty"]), 8)
        self.assertEqual(self.report["flagged_port_draws_also_seen_in_validation"], 6)

    def test_nominal_coverage_is_not_simultaneous_coverage(self):
        self.assertEqual(self.report["nominal_95_qualified_inputs"], ["misc4", "misc5", "copy6"])
        self.assertTrue(all(r["validation_upper_family"] > 0.0001 for r in self.report["per_input"]))

    def test_capped_heuristics_are_not_reported_as_all_stopping(self):
        rows = {r["model"]: r for r in self.report["prefixes"]}
        self.assertEqual((rows["singleton"]["construction_runs"], rows["singleton"]["rule_fired_inputs"]), (268500, 14))
        self.assertEqual((rows["no-discovery"]["construction_runs"], rows["no-discovery"]["rule_fired_inputs"]), (81500, 19))

    def test_inconsistent_batch_novelty_is_rejected(self):
        analysis = deepcopy(json.loads((AUDIT.BASE / "analysis.json").read_text()))
        analysis["results"][0]["models"]["fixed-20000"]["validation"]["batches"][0]["novel_draws"] += 1
        with self.assertRaises(AssertionError):
            AUDIT.summarize(analysis, AUDIT.read(AUDIT.BASE / "protocol.json"), AUDIT.read(AUDIT.BASE / "COMPLETE.json"))


if __name__ == "__main__":
    unittest.main()
