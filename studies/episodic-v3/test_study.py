"""Deterministic stopping, gating, selection, and artifact tests; no searches."""

from copy import deepcopy
import math
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import study
from analysis_tools import Construction, counts_summary, upper_bound, validate_frozen


def protocol():
    p = study.read_json(study.HERE / "protocol.json")
    p.update(study_kind="smoke", workers=2, invocation_timeout_seconds=1800, port_episodes=2)
    p["construction"].update(max_episodes=4, singleton_threshold=.5)
    p["problems"] = [p["problems"][0], p["problems"][6]]
    p["validation"].update(episodes=2, family_size=4)
    return p


def seeds_for(p):
    return {ph: {x["name"]: [100000 + 10000 * k + 1000 * i + 8 * j
                             for j in range(study.phase_budget(p, ph))]
                 for i, x in enumerate(p["problems"])} for k, ph in enumerate(study.PHASES)}


def record(p, seeds, ep=0, a="z", b="z", phase="construction", pi=0):
    task = study.task_for(p, seeds, phase, pi, ep)
    winner = lambda answer: {"answer": answer, "quality": 80., "temperature": 20.,
        "rule_abstractness": 80., "theme_abstractness": 40., "coherent": True,
        "theme_count": 1, "unjustified_count": 0, "themes": ["plato-length=diff"]}
    return {"task": task, "status": "complete", "attempted_runs": 8, "answer_runs": 8,
            "capped_runs": 0, "answerless_runs": 0, "codelets": 8, "elapsed_seconds": 1.,
            "best_answers": {"best_a": a, "best_b": b},
            "outcomes": {"quality": {"kind": "answers", "answers": [a]},
                         "preference": {"kind": "answers", "answers": [b]}},
            "winners": {"quality": [winner(a)], "preference": [winner(b)]}}


class DecisionTests(unittest.TestCase):
    def setUp(self):
        self.p = protocol()
        self.seeds = seeds_for(self.p)

    def row(self, ep, **kwargs):
        return record(self.p, self.seeds, ep, **kwargs)

    def test_immediate_freeze_after_second_matching_episode(self):
        c = Construction(self.p["construction"])
        c.add(self.row(0))
        self.assertFalse(c.done)
        c.add(self.row(1))
        self.assertTrue(c.qualified)
        self.assertEqual(c.frozen["best_a"]["at_episode"], 2)
        with self.assertRaisesRegex(ValueError, "after its stop"):
            c.add(self.row(2))

    def test_independent_freeze_and_no_later_oracle_expansion(self):
        c = Construction(self.p["construction"])
        for i, (a, b) in enumerate([("a", "b"), ("a", "c"), ("x", "b")]):
            c.add(self.row(i, a=a, b=b))
        self.assertEqual(c.frozen["best_a"]["answer_counts"], {"a": 2})
        self.assertEqual([c.frozen[d]["at_episode"] for d in study.DEFINITIONS], [2, 3])
        self.assertIn("x", c.summary()["all_collected"]["best_a"]["answer_counts"])

    def test_cap_retains_data_but_not_qualification(self):
        c = Construction(self.p["construction"])
        for i in range(4):
            c.add(self.row(i, a=chr(97 + i), b=chr(97 + i)))
        self.assertTrue(c.done)
        self.assertFalse(c.qualified)
        self.assertEqual(c.summary()["stop_reason"], "budget-cap")
        self.assertEqual(c.summary()["all_collected"]["best_a"]["N"], 4)

    def test_imported_pilot_cannot_claim_retrospective_early_stop(self):
        c = Construction(self.p["construction"], imported_episodes=3)
        for i in range(3):
            c.add(self.row(i))
        self.assertEqual(c.frozen["best_a"]["at_episode"], 3)
        self.assertFalse(c.history[1]["definitions"]["best_a"]["freeze_eligible"])

    def test_zero_without_answers_does_not_qualify(self):
        c = Construction(self.p["construction"])
        r = self.row(0)
        r["best_answers"] = dict.fromkeys(study.DEFINITIONS)
        c.add(r)
        self.assertFalse(c.qualified)
        self.assertIsNone(c.history[0]["definitions"]["best_a"]["f1_over_N"])

    def test_every_episode_is_a_checkpoint(self):
        c = Construction(self.p["construction"])
        for i in range(4):
            c.add(self.row(i, a=chr(97 + i), b=chr(97 + i)))
        self.assertEqual([x["episodes"] for x in c.history], [1, 2, 3, 4])

    def test_repeated_outside_answer_counts_twice(self):
        frozen = counts_summary({"z": 10})
        rows = [self.row(i, a="a", phase="validation") for i in range(2)]
        result = validate_frozen(rows, "best_a", frozen, self.p["validation"], True)
        self.assertEqual(result["outside_occurrences"], 2)
        self.assertEqual(result["outside_counts"], {"a": 2})
        self.assertEqual(frozen["answer_counts"], {"z": 10})

    def test_no_early_confidence_bound(self):
        result = validate_frozen([self.row(0)], "best_a", counts_summary({"z": 10}), self.p["validation"], True)
        self.assertEqual(result["status"], "incomplete")
        self.assertIsNone(result["upper_bound"])

    def test_skipped_validation_has_no_invented_bound(self):
        result = validate_frozen([], "best_a", None, self.p["validation"], False)
        self.assertEqual(result["status"], "skipped-threshold-not-met")
        self.assertFalse(result["coverage_claim"])
        with self.assertRaisesRegex(ValueError, "ineligible"):
            validate_frozen([self.row(0)], "best_a", None, self.p["validation"], False)

    def test_main_confidence_family_is_all_38_not_selected_problems(self):
        p = study.read_json(study.HERE / "protocol.json")
        self.assertEqual(p["validation"]["family_size"], 38)
        self.assertAlmostEqual(upper_bound(0, 1000, .05 / 38), .0066113665413436995)
        self.assertLess(upper_bound(1, 1000, .05 / 38), .01)
        self.assertGreater(upper_bound(2, 1000, .05 / 38), .01)

    def test_exact_binomial_edges(self):
        self.assertIsNone(upper_bound(0, 0, .05))
        self.assertEqual(upper_bound(10, 10, .05), 1.)
        self.assertAlmostEqual(upper_bound(0, 300, .05), .009936081944457664)
        self.assertAlmostEqual(upper_bound(1, 1000, .00625), .0071543076395277905)
        with self.assertRaises(ValueError):
            upper_bound(2, 1, .05)

    def test_port_ties_use_occurrence_order_not_canonical_order(self):
        values = [{"answer": "z", "quality": 80.}, {"answer": "a", "quality": 80.}]
        outcomes, winners, selected = study.port_selection(values, lambda i, j: 0, study.v1.reduce_answers)
        self.assertEqual(selected, {"best_a": "z", "best_b": "z"})
        self.assertEqual(winners["quality"][0]["answer"], "a")

    def test_port_strictly_better_later_answer_wins(self):
        values = [{"answer": "z", "quality": 80.}, {"answer": "a", "quality": 95.}]
        _, _, selected = study.port_selection(values, lambda i, j: -1 if i > j else 1, study.v1.reduce_answers)
        self.assertEqual(selected, {"best_a": "a", "best_b": "a"})

    def test_port_quality_does_not_break_conceptual_tie(self):
        values = [{"answer": "z", "quality": 80.}, {"answer": "a", "quality": 95.}]
        _, _, selected = study.port_selection(values, lambda i, j: 0, study.v1.reduce_answers)
        self.assertEqual(selected, {"best_a": "a", "best_b": "z"})


class HarnessTests(unittest.TestCase):
    def test_hard_main_budgets(self):
        p = study.read_json(study.HERE / "protocol.json")
        study.validate_protocol(p)
        self.assertEqual(8 * 19 * sum(study.phase_budget(p, ph) for ph in study.PHASES), 471200)
        for key, value in (("port_episodes", 101), ("workers", 13)):
            bad = deepcopy(p)
            bad[key] = value
            with self.assertRaises(ValueError):
                study.validate_protocol(bad)
        p["construction"]["max_episodes"] = 2001
        with self.assertRaises(ValueError):
            study.validate_protocol(p)

    def test_minimum_and_checkpoint_policy_cannot_silently_change(self):
        for key in ("min_episodes", "checkpoint_every"):
            p = protocol()
            p["construction"][key] = 100
            with self.assertRaises(ValueError):
                study.validate_protocol(p)

    def test_seed_plan_bounds_and_repeated_draws_allowed(self):
        p = protocol()
        seeds = seeds_for(p)
        seeds["construction"][p["problems"][0]["name"]] = [1] * 4
        study.validate_seeds(p, seeds)
        seeds["construction"][p["problems"][0]["name"]][0] = 2**32
        with self.assertRaises(ValueError):
            study.validate_seeds(p, seeds)

    def test_saved_completed_task_never_executes(self):
        p = protocol()
        row = record(p, seeds_for(p))
        with patch.object(study.v2, "load_completed", return_value=row), patch.object(study.v2, "execute_task") as execute:
            self.assertIs(study.execute_task(Path("unused"), row["task"], {}, 1), row)
            execute.assert_not_called()

    def build_study(self, out):
        p = protocol()
        seeds = seeds_for(p)
        imported = {x["name"]: 0 for x in p["problems"]}
        for name, value in (("protocol.json", p), ("seeds.json", seeds)):
            study.write_json(out / name, value)
        manifest = {"protocol_sha256": study.sha(out / "protocol.json"), "seeds_sha256": study.sha(out / "seeds.json"),
                    "imported_episodes": imported, "source": {"files": {
                        f"studies/episodic-v3/{name}": study.sha(study.HERE / name) for name in ("study.py", "analysis_tools.py")}}}
        study.write_json(out / "manifest.json", manifest)
        saved = []

        def execute(output, task, *args):
            pi = next(i for i, x in enumerate(p["problems"]) if x["name"] == task["problem"])
            ep, phase = task["episode"], task["phase"]
            a = b = "z"
            if phase == "construction" and pi == 0:
                a, b = [("a", "b"), ("a", "c"), ("x", "b")][ep]
            elif phase == "construction":
                a = b = chr(97 + ep)
            row = record(p, seeds, ep, a=a, b=b, phase=phase, pi=pi)
            study.save_import(output, row, task, {"fixture": True})
            saved.append(row)
            return row

        args = SimpleNamespace(out=out, allow_full_experiment=False)
        with patch.object(study, "verify_study", return_value=(p, manifest, seeds, {})), \
                patch.object(study, "execute_task", side_effect=execute) as runner, patch("builtins.print"):
            study.run(args)
            self.assertEqual(runner.call_count, 13)
            study.run(args)
            self.assertEqual(runner.call_count, 13)
        return p, seeds, saved

    def test_coordinator_gates_validation_and_runs_port_for_every_problem(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self.build_study(out)
            result = study.read_json(out / "analysis.json")
            first, second = result["results"]
            self.assertEqual(first["phase_episodes"], {"construction": 3, "validation": 2, "port": 2})
            self.assertEqual(second["phase_episodes"], {"construction": 4, "validation": 0, "port": 2})
            self.assertFalse(second["coverage_qualified"])
            self.assertTrue(second["definitions"]["best_a"]["frequency_comparison"])

    def test_export_roundtrip_reproduces_stopping_and_statistics(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "raw"
            out.mkdir()
            self.build_study(out)
            study.write_json(out / "local.json", {"source": "/Users/private", "image": "sha256:private"})
            destination = Path(tmp) / "public"
            with patch("builtins.print"):
                study.export(out, destination)
                study.verify_export(destination)
            self.assertFalse((destination / "local.json").exists())
            (destination / "episodes.json").write_text("[]\n")
            with self.assertRaisesRegex(ValueError, "checksum"):
                study.verify_export(destination)

    def test_frozen_oracle_cannot_be_expanded(self):
        p = protocol()
        c = Construction(p["construction"])
        for i in range(2):
            c.add(record(p, seeds_for(p), i))
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            study.save_oracles(out, "misc4", c)
            c.frozen["best_a"]["answer_counts"]["unexpected"] = 1
            with self.assertRaisesRegex(ValueError, "Frozen oracle"):
                study.save_oracles(out, "misc4", c)

    def test_error_record_is_not_an_answer_and_is_retained(self):
        p = protocol()
        seeds = seeds_for(p)
        row = record(p, seeds)
        row.update(status="engine-error", attempted_runs=1, answer_runs=0, codelets=1,
                   best_answers=dict.fromkeys(study.DEFINITIONS), error_step=0,
                   error={"stage": "run", "detail": "fixture"},
                   outcomes={x: {"kind": "engine-error"} for x in study.DEFINITIONS.values()},
                   winners={x: [] for x in study.DEFINITIONS.values()})
        result = study.summarize([row], p, seeds, {})
        self.assertEqual(result["totals"]["construction"]["engine_error_episodes"], 1)
        self.assertEqual(result["results"][0]["definitions"]["best_a"]["reference_all_collected"]["N"], 0)


if __name__ == "__main__":
    unittest.main()
