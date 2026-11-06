"""Every run in either golden baseline has a lockstep ratchet entry (ruling 76).

The golden baselines are Petacat against its own stored runs.  The ratchets are Petacat against
patched Metacat.  A run that is only in a golden baseline has never been compared with Metacat
in the replay, so this test reads the committed golden and ratchet files and fails for any run
without an entry:

* ``golden/engine_baseline.jsonl`` (188 runs): discovery runs are in ``ratchet.json``, justify runs
  in ``ratchet-justify.json``, the eight runs of its episode in ``ratchet-episodes.json``;
* ``golden/extended_baseline.jsonl`` (114 runs, besides the 8 ``episode_answers`` lines, which
  ``scripts/compare_episode_answers.py`` checks): every run is in ``ratchet-extended.json``, under
  ``<case id>|<layout slug>/<seed>`` (``scripts/lockstep_corpus.py --extended``).

Every ratchet entry has agreement 1.0, no unregistered error and no differing state snapshot.
"""

from __future__ import annotations

import json
from pathlib import Path

LOCKSTEP = Path(__file__).resolve().parent
GOLDEN = LOCKSTEP / "golden"


def _lines(name: str) -> tuple[dict, list[dict]]:
    rows = [json.loads(line) for line in (GOLDEN / name).read_text().splitlines() if line.strip()]
    return rows[0], rows[1:]


def _ratchet(name: str) -> dict:
    return json.loads((LOCKSTEP / name).read_text())


def original_keys() -> list[tuple[str, str]]:
    """``(ratchet file, key)`` of every run of ``engine_baseline.jsonl``."""
    header, runs = _lines("engine_baseline.jsonl")
    out = []
    for run in runs:
        slug = "-".join(run["problem"])
        if run["kind"] == "discovery":
            out.append(("ratchet.json", f"{slug}/{run['seed']}"))
        elif run["kind"] == "justify":
            out.append(("ratchet-justify.json", f"justify/{slug}-{run['justify']}/{run['seed']}"))
        elif run["kind"] == "episode":
            out.append(("ratchet-episodes.json",
                        f"episodes/{slug}/{header['episode']['first_seed']}.r{run['run']}"))
        else:
            raise AssertionError(f"unknown kind in engine_baseline.jsonl: {run['id']}")
    return out


def extended_keys() -> list[str]:
    """``ratchet-extended.json`` key of every run of ``extended_baseline.jsonl``."""
    cases = json.loads((GOLDEN / "extended_cases.json").read_text())["cases"]
    _, runs = _lines("extended_baseline.jsonl")
    out = []
    for run in runs:
        if run["kind"] == "episode_answers":
            continue
        owners = [c for c in cases if run["id"] == c["id"] or run["id"].startswith(c["id"] + "/")
                  or run["id"].startswith(c["id"] + ".r")]
        assert owners, f"no case in extended_cases.json for {run['id']}"
        case = max(owners, key=lambda c: len(c["id"]))
        slug = "-".join(case["problem"] + ([case["answer"]] if case.get("answer") else []))
        if run["kind"] == "episode":
            out.append(f"{case['id']}|episodes/{slug}/{case['seeds'][0]}.r{run['run']}")
        elif run["kind"] == "justify":
            out.append(f"{case['id']}|justify/{slug}/{run['seed']}")
        else:
            out.append(f"{case['id']}|{slug}/{run['seed']}")
    return out


def test_the_golden_baselines_have_the_runs_this_test_counts():
    assert len(original_keys()) == 188
    assert len(extended_keys()) == 114
    assert len(set(extended_keys())) == 114


def test_every_original_golden_run_has_a_ratchet_entry():
    missing = [(f, k) for f, k in original_keys() if k not in _ratchet(f)]
    assert not missing, f"{len(missing)} golden runs have no ratchet entry, e.g. {missing[:5]}"


def test_every_extended_golden_run_has_a_ratchet_entry():
    ratchet = _ratchet("ratchet-extended.json")
    missing = [k for k in extended_keys() if k not in ratchet]
    assert not missing, f"{len(missing)} extended golden runs have no ratchet entry, e.g. {missing[:5]}"


def test_every_ratchet_entry_is_a_clean_replay():
    for name in ("ratchet.json", "ratchet-justify.json", "ratchet-episodes.json", "ratchet-extended.json"):
        for key, entry in _ratchet(name).items():
            assert entry["agreement"] == 1.0, (name, key)
            assert entry["unregistered_errors"] == 0, (name, key)
            assert entry["state_snapshots_differing"] == 0, (name, key)
