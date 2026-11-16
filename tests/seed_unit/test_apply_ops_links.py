"""``apply_ops`` builds links in a run's own Slipnet (increment 4, stage A).

Besides ``add_node``, ``apply_ops`` takes ``add_link`` (in the change API's shape) and ``scale`` and ``adjust`` of a
link's length (``slipnet_link_defs``, ``link_length``).  Each changes **this run's Slipnet at once**: the behaviour
list the link's type names, the target's incoming links, ``links_of``, category membership, ``get_related_node``,
the alphabet's first and last letters, and the numeric layout on every backend.  What was applied is recorded in
``ctx.proposals`` for the session, composed as ``propose_ops`` composes.  Everything is checked before anything is
changed, and anything else is refused by name.
"""

from __future__ import annotations

import copy
import math
import pickle
from pathlib import Path

import pytest

from server.engine.codelet_dsl.builtins import apply_ops, links_of, propose_ops
from server.engine.metadata import MetadataProvider
from server.engine.numeric import available_backends
from server.engine.numeric.backend import use_backend
from server.engine.runner import EngineRunner
from server.engine.slipnet import Slipnet, _UNRESOLVED
from server.services import config_document as cd
from server.services import training_base as tb
from server.services.change_resolve import resolve
from tests.support.noticing_configuration import every_noticing

pytestmark = pytest.mark.numeric_matrix

SEED_DATA = str(Path(__file__).resolve().parents[2] / "seed_data")
BACKENDS = ["off", "python", "numpy", "mlx-cpu", "mlx"]
A, B, C, D, K = "plato-a", "plato-b", "plato-c", "plato-d", "plato-k"
LC = "plato-letter-category"
ADJ = "plato-adjacent"


def node_op(ch):
    return {"op": "add_node", "name": "plato-cp-%04x" % ord(ch), "fields": {
        "short_name": ch, "glyph": ch, "plain_name": ch, "article_an": False, "conceptual_depth": 10}}


def link_op(frm, to, kind="adjacent", length=40, label=ADJ, **more):
    op = {"op": "add_link", "from": frm, "to": to, "type": kind, "fixed": True, "length": length, **more}
    if label is not None:
        op["label"] = label
    return op


def key(frm, to, kind="adjacent", label=ADJ):
    return {"from_node": frm, "to_node": to, "link_type": kind, "label_node": label}


def scale_op(frm, to, factor, kind="adjacent", label=ADJ):
    return {"op": "scale", "table": "slipnet_link_defs", "key": key(frm, to, kind, label),
            "field": "link_length", "factor": factor}


def adjust_op(frm, to, by, kind="adjacent", label=ADJ):
    return {"op": "adjust", "table": "slipnet_link_defs", "key": key(frm, to, kind, label),
            "field": "link_length", "by": by}


@pytest.fixture(scope="module")
def document():
    doc = tb.resolve_base().document
    ops, _ = resolve(doc, {"ops": [{"op": "add_link_type", "name": "near"}]})
    return cd.apply_resolved(doc, ops)


@pytest.fixture(scope="module")
def base(document) -> MetadataProvider:
    return cd.provider(document)


def fresh_ctx(meta, problem=("abc", "abd", "xyz")):
    runner = EngineRunner(meta)
    runner.init_mcat(*problem, None, seed=1)
    return runner.ctx


def with_links(document, *ops):
    """The Base's configuration with the change-API ops applied: what a session would hold."""
    resolved, _ = resolve(document, {"ops": list(ops)})
    return cd.provider(cd.apply_resolved(document, resolved))


# -- the shape checks and the refusals ---------------------------------------------------------------------


REFUSED = [
    ({**link_op(A, D), "extra": 1}, "add_link has no"),
    ({k: v for k, v in link_op(A, D).items() if k != "from"}, "needs 'from'"),
    ({k: v for k, v in link_op(A, D).items() if k != "to"}, "needs 'to'"),
    ({k: v for k, v in link_op(A, D).items() if k != "type"}, "needs 'type'"),
    (link_op("no-such-node", D), "no such node"),
    (link_op(A, "no-such-node"), "no such node"),
    (link_op(A, D, kind="no-such-type"), "no such link type"),
    (link_op(A, D, label="no-such-node"), "no such node"),
    (link_op(A, D, label=5), "label"),
    ({k: v for k, v in link_op(A, D).items() if k != "fixed"}, "needs 'fixed'"),
    (link_op(A, D, fixed="yes"), "needs 'fixed'"),
    ({k: v for k, v in link_op(A, D).items() if k != "length"}, "finite number"),
    (link_op(A, D, length=float("nan")), "finite number"),
    (link_op(A, D, length=float("inf")), "finite number"),
    (link_op(A, D, length="40"), "finite number"),
    (link_op(A, D, length=True), "finite number"),
    (link_op(A, D, length=10 ** 400), "finite number"),
    (link_op(A, D, fixed=False), "no 'length'"),
    (link_op(A, D, kind="near", fixed=False, length=None), "no behaviour"),
    (scale_op(A, D, 2), "no link"),                       # the run's Slipnet has no such link
    (adjust_op(A, D, 2), "no link"),
    ({**scale_op(A, B, 2, kind="lateral", label=None), "extra": 1}, "has no"),
    ({**scale_op(A, B, 2, kind="lateral", label=None), "table": "slipnet_node_defs"}, "takes a link's length"),
    ({**scale_op(A, B, 2, kind="lateral", label=None), "field": "fixed_length"}, "takes a link's length"),
    ({**scale_op(A, B, 2, kind="lateral", label=None), "key": {"from_node": A, "to_node": B}}, "takes a link's length"),
    ({**scale_op(A, B, 2, kind="lateral", label=None), "key": {**key(A, B, "lateral", ""), "extra": 1}},
     "takes a link's length"),
    (scale_op(A, B, "2", kind="lateral", label=""), "finite"),
    (scale_op(A, B, float("nan"), kind="lateral", label=""), "finite"),
    (scale_op(A, B, True, kind="lateral", label=""), "finite"),
    (adjust_op(A, B, float("inf"), kind="lateral", label=""), "finite"),
    ({"op": "add_trigger", "rule_key": "x", "node": A}, "add_trigger"),
    ({"op": "adjust", "table": "slipnet_node_defs", "key": {"name": A}, "field": "noticings", "by": 1}, "adjust"),
    ({"op": "remove_link", "key": key(A, B)}, "remove_link"),
    ("not an op", "None"),
]


@pytest.mark.parametrize("bad,why", REFUSED, ids=[str(i) for i in range(len(REFUSED))])
def test_an_op_apply_ops_does_not_take_is_refused_by_name_and_nothing_is_changed(base, bad, why):
    ctx = fresh_ctx(base)
    before = [(n.name, [(l.to_node.name, l.link_type, l.link_length()) for l in n.outgoing_links])
              for n in ctx.slipnet.nodes.values()]
    with pytest.raises(ValueError, match=why):
        apply_ops(ctx, [link_op(C, B, length=33), bad])  # a good op first: the whole call is checked before any is applied
    assert ctx.proposals == []
    assert before == [(n.name, [(l.to_node.name, l.link_type, l.link_length()) for l in n.outgoing_links])
                      for n in ctx.slipnet.nodes.values()]


def test_a_scale_of_a_link_that_is_not_fixed_length_or_whose_result_is_not_finite_is_refused(base):
    ctx = fresh_ctx(base)
    # a link with no fixed length (its length is its label's): a 'lateral' link of the Standard's with no stored length
    dynamic = next(l for l in ctx.slipnet.nodes[A].lateral_links if not l.fixed_length)
    with pytest.raises(ValueError, match="no fixed length"):
        apply_ops(ctx, [scale_op(A, dynamic.to_node.name, 2, "lateral", dynamic.label_node.name)])
    apply_ops(ctx, [link_op(A, D, length=1e300)])
    with pytest.raises(ValueError, match="not finite"):
        apply_ops(ctx, [scale_op(A, D, 1e300)])
    with pytest.raises(ValueError, match="not finite"):
        apply_ops(ctx, [adjust_op(A, D, 1.7e308), adjust_op(A, D, 1.7e308), adjust_op(A, D, 1.7e308)])
    assert ctx.slipnet.find_link(A, D, "adjacent", ADJ).link_length() == 1e300
    assert ctx.proposals == [link_op(A, D, length=1e300)]


def test_a_later_op_of_the_same_call_sees_the_earlier_ones(base):
    ctx = fresh_ctx(base)
    apply_ops(ctx, [node_op("1"), link_op("plato-cp-0031", A, length=30), scale_op("plato-cp-0031", A, 0.5),
                    adjust_op("plato-cp-0031", A, 1)])
    assert ctx.slipnet.find_link("plato-cp-0031", A, "adjacent", ADJ).link_length() == 16
    # a scale before the add_link of the same call has no link to scale
    with pytest.raises(ValueError, match="no link"):
        apply_ops(fresh_ctx(base), [scale_op(A, D, 0.5), link_op(A, D)])


# -- every derived structure sees an in-run link at once -----------------------------------------------------------


def test_an_added_link_is_in_its_types_list_the_targets_incoming_links_and_everything_derived_from_them(base):
    ctx = fresh_ctx(base)
    slip = ctx.slipnet
    a, d = slip.nodes[A], slip.nodes[D]
    before = list(a.outgoing_links)
    slip._numeric = None  # "a backend session is open"
    apply_ops(ctx, [link_op(A, D, length=40)])
    link = slip.find_link(A, D, "adjacent", ADJ)
    assert link is not None and link.fixed_length and link.link_length() == 40 and link.label_node is slip.nodes[ADJ]
    assert link.from_node is a and link.to_node is d
    # the list of the type's behaviour (adjacent is a lateral type), last in it; incoming on the target
    assert a.lateral_links[-1] is link and link not in a.category_links + a.instance_links + a.property_links
    assert a.outgoing_links[:len(before)] == before or set(before) <= set(a.outgoing_links)
    assert link in a.outgoing_links and link in d.incoming_links
    assert links_of_names(ctx, a, "adjacent") == [(D, ADJ, 40)]
    # what a lateral link is read for: the label's get_related_node, and the slippage and label reads
    assert slip.get_label(a, d) is slip.nodes[ADJ] or slip.get_label(a, d) is not None
    assert slip._numeric is _UNRESOLVED
    assert ctx.proposals == [link_op(A, D, length=40)]


def links_of_names(ctx, node, kind):
    return [(l.to_node.name, l.label_node.name if l.label_node else "", l.link_length()) for l in links_of(ctx, node, kind)]


def test_a_labelled_link_is_found_by_get_related_node_and_the_label_read(base):
    ctx = fresh_ctx(base)
    slip = ctx.slipnet
    a, d = slip.nodes[A], slip.nodes[D]
    assert a.get_related_node(slip.nodes[ADJ]) is None and slip.get_label(a, d) is None
    apply_ops(ctx, [link_op(A, D)])
    assert a.get_related_node(slip.nodes[ADJ]) is d and a.get_related_node(ADJ) is d
    assert slip.get_label(a, d) is slip.nodes[ADJ]


def test_a_category_and_an_instance_link_built_in_a_run_change_what_the_runs_category_reads_return(base):
    ctx = fresh_ctx(base, ("1", "1", "1"))
    slip = ctx.slipnet
    lc, one = slip.nodes[LC], None
    apply_ops(ctx, [node_op("1")])
    one = slip.nodes["plato-cp-0031"]
    assert one.category is None and not one.is_instance and one.category_links == []
    assert one not in [l.to_node for l in lc.instance_links]
    apply_ops(ctx, [link_op(one.name, LC, "category", 20, label=None), link_op(LC, one.name, "instance", 97, label=None)])
    assert one.category is lc and one.is_instance
    assert [l.to_node for l in one.category_links] == [lc] and one.outgoing_links[0].to_node is lc
    assert lc.instance_links[-1].to_node is one and lc.instance_links[-1].link_length() == 97
    assert links_of_names(ctx, one, "category") == [(LC, "", 20)]
    assert links_of_names(ctx, lc, "instance")[-1] == (one.name, "", 97)
    # the Standard's letters have the same two links, at the same lengths
    assert links_of_names(ctx, slip.nodes[A], "category") == [(LC, "", 20)]
    assert (A, "", 97) in links_of_names(ctx, lc, "instance")
    # a built link joins the Workspace's reads: the dimension's instances now include the symbol
    assert one in [l.to_node for l in slip.nodes[LC].instance_links]


def test_a_property_link_changes_the_alphabets_first_and_last_letter(base):
    ctx = fresh_ctx(base)
    slip = ctx.slipnet
    first = slip.alphabet.first_letter
    assert first is not None and first.name == A
    marker = slip.roles.alphabet_first_marker
    assert marker
    apply_ops(ctx, [link_op(B, marker.name, "property", 75, label=None)])
    assert slip.alphabet.first_letter is first  # first by node order stays a
    apply_ops(ctx, [node_op("1")])
    slip2 = ctx.slipnet
    apply_ops(ctx, [link_op("plato-cp-0031", marker.name, "property", 75, label=None)])
    assert slip2.alphabet.glyph_nodes["1"].property_links[0].to_node is marker


def test_a_plain_link_goes_in_the_sixth_list_and_a_slip_link_in_the_slip_list(base):
    ctx = fresh_ctx(base)
    a = ctx.slipnet.nodes[A]
    apply_ops(ctx, [link_op(A, D, "near", 12, label=None)])
    assert [l.to_node.name for l in a.plain_links] == [D] and a.outgoing_links[-1] is a.plain_links[0]
    assert links_of_names(ctx, a, "near") == [(D, "", 12)]


def test_an_add_link_whose_link_the_run_already_has_changes_nothing_in_the_run(base):
    ctx = fresh_ctx(base)
    a = ctx.slipnet.nodes[A]
    apply_ops(ctx, [link_op(A, D, length=40)])
    ctx.slipnet._numeric = None
    snapshot = list(a.outgoing_links)
    apply_ops(ctx, [link_op(A, D, length=99)])  # the run has the link: its length stays 40
    assert a.outgoing_links == snapshot and ctx.slipnet.find_link(A, D, "adjacent", ADJ).link_length() == 40
    assert ctx.slipnet._numeric is None  # nothing was invalidated
    # a link the configuration holds (a seed link) is a no-op as well, and is still recorded for the session
    seed = a.category_links[0]
    apply_ops(ctx, [link_op(A, seed.to_node.name, "category", seed.link_length(), label=None)])
    assert a.category_links == [seed]


def test_scale_and_adjust_change_the_length_in_the_run_at_once_and_normalise_a_whole_result(base):
    ctx = fresh_ctx(base)
    slip = ctx.slipnet
    apply_ops(ctx, [link_op(A, D, length=40)])
    link = slip.find_link(A, D, "adjacent", ADJ)
    slip._numeric = None
    apply_ops(ctx, [scale_op(A, D, 0.5)])
    assert link.link_length() == 20 and type(link.link_length()) is int  # whole stays an int
    assert slip._numeric is _UNRESOLVED
    apply_ops(ctx, [adjust_op(A, D, 0.25)])
    assert link.link_length() == 20.25
    apply_ops(ctx, [adjust_op(A, D, -30)])  # no range beyond finite: a negative length is allowed
    assert link.link_length() == pytest.approx(-9.75)
    assert link.degree_of_association() == 100.0  # ... and the association read from it is clipped
    # the keys' None reads as "" (no label): a link with no label is addressed either way
    apply_ops(ctx, [link_op(A, B, "near", 8, label=None)])
    apply_ops(ctx, [{**scale_op(A, B, 2, "near", None)}])
    assert slip.find_link(A, B, "near").link_length() == 16


def test_what_was_applied_is_recorded_and_composes_like_propose_ops(base):
    ctx = fresh_ctx(base)
    apply_ops(ctx, [link_op(A, D, length=40), scale_op(A, D, 0.5)])
    apply_ops(ctx, [link_op(A, D, length=40), scale_op(A, D, 0.5), adjust_op(A, D, 1), adjust_op(A, D, 2)])
    assert ctx.proposals == [link_op(A, D, length=40), scale_op(A, D, 0.25), adjust_op(A, D, 3)]
    # ... and exactly as propose_ops composes the same ops
    other = fresh_ctx(base)
    propose_ops(other, [link_op(A, D, length=40), scale_op(A, D, 0.5), link_op(A, D, length=40), scale_op(A, D, 0.5),
                        adjust_op(A, D, 1), adjust_op(A, D, 2)])
    assert other.proposals == ctx.proposals
    assert pickle.loads(pickle.dumps(ctx.proposals)) == ctx.proposals
    assert math.isclose(ctx.slipnet.find_link(A, D, "adjacent", ADJ).link_length(), 40 * 0.25 + 3)


def test_apply_ops_draws_no_random_number_touches_no_workspace_structure_and_writes_nothing_shared(base):
    ctx = fresh_ctx(base)
    draws, objects = ctx.rng.call_count, list(ctx.workspace.all_objects)
    shared = copy.deepcopy([(s.from_node, s.to_node, s.link_type, s.label_node, s.link_length)
                            for s in base.slipnet_link_specs])
    apply_ops(ctx, [link_op(A, D), scale_op(A, D, 0.5)])
    assert ctx.rng.call_count == draws and list(ctx.workspace.all_objects) == objects
    assert shared == [(s.from_node, s.to_node, s.link_type, s.label_node, s.link_length) for s in base.slipnet_link_specs]
    other = fresh_ctx(base)  # another run of the same provider sees nothing of it
    assert other.slipnet.find_link(A, D, "adjacent", ADJ) is None and other.proposals == []


# -- the numeric layout, on every backend --------------------------------------------------------------------------


class _NeverJumps:
    """A random source that says no to every jump, so a partly active node stays as spread."""

    def __init__(self):
        self.call_count = 0

    def prob(self, p):
        self.call_count += 1
        return False


def activations(slipnet):
    return {n: node.activation for n, node in slipnet.nodes.items()}


def spread(slipnet, backend, cycles=2):
    rng = _NeverJumps()
    with use_backend(None if backend == "off" else backend):
        for _ in range(cycles):
            slipnet.update_activations(rng, threshold=100)
    return activations(slipnet), rng.call_count


def copy_state(source, target):
    """Give *target* the activations and clamps of *source*, with ``plato-a`` fully active again (so that it spreads)
    and every buffer empty."""
    for name, node in target.nodes.items():
        node.activation = source.nodes[name].activation
        node.activation_buffer = 0.0
        node.frozen = source.nodes[name].frozen
    target.nodes[A].activation = 100.0


@pytest.mark.parametrize("backend", BACKENDS)
def test_an_in_run_link_spreads_activation_exactly_as_the_same_link_in_the_configuration_on_every_backend(
        backend, document):
    if backend not in ("off", *available_backends()):
        pytest.skip(f"{backend} is not available")
    meta = cd.provider(document)
    # What the session would hold if the link had been in the configuration all along, at its two lengths.
    early = with_links(document, link_op(A, K, length=40))
    late = with_links(document, link_op(A, K, length=20))

    ctx = fresh_ctx(meta)
    slip = ctx.slipnet
    slip.nodes[A].activation = 100.0
    spread(slip, backend, cycles=1)  # opens a backend session on the Slipnet as it is, without the link

    # the link is built: the session's flattened edges are forgotten and the next update has the new edge
    copy_state(slip, slip)  # plato-a spreads again, and nothing is waiting in a buffer
    state = Slipnet.from_metadata(meta)
    copy_state(slip, state)
    apply_ops(ctx, [link_op(A, K, length=40)])
    got, got_draws = spread(slip, backend, cycles=1)
    reference = Slipnet.from_metadata(early)
    copy_state(state, reference)
    want, want_draws = spread(reference, "off", cycles=1)
    assert got == want and got_draws == want_draws
    assert got[K] > 0  # the link is what carried it: without the link plato-d gets nothing

    # the link's length changes after the session was opened on the longer link: the weights change at once
    copy_state(slip, slip)
    state = Slipnet.from_metadata(meta)
    copy_state(slip, state)
    apply_ops(ctx, [adjust_op(A, K, -20)])
    got, _ = spread(slip, backend, cycles=1)
    reference = Slipnet.from_metadata(late)
    copy_state(state, reference)
    want, _ = spread(reference, "off", cycles=1)
    assert got == want
    assert slip.find_link(A, K, "adjacent", ADJ).link_length() == 20


@pytest.mark.parametrize("backend", BACKENDS[1:])
def test_a_run_that_builds_links_agrees_on_every_backend_in_answer_draws_and_activations(backend, document):
    """The v2.0 Base builds ``adjacent`` links in the run (``consolidator`` and ``adjacent-instantiator``) on a problem
    whose neighbours have no relation.  Every backend agrees with the loops: answer, codelets, random draws, the
    run's recorded proposals and every node's final activation."""
    if backend not in available_backends():
        pytest.skip(f"{backend} is not available")
    meta = cd.provider(every_noticing(tb.resolve_base().document))  # noticings drive the links this run builds

    def go(name):
        runner = EngineRunner(meta)
        with use_backend(None if name == "off" else name):
            runner.init_mcat("ace", "ace", "ace", None, seed=1)
            runner.run_mcat(max_steps=700)
        ctx = runner.ctx
        answer = ctx.workspace.answer_string
        return {"answer": answer.text if answer else None, "codelets": ctx.codelet_count, "draws": ctx.rng.call_count,
                "proposals": list(ctx.proposals), "activations": activations(ctx.slipnet),
                "links": sorted((l.from_node.name, l.to_node.name, l.link_length()) for n in ctx.slipnet.nodes.values()
                                for l in n.outgoing_links if l.link_type == "adjacent")}

    reference = go("off")
    assert reference["links"], "the run builds an adjacent link"
    assert any(p["op"] == "add_link" for p in reference["proposals"])
    assert go(backend) == reference
