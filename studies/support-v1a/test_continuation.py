import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import collect
from collect import (chunk_dir, execute_task, file_inventory, load_completed, protocol,
                     raw_rows, read_json, row_identity, scheme_segment, scheme_script,
                     sha, signature, tasks_for, validate_rows, write_json)


def task(count=3):
    p = protocol()
    return {**next(tasks_for(p, p["phases"][0])), "count": count}


def ordinary(t, i=0):
    return {**row_identity(t, i), "state": "abc", "codelets": 10,
            "elapsed_seconds": 0.1, "termination": "suspended"}


def error(t, i=0):
    return {**row_identity(t, i), "state": "*ERROR*", "codelets": 20,
            "elapsed_seconds": 0.2, "termination": "engine-error",
            "error": {"category": "scheme-condition", "stage": "run", "detail": "non-procedure #f"}}


def receipt(out, t, rows):
    directory = chunk_dir(out, t)
    attempt = directory / "attempt-001"
    attempt.mkdir(parents=True)
    write_json(attempt / "attempt.json", {"task": t, "exit_status": 0})
    (attempt / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    write_json(directory / "complete.json", {"task": t, "attempt": "attempt-001",
               "sha256": sha(attempt / "runs.jsonl"), "artifacts": file_inventory(attempt)})
    return directory


class ProtocolTests(unittest.TestCase):
    def test_budgets_and_engine_settings_unchanged(self):
        p = protocol()
        parent = read_json(collect.HERE.parent / "support-v1/protocol.json")
        for key, value in parent.items():
            if key not in ("study_id", "schema_version"):
                self.assertEqual(p[key], value)
        self.assertFalse(p["amendment"]["engine_changes"])
        self.assertEqual(sum(x["runs_per_problem"] * 19 for x in p["phases"]), 969000)
        for key in ("parent_protocol_sha256", "parent_manifest_sha256"):
            self.assertEqual(len(p["amendment"][key]), 64)

    def test_wrapper_guards_engine_not_output_io(self):
        script = scheme_script(task())
        self.assertIn("(tell *memory* 'clear)", script)
        self.assertIn("(set! *break-time* 100000)", script)
        self.assertIn("(not (i/o-error? c))", script)
        self.assertIn("(not (implementation-restriction-violation? c))", script)
        self.assertIn("(exit 86)", script)
        self.assertNotIn("$first_seed", script)
        self.assertEqual(script.count("(run-mcat)"), 1)


class RowTests(unittest.TestCase):
    def test_error_and_nonanswers_are_distinct(self):
        t = task(2)
        validate_rows([ordinary(t), error(t, 1)], t)
        bad = error(t, 1)
        bad["state"] = "*NONE*"
        with self.assertRaises(ValueError):
            validate_rows([ordinary(t), bad], t)

    def test_error_must_have_matching_identity_and_evidence(self):
        t = task(1)
        for field, value in (("seed", 42), ("termination", "suspended"), ("error", {}),
                             ("codelets", -1), ("elapsed_seconds", float("nan"))):
            row = error(t)
            row[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_rows([row], t)

    def test_unknown_initialization_count_is_not_invented(self):
        t = task(1)
        row = error(t)
        row["codelets"], row["error"]["stage"] = None, "initialize"
        validate_rows([row], t)

    def test_duplicates_and_partial_chunks_are_rejected(self):
        t = task(2)
        with self.assertRaises(ValueError):
            validate_rows([ordinary(t), ordinary(t)], t)
        with self.assertRaises(ValueError):
            validate_rows([ordinary(t)], t)

    def test_raw_prefix_parses_but_wrong_seed_fails(self):
        t = task(3)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "raw.tsv"
            path.write_text(f"0\t{t['first_seed']}\tabc\t10\t100\tsuspended\n")
            self.assertEqual(raw_rows(path, t), [ordinary(t)])
            path.write_text("0\t42\tabc\t10\t100\tsuspended\n")
            with self.assertRaises(ValueError):
                raw_rows(path, t)


class ReceiptTests(unittest.TestCase):
    def test_parent_style_receipt_is_unchanged_and_readable(self):
        t = task(2)
        with tempfile.TemporaryDirectory() as d:
            directory = receipt(Path(d), t, [ordinary(t, i) for i in range(2)])
            before = file_inventory(Path(d))
            self.assertEqual(len(load_completed(directory, t)), 2)
            self.assertEqual(file_inventory(Path(d)), before)

    def test_error_receipt_and_nested_artifacts_verified(self):
        t = task(1)
        with tempfile.TemporaryDirectory() as d:
            directory = receipt(Path(d), t, [error(t)])
            nested = directory / "attempt-001/segment-000"
            nested.mkdir()
            (nested / "condition.txt").write_text("original\n")
            info = read_json(directory / "complete.json")
            info["artifacts"] = file_inventory(directory / "attempt-001")
            write_json(directory / "complete.json", info)
            self.assertEqual(load_completed(directory, t)[0]["state"], "*ERROR*")
            (nested / "condition.txt").write_text("changed\n")
            with self.assertRaises(ValueError):
                load_completed(directory, t)

    def test_path_escape_and_missing_hashes_rejected(self):
        t = task(1)
        with tempfile.TemporaryDirectory() as d:
            directory = receipt(Path(d), t, [ordinary(t)])
            info = read_json(directory / "complete.json")
            info["artifacts"]["../escape"] = "0" * 64
            write_json(directory / "complete.json", info)
            with self.assertRaises(ValueError):
                load_completed(directory, t)
            info["artifacts"] = {"runs.jsonl": info["sha256"]}
            write_json(directory / "complete.json", info)
            with self.assertRaises(ValueError):
                load_completed(directory, t)

    def test_inventory_rejects_symlinks(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "link").symlink_to("/tmp")
            with self.assertRaises(ValueError):
                file_inventory(Path(d))


class ImportTests(unittest.TestCase):
    def test_import_rehashes_and_preserves_parent_byte_for_byte(self):
        p = protocol()
        p["problems"] = p["problems"][:1]
        p["phases"] = [{**p["phases"][0], "runs_per_problem": 3}]
        p["chunk_size"] = 2
        source = {"git_commit": "continuation", "files": {"engine": "unchanged"}}
        with tempfile.TemporaryDirectory() as d:
            parent, out = Path(d) / "parent", Path(d) / "continuation"
            parent.mkdir()
            (parent / "coordinator.lock").touch()
            write_json(parent / "progress.json", {"state": "failed"})
            write_json(parent / "protocol.json", {"fixture": "parent"})
            write_json(parent / "local.json", {"fixture": True})
            write_json(parent / "manifest.json", {"pilot": False,
                       "source": {"git_commit": p["amendment"]["parent_commit"], "files": source["files"]},
                       "python": {"fixture": True}, "reference_runtime": {"fixture": True},
                       "numeric_environment": {}})
            p["amendment"]["parent_manifest_sha256"] = sha(parent / "manifest.json")
            p["amendment"]["parent_protocol_sha256"] = sha(parent / "protocol.json")
            assigned = list(tasks_for(p, p["phases"][0]))
            receipt(parent, assigned[0], [ordinary(assigned[0], i) for i in range(2)])
            incomplete = chunk_dir(parent, assigned[1]) / "attempt-001"
            incomplete.mkdir(parents=True)
            write_json(incomplete / "attempt.json", {"exit_status": 255, "wall_seconds": 0.1})
            (incomplete / "raw.tsv").write_text("")
            before = file_inventory(parent)
            with patch("collect.protocol", return_value=p), patch("collect.source_snapshot", return_value=source), \
                 patch("collect.legacy.python_runtime", return_value={"fixture": True}), \
                 patch("collect.legacy.verify_reconstruction"), \
                 patch("collect.legacy.runtime_snapshot", return_value={"fixture": True}):
                collect.prepare(SimpleNamespace(out=out, parent=parent))
            self.assertEqual(file_inventory(parent), before)
            imported = read_json(out / "parent-import.json")
            self.assertEqual(imported["counts"], {"construction": 2})
            self.assertEqual(len(load_completed(chunk_dir(out, assigned[0]), assigned[0])), 2)
            self.assertFalse(chunk_dir(out, assigned[1]).exists())
            self.assertTrue((chunk_dir(out / "parent-incomplete", assigned[1]) / "attempt-001/raw.tsv").exists())
            self.assertEqual(read_json(out / "parent-inventory.json"), before)


class SchemeExitTests(unittest.TestCase):
    local = {"docker": "docker", "source": "/reference", "image": "pinned"}

    def segment(self, path, t, code, *, marker=False, wrong_seed=False):
        def run(*args, **kwargs):
            (path / "raw.tsv").write_text(f"0\t{t['first_seed']}\tabc\t10\t100\tsuspended\n")
            if marker:
                seed = 42 if wrong_seed else t["first_seed"] + 1
                (path / "engine-error.tsv").write_text(f"1\t{seed}\trun\t20\t200\n")
                (path / "condition.txt").write_text("non-procedure #f\n")
            return SimpleNamespace(returncode=code)
        with patch("collect.subprocess.run", side_effect=run):
            return scheme_segment(path, t, self.local, 10)

    def test_structured_error_is_an_observation(self):
        with tempfile.TemporaryDirectory() as d:
            rows, code = self.segment(Path(d), task(), 86, marker=True)
            self.assertEqual(code, 86)
            self.assertEqual([r["state"] for r in rows], ["abc", "*ERROR*"])

    def test_infrastructure_exit_is_not_an_error_observation(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(RuntimeError):
                self.segment(Path(d), task(), 137)

    def test_unmarked_reserved_exit_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(RuntimeError):
                self.segment(Path(d), task(), 86)

    def test_error_marker_identity_checked(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                self.segment(Path(d), task(), 86, marker=True, wrong_seed=True)

    def test_successful_exit_cannot_hide_partial_chunk(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                self.segment(Path(d), task(), 0)


class ExecutionTests(unittest.TestCase):
    def test_restart_advances_past_error_without_retry_or_duplicate(self):
        t, calls = task(5), []
        def segment(path, subtask, local, timeout):
            calls.append(copy.deepcopy(subtask))
            if len(calls) == 1:
                return [ordinary(subtask), error(subtask, 1)], 86
            return [ordinary(subtask, i) for i in range(subtask["count"])], 0
        with tempfile.TemporaryDirectory() as d, patch("collect.scheme_segment", side_effect=segment):
            out = Path(d)
            self.assertEqual(execute_task(out, t, {}, {}, 10), (5, 1))
            self.assertEqual([x["first_seed"] for x in calls], [t["first_seed"], t["first_seed"] + 2])
            rows = load_completed(chunk_dir(out, t), t)
            self.assertEqual([r["seed"] for r in rows], list(range(t["first_seed"], t["first_seed"] + 5)))
            self.assertEqual(execute_task(out, t, {}, {}, 10), (5, 1))
            self.assertEqual(len(calls), 2)

    def test_every_seed_can_error_without_endless_retry(self):
        t = task(3)
        def segment(path, subtask, local, timeout):
            return [error(subtask)], 86
        with tempfile.TemporaryDirectory() as d, patch("collect.scheme_segment", side_effect=segment) as call:
            self.assertEqual(execute_task(Path(d), t, {}, {}, 10), (3, 3))
            self.assertEqual(call.call_count, 3)

    def test_failed_prefix_mismatch_prevents_completion(self):
        t = task(2)
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            old = chunk_dir(out / "parent-incomplete", t) / "attempt-001"
            old.mkdir(parents=True)
            (old / "raw.tsv").write_text(f"0\t{t['first_seed']}\tdifferent\t10\t100\tsuspended\n")
            with patch("collect.scheme_segment", return_value=([ordinary(t, i) for i in range(2)], 0)):
                with self.assertRaises(RuntimeError):
                    execute_task(out, t, {}, {}, 10)
            self.assertFalse((chunk_dir(out, t) / "complete.json").exists())

    def test_matching_prefix_allows_replay_without_double_admission(self):
        t = task(2)
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            old = chunk_dir(out / "parent-incomplete", t) / "attempt-001"
            old.mkdir(parents=True)
            (old / "raw.tsv").write_text(f"0\t{t['first_seed']}\tabc\t10\t999\tsuspended\n")
            with patch("collect.scheme_segment", return_value=([ordinary(t), error(t, 1)], 86)):
                self.assertEqual(execute_task(out, t, {}, {}, 10), (2, 1))
            self.assertEqual(len(load_completed(chunk_dir(out, t), t)), 2)

    def test_operational_failure_remains_failed_attempt(self):
        t = task(1)
        with tempfile.TemporaryDirectory() as d, patch("collect.scheme_segment", side_effect=TimeoutError("limit")):
            out = Path(d)
            with self.assertRaises(RuntimeError):
                execute_task(out, t, {}, {}, 10)
            self.assertFalse((chunk_dir(out, t) / "complete.json").exists())
            info = read_json(chunk_dir(out, t) / "attempt-001/attempt.json")
            self.assertEqual(info["error_type"], "TimeoutError")


class CoordinatorTests(unittest.TestCase):
    def test_failure_drains_and_updates_completed_count_and_heartbeat(self):
        p = protocol()
        p["problems"] = p["problems"][:1]
        p["phases"] = [{**p["phases"][0], "runs_per_problem": 2}]
        p["chunk_size"], p["workers"] = 1, 2
        draining = threading.Event()
        def execute(out, t, *args):
            if t["offset"] == 0:
                raise RuntimeError("operational failure")
            if not draining.wait(5):
                raise AssertionError("No heartbeat while draining")
            return 1, 0
        states = []
        def write(path, value):
            write_json(path, value)
            if Path(path).name == "progress.json":
                states.append(copy.deepcopy(value))
                if value["state"] == "draining-after-failure":
                    draining.set()
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            with patch("collect.verify_study", return_value=({}, p, {})), patch("collect.verify_preflight"), \
                 patch("collect.load_completed", return_value=None), patch("collect.execute_task", side_effect=execute), \
                 patch("collect.write_json", side_effect=write):
                with self.assertRaisesRegex(RuntimeError, "operational failure"):
                    collect.run_study(SimpleNamespace(out=out))
            final = read_json(out / "progress.json")
            self.assertEqual(final["state"], "failed")
            self.assertEqual(final["active_chunks"], 0)
            self.assertEqual(final["completed_runs"], 1)
            self.assertTrue(any(s["state"] == "draining-after-failure" for s in states))
            self.assertFalse((out / "COMPLETE.json").exists())

    def test_stopped_study_does_not_analyze(self):
        with tempfile.TemporaryDirectory() as d, patch("collect.run_study"), patch("collect.subprocess.run") as run:
            collect.supervise(SimpleNamespace(out=Path(d)))
            run.assert_not_called()


@unittest.skipUnless(importlib.util.find_spec("scipy"), "Analysis tests need the study SciPy environment")
class AnalysisTests(unittest.TestCase):
    def test_complete_amended_analysis_and_corruption_rejection(self):
        from analyze import analyze
        p = protocol()
        p["problems"] = p["problems"][:1]
        p["phases"][1]["runs_per_problem"] = 100
        p["phases"][2]["runs_per_problem"] = 100
        p["analysis"]["frequency_permutations"] = 9
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            write_json(out / "protocol.json", p)
            receipts, parent_receipts = {}, {}
            for phase in p["phases"]:
                for t in tasks_for(p, phase):
                    rows = [ordinary(t, i) for i in range(t["count"])]
                    if phase["name"] == "validation":
                        rows[0] = error(t)
                    directory = receipt(out, t, rows)
                    name = str(directory.relative_to(out) / "complete.json")
                    receipts[name] = sha(directory / "complete.json")
                    if phase["name"] == "construction":
                        parent_receipts[name] = receipts[name]
            write_json(out / "parent-inventory.json", {})
            write_json(out / "parent-import.json", {"receipts": parent_receipts, "attempts": [],
                       "parent_inventory_sha256": sha(out / "parent-inventory.json")})
            write_json(out / "manifest.json", {"pilot": False, "source": {"git_commit": "fixture"},
                       "protocol_sha256": sha(out / "protocol.json"),
                       "parent_import_sha256": sha(out / "parent-import.json")})
            (out / "preflight").mkdir()
            write_json(out / "preflight.json", {"artifacts": {}, "main_observations": 0})
            write_json(out / "COMPLETE.json", {"total_runs": 20200, "receipts": receipts,
                       "manifest_sha256": sha(out / "manifest.json"), "engine_errors": 1,
                       "preflight_sha256": sha(out / "preflight.json")})
            analyze(out)
            result = read_json(out / "analysis.json")
            self.assertEqual(len(result["errors"]), 1)
            self.assertEqual(result["results"][0]["models"]["fixed-20000"]["validation"]["runs"], 100)
            self.assertIn("ERROR", (out / "RESULTS.md").read_text())
            name = next(iter(parent_receipts))
            (out / name).write_text((out / name).read_text() + "\n")
            with self.assertRaises(ValueError):
                analyze(out)

    def test_error_is_novel_and_in_denominator(self):
        from analyze import summarize_checks
        from collections import Counter
        t = task(100)
        rows = [ordinary(t, i) for i in range(99)] + [error(t, 99)]
        result = summarize_checks(rows, Counter(abc=100), protocol()["analysis"], family_size=19)
        self.assertEqual(result["runs"], 100)
        self.assertEqual(result["novel_draws"], 1)
        self.assertEqual(result["engine_error_runs"], 1)
        self.assertEqual(result["engine_error_rate"], 0.01)
        self.assertEqual(result["hard_error_batches"], 1)

    def test_reference_membership_does_not_make_error_acceptable(self):
        from analyze import summarize_checks
        from collections import Counter
        t = task(100)
        rows = [ordinary(t, i) for i in range(99)] + [error(t, 99)]
        result = summarize_checks(rows, Counter({"abc": 999, "*ERROR*": 1}), protocol()["analysis"], family_size=19)
        self.assertEqual(result["novel_draws"], 0)
        self.assertEqual(result["either_flag_batches"], 0)
        self.assertEqual(result["support_or_hard_error_batches"], 1)

    def test_unknown_codelets_are_explicit(self):
        from analyze import measured_codelets
        t = task(2)
        row = error(t, 1)
        row["codelets"] = None
        self.assertEqual(measured_codelets([ordinary(t), row]),
                         {"measured_codelets": 10, "unknown_codelet_runs": 1})


if __name__ == "__main__":
    unittest.main()
