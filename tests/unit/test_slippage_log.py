"""The slippage log a rule translation keeps (``answers.ss:1198-1272``).

Metacat's ``make-slippage-log`` records which slippages a translation really applied: a
slippage that replaced a concept (``applied``) and a coattail slippage that dragged a
related concept along (``coattail``).  Both lists are consed, so newest first.  These
tests drive the log with stand-in slippages, bridges and concepts; the comparison with
Metacat's own logs, run for run, is ``tests/lockstep/test_translation_log.py``.
"""

from types import SimpleNamespace

from server.engine.concept_mappings import SlippageLog


def _cm(name, bridge_holder=None, symmetric_of=None):
    cm = SimpleNamespace(name=name, object1=bridge_holder)
    cm.is_symmetric = lambda other: other.name == name + "'"
    return cm


def _bridge(forward, symmetric=()):
    b = SimpleNamespace()
    b.get_slippages = lambda: list(forward) + list(symmetric)
    b.get_non_symmetric_slippages = lambda: list(forward)
    return b


def _object_on(bridge):
    return SimpleNamespace(vertical_bridge=bridge)


def test_applied_slippages_are_recorded_newest_first_with_their_bridges():
    b1, b2 = _bridge([]), _bridge([])
    s1, s2 = _cm("s1", _object_on(b1)), _cm("s2", _object_on(b2))
    log = SlippageLog("top")
    log.applied(s1)
    log.applied(s2)
    assert log.directly_applied_slippages == [s2, s1]
    # ``get-slippage-bridges`` is ``remq-duplicates`` of a newest-first list.
    assert log.get_slippage_bridges() == [b2, b1]


def test_a_slippage_applied_twice_counts_once_in_the_applied_list_keeping_its_last_place():
    s1, s2 = _cm("s1", _object_on(_bridge([]))), _cm("s2", _object_on(_bridge([])))
    log = SlippageLog("bottom")
    log.applied(s1)
    log.applied(s2)
    log.applied(s1)
    # directly-applied = (s1 s2 s1); remq-duplicates keeps the last occurrence of each.
    assert log.get_applied_slippages() == [s2, s1]


def test_the_slippage_to_highlight_is_the_forward_form_of_a_symmetric_one():
    forward = _cm("f")
    reverse = _cm("f'")
    bridge = _bridge([forward], [reverse])
    forward.object1 = reverse.object1 = _object_on(bridge)
    log = SlippageLog("top")
    log.applied(reverse)
    assert log.get_bridge(reverse) is bridge
    assert log.get_slippage_to_highlight(reverse) is forward
    assert log.get_slippage_to_highlight(forward) is forward


def test_a_coattail_slippage_is_made_of_the_node_and_its_relative_and_records_the_inducer():
    bridge = _bridge([])
    inducing = _cm("ind", _object_on(bridge))
    category = SimpleNamespace(name="plato-letter-category")
    node1 = SimpleNamespace(name="plato-a", category=category, outgoing_links=[])
    node2 = SimpleNamespace(name="plato-b", category=category, outgoing_links=[])
    log = SlippageLog("top")
    log.coattail(node1, None, node2, inducing)
    (coattail, induced_by), = log.coattail_slippage_table
    assert induced_by is inducing
    assert (coattail.descriptor1, coattail.descriptor2) == (node1, node2)
    assert coattail.description_type1 is category
    assert log.get_coattail_inducing_slippages() == [inducing]
    assert log.coattail_inducing_slippage(inducing)
    # The inducing slippage is an applied one, though never directly applied.
    assert log.get_applied_slippages() == [inducing]
    assert log.get_slippage_bridges() == [bridge]
