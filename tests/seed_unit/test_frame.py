"""Stage 6: the four-string frame is configuration, defined once (ruling 11).

``string_kinds`` (``exists_at_start``), ``bridge_types`` (``from_string_kind``, ``to_string_kind``,
``orientation``, ``theme_type``) and ``rule_types`` (``bridge_type``) are the one definition.
``server/engine/frame.py`` derives from them what had been written in six places: what each kind of
string maps, who its partner is, which theme types a description speaks to, the order of the theme types
in each mode, the rule types' pairs.  This file checks

1. the derivation gives the Metacat table (the oracle is the table as the code wrote it, below);
2. the engine reads it: a topology row changed in the configuration changes a run
   (``numeric_matrix``), one row per kind of thing the tables define;
3. a row that is missing or incomplete leaves the thing out, and the run goes on or stops at its start.
"""

from __future__ import annotations

import dataclasses
import os

import pytest

from server.engine.frame import BOTH_ORIENTATIONS, Frame
from server.engine.metadata import MetadataProvider
from tests.support.run_fingerprint import fingerprint

pytestmark = pytest.mark.numeric_matrix

SEED = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")


@pytest.fixture(scope="module")
def meta() -> MetadataProvider:
    return MetadataProvider.from_standard_configuration(SEED)


@pytest.fixture(scope="module")
def frame(meta) -> Frame:
    return meta.frame


# ------------------------------------------------------------ 1. the Metacat table, as the code wrote it

#: ``(maps_horizontal, maps_vertical, horizontal_needs_justify)`` of each kind: the four ``cond``
#: ladders of ``workspace-objects.ss:457-587`` (what ``string_kind_facts`` returned before stage 6).
FACTS = {
    "initial": (True, True, False),
    "modified": (True, False, False),
    "target": (False, True, True),
    "answer": (True, False, False),
}


def old_other_string(kind: str, key: str) -> str:
    """``get-other-string`` (``workspace.ss:161-172``) as ``Workspace.get_other_string`` wrote it."""
    if kind == "initial":
        return "modified" if key in ("top", "horizontal") else "target"
    if kind == "modified":
        return "initial"
    if kind == "target":
        return "answer" if key in ("bottom", "horizontal") else "initial"
    return "target"


def test_the_facts_are_the_ones_the_ladders_wrote(frame):
    assert {k: frame.facts(k) for k in FACTS} == FACTS
    assert frame.facts("nothing") == (False, False, False)
    assert frame.facts(None) == (False, False, False)


@pytest.mark.parametrize("kind", sorted(FACTS))
@pytest.mark.parametrize("key", ["top", "bottom", "vertical", "horizontal", "unheard-of"])
def test_the_partner_is_the_one_get_other_string_gave(frame, kind, key):
    assert frame.other_kind(kind, key) == old_other_string(kind, key)


def test_a_string_no_bridge_ends_in_has_no_partner(frame):
    assert frame.other_kind("nothing", "top") is None


def test_the_theme_types_are_the_ones_descriptions_spoke_to(frame):
    assert frame.theme_types == ("top_bridge", "bottom_bridge", "vertical_bridge")
    assert frame.discovery_theme_types == ("top_bridge", "vertical_bridge")
    assert frame.kind_theme_types("initial") == (("top_bridge", "vertical_bridge"), ())
    assert frame.kind_theme_types("modified") == (("top_bridge",), ())
    assert frame.kind_theme_types("target") == (("vertical_bridge",), ("bottom_bridge",))
    assert frame.kind_theme_types("answer") == (("bottom_bridge",), ())
    assert set(frame.kind_theme_types("nothing")[0]) == {"top_bridge", "bottom_bridge", "vertical_bridge"}


def test_a_bridge_type_and_the_theme_type_it_feeds_name_each_other(frame):
    assert frame.theme_type_for["top"] == frame.theme_type_for["top_bridge"] == "top_bridge"
    assert frame.bridge_for_theme_type == {
        "top_bridge": "top", "bottom_bridge": "bottom", "vertical_bridge": "vertical"}
    assert frame.orientation == {"top": "horizontal", "bottom": "horizontal", "vertical": "vertical"}
    assert frame.vertical_names == frozenset({"vertical"})


def test_the_rules_describe_the_pairs_their_bridges_join(frame):
    assert {r.name: (r.bridge.from_kind, r.bridge.to_kind, r.needs_justify) for r in frame.rules} == {
        "top": ("initial", "modified", False), "bottom": ("target", "answer", True)}
    assert frame.going_down_kinds == frozenset({"initial", "modified"})
    assert frame.rule_theme_types == {"top": "top_bridge", "bottom": "bottom_bridge"}
    assert frame.horizontal_bridge_of == {
        "initial": "top", "modified": "top", "target": "bottom", "answer": "bottom"}
    assert frame.vertical_kinds == ("initial", "target")


def test_the_mapped_token_follows_the_facts(frame):
    no, yes = frame.mapped_tokens
    assert (no["initial"], yes["initial"]) == (BOTH_ORIENTATIONS, BOTH_ORIENTATIONS)
    assert (no["target"], yes["target"]) == ("vertical", BOTH_ORIENTATIONS)
    assert (no["modified"], yes["modified"], no["answer"], yes["answer"]) == ("horizontal",) * 4


def test_the_numeric_layout_codes_follow_the_facts(frame):
    from server.engine.numeric.layout import (
        STRING_INITIAL, STRING_MODIFIED, STRING_OTHER, STRING_TARGET, string_type_codes,
    )

    assert string_type_codes(frame) == {
        "initial": STRING_INITIAL, "modified": STRING_MODIFIED, "target": STRING_TARGET,
        "answer": STRING_MODIFIED}
    assert STRING_OTHER not in string_type_codes(frame).values()


# ------------------------------------------------------------ 2. the engine reads the rows


def _edit(field, name, **changes):
    return lambda m: dataclasses.replace(m, **{field: tuple(
        dataclasses.replace(r, **changes) if r.name == name else r for r in getattr(m, field))})


#: row changed -> (problem, seed) in which the run changes (found with ``work/mutate_policy.py``).
MUTATIONS = {
    "an answer string that is there from the start": (
        _edit("string_kinds", "answer", exists_at_start=True), ("abc", "abd", "xyz"), 1),
    "the bottom bridge feeds the top theme type": (
        _edit("bridge_types", "bottom", theme_type="top_bridge"), ("abc", "abd", "xyz"), 1),
    "the top bridge feeds the vertical theme type": (
        _edit("bridge_types", "top", theme_type="vertical_bridge"), ("abc", "abd", "xyz"), 1),
    "the top bridge is vertical": (
        _edit("bridge_types", "top", orientation="vertical"), ("abc", "abd", "xyz"), 1),
    "the vertical bridge joins initial and modified": (
        _edit("bridge_types", "vertical", to_string_kind="modified"), ("abc", "abd", "xyz"), 1),
    "the bottom rule describes the top bridge's pair": (
        _edit("rule_types", "bottom", bridge_type="top"), ("abc", "abd", "xyz"), 1),
}


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_a_run_changes_when_a_topology_row_changes(meta, name):
    mutate, problem, seed = MUTATIONS[name]
    assert fingerprint(mutate(meta), problem, seed, cap=1500) != fingerprint(meta, problem, seed, cap=1500)


# ------------------------------------------------------------ 3. what is not there


def test_a_bridge_type_with_an_unknown_string_is_left_out(meta):
    broken = _edit("bridge_types", "bottom", to_string_kind="nowhere")(meta)
    assert [b.name for b in broken.frame.bridges] == ["top", "vertical"]
    assert broken.frame.rules and [r.name for r in broken.frame.rules] == ["top"]


def test_the_frame_is_built_once_and_not_shared_across_providers(meta):
    assert meta.frame is meta.frame
    other = dataclasses.replace(meta)
    assert other.frame is not meta.frame


def test_a_configuration_with_no_frame_rows_has_an_empty_frame(meta):
    bare = dataclasses.replace(meta, string_kinds=(), bridge_types=(), rule_types=())
    f = bare.frame
    assert f.bridges == () and f.rules == () and f.theme_types == ()
    assert f.facts("initial") == (False, False, False)


def test_a_provider_hashes_the_frame_rows(meta):
    from server.engine.hashing import config_hash

    changed = _edit("bridge_types", "top", theme_type="vertical_bridge")(meta)
    assert config_hash(changed) != config_hash(meta)
    first = dataclasses.replace(meta, initial_description_rules=meta.initial_description_rules[1:])
    assert config_hash(first) != config_hash(meta)
