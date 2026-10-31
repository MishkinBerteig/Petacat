"""The silent-fallback observer (EN0) sees what it claims to, and nothing else changes.

``tests/support/fallback_instrumentation.py`` counts handled exceptions by ``except`` clause
and lookups of absent Slipnet nodes by call site, from test code only.  Here it is pointed
at the three blanket ``except Exception`` blocks of ``justify.py`` and at a missing node,
without running a codelet.  The count over the whole baseline set is made by
``scripts/count_silent_fallbacks.py`` (expected zero at the blanket blocks).
"""

from __future__ import annotations

from pathlib import Path

from tests.support.fallback_instrumentation import Observation, blanket_sites

REPO_ROOT = Path(__file__).resolve().parents[2]
JUSTIFY = REPO_ROOT / "server" / "engine" / "justify.py"


def _slipnet():
    from server.engine.metadata import MetadataProvider
    from server.engine.slipnet import Slipnet

    return Slipnet.from_metadata(MetadataProvider.from_standard_configuration(str(REPO_ROOT / "seed_data")))


def test_justify_has_three_blanket_handlers() -> None:
    sites = blanket_sites(JUSTIFY)
    assert len(sites) == 3 and all(clause == "except Exception" for _, clause in sites)


def test_a_blanket_handler_hit_is_counted() -> None:
    from server.engine import justify

    with Observation() as obs:
        # a rule that is not a rule makes get_all_reference_objects raise inside the handler's try
        assert justify._reference_objects(object(), object(), object()) == []
    report = obs.report()
    hits = [h for h in report["handled_exceptions"] if h["site"].startswith("server/engine/justify.py")]
    assert len(hits) == 1 and hits[0]["blanket"] and hits[0]["hits"] == 1


def test_a_missing_node_lookup_is_counted_and_behaves_like_a_dict() -> None:
    with Observation() as obs:
        slipnet = _slipnet()
        assert slipnet.nodes.get("plato-a") is slipnet.nodes["plato-a"]
        assert slipnet.nodes.get("plato-no-such-node") is None
        assert slipnet.nodes.get("plato-no-such-node", 7) == 7
        assert "plato-a" in slipnet.nodes and len(slipnet.nodes) == 59
    missing = obs.report()["missing_node_lookups"]
    assert len(missing) == 2 and sum(m["hits"] for m in missing) == 2
    assert all(m["name"] == "plato-no-such-node" for m in missing)


def test_the_observer_leaves_no_trace_behind() -> None:
    import sys

    from server.engine.slipnet import Slipnet

    original = Slipnet.__dict__["from_metadata"]
    with Observation():
        assert Slipnet.__dict__["from_metadata"] is not original
    assert Slipnet.__dict__["from_metadata"] is original
    assert sys.monitoring.get_tool(sys.monitoring.PROFILER_ID) is None
    assert type(_slipnet().nodes) is dict
