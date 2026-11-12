"""``add_param``: a new numeric ``engine_params`` row, journaled so that undo and ``config_at`` work."""

from __future__ import annotations

import pytest

from server.services import config_document as cd
from server.services import journal, journal_views
from server.services.change_resolve import ChangeRefused, resolve
from tests.integration.equivalence_harness import SEED_DIR


@pytest.fixture(scope="module")
def cfg() -> cd.ConfigDocument:
    return cd.document_from_standard_files(SEED_DIR)


def add(name="a_new_number", to=7, value_type="int", **kw):
    return {"op": "add_param", "name": name, "to": to, "value_type": value_type, **kw}


def test_it_adds_a_row_with_its_value_and_type(cfg):
    ops, _ = resolve(cfg, {"ops": [add(to=7), add("a_float", 0.125, "float"), add("a_ratio", 2, "rational")]})
    doc = cd.apply_resolved(cfg, ops)
    rows = doc.tables["engine_params"]
    assert (rows[("a_new_number",)]["value"], rows[("a_new_number",)]["value_type"]) == ("7", "int")
    assert rows[("a_float",)]["value"] == "0.125" and rows[("a_float",)]["value_type"] == "float"
    assert rows[("a_ratio",)]["value"] == "2/1" and rows[("a_ratio",)]["value_type"] == "rational"
    assert ("a_new_number",) not in cfg.tables["engine_params"]  # the input is not mutated


def test_it_refuses_a_name_that_exists(cfg):
    with pytest.raises(ChangeRefused) as info:
        resolve(cfg, {"ops": [add("update_cycle_length", 3)]})
    assert info.value.problems[0].kind == "key_exists"


@pytest.mark.parametrize("value_type", ["string", "json", "bool"])
def test_it_takes_numbers_only(cfg, value_type):
    with pytest.raises(ChangeRefused) as info:
        resolve(cfg, {"ops": [add(to="x", value_type=value_type)]})
    assert "numeric" in info.value.problems[0].message


def test_it_needs_a_value_type_and_a_value_that_parses(cfg):
    with pytest.raises(ChangeRefused):
        resolve(cfg, {"ops": [{"op": "add_param", "name": "n", "to": 1}]})
    with pytest.raises(ChangeRefused):
        resolve(cfg, {"ops": [add(to="seven")]})


def test_set_and_adjust_still_refuse_a_missing_row(cfg):
    for op in ({"op": "set_param", "name": "nope", "to": 1}, {"op": "adjust_param", "name": "nope", "by": 1}):
        with pytest.raises(ChangeRefused):
            resolve(cfg, {"ops": [op]})


def test_it_is_an_insert_with_no_before_image_so_undo_and_config_at_work(cfg):
    ops, _ = resolve(cfg, {"ops": [add()]})
    resolved, before = journal.normalize_ops(cfg, ops)
    assert [op["op"] for op in resolved] == ["insert"] and before == [None]
    after = cd.apply_resolved(cfg, resolved)
    entry = {"revision": 1, "resolved": resolved, "before": before}
    undone = cd.apply_resolved(after, journal_views.inverse_ops([entry]))
    assert cd.config_hash(undone) == cd.config_hash(cfg)


def test_the_cli_compares_against_the_standard_or_the_v2_base():
    from server.configuration_cli import _parser

    assert _parser().parse_args(["diff"]).against == "standard"
    assert _parser().parse_args(["--against", "training-v2", "diff"]).against == "training-v2"
    with pytest.raises(SystemExit):
        _parser().parse_args(["--against", "elsewhere", "diff"])
