"""The BondFacet change of a GroupCtgy self change (rules.ss:793-801, 1050-1054).

Metacat only asks the first change description for it and then crashes transcribing the rule
when the GroupCtgy change is not first (Metacat/KNOWN-FAILURES.md, ``abc aabbcc kkjjii`` seed
20226148); the corrected reference takes the first one any description yields.
"""

from types import SimpleNamespace

from server.engine.groups import Group
from server.engine.rules import (
    CLAUSE_INTRINSIC,
    SCOPE_SELF,
    SCOPE_SUBOBJECTS,
    IntrinsicChangeDescription,
    change_descriptions_to_rule_clause_template,
)


def _node(name):
    return SimpleNamespace(name=name)


def test_bond_facet_change_is_found_when_the_group_category_change_is_not_first():
    facet_dimension = _node("plato-bond-facet")
    letter_category = _node("plato-letter-category")
    group = object.__new__(Group)
    group.bond_facet = letter_category
    group.enclosing_group = None
    group.string = None
    group.bond_descriptions = [
        SimpleNamespace(description_type=_node("plato-bond-category")),
        SimpleNamespace(description_type=facet_dimension),
    ]
    group_category = _node("plato-group-category")
    length = _node("plato-length")
    successor, opposite = _node("plato-successor"), _node("plato-opposite")
    first = IntrinsicChangeDescription(group, SCOPE_SUBOBJECTS, length, None, successor, None)
    second = IntrinsicChangeDescription(group, SCOPE_SELF, group_category, None, None, opposite)

    slipnet = SimpleNamespace(nodes={"plato-bond-facet": facet_dimension})
    kind, reference, templates = change_descriptions_to_rule_clause_template(
        [first, second], slipnet
    )

    assert kind == CLAUSE_INTRINSIC and reference is group
    assert templates[0] == (SCOPE_SELF, facet_dimension, [letter_category])
    assert len(templates) == 3
