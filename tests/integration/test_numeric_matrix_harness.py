"""The numeric matrix's own reporting rules (``tests/conftest.py``).

The matrix decides two things about a session, and both are checked here because
both change the exit status: whether the run covered the backends it should have,
and whether a shortfall is a failure or a fact.

The rule is that **completeness is required of a run that asked for everything**.
The required command asks for the whole suite, so it is held to the whole matrix.
A deliberate slice — one file, one node id, ``-m slow``, ``-k`` on a case name, a
chosen backend — asked a narrower question; it names the roles it exercised and
exits on the strength of its own tests.

The subprocess test is what pins the exit status, since that is the property a
caller sees and it cannot be observed from inside the session it describes. The
rest exercise the decision directly, which is where the reasons live.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

from tests.conftest import _narrowing, matrix_shortfall

REPO_ROOT = Path(__file__).resolve().parents[2]

#: A cheap module in the matrix, used as the subject of a narrowed child session.
NARROW_TARGET = "tests/module/test_themespace.py"

FULL_MATRIX = [("cpu", "numpy"), ("gpu", "mlx")]


class _FakeConfig:
    """Only the surface ``_narrowing`` reads."""

    def __init__(self, args, *, markexpr="", keyword="", backends=None):
        self.args = args
        self.rootpath = REPO_ROOT
        self.option = type(
            "Options",
            (),
            {
                "markexpr": markexpr,
                "keyword": keyword,
                "deselect": None,
                "last_failed": False,
            },
        )()
        self._backends = backends

    def getoption(self, name):
        assert name == "--numeric-backends"
        return self._backends


# ─────────────────────────────────────────────────────────────────────────────
# The exit status a caller sees
# ─────────────────────────────────────────────────────────────────────────────


def test_a_narrowed_selection_whose_tests_all_pass_exits_zero() -> None:
    """``-k`` on a backend name selects one role, and that is a complete answer.

    Run in a child interpreter because the exit status is produced by
    ``pytest_sessionfinish`` after every report is in, so a test inside the session
    cannot see it. The child selects a single matrix module and filters to the
    ``mlx`` cases, which is the shape that has to stay green: every selected test
    passes, one role is exercised, and the run is a success.
    """
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            NARROW_TARGET,
            "-q",
            "-k",
            "mlx",
            "-p",
            "no:cacheprovider",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=600,
        env={**os.environ, "PYTEST_ADDOPTS": ""},
    )
    assert completed.returncode == 0, (
        "A narrowed selection in which every test passed exited non-zero. The "
        "matrix's completeness rule applies to a run that asked for the whole "
        f"suite.\n--- stdout ---\n{completed.stdout}\n--- stderr ---\n"
        f"{completed.stderr}"
    )
    assert "no selected test ran on it" in completed.stdout, (
        "The run covered one role and did not say which, so a reader cannot tell "
        f"what it speaks for.\n--- stdout ---\n{completed.stdout}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# What counts as narrowing
# ─────────────────────────────────────────────────────────────────────────────


def test_the_whole_tests_tree_is_not_a_narrowing() -> None:
    assert _narrowing(_FakeConfig(["tests"])) == ""


def test_a_single_file_is_a_narrowing() -> None:
    assert _narrowing(_FakeConfig([NARROW_TARGET])) == NARROW_TARGET


def test_a_marker_expression_is_a_narrowing() -> None:
    assert _narrowing(_FakeConfig(["tests"], markexpr="slow")) == "-m 'slow'"


def test_a_keyword_expression_is_a_narrowing() -> None:
    assert _narrowing(_FakeConfig(["tests"], keyword="mlx")) == "-k 'mlx'"


def test_choosing_the_backends_is_a_narrowing() -> None:
    assert (
        _narrowing(_FakeConfig(["tests"], backends="cpu"))
        == "--numeric-backends=cpu"
    )


# ─────────────────────────────────────────────────────────────────────────────
# When a partial matrix is a failure
# ─────────────────────────────────────────────────────────────────────────────


def test_a_full_run_that_left_a_backend_unexercised_reports_a_shortfall() -> None:
    """The case the rule exists for: everything was asked for, one role ran."""
    message = matrix_shortfall(
        FULL_MATRIX,
        Counter({"mlx": 250}),
        matrix_selected=250,
        full_suite=True,
        tests_run=1500,
        stopped_early=False,
    )
    assert message is not None
    assert "numpy" in message


def test_a_narrowed_run_that_left_a_backend_unexercised_is_silent() -> None:
    assert (
        matrix_shortfall(
            FULL_MATRIX,
            Counter({"mlx": 14}),
            matrix_selected=14,
            full_suite=False,
            tests_run=14,
            stopped_early=False,
        )
        is None
    )


def test_a_role_whose_backend_is_absent_is_not_a_shortfall() -> None:
    """A machine without MLX holds a one-role matrix and runs all of it.

    The summary names the absent role on its own line; the suite stays green,
    which is what makes the GPU an optional dependency rather than a required one.
    """
    assert (
        matrix_shortfall(
            [("cpu", "python")],
            Counter({"python": 250}),
            matrix_selected=250,
            full_suite=True,
            tests_run=1500,
            stopped_early=False,
        )
        is None
    )


def test_a_run_that_stopped_early_reports_the_stop_rather_than_the_matrix() -> None:
    """A truncated run's headline is the truncation, so it does not add a second."""
    assert (
        matrix_shortfall(
            FULL_MATRIX,
            Counter({"mlx": 120}),
            matrix_selected=250,
            full_suite=True,
            tests_run=400,
            stopped_early=True,
        )
        is None
    )


def test_a_run_with_no_matrix_tests_has_no_matrix_to_cover() -> None:
    assert (
        matrix_shortfall(
            FULL_MATRIX,
            Counter(),
            matrix_selected=0,
            full_suite=True,
            tests_run=209,
            stopped_early=False,
        )
        is None
    )
