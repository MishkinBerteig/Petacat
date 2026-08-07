# Petacat

**A self-watching cognitive architecture for analogy-making, ported from
Scheme to Python and React.**

Petacat is a port of [Metacat][metacat], a self-watching cognitive
architecture for analogy-making created by [James B. Marshall][marshall] in
his 1999 PhD dissertation at Indiana University. Metacat is itself an
extension of [Copycat][copycat] (Mitchell & Hofstadter), adding
self-monitoring via a Themespace and Temporal Trace so the system can notice
when it is stuck, break out of repetitive patterns, and explain why one
analogy is better than another.

Like the original, Petacat operates on letter-string analogy problems of the
form `abc → abd; xyz → ?` and produces answers by building perceptual
structures, discovering transformation rules, and translating those rules
across contexts. The original implementation is in Petite Chez Scheme with a
Tcl/Tk GUI; this port moves the engine to Python and replaces the Tcl/Tk GUI
with a web-based React frontend backed by PostgreSQL. Petacat was written
using both Marshall's dissertation and his original Scheme source code as
references — it is a port rather than a clean-room reimplementation, and the
license change was authorised by Dr. Marshall directly (see
[LICENSE.md](LICENSE.md)).

> **Status.** Petacat implements all seven of Metacat's core components
> (Workspace, Slipnet, Coderack, Themespace, Temporal Trace, Episodic Memory,
> Temperature) and generates answers to letter-string analogy problems
> end-to-end. Episodic Memory shapes the runs that inherit it: a run declines an
> answer already held for the same problem and rules, so repeating a problem
> within a [Training Session](#persistence-modes-and-training-sessions) explores
> a different answer each time. It ships with 2,222 test cases covering the engine, the API, and the
> help/config system, run on both the CPU and the GPU numeric backends. Underneath the seven components sits an execution
> substrate — three [persistence modes](#persistence-modes-and-training-sessions),
> a [GPU numeric substrate](#the-numeric-substrate), and
> [barrier-free codelet parallelism](#free-running-codelets-across-cpu-cores) —
> which changes how Petacat runs without changing what it perceives. See
> [Acknowledgements & License](#acknowledgements) below for credits and
> licensing.

[metacat]: http://science.slc.edu/~jmarshall/metacat/
[marshall]: http://science.slc.edu/~jmarshall/
[copycat]: https://en.wikipedia.org/wiki/Copycat_(software)

## Architecture

- **Backend**: Python 3.14 / FastAPI / SQLAlchemy / PostgreSQL
- **Frontend**: React / TypeScript / Vite
- **Execution**: native — engine, API, client and database all run on the host
- **Numeric substrate**: the engine's array arithmetic runs on the GPU through
  Metal (MLX), with vectorised-CPU and pure-Python backends behind the same seam
- **Parallelism**: codelets can run across CPU cores with no global barrier

Engine parameters, slipnet topology, codelet definitions and theme dimensions
live in `seed_data/*.json`, which the API reads at startup and which seeds the
database. Codelet behaviour is expressed as Python source strings, compiled once
at startup and executed via `exec()` in a sandboxed namespace.

Edit that configuration through the Configuration screen: every one of the
twelve collections has a tab that creates, updates and deletes its rows, and a
change is written to the database and picked up by the next run created. **Export Current Settings to
Seed Data** writes the database's configuration back to `seed_data/*.json`,
which is how a configuration arrived at in the app becomes the project's
starting point. Each replaced file is copied first, under a timestamp, into
`seed_data/.backups/`.

`GET /api/admin/export` and `POST /api/admin/import` carry the same twelve
collections as one JSON object — slipnet nodes and links, codelet types, engine
parameters, urgency levels, formula coefficients, demo problems, theme
dimensions, posting rules, commentary templates, slipnet layout and help topics.
Export orders every collection by primary key, so two exports of one
configuration are the same bytes and a backup diffs against the file it came
from. Import matches each row on its primary key, applies every collection the
payload names, reports the row count it wrote for each, and runs as a single
transaction.

The engine itself is **database-free**: nothing under `server/engine/` imports
SQLAlchemy, opens a session, or awaits I/O, and a test
(`tests/architecture/test_engine_purity.py`) fails if that ever stops being true. It is
worth enforcing rather than merely observing, because two useful properties
depend on it: a run can execute with the database stopped, and the engine can be
imported into a free-threaded interpreter without the GIL being switched back
on.

### Core Components

| Component | Python module | Purpose |
|-----------|--------------|---------|
| Workspace | `server/engine/workspace.py` | 4 letter strings + perceptual structures |
| Slipnet | `server/engine/slipnet.py` | 59-node semantic network with activation spreading |
| Coderack | `server/engine/coderack.py` | Stochastic scheduler (7 urgency bins, 100 max codelets) |
| Themespace | `server/engine/themes.py` | Self-watching: theme clusters, activation dynamics |
| Temporal Trace | `server/engine/trace.py` | Chronological event log |
| Episodic Memory | `server/engine/memory.py` | Cross-run answer/snag storage; gates rediscovery |
| Temperature | `server/engine/temperature.py` | Global exploration/exploitation control (0–100) |
| Runner | `server/engine/runner.py` | Main control loop (`init_mcat`, `step_mcat`, `update_everything`) |

### Update Cycle Order

Every 15 codelets, `update_everything()` runs in this order (matching the
original Scheme `run.ss:295-315`):

1. Check whether rules are possible
2. Update workspace structure strengths
3. Update object importances, unhappiness, salience
4. Snag-period stochastic exit
5. Clamp-period expiration check
6. Tick clamp expirations (slipnet + temperature) — Petacat's own mechanism, so a
   clamp lapses on the update cycle that reaches its expiry
7. Spread activation: workspace → themespace
8. Spread activation within themespace
9. Update slipnet: theme→slipnet, then internal decay/spread/jump
10. Update temperature
11. Post bottom-up codelets, then top-down codelets

## Getting Started

Petacat runs natively: the engine, the API, the client and the database are all
ordinary processes on your machine. There is no container stack. The engine's
performance work needs the host's own cores and its own profiler, and a Linux VM
between the engine and an Apple-silicon chip hides exactly the properties that
work is trying to measure — it also used to keep the end-to-end tests behind a
`docker compose exec` that local test runs simply skipped.

The instructions below are written for macOS with Homebrew, which is what the
project is developed and measured on. Nothing but the package manager is
platform-specific.

### 1. Install the prerequisites

```bash
brew install postgresql@17 python@3.14 node
brew services start postgresql@17
```

- **PostgreSQL 17** holds the history of every run — recorded states, traces,
  audit actions and episodic memory — and the editable copy of the configuration
  that the Configuration screen writes to. The API requires it to start.

  The schema lives in `alembic/versions/`. Startup creates any missing tables, so
  a fresh database is ready as soon as the API comes up. Bring an existing
  database forward with `.venv/bin/alembic upgrade head`, which is what applies
  the column additions a newer version expects.
- **Python 3.14** is the only supported interpreter (`requires-python = ">=3.14"`
  in `pyproject.toml`). Pinning one version matters here: the engine is a
  measurement subject, and results taken on two interpreters are not comparable.
- **Node** runs the Vite dev server and the frontend tests. Developed against
  v26.

### 2. Set up the project

```bash
python3.14 -m venv .venv
.venv/bin/pip install -e ".[dev,gpu]"
```

The install is editable, which is also what puts `server` on the interpreter's
path — the API and the test suite then find it with no `PYTHONPATH` set. `[dev]`
adds pytest and httpx.

`[gpu]` adds NumPy and MLX, which is what puts the engine's arithmetic on the
GPU's Metal cores (see [The numeric substrate](#the-numeric-substrate)).
Neither package is required: `server/engine/numeric/` ships a pure-Python
reference backend that is always available, and with NumPy and MLX absent the
engine computes exactly the same answers through it. `[numeric]` is the NumPy
half alone, which is the honest CPU baseline the GPU is measured against.

#### The free-threaded interpreter

A second virtual environment, `.venv-ft`, holds CPython 3.14.6 built without the
global interpreter lock (`python3.14t`, `Py_GIL_DISABLED=1`). It exists because
[free-running](#free-running-codelets-across-cpu-cores) only pays on an
interpreter that can actually execute Python on more than one core at a time.

```bash
brew install python-freethreading
python3.14t -m venv .venv-ft
.venv-ft/bin/pip install -e ".[dev]"
```

One wrinkle worth knowing before it confuses you. Importing SQLAlchemy
**switches the GIL back on at runtime** — `sqlalchemy.cyextension.collections`
has not declared free-threaded safety, and CPython re-enables the lock when it
loads such a module. Importing the *engine* does not, because the engine imports
nothing beyond the standard library and itself. So the API process pays and the
engine does not, and `PYTHON_GIL=0` overrides the re-enable when you want the
whole suite to run with the lock genuinely off.

Nothing else is needed before the first run, and in particular no manual
database setup: `scripts/dev.sh` creates the `petacat` role and both databases
(`petacat` for development, `petacat_test` for the end-to-end tests) if they are
absent, and the backend creates its schema and loads `seed_data/*.json` into it
on startup. It also runs `npm install` for the client the first time, so the
first start takes noticeably longer than later ones.

### 3. Start the application

```bash
scripts/dev.sh
```

This makes sure Postgres is running, then starts the API and the Vite dev server
and holds the terminal until ctrl-c, which stops both. Postgres is a Homebrew
service and is deliberately left running.

- **Frontend (open this): http://localhost:59595**
- API: http://localhost:8100 — docs at http://localhost:8100/docs
- Postgres: localhost:5432, databases `petacat` and `petacat_test`

The two servers are separate: Vite serves the UI on 59595 and proxies `/api` and
`/ws` through to the backend, so 8100 answers API calls but returns 404 at `/`.
The client asks for relative paths (`/api/...`), so it is the proxy in
`client/vite.config.ts` — not any client code — that decides where the backend
is.

The halves can also be run one at a time, in separate terminals, which is easier
when you want to watch one of them closely:

```bash
scripts/dev.sh db       # ensure Postgres is up (creating role and DBs), then exit
scripts/dev.sh api      # API only, with --reload
scripts/dev.sh client   # Vite dev server only
scripts/dev.sh stop     # stop API and client; Postgres is left running
```

`PORT` (default 8100), `CLIENT_PORT` (default 59595) and `DATABASE_URL` override
the defaults, and the Vite proxy reads the same `PORT`, so moving the API moves
the proxy with it:

```bash
PORT=8123 CLIENT_PORT=59596 scripts/dev.sh
```

### 4. Run an analogy problem

Open http://localhost:59595 in your browser. The **Run Dashboard** is the default
view. The two left-hand panels split along *what* versus *how*:

**Problem Input** (top-left) defines the problem: the four strings (Initial,
Modified, Target, and optionally Answer — supplying an Answer switches the
engine into justification mode), the **Seed**, and the demo dropdown.

**Run Controls** (below it) decides how that problem executes, in six groups: Run, Recording, Engine parameters, What this run is, Manual stepping, and Settings.

**Run** picks between the two mutually exclusive execution strategies, and the
action button and pacing control follow the choice:

- **Run to answer — full speed.** The engine runs flat out on the backend until
  an answer is found. The Workspace header shows a `PROCESSING` spinner and a
  **STOP** button. The **Sampling interval** controls how often the UI reads the
  running engine (0 = continuous, ~100 ms); it does not change how the engine
  runs.
- **Live updates — codelet by codelet.** The client drives one codelet at a
  time, refreshing every panel after each. **Delay per codelet** inserts a pause
  after each one — raise it to follow the run by eye. Much slower, but every
  structure-build is visible as it happens.

**Recording** picks the run's **persistence mode** — Normal, Audit or Fast — and
that is a different question entirely: the execution strategy is about how this
browser watches a run, and the persistence mode is about whether the run is
written down at all. See
[Persistence modes](#persistence-modes-and-training-sessions). It is fixed when
the run is created, so changing it starts a new run.

**Manual stepping** (Step N) is independent of both: it advances a fixed number
of codelets and stops.

**Settings** holds a breakpoint control for fine-grained debugging, the Eliza
commentary toggle, and a **Spreading threshold** slider — leave that at its
default of 100 for faithful Metacat behaviour, see
[Spreading Activation Threshold](#spreading-activation-threshold).

Every panel has a **`?`** button in its header that opens a context-sensitive
help popover; the same content is also available statically in
[`HELP.md`](HELP.md).

### Running the same problem again, vs. running a different one

These are two different intentions, and two separate controls:

- **A different problem.** Edit any field or pick another demo, then press Run.
  That starts a *new* run, leaving the previous one in the run history. The line
  under the Run button names the run currently on screen and warns you when your
  inputs have drifted away from it.
- **The same problem again.** **Reset to codelet 0**, at the bottom of the
  Problem Input panel, clears the current run's workspace back to bare strings
  while keeping the same problem and seed. It does not start running — press Run
  afterwards.

### 5. Explore and edit configuration

Open the **Configuration** view via the hamburger menu (top-left) or navigate
to `#/config`. This view provides editable tables for all domain knowledge that
drives the engine:

- **Slipnet Nodes** -- 59 concept nodes with conceptual depths
- **Slipnet Links** -- 202 links between nodes (category, instance, property, lateral, sliplink)
- **Slipnet Layout** -- Grid positions for the graph visualization
- **Codelet Types** -- 27 codelet types with Python `execute_body` source
- **Engine Params** -- Runtime thresholds and parameters
- **Urgency Levels** -- 7 codelet urgency bin values
- **Formula Coefficients** -- 79 formula weights and constants
- **Demo Problems** -- 34 pre-configured analogy problems
- **Theme Dimensions** -- 9 conceptual dimensions for theme clusters
- **Posting Rules** -- Codelet posting patterns
- **Commentary Templates** -- Natural-language output templates
- **Enums** -- The enum tables (bond categories, proposal levels, and the rest)
- **Help Topics** -- The in-app help text, editable in place and backed by
  `seed_data/help_topics.en.json`

All tables support inline editing (double-click a cell to edit). Changes are
saved to the database immediately and apply to the next run created; a run keeps
the configuration it started with for its whole life. Use the **Export** /
**Import** buttons to move the full configuration as a JSON file, and **Export
Current Settings to Seed Data** to write it back to `seed_data/*.json`.

You can also navigate directly to a node's configuration by double-clicking it
in the Slipnet graph (to open the node focus view) and clicking **Edit** when
no run is active.

### 6. Run the tests

Petacat has two test suites:

- **Backend** (`tests/`) — Python / pytest. Covers the engine, the API, the
  help-topic system, and database persistence. Organised into six layers:
  `unit` (one class or function against fakes), `seed_unit` (one class or
  function against the shipped `seed_data/`), `module` (component assembly with
  codelets running), `architecture` (properties of the source tree),
  `integration` (the repository's artifacts agreeing), and `e2e` (full HTTP
  stack against a running database). All six run in a single command against
  the local Postgres — 2,222 cases, which includes the numeric matrix's second
  pass over the 250 backend-sensitive tests. See
  [TESTING.md](TESTING.md) for the layer breakdown, the numeric backend matrix,
  the session ceiling, the unit-test rules, determinism requirements, test-double
  conventions, how to run the suite under the free-threaded interpreter, and what
  to check first if the free-running tests fail.
- **Frontend** (`client/src/**/*.test.tsx`) — React components with
  [Vitest](https://vitest.dev/) and
  [React Testing Library](https://testing-library.com/docs/react-testing-library/intro/).
  Renders components in a jsdom environment, drives the Zustand store
  directly via `useRunStore.setState(...)`, and asserts on the rendered
  DOM. Used to lock in UI regressions that TypeScript can't catch on its
  own (e.g. state-dependent button visibility).

```bash
# ---- Backend (Python / pytest) ----

# THE REQUIRED COMMAND. Every layer including e2e, every backend-sensitive test on
# both the CPU and the GPU, stopping at a 60-minute ceiling.
# Needs Postgres up: scripts/dev.sh db
.venv/bin/python -m pytest tests/ -q

# Fast inner loop: one CPU backend, without the slow expected-range oracle
.venv/bin/python -m pytest tests/ -q -m "not slow" --numeric-backends=cpu

# One layer at a time: unit, seed_unit, module, architecture, integration, e2e
.venv/bin/python -m pytest tests/unit/ -v

# One backend alone: cpu, gpu, python, numpy, mlx, mlx-cpu, or all
.venv/bin/python -m pytest tests/ -q --numeric-backends=gpu

# A different wall-clock ceiling, in minutes (0 runs to the end)
.venv/bin/python -m pytest tests/ -q --test-ceiling=120

# Under the free-threaded interpreter, with the GIL genuinely off
PYTHON_GIL=0 .venv-ft/bin/python -m pytest tests/ -q

# ---- Frontend (Vitest) ----

# Run all frontend tests once (for CI / pre-commit)
cd client && npm run test:run

# Interactive watch mode while developing a new component or test
cd client && npm test
```

`.venv/bin/python -m pytest tests/ -q` is the command a change is verified with,
and it carries two things a reader can check in its output.

**The numeric backend matrix.** Petacat's arithmetic runs on the Metal GPU by
default and in float64 on the CPU when asked, and every test whose outcome that
arithmetic produces runs once on each. The two halves answer different questions.
The CPU half is float64, agrees with the pure-Python reference exactly, and holds
a seeded run to the same values and the same number of random draws. The GPU half
is float32, because Apple's GPUs have no double-precision units: a decayed
activation that float64 keeps flushes to zero in float32, which changes how many
draws the run consumes and sends every later probabilistic decision elsewhere. So
a given seed reaches a different answer on the GPU, which is a correct run —
Petacat is stochastic, and a different-but-valid run is a right answer. What holds
across both is the **set** of stopping states each problem can reach, which is what
`scripts/compare_to_metacat.py` compares against Metacat's own oracle. Every session ends with a
`petacat test matrix` block naming the backends that were exercised, their
precision and how many tests took each, so "both were run" is something the output
states rather than something to remember.

**A 60-minute ceiling.** The run stops at the first test boundary past the
deadline, keeping every result collected up to that point, and reports itself as
`RUN TRUNCATED` with the layers marked `INCOMPLETE` and an exit status of 2. A
clean run says `run complete` instead. `--test-ceiling=MINUTES` sets the ceiling
from the machine, and `0` runs to the end.

[TESTING.md](TESTING.md) documents the matrix, where its line is drawn, and how to
run one backend alone.

The e2e layer talks to `petacat_test`, a database separate from the development
one on the same instance, so a test run cannot disturb the runs and episodic
memory accumulated in `petacat`. `TEST_DATABASE_URL` overrides which database it
uses.

Frontend test files live next to the component they cover, named
`ComponentName.test.tsx`. The configuration is in `client/vitest.config.ts`
(which extends `client/vite.config.ts` so the `@/` alias and React plugin
are shared with the production build), and global test setup lives in
`client/src/test/setup.ts`.

## Persistence modes and Training Sessions

A **Run** is one letter-analogy problem plus Petacat's response. A **Training
Session** is a sequence of Runs that share one Episodic Memory — and Episodic
Memory is the *only* thing that crosses a Run boundary. Everything else (the
Slipnet, the Themespace, the Workspace, the Coderack, the Trace, the
temperature, the random stream) is rebuilt for each Run, exactly as in the
original Metacat.

Sessions are not something you create. One opens by itself when a Run needs it,
and every Run afterwards joins it. Clearing episodic memory from the Admin view
is what a session boundary means — after a clear, no Run inherits anything from
the Runs before it.

### The three modes

Persistence mode is a property **of a Run**, chosen when the Run is created and
fixed for its life. It says what gets written down; it does not say anything
about what the engine computes.

| | **Fast** | **Normal** (default) | **Audit** |
|---|---|---|---|
| What is persisted | nothing, ever | the complete state at Run start and at Run end | every state-changing action, as a forward log |
| When | never | twice, at the two Run boundaries | buffered in memory, flushed once at Run end |
| Database | never touched, not even to create the Run | yes | yes |
| May ever run codelets in parallel | yes | yes | no — serial, permanently |
| Appears in Run History / Review | no — there is no row | yes | yes |

A run's worker count decides which loop it takes. `workers` defaults to 1, the
serial loop, which stays the reference every parallel result is measured
against. Above 1 the run executes free-running. Audit holds `workers` at 1: its
record is a forward log of actions, and reconstructing from it needs the order
those actions committed in.

Measured end to end on `abc → abd; mrrjjj → ?` at seed 42, on an Apple M2 Max,
fastest of five runs per cell, all six producing the same 2,255 codelets and the
same answer `mrrjjk`:

| | Fast | Normal | Audit |
|---|---|---|---|
| Wall time, default backend (`mlx`, Metal GPU) | 1,308 ms | 1,348 ms (1.03×) | 1,481 ms (1.13×) |
| Wall time, `PETACAT_NUMERIC_BACKEND=off` | 192 ms | 227 ms (1.18×) | 329 ms (1.72×) |
| Bytes written | 0 | 155 KB | 413 KB |

Each row names the backend it was taken under, because the numeric substrate sets
the size of the run the recording is added to. Recording costs a fixed number of
milliseconds either way: Normal adds 35 ms with the substrate off and 40 ms on the
GPU, and Audit adds 137 ms and 173 ms. Bytes are the summed `octet_length` of the
JSON payloads the run leaves in Postgres, and do not depend on the backend.

`PETACAT_NUMERIC_BACKEND=off` is the quickest way to work: it takes a single run to
about 190 ms.

Three things worth drawing out.

**Cognition is identical across the modes.** That is the rule the design rests
on, and it is tested rather than assumed: the engine never learns which mode is
in force. There is no `if mode == "fast"` anywhere under `server/engine/`. A
`RunSink` port (`server/engine/sink.py`) receives the same events in the same
order in every mode, and the mode is entirely a question of which
implementation (`server/services/sinks.py`) is attached.

**Fast means *nothing written*.** A Fast Run completes with Postgres stopped. It
takes its identifier as a negative number from an in-process counter. The fast
sink is a no-op, and its `__slots__` is empty.

**Mode chooses where a run is recorded.** All three modes share the Training
Session's Episodic Memory and write real commentary. A Fast Run's answers are
available to the runs that follow, it is reminded of theirs, and
`answer_present` stops a later run rediscovering one of them.

**Audit is the serial reference.** It is slower on purpose and it stays serial
permanently: a fully-recorded one-codelet-at-a-time execution is what everything
parallel is validated against.

Choose the mode when you create the run:

```bash
curl -sX POST localhost:8100/api/runs \
  -H 'content-type: application/json' \
  -d '{"initial":"abc","modified":"abd","target":"xyz","seed":42,"mode":"fast"}'
```

An unknown mode name is rejected with a 400 rather than defaulted, because
silently giving somebody a Fast Run when they asked for an audited one loses the
record they asked for.

### Reviewing a recorded run

Normal and Audit exist in order to be looked at, so the reading surfaces ship
with the writers. Open the **Review** view from the hamburger menu (or
`#/review`).

- **Session browser** — Training Sessions newest first, each expanding to its
  sequence of Runs with each Run's mode. Fast Runs are absent, and the panel
  says so rather than leaving you to wonder.
- **A Normal Run** shows its start state, its end state, and a comparison of the
  two: codelets, temperature delta, structures built by string and bridge kind,
  the rules the run ended holding with their English, the largest Slipnet
  activation changes, which themes moved and which were dominant at the end, and
  what the Run added to the session's Episodic Memory. The two captures are
  ~110 KB each and nearly identical, so the comparison — about 7 KB — is the
  useful artefact, not the blobs.
- **An Audit Run** gets a tick inspector: step forward through the Run and see,
  at each tick, the codelet that ran, the structures that changed, and the
  activation and temperature at that instant. **Forward only** in this release.
  The inspector works by restoring the Run-start capture and walking a real
  engine forward, which is only legitimate if the reconstruction really is the
  recorded run — so it is checked against the recorded action log.

The review surfaces render through the same `WorkspaceView`, `SlipnetView`,
`ThemespaceView` and `TraceView` components as the live dashboard, pointed at
recorded state instead of a running engine.

### Reproducibility is by re-execution, not replay

A Normal Run records the *complete* state at both boundaries, and the reason is
the Training Session invariant: a Run inherits the Episodic Memory of everything
before it, and declines an answer that memory already holds for the same problem
and the same rules. `(complete starting state, problem, seed)` determines a Run's
behaviour. Reload the recorded start state, re-run, and the recorded end state
follows. Two further hashes are recorded with each Run — a **config hash** over
the metadata it executed under and a **memory hash** over the memory it
inherited — so which configuration and which memory a Run saw are part of its
identity.

The mid-run snapshot system this replaced wrote a ~43 KB blob every 15 codelets
and no code path could read any of it back: ten runs came to 230 MB of
unreadable JSONB. Normal writes 155 KB for the run measured above — 41× less,
and readable.

## The numeric substrate

`server/engine/numeric/` holds the parts of the engine that are *numbers over
arrays* rather than *decisions over structures*: Slipnet activation spreading,
decay and the probabilistic jump, object importance and salience, structure
strengths, themespace dynamics, and temperature. Four interchangeable backends
sit behind one protocol — a pure-Python reference, NumPy float64, MLX on the
GPU (float32, because Metal has no float64), and MLX on its CPU stream.

**The default is the GPU, at every Slipnet size.** That is a deliberate choice
and it costs throughput today: a Metal dispatch costs about 0.2 ms whether it
carries 200 edges or 340,000, and today's Slipnet has 59 nodes and 202 links, so
the engine runs **7.1× slower** with the substrate on the GPU than with it off.
Measured on `abc → abd; mrrjjj?` at seed 42 on an Apple M2 Max, engine only with
no database attached, fastest of seven runs: 1.275 s on `mlx` against 0.180 s at
`PETACAT_NUMERIC_BACKEND=off`, or 1,769 against 12,565 codelets per second. The
same run takes 0.217 s on `numpy` — so the GPU is **5.9× slower than the NumPy
path**, which is the comparison the test matrix's two halves make — and 0.459 s
on `mlx-cpu`. All four reach `mrrjjk` in 2,255 codelets. The measured
crossover where the GPU starts to win is around 10⁴ nodes, and the
long-term target is a Slipnet of roughly 300,000 — LLM-vocabulary scale — at
which sparse activation spreading is the dominant numeric cost. Running the GPU
path now means it is exercised, measured and correct before the Slipnet grows
into it, rather than being a code path nothing has executed.

Kernel timings, milliseconds per update cycle, on an M2 Max, fastest of 25:

| nodes | edges | python | numpy | mlx (GPU) | mlx-cpu |
|---|---|---|---|---|---|
| 59 | 202 | 0.011 | 0.007 | 0.187 | 0.050 |
| 10³ | 3,424 | 0.245 | 0.029 | 0.178 | 0.131 |
| 10⁴ | 34,237 | 2.76 | 0.245 | 0.298 | 1.13 |
| 10⁵ | 342,373 | 43.10 | 2.54 | 0.324 | 9.70 |

The GPU column is nearly flat from 59 to 100,000 nodes, which says the kernel is
still dispatch-bound at 342,000 edges and has not begun to do measurable work.

Two environment variables control it, and both exist because measuring the
alternatives is the only way the policy above can be defended:

| Variable | Effect |
|---|---|
| `PETACAT_NUMERIC_BACKEND` | `auto` (default), `python`, `numpy`, `mlx`, `mlx-cpu`, or `off`. Anything but `auto`/`off` forces that backend regardless of size; `off` disables the substrate entirely and the engine runs its own loops. |
| `PETACAT_NUMERIC_MIN_NODES` | Slipnet size at which `auto` reaches for the GPU. Set it to profile the CPU path at a chosen size. |
| `PETACAT_NUMERIC_MIN_GPU_NODES` | The Slipnet size at or above which `auto` prefers the GPU. Zero by default. Set it to ~10000 to reinstate size-gated selection when what you actually want is to profile the CPU path. |

The three float64 backends are bit-identical to the reference — same answer,
same codelet count, same number of random draws. The GPU is float32 and
genuinely flips some jump draws, so its runs diverge and land on different
answers; the *set* of answers reachable is unchanged, which is the standard
every change in this layer is held to.

## Free-running: codelets across CPU cores

`server/engine/free_running.py` executes codelets on several worker threads with
no global barrier. It wraps a prepared runner, which keeps the serial reference
exactly the shape it has.

Reach it by setting `workers` above 1 — on `POST /api/runs`, or in the
**Workers** box in the Run Controls panel, which accepts 1 up to the machine's
performance core count and is fixed at 1 for an Audit run. `workers: 0` on the
API asks for that count without first having to look it up. The benchmarks
(`scripts/bench_free_running.py`) and the tests
(`tests/module/test_free_running.py`) drive it directly.

Three things had to exist first, and each is useful on its own:

- **Counter-based random streams** (`splittable_rng.py`). A Mersenne Twister has
  19,937 bits of state that every draw advances, so concurrent codelets either
  serialise behind a lock or corrupt it. A counter-based generator *computes*
  the n-th value of a stream from `(seed, stream, counter)`, which makes streams
  independent without coordination and addressable without having drawn the ones
  before them.
- **Read and write sets** (`access.py`). Each codelet records what it read, and
  the version each thing carried when it read it; at its commit point a read-set
  whose versions have all held is a codelet that decided on a Workspace that has
  not moved. Validation is optimistic rather than lock-based, which suits this
  engine unusually well because a lost race is not a retry — it is a **fizzle**,
  an outcome the architecture already has and the temperature already accounts
  for.
- **A sharded coderack** (`coderack_shards.py`). Per-worker racks with work
  stealing, chosen by measurement over the two alternatives. Sharding by codelet
  family distorts selection badly at low temperature — up to 0.354 total-variation
  distance from the unsharded rack, precisely where selection is supposed to
  become greedy — because families are not evenly spread across urgency bins.
  Per-worker sharding stays within 0.006–0.016 at every temperature, because a
  codelet's shard is independent of both its type and its urgency.

Measured throughput against the serial loop, free-threaded, best of three:
1.33× at 8 workers on `mrrjjj`, 1.35× at 4 on `iijjkk`. Against a ceiling of
1.67× for parallelising codelet execution alone, less the ~9% the free-threaded
interpreter costs single-threaded, the realistic maximum is about 1.52× — so
1.35× is roughly 89% of what parallelising codelets *can* give. The remainder is
serial by nature: coderack maintenance and the numeric substrate.

Worker count follows the machine, and the shard count follows the Coderack:
`max_coderack_size // MIN_SHARD_CAPACITY` is 4 at the default rack of 100, so a
machine offering more workers than that runs several against one shard.
`PHASE 1 PLAN.md` carries what a larger rack would take and where parallelism
past this bound may come from.

Two things are deliberately still serialised. The update cycle is not stopped
for — whichever worker crosses the boundary runs it while the others carry on,
which is exactly the staleness the design budgets for. Committing a structure
*is* serialised, because `build_structure`'s duplicate check and its fights are
read-modify-write sequences over shared lists, and running two at once corrupts
the lists rather than producing a conflict the model could read as a fizzle.

**How much staleness cognition tolerates was measured before any of this was
written**, by making the serial loop read state as it stood N codelets ago:
nothing moves at N ≤ 5; by N = 15 runs start failing to converge inside the
codelet cap; by N = 50 a genuinely new answer appears. Five codelets is
therefore the budget, and no frequently-reached answer was lost at any delay.

## Sizing to the machine

`server/engine/hardware.py` is the one place that answers *what is this machine*,
and every count that depends on the answer is computed there. It reads `sysctl`
for the logical core count and the performance/efficiency split, and
`system_profiler SPDisplaysDataType` for the GPU core count. Every probe returns
a value or nothing; a machine that answers none of them still gets a description
and a full set of sizes.

| Size | Rule | Environment variable |
|---|---|---|
| Free-running workers | One per performance core. Codelet bodies are interpreted Python and CPU-bound, and a worker holds the commit lock while it mutates the Workspace. | `PETACAT_WORKERS` |
| Coderack shards | One per worker, floor of two, bounded further by the capacity a shard needs to hold a jootsing sequence (`MIN_SHARD_CAPACITY`). | `PETACAT_CODERACK_SHARDS` |
| Population processes | Every logical core but one. The runs share nothing, so efficiency cores add throughput, and the reserved core leaves the parent and the OS somewhere to run. | `PETACAT_POPULATION_WORKERS` |
| GPU dispatch threads | GPU cores × 1,024, rounded up to a power of two. This is the target the Slipnet kernel splits rows against, so a larger GPU splits more widely in the latency-bound regime. | `PETACAT_GPU_CORES`, `PETACAT_GPU_THREADS_PER_CORE` |

`GET /api/system/numeric` reports the detected machine and everything derived
from it alongside the chosen backend, and `scripts/bench_*.py` write the same
description into their JSON records — so a timing, a worker count or a crossover
recorded on one machine is legible on another.

The crossovers themselves are measurements rather than derivations: a crossover
sits where the CPU's time on the work first exceeds the fixed cost of the
alternative, so it moves with CPU speed and memory bandwidth.
`scripts/bench_numeric.py` measures them on the machine in hand;
`PETACAT_NUMERIC_MIN_NODES`, `PETACAT_NUMERIC_MIN_GPU_NODES` and
`PETACAT_BATCHING_MIN_NODES` set the results. `PETACAT_NUMERIC_MIN_GPU_NODES`
stays at 0 by default: the numeric substrate runs on the GPU at every Slipnet
size, which is a goal of the phase rather than a performance choice.

## API

[API.md](API.md) lists every route the server serves, grouped by area. It is
generated from the application itself by `scripts/generate_api_docs.py`, so it
lists exactly what is registered; `--check` reports when it is behind. Full
interactive OpenAPI docs are at `/docs` while the server is running.

The tables below cover the routes a user drives.

### Run lifecycle

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/runs` | Create a new run — takes `mode` (`fast`/`normal`/`audit`), `workers` (1–16; above 1 runs free-running), `spreading_threshold`, and `parameters` for per-run overrides |
| GET | `/api/runs/{id}` | Get run info |
| POST | `/api/runs/{id}/step` | Step N codelets |
| POST | `/api/runs/{id}/run` | Run to completion |
| POST | `/api/runs/{id}/stop` | Stop a running run |
| POST | `/api/runs/{id}/reset` | Reset to initial state (the mode survives a reset) |

### State queries

| Method | Endpoint | Returns |
|--------|----------|---------|
| GET | `/api/runs/{id}/workspace` | Strings, bonds, groups, bridges |
| GET | `/api/runs/{id}/slipnet` | Node activations |
| GET | `/api/runs/{id}/coderack` | Codelet pool |
| GET | `/api/runs/{id}/themespace` | Theme clusters |
| GET | `/api/runs/{id}/temperature` | Temperature value |
| GET | `/api/runs/{id}/trace` | Event log |
| GET | `/api/runs/{id}/commentary` | Natural-language summary |
| GET | `/api/runs/{id}/identity` | Mode, seed, spreading threshold, config hash, memory hash, session |
| GET | `/api/runs/parameters/catalogue` | The 25 settable run parameters: kind, bounds, default, what each does |
| GET | `/api/runs/{id}/parameters` | What a Run was: `fixed` (all 25, resolved), `overridden`, `defaults`, `derived` |
| GET | `/api/runs/{id}/telemetry` | Free-running telemetry: worker split, conflict rate, throughput |
| GET | `/api/review/runs/{id}` | One Run's review projection, for linking straight to it |
| PUT | `/api/review/sessions/{id}/note` | Set a Training Session's note |
| GET | `/api/system/numeric` | Which numeric backend the server process is running, and on what device |

### Interactive controls

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/runs/{id}/breakpoint` | Set breakpoint at codelet count |
| POST | `/api/runs/{id}/clamp-temperature` | Clamp temperature |
| POST | `/api/runs/{id}/clamp-node` | Clamp slipnet node |
| POST | `/api/runs/{id}/clamp-themes` | Clamp themes |
| POST | `/api/runs/{id}/clamp-codelets` | Clamp codelet urgency |
| POST/GET | `/api/runs/{id}/spreading-threshold` | Set/get spreading activation threshold |

### Review (recorded runs)

These read rows that outlive the process that wrote them, so a 404 here means
"nothing was recorded", not "no engine with that id is loaded" — which is why
they live in their own router rather than in `runs.py`.

| Method | Endpoint | Returns |
|--------|----------|---------|
| GET | `/api/review/sessions` | Training Sessions, newest first, with Run counts |
| GET | `/api/review/sessions/{id}` | The sequence of Runs in one session |
| GET | `/api/review/runs/{id}/captures` | Which boundary captures a Run has |
| GET | `/api/review/runs/{id}/captures/{boundary}` | One capture, projected into the shapes the live views read |
| GET | `/api/review/runs/{id}/captures/{boundary}/raw` | The same capture as the raw state graph |
| GET | `/api/review/runs/{id}/comparison` | Start vs. end summary for a Normal Run |
| GET | `/api/review/runs/{id}/actions` | The Audit forward log |
| GET | `/api/review/runs/{id}/actions/summary` | Action counts by kind |
| POST/GET/DELETE | `/api/review/runs/{id}/inspector` | Open, read, close the Audit tick inspector |
| POST | `/api/review/runs/{id}/inspector/advance` | Step the inspector forward |

## Run parameters

Twenty-five entries in `seed_data/engine_params.json` are read by the engine *while it
thinks* — thresholds, periods, capacities, the update cadence. Each can be set per Run,
is stored with the Run, and is shown read-back in the interface.

```bash
curl -X POST localhost:8100/api/runs -H 'Content-Type: application/json' -d '{
  "initial": "abc", "modified": "abd", "target": "mrrjjj", "seed": 42,
  "mode": "normal", "workers": 4,
  "parameters": {"update_cycle_length": 5, "initial_temperature": 80}
}'
```

Omitted parameters keep the global default. An unknown name, an out-of-range value or a
wrongly-typed one is a **400**, checked before anything is created — ignoring a typo
would produce a Run at the default whose record claimed the override was applied.

**The other 18 entries are deliberately not offered.** Display timings
(`initial_speed`, `text_scroll_pause`, the flash settings), Scheme-era implementation
details (`garbage_collect_cycles`, `step_cycles`), and several the port reads nowhere at
all (`expiration_period`, `max_theme_activation`, `workspace_activation`). Membership is
decided by what the engine actually reads — verified against every `get_param` call site
in `server/engine/**` *and* in the codelet bodies in `seed_data/codelet_types.json`, and
pinned by a test. A control that changes nothing is worse than no control.

Formula coefficients and urgency levels stay global and Admin-editable: they are the
model's constants rather than a Run's settings. The config hash covers them, so a Run
that executed under changed coefficients is still distinguishable in the record.

**Fixed and derived are kept apart.** Fixed parameters are inputs, constant for the Run.
*Derived* values — which numeric backend actually ran, the shard count sharding settled
on, the config and memory hashes, the free-running telemetry — are equally part of what a
Run was, and are shown beside them read-only. Presenting a derived value as settable
would misrepresent how the engine works.

**The resolved set is stored, not the overrides.** `runs.parameters` holds all 25 values,
because storing overrides alone would mean reading them against whatever the defaults are
at the time of reading — so a Run's record would quietly change meaning whenever the
configuration did.

`initially_clamped_slipnodes`, `top_down_slipnodes` and `intrinsic_link_lengths` are
accepted by the API but shown read-only in the interface: validating a Slipnet node name
needs the node vocabulary, and a wrong one is not a typo a run recovers from. Change
them globally in Configuration → Engine Params.

## Spreading Activation Threshold

A Petacat-only control, exposed as the **Spreading threshold** slider in the
Run Controls panel and as `POST /api/runs/{id}/spreading-threshold`.

It is a fundamental parameter — it changes what a run does — so it is treated as
part of a run's identity rather than a transient preference:

- The **chosen** value is remembered across runs *and across page reloads*, and
  is sent with each new run so the engine is initialised with it. It survives
  Reset.
- The value each run **used** is stored on the run (`runs.spreading_threshold`)
  and reported by the API, so it outlives a restart and shows in the Run History
  **Spr** column. A run at anything other than 100 is not comparable with the
  dissertation's results, and the list says which is which.

`POST /api/runs/{id}/spreading-threshold` still changes it mid-run, and
`POST /api/runs` accepts `spreading_threshold` at creation.

**The default is 100, which reproduces the original Metacat exactly.** Leave it
there when comparing against the dissertation.

### What it controls

Each update cycle, the Slipnet decays every node, then lets some nodes spread
activation to their neighbours. The threshold is the minimum activation a node
needs to be one of the spreaders (`server/engine/slipnet.py`):

```python
for node in self.nodes.values():
    if node.activation >= threshold:
        node.spread_activation_to_neighbors(update_cycle_length)
```

The original hard-codes this: `update-slipnet-activations` spreads only from
nodes passing `fully-active?` (`slipnet.ss:392`, applied at `slipnet.ss:383`), and

```scheme
(define fully-active?
  (lambda (node)
    (= (tell node 'get-activation) %max-activation%)))   ; %max-activation% = 100
```

Activation is clamped to 100, so a threshold of 100 is exactly `fully-active?`.

### Not to be confused with the *other* activation cutoff

Metacat has two, and they do different jobs:

| Scheme | Value | Governs |
|--------|-------|---------|
| `%max-activation%` | 100 | `fully-active?` — **which nodes spread**. This is the slider. |
| `%full-activation-threshold%` | 50 | `above-threshold?` — which nodes count as "active" for top-down codelet posting, and which are eligible for the stochastic jump to full activation |

The 50 cutoff is a separate parameter (`full_activation_threshold` in
`engine_params.json`) and the slider does not touch it. Moving the slider
changes how far activation propagates, not which concepts exert top-down
pressure.

### What lowering it does

More nodes pass the gate. How much each one contributes is already scaled by
its own activation —

```
amount = (update_cycle_length / 15) × (degree_of_association / 100) × activation
```

— so a node sitting at 60 contributes 60% of what a fully-active node would,
rather than all-or-nothing. Nodes at zero never spread regardless.

The net effect of a lower threshold is a more diffuse, more exploratory
Slipnet: more concepts stay warm, more slippages become available, and runs
wander further from the obvious interpretation. This is a deliberate extension
beyond what Metacat could do, useful for experimenting with the architecture —
but it is *not* Metacat behaviour, so results obtained below 100 should not be
compared against the dissertation's.

## Seed Data

All domain knowledge lives in `seed_data/*.json`:

| File | Contents |
|------|----------|
| `slipnet_nodes.json` | 59 concept nodes with conceptual depths |
| `slipnet_links.json` | 202 links (category, instance, property, lateral, sliplink) |
| `codelet_types.json` | 27 codelet types with Python execute bodies |
| `engine_params.json` | Runtime parameters and thresholds |
| `urgency_levels.json` | 7 urgency bin values |
| `formula_coefficients.json` | 79 formula weights |
| `theme_dimensions.json` | 9 conceptual dimensions across 3 cluster types |
| `demo_problems.json` | 34 pre-configured analogy problems |
| `posting_rules.json` | Codelet posting rules |
| `commentary_templates.json` | Natural-language output templates |
| `enums.json` | Enum tables (bond categories, proposal levels, …) |
| `slipnet_layout.json` | Grid positions for the Slipnet visualisation |
| `help_topics.en.json` | Help popover text for every dashboard panel + glossary (English) |

## Help & Documentation

Every dashboard panel has a `?` button that opens a context-sensitive help
popover, and the Admin view shows detailed user- and technical-facing
descriptions for each destructive/utility operation. All of that text comes
from a single JSON source of truth (`seed_data/help_topics.en.json`), which
the backend syncs into the database on every startup and uses to regenerate
the static [`HELP.md`](HELP.md) reference and matching TypeScript constants.

- **Read help content**: [`HELP.md`](HELP.md) is a human-readable reference
  with every panel, admin action, and glossary term.
- **Edit help text**: edit `seed_data/help_topics.en.json` and run
  `python scripts/generate_help_docs.py`, which rewrites `HELP.md` and
  `client/src/constants/helpTopics.ts`. The Admin view's **Regenerate Help
  Documentation** button does the same from the running server, and `--check`
  reports when the derived files are behind.

## Key Differences from Scheme Original

1. **Database-driven configuration**: All constants, codelet definitions, and
   network topology are in Postgres (loaded from JSON seed files).
2. **Codelet DSL**: Codelet behaviour is Python source stored in the database,
   compiled once, and `exec()`'d in a sandboxed namespace.
3. **Web-based UI**: React frontend with real-time WebSocket state push.
4. **Configurable spreading threshold**: The minimum activation level for
   spreading can be tuned per-run; the original is fixed at full activation.
   Petacat defaults to 100, which is the original's behaviour — see
   [Spreading Activation Threshold](#spreading-activation-threshold).
5. **Recorded runs**: The original leaves nothing behind when it exits. Petacat
   records a Run's complete state at both of its boundaries and can re-execute
   it, or record every state-changing action and step forward through it — or,
   in Fast mode, record nothing at all. See
   [Persistence modes](#persistence-modes-and-training-sessions).
6. **The arithmetic runs on the GPU**: Activation spreading, structure
   strengths, object values, themespace dynamics and temperature are expressed
   as flat arrays and executed through Metal. See
   [The numeric substrate](#the-numeric-substrate).
7. **Codelets can run in parallel**: The original is a serial loop, and so is
   Petacat's reference mode. Petacat can also run codelets across CPU cores with
   no global barrier, resolving lost races as fizzles. See
   [Free-running](#free-running-codelets-across-cpu-cores).

None of 5–7 changes what Petacat perceives. The standard they are held to is
that the *set* of stopping states each problem can reach is unchanged — not that
a given seed produces the same answer, which is a thing that legitimately moves
whenever the order of random draws does.

Some additional minor differences include:

- Of course, the name "Petacat".
- Deterministic runs by setting a "seed".
- Double-click on a node in the Slipnet to see details about it.
- An admin page for database and help text management.

## Future Direction

Petacat is not an end state. It's a foundation for a longer-running set of
questions about whether perception, analogy-making, learning, and
self-awareness might really be one thing seen at different levels of
abstraction — the bet underneath Hofstadter's whole programme, spelled out
one step further. Four open threads worth pulling on are sketched in
[FUTURE_DIRECTION.md](FUTURE_DIRECTION.md): a self/other grounding at the
base of the slipnet, a generalised perceptual workspace that escapes the
26-letter box, evolutionary tuning of the system's own configuration, and
an interactive-curiosity mechanism in which understanding the teacher's
answer is itself an analogy problem solved by the same machinery.

That document is an invitation to a conversation, not a roadmap. If any of
it resonates — or breaks, or sparks a different direction — please reach
out.

## Community

**[Join our Discord](https://discord.gg/WwwBF9urx)** — questions about the
architecture, notes on runs you have made, and anything from
[FUTURE_DIRECTION.md](FUTURE_DIRECTION.md) you want to argue with.

## Author

Petacat is written and maintained by **Mishkin Berteig** — software developer
and longtime enthusiast of the Copycat/Metacat family of ideas. Mishkin is
responsible for the Python port, the database-driven architecture, the web
frontend, and the help system and tooling that surround the engine.

- LinkedIn: <https://www.linkedin.com/in/mishkinberteig>

Feedback, issues, and pull requests are welcome.

## Acknowledgements

Petacat stands on the shoulders of three decades of work in analogy-making
and cognitive architecture.

- **James B. Marshall** — creator of [Metacat][metacat], the self-watching
  cognitive architecture Petacat ports. Dr. Marshall's 1999 PhD dissertation
  at Indiana University introduced Themespace, Temporal Trace, jootsing, and
  the episodic memory model that makes Metacat genuinely self-monitoring.
  Every architectural idea in the engine traces back to his work, and large
  swaths of the Python code were written alongside his original Scheme source
  as a reference. Petacat exists by Dr. Marshall's express permission: he
  personally authorised the relicensing from GPL-2 to MIT — see
  [LICENSE.md](LICENSE.md) for details.

  > Marshall, J. B. (1999). *Metacat: A Self-Watching Cognitive Architecture
  > for Analogy-Making and High-Level Perception.* Doctoral dissertation,
  > Indiana University.

  **The name "Petacat" is also Dr. Marshall's.** This project was originally
  going to be called "pMetacat" (for the Python port), but in the same email
  thread where he authorised the MIT license, Dr. Marshall suggested a more
  Hofstadterian variant:

  > "My one suggestion (if I may be so presumptuous!) might be to consider a
  > slight variation on your 'pMetacat' project name, maybe a bit more in
  > keeping with the spirit of Hofstadterian wordplay: how about calling it
  > 'Petacat'? :)"
  > — Dr. James Marshall, April 2026

  The suggestion was adopted immediately and the project has carried the
  name ever since.

- **Melanie Mitchell** — creator of [Copycat][copycat], the Common Lisp
  predecessor that Metacat itself is built on. Copycat introduced the
  Workspace/Slipnet/Coderack trinity and the stochastic, temperature-regulated
  control loop that Petacat still runs today. Without Copycat there is no
  Metacat, and without Metacat there is no Petacat.

  > Mitchell, M. (1993). *Analogy-Making as Perception: A Computer Model.*
  > MIT Press.

- **Douglas Hofstadter** — whose decades of writing on fluid concepts,
  analogy, and creative thought (including *Gödel, Escher, Bach* and the
  essays collected in *Fluid Concepts and Creative Analogies*) are the
  intellectual foundation of the whole Copycat/Metacat family.

Petacat is not affiliated with, endorsed by, or representative of the
original authors' current research programs. Any bugs, misinterpretations, or
questionable design choices in this port are mine alone.

## License

Petacat is released under the [MIT License](LICENSE.md), **with express
written permission from Dr. James B. Marshall**, the author of the original
Metacat.

The original Metacat (Marshall, 1999) was distributed under the **GNU General
Public License version 2**. Petacat was written using both Dr. Marshall's
published PhD dissertation *and* the original Scheme source code as
references — it is a port, not a clean-room reimplementation. Because the
work is therefore a derivative of GPL-2 licensed code, permission from the
original author was required to release the port under a different license.

Dr. Marshall graciously authorised this in April 2026. Without that grant,
Petacat would necessarily have been released under GPL-2-or-later to match
the original. See [LICENSE.md](LICENSE.md) for the full license text and
attribution notes.
