"""The initial-description program: what a run starts with, read from the configuration.

Before the first codelet, ``make-letter`` (Scheme ``workspace-objects.ss:21-26``) and
``init-mcat`` (``run.ss:221-232``) give every letter its first descriptions and put a few
concepts fully active.  *Which* descriptions, in what order, and which concepts, is cognition:
dropping the middle-of-an-odd-string description changes 40 of 48 runs, and the
single-letter-string activation changes 10 of 48.  So the program is configuration, two tables
read in ``ordinal`` order (``initial_description_rules``, ``initial_activation_rules``).

What stays here is the engine's control flow and the arithmetic of a closed set of conditions
(the way the count-formula kinds are a closed set the engine owns), which the rows name:

* ``DESCRIPTION_CONDITIONS``, over one letter of a string of ``n`` letters:
  ``always``; ``single`` (``n == 1``); ``leftmost`` (``n != 1`` and the letter is first);
  ``rightmost`` (``n != 1`` and the letter is last); ``middle`` (``n != 1``, ``n`` odd and the
  letter is at index ``n // 2``).  The three position conditions exclude a one-letter string,
  which is ``single``.
* ``ACTIVATION_CONDITIONS``: ``always``; ``any_single_letter_string`` (some string of the
  problem has one letter).

Each description is put at the *front* of the letter's description list, so the rows applied
last come first; the order is part of what a run does, since every stochastic description pick
and the bridge's theme cross-product walk that list in order.  A role nothing holds drops the
rule: what has no node is not perceived.
"""

from __future__ import annotations

from typing import Any, Callable

from server.engine.roles import ROLE_BY_NAME, absent
from server.engine.slipnet import holds_role

SOURCE_ROLE = "role"
SOURCE_LETTER_CATEGORY = "letter_category"
#: Sources only a group has: the group's own category, bond category, direction, bond facet, and the
#: letter category of the first object in direction order (``groups.ss:47``).
GROUP_SOURCES: tuple[str, ...] = (
    "group_category", "bond_category", "direction", "bond_facet", "initial_letter_category")
DESCRIPTOR_SOURCES: tuple[str, ...] = (SOURCE_ROLE, SOURCE_LETTER_CATEGORY) + GROUP_SOURCES

#: What a rule describes: ``letter`` (every letter of the problem's strings, at the start of a run),
#: ``translated_letter`` (the letters of a string translated from a rule, ``answers.ss``), ``group``
#: (every new group, ``make-group``, ``groups.ss:20-54``).
SUBJECTS: tuple[str, ...] = ("letter", "translated_letter", "group")

#: The conditions a ``letter`` rule may name, and the test each is (``letter`` of ``n``).
_DESCRIPTION_TESTS: dict[str, Callable[[Any, int], bool]] = {
    "always": lambda letter, n: True,
    "single": lambda letter, n: n == 1,
    "leftmost": lambda letter, n: n != 1 and letter.left_string_pos == 0,
    "rightmost": lambda letter, n: n != 1 and letter.right_string_pos == n - 1,
    "middle": lambda letter, n: n != 1 and n % 2 == 1 and letter.left_string_pos == n // 2,
}
DESCRIPTION_CONDITIONS: tuple[str, ...] = tuple(_DESCRIPTION_TESTS)

#: The conditions a ``group`` rule may name.  ``whole``, ``leftmost``, ``middle`` and ``rightmost``
#: are the cascade of ``make-group`` (``groups.ss:34-42``): the first that holds is the group's
#: position, so each is true only if the ones before it are not.
_GROUP_TESTS: dict[str, Callable[[Any], bool]] = {
    "always": lambda g: True,
    "has_direction": lambda g: g.direction is not None,
    "whole": lambda g: g.spans_whole_string(),
    "leftmost": lambda g: not g.spans_whole_string() and g.leftmost_in_string(),
    "middle": lambda g: (not g.spans_whole_string() and not g.leftmost_in_string()
                         and g.middle_in_string()),
    "rightmost": lambda g: (not g.spans_whole_string() and not g.leftmost_in_string()
                            and not g.middle_in_string() and g.rightmost_in_string()),
    "facet_is_letter_category": lambda g: holds_role(g.bond_facet, "dimension.letter_category"),
}
GROUP_CONDITIONS: tuple[str, ...] = tuple(_GROUP_TESTS)
TRANSLATED_CONDITIONS: tuple[str, ...] = ("always",)

CONDITIONS_OF = {
    "letter": DESCRIPTION_CONDITIONS, "translated_letter": TRANSLATED_CONDITIONS,
    "group": GROUP_CONDITIONS,
}
SOURCES_OF = {
    "letter": (SOURCE_ROLE, SOURCE_LETTER_CATEGORY),
    "translated_letter": (SOURCE_ROLE, SOURCE_LETTER_CATEGORY),
    "group": (SOURCE_ROLE,) + GROUP_SOURCES,
}

#: The conditions an activation rule may name, over the strings of the problem.
_ACTIVATION_TESTS: dict[str, Callable[[Any], bool]] = {
    "always": lambda workspace: True,
    "any_single_letter_string": lambda workspace: any(s.length == 1 for s in workspace.all_strings),
}
ACTIVATION_CONDITIONS: tuple[str, ...] = tuple(_ACTIVATION_TESTS)


def _node(roles: Any, role: str | None) -> Any:
    """The node bound to *role*, or its ``Absent`` token (an unknown role name is unbound)."""
    spec = ROLE_BY_NAME.get(role) if role else None
    return roles.get(role) if spec is not None else absent(role or "")


def problems(meta: Any) -> list[tuple[str, str, str]]:
    """What a run cannot start with: ``(rule table, rule key, what is wrong)`` for each rule
    that names a condition or a descriptor source the engine does not define."""
    out: list[tuple[str, str, str]] = []
    for rule in meta.initial_description_rules:
        if rule.subject not in SUBJECTS:
            out.append(("initial_description_rules", rule.rule_key, f"subject '{rule.subject}'"))
            continue
        if rule.condition not in CONDITIONS_OF[rule.subject]:
            out.append(("initial_description_rules", rule.rule_key,
                        f"condition '{rule.condition}' of a {rule.subject}"))
        if rule.descriptor_source not in SOURCES_OF[rule.subject]:
            out.append(("initial_description_rules", rule.rule_key,
                        f"descriptor_source '{rule.descriptor_source}' of a {rule.subject}"))
    for rule in meta.initial_activation_rules:
        if rule.condition not in _ACTIVATION_TESTS:
            out.append(("initial_activation_rules", rule.rule_key, f"condition '{rule.condition}'"))
    return out


def apply_initial_activations(workspace: Any, slipnet: Any, meta: Any) -> None:
    """Put the concepts of ``initial_activation_rules`` fully active, in ``ordinal`` order."""
    max_act = slipnet.activation_params.max_activation
    roles = slipnet.roles
    for rule in meta.initial_activation_rules:
        node = _node(roles, rule.node_role)
        if node and _ACTIVATION_TESTS[rule.condition](workspace):
            node.activation = max_act


def add_initial_descriptions(workspace: Any, slipnet: Any, meta: Any) -> None:
    """Give every letter the descriptions of ``initial_description_rules``.

    Scheme: ``make-letter`` and ``init-mcat``.  The rules are applied to each letter in
    ``ordinal`` order, each description inserted at the front of the letter's list, and each
    descriptor made fully active when its rule says so (``run.ss:227-232`` activates *every*
    descriptor of every initial description, including ``plato-letter``).
    """
    from server.engine.descriptions import Description
    from server.engine.workspace_objects import Letter

    built_level = meta.vocabulary.proposal_level_built
    roles = slipnet.roles
    # From the Slipnet the descriptors belong to, not a second read of the parameter: the node
    # already carries the run's ceiling, and two reads of one value is how they come to disagree.
    max_act = slipnet.activation_params.max_activation

    # Resolve each rule once: (description type, fixed descriptor or None for the letter's
    # own category, test, whether to activate).  A rule with an unbound role is dropped.
    resolved: list[tuple[Any, Any, Callable[[Any, int], bool], bool, bool]] = []
    for rule in meta.initial_description_rules:
        if rule.subject != "letter":
            continue
        dimension = _node(roles, rule.dimension_role)
        if not dimension:
            continue
        if rule.descriptor_source == SOURCE_LETTER_CATEGORY:
            descriptor = None
        else:
            descriptor = _node(roles, rule.descriptor_role)
            if not descriptor:
                continue
        resolved.append((dimension, descriptor, _DESCRIPTION_TESTS[rule.condition],
                         rule.activate_descriptor, rule.built))

    for ws_string in workspace.all_strings:
        letters = [o for o in ws_string.objects if isinstance(o, Letter)]
        n = len(letters)
        for letter in letters:
            for dimension, fixed, test, activate, built in resolved:
                descriptor = fixed if fixed is not None else letter.letter_category
                if not descriptor or not test(letter, n):
                    continue
                desc = Description(letter, dimension, descriptor)
                if built:
                    desc.proposal_level = built_level
                letter.descriptions.insert(0, desc)
                if activate:
                    descriptor.activation = max_act


def _plan(slipnet: Any, meta: Any, subject: str) -> list[tuple[Any, ...]]:
    """The rules of *subject* resolved against this Slipnet's roles, once per Slipnet: ``(dimension
    node, source, fixed descriptor node or None, test, built, bond_description)`` in ``ordinal``
    order.  A rule whose dimension, or fixed descriptor, no node holds is dropped."""
    cache = slipnet.__dict__.setdefault("_description_plans", {})
    key = (subject, id(meta.initial_description_rules))
    plan = cache.get(key)
    if plan is None:
        plan = []
        roles = slipnet.roles
        tests = _GROUP_TESTS if subject == "group" else None
        for rule in meta.initial_description_rules:
            if rule.subject != subject:
                continue
            dimension = _node(roles, rule.dimension_role)
            if not dimension:
                continue
            fixed = None
            if rule.descriptor_source == SOURCE_ROLE:
                fixed = _node(roles, rule.descriptor_role)
                if not fixed:
                    continue
            test = tests[rule.condition] if tests is not None else None
            plan.append((dimension, rule.descriptor_source, fixed, test, rule.built, rule.bond_description))
        cache[key] = plan
    return plan


def describe_group(group: Any, slipnet: Any, meta: Any) -> None:
    """Give a new group its first descriptions: the ``group`` rules of ``initial_description_rules``.

    Scheme: ``make-group`` (``groups.ss:20-54``).  Each description goes to the front of the
    group's descriptions, or of its bond descriptions when the rule says so.  A dimension or a
    descriptor nothing holds describes nothing.
    """
    from server.engine.descriptions import Description

    built_level = meta.vocabulary.proposal_level_built
    for dimension, source, fixed, test, built, bond_description in _plan(slipnet, meta, "group"):
        if not test(group):
            continue
        if source == SOURCE_ROLE:
            descriptor = fixed
        elif source == "group_category":
            descriptor = group.group_category
        elif source == "bond_category":
            descriptor = group.bond_category
        elif source == "direction":
            descriptor = group.direction
        elif source == "bond_facet":
            descriptor = group.bond_facet
        elif source == "initial_letter_category":
            descriptor = group._get_initial_letter_category()
        else:
            continue
        if descriptor is None or not descriptor:
            continue
        desc = Description(group, dimension, descriptor)
        if built:
            desc.proposal_level = built_level
        if bond_description:
            group.bond_descriptions.insert(0, desc)
        else:
            group.descriptions.insert(0, desc)


def describe_translated_letters(string: Any, slipnet: Any, meta: Any) -> None:
    """Give the letters of a string built after the start (a translated string) the descriptions
    ``init_mcat`` gives, from the ``translated_letter`` rules.  A letter that already has a description
    of the rule's type is left alone.  Scheme: ``make-letter`` (``workspace-objects.ss:24-25``)."""
    from server.engine.descriptions import Description

    built_level = meta.vocabulary.proposal_level_built
    plan = _plan(slipnet, meta, "translated_letter")
    for letter in string.letters:
        for dimension, source, fixed, _test, built, _bond in plan:
            if letter.description_type_present(dimension):
                continue
            descriptor = fixed if source == SOURCE_ROLE else letter.letter_category
            if descriptor is None or not descriptor:
                continue
            desc = Description(letter, dimension, descriptor)
            if built:
                desc.proposal_level = built_level
            letter.add_description(desc)
