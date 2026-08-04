"""The Slipnet built from ``seed_data/`` — its nodes, its links and its dynamics."""

import os
import pytest
from server.engine.slipnet import Slipnet
from server.engine.metadata import MetadataProvider


SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")


@pytest.fixture
def meta():
    return MetadataProvider.from_seed_data(SEED_DIR)


@pytest.fixture
def slipnet(meta):
    return Slipnet.from_metadata(meta)


def test_slipnet_node_count(slipnet):
    assert len(slipnet.nodes) == 59


def test_node_properties(slipnet):
    node = slipnet.get_node("plato-a")
    assert node.short_name == "a"
    assert node.conceptual_depth == 10
    assert node.activation == 0.0


def test_successor_has_intrinsic_link_length(slipnet):
    succ = slipnet.get_node("plato-successor")
    assert succ.intrinsic_link_length == 60


def test_identity_has_intrinsic_link_length(slipnet):
    identity = slipnet.get_node("plato-identity")
    assert identity.intrinsic_link_length == 0


def test_node_links_populated(slipnet):
    """Letters should have category links to letter-category."""
    a = slipnet.get_node("plato-a")
    cat_links = a.category_links
    assert len(cat_links) > 0
    assert any(lk.to_node.name == "plato-letter-category" for lk in cat_links)


def test_letter_successor_links(slipnet):
    """plato-a should have a lateral successor link to plato-b."""
    a = slipnet.get_node("plato-a")
    succ_links = [
        lk for lk in a.lateral_links
        if lk.to_node.name == "plato-b" and lk.label_node and lk.label_node.name == "plato-successor"
    ]
    assert len(succ_links) == 1


def test_opposite_sliplinks(slipnet):
    """leftmost should have a lateral-sliplink to rightmost labeled opposite."""
    lm = slipnet.get_node("plato-leftmost")
    opp_links = [
        lk for lk in lm.lateral_sliplinks
        if lk.to_node.name == "plato-rightmost"
    ]
    assert len(opp_links) == 1
    assert opp_links[0].label_node.name == "plato-opposite"


def test_clamp_freezes_node_at_full_activation(slipnet):
    node = slipnet.get_node("plato-a")
    node.clamp(5)
    assert node.frozen
    assert node.activation == 100.0
    assert node.clamp_cycles_remaining == 5


def test_clamp_expires_after_its_cycles(slipnet):
    node = slipnet.get_node("plato-a")
    node.clamp(5)
    for _ in range(5):
        node.tick_clamp()
    assert not node.frozen
    assert node.clamp_cycles_remaining == 0


def test_spread_activation(slipnet):
    """Activating a node should spread some activation to neighbors."""
    succ = slipnet.get_node("plato-successor")
    succ.activation = 100.0
    slipnet.spread_activation(15)
    # Bond-category should get some activation (succ has category link to it)
    bc = slipnet.get_node("plato-bond-category")
    assert bc.activation > 0


def test_clamp_initially_relevant(slipnet, meta):
    slipnet.clamp_initially_relevant(meta)
    lc = slipnet.get_node("plato-letter-category")
    sp = slipnet.get_node("plato-string-position-category")
    assert lc.frozen
    assert sp.frozen
    assert lc.activation == 100.0


def test_reset_clears_node_activation(slipnet):
    slipnet.get_node("plato-a").activation = 50
    slipnet.reset_activations()
    assert slipnet.get_node("plato-a").activation == 0


def test_reset_releases_clamped_node(slipnet):
    slipnet.get_node("plato-b").clamp(10)
    slipnet.reset_activations()
    assert not slipnet.get_node("plato-b").frozen


def test_partially_active_node_does_not_spread_at_high_threshold(slipnet):
    """A node at 50 activation must not spread when the threshold is 100."""
    succ = slipnet.get_node("plato-successor")
    succ.activation = 50.0
    bc = slipnet.get_node("plato-bond-category")
    bc.activation = 0.0
    slipnet.spread_activation(15, threshold=100)
    # succ is below threshold, so bond-category receives no spread from it.
    assert bc.activation == 0.0


def test_partially_active_node_spreads_at_zero_threshold(slipnet):
    """The same node at 50 activation spreads once the threshold drops to 0."""
    succ = slipnet.get_node("plato-successor")
    succ.activation = 50.0
    bc = slipnet.get_node("plato-bond-category")
    bc.activation = 0.0
    slipnet.spread_activation(15, threshold=0)
    assert bc.activation > 0.0


# ---------------------------------------------------------------------------
#  The shipped descriptor predicates
#
#  ``slipnet_nodes.json`` carries each node's ``descriptor_predicate`` as a small
#  expression, compiled at startup — the same arrangement as a codelet's
#  ``execute_body``.  What is checked here is that the *shipped* expression asks
#  the reference's question, since a predicate that compiles and answers plausibly
#  is exactly the kind of divergence nothing else catches.
# ---------------------------------------------------------------------------

from server.engine.workspace_objects import WorkspaceObject


class _String:
    """The surface the neighbour walk reads: letters positionally, groups by edge."""

    def __init__(self, length):
        self.length = length
        self.letters = []
        self.groups = []
        self.objects = []


def _string_with_letters(length):
    string = _String(length)
    string.letters = [
        WorkspaceObject(string=string, left_pos=i, right_pos=i) for i in range(length)
    ]
    string.objects = list(string.letters)
    return string


def _group_over(string, left, right):
    members = string.letters[left : right + 1]
    group = WorkspaceObject(string=string, left_pos=left, right_pos=right)
    group.objects = members
    group.nested_member = lambda other, _m=members: other in _m
    for member in members:
        member.enclosing_group = group
    string.groups.append(group)
    string.objects.append(group)
    return group


def test_shipped_middle_predicate_is_the_group_aware_one(slipnet):
    """``plato-middle`` must reach ``middle-in-string?``, not index arithmetic.

    Scheme: ``slipnet.ss:587-589`` delegates straight to
    ``middle-in-string?`` (``workspace-objects.ss:364-370``), whose subject is an
    object's *ungrouped* neighbours.  So in ``mrrjjj`` read as ``[m][rr][jjj]``
    the ``[rr]`` group is middle — which is what gives the ``b→[rr]`` vertical
    bridge its distinguishing ``middle⇒middle`` concept-mapping.
    """
    middle = slipnet.get_node("plato-middle")
    string = _string_with_letters(6)
    rr = _group_over(string, 1, 2)
    jjj = _group_over(string, 3, 5)

    assert middle.describes(rr) is True
    assert middle.describes(jjj) is False
    assert middle.describes(string.letters[0]) is False


def test_shipped_middle_predicate_says_no_to_the_centre_of_five(slipnet):
    """``middle-in-string?`` wants the neighbours to *be* the edges.

    ``c`` in ``abcde`` has ungrouped neighbours ``b`` and ``d``, neither of which
    is an edge object, so the reference answers no.  Metacat's "middle" is
    *flanked by the ends*, not *at the centre*.
    """
    middle = slipnet.get_node("plato-middle")
    string = _string_with_letters(5)
    assert middle.describes(string.letters[2]) is False


def test_shipped_middle_predicate_says_yes_to_the_centre_of_three(slipnet):
    middle = slipnet.get_node("plato-middle")
    string = _string_with_letters(3)
    assert middle.describes(string.letters[1]) is True


def test_shipped_leftmost_and_rightmost_predicates_exclude_a_spanning_group(slipnet):
    """``slipnet.ss:577-585`` guards both with ``(not (string-spanning-group? …))``.

    A group covering the whole string is ``whole``, and must not also answer to
    ``leftmost`` merely because it starts at position 0.
    """
    leftmost = slipnet.get_node("plato-leftmost")
    rightmost = slipnet.get_node("plato-rightmost")
    string = _string_with_letters(3)
    whole = _group_over(string, 0, 2)

    assert leftmost.describes(whole) is False
    assert rightmost.describes(whole) is False
    assert leftmost.describes(string.letters[0]) is True
    assert rightmost.describes(string.letters[2]) is True


# ---------------------------------------------------------------------------
#  The property-link gate, at the association Petacat actually ships
#
#  Two property links exist in ``slipnet_links.json``: ``a→alphabetic-first`` and
#  ``z→alphabetic-last``, both fixed length 75 and so association 25.  The gate
#  in ``get-similar-property-links`` (slipnet.ss:108-112) is
#  ``temp-adjusted-probability`` of that, so the rate at which ``first`` and
#  ``last`` enter the Workspace rises with confusion and falls as the run cools —
#  0.25 at temperature 0, 0.325 at 100.
# ---------------------------------------------------------------------------

from server.engine.formulas import temp_adjusted_probability


class _Recorder:
    """Records the probabilities asked of it; always says yes."""

    def __init__(self):
        self.asked = []

    def prob(self, p):
        self.asked.append(p)
        return True


def test_shipped_property_links_are_association_25(slipnet):
    a = slipnet.get_node("plato-a")
    z = slipnet.get_node("plato-z")
    assert [lk.to_node.name for lk in a.property_links] == ["plato-alphabetic-first"]
    assert [lk.to_node.name for lk in z.property_links] == ["plato-alphabetic-last"]
    assert a.property_links[0].degree_of_association() == 25.0
    assert z.property_links[0].degree_of_association() == 25.0


@pytest.mark.parametrize("temperature, expected", [(0, 0.25), (100, 0.325)])
def test_property_link_gate_is_temperature_adjusted(slipnet, meta, temperature, expected):
    a = slipnet.get_node("plato-a")
    rng = _Recorder()
    a.get_similar_property_links(rng, temperature, meta)
    assert rng.asked == [expected]
    assert rng.asked == [temp_adjusted_probability(0.25, temperature, meta)]


def test_property_link_gate_loosens_as_the_run_gets_confused(slipnet, meta):
    """The whole point of the temperature adjustment: a confused run follows the
    link more readily than a settled one, so ``first``/``last`` are explored when
    exploration is what is wanted."""
    a = slipnet.get_node("plato-a")
    probabilities = []
    for temperature in (0, 50, 100):
        rng = _Recorder()
        a.get_similar_property_links(rng, temperature, meta)
        probabilities.append(rng.asked[0])
    assert probabilities == sorted(probabilities)
    assert probabilities[0] < probabilities[-1]


def test_property_link_gate_without_a_temperature_uses_the_bare_association(slipnet):
    a = slipnet.get_node("plato-a")
    rng = _Recorder()
    a.get_similar_property_links(rng)
    assert rng.asked == [0.25]
