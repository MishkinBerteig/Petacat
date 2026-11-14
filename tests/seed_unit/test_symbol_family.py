"""The v2.0 Base's symbol family and the engine primitive under it.

``Slipnet.add_node`` and ``invalidate_numeric_layout``; ``apply_ops`` (``add_node`` only, this run's
own Slipnet, recorded on the run, never the shared provider); ``num_unperceived_symbols``; the symbol
family's posting rule drawing nothing when every symbol is perceived; and a run that creates a node
giving the same results on every numeric backend.
"""

from __future__ import annotations

import contextlib
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


@pytest.fixture(scope="module")
def base_without_the_symbol_family(base) -> MetadataProvider:
    """The v2.0 Base minus the symbol family's posting rule (its codelet types stay, unposted)."""
    rules = tuple(r for r in base.posting_rules if r.codelet_type not in ("symbol-scout", "symbol-builder"))
    assert len(rules) == len(base.posting_rules) - 1
    return dataclasses.replace(base, posting_rules=type(base.posting_rules)(rules))


@pytest.mark.parametrize("problem", LETTER_PROBLEMS, ids=[" ".join(p) for p in LETTER_PROBLEMS])
def test_with_no_unseen_symbol_the_symbol_family_posts_nothing_and_draws_nothing(
        problem, base, base_without_the_symbol_family):
    """The property this test used to state against the Standard, restated.  Increment 2 lets two
    neighbours with no relation bond (``adjacent``), so the v2.0 Base no longer equals the Standard
    on a letter problem (``test_adjacent_bonds_are_built_on_the_base_and_never_on_the_standard``).
    What stays true is that the symbol family itself changes nothing when every symbol is perceived:
    the v2.0 Base and the v2.0 Base without the symbol family's posting rule agree run for run in
    codelets, answer, temperature and the number of random draws, with a fresh memory each run."""
    for seed in (1, 2, 3):
        _, without = run(base_without_the_symbol_family, problem, seed, steps=1500)
        _, with_family = run(base, problem, seed, steps=1500)
        for key in ("status", "answer", "codelets", "temperature", "draws"):
            assert with_family[key] == without[key], (problem, seed, key)
        assert with_family["proposals"] == []


def test_on_the_standard_the_symbol_family_is_not_there_at_all(standard):
    assert "symbol-scout" not in standard.codelet_specs
    assert all(r.codelet_type != "symbol-scout" for r in standard.posting_rules)


# -- adjacent bonds (increment 2) --------------------------------------------------------------------------------


@contextlib.contextmanager
def counting_bonds():
    """Every bond added to a string during the block, by category name."""
    from server.engine.workspace import WorkspaceString

    seen: list[str] = []
    original = WorkspaceString.add_bond

    def add_bond(self, bond, **kw):
        seen.append(bond.bond_category.name)
        return original(self, bond, **kw)

    WorkspaceString.add_bond = add_bond
    try:
        yield seen
    finally:
        WorkspaceString.add_bond = original


ADJACENT = "plato-adjacent"


#: An adjacent bond is weak by design (intrinsic length 90), so it is built rarely: on this problem
#: seed 3 builds 25 of them in 3000 codelets, and the Standard builds none.
ADJACENT_PROBLEM, ADJACENT_SEED, ADJACENT_STEPS = ("aceg", "acei", "bdfh"), 3, 3000


def adjacent_bonds(meta, problem=ADJACENT_PROBLEM, seeds=(ADJACENT_SEED,), steps=ADJACENT_STEPS):
    out = []
    for seed in seeds:
        with counting_bonds() as seen:
            run(meta, problem, seed, steps=steps)
        out.append(seen.count(ADJACENT))
    return out


def test_adjacent_bonds_are_built_on_the_base_and_never_on_the_standard(standard, base):
    # a, c, e and g are neighbours with no link between them
    assert adjacent_bonds(base)[0] > 0
    assert adjacent_bonds(standard) == [0]
    # the bonds the Standard builds on its own problems are never adjacent, on any seed tried
    for problem in (("abc", "abd", "ace"), ("ace", "acf", "bdf")):
        assert adjacent_bonds(standard, problem, seeds=(1, 2, 3), steps=1500) == [0, 0, 0], problem


def test_the_scout_still_fizzles_where_the_role_is_unbound(base):
    """With no ``bond_category.adjacent`` binding the Base's body fizzles at the same place as the
    Standard's, so no adjacent bond is ever built."""
    rows = tuple(r for r in base.node_roles if r.role != "bond_category.adjacent")
    assert len(rows) == len(base.node_roles) - 1
    unbound = dataclasses.replace(base, node_roles=type(base.node_roles)(rows))
    assert adjacent_bonds(unbound) == [0]


def test_both_group_scouts_fizzle_on_an_adjacent_bond_and_no_group_is_made_of_one(base):
    """Bonds only: ``plato-adjacent`` has no group category, so a group scout that starts from an
    adjacent bond reaches its ``grp_cat is None`` check and fizzles."""
    ctx = fresh_ctx(base, ("ace", "acf", "bdf"))
    adjacent = ctx.slipnet.nodes[ADJACENT]
    assert adjacent.get_related_node(role_node(ctx, "dimension.group_category")) is None
    for scout in ("top-down-group-scout:direction", "group-scout:whole-string"):
        assert "grp_cat is None" in base.codelet_specs[scout].execute_body
        assert "get_related_node(role('dimension.group_category'))" in base.codelet_specs[scout].execute_body
    runner, _ = run(base, ADJACENT_PROBLEM, ADJACENT_SEED, steps=ADJACENT_STEPS)
    strings = runner.ctx.workspace.all_strings
    assert any(b.bond_category.name == ADJACENT for s in strings for b in s.bonds)  # adjacent bonds stand
    assert not any(b.bond_category.name == ADJACENT
                   for s in strings for g in s.groups for b in getattr(g, "bonds", ()))


def role_node(ctx, name):
    return ctx.slipnet.roles.get(name)


def test_an_adjacent_bond_is_weak_until_its_category_is_fully_active(base):
    ctx = fresh_ctx(base, ("ace", "acf", "bdf"))
    adjacent, successor = ctx.slipnet.nodes[ADJACENT], ctx.slipnet.nodes["plato-successor"]
    assert adjacent.intrinsic_link_length == 90 and successor.intrinsic_link_length == 60
    assert adjacent.degree_of_assoc() == 10 and successor.degree_of_assoc() == 40
    adjacent.activation = 100.0
    assert adjacent.degree_of_assoc() > 10  # a fully active category shrinks its length


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
