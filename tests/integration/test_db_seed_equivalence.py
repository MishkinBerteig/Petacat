"""C0, gate G4: the database path and the seed-file path build the same provider.

``MetadataProvider.from_standard_configuration`` reads the Metacat Standard Configuration
(``seed_data/*.json``).  ``load_metadata_from_db`` reads a database loaded from those
files.  Once the database load is the only production path, any divergence between the two
is a bug the engine runs on, and it has happened before (the loader once dropped
``descriptor_predicate``).  These tests load an empty scratch database from the files, with
no edits, and compare, field by field, including order and JSON number typing.

Every package that touches a loader or adds a table re-runs this file.  A new table must be
added to ``COVERED_TABLES`` below, or ``test_every_derived_table_is_checked_for_a_lossless_load``
fails: that is how the harness grows with the schema.

What the database could not carry was recorded in ``RECORDED_STORAGE_LIMITS`` rather than
hidden, and the list could only shrink.  EN2 removed the last of them (an ordinal on
``engine_params``, ``urgency_levels``, ``formula_coefficients`` and ``slipnet_layout``;
``value_type`` on the coefficients; ``json`` rather than ``jsonb`` where key order is read
back), so it is empty and the providers must now be equal in full, including order and
number typing.  A limit found later is added back with its reason.
"""

from __future__ import annotations

import json
import os
import re

import pytest

pytest.importorskip("sqlalchemy", reason="sqlalchemy not available locally")

from server.engine.hashing import config_hash
from tests.integration.equivalence_harness import (
    SEED_DIR,
    database_reachable,
    deep_differences,
    fresh_database,
    provider_differences,
    seed_provider,
)

pytestmark = pytest.mark.skipif(
    not database_reachable(),
    reason="the scratch Postgres is not reachable (start it with scripts/dev.sh db)",
)

#: Differences that exist because a table or column cannot carry what the seed file says.
#: Each is (field, regular expression over the difference line, why).  The fix for every one
#: is a schema change (an ordinal column, a ``json`` rather than ``jsonb`` column, or a
#: ``value_type`` for coefficients), which belongs to a configuration-source package, not C0.
RECORDED_STORAGE_LIMITS: tuple[tuple[str, str, str], ...] = ()


def _classify(differences: dict[str, list[str]]):
    unexplained: list[str] = []
    recorded: dict[int, list[str]] = {i: [] for i in range(len(RECORDED_STORAGE_LIMITS))}
    for field_name, lines in differences.items():
        for line in lines:
            for i, (limit_field, pattern, _why) in enumerate(RECORDED_STORAGE_LIMITS):
                if limit_field == field_name and re.search(pattern, line):
                    recorded[i].append(line)
                    break
            else:
                unexplained.append(line)
    return unexplained, recorded


@pytest.fixture(scope="module")
def db():
    return fresh_database()


@pytest.fixture(scope="module")
def seed():
    return seed_provider()


def test_provider_equals_seed_except_recorded_limits(db, seed):
    unexplained, _ = _classify(provider_differences(seed, db.provider))
    assert not unexplained, "DB provider differs from the seed provider:\n" + "\n".join(unexplained)


def test_recorded_limits_are_exactly_the_known_ones(db, seed):
    """Every recorded limit still occurs. When one is fixed, delete it from the list."""
    _, recorded = _classify(provider_differences(seed, db.provider))
    stale = [RECORDED_STORAGE_LIMITS[i][1] for i, lines in recorded.items() if not lines]
    assert not stale, f"these recorded storage limits no longer occur; remove them: {stale}"


def test_every_provider_field_is_compared(db, seed):
    """A field added to ``MetadataProvider`` is compared automatically (the walk is over
    ``dataclasses.fields``), and both providers must carry the same fields."""
    import dataclasses

    assert [f.name for f in dataclasses.fields(seed)] == [f.name for f in dataclasses.fields(db.provider)]
    assert type(seed) is type(db.provider)


def test_config_hash_is_equal(db, seed):
    assert config_hash(db.provider) == config_hash(seed)


def test_every_hashed_field_digest_is_equal(db, seed):
    from server.engine.hashing import field_digests

    assert field_digests(db.provider) == field_digests(seed)


def test_the_database_holds_exactly_the_files_engine_parameters(db, seed):
    assert set(db.provider.params) == set(seed.params)


def test_order_that_is_behaviour_is_the_seed_order(db, seed):
    """Node order and link order fix the float accumulation order and which node each
    probabilistic draw is spent on; the rule order fixes the draws per consultation."""
    p = db.provider
    assert list(p.slipnet_node_specs) == list(seed.slipnet_node_specs)
    assert p.slipnet_link_specs == seed.slipnet_link_specs
    assert list(p.codelet_specs) == list(seed.codelet_specs)
    assert p.posting_rules == seed.posting_rules
    assert list(p.codelet_patterns) == list(seed.codelet_patterns)
    assert p.codelet_patterns == seed.codelet_patterns
    assert p.demo_problems == seed.demo_problems
    assert p.theme_dimensions == seed.theme_dimensions
    assert [s.valid_relations for s in p.theme_dimensions] == [
        s.valid_relations for s in seed.theme_dimensions
    ]


def test_codelet_bodies_and_predicates_are_byte_for_byte(db, seed):
    for name, spec in seed.codelet_specs.items():
        got = db.provider.codelet_specs[name]
        assert got.execute_body.encode() == spec.execute_body.encode(), name
        assert got.description.encode() == spec.description.encode(), name
    for name, spec in seed.slipnet_node_specs.items():
        got = db.provider.slipnet_node_specs[name]
        assert got.descriptor_predicate == spec.descriptor_predicate, name


def test_number_typing_is_preserved_in_parameters(db, seed):
    """``engine_params.value_type`` carries int against float against bool."""
    for name, value in seed.params.items():
        got = db.provider.params[name]
        assert type(got) is type(value), (name, value, got)
    for name, value in seed.urgency_levels.items():
        assert type(db.provider.urgency_levels[name]) is type(value), name


def test_engine_params_value_type_column_is_right(db):
    with open(os.path.join(SEED_DIR, "engine_params.json")) as f:
        params = json.load(f)

    def expected(v):
        if isinstance(v, (list, dict)):
            return "json"
        if isinstance(v, bool):
            return "bool"
        if isinstance(v, int):
            return "int"
        if isinstance(v, float):
            return "float"
        return "string"

    rows = {r["name"]: r for r in db.tables["engine_params"]}
    for name, value in params.items():
        assert rows[name]["value_type"] == expected(value), name


# ---------------------------------------------------------------------------
# Lossless first load: the rows read straight back from the tables equal the files.
# ---------------------------------------------------------------------------


def _file(name):
    with open(os.path.join(SEED_DIR, name)) as f:
        return json.load(f)


def _enum_rows(enums, table):
    return [
        {
            "name": r["name"],
            "display_label": r["display_label"],
            "sort_order": r["sort_order"],
            "description": r.get("description", ""),
        }
        for r in enums.get(table, [])
    ]


def _expected_tables() -> dict[str, list[dict]]:
    """Each table's rows as the seed files say they should read back, by primary key."""
    from server.services.seeding import ENUM_MODELS
    from server.models import metadata as models

    out: dict[str, list[dict]] = {}
    enums = _file("enums.json")
    for table, model_name in ENUM_MODELS.items():
        out[getattr(models, model_name).__tablename__] = sorted(
            _enum_rows(enums, table), key=lambda r: r["name"]
        )
    out["slipnet_node_defs"] = sorted(
        (
            {
                "sort_order": i,
                "name": n["name"],
                "short_name": n["short_name"],
                "conceptual_depth": n["conceptual_depth"],
                "description": n.get("description", ""),
                "descriptor_predicate": n.get("descriptor_predicate"),
                "plain_name": n.get("plain_name"),
                "glyph": n.get("glyph"),
                "numeric_value": n.get("numeric_value"),
                "full_name": n.get("full_name"),
                "cm_short_name": n.get("cm_short_name"),
                "article_an": n.get("article_an"),
            }
            for i, n in enumerate(_file("slipnet_nodes.json"))
        ),
        key=lambda r: r["name"],
    )
    out["slipnet_link_defs"] = [
        {
            "id": i,
            "sort_order": i - 1,
            "from_node": lk["from_node"],
            "to_node": lk["to_node"],
            "link_type": lk["link_type"],
            "label_node": lk.get("label_node"),
            "link_length": lk.get("link_length"),
            "fixed_length": lk["fixed_length"] if "fixed_length" in lk else lk.get("link_length") is not None,
        }
        for i, lk in enumerate(_file("slipnet_links.json"), start=1)
    ]
    out["codelet_type_defs"] = sorted(
        (
            {
                "sort_order": i,
                "name": c["name"],
                "family": c["family"],
                "phase": c["phase"],
                "default_urgency": c.get("default_urgency"),
                "description": c.get("description", ""),
                "source_file": c.get("source_file", ""),
                "source_line": c.get("source_line", 0),
                "execute_body": c.get("execute_body", ""),
            }
            for i, c in enumerate(_file("codelet_types.json"))
        ),
        key=lambda r: r["name"],
    )
    out["urgency_levels"] = sorted(
        (
            {"name": k, "value": v, "sort_order": i}
            for i, (k, v) in enumerate(_file("urgency_levels.json").items())
        ),
        key=lambda r: r["name"],
    )
    out["formula_coefficients"] = sorted(
        (
            {
                "name": k,
                "value": float(v),
                "value_type": "int" if isinstance(v, int) else "float",
                "sort_order": i,
            }
            for i, (k, v) in enumerate(_file("formula_coefficients.json").items())
        ),
        key=lambda r: r["name"],
    )
    out["demo_problems"] = [
        {
            "id": i,
            "name": d["name"],
            "section": d.get("section", ""),
            "initial": d["initial"],
            "modified": d["modified"],
            "target": d["target"],
            "answer": d.get("answer"),
            "seed": d["seed"],
            "mode": d["mode"],
            "description": d.get("description", ""),
        }
        for i, d in enumerate(_file("demo_problems.json"), start=1)
    ]
    posting = _file("posting_rules.json")
    out["posting_rules"] = [
        {
            "id": i,
            "rule_key": pr["rule_key"],
            "sort_order": i - 1,
            "codelet_type": pr["codelet_type"],
            "direction": pr["direction"],
            "urgency_when_posted": pr.get("urgency_when_posted"),
            "urgency_formula": pr.get("urgency_formula"),
            "posting_formula": pr.get("posting_formula", ""),
            "count_formula": pr.get("count_formula", ""),
            "count_values": pr.get("count_values"),
            "condition": pr.get("condition", "always"),
            "triggering_slipnodes": pr.get("triggering_slipnodes"),
        }
        for i, pr in enumerate(posting.get("posting_rules", []), start=1)
    ]
    entries = [
        (name, ct, lvl)
        for name, es in posting.get("codelet_patterns", {}).items()
        for ct, lvl in es
    ]
    out["codelet_pattern_defs"] = [
        {"id": i, "ordinal": i - 1, "pattern_name": n, "codelet_type": ct, "urgency_level": lvl}
        for i, (n, ct, lvl) in enumerate(entries, start=1)
    ]
    out["theme_dimension_defs"] = [
        {"id": i, "slipnet_node": td["slipnet_node"], "valid_relations": td["valid_relations"]}
        for i, td in enumerate(_file("theme_dimensions.json").get("dimensions", []), start=1)
    ]
    out["slipnet_layout"] = sorted(
        (
            {"node_name": n, "grid_row": p[0], "grid_col": p[1], "sort_order": i}
            for i, (n, p) in enumerate(_file("slipnet_layout.json").get("node_positions", {}).items())
        ),
        key=lambda r: r["node_name"],
    )
    roles = _file("roles.json")
    out["slipnet_node_roles"] = sorted(
        (
            {"role": r["role"], "ordinal": r["ordinal"], "node_name": r["node_name"]}
            for r in roles["node_roles"]
        ),
        key=lambda r: (r["role"], r["ordinal"]),
    )
    out["codelet_type_roles"] = sorted(
        (
            {"role": r["role"], "ordinal": r["ordinal"], "codelet_type": r["codelet_type"]}
            for r in roles["codelet_roles"]
        ),
        key=lambda r: (r["role"], r["ordinal"]),
    )
    out["theme_relations"] = sorted(
        (
            {
                "name": r["name"],
                "ordinal": r["ordinal"],
                "node_name": r.get("node_name"),
                "abstractness": r.get("abstractness"),
                "description": r.get("description", ""),
            }
            for r in _file("theme_relations.json")
        ),
        key=lambda r: r["name"],
    )
    return out


#: Tables whose rows are not compared one-to-one with a file, and why.
#: ``engine_params`` carries text ``value`` columns;
#: ``commentary_templates`` is one JSONB document.
COVERED_ELSEWHERE = {"engine_params", "commentary_templates"}


def test_every_derived_table_is_checked_for_a_lossless_load(db):
    """A table added to the schema must be added to ``_expected_tables`` (or
    ``COVERED_ELSEWHERE``), or this fails: that is how the harness follows the schema."""
    assert set(db.tables) == set(_expected_tables()) | COVERED_ELSEWHERE


def test_first_load_loses_nothing(db):
    expected = _expected_tables()
    for table, rows in expected.items():
        # Rows read back with Python types; compared type for type. sort_order and ids
        # are part of the value (they carry the file's order).
        by_pk = db.tables[table]
        problems = deep_differences(rows, by_pk, table, ordered=False)
        assert not problems, "\n".join(problems)


def test_first_load_loses_no_engine_param(db):
    with open(os.path.join(SEED_DIR, "engine_params.json")) as f:
        params = json.load(f)
    stored = {r["name"] for r in db.tables["engine_params"]}
    assert set(params) <= stored
    # exactly the file's keys: the seeder writes no bookkeeping row.
    assert stored == set(params)


def test_first_load_loses_no_commentary_template(db):
    rows = db.tables["commentary_templates"]
    assert len(rows) == 1 and rows[0]["template_key"] == "all"
    # The column is ``json``, which keeps key order, so the order is compared too.
    problems = deep_differences(
        _file("commentary_templates.json"), rows[0]["template_data"], "commentary"
    )
    assert not problems, "\n".join(problems)


def test_the_harness_catches_a_difference_it_is_meant_to_catch(db, seed):
    """The comparison must see int against float, reordering and a dropped field."""
    assert deep_differences({"a": 1}, {"a": 1.0})
    assert deep_differences({"a": 1, "b": 2}, {"b": 2, "a": 1})
    assert deep_differences([1, 2], [2, 1])
    assert deep_differences(True, 1)
    assert not deep_differences({"a": [1, {"b": 2.5}]}, {"a": [1, {"b": 2.5}]})
    import dataclasses

    from server.engine.metadata import SlipnodeSpec

    node = next(iter(seed.slipnet_node_specs.values()))
    assert provider_differences(
        seed,
        dataclasses.replace(
            seed,
            slipnet_node_specs={
                **seed.slipnet_node_specs,
                node.name: dataclasses.replace(node, descriptor_predicate="True"),
            },
        ),
    )
