"""List orders that Metacat's ``cons`` and ``vector`` fix, and that Petacat once got the other way round.

Each test names the Scheme site it pins (DISCREPANCIES5 C-1, G-Z4, I-4, I-5).  The orders are not
cosmetic: they are the orders of weighted walks, of coin flips and of first-match searches.
"""

import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from server.engine import jootsing, rules
from server.engine.coderack import Codelet, Coderack, CoderackBin
from server.engine.metadata import MetadataProvider
from server.engine.rng import RNG
from server.engine.workspace import WorkspaceString


# ---- G-Z4: Chez Scheme's ``sort`` (the merge steps of sort-templates) --------------------------

_CHEZ = json.loads((Path(__file__).parent / "chez_sort_cases.json").read_text())["cases"]


@pytest.mark.parametrize("case", _CHEZ)
def test_chez_sort_agrees_with_chez_on_a_relation_that_is_not_a_strict_order(case):
    """``sort-templates``' predicate is no strict order (``rules.ss:818-829``), so the result is the
    merge steps' own.  The expected orders were produced by ``sort`` in the Metacat image."""
    relation = case["relation"]

    def less(a, b):
        return relation[a][b] == "1"

    assert rules.chez_sort(less, list(range(len(relation)))) == case["chez"]


# ---- C-1: the string's group list is newest first (workspace-strings.ss:266) ----------------------


class _Slipnet:
    nodes: dict = {}


def _group(first, last):
    return NS(objects=[NS(left_string_pos=first, enclosing_group=None, id_num=first),
                       NS(left_string_pos=last, enclosing_group=None, id_num=last)],
              left_string_pos=first, id_num=None)


def test_a_string_lists_its_groups_newest_first_after_its_letters():
    string = WorkspaceString("abcd", _Slipnet())
    letters = list(string.objects)
    older, newer = _group(0, 1), _group(2, 3)
    string.add_group(older)
    string.add_group(newer)
    assert string.groups == [newer, older]
    assert string.objects == letters + [newer, older]
    string.remove_group(newer)
    assert string.groups == [older] and string.objects == letters + [older]


def test_a_rule_over_a_string_reads_the_bridges_of_its_top_level_objects_unsorted():
    """``get-subobject-bridges`` of a string (``workspace-strings.ss:468-471``) is over
    ``get-top-level-objects`` -- letters, then groups newest first -- not the sorted
    ``get-constituent-objects``; it is the order of a rule's supporting bridges and so of the
    supporting groups an answer lists (G-Z4)."""
    string = WorkspaceString("aabb", _Slipnet())
    left, right = _group(0, 1), _group(2, 3)
    for g, name in ((left, "left"), (right, "right")):
        g.horizontal_bridge = name
    string.add_group(left)
    string.add_group(right)
    for letter in string.objects[:4]:
        letter.enclosing_group = left  # every letter is inside a group
    assert rules._get_subobject_bridges(string, "horizontal") == ["right", "left"]


# ---- C-1: the coderack's bins are vectors and the deferred batch is consed -----------------------


SEED_DIR = Path(__file__).resolve().parents[2] / "seed_data"


def _rack(max_size):
    rack = Coderack(MetadataProvider.from_standard_configuration(SEED_DIR))
    rack.max_size = max_size
    return rack


def _codelets(n):
    return [Codelet("bottom-up-bond-scout", 10, time_stamp=i) for i in range(n)]


def test_removing_from_a_bin_moves_the_last_codelet_into_the_gap():
    """``remove-codelet`` (``coderack.ss:309-318``): ``(vector-set! codelet-vector index
    swap-codelet)``.  ``choose-random-codelet`` indexes that vector."""
    bin_ = CoderackBin(0)
    a, b, c, d = _codelets(4)
    for c_ in (a, b, c, d):
        bin_.add(c_)
    bin_.remove(b)
    assert bin_.codelets == [a, d, c]
    bin_.remove(d)
    assert bin_.codelets == [a, c]
    bin_.remove(c)
    assert bin_.codelets == [a]


def test_a_deferred_batch_lands_in_its_bin_newest_first():
    """``add-deferred-codelet`` conses (``coderack.ss:383-385``) and ``post-deferred-codelets`` walks the
    list, so the codelet created last is the first into the bin."""
    rack = _rack(100)
    batch = _codelets(3)
    rack.post_deferred(batch, current_time=5, rng=RNG(1))
    assert [c for b in rack.bins for c in b.codelets] == list(reversed(batch))


def test_a_batch_over_capacity_drops_by_a_pick_over_the_newest_first_list():
    class Pick:
        def pick(self, items):
            assert items == list(reversed(batch))
            return items[0]

    rack = _rack(2)
    batch = _codelets(3)
    rack.post_deferred(batch, current_time=5, rng=Pick())
    assert [c for b in rack.bins for c in b.codelets] == [batch[1], batch[0]]


# ---- I-4: the jootser's event set is newest first (jootsing.ss:154-168, trace.ss:201) --------------


def _snag(count, tag):
    return NS(event_type="snag", codelet_count=count, tag=tag)


def test_the_most_recent_event_set_lists_the_newest_event_first(monkeypatch):
    events = [_snag(10, "a"), _snag(20, "b"), _snag(30, "c")]
    trace = NS(events=events, get_new_events_since_last=lambda kind: list(events))
    monkeypatch.setattr(jootsing, "_events_equivalent", lambda x, y: True)
    monkeypatch.setattr(jootsing, "SNAG", "snag")
    got = jootsing.get_most_recent_event_set(trace, "snag")
    assert [e.tag for e in got] == ["c", "b", "a"]


def test_partition_puts_each_event_at_the_front_of_its_class_from_the_oldest_end(monkeypatch):
    """``partition`` (``utilities.ss:811-825``) over the newest-first list inserts the OLDEST event
    first, so a class is newest first and the first class is the oldest event's."""
    events = [_snag(30, "c1"), _snag(20, "b2"), _snag(10, "a1")]
    monkeypatch.setattr(jootsing, "_events_equivalent",
                        lambda x, y: x.tag[0] == y.tag[0] or (x.tag[0] in "ac" and y.tag[0] in "ac"))
    classes = jootsing._partition_events(events)
    assert [[e.tag for e in cls] for cls in classes] == [["c1", "a1"], ["b2"]]


# ---- I-3: the display-time prints of an answer and of a rule event (trace.ss:452, 988) -------------


def test_an_empty_slippage_log_prints_as_metacat_prints_it():
    """``(print slippage-log)`` (``answers.ss:1210-1228``)."""
    from server.engine.concept_mappings import SlippageLog

    assert SlippageLog("top").verbose_text() == (
        "\nTranslation direction: top-to-bottom\nDirectly-applied slippages:\n  None\n"
        "Coattail-slippages:\n  None\n\n")
    assert "bottom-to-top" in SlippageLog("bottom").verbose_text()


def test_a_rule_clause_prints_as_printf_rule_clause_does():
    """``printf-rule-clause`` (``rules.ss:2131-2155``)."""
    from server.engine.rules import CLAUSE_EXTRINSIC, CLAUSE_INTRINSIC, RuleChange, RuleClause
    from server.engine.verbose import rule_clause_text

    def node(short):
        return NS(short_name=short, name="plato-" + short)

    letter, position, rightmost = node("letter"), node("StringPos"), node("rmost")
    ctgy, succ = node("LettCtgy"), node("succ")
    intrinsic = RuleClause(
        CLAUSE_INTRINSIC, object_description=(letter, position, rightmost),
        changes=[RuleChange(dimension=ctgy, relation=succ)])
    assert rule_clause_text(intrinsic) == (
        "CHANGE (<letter> <StringPos> <rmost>)\n   (self <LettCtgy> <succ>)\n")
    swap = RuleClause(
        CLAUSE_EXTRINSIC,
        extrinsic_objects=[("string", position, rightmost), (letter, ctgy, succ)],
        dimensions=[position, ctgy])
    assert rule_clause_text(swap) == (
        "SWAP <StringPos>, <LettCtgy> of\n   (string <StringPos> <rmost>)\n"
        "   (<letter> <LettCtgy> <succ>)\n")
