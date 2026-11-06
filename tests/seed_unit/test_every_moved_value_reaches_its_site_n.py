"""Round 2, stage N: the numbers the numeric literal guard found, and moved, reach their sites.

``tests/architecture/test_numeric_literals.py`` walks every number in ``server/engine/`` and
``server/parallel/``.  It found ten that decide which text or which formula a Metacat Mode run
uses and were still literals:

* nine commentary bands (``engine_params``), which choose the template an event is reported with
  (``answers.ss:47-75``, ``trace.ss:212-226``, ``memory.ss:214-229``);
* ``local_support_number_denominator_floor`` (``formula_coefficients``), the floor of the
  denominator in a bond's or group's local-support exponent ``base ** (1 / max(floor, n ** e))``.

For each row: the seed carries the old literal in its old form; a configuration without it stops
the run at its start; and the site, called with the key changed, gives another result (so a site
that goes back to the literal fails).  The commentary rows are called directly, since commentary
reads no random draw and needs no run.
"""

from __future__ import annotations

import dataclasses
import os
from typing import Any, Callable

import pytest

from server.engine.commentary import (
    CommentaryLog,
    _progress_key,
    emit_answer_discovered,
    emit_answer_justified,
    emit_reminding,
)
from server.engine.metadata import MetadataProvider
from server.engine.start_check import check_run_start
from tests.support.run_binding import rebind

SEED = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")

#: key -> (table, the literal the site held, in its form).
LITERAL: dict[str, tuple[str, Any]] = {
    "commentary_discovery_emphatic_below": ("params", 30),
    "commentary_discovery_emphatic_from": ("params", 85),
    "commentary_discovery_bad_below": ("params", 60),
    "commentary_justified_bad_below": ("params", 60),
    "commentary_justified_extreme_from": ("params", 85),
    "commentary_progress_little_below": ("params", 50),
    "commentary_progress_some_below": ("params", 80),
    "commentary_reminding_strong_above": ("params", 70),
    "commentary_reminding_some_above": ("params", 30),
    "local_support_number_denominator_floor": ("formula_coefficients", 1),
}


@pytest.fixture(scope="module")
def meta() -> MetadataProvider:
    return MetadataProvider.from_standard_configuration(SEED)


def with_value(meta: MetadataProvider, key: str, value: Any) -> MetadataProvider:
    table = LITERAL[key][0]
    return dataclasses.replace(meta, **{table: {**getattr(meta, table), key: value}})


def _get(meta: MetadataProvider, key: str) -> Any:
    return getattr(meta, LITERAL[key][0])[key]


@pytest.mark.parametrize("key", LITERAL)
def test_the_seed_carries_the_old_literal_and_its_type(meta, key):
    got = _get(meta, key)
    assert got == LITERAL[key][1] and type(got) is type(LITERAL[key][1])


@pytest.mark.parametrize("key", LITERAL)
def test_a_missing_key_stops_the_run_at_its_start(meta, key):
    table = LITERAL[key][0]
    without = {k: v for k, v in getattr(meta, table).items() if k != key}
    problems = check_run_start(dataclasses.replace(meta, **{table: without}))
    assert any(p.name == key for p in problems)


# ---- the sites ---------------------------------------------------------------------------


def _say_discovered(meta, quality):
    log = CommentaryLog()
    emit_answer_discovered(log, "xyd", quality, "good", 50.0, 100, 0, meta.commentary_templates)
    return log.render(eliza_mode=True)


def _say_justified(meta, quality):
    log = CommentaryLog()
    emit_answer_justified(log, quality, "good", 100, meta.commentary_templates)
    return log.render(eliza_mode=True)


def _say_reminding(meta, strength):
    log = CommentaryLog()
    emit_reminding(log, "xyd", "abc -> abd, mrrjjj -> ?", strength, 100, meta.commentary_templates)
    return log.render(eliza_mode=True)


#: key -> (the site as a function of the configuration, a probe value just on one side of the literal
#: and the value the key is changed to so that it falls on the other).
SITES: dict[str, Callable[[MetadataProvider], Any]] = {
    # quality 25 is "emphatic" (below 30); raised to 20 it is not
    "commentary_discovery_emphatic_below": lambda m: _say_discovered(m, 25.0),
    # quality 90 is "emphatic" (from 85); raised to 95 it is not
    "commentary_discovery_emphatic_from": lambda m: _say_discovered(m, 90.0),
    # quality 55 is "bad" (below 60); lowered to 50 it is "good"
    "commentary_discovery_bad_below": lambda m: _say_discovered(m, 55.0),
    "commentary_justified_bad_below": lambda m: _say_justified(m, 55.0),
    "commentary_justified_extreme_from": lambda m: _say_justified(m, 90.0),
    "commentary_progress_little_below": lambda m: _progress_key(40.0),
    "commentary_progress_some_below": lambda m: _progress_key(70.0),
    "commentary_reminding_strong_above": lambda m: _say_reminding(m, 80.0),
    "commentary_reminding_some_above": lambda m: _say_reminding(m, 40.0),
}

CHANGED: dict[str, Any] = {
    "commentary_discovery_emphatic_below": 20,
    "commentary_discovery_emphatic_from": 95,
    "commentary_discovery_bad_below": 50,
    "commentary_justified_bad_below": 50,
    "commentary_justified_extreme_from": 95,
    "commentary_progress_little_below": 30,
    "commentary_progress_some_below": 60,
    "commentary_reminding_strong_above": 90,
    "commentary_reminding_some_above": 50,
    "local_support_number_denominator_floor": 4,
}


@pytest.mark.parametrize("key", sorted(SITES))
def test_a_commentary_band_follows_its_key(meta, key):
    rebind(meta)
    before = SITES[key](meta)
    changed = with_value(meta, key, CHANGED[key])
    rebind(changed)
    after = SITES[key](changed)
    assert after != before, f"{key}: the site said the same under both values"


def _bond_support(meta: MetadataProvider):
    """``Bond._local_support`` for a bond with exactly one supporting bond, density fixed."""
    from types import SimpleNamespace
    from unittest import mock

    from server.engine.bonds import Bond

    bond = Bond.__new__(Bond)
    with mock.patch.object(Bond, "get_num_of_local_supporting_bonds", return_value=1), \
            mock.patch.object(Bond, "get_local_density", return_value=100):
        return Bond._local_support(bond, SimpleNamespace())


def _group_support(meta: MetadataProvider):
    from types import SimpleNamespace
    from unittest import mock

    from server.engine.groups import Group

    group = Group.__new__(Group)
    with mock.patch.object(Group, "get_num_of_local_supporting_groups", return_value=1), \
            mock.patch.object(Group, "get_local_density", return_value=100):
        return Group._local_support(group, SimpleNamespace())


@pytest.mark.parametrize("site", [_bond_support, _group_support])
def test_the_denominator_floor_reaches_a_bond_and_a_group(meta, site):
    key = "local_support_number_denominator_floor"
    rebind(meta)
    before = site(meta)
    changed = with_value(meta, key, CHANGED[key])
    rebind(changed)
    after = site(changed)
    assert after != before, f"{site.__name__}: the support was {before!r} under both floors"
