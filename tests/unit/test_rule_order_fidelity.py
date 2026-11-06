"""Two orders in rule application that Chez Scheme decides (stage W, ``DISCREPANCIES5.md``).

* ``check-for-conflicts`` (``rules.ss:1321-1338``) walks the pairs with ``pairwise-map``
  (``utilities.ss:758-768``), so the conflict reported is the first one in Chez's evaluation
  order, not the first by index (``wxyz -> xxyz; fgzzz`` seed 3).
* ``apply-transforms`` (``rules.ss:1341-1350``) sorts with ``apply-before?`` (``rules.ss:1395-1403``),
  which is not a strict order, so the result is what Chez's merge sort gives (``zyx -> xyy; z`` seed 1).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.numeric_matrix

from server.engine import rules as R


def test_the_conflict_found_first_is_the_first_in_chezs_pairwise_map_order(monkeypatch) -> None:
    seen: list[tuple[int, int]] = []

    class Fake:
        def __init__(self, obj, scope, dim, a, b, descriptor) -> None:
            self.reference_object, self.dimension = obj, dim

        def conflicts(self, other) -> bool:
            seen.append((self.reference_object, other.reference_object))
            return False

    monkeypatch.setattr(R, "IntrinsicChangeDescription", Fake)
    R._check_for_conflicts([(i, (f"d{i}", None)) for i in range(4)])
    # the recursive call first (pairs of the later items), then the map in Chez's order
    assert seen == [(2, 3), (1, 2), (1, 3), (0, 3), (0, 1), (0, 2)]


def test_a_conflict_is_reported_for_the_first_pair_in_that_order(monkeypatch) -> None:
    class Fake:
        def __init__(self, obj, scope, dim, a, b, descriptor) -> None:
            self.reference_object, self.dimension = obj, dim

        def conflicts(self, other) -> bool:
            return {self.reference_object, other.reference_object} in ({0, 1}, {2, 3})

    monkeypatch.setattr(R, "IntrinsicChangeDescription", Fake)
    monkeypatch.setattr(R, "_ascii_name", str)
    with pytest.raises(R.ImageFailure) as raised:
        R._check_for_conflicts([(i, (f"d{i}", None)) for i in range(4)])
    assert raised.value.objects == [2, 3]  # by index, (0, 1) would have been found first


def test_apply_transforms_sorts_with_chezs_merge_sort_and_scheme_apply_before(monkeypatch) -> None:
    monkeypatch.setattr(R, "_holds", lambda node, const: node == const)
    monkeypatch.setattr(R, "_APPLY_FIRST_DIMENSION", "GC")
    monkeypatch.setattr(R, "_APPLY_BY_LENGTH_DIMENSION", "LEN")
    monkeypatch.setattr(R, "_OBJECT_LETTER", "letter")
    monkeypatch.setattr(R, "change_length_first", lambda change, length, slipnet: change == "first")
    applied: list[tuple] = []
    monkeypatch.setattr(R, "_transform_image", lambda image, dim, desc, slipnet, transforms: applied.append((dim, desc)))

    class Image:
        def get_length(self):
            return 3

    transforms = [("GC", "opp"), ("LEN", "first"), ("LEN", "notfirst")]
    R._apply_transforms(transforms, Image(), None)
    # a numeric key puts the group-category change first; Chez's merge sort with apply-before? does not
    assert applied == [("LEN", "first"), ("GC", "opp"), ("LEN", "notfirst")]


def test_building_a_bond_into_a_held_slot_overwrites_the_pointers_as_build_bond_does() -> None:
    """``build-bond`` (bonds.ss:410-422) overwrites the left object's right-bond and the right object's
    left-bond without a check; the group builder's consolidation relies on it (``pqrs -> ppqqrrss; ttt``
    seed 1: a stale bond from a group to a letter now inside the next group held the slot).  The displaced bond
    stays in the string's list.  Only ``displacing=True`` may do it."""
    from server.engine.bonds import Bond
    from server.engine.memory import EpisodicMemory
    from server.engine.numeric.backend import use_backend
    from server.engine.rng import RNG
    from server.engine.runner import EngineRunner
    from tests.support import golden_baseline as gb

    runner = EngineRunner(gb.load_meta())
    with use_backend("off"):
        runner.init_mcat("abc", "abd", "xyz", seed=1, memory=EpisodicMemory(), rng=RNG(1))
    string = runner.ctx.workspace.initial_string
    left, right = string.objects[0], string.objects[1]
    nodes = list(runner.ctx.slipnet.nodes.values())[:3]
    first = Bond(left, right, nodes[0], nodes[1], nodes[2], nodes[2], None)
    second = Bond(left, right, nodes[1], nodes[1], nodes[2], nodes[2], None)
    string.add_bond(first)
    with pytest.raises(AssertionError):
        string.add_bond(second)
    string.add_bond(second, displacing=True)
    assert left.right_bond is second and right.left_bond is second
    assert first in string.bonds and second in string.bonds
