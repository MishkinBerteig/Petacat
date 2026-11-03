"""A session with a long journal starts without reading it (package S8; plan item 8a), and what
the journal costs per entry (plan item 9, last budget).

A Training Mode Session is Stopped and Started many times, each Stop writing the entries its
configuration changed.  The Start read loads the stored current state and checks it against the
stored ``config_hash``; it replays nothing.  So the cost of a Start must not depend on how long
the journal is.  Built here through the service (real Stops on a scratch database) to tens of
thousands of entries, then:

* a Start issues no statement that touches the journal table or the merge log, and issues the
  same statements as a Start of a session whose journal holds one entry;
* the configuration it loads hashes to the stored hash, and to the hash the live document had at
  the last Stop;
* the journal still replays: ``verify_journal`` agrees with the stored state over the long
  journal (replay and ``verify-journal`` stay tested for it);
* **journal growth** (a budget, run only with ``PETACAT_BUDGETS=1``): the stored size of an
  entry of code-free ops, by kind, is at most 4 KB (``pg_column_size`` of the whole row).

It is an e2e test (it uses ``tests/e2e``'s fixtures and the scratch database ``TEST_DATABASE_URL``
names); run it alone as::

    TEST_DATABASE_URL=postgresql+asyncpg://petacat:dev@localhost:5432/petacat_<x> \\
        .venv/bin/python -m pytest tests/e2e/test_session_long_journal.py -q -p no:cacheprovider
    PETACAT_BUDGETS=1 ...the same...   # adds the journal-growth budget (and prints the sizes)

``PETACAT_LONG_JOURNAL_ENTRIES`` sets the length of the long journal (default 30,000).
"""

from __future__ import annotations

import os
import time

import pytest
from sqlalchemy import text

from server.models.journal import JournalEntry
from server.models.training_mode_session import SessionMemoryMerge
from server.services import config_document as cd
from server.services import training_mode_session_service as bs
from server.services.configuration_admin import verify_journal
from tests.e2e.conftest import _db_available
from tests.e2e.test_session_configuration import (  # noqa: F401 - the fixtures
    external, factory_of, journal_count, serial_sessions, stored_document,
)
from tests.e2e.test_session_stop_start import Statements, configuration_state
from tests.e2e.test_training_mode_sessions_api import _api, create, stop

pytestmark = [
    pytest.mark.budget,
    pytest.mark.skipif(not _db_available(), reason="the scratch Postgres is not reachable"),
]

JOURNAL = JournalEntry.__tablename__
MERGES = SessionMemoryMerge.__tablename__
ENTRIES = int(os.environ.get("PETACAT_LONG_JOURNAL_ENTRIES", "30000"))
CYCLES = 12
GROWTH_KB = 4

#: The batch kinds the long journal is built from (all code-free), by the note that names them.
KINDS = {
    "adjust_param": lambda i: [{"op": "adjust_param", "name": "update_cycle_length", "by": 1 if i % 2 else -1}],
    "8_set_param": lambda i: [{"op": "set_param", "name": "update_cycle_length", "to": 10 + i % 7}]
    + [{"op": "set_param", "name": "initial_temperature", "to": 40.0 + (i + k) % 50} for k in range(7)],
    "move_layout": lambda i: [{"op": "move_layout", "node": "plato-a", "x": i % 500, "y": (i * 7) % 500}],
}


def batch_for(i: int) -> dict:
    kind = list(KINDS)[i % len(KINDS)]
    return external(*KINDS[kind](i), note=kind)


async def build_long_journal(client, service, engine, tid: int, entries: int) -> int:
    """Start, change and Stop *tid* until its journal holds *entries* entries; returns how many."""
    per_cycle = max(1, entries // CYCLES)
    total = 0
    for _ in range(CYCLES):
        resp = await client.post(_api(tid, "/start"), json={"paused": True})
        assert resp.status_code == 200, resp.text
        for _ in range(per_cycle):
            out = await service.submit_changes(tid, batch_for(total))
            assert out["ok"] is True
            total += 1
        await stop(client, tid)
    return total


@pytest.mark.asyncio
async def test_a_session_with_a_long_journal_starts_reading_no_journal(app_client, serial_sessions, test_engine):
    service = serial_sessions
    short = (await create(app_client, 0, start=False))["session"]["id"]
    await app_client.post(_api(short, "/start"), json={"paused": True})
    await service.submit_changes(short, batch_for(0))
    await stop(app_client, short)

    tid = (await create(app_client, 0, start=False, name="long journal"))["session"]["id"]
    built = time.perf_counter()
    total = await build_long_journal(app_client, service, test_engine, tid, ENTRIES)
    built = time.perf_counter() - built
    state = await configuration_state(test_engine, tid)
    assert state["entries"] == total >= min(ENTRIES, 10_000) - CYCLES
    assert state["revision"] == total and state["document_hash"] == state["row_hash"]
    stored_hash = state["row_hash"]

    async def start_statements(session_id: int):
        with Statements(test_engine) as seen:
            started = time.perf_counter()
            resp = await app_client.post(_api(session_id, "/start"), json={"paused": True})
            took = time.perf_counter() - started
        assert resp.status_code == 200, resp.text
        return list(seen.seen), took

    long_seen, long_took = await start_statements(tid)
    short_seen, short_took = await start_statements(short)
    live = service._live[tid].config
    # Zero statements touch the journal or the merge log, and the Start is the same work
    # whatever the journal's length.
    assert [s for s in long_seen if JOURNAL in s or MERGES in s] == []
    assert len(long_seen) == len(short_seen)
    assert live.config_hash == stored_hash == cd.config_hash(live.document)
    assert live.revision == total
    print(f"\nlong journal: {total} entries built in {built:.1f} s; Start of it {long_took * 1000:.1f} ms "
          f"({len(long_seen)} statements), Start of a one-entry journal {short_took * 1000:.1f} ms")
    await stop(app_client, tid)
    await stop(app_client, short)

    # The journal itself is intact: it replays to the stored state.
    async with factory_of(test_engine)() as s:
        verdict = await verify_journal(s, state["id"])
    assert verdict["ok"] is True, verdict


@pytest.mark.asyncio
async def test_journal_growth_per_entry(app_client, serial_sessions, test_engine):
    """The stored size of an entry, by the kind of batch (code-free), is at most 4 KB.

    Sizes are gathered from a journal of a few hundred entries of each kind; the budget is a
    property of the entry, not of the journal's length."""
    if os.environ.get("PETACAT_BUDGETS") != "1":
        pytest.skip("the journal-growth budget runs only with PETACAT_BUDGETS=1")
    service = serial_sessions
    tid = (await create(app_client, 0, start=False, name="growth"))["session"]["id"]
    await app_client.post(_api(tid, "/start"), json={"paused": True})
    for i in range(300):
        assert (await service.submit_changes(tid, batch_for(i)))["ok"] is True
    await stop(app_client, tid)
    state = await configuration_state(test_engine, tid)
    async with test_engine.connect() as conn:
        rows = (await conn.execute(text(
            f"SELECT note, count(*), avg(pg_column_size(j.*)), max(pg_column_size(j.*)) FROM {JOURNAL} j "
            "WHERE configuration_id = :c AND note <> '' GROUP BY note ORDER BY note"), {"c": state["id"]})).all()
    assert {r[0] for r in rows} == set(KINDS)
    for note, n, avg, biggest in rows:
        print(f"\nbudget journal row, {note}: {n} entries, average {avg:.0f} bytes, largest {biggest} bytes "
              f"(budget {GROWTH_KB} KB)")
        assert biggest <= GROWTH_KB * 1024
