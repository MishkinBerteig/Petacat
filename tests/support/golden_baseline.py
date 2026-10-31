"""The golden baseline (gate G3 of the configuration-source plan, work package EN0).

Captured *before* the first engine edit and compared byte for byte after every engine
package.  For each (problem, seed) it records what a Metacat Mode run does, built from the
Metacat Standard Configuration (``seed_data/*.json`` through
``MetadataProvider.from_standard_configuration``) on the CPU numeric backend (float64), which is
deterministic:

* the answer, the codelet count and the final temperature;
* the RNG call count of **every codelet** (the draw count of each ``step_mcat``, so a
  refactor that moves one draw between codelets is caught even when the totals agree),
  kept in full in a gzip sidecar and as a digest in the main file;
* a hash of the trace events and a hash of the final state (the complete state graph
  plus the lockstep snapshot);
* the English corpus of the run: rule English, commentary, Verbose-mode narration, the
  trace display (print name and picture of every event) and the snag text, each as a
  count and a digest.

The set is the 19 demo problems at seeds 1-5, the justify problems at seeds 1-5, and one
8-run episode with Episodic Memory carried between the runs.

Nothing here edits or imports private state of the engine beyond what existing tests
already read; observation is by a counting RNG-free wrapper around ``step_mcat`` on the
runner *instance*, and by reading the finished context.

Verbose mode is on for every captured run so its narration is part of the baseline.
Narration reads and never decides, and the capture proves it on every run: a second
pass with Verbose mode off must give the same per-codelet RNG counts and the same state.

``capture`` returns text; ``scripts/capture_golden_baseline.py`` writes it and
``tests/lockstep/test_golden_baseline.py`` recomputes it and compares.
"""

from __future__ import annotations

import contextlib
import gzip
import hashlib
import io
import json
from collections import deque
from pathlib import Path
from typing import Any, Callable, Iterator

REPO_ROOT = Path(__file__).resolve().parents[2]
SEED_DIR = REPO_ROOT / "seed_data"
GOLDEN_DIR = REPO_ROOT / "tests" / "lockstep" / "golden"
BASELINE_PATH = GOLDEN_DIR / "engine_baseline.jsonl"
RNG_DETAIL_PATH = GOLDEN_DIR / "engine_baseline_rng.json.gz"

FORMAT = "petacat-golden-baseline/2"

#: The CPU role's float64 backend, pinned by name.  ``numpy`` agrees with the pure-Python
#: reference exactly (same values, same number of draws; TESTING.md, numeric backend
#: matrix), so a baseline captured on either is the same baseline.
BACKEND = "numpy"
#: The codelet cap of a run (Metacat's, as the lockstep harness sets it).
CAP = 100_000
SEEDS = (1, 2, 3, 4, 5)
EPISODE_PROBLEM = ("abc", "abd", "xyz")
EPISODE_SEED = 1
EPISODE_RUNS = 8

Problem = tuple[str, str, str]


# --------------------------------------------------------------------------- problems


def demo_problems(seed_dir: Path = SEED_DIR) -> tuple[list[Problem], list[tuple[Problem, str]]]:
    """``(discovery problems, justify problems)`` from ``demo_problems.json``.

    The 19 distinct (initial, modified, target) triples in file order, and the distinct
    (triple, answer) pairs of the justification demos in file order.
    """
    demos = json.loads((seed_dir / "demo_problems.json").read_text())
    triples: list[Problem] = []
    justify: list[tuple[Problem, str]] = []
    for d in demos:
        triple = (d["initial"], d["modified"], d["target"])
        if triple not in triples:
            triples.append(triple)
        if d.get("answer") and (triple, d["answer"]) not in justify:
            justify.append((triple, d["answer"]))
    return triples, justify


def case_id(kind: str, problem: Problem, answer: str | None, seed: int, run: int | None = None) -> str:
    base = f"{kind}/{'-'.join(problem)}" + (f"-{answer}" if answer else "")
    return f"{base}/{seed}" + (f".r{run}" if run is not None else "")


# --------------------------------------------------------------------------- hashing


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:20]


def canonical(obj: Any) -> str:
    """Deterministic JSON.  Refuses a value it cannot encode rather than guessing."""

    def refuse(value: Any) -> Any:
        if isinstance(value, (set, frozenset)):
            return sorted(value, key=repr)
        raise TypeError(f"golden baseline cannot encode {type(value).__name__}: {value!r}")

    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=refuse)


def digest_lines(lines: list[str]) -> list[Any]:
    """``[count, digest]`` of a list of text lines."""
    return [len(lines), sha("\n".join(lines))]


# --------------------------------------------------------------------------- capture of one run


@contextlib.contextmanager
def _unbounded_verbose_log() -> Iterator[None]:
    """Let Verbose mode keep every line of a run (the engine's log is a bounded buffer)."""
    import server.engine.runner as runner_module
    from server.engine.verbose import VerboseLog

    class Unbounded(VerboseLog):
        def __init__(self) -> None:
            super().__init__()
            self._lines = deque()

    original = runner_module.VerboseLog
    runner_module.VerboseLog = Unbounded  # type: ignore[misc]
    try:
        yield
    finally:
        runner_module.VerboseLog = original  # type: ignore[misc]


def run_observed(meta: Any, problem: Problem, seed: int, answer: str | None, memory: Any,
                 verbose: bool) -> tuple[Any, Any, list[int], list[str], int]:
    """Run to the end on the pinned backend.

    Returns ``(runner, rng, per_codelet_draws, codelet_types, draws_during_init)``.  The
    runner instance's ``step_mcat`` is wrapped, so the engine's own ``run_mcat`` loop
    drives the run unchanged and each step's draw count is read from ``rng.call_count``.
    """
    from server.engine.numeric.backend import use_backend
    from server.engine.rng import RNG
    from server.engine.runner import EngineRunner

    runner = EngineRunner(meta)
    runner.verbose_mode = verbose
    rng = RNG(seed)
    draws: list[int] = []
    types: list[str] = []
    real_step = runner.step_mcat

    def observed_step() -> Any:
        before = rng.call_count
        result = real_step()
        draws.append(rng.call_count - before)
        types.append(result.codelet_type or "")
        return result

    runner.step_mcat = observed_step  # type: ignore[method-assign]
    with use_backend(BACKEND):
        runner.init_mcat(*problem, answer=answer, seed=seed, memory=memory, rng=rng)
        init_draws = rng.call_count
        runner.run_mcat(max_steps=CAP)
    return runner, rng, draws, types, init_draws


def _trace_summary(events: list[Any]) -> list[Any]:
    return [
        [e.event_type, e.codelet_count, repr(float(e.temperature)), e.print_name,
         e.description, repr(float(e.strength)), bool(e.flipped), len(e.structures)]
        for e in events
    ]


def english_corpus(runner: Any, meta: Any) -> dict[str, list[str]]:
    """The run's English, as lists of text lines: rule English, commentary, Verbose
    narration, trace display and snag text.  A failure to produce one is recorded as a
    line, so a regression shows as a difference rather than a crash."""
    from server.engine.rule_english import transcribe_rule_to_english_lines
    from server.engine.rules import Rule
    from server.engine.trace import SNAG

    ctx = runner.ctx
    rule_lines: list[str] = []
    for ev in ctx.trace.events:
        for s in ev.structures:
            if isinstance(s, Rule):
                try:
                    text = " / ".join(transcribe_rule_to_english_lines(s, meta))
                except Exception as exc:  # noqa: BLE001 - recorded, not hidden
                    text = f"<{type(exc).__name__}: {exc}>"
                rule_lines.append(f"{ev.codelet_count}|{ev.event_type}|{text}")
    commentary = [
        f"{p.codelet_count}|{p.event_type}|{p.eliza_text}|{p.technical_text}"
        for p in ctx.commentary.get_paragraphs()
    ]
    verbose = [text for _, text in ctx.verbose_log._lines]
    display = [
        f"{ev.event_number}|{ev.print_name}|{canonical(ev.picture)}" for ev in ctx.trace.events
    ]
    snags = [
        f"{ev.codelet_count}|{ev.snag_type}|{ev.explanation}"
        for ev in ctx.trace.events if ev.event_type == SNAG
    ]
    return {"rule_english": rule_lines, "commentary": commentary, "verbose": verbose,
            "trace_display": display, "snag": snags}


def state_digest(ctx: Any) -> str:
    """The final state: the complete state graph and the lockstep snapshot, hashed."""
    from server.engine.state_graph import capture_run_state
    from tests.lockstep.snapshot import snapshot_record

    graph = capture_run_state(ctx)
    snap = snapshot_record(ctx, None, ctx.codelet_count)
    return sha(canonical({"graph": graph, "snapshot": snap}))


def capture_run(meta: Any, problem: Problem, seed: int, answer: str | None, memory: Any,
                kind: str, run: int | None = None, check_memory: Any = None,
                ) -> tuple[dict[str, Any], dict[str, Any]]:
    """One run's record and its detail (the full per-codelet draws and English text).

    ``memory`` is carried (and changed) by the run.  The verbose-off check run takes
    ``check_memory``, a second Episodic Memory that has followed the same chain of runs
    (a fresh one when omitted).
    """
    from server.engine.hashing import memory_hash
    from server.engine.memory import EpisodicMemory

    if check_memory is None:
        check_memory = EpisodicMemory()
    with _unbounded_verbose_log():
        runner, rng, draws, types, init_draws = run_observed(meta, problem, seed, answer, memory, True)
    ctx = runner.ctx
    state = state_digest(ctx)

    # Verbose mode only reads; prove it on this run.
    quiet, quiet_rng, quiet_draws, quiet_types, _ = run_observed(meta, problem, seed, answer, check_memory, False)
    if quiet_draws != draws or quiet_types != types or state_digest(quiet.ctx) != state:
        raise AssertionError(
            f"Verbose mode changed the run {case_id(kind, problem, answer, seed, run)}: "
            "narration must read and never decide"
        )

    english = english_corpus(runner, meta)
    answers = list(runner._answers)
    record: dict[str, Any] = {
        "id": case_id(kind, problem, answer, seed, run),
        "kind": kind,
        "problem": list(problem),
        "seed": seed,
        "justify": answer,
        "status": runner.status,
        "answer": answers[-1] if answers else None,
        "codelets": ctx.codelet_count,
        "temperature": repr(float(ctx.temperature.value)),
        "rng_init": init_draws,
        "rng_total": rng.call_count,
        "rng_per_codelet": sha(",".join(map(str, draws))),
        "codelet_types": sha(",".join(types)),
        "events": len(ctx.trace.events),
        "trace": sha(canonical(_trace_summary(ctx.trace.events))),
        "state": state,
        "english": {name: digest_lines(lines) for name, lines in english.items()},
    }
    if run is not None:
        record["run"] = run
        record["memory"] = memory_hash(memory)
    detail = {"id": record["id"], "rng_init": init_draws, "rng_per_codelet": draws,
              "codelet_types": types, "english": english}
    return record, detail


# --------------------------------------------------------------------------- the whole set


def load_meta(seed_dir: Path = SEED_DIR) -> Any:
    from server.engine.metadata import MetadataProvider

    return MetadataProvider.from_standard_configuration(str(seed_dir))


def iter_cases(meta: Any, progress: Callable[[str], None] | None = None,
               ) -> Iterator[tuple[dict[str, Any], dict[str, Any]]]:
    """Every case of the baseline, in a fixed order, as ``(record, detail)``."""
    from server.engine.memory import EpisodicMemory

    triples, justify = demo_problems()
    for problem in triples:
        for seed in SEEDS:
            if progress:
                progress(case_id("discovery", problem, None, seed))
            yield capture_run(meta, problem, seed, None, EpisodicMemory(), "discovery")
    for problem, answer in justify:
        for seed in SEEDS:
            if progress:
                progress(case_id("justify", problem, answer, seed))
            yield capture_run(meta, problem, seed, answer, EpisodicMemory(), "justify")
    memory, check_memory = EpisodicMemory(), EpisodicMemory()
    for k in range(1, EPISODE_RUNS + 1):
        seed = EPISODE_SEED + k - 1
        if progress:
            progress(case_id("episode", EPISODE_PROBLEM, None, seed, k))
        yield capture_run(meta, EPISODE_PROBLEM, seed, None, memory, "episode", run=k,
                          check_memory=check_memory)


def header_record(meta: Any) -> dict[str, Any]:
    triples, justify = demo_problems()
    return {
        "format": FORMAT,
        "configuration": "Metacat Standard Configuration (seed_data/*.json, from_seed_data)",
        "numeric_backend": BACKEND,
        "precision": "float64",
        "verbose_mode": "on (a verbose-off pass is checked equal for every run)",
        "cap": CAP,
        "seeds": list(SEEDS),
        "discovery_problems": len(triples),
        "justify_problems": len(justify),
        "episode": {"problem": list(EPISODE_PROBLEM), "first_seed": EPISODE_SEED, "runs": EPISODE_RUNS},
    }


def render(records: list[dict[str, Any]], meta: Any) -> str:
    """The main file: a header line, then one record per line, keys sorted."""
    lines = [canonical(header_record(meta))] + [canonical(r) for r in records]
    return "\n".join(lines) + "\n"


def render_rng_detail(details: list[dict[str, Any]]) -> bytes:
    """The gzip sidecar: every run's per-codelet draw counts, byte-reproducible (mtime 0)."""
    payload = {d["id"]: {"init": d["rng_init"], "per_codelet": d["rng_per_codelet"]} for d in details}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0, compresslevel=9) as gz:
        gz.write(raw)
    return buf.getvalue()


def render_text_dump(details: list[dict[str, Any]]) -> dict[str, str]:
    """Every run's full English and codelet type sequence, for diffing two captures
    (kept in the agents' workspace, not committed)."""
    out: dict[str, str] = {}
    for d in details:
        name = d["id"].replace("/", "__")
        for corpus, lines in d["english"].items():
            out[f"{name}.{corpus}.txt"] = "\n".join(lines) + "\n"
        out[f"{name}.codelet_types.txt"] = "\n".join(d["codelet_types"]) + "\n"
    return out


def capture(progress: Callable[[str], None] | None = None,
            ) -> tuple[str, bytes, list[dict[str, Any]]]:
    """The whole baseline: ``(main text, rng sidecar bytes, details)``."""
    meta = load_meta()
    records, details = [], []
    for record, detail in iter_cases(meta, progress):
        records.append(record)
        details.append(detail)
    return render(records, meta), render_rng_detail(details), details


def first_difference(expected: str, actual: str) -> str:
    """A readable account of where two baselines differ (first differing run and fields)."""
    exp, act = expected.splitlines(), actual.splitlines()
    for i, (a, b) in enumerate(zip(exp, act)):
        if a != b:
            try:
                ra, rb = json.loads(a), json.loads(b)
            except ValueError:
                return f"line {i + 1} differs:\n  expected {a[:200]}\n  actual   {b[:200]}"
            keys = sorted(k for k in set(ra) | set(rb) if ra.get(k) != rb.get(k))
            label = rb.get("id", f"line {i + 1}")
            return f"{label}: differing fields {keys}: " + "; ".join(
                f"{k}: expected {ra.get(k)!r}, actual {rb.get(k)!r}" for k in keys[:4])
    if len(exp) != len(act):
        return f"expected {len(exp)} lines, actual {len(act)}"
    return "identical"


def first_rng_divergence(expected_gz: bytes, actual_gz: bytes, run_id: str) -> str:
    """The first codelet at which a run's per-codelet draw counts differ."""
    exp = json.loads(gzip.decompress(expected_gz))[run_id]["per_codelet"]
    act = json.loads(gzip.decompress(actual_gz))[run_id]["per_codelet"]
    for i, (a, b) in enumerate(zip(exp, act)):
        if a != b:
            return f"{run_id}: first RNG divergence at codelet {i + 1}: expected {a} draws, actual {b}"
    return f"{run_id}: {len(exp)} expected codelets, {len(act)} actual"
