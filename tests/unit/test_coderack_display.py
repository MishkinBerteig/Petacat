"""The coderack window's data: ``coderack-graphics.ss`` and ``coderack.ss:283-368``.

A codelet type's selection probability is the sum, over its codelets, of their bin's
rounded urgency value at the current temperature, over the same sum for the whole rack.
"""

import pytest

from server.engine.coderack import (
    coderack_display,
    type_selection_probabilities,
    urgency_value_table,
)


def test_a_types_probability_is_its_share_of_the_urgency_weighted_total():
    # Two bins; the row says a codelet in bin 0 weighs 1 and one in bin 1 weighs 3.
    per_bin = [{"scout": 4, "evaluator": 2}, {"evaluator": 1, "builder": 1}]
    p = type_selection_probabilities(per_bin, [1, 3, 99])
    # total = 6*1 + 2*3 = 12
    assert p == pytest.approx({"scout": 4 / 12, "evaluator": (2 + 3) / 12, "builder": 3 / 12})
    assert sum(p.values()) == pytest.approx(1.0)


def test_an_empty_rack_has_no_probabilities():
    assert type_selection_probabilities([{}, {}], [1, 2]) == {}


def test_temperature_changes_the_weighting_of_the_bins():
    table = urgency_value_table(7, 10, 15)
    per_bin = [{"low": 1}, {}, {}, {}, {}, {}, {"high": 1}]
    hot = type_selection_probabilities(per_bin, table.row(100))
    cold = type_selection_probabilities(per_bin, table.row(0))
    assert cold["high"] > hot["high"]
    assert cold["low"] < hot["low"]


class _Bin:
    def __init__(self, bin_number, types):
        self.bin_number = bin_number
        self.codelets = [type("C", (), {"codelet_type": t}) for t in types]


class _Meta:
    codelet_specs = {"a": 1, "b": 2, "never-posted": 3}


class _Rack:
    meta = _Meta()
    urgency_table = urgency_value_table(7, 10, 15)
    total_count = 3
    clamped_urgencies = {"b": 91}
    bins = [_Bin(0, ["a", "a"])] + [_Bin(i, []) for i in range(1, 6)] + [_Bin(6, ["b"])]

    def get_codelet_type_counts(self):
        return {"a": 2, "b": 1}


def test_the_display_carries_counts_probabilities_last_type_and_every_slot():
    d = coderack_display(_Rack(), 100, "b")
    assert d["total_count"] == 3
    assert d["type_counts"] == {"a": 2, "b": 1}
    assert d["last_codelet_type"] == "b"
    assert d["codelet_types"] == ["a", "b", "never-posted"]
    assert d["clamped_urgencies"] == {"b": 91}
    row = _Rack.urgency_table.row(100)
    total = 2 * row[0] + row[6]
    assert d["type_probabilities"]["a"] == pytest.approx(2 * row[0] / total)
    assert "never-posted" not in d["type_probabilities"]
