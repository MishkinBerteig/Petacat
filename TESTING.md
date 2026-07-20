# Testing Guide

This document defines how Petacat's **backend** tests are written and
organised. It exists so that new tests stay consistent, deterministic, and
focused on the research goals of the project. For the commands to *run* the
suites, see [README.md § Run the tests](README.md#4-run-the-tests).

## Test layers

The backend suite (`tests/`) is organised bottom-up into four layers:

| Layer | Directory | Scope | Dependencies |
|-------|-----------|-------|--------------|
| **unit** | `tests/unit/` | One class/function, business logic only | None — all collaborators mocked |
| **module** | `tests/module/` | Assembly of a few real components | Real engine objects, no DB/HTTP |
| **integration** | `tests/integration/` | Seed-data consistency, codelet compilation | Real `seed_data/*.json` |
| **e2e** | `tests/e2e/` | Full HTTP API + persistence | Docker + PostgreSQL |

A first pass should test **the lowest level of code just above the database
first**, then move up toward the API and GUI.

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
