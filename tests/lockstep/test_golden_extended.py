"""The extended golden baseline gate (round 2 of the Metacat finish).

``tests/lockstep/golden/extended_baseline.jsonl`` and ``extended_baseline_rng.json.gz`` were
captured, before any round-2 engine change, from the case list
``tests/lockstep/golden/extended_cases.json``.  The cases were chosen by coverage: each one
reaches engine code, a codelet body, a descriptor predicate or a posting formula, or a feature
(event, snag or clamp kind) that the original 188 runs of ``test_golden_baseline.py`` leave
unreached.  Each was also recorded in Metacat 1.2 and replayed in Petacat with no divergence;
the case file records that per case, and a case that did not match is not in it (it is a
fidelity defect, not a baseline).  See ``tests/support/golden_extended.py`` for the format and
``tests/lockstep/README.md``, "The extended golden baseline", for how the cases were chosen.

* ``test_the_extended_files_are_consistent`` and ``test_a_sample_of_extended_runs_reproduces``
  are quick: the committed files agree with each other and with the case list, and a few runs
  recomputed in this process match their records.
* ``test_the_whole_extended_baseline_reproduces_byte_for_byte`` (slow) recomputes everything
  in a fresh interpreter, cases spread over a process pool, and compares both files byte for
  byte.  On a difference it names the first run and fields, and for the RNG sidecar the first
  codelet whose draw count moved.

The lockstep layer is outside the numeric-backend matrix (``tests/conftest.py``); the capture
pins the backend by name.  To accept a deliberate change:
``.venv/bin/python scripts/capture_golden_baseline.py --extended --jobs 8`` and say so in
the commit.
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
from tests.support import golden_extended as ge

pytestmark = pytest.mark.lockstep

REPO_ROOT = gb.REPO_ROOT


def _records() -> list[dict]:
    return [json.loads(line) for line in ge.BASELINE_PATH.read_text().splitlines()[1:]]


def _spec() -> dict:
    return json.loads(ge.CASES_PATH.read_text())


def test_the_extended_files_are_consistent() -> None:
    lines = ge.BASELINE_PATH.read_text().splitlines()
    header = json.loads(lines[0])
    records = _records()
    spec = _spec()
    assert header["format"] == ge.FORMAT
    assert header["numeric_backend"] == spec["backend"] == "off" and header["precision"] == "float64"
    assert header["cases_file_sha"] == gb.sha(ge.CASES_PATH.read_text())
    assert header["cases"] == len(spec["cases"])
    assert header["parameters"] == spec["parameters"]

    # every case is in the file exactly as the case list says, and nothing else is
    expected_ids: list[str] = []
    for case in spec["cases"]:
        assert case["metacat"]["match"] is True, f"{case['id']} did not match Metacat"
        if case["kind"] == "episode":
            expected_ids += [f"{case['id']}.r{k}" for k in range(1, len(case["seeds"]) + 1)]
            expected_ids.append(f"{case['id']}.answers")
        else:
            expected_ids += [f"{case['id']}/{s}" if len(case["seeds"]) > 1 else case["id"]
                             for s in case["seeds"]]
    assert [r["id"] for r in records] == expected_ids

    sidecar = json.loads(gzip.decompress(ge.RNG_DETAIL_PATH.read_bytes()))
    runs = [r for r in records if r["kind"] != "episode_answers"]
    assert set(sidecar) == {r["id"] for r in runs}
    for r in runs:
        draws = sidecar[r["id"]]["per_codelet"]
        assert len(draws) == r["codelets"], r["id"]
        assert gb.sha(",".join(map(str, draws))) == r["rng_per_codelet"], r["id"]
        assert sidecar[r["id"]]["init"] + sum(draws) == r["rng_total"], r["id"]
        assert set(r["english"]) == {"rule_english", "commentary", "verbose", "trace_display", "snag"}
        case_of = next(c for c in spec["cases"]
                       if r["id"] == c["id"] or r["id"].startswith(c["id"] + "/") or r["id"].startswith(c["id"] + ".r"))
        assert r["parameters"] == {**spec["parameters"], **case_of.get("parameters", {})}
        assert r["numeric_backend"] == next(
            c.get("backend", spec["backend"]) for c in spec["cases"] if r["id"].startswith(c["id"]))
    for r in records:
        if r["kind"] == "episode_answers":
            assert set(r["report"]) == {"answer", "explanation", "comparison"}
            # n answers give n explanations and n(n-1) ordered pairs
            n = r["answers"]
            assert r["report"]["explanation"][0] == n and r["report"]["comparison"][0] == n * (n - 1)


def test_the_extended_baseline_is_a_baseline_of_real_runs() -> None:
    """A run ends in an answer, by giving up, or at the case's own codelet cap (status ``halted``,
    exactly ``cap`` codelets); the set reaches what the original baseline does not."""
    records = _records()
    spec = _spec()
    caps = {c["id"]: c.get("cap") for c in spec["cases"]}
    runs = [r for r in records if r["kind"] != "episode_answers"]
    for r in runs:
        assert r["status"] in ("answer_found", "gave_up", "halted"), r["id"]
        if r["status"] == "halted":
            case_id = r["id"].split(".r")[0] if r["kind"] == "episode" else r["id"]
            cap = next(v for k, v in caps.items() if case_id == k or case_id.startswith(k + "/"))
            assert cap is not None and r["codelets"] == cap == r["cap"], r["id"]
    assert {r["kind"] for r in records} == {"discovery", "justify", "episode", "episode_answers"}
    assert any(r["status"] == "halted" for r in runs)  # the codelet-cap path is in the set
    assert any(r.get("interventions") for r in runs)  # a person's clamps are in the set
    assert any(r.get("numeric_backend") == "python" for r in runs)  # the pure-Python backend is in the set
    cleared = [c for c in spec["cases"] if c.get("clear_before")]
    assert cleared  # Clear Memory between two runs of an episode is in the set


def test_a_sample_of_extended_runs_reproduces() -> None:
    by_id = {r["id"]: r for r in _records()}
    spec = _spec()
    meta = gb.load_meta()
    # the cheapest case of each kind
    picked: dict[str, dict] = {}
    cost = {r["id"]: r["codelets"] for r in by_id.values() if "codelets" in r}
    for case in spec["cases"]:
        total = sum(v for k, v in cost.items() if k.startswith(case["id"] + "/") or k == case["id"]
                    or k.startswith(case["id"] + ".r"))
        kind = case["kind"]
        if kind not in picked or total < picked[kind][0]:
            picked[kind] = (total, case)
    assert set(picked) == {"discovery", "justify", "episode"}
    for _, case in picked.values():
        for record, _detail in ge.capture_case(meta, case, spec["parameters"], case.get("backend") or spec["backend"]):
            assert record == by_id[record["id"]], gb.first_difference(
                json.dumps(by_id[record["id"]], sort_keys=True), json.dumps(record, sort_keys=True))


@pytest.mark.slow
def test_the_whole_extended_baseline_reproduces_byte_for_byte(tmp_path: Path) -> None:
    env = dict(os.environ)
    env.pop("PETACAT_NUMERIC_BACKEND", None)
    jobs = max(1, min(8, (os.cpu_count() or 2) - 1))
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "capture_golden_baseline.py"),
         "--extended", "--jobs", str(jobs), "--out", str(tmp_path), "--quiet"],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=3000)
    assert result.returncode == 0, result.stderr[-2000:]

    expected = ge.BASELINE_PATH.read_text()
    actual = (tmp_path / ge.BASELINE_PATH.name).read_text()
    if actual != expected:
        message = gb.first_difference(expected, actual)
        try:
            exp = [json.loads(l) for l in expected.splitlines()[1:]]
            act = [json.loads(l) for l in actual.splitlines()[1:]]
            for e, a in zip(exp, act):
                if e.get("rng_per_codelet") != a.get("rng_per_codelet"):
                    message += "\n" + gb.first_rng_divergence(
                        ge.RNG_DETAIL_PATH.read_bytes(),
                        (tmp_path / ge.RNG_DETAIL_PATH.name).read_bytes(), e["id"])
                    break
        except Exception as exc:  # noqa: BLE001 - the main message is what matters
            message += f"\n(could not localise the RNG divergence: {exc})"
        pytest.fail("extended golden baseline differs from the recomputed one.\n" + message)
    assert (tmp_path / ge.RNG_DETAIL_PATH.name).read_bytes() == ge.RNG_DETAIL_PATH.read_bytes(), \
        "extended per-codelet RNG sidecar differs"


#: The numeric backends a run can use.  ``off`` (the engine's own loops) is what the committed
#: records ran on; these four must do the same thing as it.
CROSS_BACKENDS = ["numpy", "python", "mlx-cpu", "mlx"]


@pytest.fixture(scope="module")
def committed_backend_runs() -> list:
    """Every extended case recomputed on its committed backend, with normalised state digests."""
    return ge.capture_all_normalised(None, max(1, min(8, (os.cpu_count() or 2) - 1)))


@pytest.mark.slow
@pytest.mark.parametrize("backend", CROSS_BACKENDS)
def test_every_extended_case_does_the_same_on_each_numeric_backend(backend: str, committed_backend_runs) -> None:
    """The rare paths of Metacat Mode do not depend on the numeric backend.

    The committed records ran on ``off`` (three cases on ``python``).  Here every case runs on
    *backend* and is compared with the committed backend's recomputation: every field of every
    record (the answer, the codelet count, the draws of each codelet, the English, the hashes) and
    the final state with numbers normalised (a value that is ``0`` on one path and ``0.0`` on
    another is one value; the raw ``state`` hash differs only so).  A backend that is not
    available here is a skip, never a pass.
    """
    from server.engine.numeric.backend import available_backends

    if backend not in available_backends():
        pytest.skip(f"numeric backend {backend!r} is not available here")
    jobs = max(1, min(8, (os.cpu_count() or 2) - 1))
    other = ge.capture_all_normalised(backend, jobs)
    spec = _spec()
    differences: list[str] = []
    runs = 0
    for case, (recs_a, states_a), (recs_b, states_b) in zip(spec["cases"], committed_backend_runs, other):
        if states_a != states_b:
            differences.append(f"{case['id']}: the final state differs beyond number form")
        for a, b in zip(recs_a, recs_b):
            runs += 1
            keys = (set(a) | set(b)) - {"numeric_backend", "state"}
            bad = sorted(k for k in keys if a.get(k) != b.get(k))
            if bad:
                differences.append(f"{a['id']}: {bad}")
        assert len(recs_a) == len(recs_b)
    assert runs == len(_records())
    assert not differences, f"on {backend}:\n" + "\n".join(differences[:20])


def test_the_extended_baseline_notices_a_change_in_behaviour() -> None:
    """Sensitivity: one case under a different update-cycle length must not match."""
    by_id = {r["id"]: r for r in _records()}
    spec = _spec()
    case = next(c for c in spec["cases"] if c["kind"] == "discovery")
    meta = gb.load_meta().with_overrides({"update_cycle_length": 14})
    record, _ = ge.capture_case(meta, case, spec["parameters"], spec["backend"])[0]
    committed = by_id[record["id"]]
    assert record["rng_per_codelet"] != committed["rng_per_codelet"] or record["state"] != committed["state"]
