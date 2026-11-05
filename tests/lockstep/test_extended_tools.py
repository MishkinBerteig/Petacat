"""The tools behind the extended golden baseline, tested without Docker.

Three Metacat Mode surfaces were added to the recorder and the replay so that the extended
baseline's cases can be checked against Metacat: a person's codelet-pattern clamps and
"Undo last clamp" during a run (``record.py --intervene``, ``tests/support/interventions.py``),
the Clear Memory command between two runs of an episode (``--episode-clear-before``) and
Self-watching mode off (``--self-watching off``).  Recording needs Docker and the
``metacat:1.2`` image; these tests check the driver text the recorder writes, that the
interventions do what the product's own methods do, and that the replay side honours a
cleared memory.
"""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

import pytest

from tests.support import golden_baseline as gb
from tests.support import interventions

pytestmark = pytest.mark.lockstep

sys.path.insert(0, str(gb.REPO_ROOT / "tests" / "lockstep" / "metacat"))
import record  # noqa: E402


def test_the_intervention_list_parses_and_is_scheduled_in_scheme() -> None:
    ivs = record.parse_interventions("300:clamp-bottom_up,700:undo,900:clamp-group")
    assert ivs == [
        {"at": 300, "op": "clamp_codelet_pattern", "pattern": "bottom_up"},
        {"at": 700, "op": "undo_last_clamp"},
        {"at": 900, "op": "clamp_codelet_pattern", "pattern": "group"},
    ]
    text = record.driver_text(["abc", "abd", "xyz"], 1, 5000, "rev", True, False, "run", None, 0, (), ivs)
    assert "(set! *break-time* 300)" in text and "(set! *tr-cap* 5000)" in text
    assert "(cons 700 (lambda () (tell *trace* 'undo-last-clamp)))" in text
    # the Options menu's own sequence (gui.ss:1231-1245), with the group pattern against a very-low background
    assert "(against-background %very-low-urgency% %group-codelet-pattern%)" in text
    assert "'manual-clamp" in text and "(tell clamp-event 'activate)" in text
    # the header carries the list, so the replay applies the same actions
    assert '\\"interventions\\":[{\\"at\\":300' in text
    with pytest.raises(SystemExit):
        record.parse_interventions("300:clamp-nonsense")


def test_an_ordinary_driver_is_unchanged_by_the_new_options() -> None:
    plain = record.driver_text(["abc", "abd", "xyz"], 1, 5000, "rev", True, False, "run")
    assert "*tr-pending*" not in plain and "self-watching" not in plain
    assert "(set! *break-time* 5000)" in plain
    off = record.driver_text(["abc", "abd", "xyz"], 1, 5000, "rev", True, False, "run", None, 0, (), None, False)
    assert "(set! %self-watching-enabled% #f)" in off and '\\"self_watching\\":false' in off


def test_an_episode_driver_clears_memory_only_where_asked() -> None:
    text = record.driver_text(["abc", "abd", "xyz"], 1, 5000, "rev", True, False, "run", None, 4, (3, 1))
    assert text.count("(tell *memory* 'clear)") == 2  # once before run 1, once before run 3
    before_run3 = text.index('1.r3.metacat.jsonl')
    assert text.index("the user clears Episodic Memory before run 3") < before_run3
    assert '\\"memory_cleared\\":true' in text.split("1.r3.metacat.jsonl")[0].split("1.r2.metacat.jsonl")[-1]


def test_interventions_call_the_products_own_clamp_methods() -> None:
    """A clamp at codelet 150 is a manual-clamp event in the Trace, and Undo ends it."""
    from server.engine.memory import EpisodicMemory
    from server.engine.numeric.backend import use_backend
    from server.engine.rng import RNG
    from server.engine.runner import EngineRunner

    meta = gb.load_meta()
    runner = EngineRunner(meta)
    interventions.schedule(runner, [
        {"at": 150, "op": "clamp_codelet_pattern", "pattern": "bottom_up"},
        {"at": 160, "op": "undo_last_clamp"},
    ])
    seen: dict[str, object] = {}
    real = runner.step_mcat

    def watch():
        c = runner.ctx.codelet_count
        if c == 155:
            seen["within"] = runner.ctx.trace.within_clamp_period
        if c == 165:
            seen["after"] = runner.ctx.trace.within_clamp_period
        return real()

    runner.step_mcat = watch  # type: ignore[method-assign]
    # schedule() wrapped the original; wrap again so the watcher sees counts first
    with use_backend("off"):
        runner.init_mcat("abc", "abd", "xyz", seed=1, memory=EpisodicMemory(), rng=RNG(1),
                         parameters={"initial_clamp_fixed_time": True})
        runner.run_mcat(max_steps=200)
    kinds = [getattr(e, "clamp_type", None) for e in runner.ctx.trace.events]
    assert "manual_clamp" in kinds
    assert seen == {"within": True, "after": False}


def test_a_cleared_memory_header_is_honoured_by_the_answer_check(tmp_path: Path) -> None:
    from scripts import compare_episode_answers as cea

    for k in (1, 2, 3):
        head = {"t": "header", "problem": ["abc", "abd", "xyz"], "seed": k, "episode_run": k, "episode_seed": 1}
        if k == 3:
            head["memory_cleared"] = True
        with gzip.open(tmp_path / f"1.r{k}.metacat.jsonl.gz", "wt") as f:
            f.write(json.dumps(head) + "\n")
    assert cea.episode_clears(tmp_path / "1.r1.metacat.jsonl.gz") == (3,)


def test_the_coverage_tool_attributes_database_code_to_its_units() -> None:
    """``scripts/golden_coverage.py`` counts lines and branch arcs of code compiled from the
    database's strings: every codelet body, descriptor predicate and posting formula is in
    its universe, and its monitor sees a line and a branch of a code object so named."""
    from scripts import golden_coverage as gc

    meta = gb.load_meta()
    lines, branches, units = gc.db_universe(meta)
    assert sum(name.startswith("<codelet:") for name in units) == len(
        [s for s in meta.codelet_specs.values() if s.execute_body.strip()])
    assert any(name.startswith("<descriptor-predicate:") for name in units)
    assert any(name.startswith("<posting-formula:") for name in units)
    assert lines and branches and all(line > 0 for _, line in lines)

    monitor = gc.DbMonitor()
    code = compile("a = 1\nif x:\n    a = 2\n", "<codelet:probe>", "exec")
    monitor.start()
    try:
        exec(code, {"x": True})  # noqa: S102
    finally:
        monitor.stop()
    assert {line for name, line in monitor.lines if name == "<codelet:probe>"} == {1, 2, 3}
    assert len([b for b in monitor.branches if b[0] == "<codelet:probe>"]) == 1
