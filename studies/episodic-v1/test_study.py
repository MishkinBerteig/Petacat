"""Deterministic study-tool tests. These never launch either search engine."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import collect
from outcomes import PROJECTIONS, answer_outcome, compare, population, preference, reduce_answers, stopping_history


def answer(name="abc", **changes):
    result = {"answer": name, "quality": 80.0, "temperature": 20.0, "rule_abstractness": 70.0,
              "theme_abstractness": 35.0, "coherent": True, "theme_count": 1, "unjustified_count": 0,
              "themes": ["plato-string-position-category=plato-identity"]}
    result.update(changes)
    return result


def row(names=("abc",)):
    return {"outcomes": {p: answer_outcome(names) for p in PROJECTIONS}}


class StatisticsTests(unittest.TestCase):
    def test_one_set_is_one_observation(self):
        stats = population([row(("a", "b")), row(("b", "a")), row(("b",))], "quality")
        self.assertEqual((stats["N"], stats["f1"], stats["f1_over_N"]), (3, 1, 1 / 3))

    def test_empty_population_has_no_false_zero(self):
        self.assertIsNone(population([], "quality")["f1_over_N"])

    def test_no_answer_is_retained(self):
        stats = population([row(()), row(("a",)), row(("a",))], "quality")
        self.assertEqual((stats["N"], stats["f1"]), (3, 1))

    def test_zero_singletons_is_not_a_confidence_bound(self):
        result = compare([row()], [row()] * 4, "quality")
        self.assertAlmostEqual(result["zero_novelty_nominal_95_percent_upper"], 0.5271291955)

    def test_novel_sets_need_not_have_novel_members(self):
        result = compare([row(("a",)), row(("b",))], [row(("a", "b"))], "quality")
        self.assertEqual(result["novel_outcome_episodes"], 1)
        self.assertEqual(result["new_individual_answer_strings"], [])

    def test_two_populations_can_differ(self):
        a = row(("a",))
        b = row(("b",))
        b["outcomes"]["preference"] = a["outcomes"]["preference"]
        self.assertEqual(population([a, b], "quality")["f1"], 2)
        self.assertEqual(population([a, b], "preference")["f1"], 0)

    def test_checkpoint_minimum_and_streak(self):
        cfg = {"checkpoint_every": 4, "min_episodes": 8, "consecutive_checkpoints": 2, "singleton_threshold": .1}
        history, n = stopping_history([row()] * 20, cfg)
        self.assertEqual(n, 12)
        self.assertEqual([h["N"] for h in history], [4, 8, 12])

    def test_both_projections_must_pass(self):
        rows = [row() for _ in range(12)]
        for i, r in enumerate(rows):
            r["outcomes"]["preference"] = answer_outcome([chr(97 + i)])
        cfg = {"checkpoint_every": 4, "min_episodes": 8, "consecutive_checkpoints": 2, "singleton_threshold": .1}
        self.assertIsNone(stopping_history(rows, cfg)[1])

    def test_p50_is_canonical_and_reaches_half(self):
        result = population([row(("c",)), row(("b",)), row(("a",))], "quality")
        self.assertEqual(result["p50"], [answer_outcome(["a"]), answer_outcome(["b"])])
        self.assertEqual(result["p50_empirical_mass"], 2 / 3)


class SelectionTests(unittest.TestCase):
    def test_best_quality_not_latest_or_coolest(self):
        values = [answer("a", quality=95, temperature=30), answer("b", quality=70, temperature=0)]
        outcomes, _ = reduce_answers(values, lambda i, j: 0)
        self.assertEqual(outcomes["quality"], answer_outcome(["a"]))
        self.assertEqual(outcomes["preference"], answer_outcome(["a", "b"]))

    def test_equal_letters_are_compared_before_collapsing(self):
        values = [answer("a", quality=90), answer("a", quality=50), answer("b", quality=80)]
        outcomes, winners = reduce_answers(values, lambda i, j: 0)
        self.assertEqual(len(winners["preference"]), 3)
        self.assertEqual(outcomes["preference"], answer_outcome(["a", "b"]))
        self.assertEqual(winners["quality"][0]["quality"], 90)

    def test_no_answers(self):
        self.assertEqual(reduce_answers([], None)[0]["quality"], {"kind": "no-answer"})

    def test_coherence_outranks_justification(self):
        self.assertEqual(preference(answer(unjustified_count=1), answer(coherent=False)), -1)

    def test_both_incoherent_uses_partial_dominance(self):
        a = answer(coherent=False, theme_abstractness=70, theme_count=2)
        b = answer(coherent=False, theme_abstractness=80, theme_count=3)
        self.assertEqual(preference(a, b), -1)
        b["theme_count"] = 1
        self.assertEqual(preference(a, b), 0)

    def test_justification_precedes_abstractness_and_richness(self):
        self.assertEqual(preference(answer(), answer(unjustified_count=1, rule_abstractness=100, theme_count=4)), -1)

    def test_abstractness_requires_same_themes_and_comparable_rules(self):
        a, b = answer(rule_abstractness=90), answer(rule_abstractness=20)
        self.assertEqual(preference(a, b), -1)
        self.assertEqual(preference(a, b, comparable=False), 0)
        self.assertEqual(preference(a, b, same_themes=False), 0)

    def test_numeric_quality_does_not_break_native_tie(self):
        self.assertEqual(preference(answer(quality=99), answer(quality=1)), 0)

    def test_reject_asymmetry_and_cycles(self):
        with self.assertRaisesRegex(ValueError, "Asymmetric"):
            reduce_answers([answer("a"), answer("b")], lambda i, j: -1)
        edges = {(0, 1), (1, 2), (2, 0)}
        with self.assertRaisesRegex(ValueError, "Cyclic"):
            reduce_answers([answer("a"), answer("b"), answer("c")], lambda i, j: -1 if (i, j) in edges else 1)

    def test_permutation_invariant_winners(self):
        values = [answer("c", quality=50), answer("a", quality=90), answer("b", quality=90)]
        forward = reduce_answers(values, lambda i, j: 0)
        reverse = reduce_answers(list(reversed(values)), lambda i, j: 0)
        self.assertEqual(forward, reverse)


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.p = collect.read_json(collect.HERE / "protocol.smoke.json")
        self.task = collect.task_for(self.p, "construction", 0, 0)

    def test_smoke_protocol_and_budget(self):
        collect.validate_protocol(self.p)
        self.assertEqual(len(self.p["problems"]) * (20 + 4 + 4), 56)

    def test_main_needs_explicit_permission(self):
        self.p["study_kind"] = "main"
        with self.assertRaisesRegex(ValueError, "allow-full"):
            collect.authorize_main(self.p, False)

    def test_cannot_disguise_full_as_smoke(self):
        self.p["construction"]["max_episodes"] = 1000
        with self.assertRaisesRegex(ValueError, "hard safety"):
            collect.validate_protocol(self.p)

    def test_seed_blocks_and_whole_episode_offsets(self):
        self.assertEqual(collect.task_for(self.p, "construction", 0, 1)["first_seed"], self.task["first_seed"] + 8)
        self.p["seed_bases"]["port"] = self.p["seed_bases"]["construction"]
        with self.assertRaisesRegex(ValueError, "Overlapping"):
            collect.validate_protocol(self.p)

    def test_scheme_compact_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            text = "EP\tcomplete\t8\t1\t7\t0\t700100\t-1\n"
            for p in PROJECTIONS:
                text += f"DESC\t{p}\tabc\t80\t20\t70\t35\t1\t0\t1\tplato-string-position-category=plato-identity\n"
            (path / "raw.tsv").write_text(text)
            result = collect.scheme_row(path, self.task)
            result["elapsed_seconds"] = 1.0
            collect.validate_row(result, self.task)
            self.assertEqual(result["outcomes"]["quality"], answer_outcome(["abc"]))

    def test_engine_error_aborts_episode_without_best_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / "raw.tsv").write_text("EP\tengine-error\t3\t2\t0\t0\t300\t2\n")
            (path / "condition.txt").write_text("test condition")
            (path / "error-stage.txt").write_text("run\n")
            result = collect.scheme_row(path, self.task)
            result["elapsed_seconds"] = 1.0
            collect.validate_row(result, self.task)
            self.assertEqual(result["outcomes"]["quality"], {"kind": "engine-error"})
            result["outcomes"]["quality"] = answer_outcome(["abc"])
            with self.assertRaises(ValueError):
                collect.validate_row(result, self.task)

    def test_no_ordered_trajectory_fields(self):
        with self.assertRaisesRegex(ValueError, "trajectories"):
            collect.validate_row({"sequences": []}, self.task)

    def test_resume_validates_checksums(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            directory = collect.directory_for(out, self.task)
            attempt = directory / "attempt-001"
            attempt.mkdir(parents=True)
            for name in ("episode.json", "task.json", "attempt.json"):
                collect.write_json(attempt / name, {})
            collect.write_json(directory / "complete.json", {"task": self.task, "attempt": "attempt-001",
                "files": {p.name: collect.sha(p) for p in attempt.iterdir()}})
            (attempt / "episode.json").write_text("changed")
            with self.assertRaisesRegex(ValueError, "checksum"):
                collect.load_completed(out, self.task)

    def test_completed_episode_is_never_rerun(self):
        sentinel = {"already": "complete"}
        with patch.object(collect, "load_completed", return_value=sentinel):
            self.assertIs(collect.execute_task(Path("unused"), self.task, {}, {}, 1), sentinel)

    def test_coordinator_stops_at_checkpoint_and_complete_resume_runs_nothing(self):
        from types import SimpleNamespace
        p = deepcopy(self.p)
        p["problems"] = p["problems"][:1]
        saved = {}

        def load(out, task):
            return saved.get((task["phase"], task["episode"]))

        def execute(out, task, *args):
            value = {"task": task, "status": "complete", "attempted_runs": 8, "answer_runs": 1,
                     "capped_runs": 0, "answerless_runs": 7, "codelets": 8,
                     "outcomes": {pr: answer_outcome(["abc"]) for pr in PROJECTIONS},
                     "winners": {pr: [answer()] for pr in PROJECTIONS}, "elapsed_seconds": 0.1}
            saved[task["phase"], task["episode"]] = value
            return value

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            collect.write_json(out / "protocol.json", p)
            collect.write_json(out / "manifest.json", {"protocol_sha256": collect.sha(out / "protocol.json")})
            args = SimpleNamespace(out=out, allow_full_experiment=False, retry_incomplete=False)
            with patch.object(collect, "verify_study", return_value=({}, p, {})), \
                    patch.object(collect, "load_completed", side_effect=load), \
                    patch.object(collect, "execute_task", side_effect=execute) as call, \
                    patch("builtins.print"):
                collect.run(args)
                self.assertEqual(call.call_count, 20)
                self.assertEqual(len([k for k in saved if k[0] == "construction"]), 12)
                collect.run(args)
                self.assertEqual(call.call_count, 20)


if __name__ == "__main__":
    unittest.main()
