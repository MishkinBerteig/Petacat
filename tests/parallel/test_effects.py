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
               p.get("answer") if p["mode"] == "justification" else None)
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

    def sneaky(ctx, name):
        node = ctx.slipnet.nodes.get(name)
        if node is not None and not node.frozen:
            node.activation = node.activation + 1.0  # a hidden write on a read path
        return node

    registry = dict(get_builtins())
    registry["get_node"] = sneaky
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
