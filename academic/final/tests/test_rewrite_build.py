from pathlib import Path
import json
import re
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


ACADEMIC = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ACADEMIC / "tools"))
import build_final
import convert_manuscript
import package_submission


class RewriteBuildTests(unittest.TestCase):
    def test_manuscript_preserves_formal_and_data_contracts(self):
        result = build_final.manuscript_contract(
            (ACADEMIC / "manuscript.md").read_text(),
            (ACADEMIC / "support-set-oracles-final.md").read_text(),
            build_final.approved_content_changes())
        self.assertEqual(result["references"], 34)
        self.assertEqual(result["data_tables"], 12)
        self.assertEqual(result["section_labels"], 34)
        self.assertEqual(result["display_equations"], 9)

    def test_missing_equation_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "display_equations"):
            build_final.manuscript_contract("$$x=1$$", "")

    def test_only_approved_equation_removal_is_allowed(self):
        approved = {"display_equations_removed": ["x = 1."]}
        result = build_final.manuscript_contract("$$x=1$$\n$$y=2$$", "$$y=2$$", approved)
        self.assertEqual(result["display_equations"], 1)
        with self.assertRaisesRegex(ValueError, "display_equations"):
            build_final.manuscript_contract("$$x=1$$\n$$y=2$$", "", approved)

    def test_new_section_requires_specific_approval(self):
        approved = {"section_labels_added": ["sec:applications"]}
        build_final.manuscript_contract("{#sec:method}", "{#sec:method} {#sec:applications}", approved)
        with self.assertRaisesRegex(ValueError, "section_labels"):
            build_final.manuscript_contract("{#sec:method}", "{#sec:method} {#sec:other}", approved)

    def test_numeric_removals_require_exact_approval(self):
        approved = {"removed_numeric_values": ["35"]}
        self.assertEqual(build_final.numeric_contract("35 969,000", "969,000", approved), ["35"])
        with self.assertRaisesRegex(ValueError, "numeric inventory"):
            build_final.numeric_contract("35 969,000", "", approved)
        with self.assertRaisesRegex(ValueError, "numeric inventory"):
            build_final.numeric_contract("35 969,000", "969,000")

    def test_manuscript_numeric_changes_match_approval(self):
        build_final.numeric_contract(
            (ACADEMIC / "manuscript.md").read_text(),
            (ACADEMIC / "support-set-oracles-final.md").read_text(),
            build_final.approved_content_changes())

    def test_final_tables_preserve_selected_counts_only(self):
        with TemporaryDirectory() as directory, patch.object(build_final, "ACADEMIC", Path(directory)):
            root = Path(directory)
            (root / "final").mkdir()
            (root / "generated").mkdir()
            (root / "investigations").mkdir()
            for name in ("support-study-audit.json", "investigations/misc3-episodic-audit.json"):
                (root / name).write_bytes((ACADEMIC / name).read_bytes())
            (root / "generated/episode-table.tex").write_bytes((ACADEMIC / "generated/episode-table.tex").read_bytes())
            source = "\n".join(r"\input{final/generated/" + name + "}" for name in (
                "single-check-table.tex", "single-input-table.tex", "misc3-count-table.tex", "episode-table.tex"))
            build_final.prepare_tables(source)
            for path in (root / "final/generated").glob("*.tex"):
                build_final.check_paper_scope(path.read_text())
            self.assertEqual((root / "final/generated/episode-table.tex").read_bytes(),
                             (ACADEMIC / "generated/episode-table.tex").read_bytes())
            old = (ACADEMIC / "generated/single-input-table.tex").read_text()
            new = (root / "final/generated/single-input-table.tex").read_text()
            expected = [line.rsplit(" & ", 1)[0] + r" \\" for line in old.splitlines() if line.startswith(r"\texttt{")]
            self.assertEqual(expected, [line for line in new.splitlines() if line.startswith(r"\texttt{")])
            for name, old_name in (("single-check-table.tex", "single-check-table.tex"),
                                   ("misc3-count-table.tex", "misc3-frequency-table.tex")):
                old_rows = [line for line in (ACADEMIC / "generated" / old_name).read_text().splitlines()
                            if " & " in line and not line.startswith(("Frequency", "Measure", "Answer"))]
                new_rows = [line for line in (root / "final/generated" / name).read_text().splitlines()
                            if " & " in line and not line.startswith(("Measure", "Answer"))]
                self.assertEqual(old_rows, new_rows)

    def test_paper_scope_rejects_removed_material(self):
        for text in ("frequency comparison", "total-variation distance", "permutation test",
                     "Frequency rejections", "distribution equality", "p-values", "Freq."):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, "Removed discussion"):
                build_final.check_paper_scope(text)
        build_final.check_paper_scope("Good--Turing frequency estimation and p50 selection")
        build_final.check_paper_scope("fuzzy-set membership values")

    def test_bibliography_preserves_only_cited_records(self):
        original = [{"id": "ref1", "title": "Original"}, {"id": "ref32", "title": "Other"}]
        for current, valid in ((original[:1], True), (original, False),
                               ([{"id": "ref1", "title": "Changed"}], False),
                               (original[:1] * 2, False)):
            with self.subTest(current=current), patch.object(build_final.subprocess, "check_output",
                    side_effect=[json.dumps(original), json.dumps(current)]):
                if valid:
                    build_final.verify_references("pandoc", "[@ref1]")
                else:
                    with self.assertRaises(ValueError):
                        build_final.verify_references("pandoc", "[@ref1]")

    def test_bibliography_allows_only_approved_metadata_changes(self):
        original = [{"id": "ref1", "title": "Original", "URL": "https://example.org"}]
        current = [{"id": "ref1", "title": "Original", "DOI": "10.1234/example", "issue": "3"}]
        approved = {"bibliography_csl_field_changes": {"ref1": {
            "URL": {"before": "https://example.org", "after": None},
            "DOI": {"before": None, "after": "10.1234/example"},
            "issue": {"before": None, "after": "3"}}}}
        with patch.object(build_final.subprocess, "check_output",
                          side_effect=[json.dumps(original), json.dumps(current)]):
            build_final.verify_references("pandoc", "[@ref1]", approved)
        for altered in (original, [dict(current[0], title="Changed")],
                        [dict(current[0], issue="4")]):
            with self.subTest(altered=altered), patch.object(build_final.subprocess, "check_output",
                    side_effect=[json.dumps(original), json.dumps(altered)]):
                with self.assertRaisesRegex(ValueError, "differs"):
                    build_final.verify_references("pandoc", "[@ref1]", approved)

    def test_bibliography_rejects_stale_correction(self):
        original = [{"id": "ref1", "title": "Original", "issue": "2"}]
        for before in (None, "1"):
            approved = {"bibliography_csl_field_changes": {
                "ref1": {"issue": {"before": before, "after": "3"}}}}
            with self.subTest(before=before), patch.object(build_final.subprocess, "check_output",
                    side_effect=[json.dumps(original), json.dumps(original)]):
                with self.assertRaisesRegex(ValueError, "does not match the original"):
                    build_final.verify_references("pandoc", "[@ref1]", approved)

    def test_bibliography_rejects_unknown_or_uncited_correction(self):
        original = [{"id": "ref1"}, {"id": "ref2"}]
        for key in ("ref2", "ref3"):
            approved = {"bibliography_csl_field_changes": {
                key: {"issue": {"before": None, "after": "3"}}}}
            with self.subTest(key=key), patch.object(build_final.subprocess, "check_output",
                    side_effect=[json.dumps(original), json.dumps(original[:1])]):
                with self.assertRaisesRegex(ValueError, "unknown or uncited"):
                    build_final.verify_references("pandoc", "[@ref1]", approved)

    def test_bibliography_rejects_nonmetadata_or_incomplete_correction(self):
        original = [{"id": "ref1", "title": "Original"}]
        for field, change in (("title", {"before": "Original", "after": "Changed"}),
                              ("issue", {"after": "3"})):
            approved = {"bibliography_csl_field_changes": {"ref1": {field: change}}}
            with self.subTest(field=field), patch.object(build_final.subprocess, "check_output",
                    side_effect=[json.dumps(original), json.dumps(original)]):
                with self.assertRaisesRegex(ValueError, "Invalid approved"):
                    build_final.verify_references("pandoc", "[@ref1]", approved)

    def test_final_table_paths_reject_older_and_unsafe_locations(self):
        for source in (r"\input{generated/single-input-table.tex}", r"\input{final/generated/../secret.tex}"):
            with self.subTest(source=source), self.assertRaisesRegex(ValueError, "own generated tables"):
                build_final.manuscript_table_paths(source)

    def test_requested_editorial_changes_are_present(self):
        source = (ACADEMIC / "support-set-oracles-final.md").read_text()
        self.assertIn("observed support set for problem $x$", source)
        self.assertRegex(source, r"\*[Tt]est-driven development\* \(TDD\)")
        self.assertNotIn("six long discovery gaps", source)
        self.assertNotIn("so we exclude that account", source)
        headings = [line for line in source.split(r"\bibliography", 1)[0].splitlines() if line.startswith("# ")]
        self.assertEqual(headings[-2], "# Potential Application of the Process {#sec:applications}")
        build_final.check_paper_scope(source)

    def test_converter_targets_only_named_revision(self):
        with patch.object(convert_manuscript.subprocess, "run") as run:
            convert_manuscript.convert_source("pandoc", ACADEMIC / "support-set-oracles-final.md",
                                              ACADEMIC / "support-set-oracles-final.tex")
        command = run.call_args.args[0]
        self.assertIn("--output=" + str(ACADEMIC / "support-set-oracles-final.tex"), command)
        self.assertNotIn("--output=support-set-oracles-tmlr.tex", command)
        self.assertEqual(run.call_args.kwargs["cwd"], ACADEMIC)

    def test_appendices_start_on_fresh_pages(self):
        source = (ACADEMIC / "support-set-oracles-final.md").read_text()
        references, appendices = source.split(r"\appendix", 1)
        self.assertTrue(references.rstrip().endswith(r"\clearpage"))
        headings = list(re.finditer(r"^# .+ \{#app:[^}]+\}", appendices, re.M))
        self.assertEqual(len(headings), 6)
        self.assertFalse(appendices[:headings[0].start()].strip())
        for heading in headings[1:]:
            with self.subTest(appendix=heading.group()):
                self.assertTrue(appendices[:heading.start()].rstrip().endswith(r"\clearpage"))

    def test_converter_rejects_unsafe_output_location(self):
        with self.assertRaisesRegex(ValueError, "output"):
            convert_manuscript.convert_source("pandoc", ACADEMIC / "manuscript.md", "/tmp/paper.tex")

    def test_converter_rejects_markdown_output(self):
        with self.assertRaisesRegex(ValueError, "output"):
            convert_manuscript.convert_source("pandoc", ACADEMIC / "manuscript.md",
                                              ACADEMIC / "manuscript.md")

    def test_alternate_bundle_inventory_is_explicit(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "upload.zip"
            members = ("README.md", "new-source.md")
            package_submission.write_bundle(path, {n: b"anonymous" for n in members}, members)
            result = package_submission.verify_bundle(path, members=members)
            self.assertEqual(set(result["files"]), set(members))
            with self.assertRaisesRegex(ValueError, "inventory"):
                package_submission.verify_bundle(path)


if __name__ == "__main__":
    unittest.main()
