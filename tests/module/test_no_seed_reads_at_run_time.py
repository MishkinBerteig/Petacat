"""EN1: the engine takes its configuration from the run's ``MetadataProvider``, never the files.

The Metacat Standard Configuration (``seed_data/*.json``) is read to *build* a provider
(here ``MetadataProvider.from_seed_data``, in the fixture), and by nothing else.  Two kinds
of guard:

* **The audit hook.**  A ``sys.addaudithook`` hook fails any ``open`` of a file under the
  seed directory while it is armed.  It is armed across an ordinary run (Verbose mode on,
  so the message catalogue is read too), a swarm call and a Training-style episode with
  Episodic Memory carried (so reminding and comparison run), and a comparison and
  explanation of the answers it left.  The hook is installed by a local fixture, so no
  ``conftest.py`` is involved; it cannot be removed once installed, so it is disarmed with
  a flag.
* **Fallbacks raise.**  Every function that used to fall back to the files when it had no
  provider now raises ``ConfigurationRequired`` (or ``TypeError`` for a missing mandatory
  argument) rather than reading them.
"""

from __future__ import annotations

import os
import sys

import pytest

from server.engine.commentary import describe_answer, describe_answer_comparison
from server.engine.memory import EpisodicMemory
from server.engine.metadata import ConfigurationRequired, MetadataProvider, verbose_messages
from server.engine.rule_english import _param, transcribe_rule_to_english_lines
from server.engine.rules import Rule, RuleClause, RULE_TOP
from server.engine.runner import EngineRunner
from server.parallel.swarm import EpisodeTask, RunTask, run_inprocess

pytestmark = pytest.mark.numeric_matrix

SEED_DIR = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "..", "seed_data"))

_ARMED = False
_HOOK_INSTALLED = False
_READS: list[str] = []


def _audit(event: str, args: tuple) -> None:
    if not _ARMED or event != "open":
        return
    target = args[0]
    if isinstance(target, bytes):
        target = os.fsdecode(target)
    if isinstance(target, str) and os.path.realpath(target).startswith(SEED_DIR):
        _READS.append(target)
        raise AssertionError(f"the engine opened a seed file at run time: {target}")


@pytest.fixture(scope="module")
def meta():
    return MetadataProvider.from_seed_data(SEED_DIR)


@pytest.fixture
def seed_reads_forbidden():
    """Fail any ``open`` under the seed directory until the test ends."""
    global _ARMED, _HOOK_INSTALLED
    if not _HOOK_INSTALLED:
        sys.addaudithook(_audit)
        _HOOK_INSTALLED = True
    _READS.clear()
    _ARMED = True
    try:
        yield _READS
    finally:
        _ARMED = False


def test_the_audit_hook_catches_a_seed_read(seed_reads_forbidden):
    """The guard works: a read of a seed file while armed is refused and recorded."""
    with pytest.raises(AssertionError):
        open(os.path.join(SEED_DIR, "engine_params.json")).close()
    assert len(seed_reads_forbidden) == 1


def test_a_run_reads_no_seed_file(meta, seed_reads_forbidden):
    runner = EngineRunner(meta)
    runner.verbose_mode = True
    runner.init_mcat("abc", "abd", "ijk", seed=3)
    runner.run_mcat(max_steps=2500)
    assert runner.ctx.codelet_count > 0
    assert runner.ctx.verbose_log.since(0)["total"] > 0
    assert seed_reads_forbidden == []


def test_a_swarm_call_reads_no_seed_file(meta, seed_reads_forbidden):
    outcome = run_inprocess(RunTask("abc", "abd", "ijk", None, 5, 1500), meta)
    assert outcome is not None
    assert seed_reads_forbidden == []


def test_an_episode_and_the_answers_it_leaves_read_no_seed_file(meta, seed_reads_forbidden):
    memory = EpisodicMemory()
    for seed in (1, 2, 3):
        runner = EngineRunner(meta)
        runner.init_mcat("abc", "abd", "mrrjjj", seed=seed, memory=memory)
        runner.run_mcat(max_steps=6000)
    assert seed_reads_forbidden == []
    outcome = run_inprocess(
        EpisodeTask("abc", "abd", "ijk", first_seed=1, runs=2, max_steps=2000), meta
    )
    assert outcome is not None
    answers = memory.answers
    assert len(answers) >= 2
    # Comparison, explanation and distance all render and measure from the provider.
    describe_answer_comparison(
        answers[0], answers[1], memory=memory, meta=meta, templates=meta.commentary_templates
    )
    describe_answer(answers[0], memory=memory, templates=meta.commentary_templates)
    memory.distance(answers[0], answers[1], meta)
    assert seed_reads_forbidden == []


# -- fallbacks raise ---------------------------------------------------------------


def test_rule_english_without_a_provider_raises():
    with pytest.raises(ConfigurationRequired):
        _param(None, "maximum_rule_line_length", 60)
    rule = Rule(rule_type=RULE_TOP, clauses=[RuleClause(clause_type="intrinsic")])
    with pytest.raises(ConfigurationRequired):
        transcribe_rule_to_english_lines(rule, None)
    with pytest.raises(ConfigurationRequired):
        rule.transcribe_to_english(None)


def test_a_missing_provider_never_reads_the_files_for_the_catalogue():
    with pytest.raises(ConfigurationRequired):
        verbose_messages(None)


def test_comparison_and_reminding_need_the_provider(meta):
    memory = EpisodicMemory()
    with pytest.raises(TypeError):
        memory.distance(None, None)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        memory.find_remindings(None)  # type: ignore[call-arg]
    with pytest.raises(ConfigurationRequired):
        memory.find_remindings(None, 5.0, meta=None)
    with pytest.raises(ConfigurationRequired):
        describe_answer(None, memory=memory, templates=None)
    with pytest.raises(TypeError):
        describe_answer_comparison(None, None)  # type: ignore[call-arg]
    with pytest.raises(ConfigurationRequired):
        describe_answer_comparison(None, None, meta=None)


def test_the_former_file_fallbacks_no_longer_exist():
    import server.engine.answer_comparison as ac
    import server.engine.metadata as md
    import server.engine.rule_english as re_

    for module, name in (
        (md, "default_commentary_templates"),
        (md, "DEFAULT_SEED_DIR"),
        (ac, "default_conceptual_depths"),
        (re_, "_seed_params_cache"),
        (re_, "_SEED_DIR"),
    ):
        assert not hasattr(module, name), f"{module.__name__}.{name} still exists"
