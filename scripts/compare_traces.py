#!/usr/bin/env python3
"""Compare a Metacat decision trace with a Petacat replay trace (lockstep harness).

Implements ``meta-peta-trace-idea.md`` section 3 (trace format), 7 (comparison rules),
8 (snapshots), 9 (registry) and 10.4 (metrics).  ``tests/lockstep/DECISIONS.md``
overrides the spec where they differ; the key point is that pairing is done by the
Petacat replay RNG at run time.  Every Petacat ``decision`` record carries ``pair``:
the 0-based index into the Metacat trace's ``decision`` records (file order), or
``null`` for a surplus call.  This module never re-pairs.  It computes every check
class of section 7.3 from those pairs, finds Metacat records that were never paired,
handles the ``fatal`` record, compares ``end`` records and compares snapshots by ``u``.

Usage::

    compare_traces.py METACAT PETACAT [--json out.json] [--registry path]

Python standard library only (3.11+ for ``tomllib``).
"""

from __future__ import annotations

import argparse
import ast
import gzip
import io
import json
import math
import re
import sys
import tomllib
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REGISTRY = REPO_ROOT / "tests" / "lockstep" / "known_divergences.toml"

FATAL_CLASSES = {"unit", "missing-pick"}
WARNING_CLASSES = {"order"}


# --------------------------------------------------------------------------- reading


def open_text(path: str | Path) -> io.TextIOBase:
    """Open a ``.jsonl`` or ``.jsonl.gz`` file (detected by magic bytes) as text."""
    path = Path(path)
    with open(path, "rb") as fh:
        magic = fh.read(2)
    if magic == b"\x1f\x8b":
        return io.TextIOWrapper(gzip.open(path, "rb"), encoding="utf-8")
    return open(path, "r", encoding="utf-8")


def read_records(path: str | Path) -> list[dict]:
    out = []
    with open_text(path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


@dataclass
class Trace:
    path: str
    records: list[dict]
    header: dict = field(default_factory=dict)
    decisions: list[dict] = field(default_factory=list)  # file order
    decision_pos: list[int] = field(default_factory=list)  # index into records
    snapshots: dict[Any, dict] = field(default_factory=dict)  # u -> snapshot
    snapshot_order: list[Any] = field(default_factory=list)
    end: dict | None = None
    fatal: dict | None = None
    fatal_pos: int | None = None

    @classmethod
    def load(cls, path: str | Path) -> "Trace":
        return cls.from_records(read_records(path), str(path))

    @classmethod
    def from_records(cls, records: Iterable[dict], path: str = "<memory>") -> "Trace":
        tr = cls(path=path, records=list(records))
        for i, rec in enumerate(tr.records):
            t = rec.get("t")
            if t == "header":
                tr.header = rec
            elif t == "decision":
                tr.decisions.append(rec)
                tr.decision_pos.append(i)
            elif t == "snapshot":
                u = rec.get("u")
                if u not in tr.snapshots:
                    tr.snapshot_order.append(u)
                tr.snapshots[u] = rec
            elif t == "end":
                tr.end = rec
            elif t == "fatal" and tr.fatal is None:
                tr.fatal = rec
                tr.fatal_pos = i
        return tr


# --------------------------------------------------------------------------- numbers


def close(a: Any, b: Any, rel_tol: float, abs_tol: float) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, rel_tol=rel_tol, abs_tol=abs_tol)
    return a == b


# --------------------------------------------------------------------------- registry


@dataclass
class Divergence:
    id: str
    cause: str
    match: dict
    effect: str
    note: str
    name: str = ""


class Registry:
    """Known divergences (spec 9.1); matching rules are documented in the TOML file."""

    def __init__(self, entries: list[Divergence] | None = None):
        self.entries = entries or []
        self._func_cache: dict[str, list[tuple[int, int, str]]] = {}

    @classmethod
    def load(cls, path: str | Path | None = DEFAULT_REGISTRY) -> "Registry":
        if path is None or not Path(path).exists():
            return cls([])
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
        entries = [
            Divergence(
                id=d["id"],
                cause=d.get("cause", ""),
                match=dict(d.get("match", {})),
                effect=d.get("effect", "skip"),
                note=d.get("note", ""),
                name=d.get("name", ""),
            )
            for d in data.get("divergence", [])
        ]
        return cls(entries)

    # -- site resolution -------------------------------------------------------

    def _functions(self, rel: str) -> list[tuple[int, int, str]]:
        if rel not in self._func_cache:
            spans: list[tuple[int, int, str]] = []
            p = REPO_ROOT / rel
            try:
                tree = ast.parse(p.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        spans.append((node.lineno, node.end_lineno or node.lineno, node.name))
            except (OSError, SyntaxError):
                pass
            self._func_cache[rel] = spans
        return self._func_cache[rel]

    def resolve_site(self, site: str | None) -> dict:
        """Parse a Petacat ``site`` into ``file`` / ``line`` / ``function`` / ``codelet``."""
        info: dict = {"raw": site or ""}
        if not site:
            return info
        m = re.match(r"^<codelet:([^>]+)>(?::(\d+))?$", site)
        if m:
            info["codelet"] = m.group(1)
            if m.group(2):
                info["line"] = int(m.group(2))
            return info
        m = re.match(r"^(.+?):(\d+)$", site)
        if not m:
            return info
        file, line = m.group(1), int(m.group(2))
        try:
            file = str(Path(file).resolve().relative_to(REPO_ROOT)) if Path(file).is_absolute() else file
        except ValueError:
            pass
        info["file"], info["line"] = file, line
        best = None
        for lo, hi, name in self._functions(file):
            if lo <= line <= hi and (best is None or lo >= best[0]):
                best = (lo, name)
        if best:
            info["function"] = best[1]
        return info

    def lookup_reference_crash(self, header: dict, end: dict | None) -> Divergence | None:
        """A registered Metacat crash (``match.class = "reference-crash"``).

        Matches a trace whose Metacat ``end`` record is reason ``error`` and whose header has
        the entry's ``problem`` (list of three strings) and ``seed``.  Everything the replay
        does from the crashing codelet on is then the consequence of the reference bug."""
        if not end or end.get("reason") != "error":
            return None
        for e in self.entries:
            m = e.match
            if m.get("class") != "reference-crash":
                continue
            if list(m.get("problem", [])) == list(header.get("problem", [])) \
                    and m.get("seed") == header.get("seed"):
                return e
        return None

    def lookup(self, klass: str, site: str | None, complemented: bool = False) -> Divergence | None:
        info = self.resolve_site(site)
        for e in self.entries:
            m = e.match
            if m.get("class", klass) != klass:
                continue
            if e.effect == "complement" and not complemented:
                continue
            ok = True
            if "petacat_site" in m and m["petacat_site"] != info["raw"]:
                ok = False
            if "petacat_file" in m and m["petacat_file"] != info.get("file"):
                ok = False
            if "petacat_function" in m and m["petacat_function"] != info.get("function"):
                ok = False
            if "petacat_codelet" in m and m["petacat_codelet"] != info.get("codelet"):
                ok = False
            if not any(k.startswith("petacat_") for k in m):
                ok = False  # an entry must name a site
            if ok:
                return e
        return None


# --------------------------------------------------------------------------- checks


@dataclass
class Issue:
    klass: str
    message: str
    severity: str = "error"  # error | warning
    flags: list[str] = field(default_factory=list)
    complemented: bool = False


def _names(opts: Iterable[Any]) -> list[str]:
    return [o if isinstance(o, str) else json.dumps(o) for o in opts]


def _weight_map(names: list[str], weights: list[float] | None) -> dict[str, float]:
    out: dict[str, float] = defaultdict(float)
    for i, n in enumerate(names):
        out[n] += 1.0 if weights is None else float(weights[i])
    return dict(out)


def check_pair(m: dict, p: dict, rel_tol: float, abs_tol: float) -> list[Issue]:
    """All section 7.3 checks for one paired (Metacat, Petacat) decision."""
    issues: list[Issue] = []
    # unit
    if m.get("ctx") == "update" or p.get("ctx") == "update":
        mu, pu = (m.get("u"), m.get("who"), m.get("ctx")), (p.get("u"), p.get("who"), p.get("ctx"))
    else:
        mu, pu = (m.get("c"), m.get("who"), m.get("ctx")), (p.get("c"), p.get("who"), p.get("ctx"))
    if mu != pu:
        issues.append(Issue("unit", f"paired records are in different units: metacat {mu} vs petacat {pu}"))
    # kind
    mk, pk = m.get("kind"), p.get("kind")
    if mk != pk:
        issues.append(Issue("kind", f"kind differs: metacat {mk} vs petacat {pk}"))
        return issues
    if mk == "choice":
        issues.extend(_check_choice(m, p, rel_tol, abs_tol))
    elif mk == "prob":
        mp, pp = m.get("p"), p.get("p")
        if not close(mp, pp, rel_tol, abs_tol):
            if close(1.0 - mp, pp, rel_tol, abs_tol):
                issues.append(Issue("p", f"p differs: metacat {mp} vs petacat {pp} (= 1 - p)", complemented=True,
                                    flags=["complemented?"]))
            else:
                issues.append(Issue("p", f"p differs: metacat {mp} vs petacat {pp}"))
    elif mk == "perturb":
        if not close(m.get("value"), p.get("value"), rel_tol, abs_tol):
            issues.append(Issue("value", f"perturb value differs: metacat {m.get('value')} vs petacat {p.get('value')}"))
        if not close(m.get("bound"), p.get("bound"), rel_tol, abs_tol) or m.get("integer") != p.get("integer"):
            issues.append(Issue(
                "bound",
                f"perturb bound/integer differs: metacat {m.get('bound')}/{m.get('integer')} "
                f"vs petacat {p.get('bound')}/{p.get('integer')}"))
    elif mk == "int":
        if not close(m.get("bound"), p.get("bound"), rel_tol, abs_tol):
            issues.append(Issue("bound", f"int bound differs: metacat {m.get('bound')} vs petacat {p.get('bound')}"))
    return issues


def _check_choice(m: dict, p: dict, rel_tol: float, abs_tol: float) -> list[Issue]:
    issues: list[Issue] = []
    mo, po = _names(m.get("options", [])), _names(p.get("options", []))
    mc, pc = Counter(mo), Counter(po)
    picked = m.get("picked")
    picked_n = picked if isinstance(picked, str) else json.dumps(picked)
    if pc[picked_n] == 0:
        issues.append(Issue("missing-pick", f"metacat picked {picked_n!r}, which is not among petacat's options"))
    mw = _weight_map(mo, m.get("weights"))
    pw = _weight_map(po, p.get("weights"))
    shared = sorted(set(mw) & set(pw))
    if mc != pc:
        added = sorted((pc - mc).elements())
        dropped = sorted((mc - pc).elements())
        flags = []
        # Rounding near a threshold: options differ but every shared option still agrees.
        if shared:
            raw_ok = all(close(mw[n], pw[n], rel_tol, abs_tol) for n in shared)
            ms, ps = sum(mw[n] for n in shared), sum(pw[n] for n in shared)
            norm_ok = ms > 0 and ps > 0 and all(
                close(mw[n] / ms, pw[n] / ps, rel_tol, abs_tol) for n in shared)
            if raw_ok or norm_ok:
                flags.append("rounding-near-threshold?")
        issues.append(Issue("options", f"option multisets differ: only in petacat {added[:6]}, only in metacat {dropped[:6]}",
                            flags=flags))
    # weights: normalised over the shared names, summed for duplicates
    if shared:
        ms, ps = sum(mw[n] for n in shared), sum(pw[n] for n in shared)
        bad = []
        for n in shared:
            a = mw[n] / ms if ms else 0.0
            b = pw[n] / ps if ps else 0.0
            if not close(a, b, rel_tol, abs_tol):
                bad.append((n, a, b))
        if bad:
            n, a, b = bad[0]
            issues.append(Issue("weights", f"{len(bad)} weight(s) differ; first {n!r}: metacat {a:.6g} vs petacat {b:.6g}"))
    # ages
    if m.get("stamps") is not None and p.get("stamps") is not None:
        ma = Counter(zip(mo, m["stamps"]))
        pa = Counter(zip(po, p["stamps"]))
        if ma != pa:
            diff = sorted((ma - pa).elements())[:3] + sorted((pa - ma).elements())[:3]
            issues.append(Issue("age", f"stamps differ per name (examples {diff})"))
    # order (warning)
    if mc == pc and mo != po:
        issues.append(Issue("order", "options are the same multiset but listed in a different order", severity="warning"))
    return issues


# --------------------------------------------------------------------------- snapshots


def diff_snapshots(a: Any, b: Any, rel_tol: float = 1e-9, abs_tol: float = 1e-12, path: str = "") -> tuple[str, Any, Any] | None:
    """First differing field path between two snapshot values, or ``None``.

    Dicts: key sets must be equal.  Lists of dicts carrying a ``name`` are keyed by
    name; lists of scalars are multisets; lists of rows led by a name are multisets
    of rows; other lists compare positionally.
    Numbers agree within tolerance.
    """
    skip = {"t"} if not path else set()

    def sub(p: str, k: str) -> str:
        return f"{p}.{k}" if p else str(k)

    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted((set(a) | set(b)) - skip, key=str):
            if k not in a:
                return (sub(path, k), "<absent>", b[k])
            if k not in b:
                return (sub(path, k), a[k], "<absent>")
            d = diff_snapshots(a[k], b[k], rel_tol, abs_tol, sub(path, k))
            if d:
                return d
        return None
    if isinstance(a, list) and isinstance(b, list):
        if all(isinstance(x, dict) and "name" in x for x in a + b) and (a or b):
            def keyed(lst):
                seen: Counter = Counter()
                out = {}
                for x in lst:
                    seen[x["name"]] += 1
                    k = x["name"] if seen[x["name"]] == 1 else f"{x['name']}#{seen[x['name']]}"
                    out[k] = {kk: vv for kk, vv in x.items() if kk != "name"}
                return out
            return diff_snapshots(keyed(a), keyed(b), rel_tol, abs_tol, path)
        if all(not isinstance(x, (dict, list)) for x in a + b):
            if all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in a + b):
                sa, sb = sorted(a), sorted(b)
            else:
                sa, sb = sorted(map(repr, a)), sorted(map(repr, b))
            if len(sa) != len(sb):
                return (path, a, b)
            for x, y in zip(sa, sb):
                if not close(x, y, rel_tol, abs_tol):
                    return (path, a, b)
            return None
        if all(isinstance(x, list) and x and isinstance(x[0], str) for x in a + b) and (a or b):
            # Rows led by a canonical name (coderack codelets, structures) are an
            # unordered collection: the engines keep them in different orders.  Rows
            # are matched by name and then by their non-float fields, so a float
            # that differs is reported against the right row.
            def row_key(row):
                return (row[0], [repr(v) for v in row[1:] if not isinstance(v, float)])

            sa, sb = sorted(a, key=row_key), sorted(b, key=row_key)
            if [r[0] for r in sa] != [r[0] for r in sb]:
                ca, cb = Counter(r[0] for r in a), Counter(r[0] for r in b)
                return (path, sorted((ca - cb).elements())[:6] or "<same names>",
                        sorted((cb - ca).elements())[:6] or "<same names>")
            for x, y in zip(sa, sb):
                d = diff_snapshots(x, y, rel_tol, abs_tol, f"{path}[{x[0]}]")
                if d:
                    return d
            return None
        if len(a) != len(b):
            return (path, f"<{len(a)} items>", f"<{len(b)} items>")
        for i, (x, y) in enumerate(zip(a, b)):
            d = diff_snapshots(x, y, rel_tol, abs_tol, f"{path}[{i}]")
            if d:
                return d
        return None
    if close(a, b, rel_tol, abs_tol):
        return None
    return (path, a, b)


# --------------------------------------------------------------------------- report


@dataclass
class Finding:
    klass: str
    severity: str
    message: str
    pet_index: int | None = None  # index into petacat decisions
    meta_index: int | None = None  # index into metacat decisions
    petacat: dict | None = None
    metacat: dict | None = None
    registered: str | None = None  # registry id when registered
    flags: list[str] = field(default_factory=list)
    fatal: bool = False
    c: int | None = None
    snapshot_diff: dict | None = None

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class Report:
    metacat_path: str
    petacat_path: str
    metacat_decisions: int = 0
    petacat_decisions: int = 0
    errors: list[Finding] = field(default_factory=list)  # unregistered errors (and fatals)
    warnings: list[Finding] = field(default_factory=list)
    registered: list[Finding] = field(default_factory=list)
    first_fatal: Finding | None = None
    first_error: Finding | None = None
    counts: dict[str, int] = field(default_factory=dict)
    warning_counts: dict[str, int] = field(default_factory=dict)
    registered_counts: dict[str, int] = field(default_factory=dict)
    by_who: dict[str, dict] = field(default_factory=dict)
    by_petacat_site: dict[str, dict] = field(default_factory=dict)
    by_metacat_site: dict[str, dict] = field(default_factory=dict)
    reach: int = 0
    run_length: int = 0
    agreement: float = 1.0
    unregistered_error_count: int = 0
    snapshot_first_diff: dict | None = None
    snapshots_compared: int = 0
    snapshots_differing: int = 0

    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items()}
        for k in ("errors", "warnings", "registered"):
            d[k] = [f.to_dict() for f in d[k]]
        for k in ("first_fatal", "first_error"):
            d[k] = d[k].to_dict() if d[k] else None
        return d

    # -- text ------------------------------------------------------------------

    def format(self, max_rows: int = 25) -> str:
        out: list[str] = []
        w = out.append
        w(f"metacat: {self.metacat_path}  ({self.metacat_decisions} decisions)")
        w(f"petacat: {self.petacat_path}  ({self.petacat_decisions} decisions)")
        w(f"reach (codelet): {self.reach}   run length: {self.run_length}   "
          f"agreement: {self.agreement:.4f}   unregistered errors: {self.unregistered_error_count}")
        w("")
        for title, f in (("FIRST FATAL FAILURE", self.first_fatal), ("FIRST ERROR", self.first_error)):
            w(f"== {title} ==")
            if f is None:
                w("  none")
            else:
                w(f"  class {f.klass}  at c={f.c}  {f.message}" + (f"  [{', '.join(f.flags)}]" if f.flags else ""))
                w(f"  metacat: {json.dumps(f.metacat, sort_keys=True) if f.metacat else '-'}")
                w(f"  petacat: {json.dumps(f.petacat, sort_keys=True) if f.petacat else '-'}")
                sd = f.snapshot_diff
                if sd:
                    w(f"  nearest snapshot difference (u={sd.get('u')}): {sd['path']}: "
                      f"metacat {sd['metacat']!r} vs petacat {sd['petacat']!r}")
                else:
                    w("  nearest snapshot difference: none")
            w("")
        w("== COUNTS BY CLASS (unregistered errors) ==")
        for k, v in sorted(self.counts.items()):
            w(f"  {k:14s} {v}")
        if not self.counts:
            w("  none")
        if self.warning_counts:
            w("== WARNINGS ==")
            for k, v in sorted(self.warning_counts.items()):
                w(f"  {k:14s} {v}")
        w("== REGISTERED DIVERGENCES (not counted as errors) ==")
        for k, v in sorted(self.registered_counts.items()):
            w(f"  {k:30s} {v}")
        if not self.registered_counts:
            w("  none")
        w("")
        for title, table in (("AGREEMENT BY CODELET TYPE", self.by_who),
                             ("AGREEMENT BY PETACAT SITE", self.by_petacat_site),
                             ("AGREEMENT BY METACAT SITE", self.by_metacat_site)):
            w(f"== {title} ==")
            rows = sorted(table.items(), key=lambda kv: (kv[1]["ok"] / kv[1]["n"] if kv[1]["n"] else 1, -kv[1]["n"]))
            for k, v in rows[:max_rows]:
                rate = v["ok"] / v["n"] if v["n"] else 1.0
                w(f"  {rate:6.3f}  {v['ok']:>7}/{v['n']:<7} {k}")
            if len(rows) > max_rows:
                w(f"  ... {len(rows) - max_rows} more")
            w("")
        w(f"snapshots compared: {self.snapshots_compared}, differing: {self.snapshots_differing}")
        if self.snapshot_first_diff:
            sd = self.snapshot_first_diff
            w(f"first snapshot difference (u={sd['u']}): {sd['path']}: metacat {sd['metacat']!r} vs petacat {sd['petacat']!r}")
        return "\n".join(out)


# --------------------------------------------------------------------------- compare


def _snap_diff(meta: Trace, pet: Trace, u: Any, rel_tol: float, abs_tol: float) -> dict | None:
    ms, ps = meta.snapshots.get(u), pet.snapshots.get(u)
    if ms is None or ps is None:
        return None
    d = diff_snapshots(ms, ps, rel_tol, abs_tol)
    if d is None:
        return None
    return {"u": u, "path": d[0], "metacat": d[1], "petacat": d[2]}


def _nearest_u(meta: Trace, pet: Trace, rec: dict) -> Any:
    """The update cycle a decision belongs to or most recently follows."""
    if rec.get("ctx") == "update" and rec.get("u") in meta.snapshots:
        return rec["u"]
    c = rec.get("c")
    best = None
    for u in meta.snapshot_order:
        s = meta.snapshots[u]
        if c is not None and s.get("c") is not None and s["c"] <= c:
            best = u
    return best if best is not None else (meta.snapshot_order[0] if meta.snapshot_order else None)


def _tally(table: dict, key: str | None, ok: bool) -> None:
    if key is None:
        return
    row = table.setdefault(key, {"n": 0, "ok": 0})
    row["n"] += 1
    row["ok"] += 1 if ok else 0


def compare(metacat_path, petacat_path, registry: Registry | str | Path | None = DEFAULT_REGISTRY,
            rel_tol: float = 1e-9, abs_tol: float = 1e-12) -> Report:
    meta = metacat_path if isinstance(metacat_path, Trace) else Trace.load(metacat_path)
    pet = petacat_path if isinstance(petacat_path, Trace) else Trace.load(petacat_path)
    if not isinstance(registry, Registry):
        registry = Registry.load(registry)
    return compare_traces(meta, pet, registry, rel_tol, abs_tol)


def compare_traces(meta: Trace, pet: Trace, registry: Registry, rel_tol: float = 1e-9, abs_tol: float = 1e-12) -> Report:
    rep = Report(metacat_path=meta.path, petacat_path=pet.path,
                 metacat_decisions=len(meta.decisions), petacat_decisions=len(pet.decisions))
    findings: list[tuple[int, Finding]] = []  # (file position, finding) for ordering
    bad_meta: set[int] = set()  # meta decisions paired with an unregistered error
    paired_meta: set[int] = set()
    pet_ok: dict[int, bool] = {}

    # header
    for key in ("problem", "seed", "cap"):
        mv, pv = meta.header.get(key), pet.header.get(key)
        if mv is not None and pv is not None and mv != pv:
            findings.append((-1, Finding("header", "error", f"header {key} differs: metacat {mv} vs petacat {pv}", fatal=True)))

    last_pair = -1
    for pi, p in enumerate(pet.decisions):
        pos = pet.decision_pos[pi]
        mi = p.get("pair")
        if mi is None or not (0 <= mi < len(meta.decisions)):
            f = Finding("count", "error", "surplus petacat decision (no metacat record to pair with)"
                        if mi is None else f"pair {mi} out of range", pet_index=pi, petacat=p, c=p.get("c"))
            findings.append((pos, f))
            pet_ok[pi] = False
            continue
        paired_meta.add(mi)
        m = meta.decisions[mi]
        if mi < last_pair:
            findings.append((pos, Finding("order", "warning", f"paired out of order: metacat index {mi} after {last_pair}",
                                          pet_index=pi, meta_index=mi, petacat=p, metacat=m, c=p.get("c"))))
        last_pair = max(last_pair, mi)
        ok = True
        for iss in check_pair(m, p, rel_tol, abs_tol):
            f = Finding(iss.klass, iss.severity, iss.message, pet_index=pi, meta_index=mi, petacat=p, metacat=m,
                        flags=list(iss.flags), c=p.get("c"), fatal=iss.klass in FATAL_CLASSES)
            if iss.severity == "warning":
                findings.append((pos, f))
                continue
            entry = registry.lookup(iss.klass, p.get("site"), complemented=iss.complemented)
            if entry is not None:
                f.registered = entry.id
                f.severity = "registered"
            else:
                ok = False
            findings.append((pos, f))
        pet_ok[pi] = ok
        if not ok:
            bad_meta.add(mi)

    # fatal record from the replay
    fatal_idx = None
    if pet.fatal is not None:
        fr = pet.fatal
        # the decision just before the fatal record gives the side-by-side context
        prev = None
        for pi in range(len(pet.decisions) - 1, -1, -1):
            if pet.decision_pos[pi] < (pet.fatal_pos or 0):
                prev = pi
                break
        pdec = pet.decisions[prev] if prev is not None else None
        mdec = meta.decisions[pdec["pair"]] if pdec and pdec.get("pair") is not None and pdec["pair"] < len(meta.decisions) else None
        f = Finding(str(fr.get("class", "unit")), "error", f"replay stopped: {fr.get('detail', '')}",
                    pet_index=prev, meta_index=pdec.get("pair") if pdec else None, petacat=pdec, metacat=mdec,
                    fatal=True, c=fr.get("c"))
        findings.append((pet.fatal_pos or 0, f))
        fatal_idx = pet.fatal_pos

    # missing metacat records
    max_paired = max(paired_meta) if paired_meta else -1
    for mi, m in enumerate(meta.decisions):
        if mi in paired_meta:
            continue
        if pet.fatal is not None or (pet.end or {}).get("reason") == "fatal":
            if mi > max_paired:
                continue  # the replay stopped; the tail is not "missing", it is unreached
        f = Finding("count", "error", "metacat decision never paired (missing in petacat)", meta_index=mi, metacat=m, c=m.get("c"))
        # position: just after the petacat decision paired with the nearest earlier metacat record
        findings.append((10**12 + mi, f))
        bad_meta.add(mi)

    # end records
    fatal_stop = pet.fatal is not None or (pet.end or {}).get("reason") == "fatal"
    me, pe = meta.end, pet.end
    if me is not None and pe is not None and not fatal_stop:
        diffs = [f"{k}: metacat {me.get(k)!r} vs petacat {pe.get(k)!r}"
                 for k in ("reason", "answer", "c") if me.get(k) != pe.get(k)]
        if diffs:
            findings.append((10**13, Finding("end", "error", "end records differ: " + "; ".join(diffs),
                                             petacat=pe, metacat=me, c=pe.get("c"))))
    elif me is not None and pe is None and not fatal_stop:
        findings.append((10**13, Finding("end", "error", "petacat trace has no end record", metacat=me)))

    # snapshots
    for u in meta.snapshot_order:
        if u in pet.snapshots:
            rep.snapshots_compared += 1
            d = _snap_diff(meta, pet, u, rel_tol, abs_tol)
            if d:
                rep.snapshots_differing += 1
                if rep.snapshot_first_diff is None:
                    rep.snapshot_first_diff = d

    # a registered reference crash: what the replay does from the crashing codelet on
    # (the codelet's remaining decisions, later codelets, the end record) is not an error
    crash = registry.lookup_reference_crash(meta.header, meta.end)
    if crash is not None:
        crash_c = (meta.end or {}).get("c")
        for _, f in findings:
            if f.severity == "error" and (f.klass == "end"
                                          or (crash_c is not None and f.c is not None and f.c >= crash_c)):
                f.registered = crash.id
                f.severity = "registered"

    # sort findings by position and attach snapshot context for first fatal/error
    findings.sort(key=lambda t: t[0])
    for _, f in findings:
        if f.severity == "warning":
            rep.warnings.append(f)
            rep.warning_counts[f.klass] = rep.warning_counts.get(f.klass, 0) + 1
        elif f.severity == "registered":
            rep.registered.append(f)
            rep.registered_counts[f.registered] = rep.registered_counts.get(f.registered, 0) + 1
        else:
            rep.errors.append(f)
            rep.counts[f.klass] = rep.counts.get(f.klass, 0) + 1
    rep.unregistered_error_count = len(rep.errors)
    rep.first_error = rep.errors[0] if rep.errors else None
    rep.first_fatal = next((f for f in rep.errors if f.fatal), None)
    for f in {id(x): x for x in (rep.first_fatal, rep.first_error) if x}.values():
        rec = f.metacat or f.petacat
        if rec is not None:
            f.snapshot_diff = _snap_diff(meta, pet, _nearest_u(meta, pet, rec), rel_tol, abs_tol)
            if f.snapshot_diff is None:
                f.snapshot_diff = rep.snapshot_first_diff

    # metrics
    meta_end_c = (meta.end or {}).get("c")
    if meta_end_c is None:
        meta_end_c = max((d.get("c") or 0 for d in meta.decisions), default=0)
    rep.run_length = int(meta_end_c)
    rep.reach = int(rep.first_fatal.c) if rep.first_fatal and rep.first_fatal.c is not None else rep.run_length
    n = len(meta.decisions)
    rep.agreement = (sum(1 for mi in paired_meta if mi not in bad_meta) / n) if n else 1.0

    # agreement tables
    for pi, p in enumerate(pet.decisions):
        mi = p.get("pair")
        ok = pet_ok.get(pi, False)
        _tally(rep.by_petacat_site, p.get("site"), ok)
        if mi is None or not (0 <= mi < n):
            if p.get("ctx") == "codelet":
                _tally(rep.by_who, p.get("who"), False)
            continue
        m = meta.decisions[mi]
        _tally(rep.by_metacat_site, m.get("site"), ok)
        if m.get("ctx") == "codelet":
            _tally(rep.by_who, m.get("who"), ok)
    for mi, m in enumerate(meta.decisions):
        if mi in paired_meta:
            continue
        if mi in bad_meta:
            _tally(rep.by_metacat_site, m.get("site"), False)
            if m.get("ctx") == "codelet":
                _tally(rep.by_who, m.get("who"), False)
    return rep


# --------------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("metacat")
    ap.add_argument("petacat")
    ap.add_argument("--json", help="write the report as JSON")
    ap.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    ap.add_argument("--rel-tol", type=float, default=1e-9)
    ap.add_argument("--abs-tol", type=float, default=1e-12)
    args = ap.parse_args(argv)
    rep = compare(args.metacat, args.petacat, Registry.load(args.registry), args.rel_tol, args.abs_tol)
    print(rep.format())
    if args.json:
        Path(args.json).write_text(json.dumps(rep.to_dict(), indent=1, default=str))
    return 0 if rep.unregistered_error_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
