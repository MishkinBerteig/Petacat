"""Phase G: the Slipnet's link lengths must match the reference Scheme.

Link length determines degree-of-association, which scales both activation
spreading and slippage probability, so losing the tuned lengths distorts the
whole network.  The seed data previously carried no lengths at all: every link
fell through to ``SlipnetLink.link_length()``'s default of 50.
"""

import json
import os

import pytest

from server.engine.metadata import MetadataProvider
from server.engine.slipnet import Slipnet

SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")


@pytest.fixture(scope="module")
def links():
    with open(os.path.join(SEED_DIR, "slipnet_links.json")) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def slipnet():
    return Slipnet.from_metadata(MetadataProvider.from_seed_data(SEED_DIR))


def test_link_count_matches_the_scheme(links):
    """202 links, not the 226 the docs used to claim."""
    assert len(links) == 202


def test_every_link_is_either_fixed_length_or_labelled(links):
    """A link with neither a length nor a label has no defined association.

    In the Scheme, ``set-link-length`` also sets ``fixed-length? #t``, so a link
    is fixed-length exactly when it was declared with ``length:``; the rest carry
    a ``label:`` and take their length from the label node.
    """
    for lk in links:
        assert lk["fixed_length"] or lk["label_node"], (
            f"{lk['from_node']} -> {lk['to_node']} has no length and no label, "
            f"so it would silently fall back to the default of 50"
        )


def test_no_link_uses_the_default_fallback_length(slipnet):
    """Every link resolves to a real length, never the 50 fallback."""
    for node in slipnet.nodes.values():
        for link in node.outgoing_links:
            if link.fixed_length:
                continue
            assert link.label_node is not None
            assert link.label_node.intrinsic_link_length is not None, (
                f"{link} is dynamic but its label has no intrinsic link length"
            )


@pytest.mark.parametrize(
    "from_node,to_node,expected",
    [
        # instance-link* letter-category --> (a..z) all-lengths: 97
        ("plato-letter-category", "plato-a", 97),
        # category-link* a --> letter-category, computed as depth difference
        ("plato-a", "plato-letter-category", 20),
        # instance-link* string-position-category --> leftmost length: 100
        ("plato-string-position-category", "plato-leftmost", 100),
        # property-link* a --> alphabetic-first length: 75
        ("plato-a", "plato-alphabetic-first", 75),
        # lateral-link* alphabetic-first <--> leftmost length: 100
        ("plato-alphabetic-first", "plato-leftmost", 100),
        # The four §3.5 links: fixed lengths *and* labels.
        ("plato-leftmost", "plato-left", 90),
        ("plato-rightmost", "plato-right", 90),
        ("plato-leftmost", "plato-right", 100),
        ("plato-rightmost", "plato-left", 100),
        # instance-link* length --> (one..five) all-lengths: 100
        ("plato-length", "plato-one", 100),
        # lateral-sliplink* letter-category <--> length length: 95
        ("plato-letter-category", "plato-length", 95),
    ],
)
def test_specific_link_lengths_match_the_scheme(slipnet, from_node, to_node, expected):
    node = slipnet.nodes[from_node]
    link = next(l for l in node.outgoing_links if l.to_node.name == to_node)
    assert link.link_length() == expected


def test_letter_successor_links_take_their_length_from_the_label(slipnet):
    """a -> b is declared with ``label: successor`` only, so it is dynamic.

    plato-successor's intrinsic link length is 60, giving a degree of
    association of 40 while the label is not fully active.
    """
    node = slipnet.nodes["plato-a"]
    link = next(l for l in node.lateral_links if l.to_node.name == "plato-b")
    assert not link.fixed_length
    assert link.label_node.name == "plato-successor"
    assert link.link_length() == 60
    assert link.intrinsic_degree_of_association() == 40


def test_the_four_new_metacat_link_labels_are_present(slipnet):
    """§3.5 / Fig. 3.17: Metacat labels four links Copycat left unlabelled."""
    expected = {
        ("plato-leftmost", "plato-left"): "plato-identity",
        ("plato-rightmost", "plato-right"): "plato-identity",
        ("plato-leftmost", "plato-right"): "plato-opposite",
        ("plato-rightmost", "plato-left"): "plato-opposite",
    }
    for (src, dst), label in expected.items():
        link = next(
            l for l in slipnet.nodes[src].outgoing_links if l.to_node.name == dst
        )
        assert link.label_node is not None and link.label_node.name == label
