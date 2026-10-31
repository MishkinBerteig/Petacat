"""Exact-arithmetic fidelity of urgency bins, spreading and the ``100*`` roundings.

Metacat computes in exact rationals and shadows ``round`` with a half-to-even exact
integer (utilities.ss:238-252); each test pins a value where a float shortcut lands on
the other side.  See DISCREPANCIES5.md B-1, B-3, B-4, B-5, D-4.
"""

import json
import os
from types import SimpleNamespace

from server.engine.codelet_dsl import builtins
from server.engine.coderack import Coderack
from server.engine.jootsing import _build_theme_overlap_table
from server.engine.metadata import MetadataProvider
from server.engine.slipnet import SlipnetLink, SlipnetNode

SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")


def _rack():
    return Coderack(MetadataProvider.from_seed_data(SEED_DIR))


def test_bin_follows_get_coderack_bin_on_unrounded_urgency():
    # coderack.ss:377-382.  14.4 is bin 1 (>= 100/7); rounding first gave bin 0.
    rack = _rack()
    assert rack._urgency_to_bin(14.4) == 1
    assert rack._urgency_to_bin(14) == 0
    assert rack._urgency_to_bin(28.5) == 1
    assert rack._urgency_to_bin(71.4) == 4
    assert rack._urgency_to_bin(28.6) == 2
    assert rack._urgency_to_bin(71.5) == 5
    assert rack._urgency_to_bin(100) == 6
    assert rack._urgency_to_bin(250) == 6
    assert rack._urgency_to_bin(0) == 0
    assert rack._urgency_to_bin(-3.5) == 0
    assert rack._urgency_to_bin(35) == 2
    assert rack._urgency_to_bin(99.99) == 6


def test_posting_rules_do_not_round_top_down_or_thematic_urgency():
    # slipnet.ss:214 / coderack.ss:586-591: the urgency is an unrounded value.
    with open(os.path.join(SEED_DIR, "posting_rules.json")) as fh:
        rules = json.load(fh)
    rules = rules if isinstance(rules, list) else next(iter(rules.values()))
    formulas = {
        r["codelet_type"]: r["urgency_formula"]
        for r in rules
        if r.get("urgency_formula") and r["codelet_type"] != "answer-finder"
    }
    for ctype, formula in formulas.items():
        if "temperature" in formula:
            continue
        assert "round" not in formula, (ctype, formula)


def test_spread_amount_rounds_the_exact_product():
    # slipnet.ss:181-186: round(assoc * act / 100) exact.  assoc 70, act 45 -> 31.5 -> 32.
    for activation, expected in ((45, 32), (85, 60)):
        src = SlipnetNode("a", "a", 50)
        dst = SlipnetNode("b", "b", 50)
        link = SlipnetLink(src, dst, "lateral", fixed_link_length=30)
        src.lateral_links.append(link)
        src.activation = activation
        src.spread_activation_to_neighbors(15)
        assert dst.activation_buffer == expected


def test_theme_overlap_is_rounded_like_100_star():
    # jootsing.ss:64-65: two of three snags is 67, not 66.667.
    e = {"dimension": "d", "relation": "r"}
    f = {"dimension": "d2", "relation": "r"}
    table = _build_theme_overlap_table([e, dict(e), f], 3)
    assert [ov for _, ov in table] == [67, 33]


def _ctx(length_activation=50.0):
    return SimpleNamespace(
        slipnet=SimpleNamespace(
            nodes={"plato-length": SimpleNamespace(activation=length_activation)}
        ),
        temperature=SimpleNamespace(value=50.0),
        meta=None,
        rng=None,
    )


def test_descriptor_support_is_rounded_like_100_star():
    # workspace-structure-formulas.ss:44-54: 2 of 3 groups is 67, not 66.667.
    def group(has):
        d = SimpleNamespace(descriptor=SimpleNamespace(name="plato-left" if has else "x"))
        return SimpleNamespace(is_built=True, get_all_descriptions=lambda: [d])

    string = SimpleNamespace(groups=[group(True), group(True), group(False)])
    assert builtins.descriptor_support(_ctx(), string, "plato-left") == 67
    assert builtins.descriptor_support(_ctx(), SimpleNamespace(groups=[]), "plato-left") == 0


def test_single_letter_group_exponent_is_one_for_zero_supporting(monkeypatch):
    # workspace-structure-formulas.ss:34-37: (case n (1 4) (2 2) (else 1)).
    monkeypatch.setattr(builtins, "temp_adjusted_probability", lambda p, t, m: p)
    for supporting, exponent in ((0, 1), (1, 4), (2, 2), (3, 1)):
        grp = SimpleNamespace(
            get_num_of_local_supporting_groups=lambda n=supporting: n,
            _local_support=lambda rng: 50.0,
        )
        got = builtins.single_letter_group_probability(_ctx(), grp)
        assert got == (0.5 * 0.5) ** exponent


def test_singleton_gate_asks_the_references_side_of_the_coin():
    # groups.ss:483: (stochastic-if* (1- (single-letter-group-probability g)) (fizzle)).
    with open(os.path.join(SEED_DIR, "codelet_types.json")) as fh:
        body = next(
            c["execute_body"]
            for c in json.load(fh)
            if "single_letter_group_probability" in c.get("execute_body", "")
        )
    assert "if prob(1.0 - single_letter_group_probability(singleton)):" in body


# --- D-11 smaller items --------------------------------------------------------


def test_no_describable_bridges_builds_an_identity_rule():
    # rules.ss:417-442: an empty change list is an identity rule, not a fizzle.
    from server.engine.rules import build_rule_from_bridges

    rule = build_rule_from_bridges(
        "top", [], slipnet=None, meta=MetadataProvider.from_seed_data(SEED_DIR)
    )
    assert rule is not None and rule.is_identity_rule
    assert rule.rule_clause_templates == []


def test_verbatim_rule_needs_exactly_one_verbatim_clause():
    # rules.ss:206-208.
    from server.engine.rules import Rule

    verbatim = SimpleNamespace(is_verbatim=True)
    other = SimpleNamespace(is_verbatim=False)
    rule = Rule("top", [verbatim])
    assert rule.is_verbatim_rule
    rule.clauses = [verbatim, other]
    assert not rule.is_verbatim_rule


def test_probabilistic_jump_is_a_noop_on_a_frozen_node():
    # slipnet.ss:387-389: update-activation is wrapped in (if* (not frozen?) ...).
    from server.engine.rng import RNG

    node = SlipnetNode("n", "n", 50)
    node.activation = 99.0
    node.frozen = True
    node.probabilistic_jump_to_full(RNG(1))
    assert node.activation == 99.0
