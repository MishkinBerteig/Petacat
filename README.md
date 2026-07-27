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
> end-to-end. It ships with ~500 passing tests covering the engine, the API,
> and the help/config system. See [Acknowledgements & License](#acknowledgements)
> below for credits and licensing.

[metacat]: http://science.slc.edu/~jmarshall/metacat/
[marshall]: http://science.slc.edu/~jmarshall/
[copycat]: https://en.wikipedia.org/wiki/Copycat_(software)

## Architecture

- **Backend**: Python 3.12+ / FastAPI / SQLAlchemy / PostgreSQL
- **Frontend**: React / TypeScript / Vite
- **Deployment**: Docker Compose (dev and production)

Engine parameters, slipnet topology, codelet definitions, and theme dimensions
are stored in the database and loaded at startup. Codelet behaviour is expressed
as Python source strings in the `codelet_type_defs` table, compiled once at
startup, and executed via `exec()` in a sandboxed namespace.

### Core Components

| Component | Python module | Purpose |
|-----------|--------------|---------|
| Workspace | `server/engine/workspace.py` | 4 letter strings + perceptual structures |
| Slipnet | `server/engine/slipnet.py` | 59-node semantic network with activation spreading |
| Coderack | `server/engine/coderack.py` | Stochastic scheduler (7 urgency bins, 100 max codelets) |
| Themespace | `server/engine/themes.py` | Self-watching: theme clusters, activation dynamics |
| Temporal Trace | `server/engine/trace.py` | Chronological event log |
| Episodic Memory | `server/engine/memory.py` | Cross-run answer/snag storage |
| Temperature | `server/engine/temperature.py` | Global exploration/exploitation control (0–100) |
| Runner | `server/engine/runner.py` | Main control loop (`init_mcat`, `step_mcat`, `update_everything`) |

### Update Cycle Order

Every 15 codelets, `update_everything()` runs in this order (matching the
original Scheme `run.ss`):

1. Update workspace structure strengths
2. Update object importances, unhappiness, salience
3. Tick clamp expirations (slipnet + temperature)
4. Spread activation: workspace → themespace
5. Spread activation within themespace
6. Update slipnet: theme→slipnet, then internal decay/spread/jump
7. Update temperature
8. Post bottom-up codelets
9. Post top-down codelets

## Getting Started

### 1. Start the application

```bash
docker compose -f docker-compose.dev.yml up -d
```

- **Frontend (open this): http://localhost:59595**
- API: http://localhost:8100 — docs at http://localhost:8100/docs
- Postgres: localhost:5434

In the dev stack the two are separate: Vite serves the UI on 59595 and proxies
`/api` and `/ws` through to the backend, so 8100 answers API calls but has
nothing at `/`. The production image is the other way round — `npm run build`
output is baked into `/app/static` and FastAPI serves the UI and API together on
one port.

### 2. Run an analogy problem

Open http://localhost:59595 in your browser. The **Run Dashboard** is the default
view. The two left-hand panels split along *what* versus *how*:

**Problem Input** (top-left) defines the problem: the four strings (Initial,
Modified, Target, and optionally Answer — supplying an Answer switches the
engine into justification mode), the **Seed**, and the demo dropdown.

**Run Controls** (below it) decides how that problem executes. **How to run**
selects between the two mutually exclusive execution modes, and the action
button and pacing control follow the choice:

- **Run to answer — full speed.** The engine runs flat out on the backend until
  an answer is found. The Workspace header shows a `PROCESSING` spinner and a
  **STOP** button. The **Sampling interval** controls how often the UI reads the
  running engine (0 = continuous, ~100 ms); it does not change how the engine
  runs.
- **Live updates — codelet by codelet.** The client drives one codelet at a
  time, refreshing every panel after each. **Delay per codelet** inserts a pause
  after each one — raise it to follow the run by eye. Much slower, but every
  structure-build is visible as it happens.

**Manual stepping** (Step N) is independent of the mode: it advances a fixed
number of codelets and stops. There are also breakpoint controls for
fine-grained debugging, and a **Spreading threshold** slider — leave that at its
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

### 3. Explore and edit configuration

Open the **Configuration** view via the hamburger menu (top-left) or navigate
to `#/config`. This view provides editable tables for all domain knowledge that
drives the engine:

- **Slipnet Nodes** -- 59 concept nodes with conceptual depths
- **Slipnet Links** -- 202 links between nodes (category, instance, property, lateral, sliplink)
- **Slipnet Layout** -- Grid positions for the graph visualization
- **Codelet Types** -- 27 codelet types with Python `execute_body` source
- **Engine Params** -- Runtime thresholds and parameters
- **Urgency Levels** -- 7 codelet urgency bin values
- **Formula Coefficients** -- 50+ formula weights and constants
- **Demo Problems** -- Pre-configured analogy problems
- **Theme Dimensions** -- 9 conceptual dimensions for theme clusters
- **Posting Rules** -- Codelet posting patterns
- **Commentary Templates** -- Natural-language output templates

All tables support inline editing (double-click a cell to edit). Changes are
saved to the database immediately. Use the **Export** / **Import** buttons to
back up or restore the full configuration as a JSON file.

You can also navigate directly to a node's configuration by double-clicking it
in the Slipnet graph (to open the node focus view) and clicking **Edit** when
no run is active.

### 4. Run the tests

Petacat has two test suites:

- **Backend** (`tests/`) — Python / pytest. Covers the engine, the API, the
  help-topic system, and database persistence. Organised into four layers:
  `unit` (pure functions and data structures), `integration` (seed data and
  codelet compilation), `module` (component assembly), and `e2e` (full HTTP
  stack against a running database). See [TESTING.md](TESTING.md) for the
  unit-test rules, determinism requirements, and test-double conventions.
- **Frontend** (`client/src/**/*.test.tsx`) — React components with
  [Vitest](https://vitest.dev/) and
  [React Testing Library](https://testing-library.com/docs/react-testing-library/intro/).
  Renders components in a jsdom environment, drives the Zustand store
  directly via `useRunStore.setState(...)`, and asserts on the rendered
  DOM. Used to lock in UI regressions that TypeScript can't catch on its
  own (e.g. state-dependent button visibility).

```bash
# ---- Backend (Python / pytest) ----

# Unit, integration, and module tests (no Docker needed)
python3 -m pytest tests/unit/ tests/integration/ tests/module/ -v

# End-to-end tests (requires running Docker Compose)
docker compose -f docker-compose.dev.yml exec app pytest tests/e2e/ -v

# ---- Frontend (Vitest) ----

# Run all frontend tests once (for CI / pre-commit)
docker compose -f docker-compose.dev.yml exec frontend npm run test:run

# Or locally, from the host (after `cd client && npm install`):
cd client && npm run test:run

# Interactive watch mode while developing a new component or test
cd client && npm test
```

Frontend test files live next to the component they cover, named
`ComponentName.test.tsx`. The configuration is in `client/vitest.config.ts`
(which extends `client/vite.config.ts` so the `@/` alias and React plugin
are shared with the production build), and global test setup lives in
`client/src/test/setup.ts`.

## API

Full OpenAPI docs are available at `/docs` when the server is running.

### Run lifecycle

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/runs` | Create a new run |
| GET | `/api/runs/{id}` | Get run info |
| POST | `/api/runs/{id}/step` | Step N codelets |
| POST | `/api/runs/{id}/run` | Run to completion |
| POST | `/api/runs/{id}/stop` | Stop a running run |
| POST | `/api/runs/{id}/reset` | Reset to initial state |

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

### Interactive controls

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/runs/{id}/breakpoint` | Set breakpoint at codelet count |
| POST | `/api/runs/{id}/clamp-temperature` | Clamp temperature |
| POST | `/api/runs/{id}/clamp-node` | Clamp slipnet node |
| POST | `/api/runs/{id}/clamp-themes` | Clamp themes |
| POST | `/api/runs/{id}/clamp-codelets` | Clamp codelet urgency |
| POST/GET | `/api/runs/{id}/spreading-threshold` | Set/get spreading activation threshold |

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
nodes passing `fully-active?` (`slipnet.ss:381`), and

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
| `formula_coefficients.json` | 50+ formula weights |
| `theme_dimensions.json` | 9 conceptual dimensions for themes |
| `demo_problems.json` | 30+ pre-configured analogy problems |
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
- **Edit, translate, or contribute help text**: see
  [`LOCALIZATION.md`](LOCALIZATION.md) for the schema, the edit workflow
  (including the Admin view's **Regenerate Help Documentation** button),
  and instructions for adding a new language.

The first release ships English only; the plumbing is in place for
additional languages without schema changes.

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
