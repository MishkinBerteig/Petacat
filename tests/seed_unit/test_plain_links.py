"""A link type a configuration creates is live: plain links, ``links_of`` and the readers of links.

A link whose type has no behaviour is a **plain** link.  It sits in ``SlipnetNode.plain_links``, the
sixth list, last in ``outgoing_links``, spreads activation by its fixed length on every numeric
backend, survives a ``state_graph`` snapshot and restore, and is read by ``links_of``.  Under the
Metacat Standard Configuration every type has a behaviour, so the list is empty and the order of
``outgoing_links`` is what it always was.

The module is in the numeric matrix (``numeric_matrix``): every test runs on the CPU and on the GPU,
and the tests that name a backend force it inside the matrix's.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.engine.codelet_dsl.builtins import links_of
from server.engine.metadata import MetadataProvider
from server.engine.numeric import available_backends
from server.engine.numeric.backend import use_backend
from server.engine.roles import Absent, absent
from server.engine.runner import EngineRunner
from server.engine.slipnet import Slipnet
from server.engine.state_graph import _Reader, capture_run_state, restore_run_state
from server.services import config_document as cd
from server.services.change_resolve import resolve

pytestmark = pytest.mark.numeric_matrix

SEED_DATA = str(Path(__file__).resolve().parents[2] / "seed_data")
BACKENDS = ["off", "python", "numpy", "mlx-cpu", "mlx"]


def _ops():
    return [
        {"op": "add_link_type", "name": "near"},  # plain
        {"op": "add_link_type", "name": "kin", "behaviour": "lateral"},  # a created lateral type
        {"op": "add_link", "from": "plato-a", "to": "plato-c", "type": "near", "fixed": True, "length": 20},
        {"op": "add_link", "from": "plato-a", "to": "plato-d", "type": "kin", "fixed": True, "length": 40},
        {"op": "add_link", "from": "plato-a", "to": "plato-e", "type": "near", "fixed": True, "length": 0},
    ]


@pytest.fixture(scope="module")
def standard() -> MetadataProvider:
    return MetadataProvider.from_standard_configuration(SEED_DATA)


@pytest.fixture(scope="module")
def created() -> MetadataProvider:
    doc = cd.document_from_standard_files(SEED_DATA)
    resolved, _ = resolve(doc, {"ops": _ops()})
    return cd.provider(cd.apply_resolved(doc, resolved))


def test_a_plain_link_is_in_the_sixth_list_and_last_in_outgoing_links(created):
    a = Slipnet.from_metadata(created).nodes["plato-a"]
    assert [l.to_node.name for l in a.plain_links] == ["plato-c", "plato-e"]
    assert [l.link_type for l in a.plain_links] == ["near", "near"]
    # the created lateral type is a lateral link, in its list, after the Standard's
    assert a.lateral_links[-1].link_type == "kin" and a.lateral_links[-1].to_node.name == "plato-d"
    assert a.outgoing_links[-len(a.plain_links):] == a.plain_links
    assert a.outgoing_links == (
        a.category_links + a.instance_links + a.property_links + a.lateral_links + a.lateral_sliplinks + a.plain_links)
    assert all(l in a.outgoing_links for l in a.plain_links)
    assert all(l in l.to_node.incoming_links for l in a.plain_links)
    # only the node a plain link leaves has one
    others = [n for n in Slipnet.from_metadata(created).nodes.values() if n.plain_links and n.name != "plato-a"]
    assert others == []


def test_under_the_standard_configuration_the_list_is_empty_and_the_order_is_unchanged(standard):
    slipnet = Slipnet.from_metadata(standard)
    for node in slipnet.nodes.values():
        assert node.plain_links == []
        assert node.outgoing_links == (
            node.category_links + node.instance_links + node.property_links + node.lateral_links
            + node.lateral_sliplinks)


def test_a_link_whose_type_has_no_behaviour_attaches_to_no_other_list(created):
    a = Slipnet.from_metadata(created).nodes["plato-a"]
    for group in (a.category_links, a.instance_links, a.property_links, a.lateral_links, a.lateral_sliplinks):
        assert not any(l.link_type == "near" for l in group)


def test_a_plain_link_reads_its_length_as_its_association(created):
    a = Slipnet.from_metadata(created).nodes["plato-a"]
    assert [l.intrinsic_degree_of_association() for l in a.plain_links] == [80.0, 100.0]


# -- links_of ---------------------------------------------------------------------------------------


class _Ctx:  # links_of reads nothing of the context
    pass


def test_links_of_returns_the_nodes_outgoing_links_of_one_type_in_order(created):
    slipnet = Slipnet.from_metadata(created)
    a = slipnet.nodes["plato-a"]
    near = links_of(_Ctx(), a, "near")
    assert [(l.to_node.name, l.link_length()) for l in near] == [("plato-c", 20), ("plato-e", 0)]
    assert all(l in a.plain_links for l in near) and near is not a.plain_links
    assert [l.to_node.name for l in links_of(_Ctx(), a, "kin")] == ["plato-d"]
    assert [l.to_node.name for l in links_of(_Ctx(), a, "lateral")][:1] == ["plato-b"]
    assert links_of(_Ctx(), a, "nonexistent") == [] and links_of(_Ctx(), slipnet.nodes["plato-b"], "near") == []
    assert links_of(_Ctx(), absent("bond_category.adjacent"), "near") == []


def test_links_of_is_a_codelet_builtin_the_body_can_call(created):
    from server.engine.codelet_dsl.builtins import get_builtins

    assert get_builtins()["links_of"] is links_of


# -- spreading, on every backend ----------------------------------------------------------------------


class _NeverJumps:
    """A random source that says no to every jump, so a partly active node stays as spread."""

    def __init__(self):
        self.call_count = 0

    def prob(self, p):
        self.call_count += 1
        return False


def _spread(meta, backend, cycles=3):
    slipnet = Slipnet.from_metadata(meta)
    slipnet.nodes["plato-a"].activation = 100.0
    rng = _NeverJumps()
    with use_backend(None if backend == "off" else backend):
        for _ in range(cycles):
            slipnet.update_activations(rng, threshold=100)
    return {n: node.activation for n, node in slipnet.nodes.items()}, rng.call_count


@pytest.mark.parametrize("backend", BACKENDS)
def test_a_plain_link_spreads_activation_by_its_length_on_every_backend(backend, created):
    if backend not in ("off", *available_backends()):
        pytest.skip(f"{backend} is not available")
    one, _ = _spread(created, backend, cycles=1)
    # plato-c: 100 * (100 - 20) / 100 = 80 through the plain link; plato-e: association 100
    assert one["plato-c"] == 80.0 and one["plato-e"] == 100.0
    # plato-d: through the created lateral link, association 60
    assert one["plato-d"] == 60.0


@pytest.mark.parametrize("backend", BACKENDS[1:])
def test_every_backend_agrees_with_the_loops_over_several_cycles(backend, created):
    if backend not in available_backends():
        pytest.skip(f"{backend} is not available")
    reference = _spread(created, "off")
    got = _spread(created, backend)
    assert got == reference


def test_without_the_plain_link_nothing_reaches_the_target(standard):
    got, _ = _spread(standard, "off", cycles=1)
    assert got["plato-c"] == 0.0 and got["plato-e"] == 0.0


# -- the state graph: snapshot and restore ----------------------------------------------------------------


def test_a_snapshot_restores_a_run_on_a_configuration_with_plain_links(created):
    problem = ("abc", "abd", "xyz")
    whole = EngineRunner(created)
    whole.init_mcat(*problem, seed=3)
    whole.run_mcat(max_steps=700)

    first = EngineRunner(created)
    first.init_mcat(*problem, seed=3)
    first.run_mcat(max_steps=300)
    state = json.loads(json.dumps(capture_run_state(first.ctx)))
    second = EngineRunner(created)
    second.init_mcat(*problem, seed=3)
    restore_run_state(second, state)
    second.run_mcat(max_steps=400)
    assert (second.ctx.codelet_count, second.status) == (whole.ctx.codelet_count, whole.status)
    assert {n: x.activation for n, x in second.ctx.slipnet.nodes.items()} == {
        n: x.activation for n, x in whole.ctx.slipnet.nodes.items()}
    assert second.ctx.rng.call_count == whole.ctx.rng.call_count


def test_a_link_in_a_snapshot_is_found_among_the_plain_links(created):
    slipnet = Slipnet.from_metadata(created)
    reader = _Reader([], slipnet, {})
    found = reader._find_link("plato-a", "plato-c", "near")
    assert found is slipnet.nodes["plato-a"].plain_links[0]
    assert reader._find_link("plato-a", "plato-d", "kin") is slipnet.nodes["plato-a"].lateral_links[-1]
    assert reader._find_link("plato-a", "plato-b", "near") is None


# -- the Absent token and the role -----------------------------------------------------------------------------


def test_the_absent_token_has_an_empty_plain_list():
    assert absent("bond_category.adjacent").plain_links == () and isinstance(absent("x"), Absent)


def test_the_adjacent_bond_category_role_is_absent_under_the_standard(standard):
    roles = Slipnet.from_metadata(standard).roles
    assert roles.bond_category_adjacent is absent("bond_category.adjacent") and not roles.bond_category_adjacent
