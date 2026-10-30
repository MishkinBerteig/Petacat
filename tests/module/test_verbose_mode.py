"""Module tests for Verbose mode: it narrates a real run, and changes nothing in it.

Metacat's ``%verbose%`` prints what each codelet does.  Here the engine runs for real
and the tests pin what the mode must and must not do: every codelet opens with its
banner, the narration is bounded, the message catalogue and the call sites agree, a mode
switched mid-run takes effect at the next codelet, step mode narrates by itself, and a
run is the same run with the mode on or off.  What Metacat says, exactly, is checked in
``tests/lockstep/test_verbose.py``.
"""

from __future__ import annotations

import json
import os
import re

import pytest

from server.engine.metadata import MetadataProvider, verbose_messages
from server.engine.runner import EngineRunner
from server.engine.verbose import DASHES

pytestmark = pytest.mark.numeric_matrix

REPO = os.path.join(os.path.dirname(__file__), "..", "..")
SEED_DIR = os.path.join(REPO, "seed_data")


@pytest.fixture
def meta():
    return MetadataProvider.from_seed_data(SEED_DIR)


def _run(meta, verbose, steps=400, seed=3, problem=("abc", "abd", "xyz")):
    runner = EngineRunner(meta)
    runner.verbose_mode = verbose
    runner.init_mcat(*problem, seed=seed)
    for _ in range(steps):
        runner.step_mcat()
    return runner


def _fingerprint(runner):
    ctx = runner.ctx
    return (
        ctx.codelet_count,
        round(ctx.temperature.value, 9),
        sorted(round(n.activation, 9) for n in ctx.slipnet.nodes.values()),
        [(b.bond_category.name, b.left_object.left_string_pos) for b in ctx.workspace.initial_string.bonds],
        ctx.rng.random(),  # the next number the generator would draw
    )


def test_every_codelet_opens_with_its_banner(meta):
    runner = _run(meta, True, steps=40)
    lines = runner.ctx.verbose_log.since(0)["lines"]
    banners = [i for i, line in enumerate(lines) if line == DASHES]
    assert len(banners) == 40
    for i in banners:
        assert lines[i + 1].startswith("In ") and lines[i + 1].endswith(" codelet...")


def test_verbose_off_narrates_nothing(meta):
    runner = _run(meta, False, steps=200)
    assert runner.ctx.verbose_log.since(0)["total"] == 0


def test_a_run_is_the_same_run_with_verbose_on_or_off(meta):
    on = _run(meta, True)
    off = _run(meta, False)
    assert on.ctx.verbose_log.since(0)["total"] > 1000
    assert _fingerprint(on) == _fingerprint(off)


def test_verbose_on_draws_no_random_number_of_its_own(meta):
    """The generator is in the same state after the same number of codelets."""
    on, off = _run(meta, True, steps=250, seed=9), _run(meta, False, steps=250, seed=9)
    assert on.ctx.rng.random() == off.ctx.rng.random()


def test_the_mode_can_be_switched_mid_run(meta):
    runner = _run(meta, False, steps=30)
    log = runner.ctx.verbose_log
    assert log.since(0)["total"] == 0
    runner.verbose_mode = True
    runner.ctx.set_verbose(mode=True)
    for _ in range(10):
        runner.step_mcat()
    assert log.since(0)["lines"].count(DASHES) == 10
    runner.ctx.set_verbose(mode=False)
    before = log.since(0)["total"]
    for _ in range(10):
        runner.step_mcat()
    assert log.since(0)["total"] == before


def test_step_mode_narrates_even_when_the_mode_is_off(meta):
    runner = _run(meta, False, steps=5)
    ctx = runner.ctx
    ctx.set_verbose(step=True)
    assert ctx.verbose is True and ctx.verbose_mode is False
    runner.step_mcat()
    ctx.set_verbose(step=False)
    assert ctx.verbose is False
    assert ctx.verbose_log.since(0)["lines"].count(DASHES) == 1


def test_the_mode_outlives_a_reset(meta):
    runner = _run(meta, True, steps=3)
    runner.init_mcat("abc", "abd", "ijk", seed=4)
    assert runner.ctx.verbose is True
    assert runner.ctx.verbose_log.since(0)["total"] == 0  # the narration is the new run's own


def test_the_buffer_stays_within_its_capacity(meta):
    runner = EngineRunner(meta)
    runner.verbose_mode = True
    runner.init_mcat("abc", "abd", "xyz", seed=3)
    runner.ctx.verbose_log = type(runner.ctx.verbose_log)(capacity=200)
    runner.ctx.verbose_log.bind(meta)
    runner.ctx.verbose_log.slipnet = runner.ctx.slipnet
    for _ in range(150):
        runner.step_mcat()
    snap = runner.ctx.verbose_log.since(0)
    assert len(snap["lines"]) == 200
    assert snap["dropped"] == snap["total"] - 200 > 0


def _source_keys():
    keys = set()
    patterns = (
        r'''(?:say|say_|vlog\.say|verbose_log\.say|log\.say)\(\s*["']([a-z0-9-]+)["']''',
        r'''(?:key|_NOT_STRONG_ENOUGH\.get\([^)]*\)) = "([a-z0-9-]+)"''',
        r'''"((?:bond|bridge|description|rule)-not-strong-enough)"''',
    )
    sources = [
        os.path.join(SEED_DIR, "codelet_types.json"),
        *(
            os.path.join(REPO, "server", "engine", name)
            for name in (
                "codelet_dsl/builtins.py", "jootsing.py", "justify.py", "themes.py",
                "bridges.py", "trace.py", "runner.py", "workspace.py",
                "verbose.py",  # the display-time messages of ``narrate_event_display``
            )
        ),
        # The free-running engine narrates too; it lives in the parallel plugin.
        os.path.join(REPO, "server", "parallel", "free_running.py"),
    ]
    for path in sources:
        text = open(path, encoding="utf-8").read()
        if path.endswith(".json"):
            text = "\n".join(c["execute_body"] for c in json.loads(text))
        for pattern in patterns:
            keys.update(re.findall(pattern, text))
    # Keys spelled by concatenation in the fight narration.
    keys.update({"fighting-incompatible-group", "fighting-existing-group1", "fighting-existing-group2",
                 "lost-to-incompatible-group", "lost-to-existing-group1", "lost-to-existing-group2",
                 "lost-to-incompatible-bond", "lost-to-incompatible-bridge", "lost-to-existing-bond"})
    return keys


def test_every_message_a_call_site_names_is_in_the_catalogue(meta):
    catalogue = verbose_messages(meta)
    missing = sorted(k for k in _source_keys() if k not in catalogue and not k.endswith("-"))
    assert not missing, f"call sites name messages the catalogue lacks: {missing}"


def test_every_message_in_the_catalogue_is_said_somewhere(meta):
    unused = sorted(set(verbose_messages(meta)) - _source_keys())
    assert not unused, f"catalogue entries no call site names: {unused}"


def test_the_catalogue_is_seed_data_and_each_template_takes_what_its_site_gives(meta):
    for key, template in verbose_messages(meta).items():
        assert isinstance(template, str) and template, key
        assert template.count("{") == template.count("}"), key
        template.format(*["x"] * template.count("{}"))  # no stray fields
