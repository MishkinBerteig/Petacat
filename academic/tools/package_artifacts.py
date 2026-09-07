#!/usr/bin/env python3
"""Create explicit, portable LaTeX and arithmetic-analysis ZIP bundles."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


ACADEMIC = Path(__file__).resolve().parents[1]


def write_zip(path, files):
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        for source, destination in files:
            info = ZipInfo(destination, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, source.read_bytes())
    print(f"Created {path.name}: {path.stat().st_size:,} bytes, {len(files)} files")


def main():
    source_names = ["SOURCE-README.md", "support-set-oracles-tmlr.tex", "references.bib",
                    "support-set-oracles-tmlr.bbl", "tmlr.sty", "tmlr.bst", "fancyhdr.sty",
                    "generated/reference-table.tex", "generated/cycle-table.tex",
                    "generated/input-table.tex", "generated/episode-table.tex"]
    source_files = [(ACADEMIC / name, name) for name in source_names]
    source_files.append((ACADEMIC / "tmlr-template/tmlr-style-file-main/LICENSE", "TMLR-TEMPLATE-LICENSE"))
    write_zip(ACADEMIC / "support-set-oracles-tmlr-source.zip", source_files)
    analysis_names = ["ANALYSIS-README.md", "data/README.md", "data/reference-single-runs.json",
                      "data/vs-metacat-pre-rc-a.json", "data/vs-metacat.json", "data/vs-metacat-mlx.json",
                      "number-audit.json", "tools/audit_numbers.py", "tests/test_audit_numbers.py",
                      "episode-audit.json", "tools/audit_episodes.py", "tests/test_audit_episodes.py"]
    write_zip(ACADEMIC / "support-set-oracles-analysis.zip",
              [(ACADEMIC / name, "academic/" + name) for name in analysis_names])


if __name__ == "__main__":
    main()
