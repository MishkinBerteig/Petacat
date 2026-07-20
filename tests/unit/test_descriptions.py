"""Unit tests for engine.descriptions.Description.

The unit under test is the ``Description`` structure. All collaborators
(slipnet nodes, the owning workspace object, the string, sibling objects)
are replaced with deterministic fakes from ``_fakes`` so each test exercises
exactly one path through the strength / relevance / distinguishing logic.

No randomness is involved anywhere in this module, so determinism is
guaranteed by construction.
"""

from server.engine.descriptions import Description

from tests.unit._fakes import (
    FakeContainer,
    FakeNode,
    FakeObject,
    FakeString,
)


def _description(descriptor_depth=0.0, type_activation=0.0, obj=None, dtype=None, descriptor=None):
    dtype = dtype or FakeNode("plato-letter-category", activation=type_activation)
    descriptor = descriptor or FakeNode("plato-a", conceptual_depth=descriptor_depth)
    obj = obj if obj is not None else FakeObject()
    return Description(obj, dtype, descriptor)


# --- internal / external strength -----------------------------------------

def test_internal_strength_is_descriptor_conceptual_depth():
    d = _description(descriptor_depth=42.0)
    assert d.calculate_internal_strength() == 42.0


def test_external_strength_averages_local_support_and_type_activation():
    # Object with no string => local support is 0, isolating the average.
    obj = FakeObject(string=None)
    dtype = FakeNode("plato-letter-category", activation=80.0)
    descriptor = FakeNode("plato-a")
    d = Description(obj, dtype, descriptor)
    # (local_support=0 + activation=80) / 2
    assert d.calculate_external_strength() == 40.0


def test_descriptor_activation_property_reads_descriptor_node():
    descriptor = FakeNode("plato-a", activation=63.0)
    d = _description(descriptor=descriptor)
    assert d.descriptor_activation == 63.0


# --- local support: one path per branch of the count->value mapping --------

def test_local_support_zero_when_object_has_no_string():
    d = _description(obj=FakeObject(string=None))
    assert d.calculate_local_support() == 0.0


def test_local_support_zero_with_no_matching_siblings():
    dtype = FakeNode("plato-letter-category")
    string = FakeString()
    obj = FakeObject(string=string)
    string.objects = [obj]  # only self present
    d = Description(obj, dtype, FakeNode("plato-a"))
    assert d.calculate_local_support() == 0.0


def _string_with_matching_siblings(n, dtype):
    """Build a string whose *n* sibling objects each carry a description of dtype."""
    string = FakeString()
    obj = FakeObject(string=string)
    siblings = []
    for _ in range(n):
        sib = FakeObject(string=string)
        sib.descriptions = [Description(sib, dtype, FakeNode("plato-b"))]
        siblings.append(sib)
    string.objects = [obj, *siblings]
    return obj


def test_local_support_one_matching_sibling_maps_to_20():
    dtype = FakeNode("plato-letter-category")
    obj = _string_with_matching_siblings(1, dtype)
    d = Description(obj, dtype, FakeNode("plato-a"))
    assert d.calculate_local_support() == 20.0


def test_local_support_two_matching_siblings_maps_to_60():
    dtype = FakeNode("plato-letter-category")
    obj = _string_with_matching_siblings(2, dtype)
    d = Description(obj, dtype, FakeNode("plato-a"))
    assert d.calculate_local_support() == 60.0


def test_local_support_three_matching_siblings_maps_to_90():
    dtype = FakeNode("plato-letter-category")
    obj = _string_with_matching_siblings(3, dtype)
    d = Description(obj, dtype, FakeNode("plato-a"))
    assert d.calculate_local_support() == 90.0


def test_local_support_four_or_more_matching_siblings_maps_to_100():
    dtype = FakeNode("plato-letter-category")
    obj = _string_with_matching_siblings(4, dtype)
    d = Description(obj, dtype, FakeNode("plato-a"))
    assert d.calculate_local_support() == 100.0


def test_local_support_excludes_contained_objects():
    """A sibling that is contained by this object must not count as support."""
    dtype = FakeNode("plato-letter-category")
    string = FakeString()
    child = FakeObject(string=string)
    child.descriptions = [Description(child, dtype, FakeNode("plato-b"))]
    # The group under test contains the only other object in the string.
    group = FakeContainer(string=string, objects=[child])
    string.objects = [group, child]
    d = Description(group, dtype, FakeNode("plato-a"))
    assert d.calculate_local_support() == 0.0


# --- bond_description ------------------------------------------------------

def test_bond_description_true_for_bond_category_type():
    d = _description(dtype=FakeNode("plato-bond-category"))
    assert d.bond_description is True


def test_bond_description_false_for_letter_category_type():
    d = _description(dtype=FakeNode("plato-letter-category"))
    assert d.bond_description is False


# --- relevance -------------------------------------------------------------

def test_is_relevant_true_when_description_type_fully_active():
    d = _description(dtype=FakeNode("plato-letter-category", fully_active=True))
    assert d.is_relevant() is True


def test_is_relevant_false_when_description_type_not_fully_active():
    d = _description(dtype=FakeNode("plato-letter-category", fully_active=False))
    assert d.is_relevant() is False


# --- distinguishing --------------------------------------------------------

def test_is_distinguishing_true_when_object_has_no_string():
    d = _description(obj=FakeObject(string=None))
    assert d.is_distinguishing() is True


def test_is_distinguishing_true_when_string_has_single_object():
    string = FakeString()
    obj = FakeObject(string=string)
    string.objects = [obj]
    d = Description(obj, FakeNode("plato-letter-category"), FakeNode("plato-a"))
    assert d.is_distinguishing() is True


def test_is_distinguishing_false_when_all_siblings_share_descriptor():
    dtype = FakeNode("plato-letter-category")
    descriptor = FakeNode("plato-a")
    string = FakeString()
    obj = FakeObject(string=string)
    sib = FakeObject(string=string)
    sib.descriptions = [Description(sib, dtype, descriptor)]
    string.objects = [obj, sib]
    d = Description(obj, dtype, descriptor)
    assert d.is_distinguishing() is False


def test_is_distinguishing_true_when_a_sibling_differs():
    dtype = FakeNode("plato-letter-category")
    descriptor = FakeNode("plato-a")
    string = FakeString()
    obj = FakeObject(string=string)
    sib = FakeObject(string=string)
    sib.descriptions = [Description(sib, dtype, FakeNode("plato-z"))]
    string.objects = [obj, sib]
    d = Description(obj, dtype, descriptor)
    assert d.is_distinguishing() is True


# --- identity / equality ---------------------------------------------------

def test_equal_when_type_descriptor_and_object_match():
    obj = FakeObject()
    dtype = FakeNode("plato-letter-category")
    descriptor = FakeNode("plato-a")
    assert Description(obj, dtype, descriptor) == Description(obj, dtype, descriptor)


def test_not_equal_when_descriptor_differs():
    obj = FakeObject()
    dtype = FakeNode("plato-letter-category")
    d1 = Description(obj, dtype, FakeNode("plato-a"))
    d2 = Description(obj, dtype, FakeNode("plato-b"))
    assert d1 != d2


def test_hash_matches_for_equal_descriptions():
    obj = FakeObject()
    dtype = FakeNode("plato-letter-category")
    descriptor = FakeNode("plato-a")
    assert hash(Description(obj, dtype, descriptor)) == hash(
        Description(obj, dtype, descriptor)
    )
