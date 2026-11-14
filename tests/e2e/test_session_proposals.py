"""A Training Mode Session keeps everything a run proposes: links, link types, counts and triggers.

Through the real service, on the serial child and on the swarm, with a test configuration whose codelet body
calls ``propose_ops`` (``tests/support/proposing_configuration.py``, installed through the session's change
API before the session starts).  Every op reaches the session's configuration through the in-worker learner
(actor ``learner:in-worker``), a duplicate from a later run is skipped cleanly, the pair's link is
``90 - 0.125 * (N - 1)`` long after ``N`` noticings, and the serial child and the swarm give the same first run.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from server.services import training_mode_session_service as bs
from server.services.training_mode_session_executor import (
    SerialExecutor, SwarmExecutor, outcome_fingerprint,
)
from tests.e2e.test_training_mode_sessions_api import (
    make_service, runs_of, stop, until_state,
)
from tests.e2e.test_v2_base_sessions import Recording
from tests.support import proposing_configuration as pc

PROBLEM = ("abc", "abd", "xyz")


async def make_session(client, seeds):
    body = {"name": "proposals", "settings": {"seeds_per_problem": seeds, "max_codelets": 900},
            "problems": [{"initial": PROBLEM[0], "modified": PROBLEM[1], "target": PROBLEM[2]}]}
    resp = await client.post("/api/training-mode/sessions", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()["session"]["id"]


@pytest.mark.asyncio
async def test_every_proposal_reaches_the_sessions_configuration_and_the_routes_agree(app_client, test_engine):
    from server.api.runs import get_run_service

    meta = get_run_service().meta
    firsts, lengths = {}, {}
    for kind, inner in (("serial", SerialExecutor()), ("swarm", SwarmExecutor(base=meta))):
        async with test_engine.begin() as conn:
            await conn.execute(text("DELETE FROM training_mode_sessions"))
        executor = Recording(inner)
        service = make_service(test_engine, meta, executor=executor)
        await service.start()
        bs.set_training_mode_session_service(service)
        try:
            tid = await make_session(app_client, 6)
            installed = await app_client.post(f"/api/training-mode/sessions/{tid}/changes", json={
                "base_version": "head", "ops": pc.noticer_ops(pc.ALL_BODY)})
            assert installed.status_code == 200 and installed.json()["ok"], installed.text
            assert (await app_client.post(f"/api/training-mode/sessions/{tid}/start")).status_code == 200
            await until_state(app_client, tid, "finished", timeout=300)
            runs = await runs_of(app_client, tid, 1)
            assert len(runs) == 6 and not [r for r in runs if r["status"] == "error"], runs

            live = service._live[tid].config
            tables = live.document.tables
            outcomes = sorted(executor.outcomes, key=lambda o: o.seed)
            assert len(outcomes) == 6 and all(o.proposals for o in outcomes)
            # every kind of op is in the session's configuration, once
            assert [k for k in tables["link_types"] if k == ("near",)] == [("near",)]
            assert ("plato-b", "plato-c", "near", "") in tables["slipnet_link_defs"]
            assert [k for k in tables["slipnet_link_defs"] if k[:3] == ("plato-b", "plato-c", "near")] == [
                ("plato-b", "plato-c", "near", "")]
            assert "plato-b" in tables["posting_rules"][("top-down-description-scout",)]["triggering_slipnodes"]
            # the pair's link: L - s * (N - 1) after N noticings, whichever order the runs finished in
            noticed = [next(p["by"] for p in o.proposals if p["op"] == "adjust" and p["field"] == "link_length")
                       / -pc.STEP for o in outcomes]
            assert all(n == int(n) and n >= 1 for n in noticed)
            total = int(sum(noticed))
            assert tables["slipnet_link_defs"][pc.PAIR]["link_length"] == pc.LENGTH - pc.STEP * (total - 1)
            # the count adds up across runs the way the link does: each run summed its own `adjust` of +1 per noticing
            counted = sum(p["by"] for o in outcomes for p in o.proposals
                          if p["op"] == "adjust" and p["field"] == "noticings")
            assert counted >= len(outcomes) and tables["slipnet_node_defs"][("plato-b",)]["noticings"] == counted
            # journaled as the in-worker learner, duplicates skipped cleanly (never refused)
            learner = [c.pending for c in live.changes if c.pending.source == "learner"]
            assert learner and all(e.actor == f"learner:{bs.IN_WORKER_LEARNER}" for e in learner)
            assert live.diagnostics == []
            lengths[kind] = (total, tables["slipnet_link_defs"][pc.PAIR]["link_length"])
            firsts[kind] = outcomes[0]
            await stop(app_client, tid)
        finally:
            bs.set_training_mode_session_service(None)
            await service.stop()
            if kind == "serial":
                inner.close()
    # the first run of each started under the same configuration: it is the same run, proposals included
    assert outcome_fingerprint(firsts["serial"]) == outcome_fingerprint(firsts["swarm"])
    assert firsts["serial"].proposals == firsts["swarm"].proposals
    async with test_engine.begin() as conn:
        await conn.execute(text("DELETE FROM training_mode_sessions"))
