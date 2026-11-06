"""Stage 6: the initial-description program is configuration (ruling 10).

``initial_description_rules`` and ``initial_activation_rules`` replace the block of
``runner.py`` that gave every letter its first descriptions and put the first concepts active.
Removing the middle-of-an-odd-string description changes 40 of 48 runs, so the program is
cognition.  This file checks that

1. the Metacat Standard Configuration's rows give every letter exactly the descriptions, in
   exactly the order, that the code gave it (the oracle is ``tests/support/old_initial_program.py``,
   the block as it stood), and put the same concepts active;
2. the rows are applied in ``ordinal`` order, a rule whose role nothing holds is dropped, and a
   condition the engine does not define stops the run at its start;
3. removing a row, reordering two, and switching off a descriptor's activation each change a run
   (``numeric_matrix``: they run on every backend this machine has).
"""

from __future__ import annotations

import dataclasses
import os

import pytest

from server.engine import initial_program
from server.engine.metadata import MetadataProvider
from server.engine.start_check import RunStartError, check_run_start, require_run_start
from tests.support.run_fingerprint import fingerprint

pytestmark = pytest.mark.numeric_matrix

SEED = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")

PROBLEMS = [
    ("abc", "abd", "xyz"), ("a", "b", "z"), ("abcde", "abcdf", "wxyzv"), ("aabb", "cc", "aabb"),
    ("eqe", "qeq", "abbbc"), ("ab", "c", "ab"), ("zyx", "xyy", "z"),
]


@pytest.fixture(scope="module")
def meta() -> MetadataProvider:
    return MetadataProvider.from_standard_configuration(SEED)


def _initialised(meta, problem, program):
    """A runner initialised on *problem* with the initial program *program* (a function)."""
    from unittest import mock

    from server.engine.rng import RNG
    from server.engine.runner import EngineRunner

    runner = EngineRunner(meta)
    runner.verbose_mode = False
    if program is None:
        runner.init_mcat(*problem, answer=None, seed=1, rng=RNG(1))
    else:
        with mock.patch("server.engine.initial_program.add_initial_descriptions", program), \
                mock.patch("server.engine.initial_program.apply_initial_activations", lambda *a: None):
            runner.init_mcat(*problem, answer=None, seed=1, rng=RNG(1))
    return runner


def _descriptions(runner):
    ws = runner.ctx.workspace
    return [
        [(d.description_type.name, d.descriptor.name, d.proposal_level) for d in o.descriptions]
        for s in ws.all_strings for o in s.objects
    ]


# -------------------------------------------------------------- 1. the rows are the old program


def test_the_seed_rows_are_the_descriptions_and_the_one_activation(meta):
    rows = meta.initial_description_rules
    assert [r.subject for r in rows] == ["letter"] * 6 + ["group"] * 10 + ["translated_letter"] * 2
    assert [r.ordinal for r in rows] == list(range(18))
    assert [r.rule_key for r in rows if r.subject == "group"] == [
        "group-object-category", "group-group-category", "group-bond-category", "group-direction",
        "group-string-position-whole", "group-string-position-leftmost", "group-string-position-middle",
        "group-string-position-rightmost", "group-bond-facet", "group-letter-category"]
    assert [r.rule_key for r in rows if r.bond_description] == ["group-bond-category", "group-bond-facet"]
    assert not any(r.built for r in rows if r.subject == "translated_letter")
    assert [r.rule_key for r in rows if r.subject == "letter"] == [
        "object-category-letter", "letter-category", "string-position-single",
        "string-position-leftmost", "string-position-rightmost", "string-position-middle",
    ]
    letters = [r for r in rows if r.subject == "letter"]
    assert [r.condition for r in letters] == ["always", "always", "single", "leftmost", "rightmost", "middle"]
    assert all(r.activate_descriptor for r in letters)
    assert not any(r.activate_descriptor for r in rows if r.subject != "letter")
    assert [(r.node_role, r.condition) for r in meta.initial_activation_rules] == [
        ("dimension.object_category", "any_single_letter_string")]


def test_the_closed_sets_are_the_ones_the_readme_documents():
    assert initial_program.DESCRIPTION_CONDITIONS == ("always", "single", "leftmost", "rightmost", "middle")
    assert initial_program.ACTIVATION_CONDITIONS == ("always", "any_single_letter_string")
    assert initial_program.GROUP_CONDITIONS == (
        "always", "has_direction", "whole", "leftmost", "middle", "rightmost", "facet_is_letter_category")
    assert initial_program.TRANSLATED_CONDITIONS == ("always",)
    assert initial_program.SUBJECTS == ("letter", "translated_letter", "group")
    assert initial_program.DESCRIPTOR_SOURCES == (
        "role", "letter_category", "group_category", "bond_category", "direction", "bond_facet",
        "initial_letter_category")


@pytest.mark.parametrize("problem", PROBLEMS)
def test_the_rows_give_every_letter_the_descriptions_the_code_gave_it(meta, problem):
    from tests.support.old_initial_program import old_add_initial_descriptions

    def old(workspace, slipnet, m):
        # the activation block of the old code ran first, inside the same function
        old_add_initial_descriptions(workspace, slipnet, m)

    with_rows = _initialised(meta, problem, None)
    with_code = _initialised(meta, problem, old)
    assert _descriptions(with_rows) == _descriptions(with_code)
    assert [n.activation for n in with_rows.ctx.slipnet.nodes.values()] == [
        n.activation for n in with_code.ctx.slipnet.nodes.values()]


# -------------------------------------------------------------- 2. how the rows are applied


def _with_rules(meta, **changes):
    return dataclasses.replace(meta, **changes)


def test_rules_are_applied_in_ordinal_order(meta):
    """Each description goes to the front of the letter's list, so the last rule is first."""
    runner = _initialised(meta, ("abc", "abd", "xyz"), None)
    first_letter = runner.ctx.workspace.initial_string.objects[0]
    names = [d.description_type.name for d in first_letter.descriptions]
    roles = runner.ctx.slipnet.roles
    # leftmost, then rightmost (nothing: a is not last), then middle (nothing); letter-category and
    # object-category before them in the rule order, so after them in the list
    assert names == [roles.dimension_string_position.name, roles.dimension_letter_category.name,
                     roles.dimension_object_category.name]


def test_a_rule_whose_role_nothing_holds_is_dropped(meta):
    bindings = tuple(b for b in meta.node_roles if b.role != "position.middle")
    runner = _initialised(_with_rules(meta, node_roles=bindings), ("abc", "abd", "xyz"), None)
    descriptors = {d.descriptor.name for o in runner.ctx.workspace.initial_string.objects for d in o.descriptions}
    assert "plato-middle" not in descriptors and "plato-leftmost" in descriptors


def test_an_unknown_condition_stops_the_run_at_its_start(meta):
    rules = tuple(
        dataclasses.replace(r, condition="second") if r.rule_key == "string-position-middle" else r
        for r in meta.initial_description_rules)
    problems = check_run_start(_with_rules(meta, initial_description_rules=rules))
    assert [(p.kind, p.name) for p in problems] == [("initial-program rule", "string-position-middle")]
    with pytest.raises(RunStartError):
        require_run_start(_with_rules(meta, initial_description_rules=rules))


def test_a_condition_or_source_of_another_subject_stops_the_run_at_its_start(meta):
    rows = tuple(
        dataclasses.replace(r, condition="has_direction") if r.rule_key == "string-position-middle"
        else dataclasses.replace(r, descriptor_source="direction") if r.rule_key == "translated-letter-letter-category"
        else dataclasses.replace(r, subject="word") if r.rule_key == "group-direction" else r
        for r in meta.initial_description_rules)
    got = {p.name for p in check_run_start(_with_rules(meta, initial_description_rules=rows))}
    assert got == {"string-position-middle", "translated-letter-letter-category", "group-direction"}


def test_an_unknown_descriptor_source_or_activation_condition_stops_the_run_at_its_start(meta):
    d = tuple(dataclasses.replace(r, descriptor_source="name") if r.rule_key == "letter-category" else r
              for r in meta.initial_description_rules)
    a = tuple(dataclasses.replace(r, condition="never") for r in meta.initial_activation_rules)
    got = {p.name for p in check_run_start(_with_rules(meta, initial_description_rules=d, initial_activation_rules=a))}
    assert got == {"letter-category", "object-category-when-a-string-has-one-letter"}


def test_a_configuration_with_no_rules_still_runs_to_the_end_of_its_start(meta):
    """No program means no first descriptions: the run starts, with nothing described."""
    bare = _with_rules(meta, initial_description_rules=(), initial_activation_rules=())
    require_run_start(bare)
    runner = _initialised(bare, ("abc", "abd", "xyz"), None)
    assert all(not o.descriptions for s in runner.ctx.workspace.all_strings for o in s.objects)


# -------------------------------------------------------------- 3. every moved thing moves a run

#: mutation -> (a problem and seed in which it changes the run; found with
#: agents-workspace/metacat-cleanup/round2/S6-policy/work/mutate_policy.py).
def _drop(key):
    return lambda m: _with_rules(m, initial_description_rules=tuple(
        r for r in m.initial_description_rules if r.rule_key != key))


def _swap(a, b):
    def f(m):
        rows = {r.rule_key: r for r in m.initial_description_rules}
        oa, ob = rows[a].ordinal, rows[b].ordinal
        new = [dataclasses.replace(r, ordinal=ob if r.rule_key == a else oa if r.rule_key == b else r.ordinal)
               for r in m.initial_description_rules]
        return _with_rules(m, initial_description_rules=tuple(sorted(new, key=lambda r: r.ordinal)))
    return f


def _no_activation(key):
    return lambda m: _with_rules(m, initial_description_rules=tuple(
        dataclasses.replace(r, activate_descriptor=False) if r.rule_key == key else r
        for r in m.initial_description_rules))


def _drop_many(*keys):
    return lambda m: _with_rules(m, initial_description_rules=tuple(
        r for r in m.initial_description_rules if r.rule_key not in keys))


MUTATIONS = {
    **{f"remove the {k} description": (_drop(k), ("abc", "abd", "xyz"), 1) for k in (
        "group-object-category", "group-group-category", "group-bond-category", "group-direction",
        "group-string-position-whole", "group-string-position-leftmost", "group-string-position-middle",
        "group-string-position-rightmost", "group-bond-facet", "group-letter-category",
        "translated-letter-object-category", "translated-letter-letter-category")},
    "reorder group object-category and group-category": (
        _swap("group-object-category", "group-group-category"), ("abc", "abd", "xyz"), 1),
    "reorder group direction and bond-facet": (
        _swap("group-direction", "group-bond-facet"), ("abc", "abd", "xyz"), 1),
    "a group's bond category is not a bond description": (
        lambda m: _with_rules(m, initial_description_rules=tuple(
            dataclasses.replace(r, bond_description=False) if r.rule_key == "group-bond-category" else r
            for r in m.initial_description_rules)), ("abc", "abd", "xyz"), 1),
    "a translated letter's object category is built": (
        lambda m: _with_rules(m, initial_description_rules=tuple(
            dataclasses.replace(r, built=True) if r.rule_key == "translated-letter-object-category" else r
            for r in m.initial_description_rules)), ("abc", "abd", "xyz"), 1),
    "remove the object-category description": (_drop("object-category-letter"), ("abc", "abd", "xyz"), 1),
    "remove the letter-category description": (_drop("letter-category"), ("abc", "abd", "xyz"), 1),
    "remove the single description": (_drop("string-position-single"), ("a", "b", "z"), 1),
    "remove the leftmost description": (_drop("string-position-leftmost"), ("abc", "abd", "xyz"), 1),
    "remove the rightmost description": (_drop("string-position-rightmost"), ("abc", "abd", "xyz"), 1),
    "remove the middle description": (_drop("string-position-middle"), ("abc", "abd", "xyz"), 1),
    "reorder object-category and letter-category": (
        _swap("object-category-letter", "letter-category"), ("abc", "abd", "xyz"), 1),
    "do not activate the letter-category descriptors": (
        _no_activation("letter-category"), ("abc", "abd", "xyz"), 1),
    "remove the single-letter-string activation": (
        lambda m: _with_rules(m, initial_activation_rules=()), ("a", "b", "z"), 1),
}


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_a_run_changes_when_the_program_changes(meta, name):
    mutate, problem, seed = MUTATIONS[name]
    assert fingerprint(mutate(meta), problem, seed, cap=1500) != fingerprint(meta, problem, seed, cap=1500)


# -------------------------------------------------------------- the group and translated programs vs the old code

OLD_PROBLEMS = [
    (("abc", "abd", "xyz"), 1, None), (("abc", "abd", "xyz"), 2, "dyz"), (("abc", "abd", "mrrjjj"), 1, None),
    (("aabc", "aabd", "ijkk"), 2, None), (("eqe", "qeq", "abbbc"), 1, "aaabccc"),
    (("zyx", "xyy", "z"), 1, None), (("abc", "cba", "mrrjjj"), 1, None), (("a", "b", "z"), 1, None),
]


@pytest.mark.parametrize("problem,seed,answer", OLD_PROBLEMS)
def test_the_group_and_translated_rows_run_exactly_as_the_old_code_ran(meta, problem, seed, answer):
    from unittest import mock

    from tests.support.old_initial_program import old_attach_initial_descriptions, old_describe_letters

    new = fingerprint(meta, problem, seed, answer, cap=2000)
    with mock.patch("server.engine.groups.Group._attach_initial_descriptions", old_attach_initial_descriptions), \
            mock.patch("server.engine.answers._describe_letters", old_describe_letters):
        old = fingerprint(meta, problem, seed, answer, cap=2000)
    assert new == old
