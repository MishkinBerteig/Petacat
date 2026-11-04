"""EN9: answers, comparison, memory and commentary read the configuration.

* G5: the nodes the five theme dimensions resolve to are the nodes the old literals named;
* an absent template key omits its text, is counted once, and changes no perception; the one
  exception, ``comparison_judgment_priority``, makes the verdict "neither";
* Episodic Memory carried from an earlier run that names a removed node, link label or codelet
  type: the next run, under the reduced configuration, completes with no exception, and the
  names it cannot resolve contribute no match, no distance and no activation;
* G9 for the roles these files convert.
"""

from __future__ import annotations

import copy
from dataclasses import replace

import pytest

from server.engine.answer_comparison import (
    AnswerComparison,
    compare_answers_text,
    explain_answer,
    theme_dimensions,
)
from server.engine.commentary import CommentaryLog, emit_answer_discovered, emit_reminding
from server.engine.memory import AnswerDescription, EpisodicMemory
from server.engine.numeric.backend import use_backend
from server.engine.rng import RNG
from server.engine.runner import EngineRunner
from server.engine.roles import absent
from tests.support import golden_baseline as gb
from tests.support import reduced_configurations as rc
from tests.support.role_table import SINGLE_ROLES


pytestmark = pytest.mark.numeric_matrix


@pytest.fixture(scope="module")
def meta():
    return gb.load_meta()


# --- G5 ---------------------------------------------------------------------------------


def test_the_theme_dimensions_are_the_nodes_the_old_literals_named(meta) -> None:
    dims = theme_dimensions(meta)
    assert dims.string_position == "plato-string-position-category"
    assert dims.alphabetic_position == "plato-alphabetic-position-category"
    assert dims.group_category == "plato-group-category"
    assert dims.bond_facet == "plato-bond-facet"
    assert dims.direction == "plato-direction-category"


def test_a_removed_dimension_is_the_roles_absent_name() -> None:
    provider = rc.provider(rc.role_unbound("dimension.bond_facet"))
    dims = theme_dimensions(provider)
    assert dims.bond_facet == absent("dimension.bond_facet").name
    assert dims.string_position == "plato-string-position-category"


# --- the answer descriptions the runs below store ---------------------------------------


def _answer(problem, themes, signature, *, rule_abstractness=50.0, quality=70.0, **kw):
    return AnswerDescription(
        problem=problem,
        top_rule_description="rule",
        bottom_rule_description="rule",
        top_rule_quality=50.0,
        bottom_rule_quality=50.0,
        quality=quality,
        temperature=40.0,
        themes=themes,
        unjustified_slippages=[],
        top_rule_abstractness=rule_abstractness,
        theme_abstractness=60.0,
        top_rule_signature=signature,
        bottom_rule_signature=signature,
        **kw,
    )


SIG_SUCCESSOR = [["intrinsic", ["plato-letter", "plato-string-position-category", "plato-rightmost"],
                  [["plato-letter-category", None, None, "plato-successor"]]]]
SIG_LITERAL_D = [["intrinsic", ["plato-letter", "plato-string-position-category", "plato-rightmost"],
                  [["plato-letter-category", None, "plato-d", None]]]]
PROBLEM = ("abc", "abd", "ijk")
THEMES = {"plato-string-position-category": "identity", "plato-direction-category": "opposite"}


def _pair():
    return (
        _answer((*PROBLEM, "ijl"), dict(THEMES), SIG_SUCCESSOR),
        _answer((*PROBLEM, "ijd"), dict(THEMES), SIG_LITERAL_D, rule_abstractness=10.0),
    )


# --- template keys ----------------------------------------------------------------------


def test_the_standard_templates_note_no_missing_key(meta) -> None:
    a, b = _pair()
    result = compare_answers_text(a, b, None, None, meta=meta)
    assert result["warnings"] == []
    assert explain_answer(a, None, meta.commentary_templates, meta=meta)["warnings"] == []


def test_a_missing_template_key_omits_its_text_and_is_counted_once(meta) -> None:
    a, b = _pair()
    templates = copy.deepcopy(meta.commentary_templates)
    full = compare_answers_text(a, b, None, templates, meta=meta)
    del templates["comparison_templates"]["unique_theme"]
    del templates["comparison_templates"]["rule_explanation"]["intro_another_key"]
    result = compare_answers_text(a, b, None, templates, meta=meta)
    assert "comparison_templates.unique_theme" not in " ".join(full["warnings"])
    assert any(w.startswith("comparison_templates.unique_theme") for w in result["warnings"])
    assert len(result["warnings"]) == len(set(result["warnings"]))
    # the preference does not depend on a text template
    assert result["preferred"] == full["preferred"]


def test_a_missing_theme_template_changes_text_only(meta) -> None:
    a, b = _pair()
    templates = copy.deepcopy(meta.commentary_templates)
    del templates["theme_phrase_templates"]
    result = explain_answer(a, None, templates, meta=meta)
    assert result["explanation"] != explain_answer(a, None, meta.commentary_templates, meta=meta)["explanation"]
    assert any(w.startswith("theme_phrase_templates") for w in result["warnings"])


def test_an_absent_judgment_priority_judges_no_preference(meta) -> None:
    clean = _answer((*PROBLEM, "ijl"), dict(THEMES), SIG_SUCCESSOR, quality=90.0)
    poor = _answer((*PROBLEM, "ijd"), {}, SIG_SUCCESSOR, quality=20.0)
    standard = compare_answers_text(clean, poor, None, None, meta=meta)
    assert standard["preferred"]["answer"] is not None  # a priority list does pick one
    templates = copy.deepcopy(meta.commentary_templates)
    del templates["comparison_judgment_priority"]
    result = compare_answers_text(clean, poor, None, templates, meta=meta)
    assert result["preferred"] == {"answer": None, "reason": ""}
    assert "comparison_judgment_priority" in result["warnings"]
    # an empty list is the same: nothing to try
    templates["comparison_judgment_priority"] = []
    assert compare_answers_text(clean, poor, None, templates, meta=meta)["preferred"]["answer"] is None
    # and the structured comparison agrees
    memory = EpisodicMemory()
    templates.pop("comparison_judgment_priority")
    assert memory.compare_answers(clean, poor, templates, meta=meta)["preferred"]["answer"] is None


def test_a_missing_commentary_key_is_noted_in_the_runs_log_once(meta) -> None:
    templates = copy.deepcopy(meta.commentary_templates)
    del templates["answer_reporting"]["reminding"]["strongly"]
    log = CommentaryLog()
    emit_reminding(log, "ijl", "abc -> abd, ijk -> ?", 90, 5, templates)
    emit_reminding(log, "ijl", "abc -> abd, ijk -> ?", 90, 6, templates)
    assert log.warnings == {"answer_reporting.reminding.strongly"}
    assert log.count == 2  # the paragraph is still said, without that text
    clean = CommentaryLog()
    emit_answer_discovered(clean, "ijl", 70, "pretty good", 30, 5, 0, meta.commentary_templates)
    assert not clean.warnings


# --- Episodic Memory that names what the configuration no longer has ---------------------


def test_unresolved_names_add_no_distance_and_are_counted(meta) -> None:
    a, b = _pair()
    memory = EpisodicMemory()
    standard = memory.distance(a, b, meta)
    assert not memory.unresolved_names
    # plato-successor and plato-d are named by the two rules' differing clause
    reduced = rc.provider(rc.node_removed("plato-successor"))
    after = memory.distance(a, b, reduced)
    assert after <= standard
    assert memory.unresolved_names == {"plato-successor"}
    memory.clear_activations()  # every run start
    assert not memory.unresolved_names


def test_a_removed_dimension_in_a_stored_theme_matches_nothing(meta) -> None:
    a, b = _pair()
    b.themes = b.vertical_themes = {"plato-string-position-category": "identity"}
    memory = EpisodicMemory()
    with_direction = memory.distance(a, b, meta)
    reduced = rc.provider(rc.node_removed("plato-direction-category"))
    without = memory.distance(a, b, reduced)
    assert without < with_direction
    assert "plato-direction-category" in memory.unresolved_names


def test_a_removed_relation_node_in_a_stored_theme_is_unavailable(meta) -> None:
    a, b = _pair()
    reduced = rc.provider(rc.node_removed("plato-opposite"))
    memory = EpisodicMemory()
    comparison = AnswerComparison(a, b, memory, meta=reduced)
    assert ("plato-direction-category", "opposite") not in comparison.all_themes1
    assert ("plato-string-position-category", "identity") in comparison.all_themes1
    assert "opposite" in comparison.unresolved_names


def test_stored_text_is_kept(meta) -> None:
    a, b = _pair()
    reduced = rc.provider(rc.node_removed("plato-successor"))
    memory = EpisodicMemory()
    memory.distance(a, b, reduced)
    assert a.top_rule_description == "rule" and a.top_rule_signature == SIG_SUCCESSOR
    assert a.themes == THEMES


# The real carry path: one EpisodicMemory object passed from run to run through
# ``init_mcat(memory=...)``, which is how Metacat Mode's episodic runs inherit it.

CARRY_STEPS = 1500


def _run(meta, memory, seed, steps=CARRY_STEPS):
    runner = EngineRunner(meta)
    with use_backend(gb.BACKEND):
        runner.init_mcat(*PROBLEM, seed=seed, rng=RNG(seed), memory=memory)
        runner.run_mcat(max_steps=steps)
    return runner


@pytest.fixture(scope="module")
def carried(meta):
    """A memory built by three real runs under the Metacat Standard Configuration."""
    memory = EpisodicMemory()
    for seed in (1, 2, 3):
        _run(meta, memory, seed)
    assert len(memory.answers) >= 2
    names = {n for a in memory.answers for n in _flat(a.top_rule_signature)}
    assert {"plato-successor", "plato-rightmost"} <= names
    return memory


def _flat(value):
    if isinstance(value, (list, tuple)):
        for item in value:
            yield from _flat(item)
    elif isinstance(value, str):
        yield value


def _copy_memory(memory):
    """An independent memory with the same descriptions (a description may hold live
    objects that cannot be deep-copied, so each is copied one level, as stored)."""
    clone = EpisodicMemory()
    clone.answers = [replace(a) for a in memory.answers]
    clone.snags = [replace(s) for s in memory.snags]
    clone.ids = memory.ids  # a counter; sharing it only advances it
    return clone


def _carry_into(carried, reduced_meta):
    """The carried memory, as the next run inherits it (a copy so the cases are independent)."""
    memory = _copy_memory(carried)
    runner = _run(reduced_meta, memory, 1, steps=3000)
    return memory, runner


#: (reduction, the names the next run's reminding must report as unresolved).  Seed 1 finds
#: an answer (and so is reminded) under the second and third; the others are bounded runs.
REDUCTIONS = [
    pytest.param(lambda: rc.node_removed("plato-rightmost"), set(), id="removed-node-position"),
    pytest.param(lambda: rc.node_removed("plato-d"), set(), id="removed-node-letter"),
    pytest.param(
        lambda: rc.node_removed("plato-direction-category"),
        {"plato-direction-category"},
        id="removed-dimension",
    ),
    pytest.param(
        lambda: rc.node_removed("plato-successor"), {"plato-successor"}, id="removed-link-label"
    ),
    pytest.param(lambda: rc.node_removed("plato-opposite"), set(), id="removed-link-label-opposite"),
    pytest.param(lambda: rc.role_unbound("evaluator.bond"), set(), id="removed-codelet-type"),
]


@pytest.mark.parametrize("reduction, reported", REDUCTIONS)
def test_the_next_run_completes_under_the_reduced_configuration(
    carried, reduction, reported
) -> None:
    reduced = rc.provider(reduction())
    memory, runner = _carry_into(carried, reduced)
    assert runner.ctx is not None
    assert memory.unresolved_names == reported
    # the earlier runs' answers are still in memory, untouched
    assert len(memory.answers) >= len(carried.answers)
    for old, kept in zip(memory.answers[-len(carried.answers):], carried.answers):
        assert old.top_rule_signature == kept.top_rule_signature
        assert old.themes == kept.themes


def test_a_removed_name_in_a_reminding_is_reported_not_matched(carried, meta) -> None:
    reduced = rc.provider(rc.node_removed("plato-successor"))
    memory = _copy_memory(carried)
    new = _answer((*PROBLEM, "ijz"), dict(THEMES), SIG_SUCCESSOR)
    memory.clear_activations()
    memory.find_remindings(new, 5.0, meta=reduced)
    assert "plato-successor" in memory.unresolved_names
    # nothing was read as depth 0: every activation is a whole number in [0, 100]
    assert all(0 <= a.activation <= 100 for a in memory.answers)


# --- G9 for the roles these files convert -----------------------------------------------

G9_ROLES = (
    "dimension.length", "dimension.bond_facet", "object.letter", "dimension.letter_category",
    "dimension.object_category", "dimension.string_position", "dimension.alphabetic_position",
    "dimension.group_category", "dimension.direction", "object.group",
)


@pytest.mark.slow
@pytest.mark.parametrize("role", G9_ROLES)
def test_g9_the_run_completes_with_the_role_unbound_and_memory_carried(carried, role) -> None:
    reduced = rc.provider(rc.node_removed(SINGLE_ROLES[role]))
    memory = _copy_memory(carried)
    _run(reduced, memory, 5, steps=400)
    _run(reduced, memory, 6, steps=400)
