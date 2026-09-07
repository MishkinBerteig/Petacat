"""Saved-data export tests, independent of the frozen execution environment."""

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pilot
from test_pilot import protocol, record


class ArtifactTests(unittest.TestCase):
    def build(self, root):
        out = root / "private"
        out.mkdir()
        p = protocol()
        p.update(episodes_per_problem=4, checkpoint_every=2)
        p["problems"] = p["problems"][:1]
        pilot.write_json(out / "protocol.json", p)
        pilot.write_json(out / "manifest.json", {"protocol_sha256": pilot.sha(out / "protocol.json"),
            "source": {"files": {f"studies/episodic-v2/{name}": pilot.sha(pilot.HERE / name)
                                  for name in ("pilot.py", "answers.py")}}})
        for i in range(4):
            row = record(p, i, a="a" if i < 3 else "b")
            directory = pilot.v1.directory_for(out, row["task"])
            attempt = directory / "attempt-001"
            attempt.mkdir(parents=True)
            selected = row.pop("best_answers")
            for name, value in (("episode.json", row), ("selection.json", selected),
                                ("task.json", row["task"]), ("attempt.json", {"admitted": True})):
                pilot.write_json(attempt / name, value)
            pilot.write_json(directory / "complete.json", {"task": row["task"], "attempt": attempt.name,
                "files": {file.name: pilot.sha(file) for file in attempt.iterdir()}})
        result = pilot.analyze(out)
        pilot.write_json(out / "COMPLETE.json", {"totals": result["totals"],
            "analysis_sha256": pilot.sha(out / "analysis.json"), "protocol_sha256": pilot.sha(out / "protocol.json")})
        return out

    def test_export_round_trip_and_no_private_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = self.build(root)
            pilot.write_json(out / "local.json", {"image": "sha256:private-image", "source": "/Users/private/source"})
            destination = root / "public"
            with patch("builtins.print"):
                pilot.export(out, destination)
                pilot.verify_export(destination)
            self.assertFalse((destination / "local.json").exists())
            rows = pilot.read_json(destination / "episodes.json")
            self.assertEqual(len(rows), 4)
            self.assertEqual(rows[0]["best_answers"]["best_a"], "a")

    def test_modified_observation_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out, destination = self.build(root), root / "public"
            with patch("builtins.print"):
                pilot.export(out, destination)
            (destination / "episodes.json").write_text("[]\n")
            with self.assertRaisesRegex(ValueError, "checksum"):
                pilot.verify_export(destination)

    def test_private_metadata_in_scientific_file_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = self.build(root)
            manifest = pilot.read_json(out / "manifest.json")
            manifest["bad_metadata"] = "/Users/private/example"
            pilot.write_json(out / "manifest.json", manifest)
            with self.assertRaisesRegex(ValueError, "private execution"):
                pilot.export(out, root / "public")

    def test_parent_provenance_included_and_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out, destination = self.build(root), root / "public"
            pilot.write_json(out / "parent-import.json", {"excluded_diagnostic_inner_runs": 48})
            with patch("builtins.print"):
                pilot.export(out, destination)
                pilot.verify_export(destination)
            self.assertIn("parent-import.json", pilot.read_json(destination / "SHA256.json"))


if __name__ == "__main__":
    unittest.main()
