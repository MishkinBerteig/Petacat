"""A link length can be a fraction, a whole one stays whole, and every stored number is finite.

The change API's ``add_link``, ``adjust`` and the generic insert and update accept a non-whole link length;
a whole value is stored and printed as an ``int`` (so the Metacat Standard Configuration's JSON is what it
always was); ``nan``, ``inf``, ``1e999`` and ``10**400`` are refused on every route, and under ``skip`` only
that op is dropped.  ``slipnet_node_defs.noticings`` is a whole number with no range.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.models.metadata import SlipnetLinkDef, WholeAsInt, whole_as_int
from server.services import config_document as cd
from server.services.change_resolve import ChangeRefused, resolve

SEED_DATA = Path(__file__).resolve().parents[2] / "seed_data"
LINK = {"from_node": "plato-a", "to_node": "plato-c", "link_type": "lateral", "label_node": ""}
NOT_FINITE = [float("nan"), float("inf"), float("-inf"), 1e999, 10 ** 400, -(10 ** 400)]


@pytest.fixture(scope="module")
def standard():
    return cd.document_from_standard_files(str(SEED_DATA))


def length_of(doc, resolved=None, key=("plato-a", "plato-c", "lateral", "")):
    return doc.tables["slipnet_link_defs"][key]["link_length"]


def run(doc, ops, **batch):
    resolved, report = resolve(doc, {"ops": ops, **batch})
    return cd.apply_resolved(doc, resolved), resolved, report


def add(length, **more):
    return {"op": "add_link", "from": "plato-a", "to": "plato-c", "type": "lateral", "fixed": True, "length": length, **more}


def adjust(by, field="link_length", table="slipnet_link_defs", key=None):
    return {"op": "adjust", "table": table, "key": dict(LINK if key is None else key), "field": field, "by": by}


# -- the column type -----------------------------------------------------------------------------------


def test_the_column_reads_a_whole_value_back_as_an_int_and_a_fraction_as_a_float():
    assert isinstance(SlipnetLinkDef.__table__.c.link_length.type, WholeAsInt)
    t = WholeAsInt()
    assert type(t.process_result_value(90.0, None)) is int and t.process_result_value(90.0, None) == 90
    assert t.process_result_value(89.875, None) == 89.875 and type(t.process_result_value(89.875, None)) is float
    assert t.process_result_value(None, None) is None and t.process_result_value(-0.0, None) == 0
    assert str(t.process_result_value(0.0, None)) == "0"
    for odd in (float("inf"), float("-inf")):
        assert whole_as_int(odd) == odd  # never reached with a stored value, and never an OverflowError
    assert whole_as_int(float("nan")) != whole_as_int(float("nan"))


# -- the change API ------------------------------------------------------------------------------------


def test_add_link_and_adjust_take_a_fraction():
    doc, resolved, _ = run(cd.document_from_standard_files(str(SEED_DATA)), [add(89.875)])
    assert length_of(doc) == 89.875 and resolved[-1]["row"]["link_length"] == 89.875
    doc, _, _ = run(doc, [adjust(-0.125), adjust(-0.25)])
    assert length_of(doc) == 89.5
    # the generic ops take it as well
    doc, _, _ = run(doc, [{"op": "update", "table": "slipnet_link_defs", "key": LINK, "fields": {"link_length": 12.5}}])
    assert length_of(doc) == 12.5
    ins = {"op": "insert", "table": "slipnet_link_defs", "row": {
        "from_node": "plato-a", "to_node": "plato-d", "link_type": "lateral", "label_node": None,
        "link_length": 0.5, "fixed_length": True}}
    doc, _, _ = run(doc, [ins])
    assert length_of(doc, key=("plato-a", "plato-d", "lateral", "")) == 0.5


def test_a_whole_value_is_stored_as_an_int_however_it_arrives():
    doc, _, _ = run(cd.document_from_standard_files(str(SEED_DATA)), [add(90.0)])
    assert length_of(doc) == 90 and type(length_of(doc)) is int
    # a fraction that adds up to a whole number is whole again, and prints as one
    doc, _, _ = run(doc, [adjust(0.125), adjust(-0.125)])
    assert type(length_of(doc)) is int and length_of(doc) == 90
    doc, _, _ = run(doc, [adjust(-0.125) for _ in range(80)])
    assert length_of(doc) == 80 and type(length_of(doc)) is int
    assert json.dumps(doc.tables["slipnet_link_defs"][("plato-a", "plato-c", "lateral", "")]["link_length"]) == "80"


def test_adjust_sums_exactly_when_the_step_is_a_power_of_two():
    doc, _, _ = run(cd.document_from_standard_files(str(SEED_DATA)), [add(90)])
    for _ in range(280):
        doc, _, _ = run(doc, [adjust(-0.125)])
    assert length_of(doc) == 55 and type(length_of(doc)) is int
    one, _, _ = run(cd.document_from_standard_files(str(SEED_DATA)), [add(90), adjust(-0.125 * 280)])
    assert length_of(one) == 55


def test_a_whole_value_stays_printed_as_today_under_the_standard(standard):
    """Every link length the Metacat Standard Configuration holds is the ``int`` (or ``None``) the seed file
    has, and the JSON the rows print is the seed file's, character for character."""
    seed = json.loads((SEED_DATA / "slipnet_links.json").read_text())
    rows = list(standard.tables["slipnet_link_defs"].values())
    assert len(rows) == len(seed)
    for row, want in zip(rows, seed):
        got = row["link_length"]
        assert got == want["link_length"] and type(got) is type(want["link_length"]), row
        assert json.dumps(got) == json.dumps(want["link_length"])
    # and the provider the engine reads has the same ints
    meta = cd.provider(standard)
    assert [l.link_length for l in meta.slipnet_link_specs] == [w["link_length"] for w in seed]
    assert {type(l.link_length) for l in meta.slipnet_link_specs} <= {int, type(None)}


def test_the_hash_tells_a_fraction_from_a_whole_value_and_ignores_how_a_whole_one_arrived(standard):
    by_float, _, _ = run(cd.document_from_standard_files(str(SEED_DATA)), [add(90.0)])
    by_int, _, _ = run(cd.document_from_standard_files(str(SEED_DATA)), [add(90)])
    fraction, _, _ = run(cd.document_from_standard_files(str(SEED_DATA)), [add(89.875)])
    assert cd.config_hash(by_float) == cd.config_hash(by_int) != cd.config_hash(fraction)


# -- every stored number is finite -----------------------------------------------------------------------


@pytest.mark.parametrize("bad", NOT_FINITE, ids=repr)
def test_a_link_length_that_is_not_finite_is_refused_on_every_route(standard, bad):
    refused = [
        [add(bad)],
        [{"op": "insert", "table": "slipnet_link_defs", "row": {
            "from_node": "plato-a", "to_node": "plato-d", "link_type": "lateral", "label_node": None,
            "link_length": bad, "fixed_length": True}}],
        [add(10), {"op": "update", "table": "slipnet_link_defs", "key": LINK, "fields": {"link_length": bad}}],
        [add(10), adjust(bad)],
        [add(10), {"op": "add_link", "from_node": "plato-a", "to_node": "plato-e", "link_type": "lateral",
                   "link_length": bad, "fixed_length": True}],
    ]
    for ops in refused:
        with pytest.raises(ChangeRefused) as caught:
            resolve(standard, {"ops": ops})
        assert "finite" in str(caught.value.problems[0].message)


def test_under_skip_only_the_op_with_a_non_finite_number_is_dropped(standard):
    ops = [add(40), add(float("nan"), to="plato-d"), adjust(float("inf")), adjust(10 ** 400), adjust(-5),
           {"op": "add_link", "from": "plato-a", "to": "plato-e", "type": "lateral", "fixed": True, "length": 1e999},
           {"op": "add_link", "from": "plato-a", "to": "plato-f", "type": "lateral", "fixed": True, "length": 7.5}]
    doc, _, report = run(standard, ops, on_op_failure="skip")
    assert sorted(s["op"] for s in report["skipped"]) == [1, 2, 3, 5]
    assert length_of(doc) == 35
    assert length_of(doc, key=("plato-a", "plato-f", "lateral", "")) == 7.5
    assert ("plato-a", "plato-d", "lateral", "") not in doc.tables["slipnet_link_defs"]


def test_a_float_parameter_that_is_not_finite_is_refused_too(standard):
    for bad in ("nan", "inf", "-inf", "1e999"):
        with pytest.raises(ChangeRefused):
            resolve(standard, {"ops": [{"op": "set_param", "name": "spreading_threshold", "to": bad, "value_type": "float"}]})
    with pytest.raises(ChangeRefused):
        resolve(standard, {"ops": [{"op": "adjust_param", "name": "spreading_threshold", "by": float("inf")}]})
    for by in (float("inf"), float("nan"), 10 ** 400):  # a rational coefficient too
        with pytest.raises(ChangeRefused):
            resolve(standard, {"ops": [{"op": "adjust_coefficient", "name": "enclosed_group_importance_factor", "by": by}]})


# -- noticings -----------------------------------------------------------------------------------------


def node_op(by, name="plato-a"):
    return {"op": "adjust", "table": "slipnet_node_defs", "key": {"name": name}, "field": "noticings", "by": by}


def test_noticings_is_a_whole_number_on_every_node_defaulting_to_0_with_no_range(standard):
    nodes = standard.tables["slipnet_node_defs"]
    assert {r["noticings"] for r in nodes.values()} == {0}
    doc, _, _ = run(standard, [node_op(3), node_op(-10)])
    assert doc.tables["slipnet_node_defs"][("plato-a",)]["noticings"] == -7  # no range
    doc, _, _ = run(standard, [node_op(10 ** 12)])
    assert doc.tables["slipnet_node_defs"][("plato-a",)]["noticings"] == 10 ** 12
    doc, _, _ = run(standard, [node_op(2.0)])  # a whole float adds as a whole number
    assert doc.tables["slipnet_node_defs"][("plato-a",)]["noticings"] == 2
    doc, _, _ = run(standard, [{"op": "update", "table": "slipnet_node_defs", "key": {"name": "plato-a"},
                                "fields": {"noticings": 5}}])
    assert doc.tables["slipnet_node_defs"][("plato-a",)]["noticings"] == 5
    doc, _, _ = run(standard, [{"op": "add_node", "name": "plato-new", "fields": {"short_name": "n", "conceptual_depth": 10}}])
    assert doc.tables["slipnet_node_defs"][("plato-new",)]["noticings"] == 0


@pytest.mark.parametrize("bad", [0.5, float("nan"), float("inf"), 1e999, 10 ** 400], ids=repr)
def test_noticings_refuses_a_value_that_is_not_whole_and_one_that_is_not_finite(standard, bad):
    with pytest.raises(ChangeRefused):
        resolve(standard, {"ops": [node_op(bad)]})
    with pytest.raises(ChangeRefused):
        resolve(standard, {"ops": [{"op": "update", "table": "slipnet_node_defs", "key": {"name": "plato-a"},
                                    "fields": {"noticings": bad}}]})


def test_under_skip_a_refused_noticings_op_is_dropped_alone(standard):
    doc, _, report = run(standard, [node_op(1), node_op(0.5), node_op(float("inf")), node_op(2)], on_op_failure="skip")
    assert sorted(s["op"] for s in report["skipped"]) == [1, 2]
    assert doc.tables["slipnet_node_defs"][("plato-a",)]["noticings"] == 3


def test_the_provider_carries_the_count_to_the_engine(standard):
    doc, _, _ = run(standard, [node_op(4)])
    assert cd.provider(doc).slipnet_node_specs["plato-a"].noticings == 4
    assert cd.provider(standard).slipnet_node_specs["plato-a"].noticings == 0


def test_a_refused_non_finite_number_is_journaled_as_the_text_it_was():
    """``proposed`` records what was asked for; a ``json`` column cannot hold the bare token ``NaN``, so a batch
    that carried one (and was applied under ``skip`` without it) is still journaled."""
    from server.services.journal import _jsonable

    got = _jsonable([{"op": "adjust", "by": float("nan"), "key": {"a": [float("inf"), -float("inf"), 1.5, 10 ** 400]}}])
    assert got == [{"op": "adjust", "by": "NaN", "key": {"a": ["Infinity", "-Infinity", 1.5, 10 ** 400]}}]
    json.dumps(got, allow_nan=False)  # valid JSON now
