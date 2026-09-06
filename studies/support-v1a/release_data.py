#!/usr/bin/env python3
"""Package immutable scientific records without private operational files."""

import argparse
import gzip
import hashlib
import importlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

PRIVATE_ROOT_FILES = {"local.json", "coordinator.lock", "launcher.json", "supervisor.log", "STOP"}
SCIENTIFIC_ROOT_FILES = {"manifest.json", "protocol.json", "progress.json", "COMPLETE.json",
                         "analysis.json", "analysis-status.json", "RESULTS.md", "parent-import.json",
                         "parent-inventory.json", "preflight.json"}
SCIENTIFIC_DIRECTORIES = {"chunks", "parent-incomplete", "preflight"}
DATA_FILES = {"task.json", "attempt.json", "runs.jsonl", "complete.json", "raw.tsv", "collector.ss",
              "stdout.log", "stderr.log", "engine-error.tsv", "condition.txt", "segment.json"}
PRIVATE_PATTERNS = [
    rb"/Users/[^/\s\"']+", rb"/home/[^/\s\"']+",
    rb"\b(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})\b",
    rb"\bsha256:[a-f0-9]{64}\b", rb"\b[^\s\"']+\.local\b",
]


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def check_public(name, content, forbidden=()):
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name or not path.parts:
        raise ValueError("Unsafe archive path")
    if path.name in PRIVATE_ROOT_FILES or path.name in (".DS_Store", "Dockerfile"):
        raise ValueError(f"Private or unexpected file: {name}")
    if path.name not in SCIENTIFIC_ROOT_FILES | DATA_FILES:
        raise ValueError(f"Unclassified public file: {name}")
    if path.suffix == ".ss" and path.name != "collector.ss":
        raise ValueError(f"Only generated collector scripts belong in the data: {name}")
    content.decode("utf-8")
    if any(re.search(pattern, content, re.IGNORECASE) for pattern in PRIVATE_PATTERNS):
        raise ValueError(f"Private operational content found in {name}")
    if any(token.lower().encode() in content.lower() for token in forbidden):
        raise ValueError(f"Disallowed personal identifier found in {name}")


def public_files(root):
    result, omitted = [], []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("Refusing a symlink in study output")
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if len(relative.parts) == 1 and relative.name in PRIVATE_ROOT_FILES:
            omitted.append(relative.as_posix())
            continue
        if ((len(relative.parts) == 1 and relative.name not in SCIENTIFIC_ROOT_FILES)
                or (len(relative.parts) > 1 and relative.parts[0] not in SCIENTIFIC_DIRECTORIES)):
            raise ValueError(f"Unclassified study file: {relative}")
        result.append((relative.as_posix(), path))
    return result, omitted


def make_archive(root, label, destination, forbidden=()):
    files, omitted = public_files(root)
    original_hashes = {}
    with destination.open("xb") as output:
        with gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as zipped:
            with tarfile.open(fileobj=zipped, mode="w", format=tarfile.PAX_FORMAT) as archive:
                for relative, path in files:
                    content = path.read_bytes()
                    name = f"{label}/{relative}"
                    check_public(name, content, forbidden)
                    original_hashes[relative] = hashlib.sha256(content).hexdigest()
                    entry = tarfile.TarInfo(name)
                    entry.size, entry.mode, entry.mtime = len(content), 0o644, 0
                    entry.uid = entry.gid = 0
                    entry.uname = entry.gname = ""
                    archive.addfile(entry, io.BytesIO(content))
    if any(digest(root / name) != expected for name, expected in original_hashes.items()):
        raise ValueError("Source study changed during export")
    if destination.stat().st_size >= 50 * 1024 * 1024:
        raise ValueError("Archive exceeds the conservative 50 MiB Git file budget")
    return {"archive": destination.name, "sha256": digest(destination),
            "bytes": destination.stat().st_size, "files": len(files), "root": label,
            "omitted_operational_files": omitted,
            "scientific_files": original_hashes}


def unpack_archive(path, info, destination, forbidden=()):
    if digest(path) != info["sha256"] or path.stat().st_size != info["bytes"]:
        raise ValueError("Archive checksum or length mismatch")
    seen = {}
    with tarfile.open(path, "r:gz") as archive:
        for entry in archive:
            name = PurePosixPath(entry.name)
            if (not entry.isfile() or entry.uid != 0 or entry.gid != 0 or entry.uname or entry.gname
                    or entry.mtime != 0 or entry.mode != 0o644 or entry.pax_headers
                    or len(name.parts) < 2 or name.parts[0] != info["root"]):
                raise ValueError("Unexpected archive member or identifying metadata")
            content = archive.extractfile(entry).read()
            check_public(entry.name, content, forbidden)
            relative = PurePosixPath(*name.parts[1:]).as_posix()
            if relative in seen:
                raise ValueError("Duplicate archive member")
            seen[relative] = hashlib.sha256(content).hexdigest()
            target = destination.joinpath(*name.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(content)
    if seen != info["scientific_files"] or len(seen) != info["files"]:
        raise ValueError("Published file inventory mismatch")


def study_tools(path):
    sys.path.insert(0, str(path.resolve()))
    return importlib.import_module("collect"), importlib.import_module("analyze")


def verify_science(root, tools):
    collect, analysis = study_tools(tools)
    main = root / "main"
    manifest, p, data, _ = analysis.legacy.load_study(main)
    complete = read_json(main / "COMPLETE.json")
    analysis.verify_inheritance(main, manifest, complete)
    errors = [row for phase in data.values() for rows in phase.values() for row in rows if row["state"] == "*ERROR*"]
    if complete["total_runs"] != 969000 or len(errors) != 3:
        raise ValueError("Unexpected completed campaign or engine-error count")
    counts = {phase: sum(len(rows) for rows in problems.values()) for phase, problems in data.items()}
    del data
    parent_inventory = read_json(main / "parent-inventory.json")
    parent_files = {path.relative_to(root / "parent").as_posix(): digest(path)
                    for path in (root / "parent").rglob("*") if path.is_file()}
    if parent_files != {name: value for name, value in parent_inventory.items() if name not in PRIVATE_ROOT_FILES}:
        raise ValueError("Public parent differs from the original import inventory")
    secondary_counts = {}
    for label in ("parent", "pilot", "aborted-preflight"):
        directory = root / label
        m, config = read_json(directory / "manifest.json"), read_json(directory / "protocol.json")
        if digest(directory / "protocol.json") != m["protocol_sha256"]:
            raise ValueError("Secondary protocol hash mismatch")
        phases = config["pilot_phases"] if m["pilot"] else config["phases"]
        receipts, count = {}, 0
        for phase in phases:
            for task in collect.tasks_for(config, phase):
                chunk = collect.chunk_dir(directory, task)
                rows = collect.load_completed(chunk, task)
                if rows is not None:
                    count += len(rows)
                    receipts[(chunk.relative_to(directory) / "complete.json").as_posix()] = digest(chunk / "complete.json")
        secondary_counts[label] = count
        if label == "pilot":
            completed = read_json(directory / "COMPLETE.json")
            if (completed["receipts"] != receipts or completed["total_runs"] != count
                    or completed["manifest_sha256"] != digest(directory / "manifest.json") or count != 570):
                raise ValueError("Pilot completion inventory mismatch")
        elif count != 643250 or (directory / "COMPLETE.json").exists():
            raise ValueError("Interrupted collection was incorrectly labeled complete")
    previous = {name: digest(main / name) for name in ("analysis.json", "RESULTS.md")}
    subprocess.run([sys.executable, str(tools.resolve() / "analyze.py"), str(main.resolve())], check=True)
    if previous != {name: digest(main / name) for name in previous}:
        raise ValueError("Reanalysis did not reproduce the published results byte-for-byte")
    return {"admitted_main_observations": counts, "main_engine_errors": len(errors),
            "separately_preserved_observations_not_added_to_main": secondary_counts,
            "full_analysis_reproduced": previous, "parent_scientific_inventory_unchanged": True}


def build(args):
    if args.out.exists():
        raise ValueError("Refusing to overwrite an existing release")
    roots = {"main": args.main, "parent": args.parent, "pilot": args.pilot,
             "aborted-preflight": args.aborted_preflight}
    if len({path.resolve() for path in roots.values()}) != len(roots):
        raise ValueError("Study roots must be distinct")
    args.out.mkdir(parents=True)
    archives = []
    for label, root in roots.items():
        info = make_archive(root.resolve(), label, args.out / f"{label}.tar.gz", args.forbid)
        archives.append(info)
        print(f"Archived {label}: {info['files']} files, {info['bytes']} bytes", flush=True)
    index = {"schema_version": 1, "study_id": "support-v1a", "archives": archives,
             "data_policy": "Scientific files are byte-identical. Only listed operational root files are omitted. Archive owner names and timestamps are normalized. No original Metacat source is included.",
             "main_observations": 969000, "main_engine_errors": 3,
             "source_tools_commit": read_json(args.main / "manifest.json")["source"]["git_commit"]}
    write_json(args.out / "release.json", index)
    with tempfile.TemporaryDirectory(prefix="petacat-public-release-") as temporary:
        extracted = Path(temporary)
        for info in archives:
            unpack_archive(args.out / info["archive"], info, extracted, args.forbid)
        validation = verify_science(extracted, args.study_tools)
    write_json(args.out / "VALIDATION.json", {**validation, "release_sha256": digest(args.out / "release.json"),
               "export_tool_sha256": digest(Path(__file__)), "privacy_scan_passed": True})
    print(json.dumps(validation, indent=2), flush=True)


def verify(args):
    index = read_json(args.release / "release.json")
    validation = read_json(args.release / "VALIDATION.json")
    if digest(args.release / "release.json") != validation["release_sha256"]:
        raise ValueError("Release index checksum mismatch")
    if args.extract is not None and args.extract.exists():
        raise ValueError("Extraction destination must not already exist")
    with tempfile.TemporaryDirectory(prefix="petacat-release-check-") as temporary:
        destination = args.extract or Path(temporary)
        destination.mkdir(parents=True, exist_ok=True)
        seen = set()
        for info in index["archives"]:
            name = Path(info["archive"])
            if name.name != str(name) or info["root"] in seen:
                raise ValueError("Unsafe or duplicate archive assignment")
            seen.add(info["root"])
            unpack_archive(args.release / name, info, destination, args.forbid)
            print(f"Verified {name}: {info['files']} files", flush=True)
        if seen != {"main", "parent", "pilot", "aborted-preflight"}:
            raise ValueError("Incomplete release")
        if args.study_tools:
            result = verify_science(destination, args.study_tools)
            for key, value in result.items():
                if validation.get(key) != value:
                    raise ValueError("Scientific verification differs from release validation")
            print("PASS full scientific verification and byte-identical reanalysis", flush=True)
        else:
            print("PASS archive checksums, file inventories, safe extraction, and privacy scan", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("build")
    for option in ("main", "parent", "pilot", "aborted-preflight", "out", "study-tools"):
        p.add_argument(f"--{option}", type=Path, required=True)
    p.add_argument("--forbid", action="append", default=[])
    p = commands.add_parser("verify")
    p.add_argument("--release", type=Path, required=True)
    p.add_argument("--extract", type=Path)
    p.add_argument("--study-tools", type=Path)
    p.add_argument("--forbid", action="append", default=[])
    args = parser.parse_args()
    {"build": build, "verify": verify}[args.command](args)


if __name__ == "__main__":
    main()
