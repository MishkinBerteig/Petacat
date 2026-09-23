from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch


ACADEMIC = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ACADEMIC / "tools"))
import build_short


class ShortBuildTests(unittest.TestCase):
    @staticmethod
    def pdf_text(main_pages):
        header = "Under review as submission to TMLR\n"
        return "\f".join([header + "Main content"] * main_pages
                          + [header + "\nReferences\nCitations", header + "Appendix A"])

    def setUp(self):
        self.source = (ACADEMIC / "support-set-oracles-12-page.md").read_text()

    def test_accepts_up_to_twelve_main_pages(self):
        for count in (1, 9, 11, 12):
            with self.subTest(count=count):
                self.assertEqual(build_short.main_page_count(self.pdf_text(count)), count)

    def test_rejects_thirteen_main_pages(self):
        with self.assertRaisesRegex(ValueError, "13 pages"):
            build_short.main_page_count(self.pdf_text(13))

    def test_rejects_missing_or_duplicate_reference_heading(self):
        for text in ("No heading", self.pdf_text(9) + "\fReferences\n"):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, "one References heading"):
                build_short.main_page_count(text)

    def test_reference_page_cannot_hide_main_content(self):
        text = self.pdf_text(12).replace("\nReferences", "\nConclusion still continues here\nReferences")
        with self.assertRaisesRegex(ValueError, "new page"):
            build_short.main_page_count(text)

    def test_manuscript_keeps_references_equations_and_audited_tables(self):
        result = build_short.manuscript_contract(self.source)
        self.assertEqual(result["references"], 34)
        self.assertEqual(result["display_equations"], 9)
        self.assertEqual(result["audited_tables"], 12)
        self.assertEqual(result["appendices"], 10)

    def test_missing_equation_is_rejected(self):
        altered = re.sub(r"\$\$.*?\$\$", "", self.source, count=1, flags=re.S)
        with self.assertRaisesRegex(ValueError, "equation inventory"):
            build_short.manuscript_contract(altered)

    def test_missing_reference_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "reference inventory"):
            build_short.manuscript_contract(self.source.replace("@ref35", ""))

    def test_missing_audited_table_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "table inventory"):
            build_short.manuscript_contract(self.source.replace(r"\input{short/generated/episode-table.tex}", ""))

    def test_invented_summary_count_is_rejected(self):
        altered = re.sub(r"\b24 / 100(?=\s*\|)", "23 / 100", self.source)
        self.assertNotEqual(altered, self.source)
        with self.assertRaisesRegex(ValueError, "summary differs"):
            build_short.manuscript_contract(altered)

    def test_summary_alignment_whitespace_is_accepted(self):
        altered = "\n".join(re.sub(r" +", "\t   ", line) if line.startswith("|") else line
                            for line in self.source.splitlines())
        result = build_short.manuscript_contract(altered)
        self.assertEqual(result["misc3_summary"], "Matches saved study")

    def test_duplicate_section_label_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            build_short.manuscript_contract(self.source + "\n# Duplicate {#sec:method}\n")

    def test_main_text_retains_critical_boundaries(self):
        main = self.source.split(r"\bibliography", 1)[0]
        flat = re.sub(r"\s+", " ", main)
        for text in ("Historical build provenance is incomplete", "no p50 head for these two definitions",
                     "0.05/38", "Ten populations", "Twenty fail", "207,791", "969,000",
                     "conditional on a complete episode producing a solution",
                     "another conceptually meaningful", "root causes", "TDD", "consenting speaker"):
            with self.subTest(text=text):
                self.assertIn(text.lower(), flat.lower())
        self.assertNotIn("not a new estimator", main)
        self.assertIn("The novelty lies in how we", flat)
        self.assertIn("Our second contribution is the testing process", flat)

    def test_main_tables_are_compact_and_detail_remains_in_appendices(self):
        main, appendices = self.source.split(r"\appendix", 1)
        self.assertEqual(re.findall(r"\\input\{([^}]+)\}", main),
                         ["short/generated/cycle-table.tex", "short/generated/single-check-table.tex"])
        for name in ("episodic-coverage-table.tex", "episodic-port-table.tex", "single-input-table.tex"):
            self.assertIn(name, appendices)
        self.assertTrue(main.index("# Potential Application") < main.index("# Conclusion"))

    def test_stale_preservation_snapshot_is_rejected(self):
        with patch.object(build_short, "preservation_snapshot", return_value={}):
            with self.assertRaisesRegex(ValueError, "earlier draft"):
                build_short.check_preservation()

    def test_current_earlier_drafts_are_unchanged(self):
        self.assertEqual(len(build_short.check_preservation()), 64)

    def test_table_terminology_preserves_every_numeric_token(self):
        for path, content in build_short.table_contents().items():
            with self.subTest(path=path):
                old = (ACADEMIC / "final/generated" / Path(path).name).read_text()
                self.assertEqual(re.findall(r"\d+", old), re.findall(r"\d+", content))
                self.assertNotRegex(content, r"(?i)\banswers?\b|\banswered\b|\banswerless\b")

    def test_changed_generated_table_value_is_rejected(self):
        target = ACADEMIC / "short/generated/episodic-accounting-table.tex"
        read_text = Path.read_text

        def changed(path, *args, **kwargs):
            text = read_text(path, *args, **kwargs)
            return text.replace("80,591", "80,590") if path == target else text

        with patch.object(Path, "read_text", changed):
            with self.assertRaisesRegex(ValueError, "table content changed"):
                build_short.manuscript_contract(self.source)

    def test_paper_uses_consistent_solution_and_process_terms(self):
        prose = self.source.replace("*answer quality*", "")
        self.assertNotRegex(prose, r"(?i)\bworkflows?\b|\banswers?\b|\banswered\b|\banswerless\b")
        abstract = re.sub(r"\s+", " ", self.source.split("# Introduction", 1)[0])
        for term in ("two countable sets", "Metacat", "Petacat", "AI coding tools",
                     "Good--Turing", "p50", "missing", "unexpected", "episodic learning"):
            self.assertIn(term, abstract)
        self.assertNotRegex(abstract, r"969,000|25,974|207,791|1,000|24 of 100")
        self.assertIn(r"\mathcal R\subseteq\mathcal X\times\mathcal Y", self.source)
        self.assertNotIn("one-to-one", abstract)


if __name__ == "__main__":
    unittest.main()
