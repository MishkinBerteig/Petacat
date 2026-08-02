"""Shared test fixtures, the numeric backend matrix, and the session ceiling.

All tests are deterministic: every stochastic operation uses a fixed seed.
The RNG is the single source of randomness, and identical seeds produce
identical behavior regardless of execution environment.

Two session-wide mechanisms live here.

**The numeric backend matrix.**  ``server/engine/numeric/`` computes the engine's
arithmetic on any of four interchangeable backends, and the default policy puts a
run on the Metal GPU.  A test whose outcome that arithmetic produces has two
answers worth knowing — one on the CPU in float64, one on the GPU in float32 — so
every test in a module marked ``numeric_matrix`` runs once per backend in the
matrix.  The terminal summary names the backends that were exercised and how many
tests took each, which is what makes the coverage a fact of the output.  Covering
the whole matrix is *required* of a run that asked for the whole suite; a
deliberate slice reports the roles it reached and exits on its own tests.

**The session ceiling.**  A run stops at a wall-clock deadline, 60 minutes by
default.  The stop happens between tests through pytest's own
``session.shouldstop``, which keeps every report already collected: a truncated run
reports the tests that ran, the layers that finished, and the backends that were
exercised.  The summary states the truncation in words, the per-layer line reads
``INCOMPLETE``, and the exit status is pytest's ``INTERRUPTED``.
"""

from __future__ import annotations

import os
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterator

import pytest

# Ensure the project root is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

SEED_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "seed_data")

# Fixed seed for all deterministic tests
DETERMINISTIC_SEED = 42


@pytest.fixture
def seed_data_dir():
    return SEED_DATA_DIR


@pytest.fixture
def deterministic_seed():
    """Fixed seed ensuring all stochastic tests are reproducible."""
    return DETERMINISTIC_SEED


# ═══════════════════════════════════════════════════════════════════════════
# The numeric backend matrix
# ═══════════════════════════════════════════════════════════════════════════

#: A module (or a single test) carrying this marker runs once per matrix backend.
MATRIX_MARKER = "numeric_matrix"

#: The two roles the required matrix covers, and the backends that can fill them.
#:
#: ``cpu`` is float64 and agrees with the pure-Python reference exactly, down to the
#: number of random draws a run consumes.  ``gpu`` is float32, because Apple's GPUs
#: have no double-precision units, so it makes some probabilistic choices
#: differently and its individual runs diverge; what holds there is the set of
#: reachable stopping states, which is the expected-range oracle's question.
#:
#: NumPy fills the CPU role when it is installed and the reference fills it
#: otherwise, so the CPU half of the matrix exists on every machine.
ROLE_PREFERENCES: dict[str, tuple[str, ...]] = {
    "cpu": ("numpy", "python"),
    "gpu": ("mlx",),
}

#: The suite's layers, bottom-up.  The per-layer summary is printed in this order,
#: and a directory under ``tests/`` is a layer exactly when it appears here.
LAYERS = ("unit", "seed_unit", "module", "architecture", "integration", "e2e")

#: Layers whose tests must declare their relationship to the substrate.  A test
#: here that executes substrate arithmetic without the marker is reported by name
#: and fails the session, which is what keeps the matrix's membership current as
#: the suite grows.
#:
#: ``e2e`` is outside it: its subject is the HTTP and persistence stack, it adds no
#: numeric path of its own, and it runs on the policy the application ships with.
GUARDED_LAYERS = ("unit", "seed_unit", "module", "architecture", "integration")

#: Files exempt from that guard because they select backends themselves, more
#: finely than a matrix role can: they parametrise over *every* installed backend
#: and separate the exact ones from the inexact one.
SUBSTRATE_OWN_TESTS = ("test_numeric_backends.py", "test_numeric_engine.py")

#: The engine modules that consult the backend seam.  Wrapping ``select_backend``
#: in each is how a test's use of the substrate is observed.
SEAM_MODULES = (
    "server.engine.slipnet",
    "server.engine.themes",
    "server.engine.temperature",
    "server.engine.workspace",
)

ENV_MATRIX = "PETACAT_TEST_BACKENDS"
ENV_CEILING = "PETACAT_TEST_CEILING_MINUTES"

#: Wall-clock ceiling for one pytest session, in minutes.  ``0`` runs to the end.
DEFAULT_CEILING_MINUTES = 60.0


@dataclass
class _LayerTally:
    collected: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0

    @property
    def run(self) -> int:
        return self.passed + self.failed + self.skipped


@dataclass
class _SessionState:
    """What the summary reports, accumulated as the session runs."""

    started: float = field(default_factory=time.monotonic)
    ceiling_seconds: float = 0.0
    truncated_at: float | None = None
    matrix: list[tuple[str, str]] = field(default_factory=list)
    matrix_requested: bool = False
    matrix_selected: int = 0
    full_suite: bool = False
    narrowed_by: str = ""
    stopped_early: bool = False
    exercised: Counter[str] = field(default_factory=Counter)
    layers: dict[str, _LayerTally] = field(default_factory=dict)
    unmarked_seam_users: list[str] = field(default_factory=list)
    seam_calls: int = 0
    verdict: list[str] = field(default_factory=list)

    def layer(self, name: str) -> _LayerTally:
        return self.layers.setdefault(name, _LayerTally())

    @property
    def tests_run(self) -> int:
        return sum(tally.run for tally in self.layers.values())

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started


_STATE = _SessionState()


def _layer_of(nodeid: str) -> str:
    """``tests/module/test_runner.py::test_x`` -> ``module``."""
    parts = nodeid.replace(os.sep, "/").split("/")
    return parts[1] if len(parts) > 1 and parts[0] == "tests" else parts[0]


def _available() -> list[str]:
    from server.engine.numeric.backend import available_backends

    return available_backends()


def _resolve_matrix(spec: str | None) -> tuple[list[tuple[str, str]], bool]:
    """Turn a matrix specification into ``[(role, backend name), ...]``.

    ``None`` asks for the required matrix: the CPU role, always fillable, plus the
    GPU role whenever MLX is installed and its Metal probe succeeds.  A machine
    without MLX runs the CPU half and says so, which is the same skip-rather-than-
    fail rule every other backend-specific test in the suite follows.

    A specification names roles (``cpu``, ``gpu``), backends (``python``,
    ``numpy``, ``mlx``, ``mlx-cpu``) or ``all``, comma-separated.
    """
    available = _available()
    if spec is None:
        matrix = []
        for role, preference in ROLE_PREFERENCES.items():
            for name in preference:
                if name in available:
                    matrix.append((role, name))
                    break
        return matrix, False

    if spec.strip().lower() == "all":
        return [(_role_of(name), name) for name in available], True

    matrix = []
    for token in (t.strip().lower() for t in spec.split(",") if t.strip()):
        if token in ROLE_PREFERENCES:
            chosen = next((n for n in ROLE_PREFERENCES[token] if n in available), None)
            if chosen is None:
                raise pytest.UsageError(
                    f"--numeric-backends={spec!r} asks for the {token!r} role, and "
                    f"none of {ROLE_PREFERENCES[token]} is installed. Available "
                    f"backends: {available}."
                )
            matrix.append((token, chosen))
        elif token in available:
            matrix.append((_role_of(token), token))
        else:
            raise pytest.UsageError(
                f"--numeric-backends={spec!r} names {token!r}, which is neither a "
                f"role ({', '.join(ROLE_PREFERENCES)}) nor an available backend "
                f"({', '.join(available)})."
            )
    return matrix, True


def _role_of(name: str) -> str:
    for role, preference in ROLE_PREFERENCES.items():
        if name in preference:
            return role
    return "cpu"


def _narrowing(config: pytest.Config) -> str:
    """How this invocation narrowed the suite, or ``""`` for the whole of it.

    Completeness is a claim about a run that asked for everything.  A deliberate
    slice — one file, one node id, ``-m slow``, ``-k`` on a case name, a chosen
    backend — is answering a narrower question, and answers it honestly by naming
    the roles it exercised.  Only a run that asked for the whole suite is held to
    covering the whole matrix.
    """
    option = config.option
    for attribute, label in (
        ("markexpr", "-m"),
        ("keyword", "-k"),
    ):
        value = getattr(option, attribute, "")
        if value:
            return f"{label} {value!r}"
    if getattr(option, "deselect", None):
        return "--deselect"
    if getattr(option, "last_failed", False):
        return "--last-failed"
    if config.getoption("--numeric-backends"):
        return f"--numeric-backends={config.getoption('--numeric-backends')}"

    root = os.path.abspath(str(config.rootpath))
    whole_tree = {os.path.abspath(os.path.dirname(__file__)), root}

    def resolve(arg: object) -> str:
        """An invocation target as an absolute path.

        Targets arrive relative to the invocation directory when they were typed
        and relative to the rootdir when they came from ``testpaths``, so both are
        tried and the one that exists wins.
        """
        path = str(arg).split("::")[0]
        direct = os.path.abspath(path)
        if os.path.isabs(path) or os.path.exists(direct):
            return direct
        return os.path.abspath(os.path.join(root, path))

    targets = [resolve(arg) for arg in config.args]
    if not targets or any(target not in whole_tree for target in targets):
        return " ".join(str(arg) for arg in config.args) or "no targets"
    return ""


def matrix_shortfall(
    matrix: list[tuple[str, str]],
    exercised: Counter[str],
    matrix_selected: int,
    full_suite: bool,
    tests_run: int,
    stopped_early: bool,
) -> str | None:
    """The message for a full run that covered less of the matrix than it holds.

    ``None`` means there is nothing to report.  Every argument is a reason the
    question does not arise: a narrowed run asked something else, a run that
    selected no matrix tests has no matrix to cover, a run that executed nothing
    has no evidence either way, and a run that stopped early reports the stop as
    its headline.

    A role missing from ``matrix`` because its backend is not installed is not a
    shortfall — the summary names it on its own line, and the suite stays green on
    a machine without a GPU.
    """
    if not (matrix_selected and tests_run and full_suite) or stopped_early:
        return None
    missing = [name for _role, name in matrix if not exercised[name]]
    if not missing:
        return None
    return (
        f"The matrix selected {matrix_selected} tests and "
        f"{', '.join(missing)} ran none of them, so this run covers part of the "
        f"matrix while asking for all of it."
    )


def _minutes(seconds: float) -> str:
    return f"{seconds:.1f} s" if seconds < 60 else f"{seconds / 60:.1f} min"


def _precision(name: str) -> str:
    from server.engine.numeric.backend import get_backend

    return "float64" if get_backend(name).exact else "float32"


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("petacat")
    group.addoption(
        "--numeric-backends",
        action="store",
        default=os.environ.get(ENV_MATRIX) or None,
        metavar="SPEC",
        help=(
            "Numeric backends the matrix runs over: roles (cpu, gpu), backend names "
            "(python, numpy, mlx, mlx-cpu), or 'all'. Naming a single backend also "
            "makes it this session's default, so the tests outside the matrix take "
            "it too. Default: the required matrix, cpu and gpu."
        ),
    )
    group.addoption(
        "--test-ceiling",
        action="store",
        type=float,
        default=float(os.environ.get(ENV_CEILING) or DEFAULT_CEILING_MINUTES),
        metavar="MINUTES",
        help=(
            f"Wall-clock ceiling for the session, in minutes (default "
            f"{DEFAULT_CEILING_MINUTES:g}). The run stops at the first test boundary "
            f"past it, keeps every result collected so far, and reports itself as "
            f"truncated. 0 runs to the end."
        ),
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        f"{MATRIX_MARKER}: run this test once per numeric backend in the matrix.",
    )

    _STATE.matrix, _STATE.matrix_requested = _resolve_matrix(
        config.getoption("--numeric-backends")
    )
    _STATE.ceiling_seconds = max(0.0, config.getoption("--test-ceiling")) * 60.0
    _STATE.started = time.monotonic()
    _STATE.narrowed_by = _narrowing(config)
    _STATE.full_suite = not _STATE.narrowed_by

    # One named backend is a statement about the whole session, so the tests
    # outside the matrix run on it as well and the run is what it says it is.
    if _STATE.matrix_requested and len(_STATE.matrix) == 1:
        from server.engine.numeric.backend import ENV_BACKEND, reset_backend_cache

        os.environ[ENV_BACKEND] = _STATE.matrix[0][1]
        reset_backend_cache()

    _install_seam_probe()


def _install_seam_probe() -> None:
    """Count each test's calls into ``select_backend``.

    The wrapper forwards to the original and returns what it returns, so the
    engine's behaviour is untouched by the observation.  What it adds is the fact
    the guard needs: whether a given test reached the arithmetic the substrate
    owns.
    """
    import importlib

    def wrap(original):
        def select_backend(n_nodes, _original=original):
            _STATE.seam_calls += 1
            return _original(n_nodes)

        return select_backend

    for name in SEAM_MODULES:
        module = importlib.import_module(name)
        if hasattr(module, "select_backend"):
            module.select_backend = wrap(module.select_backend)


def pytest_collection_finish(session: pytest.Session) -> None:
    """Count what will actually run, after every deselection has been applied.

    ``-m "not slow"`` deselects during ``pytest_collection_modifyitems``, so counting
    there would report a layer as incomplete for tests the run never intended to
    execute.  Here the item list is final.
    """
    for item in session.items:
        _STATE.layer(_layer_of(item.nodeid)).collected += 1
        if item.get_closest_marker(MATRIX_MARKER) is not None:
            _STATE.matrix_selected += 1


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "numeric_backend" not in metafunc.fixturenames:
        return
    if metafunc.definition.get_closest_marker(MATRIX_MARKER) is None:
        return
    metafunc.parametrize(
        "numeric_backend", [name for _role, name in _STATE.matrix], indirect=True
    )


@pytest.fixture
def numeric_backend(request: pytest.FixtureRequest) -> str | None:
    """The backend this test case runs on, or ``None`` outside the matrix."""
    return getattr(request, "param", None)


@pytest.fixture(autouse=True)
def _numeric_matrix_backend(numeric_backend: str | None) -> Iterator[None]:
    """Force the case's backend for the body of the test, then restore.

    A forced backend bypasses the size policy, which is what engages the substrate
    on the 59-node Slipnet the engine runs today: each case therefore executes the
    arithmetic on the backend its name says.
    """
    if numeric_backend is None:
        yield
        return
    from server.engine.numeric.backend import use_backend

    _STATE.exercised[numeric_backend] += 1
    with use_backend(numeric_backend):
        yield


def _guarded(item: pytest.Item) -> bool:
    """Whether this test must declare its relationship to the substrate."""
    if _layer_of(item.nodeid) not in GUARDED_LAYERS:
        return False
    path = getattr(item, "path", None)
    if path is not None and os.path.basename(str(path)) in SUBSTRATE_OWN_TESTS:
        return False
    if item.get_closest_marker(MATRIX_MARKER) is not None:
        return False
    # The slow guards choose their own backend environment: the expected-range
    # oracle sets its worker pool's backend, and the optionality probe runs an
    # interpreter with MLX and NumPy made unimportable.
    return item.get_closest_marker("slow") is None


@pytest.hookimpl(wrapper=True)
def pytest_runtest_protocol(item: pytest.Item, nextitem: pytest.Item | None):
    _STATE.seam_calls = 0
    try:
        result = yield
    finally:
        if _STATE.seam_calls and _guarded(item):
            _STATE.unmarked_seam_users.append(item.nodeid)
        if item.session.shouldfail or item.session.shouldstop:
            _STATE.stopped_early = True
        if (
            _STATE.ceiling_seconds
            and _STATE.truncated_at is None
            and _STATE.elapsed >= _STATE.ceiling_seconds
        ):
            _STATE.truncated_at = _STATE.elapsed
            _STATE.stopped_early = True
            item.session.shouldstop = (
                f"the {_STATE.ceiling_seconds / 60:g} min test ceiling was reached "
                f"after {_minutes(_STATE.truncated_at)} — this run is TRUNCATED"
            )
    return result


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    tally = _STATE.layer(_layer_of(report.nodeid))
    if report.when == "call":
        if report.passed:
            tally.passed += 1
        elif report.failed:
            tally.failed += 1
        elif report.skipped:
            tally.skipped += 1
    elif report.when == "setup":
        if report.skipped:
            tally.skipped += 1
        elif report.failed:
            tally.failed += 1
    elif report.when == "teardown" and report.failed:
        tally.failed += 1


def _verdict() -> list[str]:
    """The session's failing conditions, as lines to print. Empty means clean.

    Read by both the exit status and the printed summary, from state that is final
    by the time either asks, so the two say the same thing.
    """
    if _STATE.verdict:
        return _STATE.verdict

    lines: list[str] = []
    if _STATE.unmarked_seam_users:
        lines.append(
            "These tests executed numeric-substrate arithmetic without being in "
            "the matrix. Mark the module with `pytestmark = "
            "pytest.mark.numeric_matrix`, or the single test with "
            "`@pytest.mark.numeric_matrix`, so it runs on the CPU and the GPU:"
        )
        lines.extend(f"    {nodeid}" for nodeid in _STATE.unmarked_seam_users)

    shortfall = matrix_shortfall(
        _STATE.matrix,
        _STATE.exercised,
        _STATE.matrix_selected,
        _STATE.full_suite,
        _STATE.tests_run,
        _STATE.stopped_early,
    )
    if shortfall:
        lines.append(shortfall)

    _STATE.verdict = lines
    return lines


def pytest_terminal_summary(
    terminalreporter, exitstatus: int, config: pytest.Config
) -> None:
    write = terminalreporter.write_line
    terminalreporter.write_sep("=", "petacat test matrix")

    if _STATE.matrix_selected:
        for role, name in _STATE.matrix:
            count = _STATE.exercised[name]
            write(
                f"  {role:<4} {name:<8} {_precision(name):<8} "
                f"{count:>5} test{'' if count == 1 else 's'}"
            )
    else:
        write("  no matrix tests were selected")

    covered = {role for role, _name in _STATE.matrix}
    available = _available()
    for role, preference in ROLE_PREFERENCES.items():
        if role in covered:
            continue
        reason = (
            "left out by --numeric-backends"
            if _STATE.matrix_requested and any(n in available for n in preference)
            else f"{'/'.join(preference)} is not installed here"
        )
        write(f"  {role:<4} not exercised: {reason}")

    # A role in the matrix that no selected test reached, named so the reader knows
    # what this run does and does not speak for.
    if _STATE.matrix_selected:
        for role, name in _STATE.matrix:
            if not _STATE.exercised[name]:
                write(f"  {role:<4} {name}: no selected test ran on it")

    if _STATE.full_suite:
        write("  whole suite requested: the full matrix is required of this run")
    else:
        write(
            f"  narrowed by {_STATE.narrowed_by}: this run reports the roles it "
            f"exercised and is not held to the full matrix"
        )

    if not _STATE.tests_run:
        write("")
        write("  no tests were run")
        for line in _verdict():
            write(f"  {line}")
        return

    write("")
    for layer in LAYERS:
        tally = _STATE.layers.get(layer)
        if tally is None or not tally.collected:
            continue
        state = "complete" if tally.run >= tally.collected else "INCOMPLETE"
        write(
            f"  {layer:<12} {tally.collected:>5} collected  {tally.run:>5} run  "
            f"{tally.passed:>5} passed  {tally.failed:>5} failed  "
            f"{tally.skipped:>5} skipped  {state}"
        )

    write("")
    ceiling = (
        f"{_STATE.ceiling_seconds / 60:g} min ceiling"
        if _STATE.ceiling_seconds
        else "no ceiling"
    )
    if _STATE.truncated_at is not None:
        write(
            f"  RUN TRUNCATED: the {ceiling} was reached after "
            f"{_minutes(_STATE.truncated_at)}. Everything above is what the run "
            f"produced before it stopped; the tests it had not reached never ran."
        )
        write(
            "  Raise the ceiling with --test-ceiling=MINUTES, or narrow the run, "
            "to get a complete result."
        )
    else:
        write(f"  run complete in {_minutes(_STATE.elapsed)} against a {ceiling}")

    for line in _verdict():
        write(f"  {line}")


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if _verdict() and session.exitstatus == pytest.ExitCode.OK:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
