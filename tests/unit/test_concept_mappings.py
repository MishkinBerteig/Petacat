"""Unit tests for engine.concept_mappings.ConceptMapping.

The unit under test is a single ConceptMapping. Its collaborators (slipnet
nodes, links, workspace objects/strings) are faked, so each test drives one
path through the strength / slippability / relevance / distinguishing /
symmetry logic. No randomness is used.
"""

from server.engine.concept_mappings import ConceptMapping
from server.engine.slipnet import SlipnetNode

from tests.unit._fakes import FakeLink, FakeNode, FakeObject, FakeString


def _identity(descriptor=None, description_type=None):
    d = descriptor or FakeNode("plato-a", conceptual_depth=10.0)
    dt = description_type or FakeNode("plato-letter-category")
    return ConceptMapping(dt, d, dt, d)


def _labeled_slippage(*, degree, depth1, depth2, dt_name="plato-string-position-category"):
    """A labeled slippage leftmost->rightmost with a sliplink of given degree."""
    d1 = FakeNode("plato-leftmost", conceptual_depth=depth1)
    d2 = FakeNode("plato-rightmost", conceptual_depth=depth2)
    d1.lateral_sliplinks = [FakeLink(d2, degree=degree)]
    dt = FakeNode(dt_name)
    label = FakeNode("plato-opposite")
    return ConceptMapping(dt, d1, dt, d2, label=label)


# --- identity vs slippage --------------------------------------------------

def test_is_identity_true_when_descriptors_are_same_node():
    assert _identity().is_identity is True


def test_is_slippage_true_when_descriptors_differ():
    cm = _labeled_slippage(degree=70, depth1=40, depth2=40)
    assert cm.is_slippage is True


# --- strength --------------------------------------------------------------

def test_strength_identity_is_100():
    assert _identity().strength() == 100.0


def test_strength_labeled_slippage_scales_association_by_depth_bonus():
    cm = _labeled_slippage(degree=70, depth1=40, depth2=40)
    # depth = 40, bonus = 1 + (0.4)^2 = 1.16, 70 * 1.16 = 81.2 -> round 81
    assert cm.strength() == 81.0


def test_strength_labeled_slippage_capped_at_100():
    cm = _labeled_slippage(degree=90, depth1=100, depth2=100)
    # bonus = 1 + 1 = 2, 90 * 2 = 180 -> capped to 100
    assert cm.strength() == 100.0


def test_strength_unlabeled_slippage_is_5():
    d1 = FakeNode("plato-a", conceptual_depth=10.0)
    d2 = FakeNode("plato-b", conceptual_depth=10.0)
    dt = FakeNode("plato-letter-category")
    cm = ConceptMapping(dt, d1, dt, d2, label=None)
    assert cm.strength() == 5.0


# --- slippability ----------------------------------------------------------

def test_slippability_identity_is_100():
    assert _identity().slippability() == 100.0


def test_slippability_slippage_scales_association_by_depth_penalty():
    cm = _labeled_slippage(degree=70, depth1=40, depth2=40)
    # penalty = 1 - (0.4)^2 = 0.84, 70 * 0.84 = 58.8 -> round 59
    assert cm.slippability() == 59.0


# --- conceptual depth ------------------------------------------------------

def test_conceptual_depth_is_average_of_descriptor_depths():
    d1 = FakeNode("plato-a", conceptual_depth=10.0)
    d2 = FakeNode("plato-b", conceptual_depth=30.0)
    dt = FakeNode("plato-letter-category")
    cm = ConceptMapping(dt, d1, dt, d2, label=FakeNode("plato-successor"))
    assert cm.conceptual_depth == 20.0


# --- slipnet link discovery ------------------------------------------------

def test_link_found_via_lateral_sliplinks_for_non_letter_type():
    cm = _labeled_slippage(degree=55, depth1=20, depth2=20)
    assert cm.slipnet_link is not None
    assert cm.slipnet_link.degree_of_association() == 55.0


def test_link_searched_via_lateral_links_for_letter_category_type():
    d1 = FakeNode("plato-a")
    d2 = FakeNode("plato-b")
    d1.lateral_links = [FakeLink(d2, degree=42)]
    dt = FakeNode("plato-letter-category")
    cm = ConceptMapping(dt, d1, dt, d2, label=FakeNode("plato-successor"))
    assert cm.slipnet_link is not None
    assert cm.slipnet_link.degree_of_association() == 42.0


def test_link_is_none_for_identity_mapping():
    assert _identity().slipnet_link is None


# --- relevance -------------------------------------------------------------

def test_relevant_true_when_both_description_types_fully_active():
    dt1 = FakeNode("plato-letter-category", fully_active=True)
    dt2 = FakeNode("plato-letter-category", fully_active=True)
    cm = ConceptMapping(dt1, FakeNode("plato-a"), dt2, FakeNode("plato-a"))
    assert cm.relevant() is True


def test_relevant_false_when_one_description_type_inactive():
    dt1 = FakeNode("plato-letter-category", fully_active=True)
    dt2 = FakeNode("plato-letter-category", fully_active=False)
    cm = ConceptMapping(dt1, FakeNode("plato-a"), dt2, FakeNode("plato-a"))
    assert cm.relevant() is False


def _cm_with_types_at(activation: float) -> ConceptMapping:
    """A concept-mapping whose description types are *real* nodes at *activation*.

    ``FakeNode`` carries relevance as a boolean the test sets, which is right for
    the tests above — they are about ``relevant()``'s conjunction, not about
    where the line is drawn.  These two are about exactly where the line is
    drawn, so they need a node that computes it: ``relevant?``
    (concept-mappings.ss:107-109) asks ``fully-active?``, which is exact equality
    with %max-activation% (slipnet.ss:392-394), not the >= 50 threshold.
    """
    dt1 = SlipnetNode("plato-letter-category", "lettctgy", 20)
    dt2 = SlipnetNode("plato-letter-category", "lettctgy", 20)
    dt1.activation = activation
    dt2.activation = activation
    return ConceptMapping(dt1, FakeNode("plato-a"), dt2, FakeNode("plato-a"))


def test_relevant_false_when_description_types_are_at_99():
    assert _cm_with_types_at(99.0).relevant() is False


def test_relevant_true_when_description_types_are_at_100():
    assert _cm_with_types_at(100.0).relevant() is True


# --- distinguishing --------------------------------------------------------

def test_distinguishing_true_conservative_default_when_objects_missing():
    cm = _labeled_slippage(degree=70, depth1=40, depth2=40)
    # object1 / object2 default to None
    assert cm.distinguishing() is True


def test_distinguishing_false_for_identity_of_whole():
    whole = FakeNode("plato-whole")
    dt = FakeNode("plato-string-position-category")
    cm = ConceptMapping(
        dt, whole, dt, whole, object1=FakeObject(), object2=FakeObject()
    )
    assert cm.distinguishing() is False


def test_descriptor_not_distinguishing_for_generic_category_node():
    # plato-letter is a generic category => never distinguishing.
    obj = FakeObject(string=FakeString())
    assert ConceptMapping._descriptor_is_distinguishing(FakeNode("plato-letter"), obj) is False


def test_descriptor_distinguishing_true_when_no_string():
    obj = FakeObject(string=None)
    assert ConceptMapping._descriptor_is_distinguishing(FakeNode("plato-a"), obj) is True


def test_descriptor_not_distinguishing_when_all_siblings_share_it():
    descriptor = FakeNode("plato-a")
    string = FakeString()
    obj = FakeObject(string=string)
    sib = FakeObject(string=string)
    from server.engine.descriptions import Description
    sib.descriptions = [Description(sib, FakeNode("plato-letter-category"), descriptor)]
    string.letters = [obj, sib]
    assert ConceptMapping._descriptor_is_distinguishing(descriptor, obj) is False


def test_descriptor_distinguishing_when_a_sibling_differs():
    descriptor = FakeNode("plato-a")
    string = FakeString()
    obj = FakeObject(string=string)
    sib = FakeObject(string=string)
    from server.engine.descriptions import Description
    sib.descriptions = [Description(sib, FakeNode("plato-letter-category"), FakeNode("plato-z"))]
    string.letters = [obj, sib]
    assert ConceptMapping._descriptor_is_distinguishing(descriptor, obj) is True


# --- symmetry --------------------------------------------------------------

def test_symmetric_mapping_of_identity_returns_self():
    cm = _identity()
    assert cm.symmetric_mapping() is cm


def test_symmetric_mapping_of_slippage_swaps_descriptors():
    cm = _labeled_slippage(degree=70, depth1=40, depth2=40)
    sym = cm.symmetric_mapping()
    assert sym.descriptor1 is cm.descriptor2
    assert sym.descriptor2 is cm.descriptor1


def test_is_symmetric_true_for_reversed_mapping():
    cm = _labeled_slippage(degree=70, depth1=40, depth2=40)
    assert cm.is_symmetric(cm.symmetric_mapping()) is True


# --- opposite mapping ------------------------------------------------------

def test_opposite_mapping_true_when_label_is_opposite():
    cm = _labeled_slippage(degree=70, depth1=40, depth2=40)  # label = plato-opposite
    assert cm.opposite_mapping is True


def test_opposite_mapping_true_for_whole_to_single():
    dt = FakeNode("plato-string-position-category")
    cm = ConceptMapping(dt, FakeNode("plato-whole"), dt, FakeNode("plato-single"))
    assert cm.opposite_mapping is True


def test_opposite_mapping_false_for_plain_slippage():
    d1 = FakeNode("plato-a")
    d2 = FakeNode("plato-b")
    dt = FakeNode("plato-letter-category")
    cm = ConceptMapping(dt, d1, dt, d2, label=FakeNode("plato-successor"))
    assert cm.opposite_mapping is False


# --- bond concept mapping --------------------------------------------------

def test_bond_concept_mapping_true_for_bond_category_type():
    dt = FakeNode("plato-bond-category")
    cm = ConceptMapping(dt, FakeNode("plato-sameness"), dt, FakeNode("plato-sameness"))
    assert cm.bond_concept_mapping is True


def test_bond_concept_mapping_false_for_letter_category_type():
    assert _identity().bond_concept_mapping is False


# --- activation side effects ----------------------------------------------

def test_activate_descriptions_sets_all_four_nodes_to_full():
    dt1 = FakeNode("plato-letter-category")
    d1 = FakeNode("plato-a")
    dt2 = FakeNode("plato-letter-category")
    d2 = FakeNode("plato-b")
    cm = ConceptMapping(dt1, d1, dt2, d2, label=FakeNode("plato-successor"))
    cm.activate_descriptions()
    # activate-from-workspace increments the buffer by 100; it is clipped when
    # the Slipnet flushes buffers at the next update cycle.
    assert dt1.activation_buffer == 100.0
    assert d1.activation_buffer == 100.0
    assert dt2.activation_buffer == 100.0
    assert d2.activation_buffer == 100.0


def test_activate_label_flushes_pending_activation_buffer():
    label = FakeNode("plato-successor", activation=0.0)
    label.activation_buffer = -30.0
    dt = FakeNode("plato-letter-category")
    cm = ConceptMapping(dt, FakeNode("plato-a"), dt, FakeNode("plato-b"), label=label)
    cm.activate_label()
    # +100 into the buffer joins the pending -30, then the flush applies 70.
    assert label.activation == 70.0
    assert label.activation_buffer == 0.0


# --- concept pattern -------------------------------------------------------

def test_concept_pattern_includes_label_when_present():
    cm = _labeled_slippage(degree=70, depth1=40, depth2=40)
    pattern = cm.get_concept_pattern()
    nodes = [node for node, _ in pattern]
    assert cm.label in nodes
    assert len(pattern) == 4


def test_concept_pattern_omits_label_when_absent():
    d1 = FakeNode("plato-a")
    d2 = FakeNode("plato-b")
    dt = FakeNode("plato-letter-category")
    cm = ConceptMapping(dt, d1, dt, d2, label=None)
    assert len(cm.get_concept_pattern()) == 3


# --- compatibility ---------------------------------------------------------

def test_compatible_when_same_type_maps_to_same_descriptor():
    dt = FakeNode("plato-letter-category")
    d = FakeNode("plato-a")
    cm1 = ConceptMapping(dt, d, dt, d)
    cm2 = ConceptMapping(dt, d, dt, d)
    assert cm1.is_compatible(cm2) is True


def test_incompatible_when_same_type_maps_to_different_descriptor():
    dt = FakeNode("plato-letter-category")
    cm1 = ConceptMapping(dt, FakeNode("plato-a"), FakeNode("plato-x"), FakeNode("plato-p"))
    cm2 = ConceptMapping(dt, FakeNode("plato-b"), FakeNode("plato-y"), FakeNode("plato-q"))
    # Shared description_type1 (dt) but descriptor1 differs (a vs b) => conflict.
    assert cm1.is_compatible(cm2) is False
