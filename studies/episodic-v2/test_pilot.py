"""Deterministic pilot tests; no engine execution."""

from copy import deepcopy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pilot
from answers import DEFINITIONS, discovery_curve, select_answer, statistics


def protocol():
    return pilot.read_json(pilot.HERE / "protocol.pilot.json")


def record(p, i=0, a="z", b="z", pi=0, co_winners=None):
    task = pilot.task_for(p, pi, i)
    names = sorted(set(co_winners or [a, b]))
    winner = lambda name: {"answer": name, "quality": 80.0, "temperature": 20.0,
        "rule_abstractness": 80.0, "theme_abstractness": 40.0, "coherent": True,
        "theme_count": 1, "unjustified_count": 0,
        "themes": ["plato-string-position-category=plato-identity"]}
    return {"task": task, "status": "complete", "attempted_runs": 8, "answer_runs": 8,
            "capped_runs": 0, "answerless_runs": 0, "codelets": 8, "elapsed_seconds": 1.,
            "outcomes": {pr: {"kind": "answers", "answers": names} for pr in DEFINITIONS.values()},
            "winners": {pr: [winner(n) for n in names] for pr in DEFINITIONS.values()},
            "best_answers": {"best_a": a, "best_b": b}}


class DiscoveryTests(unittest.TestCase):
    def test_counts_individual_selected_answers_not_combinations(self):
        p = protocol()
        rows = [record(p, a="a", co_winners=["a", "b", "z"]), record(p, 1, a="a", co_winners=["a", "z"])]
        result = statistics(rows, "best_a", p)
        self.assertEqual((result["N"], result["f1"], result["distinct_answers"]), (2, 0, 1))

    def test_native_earliest_selection_not_alphabetical(self):
        p = protocol()
        r = record(p, a="z", co_winners=["a", "z"])
        self.assertEqual(select_answer(r, "best_a", p), "z")

    def test_populations_have_different_curves(self):
        p = protocol()
        p["checkpoint_every"] = 2
        rows = [record(p, i, a="a", b=b) for i, b in enumerate(["b", "c", "b", "c"])]
        a, b = (discovery_curve(rows, d, p) for d in DEFINITIONS)
        self.assertEqual(a["first_observed_target_checkpoint"], 2)
        self.assertEqual(b["first_observed_target_checkpoint"], 4)
        self.assertEqual(len(a["checkpoints"]), 2)

    def test_threshold_crossing_does_not_truncate_curve(self):
        p = protocol()
        p["checkpoint_every"] = 2
        curve = discovery_curve([record(p, i, a=a) for i, a in enumerate(["a", "a", "b", "a"])], "best_a", p)
        self.assertEqual([x["f1_over_N"] for x in curve["checkpoints"]], [0, .25])
        self.assertEqual(curve["checkpoints"][1]["new_answers_since_previous_checkpoint"], ["b"])

    def test_empty_population_has_no_false_saturation(self):
        self.assertIsNone(statistics([], "best_a", protocol())["f1_over_N"])

    def test_nonzero_resolution_at_1000(self):
        p = protocol()
        rows = [record(p, i, a="b" if i == 999 else "a") for i in range(1000)]
        curve = discovery_curve(rows, "best_a", p)
        self.assertEqual(curve["latest"]["f1_over_N"], .001)
        self.assertFalse(curve["checkpoints"][-1]["at_or_below_target"])

    def test_no_answer_retained_separately_and_not_a_string(self):
        p = protocol()
        r = record(p, 1)
        r.update(answer_runs=0, answerless_runs=8, best_answers=dict.fromkeys(DEFINITIONS),
                 outcomes={pr: {"kind": "no-answer"} for pr in DEFINITIONS.values()},
                 winners={pr: [] for pr in DEFINITIONS.values()})
        pilot.validate_row(r, r["task"])
        stats = statistics([record(p), r], "best_a", p)
        self.assertEqual((stats["episodes"], stats["N"], stats["answerless_episodes"]), (2, 1, 1))

    def test_failed_episode_has_no_prefix_winner(self):
        p = protocol()
        r = record(p)
        r.update(status="engine-error", attempted_runs=2, answer_runs=1, codelets=2,
                 error_step=1, error={"stage": "run", "detail": "fixture"},
                 best_answers=dict.fromkeys(DEFINITIONS),
                 outcomes={pr: {"kind": "engine-error"} for pr in DEFINITIONS.values()},
                 winners={pr: [] for pr in DEFINITIONS.values()})
        pilot.validate_row(r, r["task"])
        stats = statistics([r], "best_a", p)
        self.assertEqual(stats["engine_error_episodes"], 1)
        self.assertIsNone(stats["f1_over_N"])


class CollectorTests(unittest.TestCase):
    def test_authorized_budget_and_reference_only(self):
        p = protocol()
        pilot.validate_protocol(p)
        self.assertEqual(len(p["problems"]) * p["episodes_per_problem"] * p["episode_runs"], 32000)
        self.assertEqual(pilot.task_for(p, 0, 0)["engine"], "metacat")

    def test_excess_budget_rejected(self):
        p = protocol()
        p["episodes_per_problem"] = 1100
        with self.assertRaises(ValueError):
            pilot.validate_protocol(p)

    def test_random_tie_policy_rejected(self):
        p = protocol()
        p["tie_policy"] = "random"
        with self.assertRaises(ValueError):
            pilot.validate_protocol(p)

    def test_overlapping_seeds_rejected(self):
        p = protocol()
        p["seed_stride"] = 100
        with self.assertRaises(ValueError):
            pilot.validate_protocol(p)

    def test_invalid_selected_answer_rejected(self):
        r = record(protocol())
        r["best_answers"]["best_a"] = "unknown"
        with self.assertRaisesRegex(ValueError, "co-winner"):
            pilot.validate_row(r, r["task"])

    def test_ordered_history_fields_rejected(self):
        r = record(protocol())
        r["runs"] = []
        with self.assertRaisesRegex(ValueError, "trajectories"):
            pilot.validate_row(r, r["task"])

    def test_duplicate_episodes_rejected(self):
        r = record(protocol())
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            pilot.summarize([r, r], protocol())

    def test_out_of_order_completion_uses_contiguous_seed_prefix(self):
        p = protocol()
        result = pilot.summarize([record(p, 2), record(p, 0)], p)["results"][0]
        self.assertEqual((result["completed_episodes"], result["contiguous_episodes"]), (2, 1))

    def test_completed_episode_never_runs_again(self):
        sentinel = record(protocol())
        with patch.object(pilot, "load_completed", return_value=sentinel):
            self.assertIs(pilot.execute_task(Path("unused"), sentinel["task"], {}, 1), sentinel)

    def test_coordinator_collects_all_checkpoints_despite_zero_singletons(self):
        p = protocol()
        p.update(episodes_per_problem=4, checkpoint_every=2, workers=2)
        p["problems"] = p["problems"][:1]
        saved = {}

        def execute(out, task, *args):
            row = record(p, task["episode"])
            saved[task["episode"]] = row
            return row

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            pilot.write_json(out / "protocol.json", p)
            pilot.write_json(out / "manifest.json", {"protocol_sha256": pilot.sha(out / "protocol.json")})
            args = SimpleNamespace(out=out, retry_incomplete=False)
            with patch.object(pilot, "verify_study", return_value=(p, {}, {})), \
                    patch.object(pilot, "load_rows", side_effect=lambda *args: list(saved.values())), \
                    patch.object(pilot, "execute_task", side_effect=execute) as run, patch("builtins.print"):
                pilot.run(args)
                self.assertEqual(run.call_count, 4)
                self.assertEqual(len(pilot.read_json(out / "analysis.json")["results"][0]["definitions"]["best_a"]["checkpoints"]), 2)
                pilot.run(args)
                self.assertEqual(run.call_count, 4)

    def test_serializer_amendment_preserves_completed_records_and_counts_overhead(self):
        p = protocol()
        r = record(p)
        with tempfile.TemporaryDirectory() as tmp:
            out, parent = Path(tmp) / "new", Path(tmp) / "old"
            out.mkdir()
            parent.mkdir()
            pilot.write_json(parent / "protocol.json", p)
            manifest = {"protocol_sha256": pilot.sha(parent / "protocol.json"), "python": {},
                        "reference_runtime": {}, "source": {"git_commit": "fixture", "files": {}}}
            pilot.write_json(parent / "manifest.json", manifest)
            complete = pilot.v1.directory_for(parent, r["task"])
            complete.mkdir(parents=True)
            pilot.write_json(complete / "complete.json", {"preserve": "byte-for-byte"})
            failure = pilot.v1.directory_for(parent, pilot.task_for(p, 0, 1)) / "attempt-001"
            failure.mkdir(parents=True)
            pilot.write_json(failure / "attempt.json", {"task": pilot.task_for(p, 0, 1), "admitted": False})
            (failure / "raw.tsv").write_text("EP\tcomplete\t8\t8\t0\t0\t100\t-1\n")
            with patch.object(pilot, "verify_study", return_value=(p, manifest, {})), \
                    patch.object(pilot, "load_rows", return_value=[r]), patch("builtins.print"):
                pilot.import_completed(out, parent)
            amendment = pilot.read_json(out / "parent-import.json")
            self.assertEqual(amendment["inherited_completed_episodes"], 1)
            self.assertEqual(amendment["excluded_diagnostic_inner_runs"], 8)
            self.assertEqual(amendment["excluded_diagnostic_codelets"], 100)
            self.assertEqual(pilot.sha(complete / "complete.json"),
                             pilot.sha(pilot.v1.directory_for(out, r["task"]) / "complete.json"))

    def test_serializer_amendment_rejects_engine_changes(self):
        p = protocol()
        with tempfile.TemporaryDirectory() as tmp:
            out, parent = Path(tmp) / "new", Path(tmp) / "old"
            out.mkdir()
            parent.mkdir()
            pilot.write_json(parent / "protocol.json", p)
            old = {"protocol_sha256": pilot.sha(parent / "protocol.json"), "python": {},
                   "reference_runtime": {}, "source": {"git_commit": "fixture", "files": {"server/engine/runner.py": "old"}}}
            new = deepcopy(old)
            new["source"]["files"]["server/engine/runner.py"] = "new"
            pilot.write_json(parent / "manifest.json", old)
            with patch.object(pilot, "verify_study", return_value=(p, new, {})):
                with self.assertRaisesRegex(ValueError, "serializer-only"):
                    pilot.import_completed(out, parent)


if __name__ == "__main__":
    unittest.main()
