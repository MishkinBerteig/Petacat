"""``scale``: the change API's multiplying op, the partner of the additive ``adjust``.

``{'op': 'scale', 'table', 'key', 'field', 'factor'}`` is addressed as ``adjust`` is and multiplies the field's
current value by ``factor``.  Factors commute, so the scales of runs that started under one configuration compose in
any order (an ``adjust`` of a value worked out from the length a run saw would overshoot).  It refuses a field that
is not a number, a ``factor`` that is not a finite number and a result that is not finite; on a whole-number column
it refuses a result that is not whole; a whole result in a ``WholeAsInt`` column is stored as an ``int``.  No other
range is imposed.  It is journaled by before-image (undo, restore and ``config_at`` work), and under ``skip`` each
refused op is dropped alone.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from server.services import config_document as cd
from server.services import journal, journal_views
from server.services.session_episode import EpisodeLog
from server.services.change_resolve import ChangeRefused, resolve
from server.services.change_resolve.checks import _ARGS
from server.services.change_resolve.spec import CONVENIENCE_OPS, schema

SEED_DATA = Path(__file__).resolve().parents[2] / "seed_data"
LINK = {"from_node": "plato-a", "to_node": "plato-c", "link_type": "lateral", "label_node": ""}
NODE = {"name": "plato-a"}
NOT_FINITE = [float("nan"), float("inf"), float("-inf"), 1e999, 10 ** 400, -(10 ** 400)]


@pytest.fixture(scope="module")
def standard():
    return cd.document_from_standard_files(str(SEED_DATA))


def scale(factor, table="slipnet_link_defs", key=None, field="link_length"):
    return {"op": "scale", "table": table, "key": dict(LINK if key is None else key), "field": field,
            "factor": factor}


def add(length):
    return {"op": "add_link", "from": "plato-a", "to": "plato-c", "type": "lateral", "fixed": True, "length": length}


def run(doc, ops, **batch):
    resolved, report = resolve(doc, {"ops": ops, **batch})
    return cd.apply_resolved(doc, resolved), resolved, report


def length_of(doc):
    return doc.tables["slipnet_link_defs"][("plato-a", "plato-c", "lateral", "")]["link_length"]


def refusal(doc, *ops):
    with pytest.raises(ChangeRefused) as caught:
        resolve(doc, {"ops": list(ops)})
    return caught.value


# -- the shape ---------------------------------------------------------------------------------------------


def test_scale_is_in_every_list_of_the_change_api_ops():
    assert "scale" in CONVENIENCE_OPS and "scale" in schema()["ops"]["convenience"]
    assert _ARGS["scale"] == {"table": "s*", "key": "o*", "field": "s*", "factor": "n*"}


@pytest.mark.parametrize("bad", [{"table": 1}, {"key": "x"}, {"field": None}, {"factor": "2"}, {"factor": True},
                                 {"factor": None}], ids=repr)
def test_the_shape_checks(standard, bad):
    op = {**scale(2), **bad}
    assert refusal(standard, add(10), op).kind == "malformed"


@pytest.mark.parametrize("missing", ["table", "key", "field", "factor"])
def test_every_argument_is_required(standard, missing):
    op = scale(2)
    del op[missing]
    assert refusal(standard, add(10), op).kind == "malformed"


def test_an_unknown_argument_is_refused(standard):
    assert refusal(standard, add(10), {**scale(2), "by": 1}).kind == "malformed"


# -- what it does -------------------------------------------------------------------------------------------


def test_it_multiplies_the_current_value_and_the_factors_commute(standard):
    doc, resolved, _ = run(standard, [add(80), scale(0.5), scale(0.25)])
    assert length_of(doc) == 10
    both, _, _ = run(standard, [add(80), scale(0.25), scale(0.5)])
    assert length_of(both) == 10
    assert resolved[-1]["op"] == "update"


def test_a_whole_result_in_a_link_length_is_stored_as_an_int_and_a_fraction_stays_a_fraction(standard):
    doc, _, _ = run(standard, [add(45), scale(2.0)])
    assert length_of(doc) == 90 and type(length_of(doc)) is int
    doc, _, _ = run(standard, [add(45), scale(0.5)])
    assert length_of(doc) == 22.5 and type(length_of(doc)) is float
    ratio = 1 - 0.0625 / 90
    doc, _, _ = run(standard, [add(90 / ratio), scale(ratio)])
    assert length_of(doc) == 90 and type(length_of(doc)) is int


def test_there_is_no_range_beyond_finiteness(standard):
    doc, _, _ = run(standard, [add(40), scale(-3)])
    assert length_of(doc) == -120
    doc, _, _ = run(standard, [add(40), scale(0)])
    assert length_of(doc) == 0
    doc, _, _ = run(standard, [add(40), scale(1e-300), scale(1e-300)])
    assert length_of(doc) == 0.0 or 0 <= length_of(doc) < 1e-290


def test_an_int_column_takes_a_whole_result_and_refuses_a_fraction(standard):
    count = {"table": "slipnet_node_defs", "key": NODE, "field": "noticings"}
    doc, _, _ = run(standard, [{"op": "adjust", **{k: v for k, v in count.items()}, "by": 6}])
    doc2, _, _ = run(doc, [scale(2, **count)])
    assert doc2.tables["slipnet_node_defs"][("plato-a",)]["noticings"] == 12
    assert type(doc2.tables["slipnet_node_defs"][("plato-a",)]["noticings"]) is int
    doc3, _, _ = run(doc, [scale(0.5, **count)])
    assert doc3.tables["slipnet_node_defs"][("plato-a",)]["noticings"] == 3
    doc4, _, _ = run(doc, [scale(2.0, **count)])
    assert doc4.tables["slipnet_node_defs"][("plato-a",)]["noticings"] == 12
    assert "integer" in str(refusal(doc, scale(0.25, **count)).problems[0].message)


def test_it_scales_a_parameter_value_and_a_coefficient_as_adjust_does(standard):
    doc, _, _ = run(standard, [scale(2, "engine_params", {"name": "update_cycle_length"}, "value")])
    assert doc.tables["engine_params"][("update_cycle_length",)]["value"] == "30"
    assert refusal(standard, scale(0.5, "engine_params", {"name": "update_cycle_length"}, "value")).kind == "malformed"
    assert refusal(standard, scale(2, "engine_params", {"name": "top_down_slipnodes"}, "value")).kind == "malformed"


# -- refusals -----------------------------------------------------------------------------------------------


def test_it_refuses_a_field_that_is_not_a_number(standard):
    assert refusal(standard, scale(2, "slipnet_node_defs", NODE, "short_name")).kind == "malformed"
    assert refusal(standard, add(10), scale(2, field="fixed_length")).kind == "malformed"
    assert refusal(standard, scale(2, "slipnet_node_defs", NODE, "no_such_field")).kind == "malformed"
    assert refusal(standard, scale(2, "no_such_table", NODE, "x")).kind == "malformed"


def test_it_refuses_a_row_that_is_not_there(standard):
    assert refusal(standard, scale(2, key={**LINK, "to_node": "plato-z"})).kind in ("unknown_reference", "malformed")


@pytest.mark.parametrize("bad", NOT_FINITE, ids=repr)
def test_it_refuses_a_factor_that_is_not_finite(standard, bad):
    problem = refusal(standard, add(10), scale(bad)).problems[0]
    assert "finite" in str(problem.message)
    assert "finite" in str(refusal(standard, scale(bad, "engine_params", {"name": "update_cycle_length"},
                                                   "value")).problems[0].message)


def test_it_refuses_a_result_that_is_not_finite(standard):
    problem = refusal(standard, add(1e300), scale(1e300)).problems[0]
    assert "finite" in str(problem.message) or "range" in str(problem.message)
    assert refusal(standard, add(10 ** 300), scale(10 ** 300)).kind == "malformed"


def test_under_skip_each_refused_scale_is_dropped_alone(standard):
    ops = [add(80), scale(float("nan")), scale(0.5), scale(float("inf")), scale(1e999), scale(0.5),
           scale(2, "slipnet_node_defs", NODE, "short_name"), scale(1e300), scale(1e300), scale(10 ** 400)]
    doc, _, report = run(standard, ops, on_op_failure="skip")
    # 80 * 0.5 * 0.5 = 20; the first 1e300 makes 2e301, the second 2e601 (past float's range): dropped
    assert sorted(s["op"] for s in report["skipped"]) == [1, 3, 4, 6, 8, 9]
    assert length_of(doc) == 20 * 1e300


def test_a_scale_of_a_row_that_is_not_there_is_dropped_under_skip_and_the_rest_applies(standard):
    doc, _, report = run(standard, [add(80), scale(2, key={**LINK, "to_node": "plato-z"}), scale(0.5)],
                         on_op_failure="skip")
    assert [s["op"] for s in report["skipped"]] == [1] and length_of(doc) == 40


# -- the journal --------------------------------------------------------------------------------------------


def test_it_is_journaled_by_before_image_so_undo_works(standard):
    with_link, _, _ = run(standard, [add(80)])
    ops = resolve(with_link, {"ops": [scale(0.5)]})[0]
    resolved, before = journal.normalize_ops(with_link, ops)
    assert [op["op"] for op in resolved] == ["update"] and resolved[0]["set"] == {"link_length": 40}
    assert before[0]["link_length"] == 80
    after = cd.apply_resolved(with_link, resolved)
    assert length_of(after) == 40
    undone = cd.apply_resolved(after, journal_views.inverse_ops([{"revision": 2, "resolved": resolved, "before": before}]))
    assert length_of(undone) == 80 and cd.config_hash(undone) == cd.config_hash(with_link)


def test_config_at_every_version_shows_the_length_the_scales_made(standard):
    with_link, _, _ = run(standard, [add(80)])
    log = EpisodeLog(with_link, resolve)
    ratio = 1 - 0.0625 / 90
    for _ in range(3):
        log.finish_run(batch={"ops": [scale(ratio)], "base_mode": "rebase", "on_op_failure": "skip"})
    want = [80.0]
    for _ in range(3):
        want.append(want[-1] * ratio)
    assert [length_of(log.config_at(v)) for v in range(with_link.version, log.version + 1)] == want
    assert length_of(log.current) == want[-1]
