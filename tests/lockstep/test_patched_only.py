"""The lockstep harness runs only the patched Metacat (ruling 70).

"Patched" is ``Metacat/build/source`` with the bundle's second patch group, the known-failure
fixes.  Nothing in the harness may run the unpatched reconstruction, so:

* ``record.py`` has no flag that picks the build or takes the fixes off;
* every recorder reaches Docker through ``record.run_container``, which refuses a tree that
  does not verify as the patched build (proved here with a tree that fails verification, and
  with ``describe`` made to answer "reference"; no fix is taken off any tree);
* every trace header the corpora hold ends in ``+known-failure-fixes``, with no exception.  (The
  recordings of the three crashes of the build without the fixes were removed on 2026-11-08, at the
  user's ruling; ``Metacat/KNOWN-FAILURES.md`` holds the record of how to reproduce each crash.)
"""

from __future__ import annotations

import ast
import gzip
import json
import subprocess
from pathlib import Path

import pytest

import sys

LOCKSTEP = Path(__file__).resolve().parent
METACAT_DIR = LOCKSTEP / "metacat"
sys.path.insert(0, str(METACAT_DIR))

import record  # noqa: E402
MARK = "+known-failure-fixes"


def _no_docker(monkeypatch) -> list:
    """Make any attempt to start Docker fail; other processes (``patch``) still run."""
    calls: list = []
    real = subprocess.run

    def guarded(cmd, *args, **kwargs):
        if cmd and cmd[0] == "docker":
            calls.append(cmd)
            raise AssertionError("Docker was reached")
        return real(cmd, *args, **kwargs)

    monkeypatch.setattr(record.subprocess, "run", guarded)
    return calls


def test_record_has_no_way_to_choose_the_build():
    source = (METACAT_DIR / "record.py").read_text()
    for word in ("--reference", "--known-failures-patch", "remove_fixes", "known_failures_patch"):
        assert word not in source, f"record.py still mentions {word!r}"
    flags = [node.args[0].value for node in ast.walk(ast.parse(source))
             if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "add_argument"
             and node.args and isinstance(node.args[0], ast.Constant)]
    assert "--reference" not in flags and "--known-failures-patch" not in flags


def test_every_recorder_reaches_docker_only_through_the_guard():
    """Only record.py starts a process; the others call run_container or wrap.run_driver, and the
    ones that call run_container themselves also call require_patched first."""
    for path in sorted(METACAT_DIR.glob("*.py")):
        if path.name in ("record.py",):
            continue
        text = path.read_text()
        assert "docker_command" not in text and '"docker"' not in text, f"{path.name} starts Docker itself"
        assert "subprocess" not in text, f"{path.name} starts a process of its own"
        assert "recorder-source" not in text and "SOURCE =" not in text, path.name
        if "record.run_container" in text:
            assert "record.require_patched()" in text, f"{path.name} runs a container without the check"
    wrap = (METACAT_DIR / "wrap.py").read_text()
    assert "record.require_patched()" in wrap and "record.run_container(record.SOURCE" in wrap


def test_the_recorder_copy_must_be_marked_patched(tmp_path, monkeypatch):
    calls = _no_docker(monkeypatch)
    monkeypatch.setattr(record, "require_patched", lambda: None)
    copy = tmp_path / "copy"
    copy.mkdir()
    (copy / ".recorder-patch.sha256").write_text("reference+abc\n")
    monkeypatch.setattr(record, "RECORDER_SOURCE", copy)
    with pytest.raises(SystemExit):
        record.run_container(copy, tmp_path, 5)
    assert calls == []


def test_run_container_refuses_a_tree_that_does_not_verify(tmp_path, monkeypatch):
    calls = _no_docker(monkeypatch)
    bogus = tmp_path / "source"
    bogus.mkdir()
    (bogus / "x.ss").write_text("(display 1)\n")
    monkeypatch.setattr(record, "SOURCE", bogus)
    with pytest.raises(SystemExit) as exc:
        record.run_container(bogus, tmp_path, 5)
    assert "patched" in str(exc.value).lower()
    with pytest.raises(SystemExit):
        record.source_state()
    with pytest.raises(SystemExit):
        record.ensure_recorder_source()
    assert calls == []


def test_run_container_refuses_a_source_that_is_not_the_build(tmp_path, monkeypatch):
    calls = _no_docker(monkeypatch)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    with pytest.raises(SystemExit):
        record.run_container(elsewhere, tmp_path, 5)
    assert calls == []


def test_run_container_refuses_a_tree_that_verifies_as_the_reference(tmp_path, monkeypatch):
    """No fix is taken off any tree: ``describe`` is made to answer "reference" for a plain directory."""
    calls = _no_docker(monkeypatch)
    tree = tmp_path / "source"
    tree.mkdir()

    class Reconstruct:
        @staticmethod
        def describe(root, manifest):
            return "reference"

    monkeypatch.setattr(record, "_reconstruct", lambda: Reconstruct)
    monkeypatch.setattr(record, "_manifest", lambda: {})
    monkeypatch.setattr(record, "SOURCE", tree)
    with pytest.raises(SystemExit) as exc:
        record.run_container(tree, tmp_path, 5)
    assert "patched" in str(exc.value).lower()
    with pytest.raises(SystemExit):
        record.ensure_recorder_source()
    with pytest.raises(SystemExit):
        record.source_state()
    assert calls == []


def _corpus_traces():
    for path in sorted(LOCKSTEP.glob("traces*/**/*.metacat.jsonl.gz")):
        yield path


def test_every_stored_trace_header_is_patched():
    checked = 0
    unpatched = []
    for path in _corpus_traces():
        with gzip.open(path, "rt") as handle:
            header = json.loads(handle.readline())
        checked += 1
        if not header["revision"].endswith(MARK):
            unpatched.append(str(path.relative_to(LOCKSTEP)))
    if checked == 0:
        pytest.skip("no stored trace is present")
    assert not unpatched, f"{len(unpatched)} traces are not from the patched build, e.g. {unpatched[:5]}"


def test_the_recordings_of_the_crashes_of_the_unpatched_build_are_gone():
    # Removed on 2026-11-08 at the user's ruling.  Metacat/KNOWN-FAILURES.md is the record.
    assert not (LOCKSTEP / "traces-known-failures" / "reference").exists()
    assert not list(LOCKSTEP.glob("traces*/**/reference/*.metacat.jsonl.gz"))
