"""EN5b: the alphabet and the numbers are data (plan 3.13; ABSENCE-BEHAVIOUR.md section 3).

* G5: ``slipnet.alphabet`` equals the old hard-coded lists under the Metacat Standard
  Configuration (the lists themselves are deleted from ``images.py`` and ``groups.py``; the
  committed recording ``tests/seed_unit/role_identity_today.json`` still holds them).
* Build rules: first by node order wins a shared glyph or value; the build never raises.
* Problem parsing: a character with no glyph node is not perceived.
* G9: an alphabet of a to d and w to z (with and without the links of the removed letters left
  in place) and a gapped ladder (1, 2, 4) build a run on every demo problem and step.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from server.engine.numeric.backend import use_backend
from server.engine.rng import RNG
from server.engine.runner import EngineRunner
from server.engine.slipnet import Slipnet
from server.engine.workspace import WorkspaceString
from server.engine.workspace_objects import _is_generic_descriptor
from tests.support import golden_baseline as gb
from tests.support import reduced_configurations as rc
from tests.support.role_table import LETTER_NODES, NUMBER_NODES

RECORDING = Path(__file__).resolve().parents[1] / "seed_unit" / "role_identity_today.json"
G9_STEPS = 150

#: The set ``workspace_objects._NON_DISTINGUISHING_NAMES`` held before EN5b.
OLD_NON_DISTINGUISHING = {
    "plato-letter", "plato-group", "plato-one", "plato-two", "plato-three", "plato-four",
    "plato-five",
}


@pytest.fixture(scope="module")
def meta():
    return gb.load_meta() if hasattr(gb, "load_meta") else rc.provider(rc.standard())


@pytest.fixture(scope="module")
def slipnet(meta):
    return Slipnet.from_metadata(meta)


# --- G5 ------------------------------------------------------------------------------------


def test_the_glyph_nodes_equal_the_old_letter_list(slipnet) -> None:
    old = json.loads(RECORDING.read_text())["ordered_lists_in_engine_code"]["alphabet"]
    assert old == list(LETTER_NODES)
    assert list(slipnet.alphabet.glyph_nodes) == [n[len("plato-"):] for n in old]
    for glyph, name in zip(slipnet.alphabet.glyph_nodes, old):
        assert slipnet.alphabet.glyph_nodes[glyph] is slipnet.nodes[name]


def test_the_numbers_equal_the_old_ladder(slipnet) -> None:
    old = json.loads(RECORDING.read_text())["ordered_lists_in_engine_code"]["ladder"]
    assert old == list(NUMBER_NODES)
    alphabet = slipnet.alphabet
    for n, name in enumerate(old, start=1):
        assert alphabet.number_for(n) is slipnet.nodes[name]
        assert alphabet.value_of(slipnet.nodes[name]) == n
    assert alphabet.number_for(0) is None and alphabet.number_for(6) is None
    assert alphabet.unit_length_node is slipnet.nodes["plato-one"]


def test_the_non_distinguishing_set_equals_the_old_set(slipnet) -> None:
    found = {n for n, node in slipnet.nodes.items() if _is_generic_descriptor(node)}
    assert found == OLD_NON_DISTINGUISHING


def test_first_and_last_letter_are_the_ones_the_old_code_named(slipnet) -> None:
    assert slipnet.alphabet.first_letter is slipnet.nodes["plato-a"]
    assert slipnet.alphabet.last_letter is slipnet.nodes["plato-z"]


def test_the_record_is_frozen(slipnet) -> None:
    with pytest.raises(Exception):
        slipnet.alphabet.first_letter = None  # type: ignore[misc]
    with pytest.raises(TypeError):
        slipnet.alphabet.glyph_nodes["q"] = None  # type: ignore[index]


# --- build rules ---------------------------------------------------------------------------


def _with_columns(meta, **by_name):
    specs = dict(meta.slipnet_node_specs)
    for name, columns in by_name.items():
        specs[name] = replace(specs[name], **columns)
    return replace(meta, slipnet_node_specs=specs)


def test_a_shared_glyph_goes_to_the_first_node_in_order(meta) -> None:
    dup = _with_columns(meta, **{"plato-b": {"glyph": "a"}})
    slipnet = Slipnet.from_metadata(dup)
    assert slipnet.alphabet.glyph_nodes["a"] is slipnet.nodes["plato-a"]
    assert "b" not in slipnet.alphabet.glyph_nodes


def test_a_shared_value_goes_to_the_first_node_in_order(meta) -> None:
    dup = _with_columns(meta, **{"plato-two": {"numeric_value": 1}})
    slipnet = Slipnet.from_metadata(dup)
    assert slipnet.alphabet.number_for(1) is slipnet.nodes["plato-one"]
    assert slipnet.alphabet.number_for(2) is None


def test_a_marker_with_no_letter_linked_gives_no_first_letter() -> None:
    reduced = rc.node_removed("plato-a")
    slipnet = Slipnet.from_metadata(rc.provider(reduced))
    assert slipnet.alphabet.first_letter is None
    assert slipnet.alphabet.last_letter is slipnet.nodes["plato-z"]


# --- problem parsing -----------------------------------------------------------------------


def test_a_character_with_no_glyph_node_is_not_perceived(slipnet) -> None:
    string = WorkspaceString("aXb", slipnet)
    assert [o.letter_category for o in string.objects] == [
        slipnet.nodes["plato-a"], None, slipnet.nodes["plato-b"]]
    assert string.length == 3


def test_letters_outside_a_d_w_z_are_not_perceived() -> None:
    slipnet = Slipnet.from_metadata(rc.provider(rc.a_d_w_z()))
    string = WorkspaceString("amrz", slipnet)
    assert [o.letter_category is not None for o in string.objects] == [True, False, False, True]


# --- G9 ------------------------------------------------------------------------------------


def _links_left(reduced: rc.Reduced) -> rc.Reduced:
    """What deleting the nodes through the Admin API leaves in the database when the links
    that name them stay in place: the node rows are gone, the links are not."""
    standard = rc.standard()
    reduced.documents["slipnet_links.json"] = list(standard.documents["slipnet_links.json"])
    return reduced


def a_d_w_z_links_left() -> rc.Reduced:
    return _links_left(rc.a_d_w_z())


def ladder_one_two_four() -> rc.Reduced:
    return _remove(("plato-three", "plato-five"))


def _remove(names) -> rc.Reduced:
    reduced = rc.standard()
    from tests.support import configuration_cascade as cascade
    for name in names:
        reduced.report.merge(cascade.remove_node(reduced.documents, name))
    return reduced


def ladder_one_two_four_links_left() -> rc.Reduced:
    return _links_left(ladder_one_two_four())


CONFIGS = {
    "a-d/w-z": rc.a_d_w_z,
    "a-d/w-z, links left": a_d_w_z_links_left,
    "ladder 1,2,4": ladder_one_two_four,
    "ladder 1,2,4, links left": ladder_one_two_four_links_left,
}


def _step(provider, problem, seed=1, steps=G9_STEPS):
    runner = EngineRunner(provider)
    with use_backend(gb.BACKEND):
        runner.init_mcat(*problem, seed=seed, rng=RNG(seed))
        for _ in range(steps):
            if runner.step_mcat().codelet_type is None:
                break
    return runner


def test_the_a_d_w_z_alphabet_derives_from_the_nodes_that_remain() -> None:
    slipnet = Slipnet.from_metadata(rc.provider(a_d_w_z_links_left()))
    assert "".join(slipnet.alphabet.glyph_nodes) == "abcdwxyz"
    assert slipnet.alphabet.first_letter is slipnet.nodes["plato-a"]
    assert slipnet.alphabet.last_letter is slipnet.nodes["plato-z"]


def test_a_gapped_ladder_names_only_the_counts_it_has() -> None:
    slipnet = Slipnet.from_metadata(rc.provider(ladder_one_two_four_links_left()))
    assert sorted(slipnet.alphabet.numbers) == [1, 2, 4]
    assert slipnet.alphabet.number_for(3) is None


@pytest.mark.slow
@pytest.mark.parametrize("config", sorted(CONFIGS))
def test_g9_every_demo_problem_builds_and_steps(config) -> None:
    provider = rc.provider(CONFIGS[config]())
    triples, _ = gb.demo_problems()
    for problem in triples:
        _step(provider, problem)


@pytest.mark.numeric_matrix
@pytest.mark.parametrize("config", ["a-d/w-z, links left", "ladder 1,2,4, links left"])
def test_g9_quick_two_problems(config) -> None:
    provider = rc.provider(CONFIGS[config]())
    for problem in (("abc", "abd", "xyz"), ("abc", "abd", "mrrjjj")):
        _step(provider, problem, steps=60)
