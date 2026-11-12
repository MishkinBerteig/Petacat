"""The effects table, and the hidden-write detector that checks its READ claims.

What these defend
-----------------
* ``test_table_covers_registry`` -- every builtin and every codelet type has an entry, and
  nothing stale remains: an unclassified builtin would be treated as WRITE(everything), which
  is safe but silently slow, so a new builtin or codelet type must be classified on purpose.
* ``test_bodies_call_only_classified_builtins`` / ``test_speculated_bodies_touch_only_audited_names``
  -- an AST scan of the 27 ``execute_body`` sources: a body that starts referring to the
  coderack, the trace, the Slipnet object, the Themespace or the commentary directly has
  left the audited envelope, and a speculated type must not do so without a new audit.
* ``test_barriers_are_meta_and_answer`` -- the families that clamp, snag, give up and report
  answers can run an update cycle from inside a codelet and are never speculated.
* ``test_no_hidden_write_in_a_speculated_prefix`` -- the detector: run real problems, and
  fingerprint every component of the shared state before each codelet body and at its first
  trapped write.  Any component that moved in between was written by a "read".
* ``test_detector_catches_a_planted_hidden_write`` -- the detector itself must be able to fail.
* ``test_detect_mode_is_the_ssr`` -- the plugin interpreter, the deferred Slipnet jolts and
  the guards leave a run bit-identical to the SSR when nothing is speculated.
"""

from __future__ import annotations

import ast
import json
import os

import pytest

from server.engine.codelet_dsl.builtins import get_builtins
from server.engine.metadata import MetadataProvider
from server.engine.runner import EngineRunner
from server.parallel.speculative import effects as fx
from server.parallel.speculative.compare import diff, run_record
from server.parallel.speculative.engine import SpeculativeEngine

SEED_DATA = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")


@pytest.fixture(scope="module")
def meta():
    return MetadataProvider.from_standard_configuration(SEED_DATA)


@pytest.fixture(scope="module")
def bodies():
    with open(os.path.join(SEED_DATA, "codelet_types.json")) as f:
        return {c["name"]: c for c in json.load(f)}


def problems():
    with open(os.path.join(SEED_DATA, "demo_problems.json")) as f:
        demo = json.load(f)
    seen, out = set(), []
    for p in demo:
        key = (p["initial"], p["modified"], p["target"],
               p.get("answer"))
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def test_table_covers_registry(bodies):
    table = fx.load()
    assert set(table.builtins) == set(get_builtins()), "builtin registry and effects table differ"
    assert set(table.types) == set(bodies), "codelet types and effects table differ"
    for name, e in table.builtins.items():
        assert e.kind in (fx.READ, fx.WRITE, fx.BARRIER), name
        if e.kind == fx.READ:
            assert not (e.writes & ~fx.BIT["slipnet_buf"]), f"READ builtin {name} declares writes"


def test_barriers_are_meta_and_answer(bodies):
    table = fx.load()
    for name, body in bodies.items():
        if body["family"] in ("meta", "answer"):
            assert table.types[name].barrier, name
            assert not table.types[name].speculate, name


def _called_names(source: str) -> set[str]:
    return {
        n.func.id for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }


def test_bodies_call_only_classified_builtins(bodies):
    table = fx.load()
    safe = {"fizzle", "round", "min", "max", "abs", "len", "range", "sum", "any", "all",
            "isinstance", "getattr", "hasattr", "print", "list", "set", "dict", "tuple",
            "enumerate", "zip", "sorted", "reversed", "float", "int", "str", "bool", "next",
            "map", "filter", "frozenset", "type"}
    registry = set(table.builtins)
    for name, body in bodies.items():
        for called in _called_names(body["execute_body"]):
            if called in registry or called in safe:
                continue
            # A direct engine call (imported inside the body, or a local helper).  It is
            # reported rather than failed, because the audit covers them by name; but a
            # speculated type may only make the ones the audit knows.
            assert called in KNOWN_DIRECT_CALLS or not table.types[name].speculate, (
                f"{name} makes a direct engine call {called!r} that the audit has not seen"
            )


#: Direct engine calls (not builtins) the audit examined in the speculated bodies.
KNOWN_DIRECT_CALLS = {
    "incompatible_bond_candidates", "possible_bridge_cms", "propose_bridge",
    "reverse_direction_orientation", "Group", "attach_length_description",
    "Letter", "Bond", "Description", "ConceptMapping",
}


#: Namespace names a speculated body may use: everything else (the Slipnet object, the
#: coderack, the trace, the themespace, memory, commentary) is outside the audited envelope.
AUDITED_NAMES = {"ctx", "args", "workspace", "temperature", "rng", "meta", "codelet_count",
                 "justify_mode", "verbose"}
SUSPECT_NAMES = {"slipnet", "coderack", "themespace", "trace", "memory", "commentary",
                 "self_watching"}


def test_speculated_bodies_touch_only_audited_names(bodies):
    table = fx.load()
    for name, body in bodies.items():
        if not table.types[name].speculate:
            continue
        used = {n.id for n in ast.walk(ast.parse(body["execute_body"])) if isinstance(n, ast.Name)}
        assert not (used & SUSPECT_NAMES), (
            f"{name} references {sorted(used & SUSPECT_NAMES)} directly; audit it before speculating"
        )


def test_uses_cc_matches_body_source(bodies):
    table = fx.load()
    for name, body in bodies.items():
        used = {n.id for n in ast.walk(ast.parse(body["execute_body"])) if isinstance(n, ast.Name)}
        mentions = "codelet_count" in used
        if mentions:
            assert table.types[name].uses_cc, f"{name} reads codelet_count but the table says not"


# -- the hidden-write detector ---------------------------------------------------------

DETECT_PROBLEMS = [0, 1, 6, 12, 16, 20, 27]


@pytest.mark.parametrize("pi", DETECT_PROBLEMS)
def test_no_hidden_write_in_a_speculated_prefix(meta, pi):
    problem = problems()[pi]
    table = fx.load()
    for seed in (1, 2):
        runner = EngineRunner(meta)
        runner.init_mcat(*problem, seed=seed)
        engine = SpeculativeEngine(runner, 0, detect=True)
        try:
            engine.run(350)
        finally:
            engine.close()
        offenders = [v for v in engine.violations if table.types[v["codelet"]].speculate]
        assert not offenders, offenders[:3]


def test_detector_catches_a_planted_hidden_write(meta, monkeypatch):
    """A READ that secretly writes the Slipnet must be reported."""
    import server.engine.codelet_dsl.builtins as b

    real_role = b.role

    def sneaky(ctx, name):
        node = real_role(ctx, name)
        if node and not isinstance(node, (tuple, str)) and not node.frozen:
            node.activation = node.activation + 1.0  # a hidden write on a read path
        return node

    registry = dict(get_builtins())
    registry["role"] = sneaky
    monkeypatch.setattr(b, "get_builtins", lambda: registry)
    problem = problems()[0]
    runner = EngineRunner(meta)
    runner.init_mcat(*problem, seed=1)
    engine = SpeculativeEngine(runner, 0, detect=True)
    engine._builtins = registry
    try:
        engine.run(120)
    finally:
        engine.close()
    assert any("slipnet_act" in v["components"] for v in engine.violations)


@pytest.mark.parametrize("pi", [0, 6, 16])
def test_detect_mode_is_the_ssr(meta, pi):
    problem = problems()[pi]
    ssr = run_record(meta, problem, 3, "ssr", max_steps=300)
    detect = run_record(meta, problem, 3, "spec", workers=0, max_steps=300, detect=True)
    assert diff(ssr, detect) == []


# -- the audit belongs to the audited body (body digests) -------------------------------


def test_every_type_stores_the_digest_of_its_audited_body(bodies):
    """``effects_data.json`` holds a digest for each of the 27 bodies, equal to the digest of
    the Metacat Standard Configuration's body: a changed seed body must be re-audited and its
    digest updated on purpose."""
    table = fx.load()
    for name, body in bodies.items():
        assert table.types[name].body_digest == fx.body_digest(body["execute_body"]), (
            f"{name}: the body changed since it was audited; re-audit it and update its digest"
        )


def test_info_returns_the_audited_entry_only_for_the_audited_body(bodies):
    table = fx.load()
    for name, body in bodies.items():
        audited = table.info(name, fx.body_digest(body["execute_body"]))
        assert audited is table.types[name]
        edited = table.info(name, fx.body_digest(body["execute_body"] + "\n# edited\n"))
        assert edited.barrier and edited.reads == fx.ALL and edited.writes == fx.ALL
        assert edited.uses_cc
    assert table.info("a-type-nobody-audited", fx.body_digest("fizzle()")).barrier
    assert table.info("bond-builder", "").barrier  # no body (an empty one) is not the audited one


def test_a_digest_is_a_sha256_of_the_source():
    import hashlib

    assert fx.body_digest("fizzle()") == hashlib.sha256(b"fizzle()").hexdigest()


# -- the audit belongs to the audited descriptor predicates (support digest) ---------------

#: Types the effects table marks speculable but not profitable, and which call a descriptor
#: predicate (the top-down description scout through ``possible_descriptor``).  Marking them
#: profitable is a data change, and it is how a predicate comes to run on a worker.
_UNPROFITABLE_PREDICATE_CALLERS = ("top-down-description-scout", "description-evaluator",
                                   "important-object-bridge-scout")
_WRITING_PREDICATE = (
    "(obj.salience.update({'intra': obj.salience.get('intra', 0.0) + 0.5}) or True) "
    "and group_length(obj) == 1"
)


def _with_node_predicate(meta, node: str, source: str):
    import dataclasses

    specs = dict(meta.slipnet_node_specs)
    specs[node] = dataclasses.replace(specs[node], descriptor_predicate=source)
    return dataclasses.replace(meta, slipnet_node_specs=specs)


def _first(meta, field_name: str) -> str:
    return next(getattr(r, field_name) for r in meta.posting_rules if getattr(r, field_name))


def test_the_standard_configuration_is_the_audited_one(meta):
    table = fx.load()
    assert table.support_digest and table.support_digest == fx.support_digest(meta), (
        "a descriptor predicate changed since the audit; re-audit and update support_digest "
        "in effects_data.json on purpose"
    )


def test_a_changed_predicate_makes_every_type_a_barrier(meta, bodies):
    table = fx.load()
    name = "bond-evaluator"
    digest = fx.body_digest(bodies[name]["execute_body"])
    assert table.info(name, digest, fx.support_digest(meta)) is table.types[name]
    edited = _with_node_predicate(meta, "plato-one", "group_length(obj) == 1 or False")
    got = table.info(name, digest, fx.support_digest(edited))
    assert got.barrier and got.reads == fx.ALL and got.writes == fx.ALL


def test_the_engine_plans_every_type_as_a_barrier_under_an_edited_predicate(meta):
    edited = _with_node_predicate(meta, "plato-one", "group_length(obj) == 1 or False")
    for m, expect_barrier in ((meta, False), (edited, True)):
        runner = EngineRunner(m)
        runner.init_mcat("abc", "abd", "ijk", seed=3)
        engine = SpeculativeEngine(runner, workers=2)
        plans = [engine._type_plan(t)[0] for t in m.codelet_specs]
        audited = [p for p in plans if not p.barrier]
        assert (not audited) if expect_barrier else bool(audited)


def test_posting_formulas_are_evaluated_only_where_nothing_is_in_flight():
    """Why the digest does not cover posting, urgency and count formulas or conditions: their
    only callers are the update cycle, the opening posting and the snag restart."""
    import re

    callers = set()
    root = os.path.join(os.path.dirname(__file__), "..", "..", "server")
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            if not f.endswith(".py"):
                continue
            path = os.path.join(dirpath, f)
            if f == "posting.py":
                continue
            text = open(path).read()
            if re.search(r"evaluate_(posting_formula|count_formula|condition|urgency)\(", text):
                callers.add(os.path.relpath(path, root))
    assert callers == {"engine/runner.py", "parallel/update_cycle.py"}, callers
    builtins_src = open(os.path.join(root, "engine", "codelet_dsl", "builtins.py")).read()
    assert "PostingContext" not in builtins_src and "posting_formula" not in builtins_src


def _reachable_table(monkeypatch):
    """The effects table with the unprofitable predicate callers marked profitable."""
    import dataclasses

    base = fx.load()
    types = dict(base.types)
    for name in _UNPROFITABLE_PREDICATE_CALLERS:
        types[name] = dataclasses.replace(types[name], profitable=True)
    table = fx.Effects(base.builtins, types, base.support_digest)
    monkeypatch.setattr(fx, "load", lambda path=None: table)
    return table


def _predicate_threads(monkeypatch, meta, problem, seed):
    import collections
    import threading

    import server.engine.slipnet as sl

    seen = collections.Counter()
    orig = sl.DESCRIPTOR_PREDICATE_NAMESPACE["group_length"]

    def recording(g):
        seen[threading.current_thread().name] += 1
        return orig(g)

    monkeypatch.setitem(sl.DESCRIPTOR_PREDICATE_NAMESPACE, "group_length", recording)
    rec = run_record(meta, problem, seed, "spec", workers=4, max_steps=900)
    return rec, seen


def test_a_predicate_can_run_on_a_worker_inside_a_speculated_prefix(meta, monkeypatch):
    """The path exists: once a predicate-calling type is allowed to run ahead (a data change in
    the table), a descriptor predicate is evaluated on a ``spec-worker`` thread."""
    _reachable_table(monkeypatch)
    on_workers = 0
    for problem, seed in ((("abc", "abd", "mrrjjj", None), 1), (("abc", "abd", "xyz", None), 2),
                          (("abc", "abd", "aabbcc", None), 3)):
        _rec, seen = _predicate_threads(monkeypatch, meta, problem, seed)
        on_workers += sum(n for t, n in seen.items() if t != "MainThread")
    assert on_workers > 0


def test_an_edited_writing_predicate_never_runs_on_a_worker_and_is_exact(meta, monkeypatch):
    """With the digest, the edited configuration is unaudited, so the predicate (which writes)
    runs only on the coordinator and the run equals the reference."""
    _reachable_table(monkeypatch)
    edited = _with_node_predicate(meta, "plato-one", _WRITING_PREDICATE)
    for problem, seed in ((("abc", "abd", "mrrjjj", None), 1), (("abc", "abd", "xyz", None), 2),
                          (("abc", "abd", "aabbcc", None), 3)):
        spec, seen = _predicate_threads(monkeypatch, edited, problem, seed)
        assert set(seen) <= {"MainThread"}, seen
        ref = run_record(edited, problem, seed, "ssr", max_steps=900)
        assert diff(ref, spec) == []


def test_without_the_digest_the_same_edit_does_run_on_a_worker(meta, monkeypatch):
    """The digest is what keeps it off the workers: with the check disabled (the old behaviour)
    the writing predicate runs on a ``spec-worker`` thread."""
    table = _reachable_table(monkeypatch)
    monkeypatch.setattr(fx, "support_digest", lambda m: table.support_digest)
    edited = _with_node_predicate(meta, "plato-one", _WRITING_PREDICATE)
    on_workers = 0
    for problem, seed in ((("abc", "abd", "mrrjjj", None), 1), (("abc", "abd", "xyz", None), 2),
                          (("abc", "abd", "aabbcc", None), 3)):
        _rec, seen = _predicate_threads(monkeypatch, edited, problem, seed)
        on_workers += sum(n for t, n in seen.items() if t != "MainThread")
    assert on_workers > 0


def test_apply_ops_is_a_barrier_so_the_speculative_executor_serialises_it():
    """``apply_ops`` appends to the run's Slipnet and replaces its alphabet and metadata view.  The
    speculative executor has no guard class, node list or structure read for a created node yet
    (``Slipnet`` nodes are wrapped at construction), so the table makes it a BARRIER."""
    entry = fx.load().builtins["apply_ops"]
    assert entry.kind == fx.BARRIER
    assert entry.writes & fx.BIT["slipnet_act"] and entry.writes & fx.BIT["ctx"]
