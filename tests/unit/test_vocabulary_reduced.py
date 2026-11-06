"""A configuration with a vocabulary role unbound still runs every demo problem (NAME-DESIGN 4.6).

An unbound role is a concept the configuration does not have: its name is an ``AbsentName``,
equal to nothing, so the engine never takes the branch.  Only the roles in
``start_check.REQUIRED_VOCABULARY_ROLES`` stop a run, and they stop it at its start with a
``RunStartError`` naming them, never mid-run.
"""

from __future__ import annotations

import pytest

from server.engine.numeric.backend import use_backend
from server.engine.roles import VOCABULARY, VOCABULARY_BY_NAME
from server.engine.start_check import REQUIRED_VOCABULARY_ROLES, RunStartError
from tests.support import golden_baseline as gb
from tests.support import reduced_configurations as rc
from tests.support.configuration_cascade import load_documents
from tests.unit.test_en6_perception import _every_demo

REQUIRED = {name for name, _ in REQUIRED_VOCABULARY_ROLES}
OPTIONAL = [s.name for s in VOCABULARY if s.name not in REQUIRED]


def _unbound(role: str) -> rc.Reduced:
    docs = load_documents()
    table = VOCABULARY_BY_NAME[role].table
    rows = docs["theme_relations.json"] if table == "theme_relations" else docs["enums.json"][table]
    for row in rows:
        if row.get("role") == role:
            row["role"] = None
    return rc.Reduced(f"unbound-{role}", docs, rc.Report())


def test_the_required_list_names_real_roles() -> None:
    assert REQUIRED <= {s.name for s in VOCABULARY}
    assert OPTIONAL, "every role is required: the reduced-configuration test would test nothing"


@pytest.mark.parametrize("role", sorted(REQUIRED))
def test_a_required_role_unbound_stops_the_run_at_its_start(role) -> None:
    from server.engine.runner import EngineRunner
    from server.engine.rng import RNG

    provider = rc.provider(_unbound(role))
    runner = EngineRunner(provider)
    with use_backend(gb.BACKEND), pytest.raises(RunStartError, match=role.replace(".", r"\.")):
        runner.init_mcat("abc", "abd", "xyz", seed=1, rng=RNG(1))


@pytest.mark.slow
@pytest.mark.parametrize("role", OPTIONAL)
def test_an_optional_role_unbound_runs_every_demo_problem(role) -> None:
    _every_demo(rc.provider(_unbound(role)))
