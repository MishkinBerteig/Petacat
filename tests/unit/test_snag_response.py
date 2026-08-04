"""The snag response and the clamp machinery — ``answers.ss:1153-1193``, ``trace.ss``.

Every unit here isolates one piece of the response a snag triggers.  The
collaborators are hand-rolled: a Slipnet is a dict of nodes that can be clamped, a
Workspace is a list of structures, a Themespace is whatever the piece under test
actually reads.  What is real is the engine class being exercised.
"""

from __future__ import annotations

from typing import Any

from server.engine.bonds import Bond
from server.engine.temperature import Temperature
from server.engine.trace import (
    SNAG,
    ClampEvent,
    SnagEvent,
    TemporalTrace,
    get_associated_concept_pattern,
    get_snag_concept_pattern,
    get_snag_theme_pattern,
)
from server.engine.workspace_objects import WorkspaceObject


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeSlipnetNode:
    """Only the surface ``clamp_concept_pattern``/``unclamp_concept_pattern`` touch."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.activation = 0.0
        self.frozen = False
        self.clamp_cycles_remaining = 0

    def clamp(self, cycles: int = 0, activation: float = 100.0) -> None:
        self.frozen = True
        self.clamp_cycles_remaining = cycles
        self.activation = float(activation)

    def unclamp(self) -> None:
        self.frozen = False
        self.clamp_cycles_remaining = 0


class _FakeSlipnet:
    def __init__(self, *names: str) -> None:
        self.nodes = {name: _FakeSlipnetNode(name) for name in names}


class _FakeThemespace:
    """A Themespace with no clusters — every clamp over it is a no-op."""

    clusters: list = []

    def thematic_pressure_on(self, types: Any = None) -> None:
        pass

    def unclamp_all(self) -> None:
        pass


class _FakeStructure:
    """A workspace structure that is not a bond, carrying only a strength."""

    def __init__(self, strength: float) -> None:
        self.strength = strength


class _FakeWorkspace:
    def __init__(self, structures: list[Any]) -> None:
        self.all_structures = list(structures)


class _FakeDescription:
    def __init__(self, descriptor: Any) -> None:
        self.descriptor = descriptor


class _FakeConceptMapping:
    def __init__(self, dimension: str, label: Any) -> None:
        self.description_type1 = _FakeSlipnetNode(dimension)
        self.label = label


# ---------------------------------------------------------------------------
# CL-4 — a clamp activating during a snag period must release the temperature
# ---------------------------------------------------------------------------


def test_clamp_activation_unclamps_the_temperature():
    """``trace.ss:619`` -> ``trace.ss:188-196``: clamp activation calls
    ``undo-snag-condition``, which unconditionally clears ``*temperature-clamped?*``.

    Petacat's ``ClampEvent.activate`` did not forward the temperature to
    ``undo_snag_condition``, which then skipped the unclamp.  Once any jootser or
    justify clamp activated during a snag period, temperature stayed frozen for the
    rest of the run.
    """
    trace = TemporalTrace()
    slipnet = _FakeSlipnet()
    themespace = _FakeThemespace()
    temperature = Temperature()
    temperature.clamp(100.0)

    trace.add_snag_event(SnagEvent(codelet_count=10, temperature=100.0))
    assert trace.within_snag_period
    assert temperature.clamped

    clamp = ClampEvent(codelet_count=20, temperature=100.0)
    clamp.activate(trace, themespace, slipnet, None, temperature)

    assert not trace.within_snag_period
    assert not temperature.clamped


# ---------------------------------------------------------------------------
# SN-3 — snag activation
# ---------------------------------------------------------------------------


def test_a_snag_during_a_clamp_undoes_it_and_pins_the_impasse():
    """``trace.ss:1155-1162``: activation undoes the live clamp, clamps salience on
    every snag object, and clamps the snag concept pattern.

    Nothing called ``SnagEvent.activate`` at all, and the event was built with
    ``snag_concept_pattern=None``, so all three were dead.
    """
    trace = TemporalTrace()
    slipnet = _FakeSlipnet("plato-a", "plato-leftmost")
    themespace = _FakeThemespace()

    clamp = ClampEvent(codelet_count=5, temperature=50.0)
    trace.add_clamp_event(clamp)
    assert trace.within_clamp_period

    obj = WorkspaceObject(string=None, left_pos=0, right_pos=0)
    obj.descriptions = [
        _FakeDescription(_FakeSlipnetNode("plato-a")),
        _FakeDescription(_FakeSlipnetNode("plato-leftmost")),
    ]

    snag = SnagEvent(
        codelet_count=30,
        temperature=100.0,
        snag_objects=[obj],
        snag_concept_pattern=get_snag_concept_pattern([obj]),
    )
    trace.add_snag_event(snag)
    snag.activate(trace, themespace, slipnet, None, 30)

    # (a) the clamp period is over
    assert not trace.within_clamp_period
    # (b) the snag object is maximally salient
    assert obj.salience_clamped
    obj.update_intra_string_salience()
    assert obj.salience["intra"] == 100
    # (c) its descriptors are frozen at full activation
    assert slipnet.nodes["plato-a"].frozen
    assert slipnet.nodes["plato-a"].activation == 100.0
    assert slipnet.nodes["plato-leftmost"].frozen

    # And deactivation puts all of it back.
    snag.deactivate(slipnet)
    assert not obj.salience_clamped
    assert not slipnet.nodes["plato-a"].frozen


def test_the_snag_concept_pattern_is_the_snag_objects_descriptors():
    """``trace.ss:1042-1048`` — every descriptor of every snag object, at max."""
    obj = WorkspaceObject(string=None, left_pos=0, right_pos=0)
    obj.descriptions = [
        _FakeDescription(_FakeSlipnetNode("plato-z")),
        _FakeDescription(_FakeSlipnetNode("plato-rightmost")),
        _FakeDescription(_FakeSlipnetNode("plato-z")),  # duplicate, collapsed
    ]
    pattern = get_snag_concept_pattern([obj])
    assert pattern["type"] == "concepts"
    assert pattern["entries"] == [
        {"node": "plato-z", "activation": 100.0},
        {"node": "plato-rightmost", "activation": 100.0},
    ]


# ---------------------------------------------------------------------------
# SN-4 — the snag theme pattern comes from the failed mapping's concept-mappings
# ---------------------------------------------------------------------------


def test_the_snag_theme_pattern_is_derived_from_concept_mappings():
    """``trace.ss:1031-1039``: one entry per distinct ``(CM-type, label)``.

    Petacat read the Themespace's *dominant* vertical pattern instead, which needs a
    90-point cluster lead and is routinely empty however many mappings the failed
    interpretation rested on.
    """
    identity = _FakeSlipnetNode("plato-identity")
    opposite = _FakeSlipnetNode("plato-opposite")
    pattern = get_snag_theme_pattern(
        [
            _FakeConceptMapping("plato-letter-category", identity),
            _FakeConceptMapping("plato-string-position-category", opposite),
            # A duplicate pair contributes nothing (``remove-duplicates``).
            _FakeConceptMapping("plato-letter-category", identity),
            # An unlabelled mapping is the "different" relation, not a dropped one.
            _FakeConceptMapping("plato-object-category", None),
        ]
    )
    assert pattern == [
        "vertical_bridge",
        ("plato-letter-category", "identity"),
        ("plato-string-position-category", "opposite"),
        ("plato-object-category", "diff"),
    ]


# ---------------------------------------------------------------------------
# SN-5 — progress since a snag is measured over Workspace structures
# ---------------------------------------------------------------------------


def _snagged_trace(snapshot: list[Any]) -> tuple[TemporalTrace, SnagEvent]:
    trace = TemporalTrace()
    snag = SnagEvent(
        codelet_count=100, temperature=100.0, workspace_structures=snapshot
    )
    trace.add_snag_event(snag)
    return trace, snag


def test_a_new_structure_since_the_snag_is_progress_at_its_own_strength():
    """``trace.ss:96-103, 182-187``: live structures minus the snag's snapshot, max
    strength.  A new bridge of strength 60 is 60 points of progress — no Trace event
    required, which is what Petacat demanded."""
    old = _FakeStructure(90.0)
    trace, _ = _snagged_trace([old])

    new = _FakeStructure(60.0)
    assert trace.progress_since_last_snag(_FakeWorkspace([old, new])) == 60.0


def test_a_post_snag_clamp_event_alone_is_no_progress():
    """A clamp event's strength is 100 (``trace.ss``), and Petacat added it to the
    snag's progress — so the jootser's own snag-response clamp made the stochastic
    snag exit certain on the very next update cycle.  Progress is a property of the
    Workspace, not of the Trace."""
    old = _FakeStructure(90.0)
    trace, _ = _snagged_trace([old])

    clamp = ClampEvent(codelet_count=110, temperature=100.0)
    trace.add_clamp_event(clamp)

    assert trace.progress_since_last_snag(_FakeWorkspace([old])) == 0.0


def test_a_new_bond_is_not_progress():
    """``trace.ss:1069-1073``: the progress evaluator scores bonds 0.

    The old guard was ``hasattr(structure, "structure_type")``, an attribute no
    structure class in the port has, so bonds counted at full strength.
    """
    trace, _ = _snagged_trace([])
    bond = Bond.__new__(Bond)
    bond.strength = 95.0
    assert trace.progress_since_last_snag(_FakeWorkspace([bond])) == 0.0


def test_progress_is_zero_before_anything_new_is_built():
    trace, _ = _snagged_trace([_FakeStructure(90.0)])
    assert trace.progress_since_last_snag(_FakeWorkspace([])) == 0.0


def test_undo_snag_condition_records_the_progress_it_measured():
    old = _FakeStructure(10.0)
    trace, snag = _snagged_trace([old])
    workspace = _FakeWorkspace([old, _FakeStructure(72.0)])
    temperature = Temperature()
    temperature.clamp(100.0)

    trace.undo_snag_condition(_FakeThemespace(), _FakeSlipnet(), temperature, workspace)

    assert snag.progress_achieved == 72.0
    assert not trace.within_snag_period
    assert not temperature.clamped


# ---------------------------------------------------------------------------
# CL-3 — the concept pattern a theme pattern drags into the Slipnet
# ---------------------------------------------------------------------------


def test_a_theme_pattern_pins_its_dimension_nodes():
    """``trace.ss:1503-1516``: the dimension node at ``%max-activation%``."""
    pattern = get_associated_concept_pattern(
        {
            "type": "vertical_bridge",
            "entries": [{"dimension": "plato-direction-category", "relation": "identity"}],
        }
    )
    assert pattern["entries"] == [
        {"node": "plato-direction-category", "activation": 100.0}
    ]


def test_a_negative_opposite_theme_suppresses_plato_opposite():
    """``trace.ss:1512-1514``: ``plato-opposite`` goes to 100 for a positive theme and
    to **0** for a negative one — a negative snag-response clamp actively suppresses
    the concept rather than merely not favouring it."""
    positive = get_associated_concept_pattern(
        {
            "type": "vertical_bridge",
            "entries": [
                {
                    "dimension": "plato-string-position-category",
                    "relation": "opposite",
                    "activation": 100.0,
                }
            ],
        }
    )
    negative = get_associated_concept_pattern(
        {
            "type": "vertical_bridge",
            "entries": [
                {
                    "dimension": "plato-string-position-category",
                    "relation": "opposite",
                    "activation": -100.0,
                }
            ],
        }
    )
    assert {"node": "plato-opposite", "activation": 100.0} in positive["entries"]
    assert {"node": "plato-opposite", "activation": 0.0} in negative["entries"]


def test_a_clamp_event_derives_concept_patterns_from_its_theme_patterns():
    """``trace.ss:526-530``: the derivation happens at construction, and the derived
    patterns are clamped alongside any the caller supplied."""
    event = ClampEvent(
        codelet_count=1,
        temperature=50.0,
        clamped_theme_patterns=[
            [
                "vertical_bridge",
                ("plato-direction-category", "identity"),
            ]
        ],
    )
    nodes = {
        entry["node"]
        for pattern in event.clamped_concept_patterns
        for entry in pattern["entries"]
    }
    assert "plato-direction-category" in nodes


def test_deactivating_a_clamp_only_unfreezes_its_own_nodes():
    """``trace.ss:1554-1557`` unfreezes the pattern's entries.  Petacat unfroze every
    node in the Slipnet, so ending one clamp released every other clamp in force —
    including the run's initial slipnode clamp."""
    slipnet = _FakeSlipnet("plato-direction-category", "plato-successor")
    slipnet.nodes["plato-successor"].clamp(50)

    event = ClampEvent(
        codelet_count=1,
        temperature=50.0,
        clamped_theme_patterns=[
            ["vertical_bridge", ("plato-direction-category", "identity")]
        ],
    )
    trace = TemporalTrace()
    trace.add_clamp_event(event)
    temperature = Temperature()
    event.activate(trace, _FakeThemespace(), slipnet, None, temperature)
    assert slipnet.nodes["plato-direction-category"].frozen

    event.deactivate(trace, _FakeThemespace(), slipnet)
    assert not slipnet.nodes["plato-direction-category"].frozen
    assert slipnet.nodes["plato-successor"].frozen, "an unrelated clamp was released"


def test_clamping_a_concept_pattern_reports_the_activations_it_moved():
    """``slipnet.ss:139-140`` calls ``monitor-slipnode-activation-change`` from inside
    ``clamp``, which is how a clamp puts concept-activation events into the Trace."""
    from server.engine.trace import clamp_concept_pattern

    slipnet = _FakeSlipnet("plato-opposite")
    seen: list[tuple[str, float, float]] = []
    clamp_concept_pattern(
        {"type": "concepts", "entries": [{"node": "plato-opposite", "activation": 100.0}]},
        slipnet,
        lambda node, before, after: seen.append((node.name, before, after)),
    )
    assert seen == [("plato-opposite", 0.0, 100.0)]


def test_an_empty_concept_pattern_clamps_and_unclamps_without_raising():
    """A structured pattern naming no entries clamps nothing — it is not a pattern in
    the ``node -> activation`` spelling.

    ``get_snag_concept_pattern`` returns exactly ``{"type": "concepts", "entries": []}``
    for a snag whose objects carry no descriptions, and the reader keyed the spelling
    off ``if entries:`` rather than ``if "entries" in pattern``.  The empty list read as
    "other spelling", the literal key ``"entries"`` became a node name, and
    ``float([])`` raised — on the path
    ``undo_snag_condition -> SnagEvent.deactivate -> unclamp_concept_pattern``, which
    every snag exit takes.
    """
    from server.engine.trace import clamp_concept_pattern, unclamp_concept_pattern

    slipnet = _FakeSlipnet("plato-a")
    empty = get_snag_concept_pattern([])
    assert empty == {"type": "concepts", "entries": []}

    clamp_concept_pattern(empty, slipnet)
    unclamp_concept_pattern(empty, slipnet)
    assert not slipnet.nodes["plato-a"].frozen


def test_a_snag_with_no_objects_survives_activation_and_deactivation():
    """The same shape, reached the way the engine reaches it."""
    trace = TemporalTrace()
    slipnet = _FakeSlipnet("plato-a")
    temperature = Temperature()
    temperature.clamp(100.0)

    snag = SnagEvent(
        codelet_count=10,
        temperature=100.0,
        snag_objects=[],
        snag_concept_pattern=get_snag_concept_pattern([]),
    )
    trace.add_snag_event(snag)
    snag.activate(trace, _FakeThemespace(), slipnet, None, 10)

    trace.undo_snag_condition(
        _FakeThemespace(), slipnet, temperature, _FakeWorkspace([])
    )
    assert not trace.within_snag_period
    assert not temperature.clamped


def test_an_empty_theme_pattern_clamps_nothing():
    """The same presence-not-truthiness rule for theme patterns: an empty ``entries``
    must not make the key ``"entries"`` a dimension name."""
    from server.engine.trace import clamp_theme_pattern

    themespace = _FakeThemespace()
    clamp_theme_pattern({"type": "vertical_bridge", "entries": []}, themespace)


def test_clamping_applies_to_a_node_that_is_already_frozen():
    """``clamp`` (``slipnet.ss:138-145``) applies unconditionally.  Petacat skipped any
    node that happened to be frozen, silently dropping entries whenever a clamp landed
    during the initial slipnode clamp period."""
    from server.engine.trace import clamp_concept_pattern

    slipnet = _FakeSlipnet("plato-opposite")
    slipnet.nodes["plato-opposite"].clamp(50, 100.0)
    clamp_concept_pattern(
        {"type": "concepts", "entries": [{"node": "plato-opposite", "activation": 0.0}]},
        slipnet,
    )
    assert slipnet.nodes["plato-opposite"].activation == 0.0


class _FakeCoderack:
    """Records what a clamp asked of it, resolving nothing."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, Any]] = []

    def clamp_pattern(self, pattern: Any, background: Any = None) -> None:
        self.calls.append((pattern, background))

    def unclamp_all(self) -> None:
        self.calls.append(("unclamp_all", None))


def test_a_rule_codelet_clamp_applies_its_pattern_against_a_very_low_background():
    """``jootsing.ss:326-327``: the rule-codelet clamp is built from
    ``(against-background %very-low-urgency% %rule-codelet-pattern%)``.

    The background belongs to the clamp, not to the pattern — the Scheme applies it at
    the clamp site — so it is carried here rather than by whatever the clamp happens to
    have been handed.  Petacat had no complement mechanism at all.
    """
    coderack = _FakeCoderack()
    event = ClampEvent(
        codelet_count=1,
        temperature=50.0,
        clamp_type="rule_codelet_clamp",
        clamped_codelet_patterns=[[("rule-scout", 77)]],
    )
    event.activate(
        TemporalTrace(), _FakeThemespace(), _FakeSlipnet(), coderack, Temperature()
    )
    assert coderack.calls == [([("rule-scout", 77)], "very_low")]


def test_other_clamp_types_apply_their_pattern_with_no_background():
    """Only the rule-codelet clamp uses ``against-background``; the justify clamp
    applies its top-down and thematic patterns as-is (``justify.ss``)."""
    coderack = _FakeCoderack()
    event = ClampEvent(
        codelet_count=1,
        temperature=50.0,
        clamp_type="justify_clamp",
        clamped_codelet_patterns=[[("thematic-bridge-scout", 91)]],
    )
    event.activate(
        TemporalTrace(), _FakeThemespace(), _FakeSlipnet(), coderack, Temperature()
    )
    assert coderack.calls == [([("thematic-bridge-scout", 91)], None)]


def test_a_snag_event_still_has_a_type_and_a_number():
    """Nothing above should have disturbed the event's identity in the Trace."""
    trace = TemporalTrace()
    trace.add_snag_event(
        SnagEvent(codelet_count=1, temperature=100.0, snag_type=SnagEvent.SWAP)
    )
    assert trace.get_last_event(SNAG).snag_type == "swap"
