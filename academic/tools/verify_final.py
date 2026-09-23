#!/usr/bin/env python3
"""Check the restyled anonymous manuscript, submission limits, and preserved evidence."""

import argparse
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import subprocess
from zipfile import ZipFile

import build_final
import package_submission


ACADEMIC = Path(__file__).resolve().parents[1]
PRIVATE = re.compile(r"mishkin|berteig|m3u512gb|10\.0\.0\.12|/Users/|github\.com/[^\s]*[Pp]etacat", re.I)


class Bounds(HTMLParser):
    def __init__(self):
        super().__init__()
        self.pages = 0
        self.errors = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "page":
            self.pages += 1
        if tag == "word" and not (71.5 <= float(a["xmin"]) <= float(a["xmax"]) <= 540.5
                                  and 0 <= float(a["ymin"]) <= float(a["ymax"]) <= 792):
            self.errors.append((self.pages, a))


def output(*command):
    return subprocess.check_output(command, text=True)


def verify(invitation, style):
    pdf = ACADEMIC / (build_final.STEM + ".pdf")
    info = dict(line.split(":", 1) for line in output("pdfinfo", str(pdf)).splitlines() if ":" in line)
    info = {k: v.strip() for k, v in info.items()}
    text = output("pdftotext", "-layout", str(pdf), "-")
    pages = text.split("\f")
    main_pages = next(i for i, p in enumerate(pages) if re.search(r"(?m)^References\s*$", p))
    assert info["Page size"].startswith("612 x 792")
    assert not info.get("Author") and "Anonymous authors" in pages[0]
    assert text.count("Under review as submission to TMLR") == int(info["Pages"])
    assert not PRIVATE.search(text + str(info) + output("pdfinfo", "-url", str(pdf)))
    tex = (ACADEMIC / (build_final.STEM + ".tex")).read_text()
    assert r"\usepackage{tmlr}" in tex
    assert not re.search(r"\\usepackage\[[^]]*(?:preprint|accepted)[^]]*\]\{tmlr\}", tex)
    assert tex.index(r"\bibliography{final/references}") < tex.index(r"\appendix")
    bbl = (ACADEMIC / (build_final.STEM + ".bbl")).read_text()
    assert bbl.count(r"\bibitem") == 34
    for content in (text, tex, bbl, (ACADEMIC / "final/references.bib").read_text()):
        build_final.check_paper_scope(content)
    log = (ACADEMIC / (build_final.STEM + ".log")).read_text(errors="replace")
    assert not re.search(r"Overfull|undefined references|Citation .+ undefined|Reference .+ undefined|Missing character", log)
    bounds = Bounds()
    bounds.feed(output("pdftotext", "-bbox", str(pdf), "-"))
    assert not bounds.errors, bounds.errors
    assert bounds.pages == int(info["Pages"])
    fonts = output("pdffonts", str(pdf)).splitlines()[2:]
    assert fonts and all(re.search(r"\s+yes\s+(?:yes|no)\s+(?:yes|no)\s+\d+\s+\d+\s*$", f) for f in fonts)
    with ZipFile(style) as archive:
        for name in ("tmlr.sty", "tmlr.bst", "fancyhdr.sty"):
            assert (ACADEMIC / name).read_bytes() == archive.read("tmlr-style-file-main/" + name)
    form = json.loads(invitation.read_text())["invitations"][0]
    assert form["id"] == "TMLR/-/Submission"
    fields = form["edit"]["note"]["content"]
    abstract = (ACADEMIC / "final/abstract.txt").read_text().strip()
    assert len(info["Title"]) <= fields["title"]["value"]["param"]["maxLength"]
    assert len(abstract) <= fields["abstract"]["value"]["param"]["maxLength"]
    assert pdf.stat().st_size < fields["pdf"]["value"]["param"]["maxSize"] * 1_000_000
    category = "Long submission (more than 12 pages of main content)"
    assert main_pages > 12 and category in fields["submission_length"]["value"]["param"]["enum"]
    for name in ("authors", "authorids", "competing_interests", "human_subjects_reporting"):
        readers = fields[name]["readers"]
        assert "everyone" not in readers and not any("/Reviewers" in value for value in readers)
    supplement = ACADEMIC / (build_final.STEM + "-supplement.zip")
    package = package_submission.verify_bundle(supplement, ("mishkin", "berteig", "m3u512gb", "10.0.0.12"),
                                                members=build_final.MEMBERS)
    assert supplement.stat().st_size < fields["supplementary_material"]["value"]["param"]["maxSize"] * 1_000_000
    assert build_final.preservation_snapshot() == json.loads((ACADEMIC / "final/preserved-draft.json").read_text())
    old, new = [(ACADEMIC / name).read_text() for name in ("manuscript.md", build_final.STEM + ".md")]
    approved = build_final.approved_content_changes()
    contract = build_final.manuscript_contract(old, new, approved)
    build_final.check_paper_scope(new)
    tables = build_final.manuscript_table_paths(new)
    for name in tables:
        build_final.check_paper_scope((ACADEMIC / name).read_text())
    with ZipFile(ACADEMIC / (build_final.STEM + "-source.zip")) as source_zip:
        assert {name for name in source_zip.namelist() if name.endswith(".tex") and "generated/" in name} == set(tables)
        assert {name for name in source_zip.namelist() if name.endswith(".bib")} == {"final/references.bib"}
        for name in source_zip.namelist():
            if name.endswith((".md", ".tex", ".bib", ".bbl")):
                build_final.check_paper_scope(source_zip.read(name).decode())
    removed_numbers = build_final.numeric_contract(old, new, approved)
    build = json.loads((ACADEMIC / "final/build.json").read_text())
    assert build["pdf"]["sha256"] == build_final.digest(pdf)
    assert build["sha256"] == package["sha256"]
    assert build["markdown_sha256"] == build_final.digest(ACADEMIC / (build_final.STEM + ".md"))
    assert build["approved_content_changes_sha256"] == build_final.digest(ACADEMIC / "final/approved-content-changes.json")
    assert build["bibliography_sha256"] == build_final.digest(ACADEMIC / "final/references.bib")
    return {
        "scope": "Anonymous initial-submission files, not editorial acceptance or author approval",
        "pdf": build["pdf"], "supplement": {"file": supplement.name, **package},
        "title": info["Title"], "title_characters": len(info["Title"]),
        "abstract_words": len(abstract.split()), "abstract_characters": len(abstract),
        "pdf_pages": int(info["Pages"]), "main_text_pages": main_pages,
        "submission_type": category, "beyond_pdf": "Leave empty",
        "form_url": "https://api2.openreview.net/invitations?id=TMLR%2F-%2FSubmission",
        "form_sha256": build_final.digest(invitation), "style_download_sha256": build_final.digest(style),
        "official_style_bytes": "PASS", "anonymous_mode_and_metadata": "PASS",
        "private_identifier_scan": "PASS", "all_page_text_bounds": "PASS",
        "paper_scope_scan": "PASS: Markdown, LaTeX, tables, bibliography, PDF, and source bundle",
        "embedded_fonts": len(fonts), "undefined_references_and_overfull_boxes": 0,
        "manuscript_contract": contract,
        "original_numeric_value_inventory": "Preserved except explicitly approved editorial removals; not a substitute for contextual review",
        "approved_removed_numeric_tokens": removed_numbers,
        "approved_content_changes_sha256": build["approved_content_changes_sha256"],
        "preserved_original_files": build["preserved_original_files"],
        "private_form_responses": "Not supplied", "engine_executions": 0,
        "author_manual_review_and_final_approval": "Pending; no commit, push, or submission authorized",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--invitation", required=True, type=Path)
    parser.add_argument("--style", required=True, type=Path)
    args = parser.parse_args()
    result = verify(args.invitation, args.style)
    (ACADEMIC / "final/verification.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
