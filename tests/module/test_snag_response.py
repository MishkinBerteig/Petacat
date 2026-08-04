"""The snag response, driven end to end — ``process-snag`` (``answers.ss:1153-1193``).

``process-snag`` performs seven steps.  Petacat performed one and a half of them:
it recorded the event, clamped the temperature *at its current value*, and stored a
snag description.  These tests drive a real run into a real snag and hold the
response to the reference.

Marked ``numeric_matrix`` because reaching a snag runs the update cycle, which is
arithmetic the substrate owns; the snag response itself is backend-independent.
"""

from __future__ import annotations

import os

import pytest

from server.engine.metadata import MetadataProvider
from server.engine.runner import EngineRunner
from server.engine.trace import SnagEvent

# Every test here reaches a snag by running the engine, which executes arithmetic the
# numeric substrate owns, so each one runs once per backend in the matrix.
pytestmark = pytest.mark.numeric_matrix

SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")

#: ``abc -> abd; xyz -> ?`` is the dissertation's canonical snag problem: the rule
#: "replace the rightmost letter by its successor" cannot be applied to ``z``.
SNAG_PROBLEM = ("abc", "abd", "xyz")
SEEDS = range(24)
STEP_BUDGET = 2500


@pytest.fixture(scope="module")
def meta():
    return MetadataProvider.from_seed_data(SEED_DIR)


def _run_to_first_snag(meta) -> tuple[EngineRunner, set[int]]:
    """Step a seeded run until a snag lands; return it and the pre-snag rack ids.

    Stepping one codelet at a time is what lets the rack be inspected at the moment
    the snag is dealt with rather than whenever the run happens to stop.  Identity is
    taken from ``Codelet.id`` — the run's own allocator — and not from ``id()``, which
    CPython reuses the moment the flushed codelets are collected.
    """
    for seed in SEEDS:
        runner = EngineRunner(meta)
        runner.init_mcat(*SNAG_PROBLEM, seed=seed)
        for _ in range(STEP_BUDGET):
            before = {
                c.id for b in runner.ctx.coderack.bins for c in b.codelets
            }
            runner.step_mcat()
            if runner.ctx.trace.snag_count:
                return runner, before
    pytest.fail(
        f"no snag in {len(SEEDS)} seeds x {STEP_BUDGET} codelets of "
        f"{SNAG_PROBLEM[0]} => {SNAG_PROBLEM[1]}; {SNAG_PROBLEM[2]} => ?"
    )


@pytest.fixture(scope="module")
def snagged(meta):
    return _run_to_first_snag(meta)


def test_a_snag_sets_the_temperature_to_100_and_clamps_it(snagged):
    """``answers.ss:1183-1184``: ``(set! *temperature* 100)`` **and**
    ``(set! *temperature-clamped?* #t)``.

    Petacat clamped at the *current* value with a comment claiming to reproduce
    Metacat.  A snag happens precisely when a strong rule was about to apply — at low
    temperature — so that pinned the run greedy on the interpretation that had just
    failed, the exact opposite of the reference's maximally-random escape regime.
    """
    runner, _ = snagged
    assert runner.ctx.temperature.clamped
    assert runner.ctx.temperature.value == 100.0


def test_the_snag_response_empties_the_coderack_and_reposts(snagged):
    """``answers.ss:1189-1190``: ``delete-all-codelets`` then ``post-initial-codelets``.

    The evaluators and builders of the failed interpretation must not survive the
    snag — that reset is what the architecture's escape behaviour is built on, and
    none of it existed.  The Scheme's separate purge of proposed bonds, groups and
    bridges needs no counterpart: its own comment says deleting the codelets erases
    them, and in Petacat a proposed structure *is* a codelet argument.
    """
    runner, before = snagged
    after = {c.id for b in runner.ctx.coderack.bins for c in b.codelets}

    assert before, "nothing was on the rack before the snag, so this proves nothing"
    assert not (before & after), "codelets from before the snag survived it"

    # The reposted population is bottom-up scouts, two per Workspace object, plus
    # whatever the update cycle that follows chose to post.
    types = runner.ctx.coderack.get_codelet_type_counts()
    num_objects = len(runner.ctx.workspace.all_objects)
    assert types.get("bottom-up-bond-scout", 0) >= num_objects
    assert types.get("bottom-up-bridge-scout", 0) >= num_objects


def test_the_snag_event_carries_the_failed_interpretation(snagged):
    """``trace.ss:1050-1073``: the type, the objects, the rules, and a snapshot of the
    Workspace as it stood."""
    runner, _ = snagged
    snag = next(e for e in runner.ctx.trace.events if isinstance(e, SnagEvent))

    assert snag.snag_type in {"swap", "conflict", "change"}
    assert snag.snag_rule is not None
    assert snag.translated_rule is not None
    assert snag.snag_objects
    assert snag.workspace_structures, (
        "no structure snapshot, so progress since the snag cannot be measured"
    )
    assert snag.snag_concept_pattern is not None
    assert snag.snag_concept_pattern["entries"], (
        "the snag objects' descriptors were not collected, so activation clamps nothing"
    )


def test_the_snag_theme_pattern_survives_an_empty_dominant_pattern(snagged):
    """``trace.ss:1031-1039, 1060-1067``: the pattern is derived from the snag
    objects' vertical concept-mappings, not from Themespace dominance.

    Dominance needs a >90-point cluster lead, so a cluster with two live themes
    contributes nothing and the dominant pattern is routinely empty — while the
    mappings the failed interpretation rested on are right there.  The jootser's
    snag-overlap table then compared empty patterns and never fired.
    """
    runner, _ = snagged
    snag = next(e for e in runner.ctx.trace.events if isinstance(e, SnagEvent))

    assert snag.snag_concept_mappings, "no vertical mappings to derive a pattern from"
    assert len(snag.snag_theme_pattern) > 1, "the snag theme pattern is empty"

    # Every entry is a (dimension, relation) pair drawn from those mappings.
    from server.engine.themes import relation_name_for_label

    derived = {
        (
            cm.description_type1.name,
            relation_name_for_label(cm.label),
        )
        for cm in snag.snag_concept_mappings
    }
    assert set(snag.snag_theme_pattern[1:]) == derived


def test_the_snag_objects_are_maximally_salient(snagged):
    """``trace.ss:1156-1157``: ``clamp-salience`` on each snag object, so attention
    returns to the impasse rather than wandering with the temperature at 100."""
    runner, _ = snagged
    snag = next(e for e in runner.ctx.trace.events if isinstance(e, SnagEvent))
    clamped = [o for o in snag.snag_objects if getattr(o, "salience_clamped", False)]
    assert clamped, "no snag object had its salience clamped"
    for obj in clamped:
        assert obj.salience["intra"] == 100


def test_the_snag_descriptors_are_frozen_in_the_slipnet(snagged):
    """``trace.ss:1158`` -> ``trace.ss:1547-1552``: the snag concept pattern is clamped,
    which pins each descriptor at max activation."""
    runner, _ = snagged
    snag = next(e for e in runner.ctx.trace.events if isinstance(e, SnagEvent))
    for entry in snag.snag_concept_pattern["entries"]:
        node = runner.ctx.slipnet.nodes.get(entry["node"])
        if node is None:
            continue
        assert node.frozen, f"{entry['node']} was not clamped by the snag"
        assert node.activation == entry["activation"]


def test_the_run_carries_on_after_the_snag(meta, snagged):
    """The snag response is a restart, not a stop: the rack is repopulated and the
    next codelets run.  A response that emptied the rack without reposting would
    fall into ``step_mcat``'s empty-rack repost instead, which also re-clamps the
    initially-relevant slipnodes — a different state entirely.
    """
    runner, _ = snagged
    at_snag = runner.ctx.codelet_count
    for _ in range(50):
        runner.step_mcat()
    assert runner.ctx.codelet_count > at_snag
