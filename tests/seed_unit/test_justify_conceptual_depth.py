"""`justify._get_conceptual_depth` and the retention loop for a name no node holds.

A name no node holds, or ``None``, is no node, and the engine's Null Object gives it its
depth (``Absent.conceptual_depth``, 0): its retention probability is 0 and a pattern entry
naming it is dropped, not raised on.  Unreachable under the Metacat Standard Configuration
(lockstep proves Metacat Mode unchanged); this pins the behaviour for any other configuration.
"""

import os

import pytest

from server.engine import justify
from server.engine.metadata import MetadataProvider
from server.engine.rng import RNG
from server.engine.roles import Absent
from server.engine.slipnet import Slipnet

SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")
NO_SUCH_NODE = "plato-no-such-node"


@pytest.fixture
def meta():
    return MetadataProvider.from_standard_configuration(SEED_DIR)


@pytest.fixture
def slipnet(meta):
    return Slipnet.from_metadata(meta)


def test_a_name_no_node_holds_has_the_absent_depth(slipnet):
    assert justify._get_conceptual_depth(NO_SUCH_NODE, slipnet) == Absent.conceptual_depth == 0


def test_none_has_the_absent_depth(slipnet):
    assert justify._get_conceptual_depth(None, slipnet) == Absent.conceptual_depth


def test_a_node_name_and_a_node_object_have_the_nodes_depth(slipnet):
    node = slipnet.nodes["plato-a"]
    assert justify._get_conceptual_depth("plato-a", slipnet) == node.conceptual_depth == 10
    assert justify._get_conceptual_depth(node, slipnet) == 10


def test_retention_probability_of_a_name_no_node_holds_is_zero(slipnet):
    entry = (NO_SUCH_NODE, "identity")
    assert justify._retention_probability(entry, [entry], slipnet, 50) == 0.0


def test_the_retention_loop_drops_an_entry_naming_no_node(slipnet, meta):
    string_position = slipnet.roles.dimension_string_position.name
    unknown = (NO_SUCH_NODE, "identity")
    pattern = ["vertical_bridge", (string_position, "opposite"), unknown]
    for seed in range(20):
        result = justify.get_vertical_theme_pattern_to_clamp(
            pattern, slipnet, rng=RNG(seed), meta=meta
        )
        assert NO_SUCH_NODE not in [e["dimension"] for e in result["entries"]]
        assert string_position in [e["dimension"] for e in result["entries"]]
