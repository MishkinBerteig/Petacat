"""The role mechanism (EN3): the vocabulary, the ``Absent`` token, ``Roles``, resolution at
Slipnet build, the run-start check, and the skeleton of the any-configuration suite (G9).

Nothing in the engine consumes a role yet (stage 2 switches the code over), so this proves the
mechanism on its own: the vocabulary agrees with the Metacat Standard Configuration and with
``tests/support/role_table.py``; the ``Absent`` token has the properties the plan (3.2) gives
it; resolution never raises, on the Metacat Standard Configuration or on any reduced one.
"""

from __future__ import annotations

import copy
import json
import pickle
from pathlib import Path
from types import SimpleNamespace

import pytest

from server.engine import roles as R
from server.engine.metadata import MetadataProvider
from server.engine.slipnet import Slipnet
from server.engine.start_check import (
    REQUIRED_FORMULA_COEFFICIENTS, REQUIRED_URGENCY_LEVELS, RunStartError, check_run_start,
    require_run_start,
)
from tests.support import reduced_configurations as rc
from tests.support.role_table import CODELET_ROLES, ORDERED_ROLES, SINGLE_ROLES, role_attr

SEED_DIR = Path(__file__).resolve().parents[2] / "seed_data"


@pytest.fixture(scope="module")
def meta():
    return MetadataProvider.from_standard_configuration(str(SEED_DIR))


@pytest.fixture(scope="module")
def slipnet(meta):
    return Slipnet.from_metadata(meta)


# ---------------------------------------------------------------------------
# The vocabulary
# ---------------------------------------------------------------------------


def test_vocabulary_agrees_with_the_role_table_and_the_standard_configuration() -> None:
    ours = {s.name: (s.target_kind, s.cardinality) for s in R.ROLES}
    expected = {r: (R.NODE, R.ONE) for r in SINGLE_ROLES}
    expected.update({r: (R.NODE, R.ORDERED) for r in ORDERED_ROLES})
    expected.update({r: (R.CODELET_TYPE, R.ONE) for r in CODELET_ROLES})
    assert ours == expected
    assert len(R.ROLES) == 31
    data = json.loads((SEED_DIR / "roles.json").read_text())
    bound = {b["role"] for b in data["node_roles"]} | {b["role"] for b in data["codelet_roles"]}
    assert bound == set(ours)
    assert all(s.attr == role_attr(s.name) for s in R.ROLES)
    assert len({s.attr for s in R.ROLES}) == len(R.ROLES)


def test_the_vocabulary_names_no_node() -> None:
    assert not any(s.name.startswith("plato-") for s in R.ROLES)


# ---------------------------------------------------------------------------
# The Absent token
# ---------------------------------------------------------------------------


def test_absent_is_falsy_frozen_and_identical_only_to_itself() -> None:
    a, b = R.absent("dimension.length"), R.absent("dimension.direction")
    assert not a and not b
    assert R.absent("dimension.length") is a  # one token per role
    assert a is not b and a != b  # two absent roles never compare equal
    assert a != None and a is not None  # noqa: E711
    assert a not in (None, b)
    with pytest.raises(AttributeError):
        a.activation = 50.0  # type: ignore[misc]
    with pytest.raises(AttributeError):
        a.role = "x"  # type: ignore[misc]
    assert copy.copy(a) is a and copy.deepcopy(a) is a and pickle.loads(pickle.dumps(a)) is a


def test_absent_is_node_shaped() -> None:
    a = R.absent("dimension.length")
    assert a.activation == 0 and a.activation_buffer == 0 and a.conceptual_depth == 0
    assert not a.fully_active() and not a.above_threshold() and not a.partially_active()
    assert not a.frozen and not a.is_instance
    for links in (a.category_links, a.instance_links, a.property_links, a.lateral_links,
                  a.lateral_sliplinks, a.incoming_links, a.outgoing_links):
        assert len(links) == 0
    assert a.get_related_node("anything") is None
    assert a.roles == frozenset() and not a.has_role("dimension.length")
    assert a.category is None and a.descriptor_predicate is None
    assert not a.describes(object()) and not a.description_possible(object())
    a.decay(); a.clamp(); a.unclamp(); a.tick_clamp(); a.activate_from_workspace()
    assert a.activation == 0  # the mutators do nothing
    assert "dimension.length" in a.name and "dimension.length" in repr(a)


# ---------------------------------------------------------------------------
# Roles and resolution
# ---------------------------------------------------------------------------


def test_roles_never_hold_none() -> None:
    empty = R.Roles()
    for name, value in empty.items():
        assert value is not None
        if R.ROLE_BY_NAME[name].cardinality == R.ORDERED:
            assert value == ()
        else:
            assert value is R.absent(name) and not value
    with pytest.raises(AttributeError):
        empty.dimension_length = 1  # type: ignore[misc]
    # A bare Slipnet has every role absent.
    assert Slipnet().roles.get("dimension.length") is R.absent("dimension.length")


def test_every_role_of_the_standard_configuration_is_bound(slipnet) -> None:
    for name, value in slipnet.roles.items():
        assert value is not None
        spec = R.ROLE_BY_NAME[name]
        if spec.cardinality == R.ORDERED:
            assert len(value) > 0 and all(value)
        else:
            assert value, f"{name} is absent under the Metacat Standard Configuration"


def test_every_node_of_the_standard_configuration_is_truthy(slipnet) -> None:
    assert len(slipnet.nodes) == 59 and all(bool(n) for n in slipnet.nodes.values())


def test_node_roles_are_the_role_names_the_node_holds(slipnet) -> None:
    held = slipnet.nodes[SINGLE_ROLES["dimension.direction"]].roles
    assert isinstance(held, frozenset)
    assert held == {"dimension.direction", "rule.dimension_order", "answer.description_dimension"}
    assert slipnet.nodes[SINGLE_ROLES["dimension.direction"]].has_role("rule.dimension_order")
    assert slipnet.nodes["plato-a"].roles == frozenset()  # a letter holds no role


def _binding_meta(meta, node_roles=(), codelet_roles=()):
    from dataclasses import replace

    return replace(meta, node_roles=tuple(node_roles), codelet_roles=tuple(codelet_roles))


def test_unknown_role_names_and_missing_targets_are_skipped(meta) -> None:
    from server.engine.metadata import CodeletRoleSpec, NodeRoleSpec

    some = next(iter(meta.slipnet_node_specs))
    ctype = next(iter(meta.codelet_specs))
    m = _binding_meta(
        meta,
        node_roles=[
            NodeRoleSpec("not.a.role", 0, some),            # not in the vocabulary
            NodeRoleSpec("evaluator.bond", 0, some),        # a codelet role in the node table
            NodeRoleSpec("dimension.length", 0, "no-such-node"),  # target does not exist
            NodeRoleSpec("position.whole", 3, some),        # higher ordinal ...
            NodeRoleSpec("position.whole", 1, some),        # ... lowest ordinal wins
        ],
        codelet_roles=[
            CodeletRoleSpec("dimension.length", 0, ctype),  # a node role in the codelet table
            CodeletRoleSpec("evaluator.group", 0, "no-such-type"),
        ],
    )
    s = Slipnet.from_metadata(m)
    assert s.roles.dimension_length is R.absent("dimension.length")
    assert s.roles.evaluator_bond is R.absent("evaluator.bond")
    assert s.roles.evaluator_group is R.absent("evaluator.group")
    assert s.roles.position_whole is s.nodes[some]
    assert s.nodes[some].roles == {"position.whole"}


def test_ordered_role_keeps_ordinal_order_and_drops_gaps(meta) -> None:
    from server.engine.metadata import NodeRoleSpec

    names = list(meta.slipnet_node_specs)[:3]
    m = _binding_meta(meta, node_roles=[
        NodeRoleSpec("rule.dimension_order", 5, names[2]),
        NodeRoleSpec("rule.dimension_order", 0, names[0]),
        NodeRoleSpec("rule.dimension_order", 2, names[1]),
    ])
    s = Slipnet.from_metadata(m)
    assert [n.name for n in s.roles.rule_dimension_order] == [names[0], names[1], names[2]]
    assert s.roles.answer_description_dimension == ()


# ---------------------------------------------------------------------------
# The run-start check
# ---------------------------------------------------------------------------


def test_the_standard_configuration_passes_the_run_start_check(meta) -> None:
    assert check_run_start(meta) == ()
    require_run_start(meta)


def test_the_declared_read_list_is_what_the_engine_reads() -> None:
    import re

    engine = Path(__file__).resolve().parents[2] / "server"
    text = "\n".join(p.read_text() for p in engine.rglob("*.py") if "start_check" not in p.name)
    read = set(re.findall(r'get_formula_coeff\(\s*"([a-z_0-9]+)"', text))
    assert read <= {n for n, _ in REQUIRED_FORMULA_COEFFICIENTS}
    urgencies = set(re.findall(r'get_urgency\("([a-z_]+)"\)', text))
    assert urgencies <= {n for n, _ in REQUIRED_URGENCY_LEVELS}


def test_the_run_start_check_lists_everything_missing(meta) -> None:
    from dataclasses import replace

    coeffs = {k: v for k, v in meta.formula_coefficients.items() if k != "unhappiness_weight"}
    levels = {k: v for k, v in meta.urgency_levels.items() if k != "low"}
    m = replace(meta, formula_coefficients=coeffs, urgency_levels=levels,
                params={**meta.params, "initial_codelet_types": [], "initial_codelet_urgency": "very_low"},
                posting_rules=[])
    with pytest.raises(RunStartError) as e:
        require_run_start(m)
    text = str(e.value)
    assert "unhappiness_weight" in text and "'low'" in text and "no codelet can be posted" in text
    assert {p.check for p in e.value.problems} == {"I-1", "I-2"}


def test_an_engine_run_on_a_lacking_configuration_stops_at_the_start(meta) -> None:
    from dataclasses import replace

    from server.engine.runner import EngineRunner

    m = replace(meta, formula_coefficients={})
    with pytest.raises(RunStartError, match="temp_exponent_base"):
        EngineRunner(m).init_mcat("abc", "abd", "xyz", seed=1)


# ---------------------------------------------------------------------------
# G9 skeleton: the engine builds and resolves roles on every reduced configuration
# ---------------------------------------------------------------------------


def _check_reduced(r: rc.Reduced) -> Slipnet:
    s = Slipnet.from_metadata(rc.provider(r))
    for name, value in s.roles.items():
        assert value is not None, f"{r.name}: {name} is None"
        if R.ROLE_BY_NAME[name].cardinality == R.ONE:
            assert value is R.absent(name) or value, r.name
    return s


@pytest.mark.parametrize("role", sorted(SINGLE_ROLES))
def test_a_single_role_unbound_resolves_to_absent(role) -> None:
    s = _check_reduced(rc.role_unbound(role))
    value = s.roles.get(role)
    assert value is R.absent(role) and not value
    assert SINGLE_ROLES[role] not in s.nodes


@pytest.mark.parametrize("role", sorted(CODELET_ROLES))
def test_a_codelet_role_unbound_resolves_to_absent(role) -> None:
    s = _check_reduced(rc.role_unbound(role))
    assert s.roles.get(role) is R.absent(role)


@pytest.mark.parametrize("role", sorted(ORDERED_ROLES))
def test_an_ordered_role_loses_the_removed_element(role) -> None:
    for i, name in enumerate(ORDERED_ROLES[role]):
        s = _check_reduced(rc.role_unbound(role, i))
        assert [n.name for n in s.roles.get(role)] == [n for n in ORDERED_ROLES[role] if n != name]


def test_every_node_removed_in_turn_builds_and_resolves() -> None:
    count = 0
    for r in rc.all_node_removals():
        s = _check_reduced(r)
        assert len(s.nodes) <= 58 and all(bool(n) for n in s.nodes.values())
        count += 1
    assert count == 59


def test_the_alphabet_and_ladder_reductions_build_and_resolve() -> None:
    for r in (rc.a_d_w_z(), rc.ladder_with_gap(), rc.letter_removed("b")):
        _check_reduced(r)


def test_reduced_configurations_pass_the_run_start_check() -> None:
    """Removing concepts removes no scalar: only the named run-start messages may stop a run,
    and none applies here."""
    for r in list(rc.all_single_role_removals())[:6] + [rc.a_d_w_z(), rc.ladder_with_gap()]:
        assert check_run_start(rc.provider(r)) == (), r.name
