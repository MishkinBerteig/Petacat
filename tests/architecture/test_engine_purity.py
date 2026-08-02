"""Engine purity invariant — the engine must never reach for the database layer.

`server/engine/` is the cognitive architecture: workspace, slipnet, coderack,
themespace, trace, memory, temperature. Every module in it is database-free, so
`EngineRunner(meta)` plus `MetadataProvider.from_seed_data(seed_dir)` runs a
complete problem with no Postgres, no Docker and no FastAPI. That property is
what lets the engine be benchmarked, fuzzed over hundreds of thousands of runs,
and eventually parallelised without dragging a session and an event loop along.

Today the property holds by discipline. This test makes it hold by construction:
a single `from server.services...` added to a codelet or a formula module would
otherwise pass review unnoticed and quietly couple the architecture to the
persistence layer.

The main check is static — it parses source with `ast` and never imports anything
it inspects. That matters because a real `from sqlalchemy import select` cannot
hide from an AST walk the way it can hide from a grep of a file that also
mentions SQLAlchemy in a docstring, and because the scan works on a checkout
where the database layer is not installed at all.

Static analysis alone is necessary but not sufficient: it proves no engine
*source file* names the database layer, not that the engine actually runs
without it. The last test in the file closes that gap for the serializers by
running them in a fresh interpreter with the database layer made unimportable.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from dataclasses import dataclass

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ENGINE_DIR = os.path.join(REPO_ROOT, "server", "engine")
SEED_DATA_DIR = os.path.join(REPO_ROOT, "seed_data")
CODELET_SEED_FILE = os.path.join(REPO_ROOT, "seed_data", "codelet_types.json")

# The four roots named by the Phase 0 plan (WP0.2). Any module whose dotted name
# equals one of these, or is a submodule of one, is banned from the engine.
FORBIDDEN_ROOTS = (
    "sqlalchemy",     # the ORM itself
    "server.models",  # ORM row definitions
    "server.db",      # async engine and session factory
    "server.services",  # the only writers of run state
)

# Decision: `if TYPE_CHECKING:` imports are NOT exempt.
#
# The tempting argument for exempting them is that they never execute, so an
# engine module carrying one still runs without the database layer installed.
# The invariant this test defends is larger than that. A type-only import of
# `server.models.Run` means an engine signature is expressed in terms of a
# database row, which is exactly the coupling later phases must not inherit; it
# also makes type-checking the engine require SQLAlchemy to be installed, and it
# is one deleted `if` away from being a runtime import. The exemption also costs
# nothing to refuse: every `TYPE_CHECKING` block in the engine today imports
# from `server.engine.*` and nothing else, so enforcing the ban uniformly rules
# out a future leak without flagging a single existing line.
#
# The checker therefore walks the entire module tree, including `TYPE_CHECKING`
# blocks, function bodies and `try`/`except ImportError` blocks — a deferred
# import inside a function is the most likely place for this coupling to appear.

# Floor on the number of engine modules scanned. The engine has 30 `.py` files
# today (29 modules plus an empty `codelet_dsl/__init__.py`). The floor is not a
# census — modules may legitimately come and go — it exists so that a broken
# path, a renamed directory or a glob that silently matches nothing cannot make
# this test pass vacuously, which is how invariant tests usually rot.
MIN_ENGINE_MODULES = 25

# Same reasoning for the DSL bodies: 27 codelet types are seeded today.
MIN_CODELET_BODIES = 20

# --- Third-party imports: a separate, weaker rule ---------------------------
#
# The ban above is about the *database layer*, and it is absolute. Third-party
# packages in general are not banned: `FORBIDDEN_ROOTS` names four roots and says
# nothing about anything else, so `import numpy` in an engine module has always
# been permitted by this file's policy.
#
# WP4.5 is the first work package to use that permission, and it is worth being
# explicit about the decision rather than leaving it to be inferred from the
# absence of a rule. The numeric substrate (`server/engine/numeric/`) can put
# activation spreading on NumPy or on the GPU via MLX. Both are optional, and the
# property that matters is not "the engine imports nothing" but "the engine runs
# with nothing extra installed" — which is the same property the database ban
# defends, applied to a different dependency.
#
# So the rule is: a third-party import in the engine must be *declared here*, and
# must be reachable only through a guarded registry, never from a module the
# engine imports unconditionally. `server/engine/numeric/backend.py` does the
# guarding; `numpy_backend.py` and `mlx_backend.py` are the only modules allowed
# to import at the top level, and they are only ever imported inside a
# `try: ... except ImportError` that leaves the backend unregistered.
#
# Adding a name to this set is a decision, and it should be taken deliberately.
DECLARED_THIRD_PARTY = {"numpy", "mlx"}

# Engine modules permitted to import a declared package *at module level*.
# Anything else must defer the import into a function body, so that a process
# which never reaches for a backend never imports its dependency at all —
# `metal_kernels.py` does exactly that, and is deliberately absent from this set
# because deferring is the stronger arrangement, not a loophole in it.
THIRD_PARTY_IMPORTERS = {
    "server/engine/numeric/numpy_backend.py",
    "server/engine/numeric/mlx_backend.py",
}


@dataclass(frozen=True)
class Violation:
    """One forbidden import, located precisely enough to fix without searching."""

    location: str      # module path or codelet name
    line: int          # line number within that source
    statement: str     # the import as written
    imported: str      # the resolved dotted module name that is banned
    root: str          # which forbidden root it fell under

    def __str__(self) -> str:
        return (
            f"{self.location}:{self.line}: {self.statement}\n"
            f"        imports '{self.imported}', which belongs to the "
            f"forbidden root '{self.root}'"
        )


def _is_forbidden(module_name: str) -> str | None:
    """Return the forbidden root `module_name` falls under, or None.

    Matching is on dotted-name boundaries, so `server.models.run` is forbidden
    but a hypothetical `server.dbutils` or `sqlalchemy_stubs` is not.
    """
    for root in FORBIDDEN_ROOTS:
        if module_name == root or module_name.startswith(root + "."):
            return root
    return None


def _package_of(module_path: str) -> str:
    """Dotted package name containing `module_path`, e.g. `server.engine.codelet_dsl`.

    Needed to resolve relative imports: `from ..db import get_session` inside
    `server/engine/anything.py` resolves to `server.db` and must be caught.
    """
    rel = os.path.relpath(module_path, REPO_ROOT)
    parts = rel.replace(os.sep, "/").split("/")
    return ".".join(parts[:-1])


def _resolve_relative(package: str, level: int, module: str | None) -> str:
    """Resolve a relative `from ... import` to an absolute dotted name.

    `level` 1 means the containing package, 2 its parent, and so on — the same
    rule the import machinery uses.
    """
    parts = package.split(".") if package else []
    if level - 1 > 0:
        parts = parts[: -(level - 1)] if level - 1 <= len(parts) else []
    base = ".".join(parts)
    if module:
        return f"{base}.{module}" if base else module
    return base


def _scan_source(source: str, location: str, package: str = "") -> list[Violation]:
    """Return every forbidden import in `source`.

    `ast.walk` visits the whole tree, so imports nested inside `if TYPE_CHECKING:`,
    function bodies, class bodies and `try` blocks are all reached.
    """
    violations: list[Violation] = []
    tree = ast.parse(source, filename=location)
    lines = source.splitlines()

    def statement_text(node: ast.AST) -> str:
        index = getattr(node, "lineno", 0) - 1
        if 0 <= index < len(lines):
            return lines[index].strip()
        return "<source unavailable>"

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            # `import sqlalchemy`, `import server.db as db`
            for alias in node.names:
                root = _is_forbidden(alias.name)
                if root:
                    violations.append(
                        Violation(location, node.lineno, statement_text(node), alias.name, root)
                    )
        elif isinstance(node, ast.ImportFrom):
            # `from sqlalchemy import select`, `from server import db`,
            # `from ..services.run_service import RunService`
            if node.level:
                module = _resolve_relative(package, node.level, node.module)
            else:
                module = node.module or ""
            root = _is_forbidden(module)
            if root:
                violations.append(
                    Violation(location, node.lineno, statement_text(node), module, root)
                )
                continue
            # `from server import db` names the forbidden module as an alias,
            # not as the module being imported from.
            for alias in node.names:
                if alias.name == "*":
                    continue
                qualified = f"{module}.{alias.name}" if module else alias.name
                root = _is_forbidden(qualified)
                if root:
                    violations.append(
                        Violation(location, node.lineno, statement_text(node), qualified, root)
                    )

    return violations


def _engine_module_paths() -> list[str]:
    """Every `.py` file under `server/engine/`, recursively (includes `codelet_dsl/`)."""
    paths: list[str] = []
    for dirpath, dirnames, filenames in os.walk(ENGINE_DIR):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for filename in filenames:
            if filename.endswith(".py"):
                paths.append(os.path.join(dirpath, filename))
    return sorted(paths)


def _codelet_bodies() -> list[tuple[str, str]]:
    """(codelet name, execute_body) for every seeded codelet type.

    The seed JSON is the source of truth for the `execute_body` column: it is
    what `main.py` loads into the database at startup, and what
    `MetadataProvider.from_seed_data` reads directly when running without one.
    """
    with open(CODELET_SEED_FILE, encoding="utf-8") as handle:
        specs = json.load(handle)
    return [(spec["name"], spec.get("execute_body") or "") for spec in specs]


WHY_IT_MATTERS = (
    "\n\nThe engine must run with no database layer installed: no Postgres, no "
    "session, no FastAPI. That is what makes it benchmarkable, fuzzable over "
    "hundreds of thousands of runs, and parallelisable later. Move whatever "
    "needs persistence into server/services/ and pass the engine plain data."
)


def test_engine_module_set_is_non_trivial():
    """The scan actually reaches the engine — a broken path cannot pass vacuously."""
    paths = _engine_module_paths()
    assert len(paths) >= MIN_ENGINE_MODULES, (
        f"Only {len(paths)} Python modules found under {ENGINE_DIR}; expected at "
        f"least {MIN_ENGINE_MODULES}. The purity scan is looking in the wrong "
        f"place, so it would report no violations no matter what the engine does."
    )


def test_engine_scan_descends_into_subpackages():
    """`codelet_dsl/` is scanned — a non-recursive glob would silently skip it."""
    scanned = {os.path.relpath(p, REPO_ROOT) for p in _engine_module_paths()}
    dsl_modules = {p for p in scanned if "codelet_dsl" in p}
    assert dsl_modules, (
        "No modules from server/engine/codelet_dsl/ were scanned. The codelet "
        "interpreter and its builtins live there, and they are the most likely "
        "place for a database import to appear."
    )


def test_no_engine_module_imports_the_database_layer():
    """No module under server/engine/ imports sqlalchemy, server.models/db/services."""
    violations: list[Violation] = []
    for path in _engine_module_paths():
        location = os.path.relpath(path, REPO_ROOT)
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        violations.extend(_scan_source(source, location, package=_package_of(path)))

    assert not violations, (
        "The engine imports the database layer:\n\n"
        + "\n".join(f"  - {v}" for v in violations)
        + WHY_IT_MATTERS
    )


def test_no_codelet_body_imports_the_database_layer():
    """Codelet DSL sources are engine code too, and are held to the same rule.

    `execute_body` is Python source compiled with `compile()` and run with
    `exec()` inside the engine. A database import smuggled through a codelet
    would break the invariant exactly as thoroughly as one written into a module,
    and would do it at runtime, where no reviewer is reading.
    """
    violations: list[Violation] = []
    for name, body in _codelet_bodies():
        if not body.strip():
            continue
        violations.extend(_scan_source(body, f"codelet '{name}' (execute_body)"))

    assert not violations, (
        "A seeded codelet body imports the database layer:\n\n"
        + "\n".join(f"  - {v}" for v in violations)
        + WHY_IT_MATTERS
    )


def _roots_of(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Import):
        return {alias.name.split(".")[0] for alias in node.names}
    if isinstance(node, ast.ImportFrom) and not node.level and node.module:
        return {node.module.split(".")[0]}
    return set()


def _import_roots(source: str) -> tuple[set[str], set[str]]:
    """`(module-level roots, all roots)` for `source`.

    The distinction is the whole point. A module-level import runs when the module
    is imported and therefore makes the package required; an import inside a
    function body runs only when that function is called, and if the only caller
    is behind the registry then the package stays optional. The first walk stops
    at function boundaries; the second does not.
    """
    tree = ast.parse(source)
    module_level: set[str] = set()

    def descend(body: list[ast.stmt]) -> None:
        for node in body:
            module_level.update(_roots_of(node))
            # `if TYPE_CHECKING:`, `try:`/`except ImportError:` and class bodies
            # all execute at import time, so they are module level too. Function
            # bodies are not, and are the only thing not descended into.
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for field_name in ("body", "orelse", "finalbody"):
                nested = getattr(node, field_name, None)
                if isinstance(nested, list):
                    descend([s for s in nested if isinstance(s, ast.stmt)])
            for handler in getattr(node, "handlers", []):
                descend(handler.body)

    descend(tree.body)
    everything = set().union(*(_roots_of(n) for n in ast.walk(tree)), set())
    return module_level, everything


def _is_third_party(root: str) -> bool:
    return root not in sys.stdlib_module_names and root not in ("server", "__future__")


def test_engine_third_party_imports_are_declared_and_confined():
    """Every non-standard-library import in the engine is one we chose to allow.

    Two assertions, and they are two halves of the same guarantee.
    *Declared*: no third-party package appears anywhere in the engine without
    being named in `DECLARED_THIRD_PARTY`, so a dependency cannot arrive by
    accident. *Confined*: it is imported at module level only in the modules
    listed in `THIRD_PARTY_IMPORTERS`, so the dependency stays optional — a module
    the engine imports unconditionally cannot be the one that needs NumPy present.
    """
    undeclared: list[str] = []
    unexpected_importers: list[str] = []

    for path in _engine_module_paths():
        location = os.path.relpath(path, REPO_ROOT).replace(os.sep, "/")
        with open(path, encoding="utf-8") as handle:
            module_level, everything = _import_roots(handle.read())
        for root in sorted(everything):
            if not _is_third_party(root):
                continue
            if root not in DECLARED_THIRD_PARTY:
                undeclared.append(f"{location}: imports '{root}'")
            elif root in module_level and location not in THIRD_PARTY_IMPORTERS:
                unexpected_importers.append(
                    f"{location}: imports '{root}' at module level"
                )

    assert not undeclared, (
        "The engine imports third-party packages that are not declared:\n\n"
        + "\n".join(f"  - {v}" for v in undeclared)
        + "\n\nIf the dependency is wanted, add it to DECLARED_THIRD_PARTY and to "
        "an optional-dependency group in pyproject.toml, and make sure the engine "
        "still runs without it. If it is not wanted, remove the import."
    )
    assert not unexpected_importers, (
        "A third-party package is imported at module level outside the modules "
        "allowed to do that:\n\n"
        + "\n".join(f"  - {v}" for v in unexpected_importers)
        + "\n\nOptional dependencies stay optional only while every module-level "
        "import of them sits behind server/engine/numeric/backend.py's guarded "
        "registry. Defer the import into the function that needs it, or add the "
        "module to THIRD_PARTY_IMPORTERS if it genuinely belongs there."
    )


def test_the_declared_third_party_importers_exist_and_do_import_them():
    """The allowlist is not stale: each named module exists and uses its permission.

    Without this, deleting `mlx_backend.py` would leave an entry in
    `THIRD_PARTY_IMPORTERS` that silently permits a future module at that path.
    """
    for location in sorted(THIRD_PARTY_IMPORTERS):
        path = os.path.join(REPO_ROOT, location)
        assert os.path.exists(path), (
            f"{location} is listed as permitted to import a third-party package "
            f"but does not exist. Remove it from THIRD_PARTY_IMPORTERS."
        )
        with open(path, encoding="utf-8") as handle:
            module_level, _ = _import_roots(handle.read())
        assert module_level & DECLARED_THIRD_PARTY, (
            f"{location} is listed as permitted to import a declared third-party "
            f"package at module level but imports none of "
            f"{sorted(DECLARED_THIRD_PARTY)} there."
        )


@pytest.mark.parametrize(
    "source,module_level,everything",
    [
        ("import numpy", {"numpy"}, {"numpy"}),
        ("def f():\n    import numpy\n", set(), {"numpy"}),
        # Executed at import time even though it is nested, so still module level.
        ("try:\n    import mlx.core\nexcept ImportError:\n    pass\n",
         {"mlx"}, {"mlx"}),
        ("if TYPE_CHECKING:\n    import numpy\n", {"numpy"}, {"numpy"}),
        ("class A:\n    import numpy\n", {"numpy"}, {"numpy"}),
        ("from server.engine.numeric import layout", set(), set()),
    ],
)
def test_the_import_classifier_separates_module_level_from_deferred(
    source, module_level, everything
):
    """The distinction the confinement rule rests on, pinned one form at a time."""
    observed_module_level, observed_all = _import_roots(source)
    assert {r for r in observed_module_level if _is_third_party(r)} == module_level
    assert {r for r in observed_all if _is_third_party(r)} == everything


def test_codelet_body_set_is_non_trivial():
    """The codelet scan reaches real bodies rather than an empty or renamed file."""
    bodies = [body for _, body in _codelet_bodies() if body.strip()]
    assert len(bodies) >= MIN_CODELET_BODIES, (
        f"Only {len(bodies)} non-empty codelet bodies found in {CODELET_SEED_FILE}; "
        f"expected at least {MIN_CODELET_BODIES}. The DSL purity scan is not "
        f"seeing the codelet sources."
    )


# --- The serializers, named and exercised -----------------------------------
#
# `server/engine/serialization.py` is covered by the sweep above simply because
# it sits under `server/engine/`. Naming it explicitly is worth the two extra
# tests, because it is the one engine module that exists *as a consequence* of
# this invariant: the serializers used to live in
# `server/services/snapshot_service.py` next to `sqlalchemy` and
# `server.models.run` imports (defect D2), which meant reading engine state
# required the ORM. WP3.1 split them out. A test that names the module records
# what was bought and fails loudly if someone moves it back, instead of leaving
# the guarantee to be inferred from a directory listing.

SERIALIZATION_MODULE = os.path.join(ENGINE_DIR, "serialization.py")


def test_serialization_module_lives_in_the_engine_and_is_scanned():
    """The serializers are engine code, and the purity sweep reaches them."""
    assert os.path.exists(SERIALIZATION_MODULE), (
        "server/engine/serialization.py is missing. The pure serialize_* "
        "functions belong in the engine; if they have moved back into "
        "server/services/, reading engine state once again requires importing "
        "the database layer (defect D2)."
    )
    assert SERIALIZATION_MODULE in _engine_module_paths(), (
        "server/engine/serialization.py exists but was not picked up by the "
        "purity scan, so the ban on database imports is not being applied to it."
    )


def test_serialization_module_imports_no_database_layer():
    """Stated by name: reading engine state must not require the ORM."""
    with open(SERIALIZATION_MODULE, encoding="utf-8") as handle:
        source = handle.read()
    violations = _scan_source(
        source, "server/engine/serialization.py", package="server.engine"
    )
    assert not violations, (
        "The serializers import the database layer again:\n\n"
        + "\n".join(f"  - {v}" for v in violations)
        + "\n\nThe whole point of server/engine/serialization.py is that engine "
        "state can be read without a session, a driver or an ORM anywhere in "
        "sight. Persistence belongs in server/services/snapshot_repository.py."
    )


# The probe below runs in a *separate* interpreter, and that is the substance of
# the test rather than an implementation detail.
#
# Blocking `sqlalchemy` inside the pytest process would prove nothing: by the
# time this file runs, other tests have already imported `server.services.
# run_service`, so SQLAlchemy is sitting in `sys.modules` and any import of it
# would succeed from cache no matter what the engine does. Only a fresh
# interpreter, with the block installed before the first engine import, can
# answer the question honestly.
#
# The block is a `sys.meta_path` finder that *raises* rather than returning
# None, because returning None would simply let the next finder locate the real
# package. Raising `ModuleNotFoundError` reproduces exactly what a checkout with
# no database layer installed would do — including being swallowed by a
# `try: import sqlalchemy / except ImportError:` if any engine module were ever
# to hedge that way, which is the behaviour we want to inherit rather than
# paper over.
#
# The probe does not merely import the module: it builds a real EngineContext,
# runs codelets until there are structures to serialise, calls all seven
# serializers, and JSON-encodes the result — the same work `save_cycle_snapshot`
# does. An import that succeeds while the first call reaches for a session
# would be a split in name only.

_ABSENT_DATABASE_PROBE = r'''
import importlib.abc
import json
import sys

REPO_ROOT, SEED_DIR = sys.argv[1], sys.argv[2]
sys.path.insert(0, REPO_ROOT)

FORBIDDEN = ("sqlalchemy", "server.models", "server.db", "server.services")


class DatabaseLayerAbsent(importlib.abc.MetaPathFinder):
    """Makes the database layer unimportable, as on a checkout without it."""

    def find_spec(self, fullname, path=None, target=None):
        for root in FORBIDDEN:
            if fullname == root or fullname.startswith(root + "."):
                raise ModuleNotFoundError(
                    "the database layer is deliberately absent from this "
                    "interpreter: " + fullname,
                    name=fullname,
                )
        return None


sys.meta_path.insert(0, DatabaseLayerAbsent())

from server.engine import serialization
from server.engine.metadata import MetadataProvider
from server.engine.runner import (
    EngineRunner, STATUS_ANSWER_FOUND, STATUS_GAVE_UP, STATUS_HALTED,
)

runner = EngineRunner(MetadataProvider.from_seed_data(SEED_DIR))
runner.init_mcat("abc", "abd", "xyz", seed=42)
for _ in range(400):
    if runner.status in (STATUS_ANSWER_FOUND, STATUS_GAVE_UP, STATUS_HALTED):
        break
    runner.step_mcat()

ctx = runner.ctx
workspace = serialization.serialize_workspace_state(ctx)
state = {
    "rng": serialization.serialize_rng_state(ctx),
    "workspace": workspace,
    "slipnet": serialization.serialize_slipnet_state(ctx),
    "coderack": serialization.serialize_coderack_state(ctx),
    "themespace": serialization.serialize_themespace_state(ctx),
    "trace": serialization.serialize_trace_state(ctx),
    "runner": serialization.serialize_runner_state(ctx),
}
blob = json.dumps(state)

# Cross-check the finder: nothing forbidden reached sys.modules by some route
# the finder did not see, such as a C extension or a pre-seeded entry.
leaked = sorted({name for name in list(sys.modules)
                 for root in FORBIDDEN
                 if name == root or name.startswith(root + ".")})

structures = (
    sum(len(v) for v in workspace["bonds"].values())
    + sum(len(v) for v in workspace["groups"].values())
    + len(workspace["top_bridges"])
    + len(workspace["vertical_bridges"])
    + len(workspace["bottom_bridges"])
    + len(workspace["top_rules"])
    + len(workspace["bottom_rules"])
)
print(json.dumps({
    "json_bytes": len(blob),
    "codelets": ctx.codelet_count,
    "structures": structures,
    "leaked": leaked,
}))
'''


def test_serializers_run_with_the_database_layer_absent():
    """A real run is serialised in an interpreter where the ORM cannot be imported."""
    completed = subprocess.run(
        [sys.executable, "-c", _ABSENT_DATABASE_PROBE, REPO_ROOT, SEED_DATA_DIR],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert completed.returncode == 0, (
        "Serializing engine state failed in an interpreter with no database "
        "layer available. Either server/engine/serialization.py imports it "
        "again, or something it depends on does.\n\n"
        f"--- stderr ---\n{completed.stderr}\n"
        f"--- stdout ---\n{completed.stdout}"
    )

    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result["leaked"] == [], (
        "The probe finished, but these database-layer modules were loaded "
        f"anyway: {result['leaked']}. The import block missed a route in, so "
        "the run does not prove what it claims to."
    )
    # Guards against the reassuring-but-empty version of this test: serializing
    # a workspace with nothing in it would exercise none of the _serialize_bond
    # / _serialize_bridge / _serialize_group / _serialize_rule helpers. Which
    # kinds of structure exist by codelet 400 is stochastic, so the assertion is
    # on the total rather than on any one kind.
    assert result["codelets"] > 0
    assert result["structures"] > 0, (
        "The probe serialised an empty workspace, so the per-structure helpers "
        "never ran and the test would pass even if they needed a session."
    )
    assert result["json_bytes"] > 10_000, (
        f"Only {result['json_bytes']} bytes of state were produced; a snapshot "
        f"of a run in progress is ~43 KB. The serializers are returning far "
        f"less than a real snapshot, so little of them was exercised."
    )


# --- The checker's own tests ------------------------------------------------
#
# A static-analysis guard that stops detecting anything still passes. These
# tests pin the detector itself, one import form per case, so that the guard
# above cannot decay into an assertion about an empty list.

@pytest.mark.parametrize(
    "source,expected_module",
    [
        ("import sqlalchemy", "sqlalchemy"),
        ("import sqlalchemy.orm", "sqlalchemy.orm"),
        ("import server.db as db", "server.db"),
        ("from sqlalchemy import select", "sqlalchemy"),
        ("from sqlalchemy.ext.asyncio import AsyncSession", "sqlalchemy.ext.asyncio"),
        ("from server.models.run import Run", "server.models.run"),
        ("from server import db", "server.db"),
        ("from server.services.run_service import RunService", "server.services.run_service"),
    ],
)
def test_detector_catches_absolute_forbidden_import(source, expected_module):
    """Each spelling of an absolute forbidden import is detected."""
    violations = _scan_source(source, "example.py")
    assert [v.imported for v in violations] == [expected_module]


def test_detector_catches_relative_forbidden_import():
    """`from ..db import ...` inside the engine resolves to server.db and is caught."""
    violations = _scan_source(
        "from ..db import get_session", "server/engine/example.py", package="server.engine"
    )
    assert len(violations) == 1
    assert violations[0].imported == "server.db"
    assert violations[0].root == "server.db"


def test_detector_catches_import_hidden_in_a_function():
    """A deferred import inside a function body is caught — ast.walk sees the whole tree."""
    source = "def save(run):\n    from server.services import run_service\n    return run_service\n"
    violations = _scan_source(source, "example.py")
    assert len(violations) == 1
    assert violations[0].imported == "server.services"
    assert violations[0].line == 2


def test_detector_catches_import_guarded_by_type_checking():
    """TYPE_CHECKING imports are not exempt — see the decision note above."""
    source = (
        "from typing import TYPE_CHECKING\n"
        "\n"
        "if TYPE_CHECKING:\n"
        "    from server.models.run import Run\n"
    )
    violations = _scan_source(source, "example.py")
    assert len(violations) == 1
    assert violations[0].imported == "server.models.run"
    assert violations[0].line == 4


def test_detector_ignores_forbidden_names_in_strings_and_comments():
    """Docstrings, comments and string literals naming sqlalchemy are not imports."""
    source = (
        '"""This module deliberately avoids sqlalchemy and server.services."""\n'
        "# import sqlalchemy  <- would violate the purity invariant\n"
        "DRIVER = 'sqlalchemy+asyncpg'\n"
        "import json\n"
    )
    assert _scan_source(source, "example.py") == []


@pytest.mark.parametrize(
    "source",
    [
        "import json",
        "from server.engine.slipnet import Slipnet",
        "from server.engine.codelet_dsl.builtins import choose_object",
        "from . import formulas",
        "from typing import TYPE_CHECKING",
    ],
)
def test_detector_allows_pure_imports(source):
    """Standard library and intra-engine imports are what the engine is made of."""
    assert _scan_source(source, "server/engine/example.py", package="server.engine") == []


def test_violation_message_names_module_line_and_import():
    """The failure text points at the exact line, so no searching is needed to fix it."""
    violations = _scan_source(
        "import json\nfrom sqlalchemy import select\n", "server/engine/example.py"
    )
    message = str(violations[0])
    assert "server/engine/example.py:2" in message
    assert "from sqlalchemy import select" in message
    assert "sqlalchemy" in message
