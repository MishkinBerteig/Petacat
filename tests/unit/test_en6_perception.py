"""EN6: the perception structures (bonds, groups, bridges, concept mappings, images) read roles,
relations, the alphabet and node columns, never node names.

* G5: every role those files read is held by the node the old literal named;
* the recruitment of ``propose_bridge`` posts in the Scheme's order, through the recruit roles;
* identity absent never raises, and labels nothing;
* G9: with each role those files read unbound (the binding dropped, or the node removed with its
  cascade), a run is built and stepped on every demo problem with no exception;
* rename invariance: renaming every role-bound, letter and number node to an opaque name, with
  the display columns kept, leaves complete runs (answers, codelet counts, RNG draws, the
  English) unchanged.
"""

from __future__ import annotations

import copy
import os

import pytest

from server.engine import bridges
from server.engine.metadata import MetadataProvider
from server.engine.numeric.backend import use_backend
from server.engine.rng import RNG
from server.engine.runner import EngineRunner
from server.engine.slipnet import Slipnet
from tests.support import golden_baseline as gb
from tests.support import reduced_configurations as rc
from tests.support.configuration_cascade import load_documents
from tests.support.role_table import SINGLE_ROLES

pytestmark = pytest.mark.numeric_matrix

SEED = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")

#: The node roles the five perception files, descriptions.py and images.py read.
ROLES_READ = tuple(
    r for r in SINGLE_ROLES if not r.startswith("alphabet.")
)
CODELET_ROLES_READ = ("recruit.description_scout", "recruit.group_scout_category")
RELATIONS = {
    "identity": "plato-identity",
    "opposite": "plato-opposite",
    "successor": "plato-successor",
    "predecessor": "plato-predecessor",
}


@pytest.fixture(scope="module")
def meta():
    return MetadataProvider.from_standard_configuration(SEED)


@pytest.fixture(scope="module")
def slipnet(meta):
    return Slipnet.from_metadata(meta)


# --- G5 ----------------------------------------------------------------------------------


@pytest.mark.parametrize("role", ROLES_READ)
def test_the_role_is_held_by_the_node_the_old_literal_named(slipnet, role) -> None:
    node = slipnet.nodes[SINGLE_ROLES[role]]
    assert getattr(slipnet.roles, role.replace(".", "_")) is node
    assert role in node.roles


@pytest.mark.parametrize("relation", sorted(RELATIONS))
def test_the_relation_is_the_node_the_old_literal_named(slipnet, relation) -> None:
    assert slipnet.relation(relation) is slipnet.nodes[RELATIONS[relation]]
    # the descriptors know the identity node themselves (no sentinel, no Slipnet handle)
    node = slipnet.nodes["plato-a"]
    assert node.relations is slipnet.relations


def test_the_recruit_roles_name_the_codelet_types_the_old_literals_named(slipnet) -> None:
    assert slipnet.roles.recruit_description_scout.name == "top-down-description-scout"
    assert slipnet.roles.recruit_group_scout_category.name == "top-down-group-scout:category"


# --- the identity label ------------------------------------------------------------------


def test_identical_descriptors_are_labelled_with_the_identity_node(slipnet) -> None:
    a, b = slipnet.nodes["plato-a"], slipnet.nodes["plato-b"]
    assert bridges._label_node(a, a) is slipnet.nodes["plato-identity"]
    assert bridges._label_node(a, b) is slipnet.nodes["plato-successor"]
    assert bridges._label_node(b, a) is slipnet.nodes["plato-predecessor"]
    assert bridges._label_node(a, slipnet.nodes["plato-c"]) is None
    assert not hasattr(bridges, "_IdentitySentinel")
    assert not hasattr(bridges, "_IDENTITY_SENTINEL")


def test_without_identity_the_same_descriptor_has_no_label_and_nothing_raises() -> None:
    s = Slipnet.from_metadata(rc.provider(rc.node_removed("plato-identity")))
    a = s.nodes["plato-a"]
    assert bridges._label_node(a, a) is None
    assert s.get_label(a, a) is None
    from server.engine import images
    from server.engine.concept_mappings import ConceptMapping

    assert images.get_label(a, a, s) is None
    assert images.relationship_between([a], s) is None
    cm = ConceptMapping(s.roles.dimension_letter_category, a, s.roles.dimension_letter_category, a, None)
    assert cm.label is None and cm.is_identity
    assert not cm.identity_or_opposite_mapping
    # an unlabelled mapping reads as `diff` in the Themespace, never as the absent identity
    assert bridges._label_relation(a, a) == "diff"


# --- the recruitment order (plan 4.2, the posting order of propose_bridge) ----------------


def _record_recruitment(provider, problem, steps, seed=1):
    """Run, and record the codelets each differing-length ``propose_bridge`` posts."""
    calls: list[dict] = []
    real = bridges._propose_bridge_side_effects

    def spy(bridge_type, object1, object2, ctx):
        posted: list = []
        if ctx is not None:
            original = ctx.coderack.post

            def post(codelet, *a, **k):
                posted.append(codelet)
                return original(codelet, *a, **k)

            ctx.coderack.post = post  # type: ignore[method-assign]
        try:
            real(bridge_type, object1, object2, ctx)
        finally:
            if ctx is not None:
                del ctx.coderack.post  # restore the class's method
        calls.append({"o1": object1, "o2": object2, "type": bridge_type, "posted": posted})

    bridges._propose_bridge_side_effects = spy  # type: ignore[assignment]
    try:
        runner = EngineRunner(provider)
        with use_backend(gb.BACKEND):
            runner.init_mcat(*problem, seed=seed, rng=RNG(seed))
            for _ in range(steps):
                if runner.step_mcat().codelet_type is None:
                    break
    finally:
        bridges._propose_bridge_side_effects = real  # type: ignore[assignment]
    return calls


def test_a_differing_length_bridge_posts_description_scouts_then_group_scouts(meta) -> None:
    calls = _record_recruitment(meta, ("abc", "abd", "ijkk"), 3000)
    differing = [c for c in calls if c["posted"]]
    assert differing, "the run must propose a bridge between objects of different lengths"
    with_group_scout = 0
    for call in differing:
        o1, o2 = call["o1"], call["o2"]
        expected = [("top-down-description-scout", getattr(o.string, "string_type", None)) for o in (o1, o2)]
        for letter, group in ((o1, o2), (o2, o1)):
            if hasattr(letter, "objects") or not hasattr(group, "objects"):
                continue
            if getattr(group, "group_category", None) is None:
                continue
            expected.append(("top-down-group-scout:category", getattr(letter.string, "string_type", None)))
        got = [
            (c.codelet_type if hasattr(c, "codelet_type") else c.type_name,
             getattr(c.arguments.get("scope"), "string_type", None))
            for c in call["posted"]
        ]
        assert got == expected
        with_group_scout += any(g[0] == "top-down-group-scout:category" for g in got)
        assert len({c.urgency for c in call["posted"]}) == 1
    assert with_group_scout, "a letter facing a group must recruit a group scout"


@pytest.mark.parametrize(
    "role,posts",
    [
        ("recruit.description_scout", "top-down-description-scout"),
        ("recruit.group_scout_category", "top-down-group-scout:category"),
    ],
)
def test_an_unbound_recruit_role_posts_nothing_of_its_kind(role, posts) -> None:
    provider = rc.provider(rc.role_unbound(role))
    calls = _record_recruitment(provider, ("abc", "abd", "ijkk"), 3000)
    kinds = {
        (c.codelet_type if hasattr(c, "codelet_type") else c.type_name)
        for call in calls for c in call["posted"]
    }
    assert posts not in kinds


# --- G9 ----------------------------------------------------------------------------------

G9_STEPS = 500
G9_JUSTIFY_STEPS = 1500


def _step(provider, problem, answer=None, seed=1, steps=G9_STEPS) -> None:
    runner = EngineRunner(provider)
    with use_backend(gb.BACKEND):
        runner.init_mcat(*problem, answer=answer, seed=seed, rng=RNG(seed))
        for _ in range(steps):
            if runner.step_mcat().codelet_type is None:
                break


def _every_demo(provider) -> None:
    triples, justify = gb.demo_problems()
    for problem in triples:
        _step(provider, problem)
    for problem, answer in justify[:2]:
        _step(provider, problem, answer=answer, steps=G9_JUSTIFY_STEPS)


def _binding_dropped(role: str) -> rc.Reduced:
    """The role unbound but its node still in the Slipnet."""
    reduced = rc.standard()
    doc = reduced.documents["roles.json"]
    if role in SINGLE_ROLES or role.startswith("rule.") or role.startswith("answer."):
        doc["node_roles"] = [r for r in doc["node_roles"] if r["role"] != role]
    else:
        doc["codelet_roles"] = [r for r in doc["codelet_roles"] if r["role"] != role]
    return reduced


@pytest.mark.slow
@pytest.mark.parametrize("role", ROLES_READ + CODELET_ROLES_READ)
def test_g9_role_unbound_node_removed_runs_every_demo_problem(role) -> None:
    _every_demo(rc.provider(rc.role_unbound(role)))


@pytest.mark.slow
@pytest.mark.parametrize("role", ROLES_READ + CODELET_ROLES_READ)
def test_g9_role_binding_dropped_runs_every_demo_problem(role) -> None:
    _every_demo(rc.provider(_binding_dropped(role)))


@pytest.mark.slow
@pytest.mark.parametrize("relation", sorted(RELATIONS))
def test_g9_relation_node_removed_runs_every_demo_problem(relation) -> None:
    _every_demo(rc.provider(rc.node_removed(RELATIONS[relation])))


# --- rename invariance (plan 4.2) --------------------------------------------------------


def _renamed_provider():
    import tempfile
    from pathlib import Path

    from tests.support.renamed_configuration import renamed

    docs, mapping = renamed(load_documents())
    reduced = rc.Reduced("renamed", docs, rc.Report())
    return rc.provider(reduced), mapping


def _old_names(text: str, mapping: dict[str, str]) -> str:
    """*text* with every renamed node's new name written as its old one.  Identifiers (the
    names that key a Slipnet snapshot in a trace picture) are the one place a name is data
    rather than text; the display text itself must need no such help."""
    import re

    back = {new: old for old, new in mapping.items()}
    return re.sub(r"(?<![A-Za-z0-9_-])n\d+(?![A-Za-z0-9_-])", lambda m: back.get(m.group(0), m.group(0)), text)


def _observe(provider, problem, seed, answer=None, memory=None, mapping=None):
    runner, rng, draws, types, init_draws = gb.run_observed(provider, problem, seed, answer, memory, True)
    ctx = runner.ctx
    english = gb.english_corpus(runner, provider)
    if mapping:
        # only the picture payloads (ids of the Slipnet snapshot) are read back
        english["trace_display"] = [_old_names(t, mapping) for t in english["trace_display"]]
    answers = list(runner._answers)
    return {
        "status": runner.status,
        "answer": answers[-1] if answers else None,
        "codelets": ctx.codelet_count,
        "rng_total": rng.call_count,
        "rng_init": init_draws,
        "draws": draws,
        "types": types,
        "english": english,
    }


RENAME_CASES = [
    (("abc", "abd", "xyz"), 1),
    (("abc", "abd", "xyz"), 3),
    (("abc", "abd", "ijk"), 2),
    (("abc", "abd", "mrrjjj"), 1),
    (("abc", "abd", "mrrkkk"), 4),
    (("aabc", "aabd", "ijkk"), 2),
]


@pytest.mark.slow
def test_renaming_the_role_bound_letter_and_number_nodes_changes_nothing(meta) -> None:
    renamed_meta, mapping = _renamed_provider()
    assert mapping["plato-a"] != "plato-a" and "plato-length" in mapping
    with use_backend(gb.BACKEND):
        for problem, seed in RENAME_CASES:
            expected = _observe(meta, problem, seed)
            got = _observe(renamed_meta, problem, seed, mapping=mapping)
            assert got == expected, (problem, seed)


@pytest.mark.slow
def test_renaming_changes_nothing_in_a_justify_run_or_with_memory_carried(meta) -> None:
    from server.engine.memory import EpisodicMemory

    renamed_meta, mapping = _renamed_provider()
    triples, justify = gb.demo_problems()
    with use_backend(gb.BACKEND):
        problem, answer = justify[0]
        assert _observe(renamed_meta, problem, 1, answer, mapping=mapping) == _observe(meta, problem, 1, answer)
        # a short episode: the Episodic Memory a run leaves is carried into the next
        mem_a, mem_b = EpisodicMemory(), EpisodicMemory()
        for seed in (1, 2, 3):
            expected = _observe(meta, ("abc", "abd", "xyz"), seed, memory=mem_a)
            got = _observe(renamed_meta, ("abc", "abd", "xyz"), seed, memory=mem_b, mapping=mapping)
            assert got == expected, seed
