#!/usr/bin/env python3
"""Verify the extracted review supplement using only saved observations."""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parent


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def run(*args, quiet=False):
    result = subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=quiet, text=quiet)
    if result.returncode:
        if quiet:
            print(result.stdout, end="")
            print(result.stderr, end="", file=sys.stderr)
        result.check_returncode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full-single-run", action="store_true")
    args = parser.parse_args()
    metadata = json.loads((ROOT / "SUPPLEMENT-MANIFEST.json").read_text())
    for name, record in metadata["files"].items():
        path = Path(name)
        if path.is_absolute() or ".." in path.parts or (ROOT / path).is_symlink():
            raise ValueError("Unsafe manifest path")
        if sha(ROOT / path) != record["sha256"]:
            raise ValueError(f"Changed package file: {name}")
    checked = 0
    for records in metadata["source_snapshots"].values():
        for name, record in records.items():
            if record["status"] == "byte-identical":
                if sha(ROOT / name) != record["expected_sha256"]:
                    raise ValueError(f"Frozen source mismatch: {name}")
                checked += 1
    print(f"PASS package inventory hashes and {checked} frozen-source comparisons", flush=True)
    audits = (
        ("audit_numbers.py", "number-audit.json"),
        ("audit_episodes.py", "episode-audit.json"),
        ("audit_support_study.py", "support-study-audit.json"),
        ("audit_episodic_study.py", "episodic-study-audit.json"),
        ("investigate_misc3.py", "investigations/misc3-episodic-audit.json"),
    )
    for script, output in audits:
        extra = ("--output", "academic/" + output) if script == "investigate_misc3.py" else ()
        run("academic/tools/" + script, *extra, quiet=True)
        if sha(ROOT / "academic" / output) != metadata["files"]["academic/" + output]["sha256"]:
            raise ValueError(f"Audit differs from saved report: {output}")
        print(f"PASS byte-identical {output}", flush=True)
    spec = importlib.util.spec_from_file_location("review_tables", ROOT / "academic/tools/convert_manuscript.py")
    converter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(converter)
    read = lambda p: json.loads((ROOT / p).read_text())
    converter.generate_tables(read("academic/number-audit.json"), read("academic/episode-audit.json"),
                              read("studies/episodic-v3/results/main/analysis.json"),
                              read("academic/investigations/misc3-episodic-audit.json"),
                              read("academic/support-study-audit.json"), read("academic/episodic-study-audit.json"))
    tables = [n for n in metadata["files"] if n.startswith("academic/generated/")]
    for name in tables:
        if sha(ROOT / name) != metadata["files"][name]["sha256"]:
            raise ValueError(f"Generated table changed: {name}")
    print(f"PASS {len(tables)} byte-identical generated tables; no Pandoc or TeX required", flush=True)
    run("studies/episodic-v3/study.py", "verify-export", "studies/episodic-v3/results/main")
    run("-m", "unittest", "discover", "-s", "academic/tests", "-p", "test_*.py")
    run("-m", "unittest", "discover", "-s", "Metacat/tests", "-p", "test_*.py")
    if args.full_single_run:
        run("studies/support-v1a/release_data.py", "verify", "--release", "studies/support-v1a/data",
            "--study-tools", "studies/support-v1a")
    print("PASS review verification; zero engine executions", flush=True)


if __name__ == "__main__":
    main()
