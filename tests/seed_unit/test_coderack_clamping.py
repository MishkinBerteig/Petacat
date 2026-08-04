"""Codelet-type clamping — ``coderack.ss:95-112, 194-200, 447-473``.

A clamp on a codelet type does four things in the reference, and Petacat did one of
them.  These hold it to all four against the urgency levels and codelet types the
program actually ships with.
"""

import os

import pytest

from server.engine.coderack import Codelet, Coderack
from server.engine.metadata import MetadataProvider

SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")


@pytest.fixture
def meta():
    return MetadataProvider.from_seed_data(SEED_DIR)


@pytest.fixture
def coderack(meta):
    return Coderack(meta)


def _bin_of(coderack, codelet):
    for b in coderack.bins:
        if codelet in b.codelets:
            return b.bin_number
    return None


# ---------------------------------------------------------------------------
# (a) and (b) — new posts take the clamped urgency, and the rack is re-binned
# ---------------------------------------------------------------------------


def test_a_clamp_refiles_codelets_already_on_the_rack(coderack):
    """``coderack.ss:100`` — ``clamp`` calls ``(tell *coderack* 'set-urgencies self
    urgency)``, which walks the rack and moves every codelet of the type.

    Petacat recorded the clamp and stopped there, so applying a clamp to a rack of
    100 changed nothing about the 100 codelets on it — during precisely the episodes
    self-watching exists for.
    """
    scout = Codelet("rule-scout", 7, time_stamp=3)
    other = Codelet("breaker", 7, time_stamp=3)
    coderack.post(scout)
    coderack.post(other)
    assert _bin_of(coderack, scout) == 0

    coderack.clamp_codelet_type("rule-scout", 91)

    assert scout.urgency == 91
    assert _bin_of(coderack, scout) == 6
    assert other.urgency == 7, "an unclamped type must not move"
    assert _bin_of(coderack, other) == 0
    assert coderack.total_count == 2


def test_refiling_keeps_the_bins_eviction_aggregates_correct(coderack):
    """The bins maintain ``Σ time_stamp`` for the O(1) eviction weights; a move that
    bypassed ``CoderackBin.remove``/``add`` would silently corrupt them."""
    coderack.post(Codelet("rule-scout", 7, time_stamp=11))
    coderack.post(Codelet("rule-scout", 7, time_stamp=13))
    coderack.clamp_codelet_type("rule-scout", 91)

    for b in coderack.bins:
        assert b.sum_time_stamp == sum(c.time_stamp for c in b.codelets)


def test_a_new_post_takes_the_clamped_urgency_exactly(coderack):
    """``coderack.ss:196-200``: ``(if urgency-clamped? clamped-relative-urgency
    original-urgency)``.  Petacat took the *max*, which turned a clamp meant to
    starve a type — the very-low background of ``against-background`` — into a no-op.
    """
    coderack.clamp_codelet_type("breaker", 21)
    breaker = Codelet("breaker", 91)
    coderack.post(breaker)
    assert breaker.urgency == 21
    assert _bin_of(coderack, breaker) == 1


# ---------------------------------------------------------------------------
# (c) — unclamping restores what was there
# ---------------------------------------------------------------------------


def test_unclamping_restores_the_posted_urgencies(coderack):
    """``coderack.ss:107-112`` -> ``reset-urgencies`` (``coderack.ss:452-456``), which
    sends each codelet back to its ``original-urgency`` (``coderack.ss:256-257``)."""
    scout = Codelet("rule-scout", 35, time_stamp=1)
    coderack.post(scout)
    coderack.clamp_codelet_type("rule-scout", 91)
    assert _bin_of(coderack, scout) == 6

    coderack.unclamp_codelet_type("rule-scout")

    assert scout.urgency == 35
    assert _bin_of(coderack, scout) == 2
    assert coderack.clamped_urgencies == {}


def test_unclamp_all_restores_every_type(coderack):
    scout = Codelet("rule-scout", 35, time_stamp=1)
    breaker = Codelet("breaker", 63, time_stamp=1)
    coderack.post(scout)
    coderack.post(breaker)
    coderack.clamp_pattern([("rule-scout", 91), ("breaker", 7)])
    assert (scout.urgency, breaker.urgency) == (91, 7)

    coderack.unclamp_all()

    assert (scout.urgency, breaker.urgency) == (35, 63)
    assert coderack.clamped_urgencies == {}


# ---------------------------------------------------------------------------
# (d) — the posting-probability override
# ---------------------------------------------------------------------------


def test_a_clamped_type_posts_at_its_clamped_urgency(coderack):
    """``post-codelet-probability`` (``coderack.ss:470-473``) returns ``(%
    clamped-urgency)`` for a clamped type, ahead of any workspace-driven
    computation.  Petacat's ``_compute_posting_probability`` never consulted the
    clamp at all."""
    assert coderack.clamped_posting_probability("rule-scout") is None
    coderack.clamp_codelet_type("rule-scout", 77)
    assert coderack.clamped_posting_probability("rule-scout") == 0.77
    coderack.clamp_codelet_type("breaker", 21)
    assert coderack.clamped_posting_probability("breaker") == 0.21


# ---------------------------------------------------------------------------
# CL-2 — ``against-background`` and the named patterns
# ---------------------------------------------------------------------------


def test_a_background_clamps_every_unspecified_type(coderack):
    """``jootsing.ss:326-327``: the rule-codelet clamp is ``(against-background
    %very-low-urgency% %rule-codelet-pattern%)`` — the three rule types at 77/91/91
    **and all 24 others at 21**.  The complement did not exist anywhere in the port,
    so the stall-escape was a mild boost rather than a redirection.
    """
    resolved = dict(
        coderack.resolve_codelet_pattern(
            {"type": "rule_codelet_pattern"}, background="very_low"
        )
    )

    assert len(resolved) == 27
    assert resolved["rule-scout"] == 77
    assert resolved["rule-evaluator"] == 91
    assert resolved["rule-builder"] == 91
    background = [
        urgency for name, urgency in resolved.items() if not name.startswith("rule-")
    ]
    assert background and set(background) == {21}


def test_applying_a_pattern_against_a_background_throttles_everything_else(coderack):
    coderack.clamp_pattern({"type": "rule_codelet_pattern"}, "very_low")
    assert coderack.clamped_posting_probability("rule-evaluator") == 0.91
    assert coderack.clamped_posting_probability("bottom-up-bond-scout") == 0.21


def test_no_background_clamps_only_what_the_pattern_names(coderack):
    """``%thematic-codelet-pattern%`` (``trace.ss:1629-1631``) is one entry, and the
    justify clamp applies it as-is — no complement."""
    resolved = coderack.resolve_codelet_pattern({"type": "thematic_codelet_pattern"})
    assert resolved == [("thematic-bridge-scout", 91)]


def test_a_background_applies_to_an_already_resolved_pattern_too(coderack):
    """The clamp sites carry resolved ``(type, urgency)`` lists read out of
    ``meta.codelet_patterns``, so the complement has to work on those and not only on
    the named form."""
    resolved = dict(
        coderack.resolve_codelet_pattern([("rule-scout", 77)], background="very_low")
    )
    assert len(resolved) == 27
    assert resolved["rule-scout"] == 77
    assert resolved["breaker"] == 21


def test_a_pattern_dict_may_name_its_own_background(coderack):
    resolved = dict(
        coderack.resolve_codelet_pattern(
            {"type": "thematic_codelet_pattern", "background": "extremely_low"}
        )
    )
    assert resolved["thematic-bridge-scout"] == 91
    assert resolved["breaker"] == 7


def test_either_spelling_of_a_pattern_name_resolves(coderack):
    """The clamp sites write ``rule_codelet_pattern``; ``seed_data/posting_rules.json``
    is keyed ``rule-codelet-pattern``.  Both must find the same nine patterns, so
    neither side has to know the other's convention."""
    assert coderack.resolve_codelet_pattern(
        {"type": "rule-codelet-pattern"}
    ) == coderack.resolve_codelet_pattern({"type": "rule_codelet_pattern"})


def test_an_already_resolved_pattern_passes_through(coderack):
    assert coderack.resolve_codelet_pattern([("breaker", 35)]) == [("breaker", 35)]


def test_an_unknown_pattern_name_clamps_nothing(coderack):
    """A placeholder no named pattern matches must leave the rack alone rather than
    unpacking the dict's keys, which is what ``clamp_pattern`` used to do."""
    coderack.clamp_pattern({"type": "no-such-pattern"})
    assert coderack.clamped_urgencies == {}
