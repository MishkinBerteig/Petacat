"""The extended golden baseline: the rare paths of Metacat Mode that the original 188 runs miss.

``tests/support/golden_baseline.py`` records 188 runs: the 19 demo problems and the justify
demos at seeds 1-5, and one 8-run episode.  A weight on a rare path can move without it
noticing, so this baseline records further cases, chosen by coverage (see
``tests/lockstep/README.md``, "The extended golden baseline"): each one reaches engine
code, a codelet body, a descriptor predicate or a posting formula that the original runs
leave unreached, or a feature (a kind of event, snag or clamp) they never show.

It reuses the original baseline's run record, hashes and English corpus unchanged
(``golden_baseline.capture_run``); only the set of cases differs, and the case list is data:
``tests/lockstep/golden/extended_cases.json``.  Every case runs under the file's
``parameters``, which are the faithful-mode parameters the lockstep harness replays Metacat
under (``initial_clamp_fixed_time``: the initial Slipnet clamp lapses at Metacat's fixed
codelet count, ``run.ss:151-154``).  So a case here is the configuration the Metacat
recordings were checked against, whereas the original baseline runs the Metacat Standard
Configuration's default (the update-cycle countdown).  Each case was recorded in Metacat
1.2 and replayed in Petacat with no divergence before it was admitted (the case file says so
per case); a case that did not match is a fidelity defect and is not here.

The file's ``backend`` is the numeric backend every case runs on: ``off``, the engine's own object-graph
loops, which is what the lockstep harness compares with Metacat (the original baseline runs NumPy).  A
case may name another (``python``, the pure-Python reference backend, replayed against Metacat with
``--numeric-backend python``).

A case is ``{"id", "kind", "problem", "seeds", "answer", "cap", "clear_before", "interventions",
"backend", "parameters", "why", "metacat"}`` (the last two are documentation: what it added, and its Metacat check):

* ``kind`` ``"discovery"`` or ``"justify"``: one run per seed, a fresh Episodic Memory each;
* ``kind`` ``"episode"``: one run per seed in order with one Episodic Memory carried, which is
  cleared before the runs listed in ``clear_before`` (a person pressing Clear Memory).  After
  the last run the episode's answer report is recorded too: the snag explanation, the
  two-voice explanation of every answer in memory and the comparison text of every ordered
  pair (``answers.ss`` ``get-snag-explanation``, ``explain``, ``get-answer-comparison-text``;
  the lockstep tool ``scripts/compare_episode_answers.py`` checks them against Metacat);
* ``parameters`` (optional) are the case's own faithful-mode parameters, laid over the file's: the cases
  that run with Self-watching mode off from the start say ``{"self_watching_enabled_default": false}``;
* ``cap`` is the case's codelet cap (the original baseline's ``CAP`` when absent);
* ``interventions`` are a person's actions at given codelet counts (``tests/support/interventions.py``):
  a codelet-pattern clamp, Clamp Themes, Undo last clamp, Self-watching mode off or on.

``capture`` returns text and bytes; ``scripts/capture_golden_baseline.py --extended`` writes
them and ``tests/lockstep/test_golden_extended.py`` recomputes and compares.
"""

from __future__ import annotations

import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Callable

from tests.support import golden_baseline as gb

CASES_PATH = gb.GOLDEN_DIR / "extended_cases.json"
BASELINE_PATH = gb.GOLDEN_DIR / "extended_baseline.jsonl"
RNG_DETAIL_PATH = gb.GOLDEN_DIR / "extended_baseline_rng.json.gz"

FORMAT = "petacat-golden-baseline-extended/1"


def load_cases(path: Path = CASES_PATH) -> dict[str, Any]:
    return json.loads(path.read_text())


def answers_report(meta: Any, memory: Any) -> dict[str, list[str]]:
    """The episode's answer report: what ``scripts/compare_episode_answers.py`` compares
    with Metacat, as lines (the answer's key, then the text)."""
    from server.engine.answer_comparison import (
        compare_answers_text,
        explain_answer,
        snag_explanation_for,
    )

    templates = meta.commentary_templates

    def key(a: Any) -> str:
        return "%s|%s" % (a.problem[3], "/".join(a.top_rule_description.split("\n")))

    ans: list[str] = []
    expl: list[str] = []
    cmp_: list[str] = []
    for a in memory.answers:
        ans.append("%s\t%s" % (key(a), snag_explanation_for(a, memory)))
        e = explain_answer(a, memory, templates, meta=meta)
        expl.append("%s\t%s\t%s" % (key(a), e["eliza_text"], e["technical_text"]))
    for a in memory.answers:
        for b in memory.answers:
            if a is not b:
                cmp_.append("%s\t%s\t%s" % (
                    key(a), key(b), compare_answers_text(a, b, memory, templates, meta=meta)["text"]))
    return {"answer": ans, "explanation": expl, "comparison": cmp_}


def capture_case(meta: Any, case: dict[str, Any], parameters: dict[str, Any],
                 backend: str | None = None,
                 ) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Every record of one case, as ``(record, detail)`` pairs."""
    from server.engine.hashing import memory_hash
    from server.engine.memory import EpisodicMemory

    parameters = {**parameters, **case.get("parameters", {})}
    problem = tuple(case["problem"])
    answer = case.get("answer")
    cap = case.get("cap")
    out: list[tuple[dict[str, Any], dict[str, Any]]] = []
    if case["kind"] == "episode":
        memory, check = EpisodicMemory(), EpisodicMemory()
        clears = set(case.get("clear_before", ()))
        for k, seed in enumerate(case["seeds"], 1):
            if k in clears and k > 1:
                memory.clear()
                check.clear()
            out.append(gb.capture_run(meta, problem, seed, answer, memory, "episode", run=k,
                                      check_memory=check, parameters=parameters, cap=cap,
                                      case=case["id"], backend=backend))
        report = answers_report(meta, memory)
        record = {
            "id": f"{case['id']}.answers", "kind": "episode_answers", "problem": list(problem),
            "answers": len(memory.answers),
            "report": {name: gb.digest_lines(lines) for name, lines in report.items()},
            "memory": memory_hash(memory),
        }
        out.append((record, {"id": record["id"], "report": report}))
    else:
        for seed in case["seeds"]:
            out.append(gb.capture_run(meta, problem, seed, answer, EpisodicMemory(), case["kind"],
                                      parameters=parameters, cap=cap, backend=backend,
                                      interventions=case.get("interventions"),
                                      case=f"{case['id']}/{seed}" if len(case["seeds"]) > 1 else case["id"]))
    return out


_META: Any = None


def _worker(args: tuple[dict[str, Any], dict[str, Any], str | None]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    global _META
    if _META is None:
        _META = gb.load_meta()
    case, parameters, backend = args
    return capture_case(_META, case, parameters, case.get("backend") or backend)


def iter_cases(jobs: int = 1, progress: Callable[[str], None] | None = None,
               cases: dict[str, Any] | None = None,
               ) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Every record of the baseline in the case file's order.  ``jobs`` > 1 runs the cases in
    a process pool; the result is the same, since a case depends on nothing outside itself."""
    spec = cases or load_cases()
    parameters = spec["parameters"]
    backend = spec.get("backend")
    work = [(c, parameters, backend) for c in spec["cases"]]
    results: list[Any] = []
    if jobs <= 1:
        meta = gb.load_meta()
        for c, p, b in work:
            if progress:
                progress(c["id"])
            results.append(capture_case(meta, c, p, c.get("backend") or b))
    else:
        with ProcessPoolExecutor(jobs) as pool:
            for c, res in zip(spec["cases"], pool.map(_worker, work, chunksize=1)):
                if progress:
                    progress(c["id"])
                results.append(res)
    return [pair for res in results for pair in res]


def normalised(x: Any) -> Any:
    """*x* with every number a float, so ``0`` and ``0.0`` are one value; nothing else is merged.

    A numeric backend may hold a quantity as an int on one path and a float on another (a
    zero, an activation that has never moved).  That is not a difference in what the run did,
    and it is the only difference the backends have in the final state (checked on all four).
    """
    if isinstance(x, bool):
        return x
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, list):
        return [normalised(v) for v in x]
    if isinstance(x, dict):
        return {k: normalised(v) for k, v in x.items()}
    return x


def capture_case_normalised(meta: Any, case: dict[str, Any], parameters: dict[str, Any],
                            backend: str | None) -> tuple[list[dict[str, Any]], list[str]]:
    """One case's records and the digest of each run's final state with numbers normalised.

    The digest is the one ``golden_baseline.state_digest`` takes (state graph without its parameter
    table, plus the lockstep snapshot), computed on ``normalised`` content.
    """
    from server.engine.state_graph import capture_run_state
    from tests.lockstep.snapshot import snapshot_record

    digests: list[str] = []
    original = gb.state_digest

    def spy(ctx: Any) -> str:
        graph = {k: v for k, v in capture_run_state(ctx).items() if k != "parameters"}
        snap = snapshot_record(ctx, None, ctx.codelet_count)
        digests.append(gb.sha(json.dumps(
            normalised(json.loads(gb.canonical({"graph": graph, "snapshot": snap}))), sort_keys=True)))
        return original(ctx)

    gb.state_digest = spy
    try:
        records = [r for r, _ in capture_case(meta, case, parameters, backend)]
    finally:
        gb.state_digest = original
    return records, digests


def _normalised_worker(args: tuple[dict[str, Any], dict[str, Any], str | None],
                       ) -> tuple[list[dict[str, Any]], list[str]]:
    global _META
    if _META is None:
        _META = gb.load_meta()
    case, parameters, backend = args
    return capture_case_normalised(_META, case, parameters, backend)


def capture_all_normalised(backend: str | None, jobs: int,
                           ) -> list[tuple[list[dict[str, Any]], list[str]]]:
    """Every case on *backend* (``None``: the case's own, as committed), cases in a process pool."""
    spec = load_cases()
    work = [(c, spec["parameters"], backend or c.get("backend") or spec["backend"]) for c in spec["cases"]]
    with ProcessPoolExecutor(jobs) as pool:
        return list(pool.map(_normalised_worker, work, chunksize=1))


def header_record(spec: dict[str, Any], cases_text: str) -> dict[str, Any]:
    return {
        "format": FORMAT,
        "configuration": "Metacat Standard Configuration (seed_data/*.json) + the case file's parameters",
        "parameters": spec["parameters"],
        "numeric_backend": spec.get("backend") or gb.BACKEND,
        "precision": "float64",
        "verbose_mode": "on (a verbose-off pass is checked equal for every run)",
        "default_cap": gb.CAP,
        "cases": len(spec["cases"]),
        "cases_file_sha": gb.sha(cases_text),
    }


def render(records: list[dict[str, Any]], spec: dict[str, Any], cases_text: str) -> str:
    lines = [gb.canonical(header_record(spec, cases_text))] + [gb.canonical(r) for r in records]
    return "\n".join(lines) + "\n"


def capture(jobs: int = 1, progress: Callable[[str], None] | None = None,
            ) -> tuple[str, bytes, list[dict[str, Any]]]:
    """The whole extended baseline: ``(main text, rng sidecar bytes, details)``."""
    cases_text = CASES_PATH.read_text()
    spec = json.loads(cases_text)
    pairs = iter_cases(jobs, progress, spec)
    records = [r for r, _ in pairs]
    details = [d for _, d in pairs]
    # the sidecar holds the runs' draw counts only; an episode's answer report has none
    runs = [d for d in details if "rng_per_codelet" in d]
    return render(records, spec, cases_text), gb.render_rng_detail(runs), details
