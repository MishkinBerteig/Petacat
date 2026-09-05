from collections import Counter
import copy
import json
from pathlib import Path
import tempfile
import unittest

from analyze import flags, frequency_test, head, stopping_prefixes, upper_limit
from collect import (HERE, chunk_dir, load_completed, read_json, row_identity,
                     scheme_script, sha, tasks_for, validate_protocol, validate_rows, write_json)


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.p = read_json(HERE / "protocol.json")

    def test_protocol_and_budgets(self):
        validate_protocol(self.p)
        self.assertEqual(sum(x["runs_per_problem"] * 19 for x in self.p["phases"]), 969000)
        self.assertEqual(sum(x["runs_per_problem"] * 19 for x in self.p["pilot_phases"]), 570)

    def test_overlap_refused(self):
        self.p["phases"][1]["seed_base"] = self.p["phases"][0]["seed_base"]
        with self.assertRaises(ValueError):
            validate_protocol(self.p)

    def test_assignments_cover_each_sequence_once(self):
        for phase in self.p["phases"] + self.p["pilot_phases"]:
            tasks = list(tasks_for(self.p, phase))
            for problem in self.p["problems"]:
                selected = [t for t in tasks if t["problem"] == problem["name"]]
                indices = [i for t in selected for i in range(t["offset"], t["offset"] + t["count"])]
                self.assertEqual(indices, list(range(phase["runs_per_problem"])))
                self.assertEqual(len({t["first_seed"] + i for t in selected for i in range(t["count"])}), len(indices))

    def test_scheme_uses_fresh_memory_and_direct_cap(self):
        task = next(tasks_for(self.p, self.p["phases"][0]))
        script = scheme_script(task)
        self.assertIn("(tell *memory* 'clear)", script)
        self.assertIn("(set! *break-time* 100000)", script)
        self.assertIn("(reset-handler (lambda () (exit 1)))", script)
        self.assertIn("/metacat/metacat-headless.ss", script)

    def test_partial_bad_seed_and_cap_rows_rejected(self):
        task = next(tasks_for(self.p, self.p["pilot_phases"][1]))
        rows = [{**row_identity(task, i), "state": "a", "codelets": 10,
                 "elapsed_seconds": 0.1} for i in range(task["count"])]
        validate_rows(rows, task)
        with self.assertRaises(ValueError):
            validate_rows(rows[:-1], task)
        bad = copy.deepcopy(rows)
        bad[0]["seed"] += 1
        with self.assertRaises(ValueError):
            validate_rows(bad, task)
        bad = copy.deepcopy(rows)
        bad[0]["state"] = "*CAP*"
        with self.assertRaises(ValueError):
            validate_rows(bad, task)

    def test_corrupt_receipt_cannot_resume(self):
        task = next(tasks_for(self.p, self.p["pilot_phases"][1]))
        with tempfile.TemporaryDirectory() as temporary:
            directory = chunk_dir(Path(temporary), task)
            attempt = directory / "attempt-001"
            attempt.mkdir(parents=True)
            rows = [{**row_identity(task, i), "state": "a", "codelets": 10,
                     "elapsed_seconds": 0.1} for i in range(task["count"])]
            data = attempt / "runs.jsonl"
            data.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
            write_json(directory / "complete.json", {"task": task, "attempt": "attempt-001",
                       "sha256": sha(data), "artifacts": {"runs.jsonl": sha(data)}})
            self.assertEqual(load_completed(directory, task), rows)
            data.write_text(data.read_text() + "\n")
            with self.assertRaises(ValueError):
                load_completed(directory, task)


class AnalysisTests(unittest.TestCase):
    def test_head_boundary_ties_and_nonanswers(self):
        self.assertEqual(head(Counter({"b": 5, "a": 5})), ["a"])
        self.assertEqual(head(Counter({"a": 4, "b": 3, "c": 3})), ["a", "b"])
        self.assertEqual(head(Counter({"*CAP*": 8, "a": 2})), ["*CAP*"])

    def test_flags_keep_units_separate(self):
        result = flags(["z", "z", "b"], Counter({"a": 9, "b": 1}))
        self.assertEqual(result, {"novel_draws": 2, "novel": {"z": 2}, "missing_head": ["a"]})

    def test_zero_discovery_upper_limits(self):
        self.assertAlmostEqual(upper_limit(0, 30000), 1 - 0.05 ** (1 / 30000), places=12)
        self.assertLess(upper_limit(0, 30000), 1e-4)
        self.assertGreater(upper_limit(0, 30000, 0.05 / 19), 1e-4)
        self.assertEqual(upper_limit(10, 10), 1)

    def test_stopping_floor_and_gap(self):
        cfg = read_json(HERE / "protocol.json")["analysis"]
        result = stopping_prefixes(["a"] * 20000, cfg)
        self.assertEqual(result["singleton"], {"runs": 10000, "rule_fired": True})
        self.assertEqual(result["no-discovery"], {"runs": 3000, "rule_fired": True})

    def test_stopping_truncation_reported(self):
        cfg = read_json(HERE / "protocol.json")["analysis"]
        result = stopping_prefixes([str(i) for i in range(20000)], cfg)
        self.assertFalse(result["singleton"]["rule_fired"])
        self.assertFalse(result["no-discovery"]["rule_fired"])

    def test_frequency_identity_and_extreme(self):
        equal = frequency_test(Counter(a=100), Counter(a=100), 999, 123)
        self.assertEqual(equal["p_value"], 1)
        self.assertEqual(equal["total_variation"], 0)
        opposite = frequency_test(Counter(a=100), Counter(b=100), 999, 123)
        self.assertEqual(opposite["p_value"], 0.001)
        self.assertEqual(opposite["total_variation"], 1)

    def test_frequency_reproducible(self):
        args = (Counter(a=8, b=2), Counter(a=5, b=5), 999, 99)
        self.assertEqual(frequency_test(*args), frequency_test(*args))


if __name__ == "__main__":
    unittest.main()
