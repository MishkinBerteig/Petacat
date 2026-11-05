"""C6: the journal's pure part: replaying resolved ops and undoing them from before-images."""

from __future__ import annotations

import copy

import pytest

from server.services import journal_views as jv


def _entry(revision, ops, before):
    return {"revision": revision, "resolved": ops, "before": before}


def _ins(name, depth=1):
    return {"op": "insert", "table": "urgency_levels", "key": {"name": name},
            "row": {"name": name, "value": depth, "sort_order": depth}}


def test_replay_applies_inserts_updates_rekeys_and_deletes_in_order():
    state = jv.empty_state()
    jv.apply_ops(state, [
        _ins("low", 1), _ins("high", 9),
        {"op": "update", "table": "urgency_levels", "key": {"name": "low"}, "set": {"value": 2}},
        {"op": "update", "table": "urgency_levels", "key": {"name": "high"}, "set": {"name": "top"}},
        {"op": "delete", "table": "urgency_levels", "key": {"name": "low"}},
    ])
    assert state["urgency_levels"] == {("top",): {"name": "top", "value": 9, "sort_order": 9}}


def test_replay_refuses_ops_that_do_not_apply():
    state = jv.empty_state()
    jv.apply_ops(state, [_ins("low")])
    for bad in (
        _ins("low"),
        {"op": "update", "table": "urgency_levels", "key": {"name": "nope"}, "set": {"value": 1}},
        {"op": "delete", "table": "urgency_levels", "key": {"name": "nope"}},
    ):
        with pytest.raises(jv.ReplayError):
            jv.apply_ops(copy.deepcopy(state), [bad])


def test_reconstruction_by_before_images_inverts_replay():
    low = {"name": "low", "value": 1, "sort_order": 1}
    entries = [
        _entry(1, [_ins("low", 1)], [None]),
        _entry(2, [{"op": "update", "table": "urgency_levels", "key": {"name": "low"},
                    "set": {"name": "lo", "value": 5}}], [low]),
        _entry(3, [{"op": "delete", "table": "urgency_levels", "key": {"name": "lo"}}],
               [{"name": "lo", "value": 5, "sort_order": 1}]),
    ]
    current = jv.replay(entries)
    assert current["urgency_levels"] == {}
    for revision in range(4):
        assert jv.reconstruct(current, entries, revision) == jv.replay(entries, upto=revision)


def test_inverse_ops_undo_a_batch():
    low = {"name": "low", "value": 1, "sort_order": 1}
    entry = _entry(
        2,
        [{"op": "update", "table": "urgency_levels", "key": {"name": "low"}, "set": {"value": 5}},
         {"op": "delete", "table": "urgency_levels", "key": {"name": "high"}},
         _ins("mid", 3)],
        [low, {"name": "high", "value": 9, "sort_order": 9}, None],
    )
    start = jv.empty_state()
    jv.apply_ops(start, [_ins("low", 1), _ins("high", 9)])
    after = copy.deepcopy(start)
    jv.apply_ops(after, entry["resolved"])
    assert after != start
    jv.apply_ops(after, jv.inverse_ops([entry]))
    assert after == start


def test_an_update_and_its_undo_keep_the_rows_place_in_the_table():
    """A table that declares no order is read in insertion order and the hash covers it, so
    editing a row and undoing the edit must not move it to the end (round 2, stage R)."""
    a, b, c = (("a",), {"name": "a", "value": 1, "sort_order": 1}), (
        ("b",), {"name": "b", "value": 2, "sort_order": 2}), (
        ("c",), {"name": "c", "value": 3, "sort_order": 3})
    state = {"urgency_levels": dict([a, b, c])}
    update = {"op": "update", "table": "urgency_levels", "key": {"name": "a"}, "set": {"value": 9}}
    rename = {"op": "update", "table": "urgency_levels", "key": {"name": "a"}, "set": {"name": "z"}}
    before = [dict(a[1])]
    for op in (update, rename):
        edited = copy.deepcopy(state)
        jv.apply_ops(edited, [op])
        assert [k for k in edited["urgency_levels"]][1:] == [("b",), ("c",)]
        assert len(edited["urgency_levels"]) == 3
        jv.unapply_entry(edited, [op], before)
        assert list(edited["urgency_levels"]) == list(state["urgency_levels"])
        assert edited == state
