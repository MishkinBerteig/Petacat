#!/usr/bin/env python3
"""Combine the existing anonymous bundles into OpenReview's single attachment."""

import argparse
from io import BytesIO
import json
from pathlib import Path
import stat
from zipfile import ZIP_STORED, ZipFile, ZipInfo

import package_experiments as experiments


ACADEMIC = Path(__file__).resolve().parents[1]
INDEX = "UPLOAD-MANIFEST.json"
MEMBERS = ("README.md", "support-set-oracles-experiments.zip",
           "support-set-oracles-tmlr-source.zip")
OUTPUT = ACADEMIC / "support-set-oracles-submission-supplement.zip"


def write_bundle(path, files, members=MEMBERS):
    if set(files) != set(members):
        raise ValueError("Unexpected upload contents")
    records = {name: {"bytes": len(body), "sha256": experiments.digest(body)}
               for name, body in sorted(files.items())}
    entries = {**files, INDEX: experiments.encoded({"schema_version": 1, "files": records})}
    with ZipFile(path, "w", compression=ZIP_STORED) as archive:
        for name, body in sorted(entries.items()):
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o100644 << 16
            archive.writestr(info, body)


def verify_bundle(path, forbidden=(), members=MEMBERS):
    if path.stat().st_size >= experiments.LIMIT:
        raise ValueError("Supplement exceeds 100 MB")
    with ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != set(members) | {INDEX}:
            raise ValueError("Unexpected upload inventory")
        if archive.testzip() is not None or archive.comment:
            raise ValueError("Corrupt upload ZIP")
        records = json.loads(archive.read(INDEX))["files"]
        if set(records) != set(members):
            raise ValueError("Manifest inventory mismatch")
        for info in archive.infolist():
            experiments.safe_name(info.filename)
            if (not stat.S_ISREG(info.external_attr >> 16)
                    or info.date_time != (1980, 1, 1, 0, 0, 0) or info.extra or info.comment):
                raise ValueError("Unexpected upload metadata")
            body = archive.read(info)
            if info.filename != INDEX:
                if records[info.filename] != {"bytes": len(body), "sha256": experiments.digest(body)}:
                    raise ValueError("Upload content hash/length mismatch")
            if info.filename.endswith(".zip"):
                with ZipFile(BytesIO(body)) as inner:
                    if (inner.testzip() is not None or inner.comment
                            or len(inner.namelist()) != len(set(inner.namelist()))):
                        raise ValueError("Corrupt or duplicate inner ZIP entries")
                    for entry in inner.infolist():
                        experiments.safe_name(entry.filename)
                        if (not stat.S_ISREG(entry.external_attr >> 16) or entry.extra or entry.comment
                                or entry.date_time != (1980, 1, 1, 0, 0, 0)):
                            raise ValueError("Unexpected inner ZIP metadata")
                        if not entry.filename.endswith(".tar.gz"):
                            experiments.scan(entry.filename, inner.read(entry), forbidden)
            else:
                experiments.scan(info.filename, body, forbidden)
    return {"bytes": path.stat().st_size, "sha256": experiments.digest(path.read_bytes()),
            "files": records}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--forbid", action="append", default=[])
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    if args.verify:
        print(json.dumps(verify_bundle(args.verify, args.forbid), indent=2))
        return
    files = {name: (ACADEMIC / name).read_bytes() for name in MEMBERS if name != "README.md"}
    files["README.md"] = (ACADEMIC / "submission/SUPPLEMENT-README.md").read_bytes()
    experiments.verify_zip(ACADEMIC / "support-set-oracles-experiments.zip", forbidden=args.forbid)
    write_bundle(OUTPUT, files)
    result = verify_bundle(OUTPUT, args.forbid)
    result.update(pdf={"file": "support-set-oracles-tmlr.pdf",
                       "bytes": (ACADEMIC / "support-set-oracles-tmlr.pdf").stat().st_size,
                       "sha256": experiments.digest((ACADEMIC / "support-set-oracles-tmlr.pdf").read_bytes())},
                  engine_executions=0)
    (ACADEMIC / "submission-build.json").write_bytes(experiments.encoded(result))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
