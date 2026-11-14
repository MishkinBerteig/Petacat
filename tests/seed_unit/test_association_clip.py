"""Association is a link length clipped to 0 to 100 where it is read (plan sections 4.3, 4.12, 9; L16).

* ``association_from_length`` is the one function that turns a length into an association.
* Under the Metacat Standard Configuration every length lies in 0 to 100, so the clip never binds: for
  every link and every labelling node, in every state that changes the answer, the new reads return exactly what
  the old expression ``max(0.0, 100.0 - length)`` returned, value and type.
* "Far-out configuration values", for link lengths: a configuration whose links are at -500, at -0.125 or at 250
  runs exactly as the same configuration with those links at 0 (or at 100) does, on every numeric backend.

The module is in the numeric matrix (``numeric_matrix``) because it runs the engine's numeric arithmetic.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.engine.metadata import MetadataProvider
from server.engine.numeric import available_backends
from server.engine.numeric.backend import use_backend
from server.engine.runner import EngineRunner
from server.engine.slipnet import Slipnet, association_from_length
from server.services import config_document as cd
from server.services.change_resolve import resolve

pytestmark = pytest.mark.numeric_matrix

SEED_DATA = Path(__file__).resolve().parents[2] / "seed_data"
BACKENDS = ["off", "python", "numpy", "mlx-cpu", "mlx"]


def _old(length):
    """What every site computed before the clip."""
    return max(0.0, 100.0 - length)


# -- the function -----------------------------------------------------------------------------------


@pytest.mark.parametrize("length, expected", [
    (0, 100.0), (-1, 100.0), (-0.125, 100.0), (-500, 100.0), (-1025.125, 100.0),
    (20, 80.0), (89.875, 10.125), (97, 3.0), (99.5, 0.5), (100, 0.0), (100.125, 0.0), (250, 0.0),
])
def test_a_length_gives_an_association_clipped_to_0_to_100(length, expected):
    got = association_from_length(length)
    assert got == expected and isinstance(got, float)


# -- the Standard: the new reads equal the old expression, value and type ---------------------------------


@pytest.fixture(scope="module")
def standard() -> MetadataProvider:
    return MetadataProvider.from_standard_configuration(str(SEED_DATA))


def _same(a, b):
    return a == b and type(a) is type(b)


def test_every_length_the_standard_holds_lies_in_0_to_100(standard):
    slipnet = Slipnet.from_metadata(standard)
    lengths = [l._fixed_link_length for n in slipnet.nodes.values() for l in n.outgoing_links if l.fixed_length]
    lengths += [n.intrinsic_link_length for n in slipnet.nodes.values() if n.intrinsic_link_length is not None]
    lengths += [n.shrunk_link_length() for n in slipnet.nodes.values() if n.intrinsic_link_length is not None]
    assert lengths and all(0 <= x <= 100 for x in lengths)


def test_every_link_and_label_reads_what_the_old_expression_read(standard):
    slipnet = Slipnet.from_metadata(standard)
    from server.engine.run_binding import constants  # noqa: F401  (the unset length is read through the run's constants)

    links = [l for n in slipnet.nodes.values() for l in n.outgoing_links]
    assert len(links) >= 200
    for node in slipnet.nodes.values():
        for fully_active in (False, True):
            node.activation = node.max_activation if fully_active else 0.0
            assert node.fully_active() is fully_active or node.max_activation != 100
        node.activation = 0.0
    checked = 0
    for state in (False, True):
        for node in slipnet.nodes.values():
            node.activation = 100.0 if state else 0.0
        for link in links:
            old_intrinsic = (
                _old(link._fixed_link_length) if link.fixed_length
                else _old(link.label_node.intrinsic_link_length) if link.label_node is not None
                and link.label_node.intrinsic_link_length is not None
                else None)
            if old_intrinsic is not None:
                assert _same(link.intrinsic_degree_of_association(), old_intrinsic)
            assert _same(link.degree_of_association(), _old(link.link_length()))
            checked += 1
        for node in slipnet.nodes.values():
            if node.intrinsic_link_length is None:
                continue
            length = node.shrunk_link_length() if node.fully_active() else node.intrinsic_link_length
            assert _same(node.degree_of_assoc(), _old(length))
            checked += 1
    assert checked > 400
    # a label held fully active reads its shrunk length, one that is not reads the intrinsic one
    labelled = [n for n in slipnet.nodes.values() if n.intrinsic_link_length is not None]
    assert labelled
    for node in labelled:
        node.activation = 0.0
        assert _same(node.degree_of_assoc(), _old(node.intrinsic_link_length))
        node.activation = 100.0
        assert _same(node.degree_of_assoc(), _old(node.shrunk_link_length()))


# -- the far-out values -----------------------------------------------------------------------------------


def _with_lengths(standard_doc, pick, target):
    """The Standard with every fixed link that *pick*s its length set to *target*."""
    links = json.loads((SEED_DATA / "slipnet_links.json").read_text())
    ops = []
    for lk in links:
        if lk["fixed_length"] and pick(lk["link_length"]):
            ops.append({"op": "adjust", "table": "slipnet_link_defs", "field": "link_length",
                        "key": {"from_node": lk["from_node"], "to_node": lk["to_node"],
                                "link_type": lk["link_type"], "label_node": lk["label_node"] or ""},
                        "by": target - lk["link_length"]})
    assert ops
    resolved, _ = resolve(standard_doc, {"ops": ops})
    return cd.provider(cd.apply_resolved(standard_doc, resolved))


def _fingerprint(meta, backend, problem, seed):
    runner = EngineRunner(meta)
    with use_backend(None if backend == "off" else backend):
        runner.init_mcat(*problem, seed=seed)
        runner.run_mcat(max_steps=500)
    answer = runner.ctx.workspace.answer_string
    return (
        answer.text if answer else None, runner.ctx.codelet_count, runner.ctx.rng.call_count, str(runner.status),
        {n: x.activation for n, x in runner.ctx.slipnet.nodes.items()},
    )


LOW, HIGH = (lambda x: x <= 75), (lambda x: x >= 90)
CASES = [("minus500", LOW, -500, 0), ("minus_eighth", LOW, -0.125, 0), ("over100", HIGH, 250, 100)]


@pytest.mark.parametrize("backend", BACKENDS)
@pytest.mark.parametrize("name, pick, far, near", CASES, ids=[c[0] for c in CASES])
def test_a_far_out_length_runs_as_the_edge_of_the_range_does(backend, name, pick, far, near):
    if backend not in ("off", *available_backends()):
        pytest.skip(f"{backend} is not available")
    doc = cd.document_from_standard_files(str(SEED_DATA))
    far_meta, near_meta = _with_lengths(doc, pick, far), _with_lengths(doc, pick, near)
    # the stored length is the far-out one: only the association read from it is clipped
    far_links = [l for n in Slipnet.from_metadata(far_meta).nodes.values() for l in n.outgoing_links
                 if l.fixed_length and l._fixed_link_length == far]
    assert far_links
    for problem, seed in ((("abc", "abd", "xyz"), 1), (("abc", "abd", "ijk"), 2)):
        assert _fingerprint(far_meta, backend, problem, seed) == _fingerprint(near_meta, backend, problem, seed)


def test_the_far_out_test_can_fail(standard):
    """The lengths do change a run when they stay inside 0 to 100: 0 against 60 is not the same run."""
    doc = cd.document_from_standard_files(str(SEED_DATA))
    a, b = _with_lengths(doc, LOW, 0), _with_lengths(doc, LOW, 60)
    assert _fingerprint(a, "off", ("abc", "abd", "xyz"), 1) != _fingerprint(b, "off", ("abc", "abd", "xyz"), 1)
