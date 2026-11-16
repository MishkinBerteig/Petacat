"""The Training Mode Base Configuration, v2.0: its delta resolves over the current Standard, an
override of a Standard body is checked against the Standard, and Metacat Mode's data is untouched."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from server.services import config_document as cd
from server.services import training_base as tb
from server.services.configuration_admin import reference_document

BODIES_CHANGED = {
    "rule-scout": ("    if any(l is None for l in letters):\n", "    if any(not l for l in letters):\n"),
}


def standard_body(name: str) -> str:
    return reference_document().tables["codelet_type_defs"][(name,)]["execute_body"]


def test_it_resolves_over_the_standard_and_adds_what_the_readme_says():
    base = tb.resolve_base()
    std = reference_document()
    doc = base.document
    assert cd.config_hash(std) == base.standard_hash and base.delta_hash
    assert doc.tables["engine_params"][("new_node_conceptual_depth",)]["value"] == "10"
    for name, phase in (("novel-string-scout", "scout"), ("node-instantiator", "builder")):
        row = doc.tables["codelet_type_defs"][(name,)]
        assert (row["family"], row["phase"]) == ("description", phase) and row["execute_body"].strip()
        assert (name,) not in std.tables["codelet_type_defs"]
    rule = doc.tables["posting_rules"][("novel-string-scout",)]
    assert (rule["direction"], rule["urgency_level"], rule["posting_formula"], rule["count_values"],
            rule["condition"]) == ("bottom_up", "low", "1.0", {"fixed": 1}, "num_unperceived_symbols > 0")
    order = [k[0] for k in doc.tables["posting_rules"]]
    assert order[-3:] == ["breaker", "novel-string-scout", "consolidator"]
    assert tb.resolve_base().delta_hash == base.delta_hash  # stable


def test_the_three_link_instantiators_are_meta_builders_with_a_body_and_no_posting_rule_and_the_old_names_are_gone():
    doc = tb.resolve_base().document
    for name in ("adjacent-instantiator", "category-instantiator", "instance-of-instantiator"):
        row = doc.tables["codelet_type_defs"][(name,)]
        assert (row["family"], row["phase"]) == ("meta", "builder")
        assert "take_proposed_ops" in row["execute_body"] and "apply_ops" in row["execute_body"]
        assert (name,) not in reference_document().tables["codelet_type_defs"]
        assert all(k != (name,) for k in doc.tables["posting_rules"])
        # consolidator proposes for each of them
        assert f"built_by='{name}'" in doc.tables["codelet_type_defs"][("consolidator",)]["execute_body"]
    for old in ("symbol-scout", "symbol-builder"):
        assert (old,) not in doc.tables["codelet_type_defs"] and (old,) not in doc.tables["posting_rules"]


def test_the_node_instantiator_proposes_the_new_node_as_a_trigger_and_no_link():
    body = tb.resolve_base().document.tables["codelet_type_defs"][("node-instantiator",)]["execute_body"]
    assert "add_link" not in body and "plato-cp-%04x" in body
    assert "propose_ops([{'op': 'add_trigger', 'rule_key': 'consolidator', 'node': node.name}])" in body
    assert body.index("apply_ops(") < body.index("add_trigger")  # the node exists before it is proposed as a trigger


def test_the_standard_is_not_changed_by_resolving():
    before = cd.config_hash(reference_document())
    tb.resolve_base()
    assert cd.config_hash(reference_document()) == before


def test_each_override_is_the_standard_body_with_only_the_documented_change():
    doc = tb.resolve_base().document.tables["codelet_type_defs"]
    old, new = BODIES_CHANGED["rule-scout"]
    assert doc[("rule-scout",)]["execute_body"].replace(
        "    # v2.0 Base: letter_node returns a falsy Absent token for a symbol with no node, never None.\n" + new, old
    ) == standard_body("rule-scout")
    answer = doc[("answer-finder",)]["execute_body"]
    seed = standard_body("answer-finder")
    assert "answer_present" not in answer and "answer_present(" in seed
    assert answer.endswith(seed[seed.index("quality = compute_answer_quality"):])
    assert "num_unperceived" not in answer and "role('dimension.letter_category')" in answer


@pytest.fixture
def broken_standard():
    """A copy of the Standard whose body of ``rule-scout`` has changed."""
    std = reference_document()
    tables = {t: dict(rows) for t, rows in std.tables.items()}
    row = dict(tables["codelet_type_defs"][("rule-scout",)])
    row["execute_body"] += "\n# a later Standard change\n"
    tables["codelet_type_defs"][("rule-scout",)] = row
    return cd.from_rows({t: list(rows.values()) for t, rows in tables.items()}, version=0)


def test_a_changed_standard_body_fails_loudly(broken_standard):
    with pytest.raises(tb.BaseOutOfDate) as info:
        tb.resolve_base(standard=broken_standard)
    message = str(info.value)
    assert "rule-scout" in message and "sha256" in message and "Standard" in message


def test_a_standard_change_that_breaks_an_op_fails_loudly():
    std = reference_document()
    rows = {t: [dict(r) for r in rs.values()] for t, rs in std.tables.items()}
    rows["engine_params"] = [r for r in rows["engine_params"] if r["name"] != "new_node_conceptual_depth"]
    rows["codelet_type_defs"].append({**std.tables["codelet_type_defs"][("rule-scout",)], "name": "novel-string-scout"})
    with pytest.raises(tb.BaseOutOfDate) as info:
        tb.resolve_base(standard=cd.from_rows(rows, version=0))
    assert "no longer resolves" in str(info.value)


def test_a_file_reference_is_replaced_by_the_text_and_cannot_leave_the_folder(monkeypatch, tmp_path):
    folder = tmp_path / "v2.0"
    (folder / "codelets").mkdir(parents=True)
    (folder / "codelets" / "x.py").write_text("fizzle()\n")
    (folder / "delta.json").write_text(json.dumps({"ops": [
        {"op": "set_codelet_body", "name": "n", "source": {"$file": "codelets/x.py"}}]}))
    monkeypatch.setattr(tb, "BASES_DIR", tmp_path)
    assert tb.load_delta()[0]["source"] == "fizzle()\n"
    (folder / "delta.json").write_text(json.dumps({"ops": [{"op": "x", "v": {"$file": "../../etc/hosts"}}]}))
    with pytest.raises(tb.BaseOutOfDate):
        tb.load_delta()


def test_an_edit_to_a_codelet_file_changes_the_delta_hash(monkeypatch, tmp_path):
    real = tb.BASES_DIR / "v2.0"
    copy = tmp_path / "v2.0"
    shutil.copytree(real, copy)
    monkeypatch.setattr(tb, "BASES_DIR", tmp_path)
    first = tb.resolve_base().delta_hash
    scout = copy / "codelets" / "novel-string-scout.py"
    scout.write_text(scout.read_text() + "\n# edited\n")
    assert tb.resolve_base().delta_hash != first


# -- increment 2: ``adjacent`` ------------------------------------------------------------------------------


def test_the_deltas_first_op_creates_the_adjacent_link_type_with_the_lateral_behaviour():
    base = tb.resolve_base()
    first = base.resolved[0]
    assert first["op"] == "insert" and first["table"] == "link_types"
    assert first["row"]["name"] == "adjacent" and first["row"]["behaviour"] == "lateral"
    assert tb.load_delta()[0]["op"] == "add_link_type"
    std = reference_document()
    assert ("adjacent",) not in std.tables["link_types"] and ("adjacent",) in base.document.tables["link_types"]


def test_plato_adjacent_is_an_instance_of_bond_category_and_copies_successors_properties_but_its_depth():
    doc = tb.resolve_base().document
    nodes, links = doc.tables["slipnet_node_defs"], doc.tables["slipnet_link_defs"]
    adjacent, successor = nodes[("plato-adjacent",)], nodes[("plato-successor",)]
    assert adjacent["short_name"] == "adjacent" and adjacent["plain_name"] == "adjacent"
    # adjacency is the lowest-depth link concept: 45, just below successor's and predecessor's 50
    assert successor["conceptual_depth"] == nodes[("plato-predecessor",)]["conceptual_depth"] == 50
    assert adjacent["conceptual_depth"] == 45
    assert adjacent["descriptor_predicate"] is None and adjacent["glyph"] is None and adjacent["numeric_value"] is None
    assert list(nodes)[-1] == ("plato-adjacent",) or ("plato-adjacent",) in nodes
    for frm, to, kind in (("plato-successor", "plato-bond-category", "category"),
                          ("plato-bond-category", "plato-successor", "instance")):
        mirror = links[(frm, to, kind, "")]
        new = links[(frm.replace("successor", "adjacent"), to.replace("successor", "adjacent"), kind, "")]
        assert (new["link_length"], new["fixed_length"]) == (mirror["link_length"], mirror["fixed_length"])
    std = reference_document()
    assert ("plato-adjacent",) not in std.tables["slipnet_node_defs"]


def test_adjacent_has_a_long_intrinsic_link_length_a_theme_relation_and_a_role():
    doc = tb.resolve_base().document
    lengths = json.loads(doc.tables["engine_params"][("intrinsic_link_lengths",)]["value"])
    std_lengths = json.loads(reference_document().tables["engine_params"][("intrinsic_link_lengths",)]["value"])
    assert lengths["plato-adjacent"] == 90 and {k: v for k, v in lengths.items() if k != "plato-adjacent"} == std_lengths
    relation = doc.tables["theme_relations"][("adjacent",)]
    assert relation["node_name"] == "plato-adjacent" and relation["role"] is None and relation["abstractness"] is None
    assert doc.tables["slipnet_node_roles"][("bond_category.adjacent", 0)]["node_name"] == "plato-adjacent"
    std = reference_document()
    assert ("adjacent",) not in std.tables["theme_relations"]
    assert ("bond_category.adjacent", 0) not in std.tables["slipnet_node_roles"]


def test_the_bond_scout_override_is_the_standard_body_with_only_the_fizzle_replaced():
    doc = tb.resolve_base().document.tables["codelet_type_defs"]
    body, seed = doc[("bottom-up-bond-scout",)]["execute_body"], standard_body("bottom-up-bond-scout")
    assert "role('bond_category.adjacent')" in body and "role('bond_category.adjacent')" not in seed
    old = ("if bond_cat is None:\n    if verbose:\n        say('no-bond-between-descriptors')\n    fizzle()\n")
    assert old in seed
    # everything before and after the replaced block is the Standard's, character for character
    head, tail = seed.split(old)
    assert body.startswith(head) and body.endswith(tail) and "choose_bond_facet(obj, neighbor)" in body
    assert "incompatible_bond_candidates(obj, neighbor, bond_facet, bond_cat)" in body
    # the fizzle stays, behind the role being absent
    assert "if not bond_cat:" in body and "fizzle()" in body


def test_a_changed_standard_bond_scout_body_fails_loudly():
    std = reference_document()
    tables = {t: dict(rows) for t, rows in std.tables.items()}
    row = dict(tables["codelet_type_defs"][("bottom-up-bond-scout",)])
    row["execute_body"] += "\n# a later Standard change\n"
    tables["codelet_type_defs"][("bottom-up-bond-scout",)] = row
    changed = cd.from_rows({t: list(rows.values()) for t, rows in tables.items()}, version=0)
    with pytest.raises(tb.BaseOutOfDate) as info:
        tb.resolve_base(standard=changed)
    assert "bottom-up-bond-scout" in str(info.value) and "sha256" in str(info.value)


def test_the_delta_records_the_standard_bodys_sha256_for_the_bond_scout():
    ops = {o.get("name"): o for o in tb.load_delta() if o["op"] == "set_codelet_body"}
    assert ops["bottom-up-bond-scout"]["standard_sha256"] == hashlib.sha256(
        standard_body("bottom-up-bond-scout").encode("utf-8")).hexdigest()


# -- increment 3: ``consolidator`` ----------------------------------------------------------------------------


def test_consolidator_is_a_meta_codelet_with_one_top_down_rule_and_the_26_letters_as_triggers():
    doc = tb.resolve_base().document
    row = doc.tables["codelet_type_defs"][("consolidator",)]
    assert (row["family"], row["phase"]) == ("meta", "other") and row["execute_body"].strip()
    assert ("consolidator",) not in reference_document().tables["codelet_type_defs"]
    rule = doc.tables["posting_rules"][("consolidator",)]
    assert (rule["direction"], rule["urgency_formula"], rule["posting_formula"], rule["count_formula"],
            rule["count_values"], rule["condition"]) == (
        "top_down", "conceptual_depth * activation / 100", "average_unhappiness / 100", "fixed", {"fixed": 1}, "always")
    letters = [f"plato-{c}" for c in "abcdefghijklmnopqrstuvwxyz"]
    assert list(rule["triggering_slipnodes"]) == letters
    top_down = json.loads(doc.tables["engine_params"][("top_down_slipnodes",)]["value"])
    assert top_down[-26:] == letters and len(set(top_down)) == len(top_down)
    # no other rule fires for a letter: each seed top-down rule names its own triggers
    for key, other in doc.tables["posting_rules"].items():
        if other["direction"] == "top_down" and key != ("consolidator",):
            assert other["triggering_slipnodes"] and not set(other["triggering_slipnodes"]) & set(letters), key


def test_the_five_consolidator_parameters_are_in_the_base_only():
    doc, std = tb.resolve_base().document, reference_document()
    expected = {"consolidation_threshold": ("40", "int"), "adjacent_link_length": ("90", "int"),
                "adjacent_link_step": ("0.0625", "float"), "symbol_category_link_length": ("20", "int"),
                "symbol_instance_link_length": ("97", "int")}
    for name, (value, kind) in expected.items():
        row = doc.tables["engine_params"][(name,)]
        assert (row["value"], row["value_type"]) == (value, kind) and (name,) not in std.tables["engine_params"]
    assert expected["symbol_category_link_length"][0] == str(
        std.tables["slipnet_link_defs"][("plato-a", "plato-letter-category", "category", "")]["link_length"])
    assert expected["symbol_instance_link_length"][0] == str(
        std.tables["slipnet_link_defs"][("plato-letter-category", "plato-a", "instance", "")]["link_length"])
