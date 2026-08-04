"""Tests for Rule and RuleClause with string type constants."""

from server.engine.rules import (
    CLAUSE_EXTRINSIC,
    CLAUSE_INTRINSIC,
    CLAUSE_VERBATIM,
    RULE_BOTTOM,
    RULE_TOP,
    Rule,
    RuleClause,
)


def test_clause_type_constants_are_strings():
    assert isinstance(CLAUSE_INTRINSIC, str)
    assert isinstance(CLAUSE_EXTRINSIC, str)
    assert isinstance(CLAUSE_VERBATIM, str)


def test_rule_type_constants_are_strings():
    assert isinstance(RULE_TOP, str)
    assert isinstance(RULE_BOTTOM, str)


def test_intrinsic_clause():
    clause = RuleClause(clause_type=CLAUSE_INTRINSIC)
    assert clause.is_intrinsic
    assert not clause.is_extrinsic
    assert not clause.is_verbatim
    assert "intrinsic" in repr(clause)


def test_extrinsic_clause():
    clause = RuleClause(clause_type=CLAUSE_EXTRINSIC)
    assert clause.is_extrinsic
    assert not clause.is_intrinsic


def test_verbatim_clause():
    clause = RuleClause(clause_type=CLAUSE_VERBATIM)
    assert clause.is_verbatim
    assert not clause.is_intrinsic


def test_top_rule():
    rule = Rule(rule_type=RULE_TOP, clauses=[])
    assert rule.is_top_rule
    assert not rule.is_bottom_rule
    assert rule.is_identity_rule  # No clauses = identity


def test_bottom_rule():
    clause = RuleClause(clause_type=CLAUSE_INTRINSIC)
    rule = Rule(rule_type=RULE_BOTTOM, clauses=[clause])
    assert rule.is_bottom_rule
    assert not rule.is_top_rule
    assert not rule.is_identity_rule


# ``translate`` now takes the two strings it maps between and the Slipnet, because
# a clause's slippages come from the vertical bridges of *its own* reference objects
# (``answers.ss:1432-1494``) rather than from a list handed in.  A rule with no
# clauses names no objects, so no string is consulted and None is admissible here.
def test_translate_top_rule_becomes_bottom():
    rule = Rule(rule_type=RULE_TOP, clauses=[])
    assert rule.translate(None, None, None).rule_type == RULE_BOTTOM


def test_translate_bottom_rule_becomes_top():
    rule = Rule(rule_type=RULE_BOTTOM, clauses=[])
    assert rule.translate(None, None, None).rule_type == RULE_TOP
