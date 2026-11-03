"""A worker never writes the journal (package S8; evolution plan item 6d).

A worker process receives a task (a problem, a seed, a memory reference and a pickled
configuration), runs the engine and returns an outcome.  The journal belongs to the service's
Stop write.  Checked by what a worker process can reach:

* in a fresh interpreter that imports the worker-side modules and runs a task, neither the
  journal layer, the database driver nor the ORM is ever imported, so nothing in a worker can
  write a journal row (the swarm worker module is imported too);

The serial child and the swarm workers run exactly this code (``run_task`` / ``run_one`` through
``begin_run``), and the transport tests in ``test_session_transport.py`` run them for real.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap

from server.parallel.swarm import SEED_DIR

FORBIDDEN = ("server.services.journal", "sqlalchemy", "asyncpg", "server.models")

PROBE = textwrap.dedent(
    """
    import json, sys
    from server.engine.metadata import MetadataProvider
    from server.parallel import swarm  # the swarm worker module as well
    from server.services import training_mode_session_executor as ex
    meta = MetadataProvider.from_standard_configuration(sys.argv[1])
    task = ex.SessionTask("abc", "abd", "xyz", None, 1, 60, None, "off", config=ex._Shipper().ship(meta))
    out = ex.run_task(task)
    bad = sorted(m for m in sys.modules if any(m == f or m.startswith(f + ".") for f in %r))
    print(json.dumps({"status": out.status, "forbidden": bad}))
    """
) % (FORBIDDEN,)


def test_a_worker_side_run_loads_no_journal_database_or_orm_module():
    done = subprocess.run(
        [sys.executable, "-I", "-c", PROBE, SEED_DIR], capture_output=True, text=True, timeout=120,
        env={"PYTHONPATH": ".", "PATH": ""}, check=False,
    )
    assert done.returncode == 0, done.stderr
    got = json.loads(done.stdout.strip().splitlines()[-1])
    assert got["forbidden"] == [], got
    assert got["status"]
