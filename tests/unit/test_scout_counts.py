"""Unit tests for the scout-count aggregates (``workspace.ss:678-716``).

These are the four free functions that decide how many bond, group and bridge
scouts enter the coderack on each update cycle: ``rough_num_of_objects`` and the
three object predicates it counts over.  All four are pure — they read an
object's bonds, enclosing group, string role and bridges, and nothing else — so
a hand-rolled fake object isolates them completely.  The only randomness is the
``~`` blur, driven through a real :class:`RNG` at fixed seeds.
"""

import pytest

from server.engine.rng import RNG
from server.engine.workspace import (
    rough_num_of_objects,
    ungrouped,
    unmapped,
    unrelated,
)

from tests.unit._fakes import FakeString


class _FakeObj:
    """The surface the three predicates read, and nothing more."""

    def __init__(
        self,
        *,
        string=None,
        spans=False,
        enclosing_group=None,
        bonds=0,
        leftmost=False,
        rightmost=False,
        horizontal_bridge=None,
        vertical_bridge=None,
    ):
        self.string = string if string is not None else FakeString()
        self._spans = spans
        self.enclosing_group = enclosing_group
        self._bonds = [object() for _ in range(bonds)]
        self._leftmost = leftmost
        self._rightmost = rightmost
        self.horizontal_bridge = horizontal_bridge
        self.vertical_bridge = vertical_bridge

    def spans_whole_string(self):
        return self._spans

    def get_incident_bonds(self):
        return self._bonds

    def leftmost_in_string(self):
        return self._leftmost

    def rightmost_in_string(self):
        return self._rightmost

    def mapped(self, bridge_type):
        if bridge_type == "horizontal":
            return self.horizontal_bridge is not None
        if bridge_type == "vertical":
            return self.vertical_bridge is not None
        return self.horizontal_bridge is not None and self.vertical_bridge is not None


# --- ungrouped? (workspace.ss:700-704) --------------------------------------

def test_ungrouped_true_for_a_bare_object():
    assert ungrouped(_FakeObj()) is True


def test_ungrouped_false_inside_a_group():
    assert ungrouped(_FakeObj(enclosing_group=object())) is False


def test_ungrouped_false_for_a_whole_string_object():
    """Nothing is left to group a spanning group into."""
    assert ungrouped(_FakeObj(spans=True)) is False


# --- unrelated? (workspace.ss:692-698) --------------------------------------

def test_unrelated_edge_object_needs_only_one_bond():
    """An edge object has one side to bond on, so one bond satisfies it."""
    assert unrelated(_FakeObj(leftmost=True, bonds=0)) is True
    assert unrelated(_FakeObj(leftmost=True, bonds=1)) is False
    assert unrelated(_FakeObj(rightmost=True, bonds=1)) is False


def test_unrelated_interior_object_wants_two_bonds():
    """The half-bonded interior letter the ratio reading used to miss."""
    assert unrelated(_FakeObj(bonds=0)) is True
    assert unrelated(_FakeObj(bonds=1)) is True
    assert unrelated(_FakeObj(bonds=2)) is False


def test_unrelated_false_once_grouped_however_few_bonds():
    assert unrelated(_FakeObj(bonds=0, enclosing_group=object())) is False


# --- unmapped? (workspace.ss:708-716) ---------------------------------------

def _obj(string_type, *, h=None, v=None):
    """``unmapped`` takes justify mode as an argument, as the Scheme reads the
    global ``%justify-mode%``; the object only supplies its string *role*."""
    return _FakeObj(
        string=FakeString(string_type=string_type),
        horizontal_bridge=h,
        vertical_bridge=v,
    )


def test_initial_string_object_needs_both_bridges():
    assert unmapped(_obj("initial")) is True
    assert unmapped(_obj("initial", h=object())) is True
    assert unmapped(_obj("initial", v=object())) is True
    assert unmapped(_obj("initial", h=object(), v=object())) is False


def test_modified_and_answer_objects_need_only_a_horizontal_bridge():
    assert unmapped(_obj("modified", v=object())) is True
    assert unmapped(_obj("modified", h=object())) is False
    assert unmapped(_obj("answer", h=object())) is False


def test_target_object_needs_a_vertical_bridge_when_not_justifying():
    assert unmapped(_obj("target"), justify_mode=False) is True
    assert unmapped(_obj("target", v=object()), justify_mode=False) is False


def test_target_object_needs_both_bridges_when_justifying():
    """Justifying, the target string also maps horizontally onto the answer."""
    assert unmapped(_obj("target", v=object()), justify_mode=True) is True
    assert unmapped(_obj("target", h=object(), v=object()), justify_mode=True) is False


# --- rough-num-of-objects and the ~ blur (workspace.ss:678-683) -------------

def test_zero_objects_is_always_few():
    """``(~ 2)`` stays strictly above 0, so a count of 0 is below it every time."""
    rng = RNG(7)
    assert all(rough_num_of_objects(0, rng) == "few" for _ in range(200))


def test_a_large_count_is_always_many():
    """``(~ 4)`` is at best 4 + 2 = 6, so 7 clears both thresholds every time."""
    rng = RNG(7)
    assert all(rough_num_of_objects(7, rng) == "many" for _ in range(200))


@pytest.mark.parametrize("count", [1, 2, 3, 4, 5])
def test_the_thresholds_are_blurred_not_fixed(count):
    """Every count between the two thresholds is genuinely uncertain.

    This is the whole point of ``~``: a workspace sitting on a boundary cycle
    after cycle does not post the same scout mix every time.  Petacat's fixed
    0.2/0.5 ratio cutoffs were deterministic, so a stable workspace posted an
    identical number of bond scouts every cycle for the length of the run.
    """
    rng = RNG(1234)
    seen = {rough_num_of_objects(count, rng) for _ in range(400)}
    assert len(seen) > 1, f"count {count} always gave {seen}"


def test_blur_stays_within_the_reachable_band():
    """``~2`` lands in ``(0, 4)`` and ``~4`` in ``{2, …, 6}``.

    The two thresholds blur differently, and that asymmetry is the reference's,
    not an accident of this port: ``(sqrt 4)`` is exact so ``(~ 4)`` draws an
    integer delta, while ``(round (sqrt 2))`` is the flonum ``1.0`` so ``(~ 2)``
    draws a continuous one (``utilities.ss:426-429``, and see
    ``RNG.perturb``).  A count of 3 is therefore ``few`` sometimes — it needs
    only ``delta > 1`` — where an integer ``~2`` could never reach past 3.
    """
    rng = RNG(99)
    # 4 clears every draw of ~2 (strictly below 4), so it is never 'few'.
    assert all(rough_num_of_objects(4, rng) != "few" for _ in range(400))
    # 3 sits inside the continuous band, so it is 'few' some of the time.
    assert any(rough_num_of_objects(3, rng) == "few" for _ in range(400))
    # 1 is below every draw of ~4 (min 2), so it is never 'many'.
    assert all(rough_num_of_objects(1, rng) != "many" for _ in range(400))
