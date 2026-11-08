# DISCREPANCIES5 — where Petacat's source and Metacat's source still say different things

> **Status (2026-11-08).** This file keeps only the differences between Petacat's source and patched
> Metacat's source that are still to be fixed: one in the stored form of an answer's unjustified themes, and
> two small ones in `Image.new_start_letter` and `translate_rule`. Each entry names the Petacat site, the
> Metacat site and what diverges, with the lines of today's code. Entry IDs are kept as they were. The
> differences the user accepted as deliberate are in [METACAT-MODE-DIFFERENCES.md](METACAT-MODE-DIFFERENCES.md),
> and the wrong citations of Metacat's source that were listed here are corrected. Both are in the git history
> of this file. Metacat's side is `Metacat/build/source`, the patched build. The current description of the
> system is in [README.md](README.md), [TESTING.md](TESTING.md) and [HELP.md](HELP.md).
> `tests/lockstep/README.md` describes the replay that found most of these.

**What this is.** A comparison of Petacat's Python against Metacat's Scheme, function by function, for
anything that could make the two compute differently. It is a *static* comparison. It is not a measurement.

## On "inert"

The `translate_rule` entry describes a divergence that appears to be unreachable: a branch whose guard seems
never to hold. **That observation is conditional, and it does not downgrade the entry.** Inertness cannot be
established here. Metacat is late-bound Scheme: `round`, `floor` and `ceiling` are *redefined* at
`utilities.ss:238-252` after being captured, generic arithmetic silently crosses between exact rationals and
flonums, and `tell`-based dispatch resolves at call time. Static analysis cannot see through that, and
statistical sampling can only ever fail to reach a branch. So the standard applied throughout is: **Petacat
should replicate what the Scheme does, and carry a comment saying the branch may be unreachable, rather than
replicate a simplification that assumes it is.**

---

# C. Ordering

## C-2. `remq-duplicates` keeps the last occurrence; one Petacat form cannot

**Metacat** — `utilities.ss:915-927` (`remove-duplicates-pred`, `remq-duplicates` at `:926`) drops `(1st l)`
when it recurs later, and `get-unjustified-theme-pattern` (`answers.ss:239`) compares whole
`(dimension relation)` entries, so it keeps **two** entries for one dimension with different relations.

**Petacat** — `_unjustified_themes` (`server/engine/answers.py:402-424`) builds a `dict` keyed on dimension, so it
keeps the first relation for a dimension and cannot hold two. The dict form is persisted as JSONB and read by
memory and the API, so changing the form is a schema change, not a local fix.

---

# D. Missing, extra, and duplicated logic

## D-11. Smaller items

| | Petacat | Metacat | Effect |
|---|---|---|---|
| `Image.new_start_letter` | `server/engine/images.py:420-425` keeps the old start letter when a non-letter image has no related node for the relation | `images.ss:280-282` assigns unconditionally, so it becomes `#f` | a stale start letter where the reference records "there isn't one"; assigning `None` would raise a non-`ImageFailure` downstream rather than snag, so it needs its own pass |
| `translate_rule` | `server/engine/codelet_dsl/builtins.py:3247-3248` returns `None` with no built vertical bridge | `answers.ss:1436-1448` translates each description unchanged | an added precondition; probably unreachable |

---

# Summary

| Section | Entries open |
|---|---|
| C. Ordering | C-2 |
| D. Missing, extra, duplicated | D-11 (two rows: `Image.new_start_letter`, `translate_rule`) |
