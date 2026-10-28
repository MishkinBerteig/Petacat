"""Reading and writing trace files (spec §3): one JSON object per line, gzip optional."""

from __future__ import annotations

import gzip
import io
import json
from pathlib import Path
from typing import Any, Iterator

FORMAT = 1


class TraceWriter:
    """Writes records compactly.  Gzip output carries no timestamp, so equal records
    give byte-identical files (Guard 2)."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        raw = open(self.path, "wb")
        if self.path.suffix == ".gz":
            self._raw = raw
            self._fh: Any = io.TextIOWrapper(
                gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0),
                encoding="utf-8",
                newline="\n",
            )
        else:
            self._raw = None
            self._fh = io.TextIOWrapper(raw, encoding="utf-8", newline="\n")

    def write(self, record: dict[str, Any]) -> None:
        self._fh.write(json.dumps(record, separators=(",", ":"), ensure_ascii=False))
        self._fh.write("\n")

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            if self._raw is not None:
                self._raw.close()
            self._fh = None

    def __enter__(self) -> "TraceWriter":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def read_records(path: str | Path) -> Iterator[dict[str, Any]]:
    path = Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)
