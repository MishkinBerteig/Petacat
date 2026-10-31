"""The golden baseline gate (G3, work package EN0).

``tests/lockstep/golden/engine_baseline.jsonl`` and ``engine_baseline_rng.json.gz`` were
captured from the engine before the first configuration-source engine edit, from the
Metacat Standard Configuration (``seed_data/*.json``) on the CPU numeric backend (float64).
They hold, for the 19 demo problems at seeds 1-5, the justify problems at seeds 1-5 and one
8-run episode with Episodic Memory carried: the answer, codelet count, final temperature,
the RNG call count of every codelet, the trace-event and final-state hashes, and the
English corpus (rule English, commentary, Verbose narration, trace display, snag text).

* ``test_the_baseline_files_are_consistent`` and ``test_a_sample_of_runs_reproduces`` are
  quick: the committed files agree with each other, and four runs recomputed in this process
  match their records.
* ``test_the_whole_baseline_reproduces_byte_for_byte`` (slow) recomputes everything in a
  fresh interpreter and compares both files byte for byte.  On a difference it names the
  first run and fields, and for the RNG sidecar the first codelet whose draw count moved.

The lockstep layer is outside the numeric-backend matrix (``tests/conftest.py``): the
capture pins the backend itself, by name, for the same reason faithful mode does.

To accept a deliberate change: ``.venv/bin/python scripts/capture_golden_baseline.py`` and
say so in the commit.
"""

from __future__ import annotations

import gzip
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.support import golden_baseline as gb

pytestmark = pytest.mark.lockstep

REPO_ROOT = gb.REPO_ROOT


def _records() -> list[dict]:
    lines = gb.BASELINE_PATH.read_text().splitlines()
    return [json.loads(line) for line in lines[1:]]


def test_the_baseline_files_are_consistent() -> None:
    lines = gb.BASELINE_PATH.read_text().splitlines()
    header = json.loads(lines[0])
    records = _records()
    assert header["format"] == gb.FORMAT
    assert header["numeric_backend"] == gb.BACKEND and header["precision"] == "float64"

    triples, justify = gb.demo_problems()
    assert len(triples) == 19 == header["discovery_problems"]
    kinds = [r["kind"] for r in records]
    assert kinds.count("discovery") == 19 * len(gb.SEEDS)
    assert kinds.count("justify") == len(justify) * len(gb.SEEDS)
    assert kinds.count("episode") == gb.EPISODE_RUNS
    assert len({r["id"] for r in records}) == len(records)

    sidecar = json.loads(gzip.decompress(gb.RNG_DETAIL_PATH.read_bytes()))
    assert set(sidecar) == {r["id"] for r in records}
    for r in records:
        draws = sidecar[r["id"]]["per_codelet"]
        assert len(draws) == r["codelets"], r["id"]
        assert gb.sha(",".join(map(str, draws))) == r["rng_per_codelet"], r["id"]
        assert sidecar[r["id"]]["init"] + sum(draws) == r["rng_total"], r["id"]
        assert set(r["english"]) == {"rule_english", "commentary", "verbose", "trace_display", "snag"}


def test_the_baseline_is_a_baseline_of_real_runs() -> None:
    """Most runs end in an answer, the rest by giving up (the jootser), none by the cap;
    the episode carried its memory (the hash changed)."""
    records = _records()
    assert all(r["status"] in ("answer_found", "gave_up") for r in records)
    assert sum(r["status"] == "answer_found" for r in records) > 0.8 * len(records)
    episode = [r for r in records if r["kind"] == "episode"]
    assert [r["run"] for r in episode] == list(range(1, gb.EPISODE_RUNS + 1))
    assert len({r["memory"] for r in episode}) > 1


def test_a_sample_of_runs_reproduces() -> None:
    from server.engine.memory import EpisodicMemory

    by_id = {r["id"]: r for r in _records()}
    meta = gb.load_meta()
    triples, justify = gb.demo_problems()
    cases = [
        (triples[3], None, 1, "discovery"),
        (triples[4], None, 2, "discovery"),
        (justify[0][0], justify[0][1], 3, "justify"),
        (justify[-1][0], justify[-1][1], 5, "justify"),
    ]
    for problem, answer, seed, kind in cases:
        record, _ = gb.capture_run(meta, problem, seed, answer, EpisodicMemory(), kind)
        assert record == by_id[record["id"]], gb.first_difference(
            json.dumps(by_id[record["id"]], sort_keys=True), json.dumps(record, sort_keys=True))


@pytest.mark.slow
def test_the_whole_baseline_reproduces_byte_for_byte(tmp_path: Path) -> None:
    env = dict(os.environ)
    env.pop("PETACAT_NUMERIC_BACKEND", None)
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "capture_golden_baseline.py"),
         "--out", str(tmp_path), "--quiet"],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=1800)
    assert result.returncode == 0, result.stderr[-2000:]

    expected = gb.BASELINE_PATH.read_text()
    actual = (tmp_path / gb.BASELINE_PATH.name).read_text()
    if actual != expected:
        message = gb.first_difference(expected, actual)
        # name the first codelet whose draw count moved, for the first differing run
        try:
            exp_ids = [json.loads(l)["id"] for l in expected.splitlines()[1:]]
            act = [json.loads(l) for l in actual.splitlines()[1:]]
            exp = [json.loads(l) for l in expected.splitlines()[1:]]
            for e, a in zip(exp, act):
                if e["rng_per_codelet"] != a["rng_per_codelet"]:
                    message += "\n" + gb.first_rng_divergence(
                        gb.RNG_DETAIL_PATH.read_bytes(),
                        (tmp_path / gb.RNG_DETAIL_PATH.name).read_bytes(), e["id"])
                    break
        except Exception as exc:  # noqa: BLE001 - the main message is what matters
            message += f"\n(could not localise the RNG divergence: {exc})"
        pytest.fail("golden baseline differs from the recomputed one.\n" + message)
    assert (tmp_path / gb.RNG_DETAIL_PATH.name).read_bytes() == gb.RNG_DETAIL_PATH.read_bytes(), \
        "per-codelet RNG sidecar differs"


def test_the_baseline_notices_a_change_in_behaviour() -> None:
    """Sensitivity: the same run under a different update-cycle length (which moves where
    the update cycle's draws fall) must not match the baseline, in the per-codelet digest."""
    from server.engine.memory import EpisodicMemory

    by_id = {r["id"]: r for r in _records()}
    triples, _ = gb.demo_problems()
    meta = gb.load_meta().with_overrides({"update_cycle_length": 14})
    record, _ = gb.capture_run(meta, triples[3], 1, None, EpisodicMemory(), "discovery")
    committed = by_id[record["id"]]
    assert record["rng_per_codelet"] != committed["rng_per_codelet"]
    assert record["state"] != committed["state"]
