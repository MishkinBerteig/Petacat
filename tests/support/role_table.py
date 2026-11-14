"""The role vocabulary of the configuration-source plan (section 3.2), with today's literals.

``SINGLE_ROLES`` maps each single-node role to the node name the engine reaches for with a
string literal today; ``ORDERED_ROLES`` does the same for the two ordered roles;
``CODELET_ROLES`` for the five codelet roles.  Under the Metacat Standard Configuration the
role is bound to exactly that node.  The table is the contract the role-identity gate (G5,
``tests/seed_unit/test_role_identity.py``) checks and the source the reduced-configuration
fixtures use to say which node "one role unbound" removes.

Nothing here is read by the engine.  ``server/engine/roles.py`` (EN3) has its own registry,
and ``tests/seed_unit/test_roles.py`` checks that the two agree.
"""

from __future__ import annotations

#: Roles of the vocabulary that the Metacat Standard Configuration does not bind (they are single-node
#: roles, but absent under the Standard): the Training Mode Base Configuration, v2.0, binds them.
UNBOUND_UNDER_STANDARD: tuple[str, ...] = ("bond_category.adjacent",)

SINGLE_ROLES: dict[str, str] = {
    "dimension.direction": "plato-direction-category",
    "dimension.group_category": "plato-group-category",
    "dimension.alphabetic_position": "plato-alphabetic-position-category",
    "dimension.letter_category": "plato-letter-category",
    "dimension.length": "plato-length",
    "dimension.object_category": "plato-object-category",
    "dimension.string_position": "plato-string-position-category",
    "dimension.bond_facet": "plato-bond-facet",
    "dimension.bond_category": "plato-bond-category",
    "position.whole": "plato-whole",
    "position.leftmost": "plato-leftmost",
    "position.middle": "plato-middle",
    "position.rightmost": "plato-rightmost",
    "position.single": "plato-single",
    "direction.left": "plato-left",
    "direction.right": "plato-right",
    "object.letter": "plato-letter",
    "object.group": "plato-group",
    "bond_category.sameness": "plato-sameness",
    "group_category.sameness": "plato-samegrp",
    "group_category.successor": "plato-succgrp",
    "group_category.predecessor": "plato-predgrp",
    "alphabet.first_marker": "plato-alphabetic-first",
    "alphabet.last_marker": "plato-alphabetic-last",
}

#: The ``image_operation.*`` roles (stage 6): the dimension each image operation of
#: ``transform-image`` is bound to.  Each shares its node with a ``dimension.*`` role, so they are
#: kept apart from ``SINGLE_ROLES`` for the "one role, one node" check and added to it below.
IMAGE_OPERATION_ROLES: dict[str, str] = {
    "image_operation.letter_or_group": "plato-object-category",
    "image_operation.new_start_letter": "plato-letter-category",
    "image_operation.new_length": "plato-length",
    "image_operation.reverse_direction": "plato-direction-category",
    "image_operation.reverse_medium": "plato-group-category",
    "image_operation.new_alpha_position_category": "plato-alphabetic-position-category",
}
SINGLE_ROLES.update(IMAGE_OPERATION_ROLES)

ORDERED_ROLES: dict[str, tuple[str, ...]] = {
    "rule.dimension_order": (
        "plato-direction-category",
        "plato-group-category",
        "plato-alphabetic-position-category",
        "plato-letter-category",
        "plato-length",
        "plato-object-category",
        "plato-string-position-category",
        "plato-bond-facet",
    ),
    "answer.description_dimension": (
        "plato-alphabetic-position-category",
        "plato-string-position-category",
        "plato-direction-category",
        "plato-group-category",
        "plato-bond-facet",
    ),
    # The policy sets (stage 6): which dimensions behave a way.
    "dimension.ladder": ("plato-letter-category", "plato-length"),
    "dimension.reverses_together": (
        "plato-direction-category", "plato-bond-category", "plato-group-category"),
    "dimension.bond_description": ("plato-bond-category", "plato-bond-facet"),
    "dimension.freely_mappable": ("plato-string-position-category", "plato-length"),
    "bond_category.symmetric": ("plato-sameness",),
    "group_category.directed": ("plato-succgrp", "plato-predgrp"),
    "rule.object_naming_dimension": (
        "plato-string-position-category", "plato-alphabetic-position-category"),
    "rule.letter_or_alphabetic_dimension": (
        "plato-letter-category", "plato-alphabetic-position-category"),
    "rule.relation_only_dimension": ("plato-direction-category", "plato-group-category"),
    "descriptor.generic": ("plato-letter", "plato-group"),
    "rule.apply_first": ("plato-group-category",),
    "rule.apply_by_length": ("plato-length",),
}

CODELET_ROLES: dict[str, str] = {
    "evaluator.bond": "bond-evaluator",
    "evaluator.group": "group-evaluator",
    "evaluator.description": "description-evaluator",
    "recruit.description_scout": "top-down-description-scout",
    "recruit.group_scout_category": "top-down-group-scout:category",
}

#: Not roles (plan 3.2): the four relation nodes, the five numbers, the 26 letters.
RELATION_NODES: tuple[str, ...] = (
    "plato-identity", "plato-opposite", "plato-successor", "plato-predecessor")
NUMBER_NODES: tuple[str, ...] = (
    "plato-one", "plato-two", "plato-three", "plato-four", "plato-five")
LETTER_NODES: tuple[str, ...] = tuple(f"plato-{chr(c)}" for c in range(ord("a"), ord("z") + 1))


def role_attr(role: str) -> str:
    """The attribute of ``slipnet.roles`` a role is read from: dots become underscores
    (``dimension.length`` -> ``roles.dimension_length``).  ``RoleSpec.attr`` in
    ``server/engine/roles.py`` is the same rule, and the G5 test checks they agree."""
    return role.replace(".", "_")
