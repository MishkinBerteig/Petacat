# Governance notes

A record of events that affected the project's data or working practices, and of the decisions taken about them. Newest first.

## 2026-10-29: agents' working data lost in a reboot

### What happened

The maintainer's computer crashed and restarted while agents were working on the Metacat fidelity sweeps. All of the agents' working files were in Claude Code's session scratchpad, under `/private/tmp`. macOS empties that folder on restart, so everything there was deleted.

### What was lost

- **About 1,300 Metacat recordings** from the October 2026 sweeps. These were:
  - the snag-explanation sweep;
  - the fidelity agent's widened net, including its 24 episodes;
  - the 1,000-run Metacat study of `wxyz → vxyz; abcd → ?`.
- **The raw results of the matching Petacat studies.** These were the 1,000-run serial and free-running studies of the same problem.
- **The sweeps' logs and comparison results.**
- **The recorder and comparer scripts behind those sweeps.** None had been committed yet.

**Effect on `list-of-letter-string-analogy-problems.md`.** 110 of its 186 rows quote figures from runs that no longer exist. Those 110 rows cite 891 single Metacat runs, of which 9 survive. By group:

| Group | Rows affected | Cited runs lost |
|---|---:|---:|
| 3. Own exploration in the app | 1 (`abcd → dcba; xyz → ?`) | 5 |
| 4. Dissertation-cited, port parity | 4 | 34 |
| 5. Lockstep snag and desync corpora | 8 | 91 of 100 (9 are still in `tests/lockstep`) |
| 6. Snag-explanation sweep | 26 | 292 |
| 7. Fidelity widened net | 71 (all) | 469, plus the 24 episodes |

**Also lost:** the per-run data behind the 1,000-run study figures for `wxyz → vxyz; abcd → ?`, which are quoted in group 3 and in `README.md`.

The figures in the document are as they were recorded before the loss. They can no longer be checked against the runs they came from.

### What was not lost

Everything inside the repository folder survived, whether committed or not. That includes:

- the Metacat reference data for the 19 demo and copy problems (`academic/data/`);
- the 1,213 lockstep recordings under `tests/lockstep`, most of them uncommitted;
- the committed `*_metacat.tsv` fixtures.

The app database was unaffected.

### What was recovered or rebuilt

**Scripts.** The session transcripts survived because they live outside the temporary folders. 241 scripts were replayed from them into the maintainer's local working folder. These copies are not part of the repository.

**Comparison tools.** The recorders and comparers were rebuilt into the repository, with documentation and tests:

- `tests/lockstep/metacat/record_*.py` and `wrap.py`;
- `scripts/compare_*.py`, `sweep_snags.py` and `sweep_fidelity.py`.

They regenerate the committed fixtures byte for byte. Usage is in `tests/lockstep/README.md` and `tests/lockstep/metacat/README.md`.

**Recordings.** Metacat's recordings are byte-identical for a given problem, seed and codelet cap, so every lost Metacat run could be recorded again. There are two exceptions:

- The snag sweep's problem list could only be rebuilt from the transcripts as 87 problems. The original had about 100.
- The free-running Petacat study cannot be repeated exactly. Its runs depend on how the operating system schedules threads.

### Decision

**The lost data will not be re-recorded.** The maintainer decided this on 2026-10-29. The affected figures stay in the document as recorded, and this note marks them as no longer backed by their runs.

### Rule adopted

To stop a reboot from deleting work again:

- **Agents' working files** now go in `agents-workspace/<task>/` in the repository. That covers scripts, recordings, logs and comparison results. The folder is gitignored, and `CLAUDE.md` makes the rule mandatory for every agent and sub-agent, including what each brief tells them.
- **Long-running commands** must write or `tee` their full output there too.
- **Nothing in `agents-workspace/` is deleted** without the maintainer's explicit instruction.
- **On the maintainer's machine,** the same rule applies to every coding agent. Their temporary folders were moved out of the folders macOS empties on restart, and session transcripts are now kept for 180 days.
