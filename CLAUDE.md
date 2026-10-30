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

## Modes and terminology — MANDATORY

Petacat has two modes, always written as proper names: **Metacat Mode** and **Training Mode**.
Every doc, UI string, help topic, plan and decision must keep the distinction perfectly clear.

- **Metacat Mode** is the v1.2 features exactly as they are:
  - ordinary runs, Run History, Review, the one-problem Swarm and the Admin view's global
    configuration;
  - Metacat's own **episodic runs**: each run inherits the Episodic Memory that the runs before
    it left, until that memory is cleared. A clear is an event, shown as a marker between
    runs. Metacat Mode has no "sessions" of any kind: v1.2's "Training Session" was a Petacat
    misnomer, not a Metacat concept, and is removed for v2.0 (UX, API, names and schema).

  Episodic Memory is a very minimal kind of learning. Metacat Mode is permanently faithful to
  Metacat, and nothing in Training Mode affects it in any way.
- **Training Mode** is every new extension since v1.2 that makes Petacat a novel
  machine-learning platform: Trainings, each with its own episode memory, the Training's own
  evolving Slipnet, and learners. A Training never reads or writes Metacat Mode's Episodic
  Memory, Slipnet or configuration.
- **"Learning"** (learn, learned, learner) is ambiguous and must **always** be qualified by
  mode: **Metacat-Mode learning** (Episodic Memory) or **Training-Mode learning**.
- **"Episode"** is always qualified: a **Training episode**, or **Metacat's** episodic memory.
- **Starting Conceptual State** is the whole configuration a Training starts with: its base plus any
  creation overrides. In testing it is often a replica of the Metacat Standard Configuration (the
  seed files). Training-Mode learning may change any aspect of it. The term replaces "innate".
- **Run mode** is how runs execute: single-threaded, or multi-core (the speculative executor
  within a run, the swarm across runs). It is orthogonal to the two modes and must be viable
  in both. It is not the persistence mode (Fast, Normal or Audit).
- **Workspace** means only the engine's perceptual system.
- **v2.0** is the first major milestone: recognizing new concepts and incorporating them into
  the Slipnet by modelling a learning feedback loop and perceptual processes. That is
  Training-Mode learning.
