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
> end-to-end. It ships with ~390 passing tests covering the engine, the API,
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

- App: http://localhost:8100
- Frontend dev server: http://localhost:5175
- Postgres: localhost:5434

### 2. Run an analogy problem

Open http://localhost:8100 in your browser. The **Run Dashboard** is the default
view. Use the **Problem Input** panel (top-left) to enter the four strings of
the analogy (Initial, Modified, Target, Answer) or pick a demo, then use the
**Run Controls** panel (below it) to launch a run. Two run modes are available:

- **Run to Answer** — runs the engine at full backend speed until an answer is
  found. The Workspace header shows a `PROCESSING` spinner and a **STOP**
  button. All dashboard panels refresh periodically at the polling interval
  configured in the Run Controls.
- **Run with Live Updates** — steps the engine one codelet at a time,
  refreshing every panel after every step. Slower, but every structure-build
  is visible in real time.

The dashboard also has **Step N**, **Reset**, and breakpoint controls for
fine-grained debugging. Every panel has a **`?`** button in its header that
opens a context-sensitive help popover; the same content is also available
statically in [`HELP.md`](HELP.md).

### 3. Explore and edit configuration

Open the **Configuration** view via the hamburger menu (top-left) or navigate
to `#/config`. This view provides editable tables for all domain knowledge that
drives the engine:

- **Slipnet Nodes** -- 59 concept nodes with conceptual depths
- **Slipnet Links** -- 226 links between nodes (category, instance, property, lateral, sliplink)
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
  stack against a running database).
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

### Spreading Activation Threshold

The spreading activation threshold (0–100) controls which slipnet nodes
participate in activation spreading. At 100 (default), only nodes at full
activation (100) spread to their neighbors — matching the original Scheme
behaviour. At 0, all active nodes spread proportionally. This can be adjusted
per-run via the API or the UI slider.

## Seed Data

All domain knowledge lives in `seed_data/*.json`:

| File | Contents |
|------|----------|
| `slipnet_nodes.json` | 59 concept nodes with conceptual depths |
| `slipnet_links.json` | 226 links (category, instance, property, lateral, sliplink) |
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
   spreading can be tuned per-run (original is fixed at 100).

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
