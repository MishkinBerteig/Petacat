"""Training Mode Sessions on the v2.0 Base: a symbol with no Slipnet node gets one, inside the run.

Through the real service, on the serial child and on the swarm: the runs answer with the symbol;
exactly one ``plato-cp-<hex>`` node reaches the session's configuration, from the in-worker learner,
however many runs met the symbol; runs dispatched after it landed start with the symbol perceived
and propose nothing; a repeated problem keeps answering; and creating sessions on the v2.0 Base
never changes the global configuration (Metacat Mode's).
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from server.engine.hashing import config_hash as provider_hash
from server.services import config_document as cd
from server.services import configurations
from server.services import training_mode_session_service as bs
from server.services.training_mode_session_executor import (
    SerialExecutor, SwarmExecutor, outcome_fingerprint,
)
from tests.e2e.test_session_configuration import factory_of, journal_count, stored_document
from tests.e2e.test_training_mode_sessions_api import (
    make_service, runs_of, session_state, stop, until_state,
)


class Recording:
    """An executor that keeps every outcome it returns (to look at ``proposals``)."""

    def __init__(self, inner) -> None:
        self.inner, self.outcomes = inner, []

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def submit(self, tasks, meta):
        future = self.inner.submit(tasks, meta)
        future.add_done_callback(lambda f: self.outcomes.extend(f.result() if not f.exception() else []))
        return future


@pytest.fixture(params=["serial", "swarm"])
async def recorded(request, app_client, test_engine):
    from server.api.runs import get_run_service

    async with test_engine.begin() as conn:
        await conn.execute(text("DELETE FROM training_mode_sessions"))
    meta = get_run_service().meta
    inner = SerialExecutor() if request.param == "serial" else SwarmExecutor(base=meta)
    executor = Recording(inner)
    service = make_service(test_engine, meta, executor=executor)
    await service.start()
    bs.set_training_mode_session_service(service)
    service.test_engine, service.recording, service.kind = test_engine, executor, request.param
    yield service
    bs.set_training_mode_session_service(None)
    await service.stop()
    inner.close() if request.param == "serial" else None
    async with test_engine.begin() as conn:
        await conn.execute(text("DELETE FROM training_mode_sessions"))


async def make(client, problem, seeds, **settings):
    body = {"name": "v2", "settings": {"seeds_per_problem": seeds, "max_codelets": 4000, **settings},
            "problems": [{"initial": problem[0], "modified": problem[1], "target": problem[2]}]}
    resp = await client.post("/api/training-mode/sessions", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()["session"]


@pytest.mark.parametrize("symbol", ["1", "😀"])
@pytest.mark.asyncio
async def test_a_new_symbol_gets_one_node_and_the_runs_answer_with_it(recorded, app_client, symbol):
    service = recorded
    node = f"plato-cp-{ord(symbol):04x}"
    made = await make(app_client, (symbol, symbol, symbol), 12)
    assert made["settings"]["configuration_base"] == "training-v2"
    tid = made["id"]
    assert node not in {k[0] for k in (await stored_document(service.test_engine, tid)).tables["slipnet_node_defs"]}
    assert (await app_client.post(f"/api/training-mode/sessions/{tid}/start")).status_code == 200
    await until_state(app_client, tid, "finished", timeout=240)

    runs = await runs_of(app_client, tid, 1)
    assert len(runs) == 12 and all(r["status"] == "answer_found" and r["answer"] == symbol for r in runs), runs

    live = service._live[tid].config
    nodes = [k for k in live.document.tables["slipnet_node_defs"] if k[0] == node]
    assert len(nodes) == 1  # one row, however many runs met the symbol
    row = live.document.tables["slipnet_node_defs"][(node,)]
    assert (row["glyph"], row["short_name"], row["conceptual_depth"]) == (symbol, symbol, 10)
    learner = [c.pending for c in live.changes if c.pending.source == "learner"]
    assert len(learner) == 1 and learner[0].actor == f"learner:{bs.IN_WORKER_LEARNER}"
    assert [op["table"] for op in learner[0].resolved] == ["slipnet_node_defs"]
    assert live.diagnostics == []  # a duplicate is skipped cleanly, never refused

    # Runs dispatched after the node landed start with the symbol perceived: they propose nothing.
    # (The session starts at revision 1, the creation batch that holds the Base's delta; the node
    # lands as revision 2.)
    outcomes = sorted(service.recording.outcomes, key=lambda o: o.seed)
    by_revision = {r["seed"]: r for r in runs}
    assert any(o.proposals for o in outcomes)
    for o in outcomes:
        if by_revision[o.seed]["configuration_revision"] >= 2:
            assert o.proposals == [] and o.answer == symbol, o.seed
    if service.kind == "serial":  # one run at a time: only the first run met an unseen symbol
        assert [bool(o.proposals) for o in outcomes] == [True] + [False] * 11
    await stop(app_client, tid)


@pytest.mark.asyncio
async def test_the_serial_child_and_the_swarm_give_identical_outcomes_proposals_included(
        app_client, test_engine):
    from server.api.runs import get_run_service

    meta = get_run_service().meta
    results = {}
    for kind, inner in (("serial", SerialExecutor()), ("swarm", SwarmExecutor(base=meta))):
        async with test_engine.begin() as conn:
            await conn.execute(text("DELETE FROM training_mode_sessions"))
        executor = Recording(inner)
        service = make_service(test_engine, meta, executor=executor)
        await service.start()
        bs.set_training_mode_session_service(service)
        try:
            made = await make(app_client, ("1", "1", "1"), 6)
            # all six dispatched under the same (symbol-less) configuration: pause the learner's effect
            # by comparing what each run gives its own task, not the order they finish in
            await app_client.post(f"/api/training-mode/sessions/{made['id']}/start")
            await until_state(app_client, made["id"], "finished", timeout=240)
            results[kind] = executor
            await stop(app_client, made["id"])
        finally:
            bs.set_training_mode_session_service(None)
            await service.stop()
            if kind == "serial":
                inner.close()
    # The first run of each, started under the same configuration and memory, is the same run.
    first = {k: min(e.outcomes, key=lambda o: o.seed) for k, e in results.items()}
    assert outcome_fingerprint(first["serial"]) == outcome_fingerprint(first["swarm"])
    assert first["serial"].proposals and first["serial"].proposals == first["swarm"].proposals


@pytest.mark.asyncio
async def test_a_repeated_problem_keeps_answering_across_many_seeds_in_one_session(
        app_client, test_engine):
    """In the v2.0 Base Episodic Memory no longer refuses an answer it already holds: one session,
    one shared memory, the same problem 30 times (Metacat's refusal gave none after about 25)."""
    from server.api.runs import get_run_service

    async with test_engine.begin() as conn:
        await conn.execute(text("DELETE FROM training_mode_sessions"))
    service = make_service(test_engine, get_run_service().meta, executor=SerialExecutor())
    await service.start()
    bs.set_training_mode_session_service(service)
    try:
        made = await make(app_client, ("1", "1", "1"), 30)
        await app_client.post(f"/api/training-mode/sessions/{made['id']}/start")
        await until_state(app_client, made["id"], "finished", timeout=300)
        runs = await runs_of(app_client, made["id"], 1)
        assert len(runs) == 30 and all(r["answer"] == "1" for r in runs), [r["answer"] for r in runs]
        # memory still records the answer (an identical one is stored once)
        assert (await session_state(app_client, made["id"]))["memory"]["answers"] >= 1
        await stop(app_client, made["id"])
    finally:
        bs.set_training_mode_session_service(None)
        await service.stop()
        async with test_engine.begin() as conn:
            await conn.execute(text("DELETE FROM training_mode_sessions"))


@pytest.mark.asyncio
async def test_creating_sessions_on_the_v2_base_never_changes_the_global_configuration(
        app_client, test_engine):
    from server.api.runs import get_run_service

    factory = factory_of(test_engine)
    async with factory() as db:
        before = cd.config_hash(await configurations.current_document(db, 1))
        revision = (await configurations.get_row(db, 1))["revision"]
    service = make_service(test_engine, get_run_service().meta, executor=SerialExecutor())
    await service.start()
    bs.set_training_mode_session_service(service)
    try:
        default = await make(app_client, ("abc", "abd", "xyz"), 1)
        explicit = await make(app_client, ("abc", "abd", "xyz"), 1, configuration_base="training-v2",
                              parameters={"update_cycle_length": 17})
        async with factory() as db:
            after = cd.config_hash(await configurations.current_document(db, 1))
            assert after == before and (await configurations.get_row(db, 1))["revision"] == revision
            row = await configurations.row_for_session(db, default["id"])
            assert row["revision"] == 1 and await journal_count(test_engine, row["id"]) == 1
            from server.services import journal_views
            (entry,) = await journal_views.read_entries(db, row["id"])
        # The journal shows exactly what v2.0 adds, with both hashes in the note.
        assert entry["source"] == "creation"
        assert "symbol-scout" in str(entry["proposed"]) and "new_node_conceptual_depth" in str(entry["proposed"])
        from server.services import training_base as tb
        base = tb.resolve_base()
        assert base.delta_hash in entry["note"] and base.standard_hash in entry["note"]
        assert (await stored_document(test_engine, default["id"])).tables["engine_params"][
            ("new_node_conceptual_depth",)]["value"] == "10"
        override = await stored_document(test_engine, explicit["id"])
        assert override.tables["engine_params"][("update_cycle_length",)]["value"] == "17"
        assert ("symbol-scout",) in override.tables["codelet_type_defs"]
        # global and standard are still what they were
        g = await make(app_client, ("abc", "abd", "xyz"), 1, configuration_base="global")
        s = await make(app_client, ("abc", "abd", "xyz"), 1, configuration_base="standard")
        assert ("symbol-scout",) not in (await stored_document(test_engine, g["id"])).tables["codelet_type_defs"]
        assert ("symbol-scout",) not in (await stored_document(test_engine, s["id"])).tables["codelet_type_defs"]
        assert s["configuration"]["hash"] != default["configuration"]["hash"]
    finally:
        bs.set_training_mode_session_service(None)
        await service.stop()
        async with test_engine.begin() as conn:
            await conn.execute(text("DELETE FROM training_mode_sessions"))


@pytest.mark.asyncio
async def test_the_admin_compare_reads_the_v2_base_like_the_standard(app_client):
    """The Admin view's compare takes ``training-v2`` as a side: read-only, resolved over the Standard now."""
    resp = await app_client.get("/api/configurations/compare", params={"a": "standard", "b": "training-v2"})
    assert resp.status_code == 200, resp.text
    got = resp.json()
    assert got["b"]["id"] == "training-v2" and got["b"]["name"] == "Training Mode Base Configuration, v2.0"
    keys = {(r["table"], tuple(r["key"].values()), r["change"]) for r in got["rows"]}
    assert ("codelet_type_defs", ("symbol-scout",), "removed") in keys  # only the Base (b) has it
    assert ("engine_params", ("new_node_conceptual_depth",), "removed") in keys
    assert ("codelet_type_defs", ("answer-finder",), "changed") in keys
    assert ("posting_rules", ("symbol-scout",), "removed") in keys
    same = (await app_client.get("/api/configurations/compare", params={"a": "training-v2", "b": "training-v2"})).json()
    assert same["same"] is True
    refused = await app_client.get("/api/configurations/compare", params={"a": "standard", "b": "nonsense"})
    assert refused.status_code in (400, 404, 422)


# -- increment 2: adjacent bonds in real sessions ---------------------------------------------------------------


ADJACENT_PROBLEM = ("aceg", "acei", "bdfh")


@pytest.mark.asyncio
async def test_a_session_on_the_base_builds_adjacent_bonds_and_the_serial_child_and_the_swarm_agree(
        app_client, test_engine):
    """Neighbours with no relation are perceived as neighbours in a real session: the run's own
    Workspace builds ``plato-adjacent`` bonds (seed 3 of this problem builds 25), the serial child and
    the swarm give the same first run, and no ``adjacent`` link is ever written into the session's
    configuration (only the link type and the node the Base creates are there)."""
    from server.api.runs import get_run_service

    meta = get_run_service().meta
    firsts, documents = {}, {}
    for kind, inner in (("serial", SerialExecutor()), ("swarm", SwarmExecutor(base=meta))):
        async with test_engine.begin() as conn:
            await conn.execute(text("DELETE FROM training_mode_sessions"))
        executor = Recording(inner)
        service = make_service(test_engine, meta, executor=executor)
        await service.start()
        bs.set_training_mode_session_service(service)
        try:
            made = await make(app_client, ADJACENT_PROBLEM, 6)
            await app_client.post(f"/api/training-mode/sessions/{made['id']}/start")
            await until_state(app_client, made["id"], "finished", timeout=300)
            runs = await runs_of(app_client, made["id"], 1)
            assert len(runs) == 6 and all(r["status"] == "answer_found" for r in runs)
            firsts[kind] = min(executor.outcomes, key=lambda o: o.seed)
            documents[kind] = await stored_document(test_engine, made["id"])
            await stop(app_client, made["id"])
        finally:
            bs.set_training_mode_session_service(None)
            await service.stop()
            if kind == "serial":
                inner.close()
    assert outcome_fingerprint(firsts["serial"]) == outcome_fingerprint(firsts["swarm"])
    for doc in documents.values():
        assert ("adjacent",) in doc.tables["link_types"] and ("plato-adjacent",) in doc.tables["slipnet_node_defs"]
        assert not [k for k, r in doc.tables["slipnet_link_defs"].items() if r["link_type"] == "adjacent"]
        assert [k[0] for k in doc.tables["slipnet_node_defs"] if k[0].startswith("plato-cp-")] == []  # letters only
    # the serial child and the swarm see the same configuration afterwards
    assert cd.config_hash(documents["serial"]) == cd.config_hash(documents["swarm"])
