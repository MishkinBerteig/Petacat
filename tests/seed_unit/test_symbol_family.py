"""The v2.0 Base's symbol family and the engine primitive under it.

``Slipnet.add_node`` and ``invalidate_numeric_layout``; ``apply_ops`` (``add_node`` only, this run's
own Slipnet, recorded on the run, never the shared provider); ``num_unperceived_symbols``; the symbol
family's posting rule drawing nothing when every symbol is perceived; and a run that creates a node
giving the same results on every numeric backend.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from server.engine.codelet_dsl.builtins import apply_ops
from server.engine.metadata import MetadataProvider, SlipnodeSpec
from server.engine.numeric import available_backends
from server.engine.numeric.backend import use_backend
from server.engine.posting import POSTING_FORMULA_NAMES, PostingContext
from server.engine.runner import EngineRunner
from server.engine.slipnet import Slipnet, _UNRESOLVED
from server.services import config_document as cd
from server.services import training_base as tb
from tests.lockstep.metacat.wrap import read_problem_list

pytestmark = pytest.mark.numeric_matrix

DATA = Path(__file__).resolve().parents[1] / "lockstep" / "data"
SEED_DATA = str(Path(__file__).resolve().parents[2] / "seed_data")


@pytest.fixture(scope="module")
def standard() -> MetadataProvider:
    return MetadataProvider.from_standard_configuration(SEED_DATA)


@pytest.fixture(scope="module")
def base() -> MetadataProvider:
    return cd.provider(tb.resolve_base().document)


def run(meta, problem, seed, steps=3000, backend="off"):
    runner = EngineRunner(meta)
    with use_backend(backend):
        runner.init_mcat(problem[0], problem[1], problem[2], None, seed=seed)
        runner.run_mcat(max_steps=steps)
    ctx = runner.ctx
    answer = ctx.workspace.answer_string
    return runner, {
        "status": runner.status, "answer": answer.text if answer else "", "codelets": ctx.codelet_count,
        "temperature": float(ctx.temperature.value), "draws": ctx.rng.call_count,
        "proposals": list(ctx.proposals), "answers": list(runner._answers),
    }


def spec(ch="1", **kw) -> SlipnodeSpec:
    return SlipnodeSpec(name=f"plato-cp-{ord(ch):04x}", short_name=ch, conceptual_depth=10, glyph=ch,
                        plain_name=ch, article_an=False, **kw)


def add_op(ch="1", **fields):
    return {"op": "add_node", "name": f"plato-cp-{ord(ch):04x}", "fields": {
        "short_name": ch, "glyph": ch, "plain_name": ch, "article_an": False, "conceptual_depth": 10,
        **fields}}


# -- Slipnet.add_node and the invalidation -----------------------------------------------------


def test_add_node_adds_a_node_the_alphabet_finds_last_in_node_order_and_invalidates(standard):
    slipnet = Slipnet.from_metadata(standard)
    names = list(slipnet.nodes)
    assert not slipnet.alphabet.glyph_nodes.get("1")
    slipnet._numeric = None  # "resolved"
    node = slipnet.add_node(spec("1"))
    assert list(slipnet.nodes) == names + [node.name]
    assert slipnet.alphabet.glyph_nodes["1"] is node and slipnet.alphabet.glyph_nodes["a"].glyph == "a"
    assert slipnet._numeric is _UNRESOLVED
    assert node.relations is slipnet.relations
    with pytest.raises(ValueError):
        slipnet.add_node(spec("1"))


def test_a_created_node_is_the_node_from_metadata_builds_for_the_same_spec(standard):
    """Metacat Mode's construction goes through the helper a created node uses."""
    meta = dataclasses.replace(standard, slipnet_node_specs={**standard.slipnet_node_specs, "plato-cp-0031": spec("1")})
    built = Slipnet.from_metadata(meta).nodes["plato-cp-0031"]
    made = Slipnet.from_metadata(standard).add_node(spec("1"))
    for slot in ("name", "short_name", "conceptual_depth", "plain_name", "glyph", "numeric_value", "full_name",
                 "cm_short_name", "article_an", "intrinsic_link_length", "_decay_percent", "_decay_exact",
                 "activation", "frozen", "descriptor_predicate"):
        assert getattr(made, slot) == getattr(built, slot), slot


# -- apply_ops ----------------------------------------------------------------------------------


def fresh_ctx(meta, problem=("1", "1", "1")):
    runner = EngineRunner(meta)
    runner.init_mcat(*problem, None, seed=1)
    return runner.ctx


def test_apply_ops_takes_add_node_only_and_refuses_the_rest_by_name(base):
    ctx = fresh_ctx(base)
    for bad in ({"op": "add_link", "from": "a", "to": "b", "type": "lateral"},
                {"op": "adjust", "table": "slipnet_link_defs"}, {"op": "add_trigger"}):
        with pytest.raises(ValueError, match=bad["op"]):
            apply_ops(ctx, [add_op(), bad])
    assert not ctx.proposals and not ctx.slipnet.alphabet.glyph_nodes.get("1")  # nothing was applied
    for extra in ("links", "roles", "params", "layout", "theme_dimension"):
        with pytest.raises(ValueError, match=extra):
            apply_ops(ctx, [{**add_op(), extra: []}])
    with pytest.raises(ValueError):
        apply_ops(ctx, [{"op": "add_node", "name": "x", "fields": {"short_name": "x"}}])


def test_apply_ops_changes_this_runs_slipnet_and_metadata_and_records_the_op_once(base):
    ctx = fresh_ctx(base)
    shared_specs = base.slipnet_node_specs
    before = dict(shared_specs)
    apply_ops(ctx, [add_op("1")])
    apply_ops(ctx, [add_op("1")])  # identical: a no-op
    apply_ops(ctx, [add_op("2"), add_op("1")])
    node = ctx.slipnet.alphabet.glyph_nodes["1"]
    assert node.name == "plato-cp-0031" and ctx.slipnet.alphabet.glyph_nodes["2"].name == "plato-cp-0032"
    assert [p["name"] for p in ctx.proposals] == ["plato-cp-0031", "plato-cp-0032"]
    assert ctx.meta is not base and ctx.meta.slipnet_node_specs["plato-cp-0031"].glyph == "1"
    # nothing another run can see
    assert base.slipnet_node_specs is shared_specs and shared_specs == before
    other = fresh_ctx(base)
    assert not other.slipnet.alphabet.glyph_nodes.get("1") and other.proposals == []
    assert "plato-cp-0031" not in other.meta.slipnet_node_specs
    # picklable plain data
    import pickle

    assert pickle.loads(pickle.dumps(ctx.proposals)) == ctx.proposals


def test_apply_ops_draws_no_random_number_and_leaves_the_workspace_alone(base):
    ctx = fresh_ctx(base)
    draws = ctx.rng.call_count
    objects = list(ctx.workspace.all_objects)
    apply_ops(ctx, [add_op("1")])
    assert ctx.rng.call_count == draws and list(ctx.workspace.all_objects) == objects


# -- num_unperceived_symbols --------------------------------------------------------------------


def test_the_posting_name_exists_and_counts_letters_with_no_letter_category_description(base, standard):
    assert "num_unperceived_symbols" in POSTING_FORMULA_NAMES
    ctx = fresh_ctx(base, ("1", "1", "1"))
    assert PostingContext(ctx)["num_unperceived_symbols"] == 3
    ctx = fresh_ctx(base, ("abc", "abd", "xyz"))
    assert PostingContext(ctx)["num_unperceived_symbols"] == 0
    ctx = fresh_ctx(base, ("ab1", "ab1", "yz1"))
    assert PostingContext(ctx)["num_unperceived_symbols"] == 3
    # a symbol that has a node in the configuration is perceived at once
    with_node = dataclasses.replace(base, slipnet_node_specs={**base.slipnet_node_specs, "plato-cp-0031": spec("1")})
    assert PostingContext(fresh_ctx(with_node, ("1", "1", "1")))["num_unperceived_symbols"] == 0


# -- the symbol family draws nothing when nothing is unseen (check 2) ---------------------------


LETTER_PROBLEMS = read_problem_list(DATA / "fidelity_widen.txt")[:12]
assert len(LETTER_PROBLEMS) == 12


@pytest.mark.parametrize("problem", LETTER_PROBLEMS, ids=[" ".join(p) for p in LETTER_PROBLEMS])
def test_on_letter_problems_the_base_and_the_standard_agree_run_for_run(problem, standard, base):
    """With no unseen symbol the symbol family posts nothing and draws nothing: codelets, answer,
    temperature and the number of random draws are the Standard's, with a fresh memory each run."""
    for seed in (1, 2, 3):
        _, std = run(standard, problem, seed, steps=1500)
        _, b = run(base, problem, seed, steps=1500)
        for key in ("status", "answer", "codelets", "temperature", "draws"):
            assert b[key] == std[key], (problem, seed, key)
        assert b["proposals"] == []


# -- a run that creates a node, on every numeric backend (check 3) ------------------------------


CREATING = [("1", "1", "1"), ("😀", "😀", "😀"), ("aaa", "aaa", "111")]


@pytest.mark.parametrize("problem", CREATING, ids=lambda p: "->".join(p))
def test_a_run_that_creates_a_node_is_identical_on_off_python_and_numpy(problem, base):
    results = {}
    for backend in ("off", "python", *(b for b in ("numpy",) if b in available_backends())):
        for seed in (1, 2):
            _, got = run(base, problem, seed, backend=backend)
            results.setdefault(seed, {})[backend] = got
    for seed, by_backend in results.items():
        first = by_backend["off"]
        assert first["proposals"], "the run created a node"
        for backend, got in by_backend.items():
            assert got == first, (problem, seed, backend)


@pytest.mark.skipif("mlx" not in available_backends(), reason="no GPU backend")
def test_a_run_that_creates_a_node_reaches_a_valid_stopping_state_on_mlx(base):
    for seed in (1, 2):
        _, got = run(base, ("1", "1", "1"), seed, backend="mlx")
        assert got["status"] in ("answer_found", "gave_up", "halted") and got["proposals"]


@pytest.mark.parametrize("backend", ["python", "numpy"])
def test_skipping_the_invalidation_breaks_a_run_that_creates_a_node(backend, base, monkeypatch):
    if backend not in available_backends() and backend != "python":
        pytest.skip("backend not available")
    monkeypatch.setattr(Slipnet, "invalidate_numeric_layout", lambda self: None)
    with pytest.raises(Exception):
        run(base, ("1", "1", "1"), 1, backend=backend)
