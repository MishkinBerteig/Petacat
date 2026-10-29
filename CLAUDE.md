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
