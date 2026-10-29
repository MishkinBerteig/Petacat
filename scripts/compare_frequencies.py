#!/usr/bin/env python3
"""Compare Petacat's answer frequencies with Metacat's, for one problem or the 19 study problems.

Metacat's decision traces match Petacat's run for run (``scripts/lockstep_corpus.py``), so
over many seeds the answer *frequencies* should agree too; this is that final
confirmation, in two forms.

``study`` -- one problem over a seed range, both engines run on the same seeds (the
1,000-run study of ``wxyz -> vxyz; abcd -> ?`` was seeds 101-1100)::

    scripts/compare_frequencies.py study wxyz vxyz abcd 101-1100 --jobs 4 --metacat-jobs 4
    scripts/compare_frequencies.py study abc abd aabbcc 1-10 --cap 4000
    scripts/compare_frequencies.py study wxyz vxyz abcd 101-1100 \\
        --metacat FILE.metacat.tsv --petacat FILE.petacat.tsv      # compare saved recordings

Metacat's side is ``tests/lockstep/metacat/record_frequencies.py`` (Docker, ``metacat:1.2``);
Petacat's is the default shipped configuration, one worker, fresh memory per run
(``--faithful`` adds the lockstep parameters; ``--workers N`` runs the free-running engine
with N threads, the multi-worker study).  Prints both frequency tables, the
total-variation distance and a two-sample chi-square (rare answers pooled to expected
count >= 5), plus the z score of every answer that either side gave in >= 5% of runs.
No pass/fail: the exit status is 0 unless a run failed.

``support-v1a`` -- Petacat against the published Metacat observations of the 19 study
problems (``studies/support-v1a/data/main.tar.gz``, construction phase, admitted attempts,
duplicate seeds dropped, 100,000 codelets, fresh memory; 20,000 runs per problem)::

    scripts/compare_frequencies.py support-v1a --runs 200 --jobs 10 [--faithful] [--only copy1,run4]
        --json measurements/vs-metacat-support-v1a-lockstep.json

Petacat runs seeds 5000001.. (clear of the lockstep corpus).  For each problem it reports
the total-variation distance (with its expected value under the reference), Monte Carlo
p-values for TV and for Pearson chi-square (reference probabilities floored at
0.5/N so unseen answers are penalised), a classical pooled chi-square, and novel answers
(ones Metacat never produced).  The problem strings come from
``measurements/reference/single-run-sets.json``.  This regenerates the numbers in
``measurements/vs-metacat-support-v1a-lockstep.md`` (that file's Petacat counts depend on the
engine at the time; rerun after engine changes).  About 25 minutes for 19 x 200 runs on 10
cores; ``--only`` runs a few problems.
"""

from __future__ import annotations

import argparse
import collections
import json
import math
import subprocess
import sys
import tarfile
from multiprocessing import Pool
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DEFAULT_OUT = ROOT / "tests" / "lockstep" / "out"
SUPPORT_TAR = ROOT / "studies" / "support-v1a" / "data" / "main.tar.gz"
REFERENCE_SETS = ROOT / "measurements" / "reference" / "single-run-sets.json"
FIRST_PETACAT_SEED = 5_000_001


# ---------------------------------------------------------------------------
# Parsing and statistics (no engine, no Docker)

def parse_seeds(text: str) -> list[int]:
    """``"1-5,9"`` -> ``[1, 2, 3, 4, 5, 9]`` (as ``tests/lockstep/metacat/wrap.py``)."""
    seen: list[int] = []
    for part in text.split(","):
        lo, _, hi = part.strip().partition("-")
        if lo:
            seen += [s for s in range(int(lo), int(hi or lo) + 1) if s not in seen]
    return seen


def read_rows(path: Path) -> dict[int, dict]:
    """A recording (``record_frequencies.py`` or this script's Petacat file) -> ``{seed: row}``.

    Row: ``answer`` str, ``codelets`` int, ``temperature`` float.  ``#`` lines and blanks skipped.
    """
    rows: dict[int, dict] = {}
    for line in Path(path).read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        f = line.split("\t")
        rows[int(f[0])] = {"answer": f[1], "codelets": int(f[2]),
                           "temperature": float(f[3]) if len(f) > 3 else math.nan}
    return rows


def answer_counts(rows: dict[int, dict]) -> collections.Counter:
    return collections.Counter(r["answer"] for r in rows.values())


def frequencies(counts: dict, n: int | None = None) -> dict:
    """Answer -> fraction, most frequent first (ties by answer)."""
    n = n if n is not None else sum(counts.values())
    return {k: v / n for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))}


def total_variation(a: dict, b: dict) -> float:
    """Half the L1 distance between two count tables, each normalised."""
    na, nb = sum(a.values()), sum(b.values())
    cats = set(a) | set(b)
    return 0.5 * sum(abs(a.get(k, 0) / na - b.get(k, 0) / nb) for k in cats)


def chi2_sf(x: float, k: int) -> float:
    """Upper tail of the chi-square distribution with ``k`` degrees of freedom (no scipy)."""
    a, x = k / 2, x / 2
    if x <= 0:
        return 1.0
    if x < a + 1:  # series for the lower incomplete gamma
        s = term = 1 / a
        n = a
        for _ in range(1000):
            n += 1
            term *= x / n
            s += term
            if abs(term) < 1e-14 * abs(s):
                break
        return 1 - s * math.exp(-x + a * math.log(x) - math.lgamma(a))
    b = x + 1 - a  # continued fraction for the upper one
    c, d = 1e300, 1 / b
    h = d
    for i in range(1, 1000):
        an = -i * (i - a)
        b += 2
        d = an * d + b
        d = 1e-300 if abs(d) < 1e-300 else d
        c = b + an / c
        c = 1e-300 if abs(c) < 1e-300 else c
        d = 1 / d
        de = d * c
        h *= de
        if abs(de - 1) < 1e-14:
            break
    return math.exp(-x + a * math.log(x) - math.lgamma(a)) * h


def two_sample_chi2(a: dict, b: dict, min_expected: float = 5.0) -> tuple[float, int, float | None]:
    """Chi-square test of homogeneity of two count tables.

    Categories whose smaller expected count is below ``min_expected`` are pooled into one
    bin (merged into the largest bin if that is still too small).  Returns
    ``(statistic, degrees of freedom, p)``; ``p`` is ``None`` with fewer than two bins.
    """
    na, nb = sum(a.values()), sum(b.values())
    cats = sorted(set(a) | set(b), key=lambda k: -(a.get(k, 0) + b.get(k, 0)))
    bins: list[list[int]] = []
    rest = [0, 0]
    for k in cats:
        ca, cb = a.get(k, 0), b.get(k, 0)
        tot = ca + cb
        if min(na, nb) * tot / (na + nb) >= min_expected:
            bins.append([ca, cb])
        else:
            rest[0] += ca
            rest[1] += cb
    if rest[0] + rest[1]:
        if min(na, nb) * (rest[0] + rest[1]) / (na + nb) >= min_expected or not bins:
            bins.append(rest)
        else:
            bins[-1][0] += rest[0]
            bins[-1][1] += rest[1]
    stat = 0.0
    for ca, cb in bins:
        tot = ca + cb
        for obs, n in ((ca, na), (cb, nb)):
            exp = tot * n / (na + nb)
            stat += (obs - exp) ** 2 / exp
    df = len(bins) - 1
    return stat, df, (chi2_sf(stat, df) if df > 0 else None)


def proportion_z(ca: int, na: int, cb: int, nb: int) -> float:
    """Two-proportion z (pooled) for one answer; 0.0 when the pooled rate is 0 or 1."""
    p = (ca + cb) / (na + nb)
    se = math.sqrt(p * (1 - p) * (1 / na + 1 / nb))
    return (ca / na - cb / nb) / se if se else 0.0


def compare_samples(a: dict, b: dict, z_floor: float = 0.05) -> dict:
    """Everything ``study`` reports about two answer-count tables."""
    na, nb = sum(a.values()), sum(b.values())
    stat, df, p = two_sample_chi2(a, b)
    common = [k for k in set(a) | set(b) if a.get(k, 0) / na >= z_floor or b.get(k, 0) / nb >= z_floor]
    return {
        "n": [na, nb],
        "tv": total_variation(a, b),
        "chi2": stat, "chi2_df": df, "chi2_p": p,
        "z": {k: proportion_z(a.get(k, 0), na, b.get(k, 0), nb)
              for k in sorted(common, key=lambda k: -(a.get(k, 0) + b.get(k, 0)))},
    }


def compare_to_reference(ref: dict, sample: list[str], draws: int = 20000, seed: int = 12345) -> dict:
    """Sample (a list of answers) against reference counts treated as the true distribution.

    TV with its Monte Carlo p and expected value under the reference; Pearson chi-square
    over all categories with probabilities floored at ``0.5/N`` (Monte Carlo p); a classical
    chi-square on bins with expected count >= 5 (rest pooled); the novel answers.
    """
    import numpy as np

    pc = collections.Counter(sample)
    n, big_n = sum(pc.values()), sum(ref.values())
    cats = sorted(set(ref) | set(pc))
    p = np.array([ref.get(k, 0) / big_n for k in cats])
    q = np.array([pc.get(k, 0) / n for k in cats])
    obs = np.array([pc.get(k, 0) for k in cats])
    tv = 0.5 * float(np.abs(p - q).sum())
    pe = np.maximum(p, 0.5 / big_n)
    pe = pe / pe.sum()
    sims = np.random.default_rng(seed).multinomial(n, pe, size=draws)
    chis = (((sims - n * pe) ** 2) / (n * pe)).sum(1)
    tvs = 0.5 * np.abs(sims / n - pe).sum(1)
    chi = float((((obs - n * pe) ** 2) / (n * pe)).sum())
    big = [i for i in range(len(cats)) if n * p[i] >= 5]
    rest = [i for i in range(len(cats)) if i not in big]
    ob = [int(obs[i]) for i in big] + [int(obs[rest].sum())]
    ex = [float(n * p[i]) for i in big] + [float(n * p[rest].sum())]
    if ex[-1] < 5 and len(ob) > 1:
        last_o, last_e = ob.pop(), ex.pop()  # pop first: ``ob[-2] += ob.pop()`` would misindex
        ob[-1] += last_o
        ex[-1] += last_e
    pooled = sum((o - e) ** 2 / e for o, e in zip(ob, ex) if e > 0)
    df = len(ob) - 1
    return {
        "n": n, "tv": tv, "tv_expected_under_ref": float(tvs.mean()),
        "tv_p_mc": float((tvs >= tv - 1e-12).mean()),
        "chi2_full": chi, "chi2_p_mc": float((chis >= chi - 1e-9).mean()),
        "chi2_pooled": pooled, "chi2_pooled_df": df,
        "chi2_pooled_p": chi2_sf(pooled, df) if df > 0 else None,
        "novel_answers": {k: int(pc[k]) for k in pc if ref.get(k, 0) == 0},
    }


def table(label_a: str, a: dict, label_b: str, b: dict, top: int = 10) -> str:
    """Side-by-side frequency table of the ``top`` answers of either side."""
    na, nb = sum(a.values()), sum(b.values())
    cats = sorted(set(a) | set(b), key=lambda k: -(a.get(k, 0) + b.get(k, 0)))[:top]
    lines = [f"{'answer':16s} {label_a:>18s} {label_b:>18s}"]
    for k in cats:
        lines.append(f"{k:16s} {100 * a.get(k, 0) / na:8.1f}% ({a.get(k, 0):5d}) "
                     f"{100 * b.get(k, 0) / nb:8.1f}% ({b.get(k, 0):5d})")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Petacat runs

_CONTEXT: dict = {}


def _init(faithful: bool) -> None:
    from server.engine.metadata import MetadataProvider
    _CONTEXT["meta"] = MetadataProvider.from_seed_data(str(ROOT / "seed_data"))
    _CONTEXT["parameters"] = None
    if faithful:
        from tests.lockstep.faithful import FAITHFUL_PARAMETERS
        _CONTEXT["parameters"] = dict(FAITHFUL_PARAMETERS)


def petacat_run(task: tuple) -> tuple:
    """``(problem, seed, cap)`` -> ``(seed, answer, codelets, temperature)``.

    Classified as ``scripts/compare_to_metacat.py`` does: the answer, else ``*CAP*`` when the
    cap was reached, else ``*NONE*``; an exception is ``*ERROR*``.
    """
    from server.engine.runner import EngineRunner, STATUS_ANSWER_FOUND

    problem, seed, cap = task[:3]
    workers = task[3] if len(task) > 3 else 1
    try:
        runner = EngineRunner(_CONTEXT["meta"])
        params = _CONTEXT["parameters"]
        runner.init_mcat(*problem, seed=seed, **({"parameters": dict(params)} if params else {}))
        if workers > 1:
            from server.engine.free_running import FreeRunningEngine
            FreeRunningEngine(runner, workers=workers).run(cap)
        else:
            runner.run_mcat(max_steps=cap)
        ctx = runner.ctx
        if runner.status == STATUS_ANSWER_FOUND and ctx.workspace.answer_string:
            answer = ctx.workspace.answer_string.text
        elif ctx.codelet_count >= cap:
            answer = "*CAP*"
        else:
            answer = "*NONE*"
        return seed, answer, ctx.codelet_count, float(ctx.temperature.value)
    except Exception as error:  # noqa: BLE001 - reported as an *ERROR* row, never hidden
        return seed, "*ERROR*", 0, math.nan


def run_petacat(problem: list[str], seeds: list[int], cap: int, jobs: int, faithful: bool,
                workers: int = 1) -> dict[int, dict]:
    """Run every seed; ``workers`` > 1 uses the free-running engine (the multi-worker study)."""
    tasks = [(tuple(problem), s, cap, workers) for s in seeds]
    with Pool(max(1, jobs), initializer=_init, initargs=(faithful,)) as pool:
        out = pool.map(petacat_run, tasks, chunksize=4)
    return {s: {"answer": a, "codelets": c, "temperature": t} for s, a, c, t in out}


def write_rows(path: Path, header: str, rows: dict[int, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# {header}", "# Columns: seed\tanswer\tcodelets\ttemperature"]
    lines += [f"{s}\t{r['answer']}\t{r['codelets']}\t{r['temperature']:g}" for s, r in sorted(rows.items())]
    path.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# study

def cmd_study(args: argparse.Namespace) -> int:
    problem = list(args.problem)
    seeds = parse_seeds(args.seeds)
    lo, hi = min(seeds), max(seeds)
    stem = f"{'-'.join(problem)}.{lo}-{hi}.cap{args.cap}"
    out = Path(args.out) / "frequencies"
    mpath = Path(args.metacat) if args.metacat else out / f"{stem}.metacat.tsv"
    if not args.metacat:
        subprocess.run([sys.executable, str(ROOT / "tests/lockstep/metacat/record_frequencies.py"),
                        *problem, args.seeds, "--cap", str(args.cap), "--jobs", str(args.metacat_jobs),
                        "--out", str(args.out)], check=True)
    ppath = Path(args.petacat) if args.petacat else out / f"{stem}.petacat{'-faithful' if args.faithful else ''}.tsv"
    if args.petacat:
        pet = read_rows(ppath)
    else:
        pet = run_petacat(problem, seeds, args.cap, args.jobs, args.faithful, args.workers)
        write_rows(ppath, f"Petacat answers: problem {' '.join(problem)}, seeds {lo}-{hi}, cap {args.cap}"
                          f"{', faithful' if args.faithful else ''} (scripts/compare_frequencies.py)", pet)
    meta = read_rows(mpath)
    common = sorted(set(meta) & set(pet))
    ma = answer_counts({s: meta[s] for s in common})
    pa = answer_counts({s: pet[s] for s in common})
    print(f"{' '.join(problem)}  seeds {lo}-{hi}  cap {args.cap}  n={len(common)}")
    print(table("Metacat", ma, "Petacat", pa))
    mean = lambda rows, k: sum(rows[s][k] for s in common) / len(common)  # noqa: E731
    print(f"mean codelets: Metacat {mean(meta, 'codelets'):.0f}  Petacat {mean(pet, 'codelets'):.0f}")
    res = compare_samples(ma, pa)
    p = res["chi2_p"]
    chi = "chi-square n/a (fewer than two bins of expected count >= 5)" if p is None else \
        f"chi-square {res['chi2']:.1f} on {res['chi2_df']} df, p = {p:.3f}"
    print(f"TV {res['tv']:.3f}; {chi}")
    print("z (Metacat - Petacat): " + "  ".join(f"{k} {z:+.2f}" for k, z in res["z"].items()))
    same = sum(1 for s in common if meta[s]["answer"] == pet[s]["answer"])
    print(f"same answer on the same seed: {same}/{len(common)} (informative only: Petacat draws "
          f"its own random numbers; the replay that matches run for run is scripts/lockstep_corpus.py)")
    errors = sum(1 for r in pet.values() if r["answer"] == "*ERROR*")
    if args.json:
        Path(args.json).write_text(json.dumps({"problem": problem, "seeds": [lo, hi], "cap": args.cap,
                                               "metacat": dict(ma), "petacat": dict(pa), **res}, indent=1))
    return 1 if errors else 0


# ---------------------------------------------------------------------------
# support-v1a

def reference_counts(tar_path: Path = SUPPORT_TAR) -> dict[str, dict[str, int]]:
    """Per problem: answer (``*CAP*`` for capped, else the state) -> count over the construction
    phase's admitted attempts, deduplicated by seed (first occurrence kept)."""
    tar = tarfile.open(tar_path)
    admitted: dict[str, int] = {}
    members: dict[str, tarfile.TarInfo] = {}
    for m in tar:
        if "/chunks/construction/" in m.name and m.isfile():
            members[m.name] = m
            if m.name.endswith("/complete.json"):
                admitted[m.name.rsplit("/", 1)[0]] = json.load(tar.extractfile(m))["attempt"]
    seen: dict[str, dict[int, str]] = collections.defaultdict(dict)
    for chunk, attempt in sorted(admitted.items()):
        for line in tar.extractfile(members[f"{chunk}/{attempt}/runs.jsonl"]):
            r = json.loads(line)
            state = r["state"] if r["termination"] != "capped" else "*CAP*"
            seen[r["problem"]].setdefault(r["seed"], state)
    return {p: dict(collections.Counter(d.values())) for p, d in seen.items()}


def problem_strings(path: Path = REFERENCE_SETS) -> dict[str, list[str]]:
    results = json.loads(Path(path).read_text())["results"]
    return {r["name"]: list(r["problem"][1:]) for r in results}


def cmd_support(args: argparse.Namespace) -> int:
    ref = reference_counts()
    strings = problem_strings()
    names = [n for n in strings if n in ref and (not args.only or n in args.only.split(","))]
    out = {"reference": {"data": "studies/support-v1a/data/main.tar.gz, phase=construction, admitted attempts "
                                  "(complete.json), deduplicated by seed; fresh memory, 100,000-codelet cap; "
                                  "termination capped -> *CAP*"},
           "petacat": {"seeds": f"{FIRST_PETACAT_SEED}..{FIRST_PETACAT_SEED + args.runs - 1}",
                       "cap": args.cap, "n_per_problem": args.runs,
                       "mode": "faithful" if args.faithful else "default"},
           "problems": {}}
    for name in names:
        seeds = list(range(FIRST_PETACAT_SEED, FIRST_PETACAT_SEED + args.runs))
        rows = run_petacat(strings[name], seeds, args.cap, args.jobs, args.faithful)
        sample = [r["answer"] for r in rows.values()]
        total = sum(ref[name].values())
        res = compare_to_reference(ref[name], sample)
        out["problems"][name] = {"reference": {"n": total, "freq": frequencies(ref[name], total)},
                                 "petacat": {"n": len(sample), "freq": frequencies(collections.Counter(sample)),
                                             **res}}
        top = lambda f: " ".join(f"{a}:{100 * v:.1f}" for a, v in list(f.items())[:3])  # noqa: E731
        e = out["problems"][name]
        print(f"{name:11s} TV={res['tv']:.3f} (null {res['tv_expected_under_ref']:.3f}) pTV={res['tv_p_mc']:.2f} "
              f"chi2p={res['chi2_p_mc']:.2f} novel={res['novel_answers']}\n   ref {top(e['reference']['freq'])}"
              f"\n   pet {top(e['petacat']['freq'])}", flush=True)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(out, indent=1))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    st = sub.add_parser("study", help="one problem over a seed range, Metacat vs Petacat")
    st.add_argument("problem", nargs=3, metavar=("INITIAL", "MODIFIED", "TARGET"))
    st.add_argument("seeds", help="seed list/range, e.g. 101-1100")
    st.add_argument("--cap", type=int, default=100000)
    st.add_argument("--jobs", type=int, default=4, help="Petacat processes (default 4)")
    st.add_argument("--metacat-jobs", type=int, default=1, help="Metacat containers at once (default 1)")
    st.add_argument("--metacat", help="use this Metacat recording instead of recording")
    st.add_argument("--petacat", help="use this Petacat recording instead of running")
    st.add_argument("--faithful", action="store_true", help="Petacat with the lockstep parameters")
    st.add_argument("--workers", type=int, default=1,
                    help="Petacat worker threads: 1 = the serial engine (default), more = free-running "
                         "(set BACKEND=numpy; lower --jobs, each run then uses several cores)")
    st.add_argument("--out", default=str(DEFAULT_OUT), help="output root (default tests/lockstep/out)")
    st.add_argument("--json", help="also write the comparison as JSON")
    st.set_defaults(func=cmd_study)
    sv = sub.add_parser("support-v1a", help="Petacat vs the published support-v1a observations")
    sv.add_argument("--runs", type=int, default=200, help="Petacat runs per problem (default 200)")
    sv.add_argument("--cap", type=int, default=100000)
    sv.add_argument("--jobs", type=int, default=4, help="Petacat processes (default 4)")
    sv.add_argument("--faithful", action="store_true")
    sv.add_argument("--only", help="comma-separated problem names (default all 19)")
    sv.add_argument("--json", help="write the results here")
    sv.set_defaults(func=cmd_support)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
