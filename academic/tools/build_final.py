#!/usr/bin/env python3
"""Build the separate restyled manuscript without replacing the earlier draft."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

from package_artifacts import write_zip
import package_submission as submission
import convert_manuscript as converter


ACADEMIC = Path(__file__).resolve().parents[1]
STEM = "support-set-oracles-final"
MEMBERS = ("README.md", STEM + "-source.zip", "support-set-oracles-experiments.zip")
TABLE_PATTERN = r"\\input\{((?:final/)?generated/[^}]+)\}"
REMOVED_DISCUSSION = re.compile(
    r"(?<!\w)(?:permutations?|hypergeometric|total[\s-]+variation|largest[\s-]+gap|"
    r"frequency[\s-]+(?:compar\w*|test\w*|reject\w*|match\w*)|"
    r"compar\w*\s+frequencies|distribution(?:al)?[\s-]+(?:compar\w*|match\w*|equal\w*|closeness)|"
    r"equal(?:ity of)?\s+(?:outcome\s+)?distributions|p[\s-]+values?|"
    r"Testing Closeness|sec:frequency|tab:misc3-frequencies|episodic-capped|Freq\.)", re.I)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def preservation_snapshot():
    names = ["manuscript.md", "support-set-oracles-tmlr.tex", "support-set-oracles-tmlr.pdf",
             "references.bib", "support-set-oracles-tmlr-source.zip",
             "support-set-oracles-analysis.zip", "support-set-oracles-experiments.zip",
             "support-set-oracles-submission-supplement.zip", "submission-build.json",
             "submission-readiness.json", "submission/abstract.txt", "number-audit.json",
             "episode-audit.json", "support-study-audit.json", "episodic-study-audit.json",
             "investigations/misc3-episodic-audit.json"]
    names += [str(p.relative_to(ACADEMIC)) for p in sorted((ACADEMIC / "generated").glob("*.tex"))]
    return {name: digest(ACADEMIC / name) for name in names}


def approved_content_changes():
    return json.loads((ACADEMIC / "final/approved-content-changes.json").read_text())


def manuscript_contract(old, new, approved=None):
    approved = approved or {}
    normalize_equation = lambda e: re.sub(r"\s+", "", e).rstrip(".,;")
    checks = {
        "references": lambda s: set(re.findall(r"@ref\d+", s)),
        "data_tables": lambda s: set(re.findall(TABLE_PATTERN, s)),
        "section_labels": lambda s: set(re.findall(r"\{#([^}]+)\}", s)),
        "display_equations": lambda s: sorted(normalize_equation(e)
                                              for e in re.findall(r"\$\$(.*?)\$\$", s, re.S)),
    }
    for name, extract in checks.items():
        expected = extract(old)
        if name in ("references", "data_tables", "section_labels"):
            for removed in approved.get(name + "_removed", []):
                expected.remove(removed)
            for previous, replacement in approved.get(name + "_replaced", {}).items():
                expected.remove(previous)
                expected.add(replacement)
        if name == "section_labels":
            expected.update(approved.get("section_labels_added", []))
        elif name == "display_equations":
            for equation in approved.get("display_equations_removed", []):
                expected.remove(normalize_equation(equation))
        if expected != extract(new):
            raise ValueError(f"Rewrite changed the {name} inventory")
    return {name: len(extract(new)) for name, extract in checks.items()}


def numeric_contract(old, new, approved=None):
    numbers = lambda s: set(re.findall(r"(?<![A-Za-z0-9])\d+(?:,\d{3})*(?:\.\d+)?", s))
    removed = numbers(old) - numbers(new)
    expected = set((approved or {}).get("removed_numeric_values", []))
    if removed != expected:
        raise ValueError(f"Unexpected numeric inventory changes: {sorted(removed ^ expected)}")
    return sorted(removed)


def manuscript_table_paths(source):
    paths = sorted(set(re.findall(TABLE_PATTERN, source)))
    if any(not p.startswith("final/generated/") or Path(p).name != p.removeprefix("final/generated/")
           for p in paths):
        raise ValueError("Final manuscript must use its own generated tables")
    return paths


def prepare_tables(source):
    destination = ACADEMIC / "final/generated"
    destination.mkdir(exist_ok=True)
    rewritten = {"single-check-table.tex", "single-input-table.tex", "misc3-count-table.tex"}
    for name in manuscript_table_paths(source):
        if Path(name).name not in rewritten:
            shutil.copyfile(ACADEMIC / "generated" / Path(name).name, ACADEMIC / name)
    support = json.loads((ACADEMIC / "support-study-audit.json").read_text())
    metrics = (("Observations", "runs"), ("100-run checks", "batches"),
               ("Outside draws (including errors)", "novel_draws"),
               ("Checks with outside draws", "novel_batches"),
               ("Checks missing a p50 member", "missing_batches"),
               ("Engine-error observations", "engine_error_runs"))
    rows = [[label, *(f'{support["comparisons"][p][key]:,}' for p in ("validation", "port"))]
            for label, key in metrics]
    converter.write_table("single-check-table.tex", ["Measure", "Reference validation", "Port"],
        rows, "@{}lrr@{}", "Versioned fresh-memory checks against 20,000 frozen construction runs per input. "
        "Counts pool 19 inputs for accounting, not to estimate a common outcome law. "
        "Errors are included in outside draws and also reported separately.",
        "tab:single-checks", keep_together=True, output_dir=destination)
    fields = ("states", "validation_novel", "validation_errors", "port_novel", "port_errors", "port_flag_batches")
    rows = [[converter.code(r["problem"]), *(str(r[k]) for k in fields)] for r in support["per_input"]]
    converter.write_table("single-input-table.tex",
        ["Input", "States", "Ref. new", "Ref. err.", "Port new", "Port err.", "Flag"],
        rows, "@{}lrrrrrr@{}", "Versioned single-run results. States counts outcomes in 20,000 construction runs. "
        "Reference validation uses 30,000 runs per input and the port 1,000; errors are included in new draws. "
        "Flag counts port 100-run checks with an outside draw or absent p50 member, out of ten checks per input.",
        "tab:single-inputs", output_dir=destination)
    misc3 = json.loads((ACADEMIC / "investigations/misc3-episodic-audit.json").read_text())
    converter.write_table("misc3-count-table.tex",
        ["Answer", "Freeze A", "Freeze B", "Ref. A", "Ref. B", "Port A", "Port B"],
        converter.misc3_rows(misc3), "@{}lrrrrrr@{}", "Complete \\texttt{misc3} selected-answer counts. "
        "Freeze A and B use 11 and seven construction episodes, respectively; reference validation uses "
        "1,000 episodes and the port check uses 100. Only \\texttt{kji}, \\texttt{kkjjii}, and "
        "\\texttt{kkkjjjiii} belong to the frozen supports.", "tab:misc3-counts", output_dir=destination)


def verify_references(pandoc, source, approved=None):
    def parse(path):
        entries = json.loads(subprocess.check_output(
            [pandoc, str(path), "--from=biblatex", "--to=csljson"], text=True))
        if len({entry["id"] for entry in entries}) != len(entries):
            raise ValueError("Duplicate bibliography key")
        return {entry["id"]: entry for entry in entries}
    original = parse(ACADEMIC / "references.bib")
    current = parse(ACADEMIC / "final/references.bib")
    cited = set(re.findall(r"@((?:ref)\d+)", source))
    for key, fields in (approved or {}).get("bibliography_csl_field_changes", {}).items():
        if key not in original or key not in cited:
            raise ValueError("Approved bibliography correction names an unknown or uncited entry")
        for field, change in fields.items():
            if field not in ("URL", "DOI", "issue") or set(change) != {"before", "after"}:
                raise ValueError("Invalid approved bibliography field correction")
            before = change["before"]
            if (before is None and field in original[key]) or original[key].get(field) != before:
                raise ValueError("Approved bibliography correction does not match the original")
            if change["after"] is None:
                original[key].pop(field, None)
            else:
                original[key][field] = change["after"]
    if set(current) != cited or any(current[key] != original.get(key) for key in current):
        raise ValueError("Final bibliography differs from cited entries and approved corrections")


def check_paper_scope(text):
    if match := REMOVED_DISCUSSION.search(text):
        raise ValueError(f"Removed discussion remains in paper: {match.group()}")


def build(args):
    before = preservation_snapshot()
    preservation = ACADEMIC / "final/preserved-draft.json"
    if preservation.exists():
        if json.loads(preservation.read_text()) != before:
            raise ValueError("Earlier draft or evidence changed since the rewrite began")
    else:
        preservation.write_text(json.dumps(before, indent=2, sort_keys=True) + "\n")
    old = (ACADEMIC / "manuscript.md").read_text()
    new = (ACADEMIC / (STEM + ".md")).read_text()
    approved = approved_content_changes()
    contract = manuscript_contract(old, new, approved)
    numeric_contract(old, new, approved)
    check_paper_scope(new)
    subprocess.run([sys.executable, str(ACADEMIC / "tools/convert_manuscript.py"),
                    "--pandoc", args.pandoc, "--source", STEM + ".md",
                    "--output", STEM + ".tex"], check=True)
    prepare_tables(new)
    verify_references(args.pandoc, new, approved)
    for name in manuscript_table_paths(new):
        check_paper_scope((ACADEMIC / name).read_text())
    check_paper_scope((ACADEMIC / "final/references.bib").read_text())
    subprocess.run([args.tectonic, "--keep-logs", "--keep-intermediates", STEM + ".tex"],
                   cwd=ACADEMIC, check=True)
    subprocess.run([args.pandoc, STEM + ".md", "--from=markdown+raw_tex", "--to=plain",
                    "--standalone", "--wrap=none", "--template=submission/abstract-template.txt",
                    "--output=final/abstract.txt"], cwd=ACADEMIC, check=True)
    names = [STEM + ext for ext in (".md", ".tex", ".bbl")]
    names += ["final/references.bib", "tmlr.sty", "tmlr.bst", "fancyhdr.sty", "tools/tmlr-template.tex"]
    names += manuscript_table_paths(new)
    files = [(ACADEMIC / name, name) for name in names]
    files += [(ACADEMIC / "final/SOURCE-README.md", "README.md"),
              (ACADEMIC / "tmlr-template/tmlr-style-file-main/LICENSE", "TMLR-TEMPLATE-LICENSE")]
    source = ACADEMIC / (STEM + "-source.zip")
    write_zip(source, files)
    contents = {name: (ACADEMIC / name).read_bytes() for name in MEMBERS if name != "README.md"}
    contents["README.md"] = (ACADEMIC / "final/SUPPLEMENT-README.md").read_bytes()
    supplement = ACADEMIC / (STEM + "-supplement.zip")
    submission.write_bundle(supplement, contents, members=MEMBERS)
    result = submission.verify_bundle(supplement, args.forbid, members=MEMBERS)
    if preservation_snapshot() != before:
        raise ValueError("Build changed the earlier draft or scientific tables/audits")
    pdf = ACADEMIC / (STEM + ".pdf")
    result.update(pdf={"file": pdf.name, "bytes": pdf.stat().st_size, "sha256": digest(pdf)},
                  markdown_sha256=digest(ACADEMIC / (STEM + ".md")),
                  preserved_original_files=len(before), manuscript_contract=contract,
                  approved_content_changes_sha256=digest(ACADEMIC / "final/approved-content-changes.json"),
                  bibliography_sha256=digest(ACADEMIC / "final/references.bib"),
                  engine_executions=0, final_human_approval="Pending")
    (ACADEMIC / "final/build.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pandoc", default="pandoc")
    parser.add_argument("--tectonic", default="tectonic")
    parser.add_argument("--forbid", action="append", default=[])
    build(parser.parse_args())


if __name__ == "__main__":
    main()
