"""The context-response benchmark (v2.0, increment 4, stage D): the series file and the script that runs it.

The series file ``measurements/context-response-benchmark/series.json`` is read both by the benchmark script and by
``scripts/session_client.py --teacher``, so it must load with ``load_series`` and hold the five accepted series.  The
script is run on one series, two seeds and a small codelet cap as a process of its own, on a scratch database named for the test database's with `_cr` added (dropped afterwards).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

from tests.e2e.conftest import TEST_DB_URL

REPO = Path(__file__).resolve().parents[2]
SERIES_FILE = REPO / "measurements" / "context-response-benchmark" / "series.json"
FIVE = [
    ("one", "two", "1", ["2", "3"]),
    ("bad", "good", "less", ["more", "old"]),
    ("1", "2", "3", ["1234", "12345"]),
    ("up", "down", "in", ["on", "yes"]),
    ("cat", "cats", "dog", ["pig", "cow"]),
]


def test_the_series_file_loads_with_the_session_client_and_holds_the_five_series():
    sys.path.insert(0, str(REPO / "scripts"))
    import session_client

    series = session_client.load_series(str(SERIES_FILE))
    assert [(p["initial"], p["modified"], p["target"], p["inputs"]) for p in series] == FIVE
    assert all(p["seeds"] == 50 and p["end_label"] == "series over" for p in series)


@pytest.mark.asyncio
async def test_the_script_runs_one_series_and_writes_conversations_and_a_summary(tmp_path):
    out = tmp_path / "bench"
    # the script loads the Metacat Standard Configuration into a database of its own (the test database's
    # configuration was seeded by the fixtures, which is not what start-up expects), so it gets a scratch one
    bench_url = f"{TEST_DB_URL}_cr"
    cmd = [sys.executable, str(REPO / "scripts" / "context_response_benchmark.py"), "--database-url", bench_url,
           "--out", str(out), "--series", "5", "--seeds", "2", "--max-codelets", "300"]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    try:
        done = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True, timeout=300)
        assert done.returncode == 0, done.stdout + done.stderr
        data = json.loads((out / "series-5.json").read_text(encoding="utf-8"))
        assert data["problem"] == {"initial": "cat", "modified": "cats", "target": "dog", "inputs": ["pig", "cow"]}
        assert data["settings"]["max_codelets"] == 300 and data["settings"]["backend"] == "off"
        assert data["settings"]["configuration_base"] == "training-v2"
        assert [c["seed"] for c in data["conversations"]] == [1, 2]
        for c in data["conversations"]:
            first = c["turns"][0]
            assert first["positions"]["context"] == "cat" and first["positions"]["input"] == "dog"
            assert set(first["evidence"]["coderack"]) == {"full_posts", "overflowing_batches", "evicted"}
        summary = (out / "SUMMARY.md").read_text(encoding="utf-8")
        assert "## Series 5: `cat:cats::dog:?`" in summary and "Evicted per codelet" in summary
        # it never overwrites
        again = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True, timeout=60)
        assert again.returncode != 0 and "never overwrites" in (again.stdout + again.stderr)
    finally:
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.pool import NullPool

        admin = create_async_engine(TEST_DB_URL.rsplit("/", 1)[0] + "/postgres", isolation_level="AUTOCOMMIT",
                                    poolclass=NullPool)
        async with admin.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{bench_url.rsplit("/", 1)[1]}"'))
        await admin.dispose()
