"""Renaming every bound vocabulary row changes nothing a run does (NAME-DESIGN 4.6).

Every row the engine binds a role to gets an opaque name (``v_17``) and every place that names it
follows (``tests/support/renamed_vocabulary.py``).  The six cases of the node-rename test, a
justification run, a short episode, a run with Self-watching off and runs with a person's
interventions must match the Standard Configuration in status, answer, codelet count, RNG draws,
codelet types and English, with the trace's names mapped back.
"""

from __future__ import annotations

import re

import pytest

from server.engine.metadata import MetadataProvider
from server.engine.numeric.backend import use_backend
from tests.support import golden_baseline as gb
from tests.support import reduced_configurations as rc
from tests.support.configuration_cascade import load_documents
from tests.support.renamed_vocabulary import renamed

RENAME_CASES = [
    (("abc", "abd", "xyz"), 1),
    (("abc", "abd", "xyz"), 3),
    (("abc", "abd", "ijk"), 2),
    (("abc", "abd", "mrrjjj"), 1),
    (("abc", "abd", "mrrkkk"), 4),
    (("aabc", "aabd", "ijkk"), 2),
]


@pytest.fixture(scope="module")
def meta():
    return rc.provider(rc.standard())


@pytest.fixture(scope="module")
def renamed_pair():
    docs, back = renamed(load_documents())
    return rc.provider(rc.Reduced("renamed-vocabulary", docs, rc.Report())), back


def _old_names(text: str, back: dict[str, str]) -> str:
    """The old names in *text* for the opaque ones.  A name the engine capitalises at the start of
    a sentence (``V_20 bridge from ...``) maps back to the old name capitalised, and so does one
    the narration pluralises (``Jootsing from justify-clamps...``)."""

    def old(m: re.Match) -> str:
        found = back.get(m.group(0).lower())
        if found is None:
            return m.group(0)
        return found[:1].upper() + found[1:] if m.group(0)[0] == "V" else found

    return re.sub(r"(?<![A-Za-z0-9_-])[vV][_-]\d+(?=s\.\.\.|(?![A-Za-z0-9_-]))", old, text)


def _walk_back(value, back):
    if isinstance(value, str):
        return _old_names(value, back)
    if isinstance(value, list):
        return [_walk_back(v, back) for v in value]
    if isinstance(value, dict):
        return {_old_names(k, back) if isinstance(k, str) else k: _walk_back(v, back) for k, v in value.items()}
    return value


def _observe(provider, problem, seed, back=None, answer=None, memory=None, **kw):
    runner, rng, draws, types, init_draws = gb.run_observed(provider, problem, seed, answer, memory, True, **kw)
    english = gb.english_corpus(runner, provider)
    answers = list(runner._answers)
    out = {
        "status": runner.status,
        "answer": answers[-1] if answers else None,
        "codelets": runner.ctx.codelet_count,
        "rng_total": rng.call_count,
        "rng_init": init_draws,
        "draws": draws,
        "types": types,
        "english": english,
    }
    return _walk_back(out, back) if back else out


def test_the_rename_really_renames(renamed_pair, meta) -> None:
    renamed_meta, back = renamed_pair
    v = renamed_meta.vocabulary
    assert re.fullmatch(r"v_\d+", v.bridge_type_top) and re.fullmatch(r"v_\d+", v.rule_type_top)
    assert v.bridge_type_top != v.rule_type_top
    assert back[v.bridge_type_top] == "top" and back[v.rule_type_top] == "top"
    assert meta.vocabulary.bridge_type_top == "top"
    assert all(re.fullmatch(r"v_\d+", b.name) for b in renamed_meta.vocabulary_bindings)
    assert {t.behaviour for t in renamed_meta.link_types} == {t.behaviour for t in meta.link_types}
    assert all(re.fullmatch(r"v_\d+", t.name) for t in renamed_meta.link_types)


@pytest.mark.slow
@pytest.mark.parametrize("problem,seed", RENAME_CASES)
def test_renaming_the_vocabulary_changes_nothing(meta, renamed_pair, problem, seed) -> None:
    renamed_meta, back = renamed_pair
    with use_backend(gb.BACKEND):
        assert _observe(renamed_meta, problem, seed, back) == _observe(meta, problem, seed)


@pytest.mark.slow
def test_renaming_changes_nothing_in_a_justify_run_or_an_episode(meta, renamed_pair) -> None:
    from server.engine.memory import EpisodicMemory

    renamed_meta, back = renamed_pair
    triples, justify = gb.demo_problems()
    with use_backend(gb.BACKEND):
        problem, answer = justify[0]
        assert _observe(renamed_meta, problem, 1, back, answer=answer) == _observe(meta, problem, 1, answer=answer)
        mem_a, mem_b = EpisodicMemory(), EpisodicMemory()
        for seed in (1, 2, 3):
            expected = _observe(meta, ("abc", "abd", "xyz"), seed, memory=mem_a)
            got = _observe(renamed_meta, ("abc", "abd", "xyz"), seed, back, memory=mem_b)
            assert got == expected, seed


@pytest.mark.slow
def test_renaming_changes_nothing_with_self_watching_off(meta, renamed_pair) -> None:
    renamed_meta, back = renamed_pair
    kw = {"parameters": {"self_watching_enabled_default": False}, "cap": 3000}
    with use_backend(gb.BACKEND):
        assert _observe(renamed_meta, ("abc", "abd", "xyz"), 1, back, **kw) == _observe(
            meta, ("abc", "abd", "xyz"), 1, **kw)


INTERVENTIONS = [
    [{"at": 500, "op": "set_self_watching", "enabled": False}, {"at": 900, "op": "set_self_watching", "enabled": True}],
    [{"at": 200, "op": "clamp_codelet_pattern", "pattern": "group"}, {"at": 500, "op": "undo_last_clamp"}],
    [{"at": 200, "op": "clamp_codelet_pattern", "pattern": "rule"}],
]


@pytest.mark.slow
@pytest.mark.parametrize("interventions", INTERVENTIONS)
def test_renaming_changes_nothing_with_a_persons_interventions(meta, renamed_pair, interventions) -> None:
    renamed_meta, back = renamed_pair
    kw = {"interventions": interventions, "cap": 3000}
    problem = ("xqc", "xqd", "mrrjjj")
    with use_backend(gb.BACKEND):
        assert _observe(renamed_meta, problem, 1, back, **kw) == _observe(meta, problem, 1, **kw)


@pytest.mark.slow
@pytest.mark.parametrize("tiers", [{"low": "lo"}, {"very_low": "vl"}, {"low": "lo", "very_low": "vl", "high": "hi"}])
def test_renaming_an_urgency_tier_changes_nothing(meta, tiers) -> None:
    """Probes M11 and M24: the engine read the tiers ``low`` and ``very_low`` by name."""
    from tests.support.renamed_vocabulary import renamed_urgency_tiers

    provider = rc.provider(rc.Reduced("renamed-tiers", renamed_urgency_tiers(load_documents(), tiers), rc.Report()))
    with use_backend(gb.BACKEND):
        for problem, seed in RENAME_CASES[:3]:
            assert _observe(provider, problem, seed) == _observe(meta, problem, seed), (problem, seed)


@pytest.mark.numeric_matrix
def test_a_structure_reads_the_vocabulary_of_the_run_it_was_made_in(meta, renamed_pair):
    """A structure holds its run's vocabulary (``WorkspaceStructure._voc``) so its own predicates
    read an attribute and not the run binding: with two runs alive in one thread, each run's
    bridges, clauses and rules answer in that run's names, whichever run is bound at the time."""
    from server.engine.memory import EpisodicMemory
    from server.engine.rng import RNG
    from server.engine.runner import EngineRunner

    other, _back = renamed_pair

    def made(m):
        with use_backend("off"):
            runner = EngineRunner(m)
            runner.init_mcat("abc", "abd", "xyz", seed=1, memory=EpisodicMemory(), rng=RNG(1))
            runner.run_mcat(max_steps=900)
        return runner

    plain, odd = made(meta), made(other)
    for runner, m in ((plain, meta), (odd, other)):
        v = m.vocabulary
        bridges = runner.ctx.workspace.top_bridges
        assert bridges, "the run should have built a top bridge"
        for bridge in bridges:
            assert bridge.bridge_type == v.bridge_type_top
            assert bridge.orientation == v.bridge_orientation_horizontal
            assert bridge.is_horizontal and bridge.theme_type == v.theme_type_top_bridge
        rules = runner.ctx.workspace.top_rules
        assert rules, "the run should have built a top rule"
        for rule in rules:
            assert rule.is_top_rule and rule.rule_type == v.rule_type_top
            for clause in rule.clauses:
                assert clause.is_intrinsic != clause.is_extrinsic or clause.is_verbatim
    assert meta.vocabulary.bridge_type_top != other.vocabulary.bridge_type_top
