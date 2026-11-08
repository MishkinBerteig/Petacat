# The three systems

This document defines what this project is made of and what each part is for. It records the
maintainer's decision of 2026-11-06, and it governs every other document, plan and agent brief in
this repository. Where another document disagrees with it, that document is wrong and must be
corrected.

There are three systems. Two of them run in the same program, and the third is a separate program.

## The principle

Metacat is meant to model *perception and cognition*. Everything it does from the moment text is
typed to the moment a run ends is part of that model. That includes its input parser, intentionally
or not: how Metacat reads what it is given is perception.

## 1. Metacat (Scheme, patched)

**Patched Metacat is our contribution back to Metacat.** It is the original Scheme program with the
fixes in `Metacat/patches/fixes/` applied, and it is what `Metacat/build/source` holds.

- It preserves the intent of the original fully.
- It fixes legitimate crashes and bugs.
- It does not change perception or cognition, unless they are broken because of a crash or a bug.

The original, unpatched build is the source of that intent. It is never run.

## 2. Petacat (Metacat Mode)

**Metacat Mode is a 100% faithful port of patched Metacat,** with a new GUI, a database and a Python
engine. The Metacat Standard Configuration manages all the perceptual and cognitive parameters, so
that we can "play with" scenarios on Metacat without changing code.

- Under the Metacat Standard Configuration, Metacat Mode perceives and reasons as patched Metacat does.
- Changing a value in the configuration is how a scenario is explored. Changing the program is not.
- Nothing in Training Mode affects Metacat Mode in any way.
- The few places where it differs on purpose (how many random numbers it draws where the result is certain,
  and display and narration) were accepted by the user and are listed in
  [`METACAT-MODE-DIFFERENCES.md`](METACAT-MODE-DIFFERENCES.md). None changes a decision or a probability.
  Any other difference is a defect to fix.

## 3. Petacat (Training Mode)

**Training Mode uses the general architecture of Metacat as a starting point.** It is the foundation
for building a true machine learning system that can learn from, for example, LLM training text
corpora. Its core idea is that analogy-making is the foundation of the *generation* and *learning
loop*.

Training Mode is expected to change results. It is not held to Metacat, and what holds Metacat Mode
to Metacat does not bind it.

## The three side by side

| | Metacat (Scheme, patched) | Petacat (Metacat Mode) | Petacat (Training Mode) |
|---|---|---|---|
| **What it is** | Our contribution back to Metacat | A 100% faithful port of patched Metacat | The foundation of a true machine learning system |
| **Measured against** | The intent of the original | Patched Metacat | Its own goals, not Metacat |
| **Perception and cognition** | Changed only where a crash or bug broke them | The same as patched Metacat under the Metacat Standard Configuration | Expected to change |
| **Where the parameters live** | The Scheme source | The Metacat Standard Configuration, in the database | Each Training Mode Session's own configuration |
| **How a scenario is explored** | Not applicable | By changing configuration, never code | By Training-Mode learning and session configuration |
| **Input** | Metacat's input parser | The same input parser | Any UTF-8 text, kept exactly as given |

## What follows for input

Because the parser is part of perception, it belongs to the first two systems and not to the third.

Metacat's parser reads a whole line, `abc abd xyz`, optionally followed by an answer and a seed. It
treats each kind of character like this:

| Input | What the parser does |
|---|---|
| A letter a to z | Reads it |
| An uppercase letter | Lowers it: `xyZ` is read as `xyz` |
| Punctuation, a space, emoji or a combining mark | Treats it as a separator between strings: `abc abd x-z` is read as `abc abd x z`, which is the problem `abc -> abd; x -> ?` with the answer `z` to justify |
| A digit inside a string | Answers "Invalid input!": `xy1` |
| Digits alone | A seed in the fourth or fifth place, and "Invalid input!" anywhere else |
| A non-English letter | Answers "Invalid input!": `é`, `日本` |

The last row is the one fix. The original passes such a letter to the engine, which crashes with
`variable plato-é is not bound`. A crash is a legitimate bug, so patched Metacat answers
"Invalid input!", which is what the parser already says for other input it cannot read. The other
rows are Metacat's own behaviour, and the patch leaves them alone.

- **Patched Metacat** has that parser, with that one fix.
- **Metacat Mode** applies the same parser to every problem it is given, with its rules held in the
  Metacat Standard Configuration.
- **Training Mode** does not use it. A Training Mode Session takes any UTF-8 text exactly as given,
  because perceiving new kinds of input is what Training Mode is for.
