# Testing Guide

This document defines how Petacat's **backend** tests are written and
organised. It exists so that new tests stay consistent, deterministic, and
focused on the research goals of the project. For the commands to *run* the
suites, see [README.md § Run the tests](README.md#6-run-the-tests).

## Test layers

The backend suite (`tests/`) is organised bottom-up into four layers:

| Layer | Directory | Scope | Dependencies | Tests |
|-------|-----------|-------|--------------|-------|
| **unit** | `tests/unit/` | One class/function, business logic only | None — all collaborators mocked | 601 |
| **module** | `tests/module/` | Assembly of a few real components | Real engine objects, no DB/HTTP | 282 |
| **integration** | `tests/integration/` | Seed-data consistency, codelet compilation | Real `seed_data/*.json` | 43 |
| **e2e** | `tests/e2e/` | Full HTTP API + persistence | Local PostgreSQL (`petacat_test`) | 123 |

A first pass should test **the lowest level of code just above the database
first**, then move up toward the API and GUI.

All four layers run in one command — `.venv/bin/python -m pytest tests/ -q` —
and, since Petacat runs natively, all four actually run: **1,049 tests, nothing
skipped**. This is worth stating because it was not true before. The e2e layer
used to need `docker compose exec app pytest tests/e2e/`, so a local `pytest`
skipped it and the number people quoted was the other three layers. A layer that
is normally skipped is not a layer that is normally green.

Wall-clock time depends heavily on the machine and on what else it is doing. The
expected-range check alone is ~1,300 engine runs across a process pool, and the
numeric-substrate tests dispatch to the GPU; on a quiet M2 Max the whole suite is
a couple of minutes, and on a busy one it is considerably longer — the run this
document's counts were taken from took 24 minutes on a machine that was
simultaneously running GPU benchmarks. Use `-m "not slow"` when you want a fast
loop rather than a number to compare.

> **If `tests/module/test_free_running.py` fails, check the numeric backend
> first.** That file is the one place the suite runs codelets concurrently, and
> it is sensitive to which numeric backend is in force: at the time of writing it
> is green under `PETACAT_NUMERIC_BACKEND=off`, `=python` and `=numpy`, and
> red under both `=mlx` and `=mlx-cpu` — and `mlx` is the default, so a plain
> full run can show failures that a backend-forced run does not. The symptoms
> have been a lost codelet-count increment and a group reachable from a bond but
> absent from its string's object list, both races the commit discipline is meant
> to exclude. Re-running with `PETACAT_NUMERIC_BACKEND=numpy` is the quickest way
> to tell a genuine concurrency defect from an MLX interaction.

The database it needs is the local Postgres (`scripts/dev.sh db` starts it and
creates the databases). e2e talks to `petacat_test`, deliberately separate from
the development database on the same instance, so a test run cannot disturb the
runs and episodic memory accumulated in `petacat`. `TEST_DATABASE_URL` overrides
it; if no Postgres is reachable, the e2e layer skips rather than fails.

Two pytest sessions sharing `petacat_test` would destroy each other's schema,
because `setup_db` drops and recreates every table at session scope. That is not
hypothetical — it produced two `relation "runs" does not exist` failures that
looked like a free-threading defect and were not. `tests/e2e/conftest.py` now
holds a Postgres advisory lock for the session, so concurrent suites serialise
instead of interleaving.

Shared helpers that more than one test module needs live in `tests/support/`.
That directory is imported, never collected.

### What each layer covers now

The four layers are shapes, not subject areas, so it is worth naming where the
Phase 0 substrate is tested:

- **`tests/unit/`** — the usual data structures and formulas, plus the numeric
  backends compared against the pure-Python reference
  (`test_numeric_backends.py`), the counter-based RNG (`test_splittable_rng.py`),
  incremental coderack eviction (`test_coderack_eviction.py`), the `RunSink`
  protocol (`test_sink.py`), and the **engine purity invariant**
  (`test_engine_purity.py`), which fails if anything under `server/engine/**`
  imports `sqlalchemy`, `server.models`, `server.db` or `server.services`.
- **`tests/module/`** — the engine assembled and driven: state-graph round trips
  (`test_state_graph.py`), read/write sets (`test_access_sets.py`), coderack
  shard fidelity (`test_coderack_shards.py`), free-running
  (`test_free_running.py`), the numeric substrate in a live run
  (`test_numeric_engine.py`), deliberate staleness (`test_staleness.py`),
  population batching (`test_population.py`), per-run identifiers
  (`test_run_identifiers.py`), and the expected-range oracle.
- **`tests/e2e/`** — the HTTP stack, including the three persistence modes
  (`test_persistence_modes.py`) and the review endpoints
  (`test_api_review.py`).

### The `slow` marker

A test that costs seconds to minutes is marked `@pytest.mark.slow`. Marked tests
still run by default — they are guards, and a guard that has to be remembered is
not a guard — but a tight edit-test loop can drop them with `-m "not slow"`.

The one that matters is the **expected-range check**
(`tests/module/test_expected_range.py`), which samples each of the 13 distinct
demo problems 100 times and compares the set of stopping states reached against
the saturated baseline in `tests/fixtures/expected_range.json`.

That baseline is the project's **regression oracle**, and it is worth
understanding why it is a *set* rather than a seeded run. Petacat is stochastic
by design, so a different-but-correct run is right behaviour, and any change
that reorders random draws — a new scheduler, a different generator, float32
arithmetic — legitimately changes which answer a given seed produces. What must
not change is which answers are *reachable*. The baseline was built by
`scripts/build_expected_range.py`, which samples each problem until the
Good-Turing missing-mass estimate `f₁/N` says the set is saturated: 13 problems,
410,000 runs.

Run it whenever the codelet scheduler, the random stream, the numeric backend or
the order of the update cycle moves. Its checker
(`tests/support/expected_range.py`) can be pointed at a modified engine through a
`run_one` callable, which is how the staleness, sharding, free-running and
numeric-backend work is all verified against the same comparison rather than
against four hand-rolled ones.

A stopping state outside the range means **investigate**, not necessarily
**fail**: at the baseline's saturation level a genuinely novel state shows up
about 1% of the time per problem. Re-run that problem deeply, and if the state
proves old-but-rare, admit it to the baseline under `admitted_states` —
`build_expected_range.py` carries those through a rebuild, since the range is
otherwise reconstructed from the saturation counts and they would be silently
dropped.

### Running under the free-threaded interpreter

`.venv-ft` holds CPython 3.14.6 built without the GIL (`python3.14t`,
`Py_GIL_DISABLED=1`). It exists because the concurrency work is meaningless on
an interpreter that cannot execute Python on two cores at once, and the suite is
run under it as well as under the standard build.

```bash
# The suite, with the GIL genuinely off
PYTHON_GIL=0 .venv-ft/bin/python -m pytest tests/ -q

# One layer, quickly
.venv-ft/bin/python -m pytest tests/unit/ -q
```

`PYTHON_GIL=0` is not decoration. Importing SQLAlchemy **re-enables the GIL at
runtime** — `sqlalchemy.cyextension.collections` has not declared free-threaded
safety, and CPython silently switches the lock back on when it loads such a
module — so without the override the e2e layer runs with the GIL on and the
free-threaded build tells you nothing. Importing the *engine* leaves the GIL off
unaided, because the engine imports nothing beyond the standard library and
itself; that is the property `tests/unit/test_engine_purity.py` protects, and it
is the reason codelet parallelism gets a genuinely lock-free interpreter while
only the API process pays.

NumPy and MLX are not installed in `.venv-ft`, so the numeric substrate falls
back to its pure-Python reference backend there. Tests that need a specific
backend skip rather than fail when it is unavailable.

The interpreter costs roughly 9% single-threaded against the standard build,
with identical codelet counts — so it is the interpreter's overhead, not
different cognition, and the parallelism has to beat it before it earns
anything.

### Benchmarks are not tests

`scripts/bench_*.py` measure; they do not assert, and they are not collected by
pytest. They exist so that a performance claim in `PHASE 0 PLAN.md` can be
re-derived rather than trusted: `bench_engine.py` (per-phase timings and Amdahl
fractions), `bench_numeric.py` (backend scaling from 59 to 10⁵ nodes),
`bench_shards.py` (coderack shard fidelity and contention),
`bench_free_running.py` (throughput and conflict rate by worker count), and
`bench_population.py` (runs per second at K = 1/8/32/128). They take minutes and
load the machine, so run them deliberately.

## Unit-test rules

Every file in `tests/unit/` must obey these five rules:

1. **Business logic only.** Test algorithms and behaviour — not glue code,
   framework wiring, or API endpoints. A test that only asserts a constant is
   a string, an enum's membership, or a dataclass echoes its constructor args
   is *not* a unit test and does not belong here.
2. **One path per test.** Each test exercises a single path through the unit.
   Alternative branches, boundary cases, and error paths are **separate
   tests**. If a test asserts across two branches (e.g. `threshold=100` *and*
   `threshold=0`, or "identity" *and* "slippage"), split it.
3. **Completely mock dependencies.** A unit test isolates one unit; replace
   every collaborator with a deterministic double (see
   [Test doubles](#test-doubles-tests-unit_fakespy)). If a unit's
   dependencies are so extensive that mocking is impractical, that is a signal
   to **refactor the source** for testability (dependency injection,
   abstraction, polymorphism, parameterization) rather than to write a heavy,
   coupled test. Refactoring source code to make it testable is encouraged.
4. **Deterministic.** No test may depend on wall-clock time or unseeded
   randomness. Petacat funnels all randomness through
   [`engine/rng.py`](server/engine/rng.py); construct `RNG(seed)` with a fixed
   seed, or supply deterministic mock data. The same test must produce the
   same result on every machine and every run.
5. **Bottom-up, research-driven.** Prioritise coverage from the data-structure
   layer upward. Within that ordering, weight effort toward the modules that
   carry the project's research contribution — the **self-watching**
   machinery: Themespace (`themes.py`), Temporal Trace (`trace.py`), Episodic
   Memory (`memory.py`), and Jootsing (`jootsing.py`).

## Test doubles (`tests/unit/_fakes.py`)

Shared, hand-rolled fakes live in `tests/unit/_fakes.py` (the leading
underscore keeps pytest from collecting it as a test module). They implement
*only* the surface the engine actually consumes, so a test reads as an
explicit statement of the unit's true inputs:

- `FakeNode` — a slipnet node (`activation`, `conceptual_depth`,
  `fully_active()`, link lists). `fully_active` is an explicit boolean the
  test sets, so relevance logic never depends on real activation thresholds.
- `FakeLink` — a slipnet link with a fixed `degree_of_association()`.
- `FakeString` — a workspace string with independent `objects` / `letters` /
  `groups` lists.
- `FakeObject` / `FakeContainer` — an atomic object vs. a group-like container
  (the latter can nest members for containment checks).
- `FakeDescription` — a description entry carried on `object.descriptions`.

Where a unit needs geometry or config the shared fakes don't carry (e.g. bond
string positions, or the Themespace's coefficient reads), define a small local
fake in that test file rather than bloating `_fakes.py`. Config-heavy units are
mocked with a per-file `_FakeMeta` that returns fixed coefficients — this keeps
formula-driven dynamics (e.g. the Themespace `tanh` spreading) exactly
assertable.

Prefer explicit fakes over `unittest.mock` for engine collaborators: they are
clearer, self-documenting, and impossible to mis-configure into passing
vacuously.

---

## Deferred work (prioritised TODO)

Discovered during the first unit-testing pass. Ordered by priority.

### P1 — Continue bottom-up coverage of low-level structures
- [x] `groups.py` — length, spanning, membership/containment, internal/external
      strength, flipping, constituent queries (`test_groups.py`).
- [x] `workspace_objects.py` — geometry, bond bookkeeping, importance,
      intra-string unhappiness, bridge weakness (`test_workspace_object.py`).
- [x] `workspace.py` → `WorkspaceString` — bond/group management, counting,
      equivalence, spanning, relevance (`test_workspace_string.py`).
- [ ] `workspace.py` → `Workspace` — the outer container's aggregation
      (average unhappiness, mapping strength, unmapped-object counts). Several
      of these methods reach across strings/bridges; isolate with fakes or flag
      for refactoring where the coupling is heavy.

### P2 — Deepen self-watching (research core)
- [ ] `trace.py` — pattern detection beyond the basic record/snag paths.
- [ ] `jootsing.py` — snag detection and jootsing (negative-theme clamping).
- [ ] `themes.py` — multi-theme intra-cluster excite/inhibit dynamics
      (the first pass pins the single-theme decay path only).
- [ ] `justify.py` — justification-mode rule building and translation.

### P3 — Broaden mid-level coverage
- [ ] `rules.py` — quality computation (uniformity / abstractness /
      succinctness); currently only predicates + `translate` are tested.
- [ ] `bridges.py` — convert the integration-flavoured tests to isolated units
      with a stub letter instead of a full `Workspace`.
- [ ] `images.py` — abstract image pattern matching.

### P4 — Finish the audit cleanup
- [ ] Replace the vacuous assertions in `test_codelet_behaviours.py` (tests
      that only assert "doesn't crash" or `after >= before`) with meaningful
      checks, or move them to `tests/module/`.
- [ ] Decide the fate of the pure constant/enum tests (Rule 1 violations):
      delete, or consciously keep as change-detector guards and document why.
- [ ] The full-engine-driving tests in `test_runner_status.py` and parts of
      `test_codelet_dsl.py` are integration tests living under `tests/unit/`;
      relocate them to `tests/module/`.

### P5 — Testability refactors (source changes, pre-approved)
- [ ] `concept_mappings._descriptor_is_distinguishing` does an inline
      `from ...groups import Group` for an `isinstance` check — replace with a
      polymorphic `obj.is_group()` so the group path is unit-testable without
      constructing a real `Group`.
- [ ] `themes.ThemeCluster.spread_activation` reads ~8 coefficients from
      `meta` — parameterize so the dynamics can be tested without a full
      `MetadataProvider`.
