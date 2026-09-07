import importlib.util
import math
from pathlib import Path
import unittest


SPEC = importlib.util.spec_from_file_location(
    "audit_numbers", Path(__file__).resolve().parents[1] / "tools/audit_numbers.py")
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


class ArithmeticTests(unittest.TestCase):
    def test_head_boundary(self):
        self.assertEqual(audit.head_members({"b": 1, "a": 2, "c": 1}), ["a"])

    def test_head_tie_order(self):
        self.assertEqual(audit.head_members({"c": 1, "b": 1, "a": 1}), ["a", "b"])

    def test_head_includes_nonanswers(self):
        self.assertEqual(audit.head_members({"*NONE*": 7, "a": 3}), ["*NONE*"])

    def test_invalid_counts(self):
        for counts in ({}, {"a": 0}, {"a": -1}, {"a": 0.5}):
            with self.assertRaises(ValueError):
                audit.head_members(counts)

    def test_binomial_probability(self):
        self.assertAlmostEqual(audit.binomial_lower_tail(3, 0.5, 1), 0.5)
        self.assertAlmostEqual(audit.binomial_lower_tail(100, 0.2, 100), 1.0)

    def test_same_support_counterexample(self):
        self.assertGreater(audit.analytic_examples()["same_support_head_absence"], 0.9)

    def test_no_singleton_certificate(self):
        self.assertGreater(audit.analytic_examples()["zero_singleton_floor_failure"], 0.13)

    def test_frequency_comparison(self):
        example = audit.analytic_examples()
        self.assertLess(example["reweighted_p20_head_absence"], 1e-9)
        self.assertLess(example["binomial_test"]["null_rejection_probability"], 1e-10)
        self.assertGreater(example["binomial_test"]["power_at_p20"], 0.999999)

    def test_fixed_validation_budget(self):
        n = audit.analytic_examples()["independent_zero_discovery_validation"]["minimum_fixed_sample"]
        self.assertLessEqual(-math.expm1(math.log(0.05) / n), 0.0001)
        self.assertGreater(-math.expm1(math.log(0.05) / (n - 1)), 0.0001)


if __name__ == "__main__":
    unittest.main()
