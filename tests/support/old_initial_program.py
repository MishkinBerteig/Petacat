"""The initial-description program as ``server/engine/runner.py`` held it before stage 6 moved it
into the configuration (``initial_description_rules``, ``initial_activation_rules``).

Kept as the oracle for ``tests/seed_unit/test_initial_program.py``: the Metacat Standard Configuration's
rows must give every letter exactly the descriptions, in exactly the order, that this code gave it,
and put exactly the same concepts active.  Nothing in ``server/`` reads this module.
"""

from __future__ import annotations

from typing import Any


def old_add_initial_descriptions(workspace: Any, slipnet: Any, meta: Any) -> None:
    from server.engine.descriptions import Description
    from server.engine.workspace_objects import Letter

    built_level = meta.vocabulary.proposal_level_built
    roles = slipnet.roles
    letter_cat_node = roles.dimension_letter_category
    obj_cat_node = roles.dimension_object_category
    letter_obj_node = roles.object_letter
    str_pos_node = roles.dimension_string_position
    leftmost_node = roles.position_leftmost
    rightmost_node = roles.position_rightmost
    middle_node = roles.position_middle
    single_node = roles.position_single
    max_act = slipnet.activation_params.max_activation

    if obj_cat_node and any(s.length == 1 for s in workspace.all_strings):
        obj_cat_node.activation = max_act

    for ws_string in workspace.all_strings:
        letters = [o for o in ws_string.objects if isinstance(o, Letter)]
        for letter in letters:
            if obj_cat_node and letter_obj_node:
                desc = Description(letter, obj_cat_node, letter_obj_node)
                desc.proposal_level = built_level
                letter.descriptions.insert(0, desc)
                letter_obj_node.activation = max_act

            if letter_cat_node and letter.letter_category:
                desc = Description(letter, letter_cat_node, letter.letter_category)
                desc.proposal_level = built_level
                letter.descriptions.insert(0, desc)
                letter.letter_category.activation = max_act

            if str_pos_node and len(letters) == 1:
                if single_node:
                    desc = Description(letter, str_pos_node, single_node)
                    desc.proposal_level = built_level
                    letter.descriptions.insert(0, desc)
                    single_node.activation = max_act
            elif str_pos_node:
                if letter.left_string_pos == 0 and leftmost_node:
                    desc = Description(letter, str_pos_node, leftmost_node)
                    desc.proposal_level = built_level
                    letter.descriptions.insert(0, desc)
                    leftmost_node.activation = max_act
                if letter.right_string_pos == len(letters) - 1 and rightmost_node:
                    desc = Description(letter, str_pos_node, rightmost_node)
                    desc.proposal_level = built_level
                    letter.descriptions.insert(0, desc)
                    rightmost_node.activation = max_act
                if len(letters) % 2 == 1 and letter.left_string_pos == len(letters) // 2 and middle_node:
                    desc = Description(letter, str_pos_node, middle_node)
                    desc.proposal_level = built_level
                    letter.descriptions.insert(0, desc)
                    middle_node.activation = max_act


def old_attach_initial_descriptions(self: Any) -> None:
    """``Group._attach_initial_descriptions`` as ``groups.py`` held it before the group program moved
    into the configuration (bind it as the method to run the old code)."""
    from server.engine.descriptions import Description
    from server.engine.groups import _slipnet_of, holds_role
    from server.engine.run_binding import constants

    slipnet = _slipnet_of(self)
    if slipnet is None:
        return
    roles = slipnet.roles

    def describe(dt, descriptor, *, bond_description: bool = False) -> None:
        if not dt or descriptor is None or not descriptor:
            return
        desc = Description(self, dt, descriptor)
        desc.proposal_level = constants().vocab.proposal_level_built
        if bond_description:
            self.bond_descriptions.insert(0, desc)
        else:
            self.descriptions.insert(0, desc)

    describe(roles.dimension_object_category, roles.object_group)
    describe(roles.dimension_group_category, self.group_category)
    describe(roles.dimension_bond_category, self.bond_category, bond_description=True)
    if self.direction is not None:
        describe(roles.dimension_direction, self.direction)
    if self.spans_whole_string():
        describe(roles.dimension_string_position, roles.position_whole)
    elif self.leftmost_in_string():
        describe(roles.dimension_string_position, roles.position_leftmost)
    elif self.middle_in_string():
        describe(roles.dimension_string_position, roles.position_middle)
    elif self.rightmost_in_string():
        describe(roles.dimension_string_position, roles.position_rightmost)
    describe(roles.dimension_bond_facet, self.bond_facet, bond_description=True)
    if holds_role(self.bond_facet, "dimension.letter_category"):
        describe(roles.dimension_letter_category, self._get_initial_letter_category())


def old_describe_letters(string: Any, slipnet: Any) -> None:
    """``answers._describe_letters`` as it was before the translated-letter program moved."""
    from server.engine.descriptions import Description

    letter_category = slipnet.roles.dimension_letter_category
    object_category = slipnet.roles.dimension_object_category
    letter_node = slipnet.roles.object_letter
    if not letter_category:
        return
    for letter in string.letters:
        if object_category and letter_node:
            if not letter.description_type_present(object_category):
                letter.add_description(Description(letter, object_category, letter_node))
        if not letter.description_type_present(letter_category):
            letter.add_description(Description(letter, letter_category, letter.letter_category))
