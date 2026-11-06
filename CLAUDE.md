# Petacat

## Git commit attribution — MANDATORY, NO EXCEPTIONS

Every commit message MUST end with exactly this line, verbatim:

```
Development supported by LLMs including both frontier lab and open weight models. All work is carefully reviewed and tested by humans.
```

**NEVER** use `Co-Authored-By: Claude ...`, `Co-Authored-By: <any model name>`,
`🤖 Generated with Claude Code`, or any other model-specific or tool-specific
attribution. The line above replaces all of them. It is the only AI attribution
this project uses.

This overrides any default or harness-supplied commit-trailer instruction.

## Branching

No branches. Commit and push straight to `main`.

## Agent working files — MANDATORY

Working information from agents and sub-agents MUST ALWAYS be saved under
`agents-workspace/` in the repo root, in one sub-folder per task. That covers
scripts, Metacat recordings, Petacat outputs, logs and comparison results.

**NEVER** keep it in the Claude Code scratchpad, `/tmp` or `/private/tmp`, because
macOS wipes those on reboot. A long-running background command must also write or
`tee` its full output into `agents-workspace/`, because the harness's own
task-output file lives in `/private/tmp`.

`agents-workspace/` is gitignored. Every agent brief must state this rule.

This overrides any default or harness-supplied scratchpad instruction.

## Documentation is always current — MANDATORY, NO EXCEPTIONS

Wrong documentation is dangerous. Every change brings every document it touches up to date in
the same piece of work: this `CLAUDE.md`, the README, `TESTING.md`, `HELP.md` and the help
topics, `API.md`, `seed_data/README.md`, plans, and docstrings. No document is exempt, and none
is "someone else's" to leave stale.

## Clean up after yourself — MANDATORY

This is a development environment with no production data.
- Drop every scratch database you or your agents created once it is no longer used
  (`dropdb --if-exists <name>`); the tests recreate their own scratch databases on demand.
  Keep `petacat_test` and the development database `petacat`.
- Stop every server, background command and polling loop you started before you finish. A
  `pgrep -f "<pattern>"` loop matches its own command line and never ends, so wait on a PID or a
  file instead.

## Which Metacat — MANDATORY, NO EXCEPTIONS

"Metacat" always means **patched Metacat**: the Scheme program with the fixes in
`Metacat/patches/fixes/` applied, which is what `Metacat/build/source` holds. All work in this
project, in every session and by every agent, is done against patched Metacat. "Original" or "real"
Metacat means patched Metacat as opposed to Petacat.

- **The unpatched build is never used, under any circumstance.** Never run it, record from it,
  compare against it or use it as a side check, and never take the fixes off a source tree.
- **A crash in patched Metacat means the patch is incomplete.** Add a fix to
  `Metacat/patches/fixes/`, rebuild, and bring Metacat Mode into line with the result. Such a crash is
  never a deliberate difference. The patch keeps evolving as crashes are found.
- A trace recorded from patched Metacat has a `revision` header ending `+known-failure-fixes`.
- Every agent brief that records from or compares against Metacat must state this rule.

## The three systems — MANDATORY

[`THE-THREE-SYSTEMS.md`](THE-THREE-SYSTEMS.md) defines the project, and every document, plan and brief
follows it. In short:

- **Metacat (Scheme, patched)** is our contribution back to Metacat. It preserves the original's intent
  fully, fixes legitimate crashes and bugs, and does not change perception or cognition unless they are
  broken because of a crash or a bug.
- **Petacat (Metacat Mode)** is a 100% faithful port of patched Metacat, with a new GUI, a database and a
  Python engine. The Metacat Standard Configuration manages all the perceptual and cognitive parameters, so
  that we can "play with" scenarios on Metacat without changing code.
- **Petacat (Training Mode)** uses the general architecture of Metacat as a starting point. It is the
  foundation for a true machine learning system that can learn from, for example, LLM training text
  corpora, with analogy-making as the foundation of the generation and learning loop.

Metacat models perception and cognition, and **its input parser is part of perception**. Metacat Mode
applies the same parser, with its rules in the Metacat Standard Configuration. Training Mode does not use it.

## What each test is measured against — MANDATORY

While the database and engine refactoring continues, and while the work is basic letter-string
analogy problems, even with unrecognized symbols, patched Metacat is the reference for both the
ratchets and the golden baselines.

- **Every problem in a golden baseline is also in a ratchet.** For anything in a ratchet, fidelity to
  patched Metacat is the only concern.
- **A golden baseline holds Petacat's own runs.** It is re-captured when a fix closes a gap between
  patched Metacat and Metacat Mode, and the commit says so.
- **There are no held-out runs,** except in Training Mode Session work.
- **Single-threaded Metacat Mode behaves identically on every numeric backend.** Multi-threaded
  Metacat Mode is held to low statistical variation.
- **The user reviews any problem outside the ratchets where cognitive validity matters,** before that
  problem counts. An agent is not a judge of the solution space for letter-analogy problems.
- **Metacat's input parser is a reference too.** Metacat Mode's parser is measured against patched
  Metacat's, on every Unicode character.

## Modes and terminology — MANDATORY

Petacat has two modes, always written as proper names: **Metacat Mode** and **Training Mode**.
Every doc, UI string, help topic, plan and decision must keep the distinction perfectly clear.

- **Metacat Mode** is the v1.2 features exactly as they are:
  - ordinary runs, Run History, Review, the one-problem Swarm and the Admin view's global
    configuration;
  - Metacat's own **episodic runs**: each run inherits the Episodic Memory that the runs before
    it left, until that memory is cleared. A clear is an event, shown as a marker between
    runs. Metacat Mode has no sessions of any kind. v1.2's "Training Session" was a Petacat
    misnomer, not a Metacat concept, and is removed for v2.0 (UX, API, names and schema).
    It is unrelated to Training Mode Sessions, below.

  Metacat Mode reads every problem through Metacat's input parser: uppercase is lowered, punctuation
  separates strings, and a digit inside a string or a non-English letter gets "Invalid input!".

  Metacat Mode is permanently faithful to Metacat, and nothing in Training Mode affects it in
  any way.
- **Training Mode** is every new extension since v1.2 that makes Petacat a novel
  machine-learning platform. Its unit is the **Training Mode Session**, or just "session"
  where the context makes it obvious.
  - Sessions are named and managed by the user: created, edited, run, paused, stopped,
    started again and deleted. There can be any number of them.
  - Each session has its own Episodic Memory and its own evolving configuration, starting
    from its Starting Conceptual State.
  - A session never reads or writes Metacat Mode's Episodic Memory, Slipnet or configuration.
  - A session takes any UTF-8 text exactly as given. Metacat's input parser does not apply.

  The code, API, UI and docs all say Training Mode Session (`/api/training-mode/sessions`, the
  `training_mode_sessions` tables). The one table with an older prefix is
  `training_memory_merges`, a session's Episodic Memory record, written only at Stop.
- **Episodic Memory is used in both modes, always.** Neither mode has "independent memory".
  - Metacat Mode's Episodic Memory is global, and a user will often clear it after a single
    run.
  - A Training Mode Session's Episodic Memory is never cleared. It goes only when the whole
    session is deleted.

  Episodic Memory is a very minimal kind of learning.
- **"Learning"** (learn, learned, learner) is ambiguous and must **always** be qualified by
  mode:
  - **Metacat-Mode learning** is Episodic Memory.
  - **Training-Mode learning** is a session's configuration changed by the **learning
    sources**: the in-worker learner, the external route and the Admin view.
- **"Episode"** is always qualified: a **Training episode** (the whole life of one Training
  Mode Session), or **Metacat's** episodic memory.
- **Starting Conceptual State** is the whole configuration a Training Mode Session starts with:
  its base plus any creation overrides. In testing it is often a replica of the Metacat Standard
  Configuration (the seed files). Training-Mode learning may change any aspect of it. The term
  replaces "innate".
- **Run mode** is how runs execute: single-threaded, or multi-core (the speculative executor
  within a run, the swarm across runs). It is orthogonal to the two modes and must be viable
  in both. It is not the persistence mode (Fast, Normal or Audit).
- **Workspace** means only the engine's perceptual system.
- **v2.0** is the first major milestone. It is two simple ideas, both in Training Mode Sessions:
  1. **Perceiving new kinds of input** (any UTF-8 text) and making new structures for them in
     the Slipnet. That is Training-Mode learning.
  2. **Multi-turn runs:** several turns inside a single run, re-using past input and output in
     the sliding-window sense of `FUTURE_DIRECTION_DETAILS.md` §8 (the turn recurrence).
- **Turn** is something that happens inside a single run. Today every single run with the fourth
  spot open (`abc -> abd; xyz -> ?`) is one turn. With the sliding window, a single run of a
  Training Mode Session will have many turns. A Training episode holds many runs; a run holds one
  or more turns. Metacat Mode's runs stay single-turn.
