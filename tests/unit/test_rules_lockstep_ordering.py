"""Ordering and gating details of the rule machinery that decide what Metacat computes.

Each test names the Scheme site whose behaviour it pins (DISCREPANCIES5 items C-1 to C-4,
D-1, D-2, D-5).  The objects are small fakes: only the structure each function reads.
"""

from types import SimpleNamespace as NS

import pytest

from server.engine import rules
from server.engine.rules import CLAUSE_EXTRINSIC, CLAUSE_INTRINSIC


def _obj(left, right, enclosing=None, string=None):
    return NS(left_string_pos=left, right_string_pos=right,
              enclosing_group=enclosing, string=string)


# ---- C-3: sort-templates (rules.ss:816-826) -------------------------------------


def test_sort_templates_puts_the_contained_object_first():
    s = NS()
    outer = _obj(0, 2, string=s)
    inner = _obj(0, 1, enclosing=outer, string=s)
    t_outer = (CLAUSE_INTRINSIC, outer, [])
    t_inner = (CLAUSE_INTRINSIC, inner, [])
    assert rules.sort_templates([t_outer, t_inner]) == [t_inner, t_outer]
    assert rules.sort_templates([t_inner, t_outer]) == [t_inner, t_outer]


def test_sort_templates_orders_disjoint_objects_by_position_and_intrinsic_first():
    s = NS()
    a, b = _obj(0, 0, string=s), _obj(1, 1, string=s)
    ta, tb = (CLAUSE_INTRINSIC, a, []), (CLAUSE_INTRINSIC, b, [])
    ext2 = (CLAUSE_EXTRINSIC, [], [1, 2])
    ext1 = (CLAUSE_EXTRINSIC, [], [1])
    assert rules.sort_templates([ext1, ext2, tb, ta]) == [ta, tb, ext2, ext1]


# ---- D-2: get-common-change-schemas (rules.ss:702-706) --------------------------


def test_a_schema_with_no_common_relation_survives_the_identity_filter(monkeypatch):
    dim, d = NS(name="plato-letter-category"), NS(name="plato-d")
    ident = NS(name="plato-identity")
    succ = NS(name="plato-successor")
    schemas = [(dim, None, None, d), (dim, None, ident, d), (dim, None, succ, d)]
    monkeypatch.setattr(rules, "_get_common_schemas", lambda cluster: schemas)
    assert rules._get_common_change_schemas([]) == [schemas[0], schemas[2]]


# ---- D-1: the four-way gate (rules.ss:619-634) ----------------------------------


@pytest.mark.parametrize(
    "spans_left, common_right, spans_right, left_ok, right_ok, expected",
    [
        (False, False, False, True, True, False),   # not spanning the left side at all
        (True, False, False, False, False, True),   # clause 1
        (True, True, True, False, False, True),     # clause 2
        (True, True, False, False, True, True),     # clause 3
        (True, True, False, True, False, False),    # left describable does not help
        (False, True, True, True, False, True),     # clause 4
        (False, True, True, False, True, False),
        (False, True, False, True, True, False),
    ],
)
def test_the_subobjects_gate_is_the_four_clause_or(
    monkeypatch, spans_left, common_right, spans_right, left_ok, right_ok, expected
):
    left, right = object(), object()
    monkeypatch.setattr(rules, "_spans_left_side", lambda c: spans_left)
    monkeypatch.setattr(rules, "_common_right_enclosing_object", lambda c: common_right)
    monkeypatch.setattr(rules, "_spans_right_side", lambda c: spans_right)
    monkeypatch.setattr(rules, "_get_right_enclosing_object", lambda c: right)
    monkeypatch.setattr(
        rules, "_all_subobjects_describable",
        lambda obj, dim, desc: left_ok if obj is left else right_ok)
    assert rules._subobjects_gate([], left, "dim", "d1", "d2") is expected


def test_all_subobjects_describable_needs_an_existing_descriptor(monkeypatch):
    assert rules._all_subobjects_describable(NS(), "dim", None) is False


def test_common_right_enclosing_object_counts_no_group_as_a_value():
    g = object()
    same = [NS(object2=NS(enclosing_group=g)), NS(object2=NS(enclosing_group=g))]
    none = [NS(object2=NS(enclosing_group=None)), NS(object2=NS(enclosing_group=None))]
    mixed = [NS(object2=NS(enclosing_group=g)), NS(object2=NS(enclosing_group=None))]
    assert rules._common_right_enclosing_object(same)
    assert rules._common_right_enclosing_object(none)
    assert not rules._common_right_enclosing_object(mixed)


# ---- C-2: remq-duplicates keeps the last occurrence ------------------------------


def test_remq_duplicates_keeps_the_last_occurrence():
    a, b, c = object(), object(), object()
    assert rules._remq_duplicates([a, b, a, c, b]) == [a, c, b]


# ---- C-2: unjustified themes read with assq (first entry wins) -------------------


def test_unjustified_theme_for_a_repeated_dimension_takes_the_first_entry():
    from server.engine.answers import _unjustified_themes

    dim = NS(name="plato-letter-category")
    cm1 = NS(description_type1=dim, label=NS(name="plato-successor"))
    cm2 = NS(description_type1=dim, label=NS(name="plato-identity"))
    assert _unjustified_themes([cm1, cm2]) == _unjustified_themes([cm1])
    assert _unjustified_themes([cm1]) != _unjustified_themes([cm2])


# ---- C-4: differing-dimensions is not deduplicated --------------------------------


def test_differing_dimensions_counts_one_per_matching_pair():
    from server.engine.answer_comparison import AnswerComparison
    from server.engine.memory import AnswerDescription, EpisodicMemory
    from server.engine.metadata import default_commentary_templates

    X, Y = "plato-direction-category", "plato-group-category"

    def answer(themes, unjustified):
        return AnswerDescription(
            problem=("abc", "abd", "xyz", "p"), top_rule_description="r",
            bottom_rule_description="", top_rule_quality=70.0,
            bottom_rule_quality=0.0, quality=70.0, temperature=30.0,
            themes=themes, unjustified_slippages=[], unjustified_themes=unjustified,
        )

    # Answer 1 states X twice (justified identity, unjustified opposite); answer 2 once.
    a = answer({X: "identity", Y: "identity"}, {X: "opposite"})
    b = answer({X: "different", Y: "identity"}, {})
    cmp = AnswerComparison(a, b, EpisodicMemory(), default_commentary_templates(), None)
    assert cmp.differing_dimensions == [X, X]


# ---- C-1: newest-first lists -------------------------------------------------------


def test_workspace_rules_and_bridges_are_consed_newest_first():
    from server.engine.workspace import Workspace

    ws = Workspace.__new__(Workspace)
    ws.top_rules, ws.bottom_rules = [], []
    ws.top_bridges, ws.bottom_bridges, ws.vertical_bridges = [], [], []
    ws.rule_present = lambda rule: False
    r1 = NS(is_top_rule=True)
    r2 = NS(is_top_rule=True)
    ws.add_rule(r1)
    ws.add_rule(r2)
    assert ws.top_rules == [r2, r1]


# ---- C-1: the most recent clamp, first of a newest-first list (jootsing.ss:144, trace.ss:201) ---


def test_joots_from_justify_clamps_reads_the_most_recent_clamp():
    from server.engine.jootsing import joots_from_justify_clamps
    from server.engine.trace import ClampEvent

    seen = []

    class Recording(ClampEvent):
        @property
        def rules(self):
            seen.append(self.name)
            return []

    def clamp(name):
        c = Recording.__new__(Recording)
        c.name = name
        return c

    joots_from_justify_clamps(
        [clamp("new"), clamp("old")], None, 0, None, None, None, None)
    assert set(seen) == {"new"}


# ---- D-5: if* is when (answers.ss:1082-1092) -----------------------------------------


def test_length_transform_attaches_to_source_and_instantiated_and_bond_facet_is_a_sibling(
    monkeypatch,
):
    from server.engine import answers, groups

    attached = []
    monkeypatch.setattr(groups, "attach_length_description", attached.append)
    monkeypatch.setattr(answers, "_has_length", lambda g: False)
    monkeypatch.setattr(rules, "_get_constituent_objects", lambda g: [letter])

    letter = NS(name="letter")
    instantiated = groups.Group.__new__(groups.Group)
    source = groups.Group.__new__(groups.Group)
    source.image = NS(instantiated_object=instantiated)
    transforms = [
        (NS(name="plato-length"), NS(name="plato-two")),
        (NS(name="plato-bond-facet"), NS(name="plato-length")),
    ]
    answers._attach_length_to_appropriate_groups([(source, transforms)])
    # source (no Length yet), instantiated (unconditionally), then the sub-object,
    # which is not filtered to groups.
    assert attached == [source, instantiated, letter]
