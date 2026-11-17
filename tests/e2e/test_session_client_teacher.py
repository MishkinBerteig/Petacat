"""``scripts/session_client.py --teacher`` drives a series file end to end against a running test server.

A real ``uvicorn`` server runs on a free port against the test database (serial child, the real engine).  The
script creates a session from the series file's problems, supplies each waiting run's next input over HTTP and
ends each run when its inputs are used up, then prints every run's conversation and writes them to ``--out``.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request

import pytest

from tests.e2e.conftest import TEST_DB_URL

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _pg(command: str, name: str) -> None:
    """``createdb`` or ``dropdb`` for *name* on the test database's instance."""
    u = urllib.parse.urlparse(TEST_DB_URL.replace("+asyncpg", ""))
    flags = ["-h", u.hostname, "-p", str(u.port or 5432), "-U", u.username]
    done = subprocess.run([command, *flags, *(["--if-exists"] if command == "dropdb" else []), name],
                          env={**os.environ, "PGPASSWORD": u.password or ""}, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


@pytest.fixture
def server():
    """A running server on its own empty database (start-up loads the Standard Configuration into an empty
    database only), dropped afterwards."""
    port = free_port()
    scratch = TEST_DB_URL.rsplit("/", 1)[1] + "_srv"
    _pg("dropdb", scratch)
    _pg("createdb", scratch)
    env = {**os.environ, "DATABASE_URL": TEST_DB_URL.rsplit("/", 1)[0] + "/" + scratch, "PETACAT_SESSION_EXECUTOR": "serial", "PYTHONPATH": ROOT,
           "PYTHONDONTWRITEBYTECODE": "1"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 120
        while True:
            if proc.poll() is not None:
                raise AssertionError("the test server exited: " + proc.stdout.read().decode()[-2000:])
            try:
                urllib.request.urlopen(url + "/api/training-mode/sessions", timeout=2).read()
                break
            except Exception:  # noqa: BLE001 - not up yet
                if time.monotonic() > deadline:
                    raise AssertionError("the test server did not start")
                time.sleep(0.5)
        yield url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
        if proc.stdout:
            proc.stdout.close()
        _pg("dropdb", scratch)


def test_the_teacher_script_drives_a_series_file_end_to_end(server, tmp_path):
    series = {"problems": [
        {"initial": "abc", "modified": "abd", "target": "ijk", "seeds": 2, "inputs": ["xyz"], "end_label": "series over"},
        {"initial": "ab", "modified": "ab", "target": "cd", "seeds": 2, "inputs": [], "end_label": "nothing to add"},
    ]}
    path, out = tmp_path / "series.json", tmp_path / "conversations.json"
    path.write_text(json.dumps(series), encoding="utf-8")
    done = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "session_client.py"), "--url", server, "--teacher", str(path),
         "--max-codelets", "800", "--backend", "off", "--timeout", "240", "--out", str(out)],
        cwd=ROOT, capture_output=True, text=True, timeout=300, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    assert done.returncode == 0, done.stdout + done.stderr
    conversations = json.loads(out.read_text(encoding="utf-8"))
    assert len(conversations) == 4 and "done: 4 runs" in done.stdout
    by_problem = {}
    for c in conversations:
        by_problem.setdefault(c["problem_id"], []).append(c)
    for c in by_problem[2]:  # no inputs: the first turn answers and the teacher ends the run at once
        assert [t["turn"] for t in c["turns"]] == [1] and (c["end_reason"], c["end_label"]) == ("teacher", "nothing to add")
        assert c["turns"][0]["positions"]["response"]
    for c in by_problem[1]:  # one input: turn 2 ran on the window; whatever it did, the run ended
        assert c["state"] == "ended" and c["turns"][0]["positions"]["response"]
        assert c["turns"][1]["positions"]["context"] == "abc abd ijk"
        assert c["turns"][1]["positions"]["input"] == "xyz" and c["turns"][1]["supplied_by"]["input"] == "teacher"
        assert c["end_reason"] in ("no-answer", "teacher")
    # a series file that already exists as --out is never overwritten
    again = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "session_client.py"), "--url", server, "--teacher", str(path),
         "--out", str(out)], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert again.returncode != 0 and "refusing to overwrite" in (again.stderr + again.stdout)
