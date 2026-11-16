"""A ``1`` in a Training Mode Session's text is not ``plato-one`` (the user, 2026-11-15).

"1 in the text should not get matched to plato-one (or whatever it's called) because they are NOT the same thing":
the Slipnet's number nodes ``plato-one`` to ``plato-five`` are counts of things (more like singular, dual, triple,
quadruple and quintuple), not the numerals in text.  A symbol with no node of its own gets one made for it
(``plato-cp-0031`` for ``1``), nothing links a symbol node to a number node, and ``letter_node('1')`` is never a number
node, however long a session is taught.
"""

from __future__ import annotations

import pytest

from server.engine.runner import EngineRunner
from server.services import config_document as cd
from server.services import training_base as tb
from server.services.session_live_config import LiveConfiguration
from server.services.training_mode_session_executor import SessionTask, run_task
from server.services.training_mode_session_service import IN_WORKER_LEARNER, TrainingModeSessionService
from tests.support.noticing_configuration import every_noticing

pytestmark = pytest.mark.numeric_matrix

NUMBERS = ("plato-one", "plato-two", "plato-three", "plato-four", "plato-five")
ONE = "plato-cp-0031"


@pytest.fixture(scope="module")
def base():
    return cd.provider(tb.resolve_base().document)


def test_the_number_nodes_have_no_glyph_and_stand_for_counts(base):
    for name in NUMBERS:
        spec = base.slipnet_node_specs[name]
        assert spec.glyph is None and spec.numeric_value is not None, name
    assert [base.slipnet_node_specs[n].numeric_value for n in NUMBERS] == [1, 2, 3, 4, 5]


def test_the_symbol_1_is_perceived_through_its_own_node_and_letter_node_is_never_a_number_node(base):
    runner = EngineRunner(base)
    runner.init_mcat("1", "1", "1", None, seed=1)
    runner.run_mcat(max_steps=700)
    slipnet = runner.ctx.slipnet
    node = slipnet.alphabet.glyph_nodes["1"]
    assert node.name == ONE and node.numeric_value is None and node.name not in NUMBERS
    assert slipnet.alphabet.glyph_nodes["1"] is not slipnet.alphabet.number_for(1)
    assert slipnet.alphabet.number_for(1).name == "plato-one" and slipnet.alphabet.number_for(1).glyph is None
    # the Workspace describes each `1` by its own node, and no `1` by a number node as its letter category
    lc = slipnet.roles.dimension_letter_category
    workspace = runner.ctx.workspace
    ones = [o for s in workspace.aggregate_strings for o in s.objects if getattr(o, "left_string_pos", None) is not None
            and type(o).__name__ == "Letter"]
    assert ones and all(o.get_descriptor_for(lc) is node for o in ones)
    # no link of this run's Slipnet joins the symbol's node to a number node, in either direction
    assert not [l for l in node.outgoing_links + node.incoming_links if l.to_node.name in NUMBERS or l.from_node.name in NUMBERS]


def test_a_taught_session_never_links_a_symbol_node_to_a_number_node():
    document = every_noticing(tb.resolve_base().document)  # a taught session needs noticings
    config = LiveConfiguration(document, configuration_id=0, revision=0, episode_version=0)
    symbols = {"plato-cp-0031", "plato-cp-0032", "plato-cp-0033"}
    outcomes = []
    for run, seed in enumerate((1, 2, 3, 4, 5), 1):
        outcome = run_task(SessionTask("123", "123", "123", None, seed, 1500, None, "off"), cd.provider(config.document))
        assert not outcome.error
        outcomes.append(outcome)
        batch = TrainingModeSessionService._proposal_batch(outcome)
        config.finish_run(memory_merge=lambda: None, batch=batch, run=(run, seed), started_revision=0,
                          learner=IN_WORKER_LEARNER)
    assert config.diagnostics == []
    tables = config.document.tables
    assert symbols <= {k[0] for k in tables["slipnet_node_defs"]}  # the three symbols have nodes of their own
    links = tables["slipnet_link_defs"]
    joined = [k for k, row in links.items()
              if (row["from_node"] in symbols and row["to_node"] in NUMBERS)
              or (row["from_node"] in NUMBERS and row["to_node"] in symbols)]
    assert joined == []
    # and the session did learn links between the symbols themselves, so the test is not vacuous
    assert any(row["from_node"] in symbols and row["to_node"] in symbols for row in links.values())
    # no proposal of any run names a number node either
    assert not any(n in str(p) for o in outcomes for p in o.proposals for n in NUMBERS)
