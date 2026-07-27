# Phase 4 Plan — General-Purpose Learning from a Corpus, and Meta-Codelets

**Goal.** Move beyond letter-string analogies to **general-purpose learning from a
text training corpus**, and introduce **self-constructed codelets** via a new
**meta-codelet system** — the first time the system grows *code* rather than *data*.

**Source.** Partitioned from `FUTURE_DIRECTION_DETAILS.md` §9 (consolidation and
self-construction) and the corpus-mode part of §11.

**Depends on.** Phase 3 (a byte-capable workspace and a growing vocabulary). Phase 2
(valence is what corpus mode drives deterministically). Phase 0 (Fast Run is what
makes corpus training affordable at all — this phase is where the ~2.8× and the
population batching actually get spent).

---

## 1. Corpus mode — deterministic, LLM-free training

Because valence is an **externally-supplied** signal (Phase 2), it can be driven by a
**corpus** instead of the slow `local-llm`:

1. Draw the `not-me` turns from real text.
2. Let Petacat emit (4) by rule-application.
3. Set the `love`/`not-love` **strength** deterministically from a *graded*
   **nearness/distance function** between (4) and the corpus's actual next segment.

This turns the system into a trainable **completion mechanism** with a dense,
deterministic signal. Four things fall out of it at once, which is why it is the
centre of this phase:

- **Speed.** No LLM in the loop; runs go at full engine rate, in Fast Run, batched
  across a population on the GPU.
- **Determinism.** No record-replay problem — corpus mode is reproducible by
  construction, unlike live dialogue.
- **A fitness metric.** The same distance function is the quantitative fitness signal
  evolutionary tuning needs (Phase 6).
- **Vocabulary bootstrap.** Phase 3's cold-start problem is a data-volume problem, and
  a corpus is volume.

**Pipeline:** *corpus pre-training → graduate to live `local-llm` dialogue.*

**[open]** The distance function — byte-, token-, or structure-level nearness. It must
be **graded**, so valence has strength and not merely sign; a binary
right/wrong signal wastes most of the information a corpus offers.

### 1a. Wiring the valence channel into training — the open problem of this phase

Phase 2 builds `love`/`not-love` as a **bidirectional reserved primitive**: an
underlying API, not an analogised percept. That is the right shape for a live dialogue
with a single other, where valence arrives from a harness or from the `local-llm`. It
is *not* obviously the right shape for training at corpus scale, and connecting the two
is a genuine design problem rather than a plumbing task.

Three things have to be reconciled:

- **Valence is a primitive, but the corpus signal is derived.** The distance function
  computes a graded value; the channel accepts a reserved primitive. Where the
  conversion happens — and whether a derived value can enter a channel defined as
  *not* derived — needs settling without eroding what makes valence a primitive.
- **Valence out has no obvious recipient in corpus mode.** Petacat expresses
  `love`/`not-love` toward the other, and a corpus is not an other. Either corpus mode
  drops the outbound direction (and trains on a *partial* loop, which is a real
  fidelity gap worth naming), or something must stand in as recipient.
- **Training needs many others, not one.** Corpus pre-training graduating to live
  dialogue implies a population of not-self LLMs, and valence has to be well-defined
  across all of them.

**The leading approach: a RAG / memory-architecture harness around the not-self LLMs.**
Rather than treating each not-self LLM as a stateless responder, wrap it in a retrieval
and memory layer so that it can hold a *relationship* with Petacat across turns —
recalling prior exchanges, tracking what it has already valued, and responding with
continuity. This matters because valence in this design is **relational** by definition
(the mother/child, `not-me`/`me` relation), and a stateless other cannot sustain a
relation. A memory-bearing other can be a consistent source *and* recipient of valence,
which restores the outbound direction and keeps the act → sense → value loop whole
during training rather than only during live dialogue.

**[open]** The harness architecture: what the not-self LLM retrieves over, how much of
the exchange history it holds, whether each not-self instance has its own memory
(making them genuinely distinct others), and how any of this stays reproducible under
Phase 0's guarantees.

## 2. Consolidation — the conversation becomes structure

There is **no end** to the conversation; the goal is a system that **learns forever**.
Attention stays on the bounded window; learning happens by *consolidating* the passing
conversation into long-term structure.

- **Raw history** — the byte stream of all turns is stored append-only; it **cannot be
  recalled** (recall is Phase 6).
- **Consolidation** — periodically the current conversation is *instantiated in memory*
  as **Slipnet nodes and links**. This is Phase 3's crystallisation generalised beyond
  tokens to arbitrary learned structure. It is the "training" of this architecture.
- **The learning signal is self-watching.** Themes, the Temporal Trace, and coderack
  activity are mined for regularities; those that recur *and* prove useful are
  **reified**:
  - recurrent dominant **themes** → new nodes / links;
  - recurrent **trace** event-patterns → new posting-rules / attention habits;
  - productive **codelet** activity → the fitness signal for codelet-level change.

The third of those is what makes the meta-codelet system possible, and it is why
consolidation and self-construction belong in the same phase.

## 3. Meta-codelets — growing code, not just data

Everything through Phase 3 reifies **data**: nodes, links, posting rules. That is safe
and native to the DB-driven design — new knowledge is just new rows. Reifying **code**
is program synthesis, and it can corrupt the workspace in ways data cannot.

The existing architecture is unusually hospitable to this, which is the reason to
attempt it:

- Codelet behaviour is already **Python source stored in a database column**
  (`execute_body` on codelet type definitions), compiled once at startup and executed
  in a sandboxed namespace of built-in helpers.
- **Adding or modifying a codelet type is already a database change** — no Python
  changes required.

So a meta-codelet — a codelet whose product is a *new codelet type* — writes to the
same place a human author would. The mechanism exists; what does not exist is the
**safety boundary** and the **generative principle**.

**Safety boundary — required, not optional:**

- Generated codelets run **sandboxed and provenance-marked**, distinguishable from
  the 27 curated types.
- A generated codelet is **quarantined** before promotion: it runs in Audit or a
  shadow mode, and is retained only if it demonstrably helps.
- **`not-love` can remove a generated codelet; it can never remove a curated one** —
  the same seed-ontology protection Phase 1 established for nodes, extended to code.
- The DSL validator (`codelet_dsl/validator.py`) becomes load-bearing rather than
  advisory.

**[open — the hard question]** *What is the generative principle?* Options, roughly in
order of ambition: parameterising existing codelet templates; recombining fragments of
existing bodies; mutating bodies under evolutionary pressure; and — most ambitious —
using the `local-llm` to *write* a codelet body from a description of a recurring
trace pattern. The last is the only one that could produce genuinely novel behaviour,
and it is also the one that most needs the quarantine.

**Note on the constraint this creates.** Self-constructed codelets depend absolutely
on codelets remaining **data** rather than compiled artefacts. This is the concrete
reason Phase 0's runtime choice matters: a native-core rewrite that re-hosts the DSL
puts this phase at risk, which is why Phase 0 leans toward keeping the codelet DSL in
Python.

## 4. Exit criteria

- Corpus training runs end-to-end in Fast Run, batched across a population.
- **Measurable improvement in corpus completion across training** — the first genuine
  learning-curve result in the programme, and the headline claim of the phase.
- Consolidation demonstrably produces Slipnet structure that transfers to unseen
  material.
- At least one **self-constructed codelet** survives quarantine, is promoted, and
  measurably improves performance — with its provenance and its effect both traceable.
- A generated codelet that misbehaves is caught by the boundary rather than by a
  corrupted run.
- Curated codelets provably un-removable.

**Negative results worth having.** If self-constructed codelets never beat the curated
27, that is a real finding about the limits of the generative principle chosen — and
it does not invalidate corpus training, which stands on its own.

## 5. Open questions

1. **Distance function** — level, gradation, and how it maps to valence strength.
2. **Valence-to-training wiring** (§1a) — converting a derived corpus signal into a
   reserved primitive; whether corpus mode keeps the outbound direction; the RAG/memory
   harness around the not-self LLMs, and its reproducibility under Phase 0.
3. **Corpus choice and curriculum** — what text, in what order, and whether the
   `local-llm` system prompt from Phase 2 becomes a curriculum controller here.
4. **Consolidation cadence** — when it runs, and how much of a conversation it
   consumes at once.
5. **Generative principle for meta-codelets** (§3).
6. **Quarantine criteria** — how long, measured against what, and who promotes.

## Glossary

| Term | Meaning |
|------|---------|
| **Reserved primitive (valence)** | Valence is an underlying API, not an analogised percept — the shape corpus training must accommodate without eroding |
| **Not-self harness** | A RAG/memory layer wrapping each not-self LLM so it can hold a *relationship* across turns, making it a consistent source and recipient of valence |
| **Corpus mode** | Drive valence from nearness of emitted (4) to a corpus's next segment — deterministic, LLM-free training |
| **Distance function** | The graded nearness measure that sets valence strength |
| **Consolidation** | Crystallising a passing conversation into Slipnet nodes/links — this architecture's "training" |
| **Raw history** | Append-only byte log of all turns; stored but not recallable until Phase 6 |
| **Meta-codelet** | A codelet whose product is a new codelet type |
| **Quarantine** | Shadow/audited execution of a generated codelet before it is promoted |
