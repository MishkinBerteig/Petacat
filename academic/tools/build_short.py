#!/usr/bin/env python3
"""Build and verify the separate, at-most-12-page anonymous submission."""

import argparse
import json
from pathlib import Path
import re
import subprocess
from zipfile import ZipFile

import build_final
import convert_manuscript
from package_artifacts import write_zip
import package_submission
from verify_final import Bounds, PRIVATE, output


ACADEMIC = Path(__file__).resolve().parents[1]
STATE = ACADEMIC / "short"
STEM = "support-set-oracles-12-page"
MEMBERS = ("README.md", STEM + "-source.zip", "support-set-oracles-experiments.zip")
MAX_MAIN_PAGES = 12
TABLE_WORDING = (
    ("answered complete episodes", "complete episodes with solutions"),
    ("entirely answerless episodes", "episodes with no solution"),
    ("answered validation episodes", "validation episodes with solutions"),
    ("No answer", "No solution"),
    ("selected-answer", "selected-solution"),
    ("shared answers", "shared solutions"),
    ("Answered &", "With solution &"),
    ("Answer &", "Solution &"),
)


def manuscript_table_paths(source):
    paths = sorted(set(re.findall(r"\\input\{([^}]+)\}", source)))
    if any(not p.startswith("short/generated/") or Path(p).name != p.removeprefix("short/generated/")
           for p in paths):
        raise ValueError("Regular-length manuscript must use its own generated tables")
    return paths


def table_contents():
    old = (ACADEMIC / "support-set-oracles-final.md").read_text()
    tables = {}
    for path in build_final.manuscript_table_paths(old):
        content = (ACADEMIC / path).read_text()
        for previous, replacement in TABLE_WORDING:
            content = content.replace(previous, replacement)
        tables["short/generated/" + Path(path).name] = content
    return tables


def prepare_tables():
    (STATE / "generated").mkdir(exist_ok=True)
    for path, content in table_contents().items():
        (ACADEMIC / path).write_text(content)


def preservation_snapshot():
    records = build_final.preservation_snapshot()
    paths = list(ACADEMIC.glob("support-set-oracles-final.*"))
    paths += list(ACADEMIC.glob("support-set-oracles-final-*.zip"))
    paths += [p for p in (ACADEMIC / "final").rglob("*")
              if p.is_file() and "__pycache__" not in p.parts]
    records.update({str(p.relative_to(ACADEMIC)): build_final.digest(p) for p in paths})
    return dict(sorted(records.items()))


def check_preservation():
    current = preservation_snapshot()
    path = STATE / "preserved-drafts.json"
    if path.exists():
        if current != json.loads(path.read_text()):
            raise ValueError("An earlier draft or evidence file changed")
    else:
        path.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n")
    return current


def main_page_count(pdf_text, maximum=MAX_MAIN_PAGES):
    pages = pdf_text.split("\f")
    reference_pages = [i for i, page in enumerate(pages)
                       if re.search(r"(?m)^References\s*$", page)]
    if len(reference_pages) != 1:
        raise ValueError("Expected one References heading on a fresh page")
    count = reference_pages[0]
    before = pages[count].split("References", 1)[0].strip()
    if before != "Under review as submission to TMLR":
        raise ValueError("References must begin a new page")
    if not 1 <= count <= maximum:
        raise ValueError(f"Main content occupies {count} pages; maximum is {maximum}")
    return count


def summary_rows():
    analysis = json.loads((ACADEMIC.parent / "studies/episodic-v3/results/main/analysis.json").read_text())
    problem = next(r for r in analysis["results"] if r["problem"] == "misc3")
    rows = []
    for name, label in (("best_a", "Quality"), ("best_b", "Preference")):
        definition = problem["definitions"][name]
        validation, port = definition["validation"], definition["port_membership"]
        freeze = problem["construction"]["frozen"][name]["at_episode"]
        rows.append(f'| {label} (`{name}`) | {freeze} | '
                    f'{validation["outside_occurrences"]} / {validation["N"]:,} | '
                    f'{validation["upper_bound"]:.6f} | '
                    f'{port["outside_occurrences"]} / {port["N"]:,} |')
    return rows


def manuscript_contract(source):
    old = (ACADEMIC / "support-set-oracles-final.md").read_text()
    extract = lambda pattern, text: re.findall(pattern, text, re.S)
    references = lambda text: set(extract(r"@ref\d+", text))
    equations = lambda text: sorted(re.sub(r"\s+", "", eq).rstrip(".,;")
                                    for eq in extract(r"\$\$(.*?)\$\$", text))
    tables = manuscript_table_paths(source)
    if references(source) != references(old):
        raise ValueError("Cited reference inventory changed")
    if equations(source) != equations(old):
        raise ValueError("Formal equation inventory changed")
    expected_tables = table_contents()
    if tables != sorted(expected_tables):
        raise ValueError("Audited table inventory changed")
    for path, content in expected_tables.items():
        if (ACADEMIC / path).read_text() != content:
            raise ValueError("Audited table content changed beyond approved terminology")
    labels = extract(r"\{#([^}]+)\}", source)
    if len(labels) != len(set(labels)):
        raise ValueError("Duplicate section/table labels")
    source_rows = {re.sub(r"[ \t]+", " ", line.strip()) for line in source.splitlines()}
    for row in summary_rows():
        if row not in source_rows:
            raise ValueError("misc3 summary differs from saved study data")
    main, appendices = source.split(r"\appendix", 1)
    if not main.rstrip().endswith(r"\clearpage"):
        raise ValueError("Appendices must start on a fresh page")
    if not main.split(r"\bibliography", 1)[0].rstrip().endswith(r"\clearpage"):
        raise ValueError("References must start on a fresh page")
    headings = [line for line in main.splitlines() if line.startswith("# ")]
    if headings[-2] != "# Potential Application of the Process {#sec:applications}":
        raise ValueError("Potential applications must remain penultimate")
    appendix_heads = list(re.finditer(r"^# .+", appendices, re.M))
    if len(appendix_heads) != 10:
        raise ValueError("Expected ten evidence appendices")
    for heading in appendix_heads[1:]:
        if not appendices[:heading.start()].rstrip().endswith(r"\clearpage"):
            raise ValueError("Every appendix must start on a fresh page")
    build_final.check_paper_scope(source)
    return {"references": len(references(source)), "audited_tables": len(tables),
            "display_equations": len(equations(source)), "appendices": len(appendix_heads),
            "misc3_summary": "Matches saved study", "main_source_word_count": len(main.split())}


def verify_pdf(invitation, style):
    pdf = ACADEMIC / (STEM + ".pdf")
    info = dict(line.split(":", 1) for line in output("pdfinfo", str(pdf)).splitlines() if ":" in line)
    info = {key: value.strip() for key, value in info.items()}
    text = output("pdftotext", "-layout", str(pdf), "-")
    count = main_page_count(text)
    if not info["Page size"].startswith("612 x 792") or info.get("Author"):
        raise ValueError("Unexpected page format or author metadata")
    if "Anonymous authors" not in text.split("\f")[0]:
        raise ValueError("Anonymous author heading missing")
    if text.count("Under review as submission to TMLR") != int(info["Pages"]):
        raise ValueError("Submission-mode header missing")
    if PRIVATE.search(text + str(info) + output("pdfinfo", "-url", str(pdf))):
        raise ValueError("Private identifier found")
    tex = (ACADEMIC / (STEM + ".tex")).read_text()
    if r"\usepackage{tmlr}" not in tex or re.search(r"\\usepackage\[[^]]*\]\{tmlr\}", tex):
        raise ValueError("Not in official anonymous submission mode")
    if tex.index(r"\bibliography{final/references}") > tex.index(r"\appendix"):
        raise ValueError("Appendices precede references")
    bbl = (ACADEMIC / (STEM + ".bbl")).read_text()
    if bbl.count(r"\bibitem") != 34:
        raise ValueError("Incorrect bibliography inventory")
    for content in (text, tex, bbl):
        build_final.check_paper_scope(content)
    log = (ACADEMIC / (STEM + ".log")).read_text(errors="replace")
    if re.search(r"Overfull|undefined references|Citation .+ undefined|Reference .+ undefined|Missing character", log):
        raise ValueError("Unresolved LaTeX diagnostics")
    bounds = Bounds()
    bounds.feed(output("pdftotext", "-bbox", str(pdf), "-"))
    if bounds.errors or bounds.pages != int(info["Pages"]):
        raise ValueError(f"PDF text bounds failure: {bounds.errors}")
    fonts = output("pdffonts", str(pdf)).splitlines()[2:]
    if not fonts or not all(re.search(r"\s+yes\s+(?:yes|no)\s+(?:yes|no)\s+\d+\s+\d+\s*$", f) for f in fonts):
        raise ValueError("Unembedded font")
    with ZipFile(style) as archive:
        for name in ("tmlr.sty", "tmlr.bst", "fancyhdr.sty"):
            if (ACADEMIC / name).read_bytes() != archive.read("tmlr-style-file-main/" + name):
                raise ValueError("Official style bytes changed")
    with ZipFile(ACADEMIC / "support-set-oracles-final-source.zip") as original:
        template = "tools/tmlr-template.tex"
        if (ACADEMIC / template).read_bytes() != original.read(template):
            raise ValueError("Template differs from the preserved longer draft")
    form = json.loads(invitation.read_text())["invitations"][0]
    if form["id"] != "TMLR/-/Submission":
        raise ValueError("Incorrect submission form")
    fields = form["edit"]["note"]["content"]
    category = "Regular submission (no more than 12 pages of main content)"
    if category not in fields["submission_length"]["value"]["param"]["enum"]:
        raise ValueError("Regular-submission option changed")
    abstract = (STATE / "abstract.txt").read_text().strip()
    if len(info["Title"]) > fields["title"]["value"]["param"]["maxLength"]:
        raise ValueError("Title exceeds form limit")
    if len(abstract) > fields["abstract"]["value"]["param"]["maxLength"]:
        raise ValueError("Abstract exceeds form limit")
    if pdf.stat().st_size >= fields["pdf"]["value"]["param"]["maxSize"] * 1_000_000:
        raise ValueError("PDF exceeds form limit")
    return {"main_text_pages": count, "maximum_main_text_pages": MAX_MAIN_PAGES,
            "pdf_pages": int(info["Pages"]), "submission_type": category,
            "title": info["Title"], "abstract_words": len(abstract.split()),
            "abstract_characters": len(abstract), "embedded_fonts": len(fonts),
            "anonymous_mode_metadata_and_identifier_scan": "PASS", "page_text_bounds": "PASS",
            "official_style_bytes": "PASS", "unchanged_conversion_template": "PASS",
            "overfull_boxes_or_undefined_references": 0,
            "form_sha256": build_final.digest(invitation), "style_sha256": build_final.digest(style)}


def build(args):
    STATE.mkdir(exist_ok=True)
    before = check_preservation()
    source = (ACADEMIC / (STEM + ".md")).read_text()
    prepare_tables()
    contract = manuscript_contract(source)
    build_final.verify_references(args.pandoc, source, build_final.approved_content_changes())
    convert_manuscript.convert_source(args.pandoc, ACADEMIC / (STEM + ".md"),
                                     ACADEMIC / (STEM + ".tex"))
    subprocess.run([args.tectonic, "--keep-logs", "--keep-intermediates", STEM + ".tex"],
                   cwd=ACADEMIC, check=True)
    subprocess.run([args.pandoc, STEM + ".md", "--from=markdown+raw_tex", "--to=plain",
                    "--standalone", "--wrap=none", "--template=submission/abstract-template.txt",
                    "--output=short/abstract.txt"], cwd=ACADEMIC, check=True)
    result = verify_pdf(args.invitation, args.style)
    names = [STEM + ext for ext in (".md", ".tex", ".bbl")]
    names += ["final/references.bib", "tmlr.sty", "tmlr.bst", "fancyhdr.sty", "tools/tmlr-template.tex"]
    names += manuscript_table_paths(source)
    files = [(ACADEMIC / name, name) for name in names]
    files += [(STATE / "SOURCE-README.md", "README.md"),
              (ACADEMIC / "tmlr-template/tmlr-style-file-main/LICENSE", "TMLR-TEMPLATE-LICENSE")]
    for path, name in files:
        if path.suffix in (".md", ".tex", ".bib", ".bbl"):
            build_final.check_paper_scope(path.read_text())
    source_zip = ACADEMIC / (STEM + "-source.zip")
    write_zip(source_zip, files)
    with ZipFile(source_zip) as archive:
        if set(archive.namelist()) != {name for _, name in files}:
            raise ValueError("Unexpected source bundle inventory")
        for path, name in files:
            if archive.read(name) != path.read_bytes():
                raise ValueError("Source bundle differs from current manuscript files")
    contents = {name: (ACADEMIC / name).read_bytes() for name in MEMBERS if name != "README.md"}
    contents["README.md"] = (STATE / "SUPPLEMENT-README.md").read_bytes()
    supplement = ACADEMIC / (STEM + "-supplement.zip")
    package_submission.write_bundle(supplement, contents, members=MEMBERS)
    package = package_submission.verify_bundle(supplement, ("mishkin", "berteig", "m3u512gb", "10.0.0.12"),
                                                members=MEMBERS)
    fields = json.loads(args.invitation.read_text())["invitations"][0]["edit"]["note"]["content"]
    if package["bytes"] >= fields["supplementary_material"]["value"]["param"]["maxSize"] * 1_000_000:
        raise ValueError("Supplement exceeds current form limit")
    if before != preservation_snapshot():
        raise ValueError("Build changed a preserved file")
    pdf = ACADEMIC / (STEM + ".pdf")
    result.update(manuscript_contract=contract, preserved_files=len(before),
                  pdf={"file": pdf.name, "bytes": pdf.stat().st_size, "sha256": build_final.digest(pdf)},
                  markdown_sha256=build_final.digest(ACADEMIC / (STEM + ".md")),
                  bibliography_sha256=build_final.digest(ACADEMIC / "final/references.bib"),
                  supplement={"file": supplement.name, **package},
                  engine_executions=0, beyond_pdf="Leave empty",
                  private_form_responses="Not supplied",
                  final_human_approval="Pending; no commit, push, or submission authorized")
    (STATE / "verification.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pandoc", default="pandoc")
    parser.add_argument("--tectonic", default="tectonic")
    parser.add_argument("--invitation", required=True, type=Path)
    parser.add_argument("--style", required=True, type=Path)
    build(parser.parse_args())


if __name__ == "__main__":
    main()
