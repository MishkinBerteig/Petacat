#!/usr/bin/env python3
"""Build and check the review supplement without changing frozen scientific files."""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo


ROOT = Path(__file__).resolve().parents[2]
ACADEMIC = ROOT / "academic"
INDEX = "SUPPLEMENT-MANIFEST.json"
LIMIT = 100_000_000
SOURCE_MANIFESTS = ("academic/data/support-v1a/manifest.json",
                    "studies/episodic-v3/results/main/manifest.json")
OMIT_SOURCE = {"Metacat/gui-validation.png": "GUI screenshot is not needed for analysis or reconstruction."}
REVIEW_DOCS = {"Metacat/README.md", "studies/support-v1a/README.md"}
PATTERNS = {
    "author repository URL": rb"(?:github\.com[/:]|git@github\.com:)[^\s/]+/[Pp]etacat\b",
    "home directory": rb"/(?:Users|home)/[A-Za-z0-9][A-Za-z0-9_.-]*(?:/|[\s\"'])",
    "private IPv4": rb"\b(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})\b",
    "local hostname": rb"\b(?!(?:threading|self)\.local\b)[a-z0-9-]+\.local\b",
    "container image identifier": rb"\bsha256:[a-f0-9]{64}\b",
}
# These frozen tests intentionally contain synthetic private-data rejection examples.
SYNTHETIC_FIXTURES = {
    "studies/support-v1a/test_release.py": {"home directory", "private IPv4", "local hostname"},
    "studies/episodic-v3/test_study.py": {"home directory"},
    "academic/tests/test_supplement.py": {"home directory", "private IPv4", "author repository URL"},
}


def digest(content):
    return hashlib.sha256(content).hexdigest()


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def safe_name(name):
    path = PurePosixPath(name)
    if (not name or path.is_absolute() or ".." in path.parts or "\\" in name
            or path.as_posix() != name or any(p.startswith(".") for p in path.parts)):
        raise ValueError("Unsafe or hidden supplement path")
    return path


def scan(name, content, forbidden=()):
    safe_name(name)
    if any(token.encode().lower() in content.lower() for token in forbidden):
        raise ValueError(f"Author-supplied private token found in {name}")
    for label, pattern in PATTERNS.items():
        if re.search(pattern, content, re.I) and label not in SYNTHETIC_FIXTURES.get(name, set()):
            raise ValueError(f"Possible {label} in {name}")


def load_release_tool(root):
    spec = importlib.util.spec_from_file_location("review_release", root / "studies/support-v1a/release_data.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def review_metacat_readme(content):
    text = content.decode()
    start = text.index("## 2. Download This Bundle")
    end = text.index("Check your location:", start)
    replacement = (
        "## 2. Open the Review Bundle\n\n"
        "Extract the supplied review ZIP into a new folder. Open a terminal in\n"
        "that folder, then enter its `Metacat` subfolder:\n\n"
        "```sh\ncd Metacat\n```\n\n"
        "Do not clone a public repository for this review copy. All reconstruction\n"
        "patches and their manifest are already included. The original upstream\n"
        "archive is downloaded separately in the next step.\n\n"
    )
    return (text[:start] + replacement + text[end:]).encode()


def review_license(content):
    text, changes = re.subn(r"(?m)^Copyright \(c\) 2026 .+$",
                           "Copyright (c) 2026 Anonymous author (identity withheld for double-blind review)",
                           content.decode())
    if changes != 1:
        raise ValueError("Expected exactly one author copyright line")
    notice = (
        "Review-copy notice: only the copyright holder's displayed name is\n"
        "temporarily anonymized. The holder is not reassigned and the MIT terms\n"
        "and upstream attribution are unchanged. Restore the original named\n"
        "notice for a nonanonymous release. The original file hash is recorded\n"
        "in SUPPLEMENT-MANIFEST.json; the repository original is unchanged.\n\n"
    )
    return (notice + text).encode()


def collect_files():
    files, provenance, snapshots = {}, {}, {}

    def add(name, content=None, source=None, reason=None):
        safe_name(name)
        path = ROOT / (source or name)
        if path.is_symlink():
            raise ValueError(f"Source symlink: {name}")
        original = path.read_bytes()
        body = original if content is None else content
        if name in files and files[name] != body:
            raise ValueError(f"Conflicting package content: {name}")
        files[name] = body
        provenance[name] = {"source_path": source or name, "source_sha256": digest(original),
                            "policy": reason or "byte-identical"}

    for manifest_name in SOURCE_MANIFESTS:
        manifest = json.loads((ROOT / manifest_name).read_text())
        records = {}
        for name, expected in manifest["source"]["files"].items():
            if any(p.startswith(".") for p in PurePosixPath(name).parts):
                records[name] = {"expected_sha256": expected, "status": "omitted",
                                 "reason": "Repository ignore configuration; not scientific or executable content."}
            elif name in OMIT_SOURCE or name in REVIEW_DOCS:
                records[name] = {"expected_sha256": expected, "status": "review-doc" if name in REVIEW_DOCS else "omitted",
                                 "reason": "Review-specific instructions replace repository navigation." if name in REVIEW_DOCS else OMIT_SOURCE[name]}
            else:
                add(name)
                if digest(files[name]) != expected:
                    raise ValueError(f"Frozen source mismatch: {name}")
                records[name] = {"expected_sha256": expected, "status": "byte-identical"}
        snapshots[manifest_name] = records

    add("Metacat/README.md", review_metacat_readme((ROOT / "Metacat/README.md").read_bytes()),
        reason="Only repository-download instructions replaced; dependency and GUI/headless instructions retained.")
    add("studies/support-v1a/README.md", source="academic/supplement/SUPPORT-README.md",
        reason="Review-specific analysis instructions, not the historical sampled documentation.")
    add("LICENSE.md", review_license((ROOT / "LICENSE.md").read_bytes()),
        reason="Copyright holder display name anonymized for review; MIT terms and upstream attribution unchanged.")
    for name in ("README.md", "REPRODUCE.md", "verify.py"):
        add(name, source="academic/supplement/" + name, reason="Review-bundle entry point.")
    academic_names = (
        "ANALYSIS-README.md", "data/README.md", "data/reference-single-runs.json",
        "data/vs-metacat-pre-rc-a.json", "data/vs-metacat.json", "data/vs-metacat-mlx.json",
        "number-audit.json", "episode-audit.json", "support-study-audit.json", "episodic-study-audit.json",
        "investigations/MISC3-EPISODIC.md", "investigations/misc3-episodic-audit.json",
        "tools/audit_numbers.py", "tools/audit_episodes.py", "tools/audit_support_study.py",
        "tools/audit_episodic_study.py", "tools/investigate_misc3.py", "tools/convert_manuscript.py",
        "tools/package_experiments.py",
    )
    for name in academic_names:
        add("academic/" + name)
    for path in sorted((ACADEMIC / "tests").glob("test_*.py")):
        add(path.relative_to(ROOT).as_posix())
    for directory in ("academic/data/support-v1a", "studies/episodic-v3/results/main",
                      "studies/episodic-v3/results/preflight-01", "studies/episodic-v2/results/pilot-02"):
        for path in sorted((ROOT / directory).iterdir()):
            if path.is_file() and path.suffix in (".json", ".csv", ".md"):
                add(path.relative_to(ROOT).as_posix())
    for path in sorted((ACADEMIC / "generated").glob("*.tex")):
        add(path.relative_to(ROOT).as_posix())
    for name in ("release_data.py", "test_release.py"):
        add("studies/support-v1a/" + name)
    for path in sorted((ROOT / "studies/support-v1a/data").iterdir()):
        if path.is_file() and (path.suffix in (".json", ".md") or path.name.endswith(".tar.gz")):
            add(path.relative_to(ROOT).as_posix())
    metadata = {
        "schema_version": 1,
        "scope": "Saved scientific evidence, frozen source, reconstruction patches, and analysis; no fresh engine results.",
        "source_snapshots": snapshots,
        "exclusions": [
            "Original upstream Metacat source and third-party dependency archives/binaries; obtain from documented upstream links.",
            "Full private episodic attempt archive, coordinator logs, host configuration, and operational receipts. Public episode selections and winner descriptions are included; original receipt hashes remain evidence locators, not bundled raw files.",
            "Unrecorded historical episodic reference and historical sampled builds: unavailable, not reconstructed or fabricated.",
            "Application UI, database/deployment infrastructure, unrelated measurements, agent instructions, Git history, and local environments.",
            "Manuscript build files are supplied separately in the LaTeX source ZIP; this supplement includes every generated data table and its generator.",
        ],
        "anonymity_boundary": "Direct repository links and local identifiers are excluded. Immutable implementation labels, commit/file hashes, and third-party attribution remain; no claim of resistance to deliberate external fingerprinting.",
        "synthetic_privacy_fixtures": {name: sorted(labels) for name, labels in SYNTHETIC_FIXTURES.items()},
        "files": {name: {"sha256": digest(body), "bytes": len(body), **provenance[name]}
                  for name, body in sorted(files.items())},
    }
    return files, metadata


def verify_zip(path, destination=None, forbidden=()):
    with ZipFile(path) as archive:
        infos = archive.infolist()
        names = [i.filename for i in infos]
        if len(names) != len(set(names)) or INDEX not in names or archive.testzip() is not None:
            raise ValueError("Duplicate/missing entries or corrupt ZIP")
        for entry in infos:
            safe_name(entry.filename)
            if (entry.is_dir() or not stat.S_ISREG(entry.external_attr >> 16)
                    or entry.date_time != (1980, 1, 1, 0, 0, 0) or entry.extra or entry.comment):
                raise ValueError("Unexpected ZIP metadata")
        metadata = json.loads(archive.read(INDEX))
        if set(names) != set(metadata["files"]) | {INDEX}:
            raise ValueError("Manifest inventory differs from ZIP")
        for name in names:
            body = archive.read(name)
            if name != INDEX:
                record = metadata["files"][name]
                if record["sha256"] != digest(body) or record["bytes"] != len(body):
                    raise ValueError(f"Content hash/length mismatch: {name}")
            if not name.endswith(".tar.gz"):
                scan(name, body, forbidden)
        if path.stat().st_size >= LIMIT:
            raise ValueError("Supplement exceeds 100 MB")
        if destination is not None:
            if destination.exists() or destination.is_symlink():
                raise ValueError("Refusing to overwrite extraction destination")
            destination.mkdir(parents=True)
            for name in names:
                target = destination.joinpath(*safe_name(name).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(name))
                target.chmod(0o644)
    return {"bytes": path.stat().st_size, "files": len(names), "sha256": digest(path.read_bytes())}


def build(output, forbidden):
    files, metadata = collect_files()
    for name, body in files.items():
        if not name.endswith(".tar.gz"):
            scan(name, body, forbidden)
    files[INDEX] = encoded(metadata)
    scan(INDEX, files[INDEX], forbidden)
    with ZipFile(output, "w") as archive:
        for name, body in sorted(files.items()):
            entry = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.compress_type = ZIP_STORED if name.endswith(".tar.gz") else ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, body)
    result = verify_zip(output, forbidden=forbidden)
    release = load_release_tool(ROOT)
    index = release.read_json(ROOT / "studies/support-v1a/data/release.json")
    with tempfile.TemporaryDirectory(prefix="review-nested-check-") as temporary:
        for info in index["archives"]:
            release.unpack_archive(ROOT / "studies/support-v1a/data" / info["archive"],
                                   info, Path(temporary), forbidden)
    result.update(nested_single_run_archives_verified=4,
                  unchanged_scientific_files=True, engine_executions=0)
    (ACADEMIC / "supplement-build.json").write_bytes(encoded(result))
    print(json.dumps(result, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ACADEMIC / "support-set-oracles-experiments.zip")
    parser.add_argument("--verify", type=Path)
    parser.add_argument("--extract", type=Path)
    parser.add_argument("--forbid", action="append", default=[])
    args = parser.parse_args()
    if args.verify:
        print(json.dumps(verify_zip(args.verify, args.extract, args.forbid), indent=2))
    elif args.extract:
        parser.error("--extract requires --verify")
    else:
        build(args.output, args.forbid)


if __name__ == "__main__":
    main()
