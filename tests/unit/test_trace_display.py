"""A Trace event's print name and header, against Metacat's ``trace.ss``.

Metacat names each event when it makes it (``print-name``) and heads its redisplay with a
second string (``display-workspace``'s ``draw-event-header``).  The two are different
strings -- ``>a-b-c>`` in the Trace window, "Built successor-group" over the Workspace --
and the functions here are checked, one branch at a time, against the lines of
``trace.ss`` and ``trace-graphics.ss`` they port.  Real recorded Metacat output is
checked in ``tests/lockstep/test_event_names.py``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from server.engine import trace as T
from server.engine import trace_display as D


def node(name: str, short: str | None = None):
    return SimpleNamespace(name=name, short_name=short or name[6:])


def letter(category: str):
    n = node(f"plato-{category}")
    return SimpleNamespace(
        get_descriptor_for=lambda facet, n=n: n,
    )


def group_of(*descriptor_names: str, direction: str | None = None, nested: bool = False):
    """A group whose constituents carry the named descriptors on the bond facet."""
    objects = []
    for name in descriptor_names:
        descriptor = node(f"plato-{name}")
        if nested:
            objects.append(
                SimpleNamespace(
                    objects=[1], get_descriptor_for=lambda facet, d=descriptor: d
                )
            )
        else:
            objects.append(SimpleNamespace(get_descriptor_for=lambda facet, d=descriptor: d))
    return SimpleNamespace(
        bond_facet=node("plato-letter-category"),
        objects=objects,
        direction=node(f"plato-{direction}") if direction else None,
        group_category=node("plato-succgrp"),
    )


# ---------------------------------------------------------------- print names

def test_a_concept_activation_is_named_by_the_concepts_short_name():
    """``(format "(~a)" (tell slipnode 'get-short-name))`` (``trace.ss:708``)."""
    event = T.TraceEvent(T.CONCEPT_ACTIVATION, 5, 50.0, slipnode=node("plato-identity", "Identity"))
    assert D.print_name(event) == "(Identity)"


@pytest.mark.parametrize(
    "direction, expected",
    [("right", ">a-b-c>"), ("left", "<a-b-c<"), (None, "[a-b-c]")],
)
def test_a_group_is_named_by_its_letters_and_its_direction(direction, expected):
    """``>abc>`` / ``<cba<`` / ``[abc]`` by direction (``trace.ss:840-847``); the text is
    the descriptors on the bond facet hyphen-joined (``group-event-pexp-text-string``)."""
    group = group_of("a", "b", "c", direction=direction)
    event = T.TraceEvent(T.GROUP_BUILT, 5, 50.0, group=group)
    assert D.print_name(event) == expected


def test_a_group_of_groups_names_its_constituents_in_upper_case():
    """``(tell descriptor 'get-uppercase-name)`` for a group constituent."""
    group = group_of("succgrp", "predgrp", direction="right", nested=True)
    assert D.group_event_text(group) == "SUCCGRP-PREDGRP"


def test_a_length_descriptor_is_named_by_its_number():
    """``platonic-number->number`` (``trace-graphics.ss:329``)."""
    group = group_of("two", "two", direction="right", nested=True)
    assert D.group_event_text(group) == "2-2"


@pytest.mark.parametrize(
    "bridge_type, prefix", [("top", "T"), ("vertical", "V"), ("bottom", "B")]
)
def test_a_slippage_is_named_by_its_bridge_type_and_mapping(bridge_type, prefix):
    """``T:`` / ``V:`` / ``B:`` plus the concept-mapping's ``a=>b`` (``trace.ss:755``)."""
    cm = SimpleNamespace(
        descriptor1=node("plato-leftmost", "lmost"),
        descriptor2=node("plato-rightmost", "rmost"),
        is_identity=False,
    )
    event = T.TraceEvent(
        T.CONCEPT_MAPPING_BUILT, 5, 50.0,
        concept_mapping=cm, bridge=SimpleNamespace(bridge_type=bridge_type),
    )
    assert D.print_name(event) == f"{prefix}:lmost=>rmost"


def test_the_letter_category_node_is_abbreviated_inside_a_mapping():
    """``get-CM-short-name`` (``slipnet.ss:56``) avoids overlapping graphics."""
    assert D.cm_short_name(node("plato-letter-category", "LetterCtgy")) == "LettCtgy"
    assert D.cm_short_name(node("plato-succ", "succ")) == "succ"


@pytest.mark.parametrize("is_top, expected", [(True, "[Top Rule]"), (False, "[Bottom Rule]")])
def test_a_rule_is_named_top_or_bottom(is_top, expected):
    """``(case rule-type (top "[Top Rule]") (bottom "[Bottom Rule]"))`` (``trace.ss:937``)."""
    event = T.TraceEvent(T.RULE_BUILT, 5, 50.0, structures=[SimpleNamespace(is_top_rule=is_top)])
    assert D.print_name(event) == expected


def test_an_answer_a_snag_and_a_clamp_have_fixed_names():
    """``[Answer ijl]`` (``trace.ss:344``), ``[Snag]`` (``:1079``), ``[Clamp]`` (``:549``)."""
    answer = T.AnswerEvent(5, 50.0, answer_string="ijl")
    assert D.print_name(answer) == "[Answer ijl]"
    assert D.print_name(T.SnagEvent(5, 50.0)) == "[Snag]"
    assert D.print_name(T.ClampEvent(5, 50.0)) == "[Clamp]"


# -------------------------------------------------------------------- headers

def test_the_headers_of_a_concept_activation_use_the_full_concept_name():
    """``"Activation of ~a concept"`` with ``full-slipnode-name`` (``trace.ss:742, 1271``)."""
    for name, full in [
        ("plato-direction-category", "Direction"),
        ("plato-letter-category", "Letter-Category"),
        ("plato-opposite", "Opposite"),
        ("plato-succgrp", "successor-group"),
        ("plato-leftmost", "leftmost"),
    ]:
        event = T.TraceEvent(T.CONCEPT_ACTIVATION, 5, 50.0, slipnode=node(name))
        assert D.header(event) == f"Activation of {full} concept"


def test_a_group_header_names_the_kind_of_group_and_a_flip_names_the_other_kind():
    """"Built successor-group", but "Flipped" names the *unflipped* group (``trace.ss:1291``):
    a predecessor group is what a successor group is flipped *from*."""
    built = T.TraceEvent(
        T.GROUP_BUILT, 5, 50.0, group=group_of("a", "b", direction="right")
    )
    assert D.header(built) == "Built successor-group"
    flipped = T.TraceEvent(
        T.GROUP_BUILT, 5, 50.0,
        group=SimpleNamespace(
            group_category=node("plato-predgrp"), objects=[], bond_facet=None, direction=None
        ),
        flipped=True,
    )
    assert D.header(flipped) == "Flipped successor-group"


def test_a_slippage_header_names_the_mapping():
    cm = SimpleNamespace(
        descriptor1=node("plato-a"), descriptor2=node("plato-b"), is_identity=False
    )
    event = T.TraceEvent(
        T.CONCEPT_MAPPING_BUILT, 5, 50.0,
        concept_mapping=cm, bridge=SimpleNamespace(bridge_type="top"),
    )
    assert D.header(event) == "Made a=>b slippage"
    cm.is_identity = True
    assert D.header(event) == "Made a=>b concept-mapping"


def test_a_rule_header_says_whether_the_rule_is_translated():
    plain = T.TraceEvent(T.RULE_BUILT, 5, 50.0, structures=[SimpleNamespace(translated=False)])
    translated = T.TraceEvent(T.RULE_BUILT, 5, 50.0, structures=[SimpleNamespace(translated=True)])
    assert D.header(plain) == "Built rule"
    assert D.header(translated) == "Built translated rule"


@pytest.mark.parametrize(
    "justify, unjustified, expected",
    [
        (False, False, "Found new answer"),
        (False, True, "Found new answer"),
        (True, True, "Settled for unjustified answer"),
        (True, False, "Justified answer"),
    ],
)
def test_an_answer_header_follows_justify_mode_and_whether_it_is_justified(
    justify, unjustified, expected
):
    """``trace.ss:431-437``."""
    unjustified_slippages = [object()] if unjustified else []
    event = T.AnswerEvent(5, 50.0, answer_string="x", unjustified_slippages=unjustified_slippages)
    assert D.header(event, justify_mode=justify) == expected


def test_snag_and_clamp_headers():
    assert D.header(T.SnagEvent(5, 50.0)) == "Snag"
    assert D.header(T.ClampEvent(5, 50.0)) == "Clamped patterns"
    assert D.header(T.ClampEvent(5, 50.0, clamp_type="manual_clamp")) == "Manually clamped patterns"


# ------------------------------------------------------------ the trace itself

def test_a_bare_trace_names_its_events_and_keeps_no_picture():
    """A trace with no run behind it can name an event but has no Workspace to picture."""
    trace = T.TemporalTrace()
    event = T.SnagEvent(5, 50.0)
    trace.record_event(event)
    assert event.print_name == "[Snag]"
    assert event.picture is None


def test_a_picture_that_cannot_be_taken_never_stops_the_trace():
    """A display aid must not be able to break a run."""
    trace = T.TemporalTrace()
    trace.ctx = object()  # has no workspace: building the picture raises
    event = T.SnagEvent(5, 50.0)
    trace.record_event(event)
    assert trace.events == [event]
    assert event.picture is None
    assert event.print_name == "[Snag]"
