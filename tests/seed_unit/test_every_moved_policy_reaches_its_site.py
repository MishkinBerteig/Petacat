"""Stage 6: every policy that moved into the configuration is read by the site that decided it (ruling 9).

``seed_data/roles.json`` binds ten ordered roles that are sets of dimensions or categories (``dimension.ladder``,
``dimension.reverses_together``, ``dimension.bond_description``, ``dimension.freely_mappable``,
``group_category.directed``, ``rule.object_naming_dimension``, ``rule.letter_or_alphabetic_dimension``,
``rule.relation_only_dimension``, ``rule.apply_first``, ``rule.apply_by_length``), the descriptors that never
distinguish (``descriptor.generic``), and the six ``image_operation.*`` roles that say which dimension performs
which image operation.  For every member of every one of them, dropping the binding from the configuration (the node
stays) must change something.  A row is either

* ``run``: a real run in which the site is reached differs from the standard run (found with
  ``agents-workspace/metacat-cleanup/round2/S6-policy/work/mutate_policy.py``); or
* ``direct``: the site is called on its own, because no demo problem at seeds 1-3 reaches it.

The seed binds each role to what the engine's code used to name (``tests/support/role_table.py``).
"""

from __future__ import annotations

import dataclasses
import os
from types import SimpleNamespace

import pytest

from server.engine.metadata import MetadataProvider
from server.engine.slipnet import Slipnet
from tests.support.role_table import ORDERED_ROLES, SINGLE_ROLES
from tests.support.run_fingerprint import fingerprint

pytestmark = pytest.mark.numeric_matrix

SEED = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")

#: (role, node) -> (problem, seed, answer): a run in which dropping the binding changes the run.
RUNS = {
    ("dimension.ladder", "plato-letter-category"): (("abc", "abd", "xyz"), 1, None),
    ("dimension.ladder", "plato-length"): (("abc", "abd", "xyz"), 2, None),
    ("dimension.reverses_together", "plato-direction-category"): (("abc", "abd", "xyz"), 2, None),
    ("dimension.reverses_together", "plato-group-category"): (("abc", "cba", "mrrjjj"), 1, None),
    ("dimension.bond_description", "plato-bond-category"): (("abc", "abd", "xyz"), 2, None),
    ("dimension.bond_description", "plato-bond-facet"): (("abc", "abd", "mrrjjj"), 2, "mrrjjjj"),
    ("dimension.freely_mappable", "plato-string-position-category"): (("abc", "abd", "glz"), 2, None),
    ("dimension.freely_mappable", "plato-length"): (("abc", "aabbcc", "kkjjii"), 1, None),
    ("bond_category.symmetric", "plato-sameness"): (("abc", "abd", "mrrjjj"), 1, None),
    ("group_category.directed", "plato-succgrp"): (("zyx", "xyy", "z"), 1, None),
    ("group_category.directed", "plato-predgrp"): (("eqe", "qeq", "abbbc"), 2, "aaabccc"),
    ("rule.object_naming_dimension", "plato-string-position-category"): (("abc", "abd", "xyz"), 1, None),
    ("rule.object_naming_dimension", "plato-alphabetic-position-category"): (("abc", "aabbcc", "kkjjii"), 1, None),
    ("rule.letter_or_alphabetic_dimension", "plato-letter-category"): (("aabb", "cc", "aabb"), 1, None),
    ("rule.letter_or_alphabetic_dimension", "plato-alphabetic-position-category"): (("a", "z", "abc"), 2, None),
    ("image_operation.new_alpha_position_category", "plato-alphabetic-position-category"): (
        ("a", "z", "abc"), 2, None),
    ("rule.relation_only_dimension", "plato-direction-category"): (("abc", "cba", "mrrjjj"), 1, None),
    ("rule.relation_only_dimension", "plato-group-category"): (("zyx", "xyy", "z"), 2, None),
    ("rule.apply_by_length", "plato-length"): (("zyx", "xyy", "z"), 2, None),
    ("descriptor.generic", "plato-letter"): (("a", "b", "z"), 1, None),
    ("descriptor.generic", "plato-group"): (("abc", "abd", "xyz"), 1, None),
    ("image_operation.letter_or_group", "plato-object-category"): (("aabc", "aabd", "ijkk"), 1, None),
    ("image_operation.new_start_letter", "plato-letter-category"): (("abc", "abd", "xyz"), 1, None),
    ("image_operation.new_length", "plato-length"): (("abc", "aabbcc", "kkjjii"), 1, None),
    ("image_operation.reverse_direction", "plato-direction-category"): (("abc", "cba", "mrrjjj"), 1, None),
    ("image_operation.reverse_medium", "plato-group-category"): (("zyx", "xyy", "z"), 2, None),
}

#: The two members no problem reaches, checked by calling the site (below).  Searched: the 41 demo
#: problems at seeds 1-3 and the 158 problems of ``tests/lockstep/data/*.txt`` at seeds 1-2 (workspace
#: ``S6-policy/work/search_sites2.log``): dropping either changes none of those runs, and the Scheme says why.
#:
#: * ``dimension.reverses_together`` / bond category: a group's group category is derived from its bond
#:   category one to one (``groups.ss:79``, successor <-> succgrp, predecessor <-> predgrp, sameness <->
#:   samegrp), so a bridge between two groups always carries a group-category mapping that is opposite
#:   exactly when the bond-category mapping is; ``reversible-CM-type?`` (``concept-mappings.ss:84-87``) is
#:   asked of all the mappings at once (``andmap`` of ``opposite-mapping?``), so the bond-category member
#:   never changes its answer.
#: * ``rule.apply_first`` / group category: in the rule's transform list the group-category transform comes
#:   after at most the direction transform (``rule.dimension_order``), and ``reverse_direction`` and
#:   ``reverse_medium`` act on different parts of an image, so applying them in either order gives one image.
DIRECT = (
    ("dimension.reverses_together", "plato-bond-category"),
    ("rule.apply_first", "plato-group-category"),
)

#: Every member of the roles of this stage that the seed binds (the two tables above must cover them).
STAGE_ROLES = (
    "dimension.ladder", "dimension.reverses_together", "dimension.bond_description",
    "dimension.freely_mappable", "bond_category.symmetric", "group_category.directed", "rule.object_naming_dimension",
    "rule.letter_or_alphabetic_dimension", "rule.relation_only_dimension", "descriptor.generic",
    "rule.apply_first", "rule.apply_by_length",
    "image_operation.letter_or_group", "image_operation.new_start_letter", "image_operation.new_length",
    "image_operation.reverse_direction", "image_operation.reverse_medium",
    "image_operation.new_alpha_position_category",
)


def _members(role):
    return ORDERED_ROLES[role] if role in ORDERED_ROLES else (SINGLE_ROLES[role],)


@pytest.fixture(scope="module")
def meta() -> MetadataProvider:
    return MetadataProvider.from_standard_configuration(SEED)


def dropped(meta, role, node):
    return dataclasses.replace(meta, node_roles=tuple(
        b for b in meta.node_roles if not (b.role == role and b.node_name == node)))


def test_every_member_of_every_role_is_a_row_here():
    covered = set(RUNS) | set(DIRECT)
    expected = {(role, node) for role in STAGE_ROLES for node in _members(role)}
    assert covered == expected


@pytest.mark.parametrize("role,node", sorted(RUNS))
def test_a_run_changes_when_a_member_is_dropped(meta, role, node):
    problem, seed, answer = RUNS[role, node]
    kw = dict(answer=answer, cap=3000)
    assert fingerprint(dropped(meta, role, node), problem, seed, **kw) != fingerprint(meta, problem, seed, **kw)


# ------------------------------------------------------------ the sites no run reaches, called directly


@pytest.fixture()
def slipnet(meta):
    return Slipnet.from_metadata(meta)


def test_a_bond_category_concept_mapping_reverses_together(meta):
    from server.engine.concept_mappings import ConceptMapping
    from tests.support.run_binding import rebind

    def reversible(m):
        rebind(m)
        s = Slipnet.from_metadata(m)
        node = s.nodes["plato-bond-category"]
        cm = ConceptMapping(node, s.nodes["plato-sameness"], node, s.nodes["plato-sameness"], None, None, None)
        return cm.reversible_cm_type

    assert reversible(meta) is True
    assert reversible(dropped(meta, "dimension.reverses_together", "plato-bond-category")) is False


def test_an_alphabetic_position_change_is_alphabetic(meta):
    from server.engine.rules import IntrinsicChangeDescription

    def alphabetic(m):
        s = Slipnet.from_metadata(m)
        change = IntrinsicChangeDescription.__new__(IntrinsicChangeDescription)
        change.dimension = s.nodes["plato-alphabetic-position-category"]
        return change.is_lettctgy_or_alphposctgy_dimension()

    assert alphabetic(meta) is True
    assert alphabetic(dropped(meta, "rule.letter_or_alphabetic_dimension", "plato-alphabetic-position-category")) is False


def test_a_group_category_transform_is_applied_first(meta):
    from server.engine.rules import _apply_before

    def first(m):
        s = Slipnet.from_metadata(m)
        gc, direction = s.nodes["plato-group-category"], s.nodes["plato-direction-category"]
        other = s.nodes["plato-right"]
        return _apply_before((gc, other), (direction, other), None, s)

    assert first(meta) is True
    assert first(dropped(meta, "rule.apply_first", "plato-group-category")) is False


def test_an_alphabetic_position_transform_runs_the_image_operation_of_that_name(meta):
    from server.engine.rules import _transform_image

    def called(m):
        s = Slipnet.from_metadata(m)
        calls = []
        image = SimpleNamespace(new_alpha_position_category=lambda arg: calls.append(arg))
        _transform_image(image, s.nodes["plato-alphabetic-position-category"], s.nodes["plato-alphabetic-first"], s)
        return calls

    assert len(called(meta)) == 1
    assert called(dropped(meta, "image_operation.new_alpha_position_category", "plato-alphabetic-position-category")) == []


def test_the_dispatch_is_bound_to_the_dimensions_not_to_their_names(meta):
    """Rebind ``image_operation.new_length`` to the letter-category node: that dimension now lengthens."""
    from server.engine.rules import _transform_image

    rebound = dataclasses.replace(meta, node_roles=tuple(
        dataclasses.replace(b, node_name="plato-letter-category") if b.role == "image_operation.new_length" else b
        for b in meta.node_roles if not (b.role == "image_operation.new_start_letter")))
    s = Slipnet.from_metadata(rebound)
    seen = []
    image = SimpleNamespace(new_length=lambda arg: seen.append("length"), new_start_letter=lambda arg: seen.append("letter"))
    _transform_image(image, s.nodes["plato-letter-category"], s.nodes["plato-one"], s)
    assert seen == ["length"]
