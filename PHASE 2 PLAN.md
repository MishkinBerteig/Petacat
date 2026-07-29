# Phase 2 Plan — me/not-me and love/not-love

**Goal.** Introduce the two axes that make Petacat a *self* that *learns*: the
**identity axis** (`me` / `not-me`) and the **valence axis** (`love` / `not-love`).
The first gives the system something to be; the second gives it a reason to change.

**The two axes are one subject, which is why they share a phase.** Valence is not a
general-purpose reward signal that happens to be introduced alongside identity. It
expresses the **mother/child, `not-me`/`me` relationship** — it is *about* the identity
axis, the felt quality of the relation between self and other. Building either without
the other would be building half of one thing.

**This phase also gives Petacat its first non-workspace perceptual channel.**
`love`/`not-love` is *not* part of the four-part workspace — it is a **separate
mechanism** reaching the Slipnet by its own path (§7), and unlike every other modality
it is **not analogy-making**: it is closer to an underlying API, or to a tokenizer's
reserved tokens. It is **bidirectional** — love/not-love *out* as well as in. Its
consequence is that the machinery for "a percept that does not arrive through the
workspace" gets built here, in the smallest possible case: a single signed magnitude.
**Phase 5 reuses that construction pattern to add further independent channels — audio
and proprioception — but does not extend or feed the valence channel itself**, which
stays independent of every other.

**And this phase closes the act → sense → value loop (§8)** for the first time, in its
text form. That loop does not change afterwards; later phases vary only the physical
means of acting and sensing. Getting the small case right therefore matters out of
proportion to how small it is.

**Depends on.** Phase 0 (turn-level persistence is exactly what Normal mode records;
valence events are a `RunSink` event). Phase 1 (the backward pass creates concepts —
Phase 1 must already know *how* to create and wire them; Phase 2 supplies a new
*trigger*, not a new mechanism).

**Assumption flagged for review.** This plan places the **dialogue transcript** and
the **turn recurrence** here rather than in Phase 3, because `me`/`not-me` are
labels on *emitted vs. received* material and are meaningless without turns.
Phase 2 therefore runs dialogue **at letter-string granularity**; Phase 3 widens the
alphabet to arbitrary bytes. If you intended the transcript to arrive with Phase 3's
byte expansion instead, this is the section to move.

---

## 1. What plays the role of the "other"

- **`me`** = Petacat's own processing and productions.
- **`not-me`** = the `local-llm` (an OpenAI-compatible chat endpoint at
  `127.0.0.1:1234/v1`).

`local-llm` is a **swappable identifier for "the other mind."** The model behind it
will change and may become several LLMs, other Petacat instances, or a mix. The
architecture must not assume a particular model — only that there is *an other* on
the far side of the channel.

`me` and `not-me` become the **deepest nodes in the Slipnet** — deeper than
`object-category` (depth 90), per `FUTURE_DIRECTION.md` §0 ("deeper than any existing
concept"). They are joined by a **sliplink of the `opposite` family**, so a
`me`↔`not-me` slippage uses exactly the machinery that already lets `leftmost` slip
to `rightmost`.

## 2. The perceptual field becomes a dialogue transcript

The workspace is **no longer four fixed strings**. It becomes a single **growing
dialogue transcript**: interleaved turns from `me` and `not-me`, perceived over time
by the same analogy machinery.

- The classic Copycat skeleton is *preserved* — four slots forming one analogy
  `(1):(2)::(3):(4)` — but the transcript **scrolls through** those slots. The engine
  surgery is small: same four slots, but they slide, and slot (4) is *emitted* rather
  than derived-and-displayed.
- Behind the window is an **append-only raw history** of all turns, stored but **not
  recallable** (recall is deferred to Phase 6). Learning happens by *consolidation*
  (Phase 4), not recall.
- **Deterministic labelling by origin:** everything the system *receives* is labelled
  `not-me`; everything it *emits* is labelled `me`. No heuristic guesses origin — the
  harness knows who produced what.

**Why a transcript and not four labelled strings.** me/not-me labels only do
cognitive work when the two kinds of element sit **adjacent in one perceivable
field** and the system must build bridges *across* the self/other boundary. In a
four-string layout, "not-me" would collapse into "you're in the input string" —
positional, trivial, inert. In a transcript they are neighbours, and bridging them is
the whole point.

Theory of mind, in this framing, is **speaker-attribution plus bridging**: perceiving
that the other's contribution mirrors, answers, or diverges from one's own.

## 3. The turn recurrence — the sliding 4-slot window

    (1) is to (2)   as   (3) is to (4)

(1), (2), (3) are given; **(4) is the turn Petacat must produce.**

- **Bootstrap.** The `local-llm` opens with a **three-word statement**; its words seed
  slots (1), (2), (3). Petacat produces (4) — any length, no limit.
- **Exchange.** (4) goes to the `local-llm`, which replies (5) under its system prompt.
- **Reconfigure.** The window slides: `(1)+(2)+(3) → (1′)`, `(4) → (2′)`, `(5) → (3′)`,
  Petacat generates `(4′)`. Then again, forever.

**Semantics.** The top pair `(1′→2′)` is *Petacat's own previous behaviour*; the
bottom pair `(3′→4′)` is (the other's newest input → Petacat's next response). Each
turn Petacat extracts the rule of *its own last turn* and applies it, by analogy, to
what the other just said. **Continuity of self is literally an analogy to one's own
past.**

**The degenerate fixed point.** Because the top pair is Petacat's own last turn, a
trivial turn breeds trivial turns: if (4) is blank, the rule becomes "produce blank,"
and the system can lock into silence. Two things break the attractor: (a) the novelty
the `local-llm` injects as (5)/(3′), which Petacat can *ingest*; (b) snags and
jootsing forcing exploration — the existing self-watching machinery, which is all this
phase has available (curiosity is Phase 6). This makes blank-emission load-bearing
rather than
cosmetic — the system *learns to speak by learning to perceive*, early utterances
near-blank and richening as vocabulary grows (the infant/adult arc, for free).

**This is where the phase can fail.** Collapse into the fixed point is the most likely
negative result in the whole programme, and it should be tested early — before
valence is built on top of it.

## 4. Projection and ingestion — the sliplink in action

The self/other distinction is made *active* by a codelet family that attaches the
**opposite** label to an element that already carries one. Both labels may co-exist.

- **Projection** — an element labelled `me` gains an additional `not-me` label. The
  system hypothesises that the other shares this state.
  *"I notice I'm stuck → perhaps the other is stuck too."*
- **Ingestion** — an element labelled `not-me` gains an additional `me` label. The
  system adopts the other's structure as its own.
  *"The other used rule R → let me perceive R as mine."*

A **dual-labelled** element is the concrete site of the "recognition" qualia: the
moment the pattern in the other is felt to mirror the pattern in the self.

**[open]** What triggers projection/ingestion? Candidates available in this phase:
thematic pressure when a me/not-me theme becomes dominant; a snag on the `me` side
prompting a projection to check the `not-me` side; a valence event. (Curiosity would be
a natural fourth trigger but does not exist until Phase 6.) **[open]** Is the extra
label a `Description` on the object, participating in salience and strength like
others?

## 5. Completion is pure rule-application

Slot (4) is produced by applying the `(1′→2′)` rule to `(3′)`. **No LLM in the decode
path.** Grounding: Hofstadter's claim that *all* cognition is perception and
analogy-making, so a system built purely from those two operations is what we build
and train. A corollary is that the architecture is inherently **multi-modal-ready** —
any percept can enter the same workspace (Phase 5).

## 6. The harness — a shuttle plus a valence injector

At first the harness only orchestrates send/receive between Petacat and its `not-me`.
Its second job is to deliver the fitness signal.

**Pinning the external input.** Petacat is stochastic by design, and a
different-but-correct run is right behaviour — so this is not about making runs
repeat. It is that the `local-llm` is non-deterministic and will be swapped, so unless
every LLM call is **journaled and record-replayed**, a past dialogue cannot be
re-examined at all.

## 7. love / not-love — a separate, independent perceptual channel

By deliberate design choice, valence is *not* modelled as percepts inside the
workspace. It is a **separate perceptual mechanism** with its own path to the Slipnet.

**What it is.** A philosophical stance made architectural. Valence is the
**mother/child, `not-me`/`me` relation** — closer to a *soul-level* channel than a
sensory one, and **completely independent of every other channel**. It does not report
on the world and it does not report on the body; it reports on the relation between
self and other. This grounds it in the same hypothesis as §0 of
`FUTURE_DIRECTION.md`: the infant feels, signals, and acts, and what is missing — the
other's inner life — is inferred by analogy.

**What it is *not*: an analogy-making channel.** This is the sharpest difference
between valence and every other modality. Text, audio, and proprioception are all
perceived through `(1):(2)::(3):(4)` — they are *analogised*. Valence is not. It is
closer to an **underlying API**, or to the **reserved tokens of a tokenizer**: a small
set of structural primitives that are not composed, not discovered from data, and not
inferred by analogy. They are simply *present*, available to the whole system, part of
what it is rather than part of what it perceives.

This is why valence needs no chunking, no bonds, no rules, and no window. It also
means valence carries no risk of the degenerate fixed point (§3) — a reserved
primitive cannot collapse into a trivial rule, because it was never produced by one.

**Why the independence must be preserved in the implementation.** It would be easy, and
wrong, to let valence become a general-purpose reward bus that later channels feed
into. Phase 5 adds audio and proprioception as **their own independent channels**; a
bodily state does not become a source of love. If valence degenerates into "whatever
currently feels good," the distinction the architecture exists to draw is gone.

**The channel is bidirectional: `love`/`not-love` *out* is part of this phase.**
Petacat must be able to **express** valence toward the other, not only receive it. In
the mother/child grounding this is the stronger half — the child does not merely
receive love, it expresses it, and expression is what makes the relation mutual rather
than one-directional. Architecturally it also completes the symmetry with the identity
axis: `me`/`not-me` is a two-way distinction, and a valence channel that only ever
flows inward would make the relation it supposedly reports on asymmetric.

Because valence is a reserved primitive rather than an analogised percept, **emission
is direct** — Petacat does not compose or derive an outgoing valence signal through the
four-slot machinery. It expresses it the way it receives it: as a primitive on the
channel. **[open]** What determines the outgoing signal, given that it is not derived
by analogy — internal state (temperature, snags, theme dominance) is the obvious
candidate.

**What is nonetheless reusable.** This is the first percept arriving outside the
four-slot workspace, so building it answers questions every later channel re-asks: how
a non-workspace percept reaches the Slipnet, at what cadence, with what persistence,
and how it is arbitrated against what the workspace is simultaneously perceiving. The
valence channel is the simplest possible instance — one signed magnitude — which is
exactly why it is the right place to establish the pattern.

**Design accordingly.** Where a choice can be made either as "the valence special
case" or as "the general non-workspace-percept case" at similar cost, take the general
one — *generality of mechanism, independence of channel.* Phase 5's cost is set here.

It couples to the rest of the system in two ways:

- **(A) Global, undirected plasticity modulation.** `love` gives *everything* a small
  boost toward **permanence** (lower decay / higher strength-floor); `not-love` gives
  everything a small nerf toward **impermanence**. Uniform — *no credit assignment* —
  the "how sticky is this moment" neuromodulator.
- **(B) A structural backward pass.** `love` triggers a **memory-formation codelet**:
  read the *whole context*, follow the *deepest activated paths* in the workspace, and
  **reify that path as a new Slipnet concept**, linked to the nodes it was abstracted
  from. The activation pattern is the gradient; the new concept is the weight update.
  `not-love` triggers the dual — a **forgetting codelet** that finds a *learned*
  concept on the deepest activated paths and weakens or removes it.

Because a love-born concept is linked to its constituent path by construction, **B
absorbs the wiring problem** — new concepts are not inert islands. B reuses Phase 1's
node-and-link creation mechanism; what Phase 2 adds is the *trigger*.

**Scope in this phase.** B ships at **stage (a) new nodes** and, if Phase 1 delivered
it, **stage (b) new links**. Stage (c) — new relation types — is Phase 6.

**Homeostasis and safety are requirements, not niceties.** `love` grows the Slipnet
and `not-love` prunes it, so their rates must balance and near-duplicate concepts must
**merge**. Only **learned** concepts are removable — the innate seed ontology (a–z,
the relations, `me`/`not-me`) is protected from `not-love`, or the system can
lobotomise itself. This is why Phase 1 records provenance.

**Who triggers it.** The **harness** (a human or Claude Code now, learned criteria
later) and the **`local-llm`** (social approval). The guider's role *is* to deliver
love.

## 8. The act → sense → value loop — established here, unchanged thereafter

The three preceding sections combine into one cycle, and this is the phase that closes
it for the first time:

    act   — Petacat emits a turn (slot (4)), by rule-application (§5)
    sense — the other replies; the reply enters the transcript as `not-me` (§2, §6)
    value — `love`/`not-love` arrives on the valence channel (§7)
            → mechanism A modulates plasticity; mechanism B reifies structure

**This loop does not change in any later phase.** Phase 4 substitutes a corpus for the
other and derives valence from a distance function; Phase 5 adds audio and
proprioception as further ways to act and to sense. Neither alters the shape. What
varies across the programme is only *the physical mechanism of acting and sensing* —
the loop itself, and the fact that the value term is the independent valence channel,
are fixed here.

Getting the loop right in the simplest case therefore matters out of proportion to how
simple that case is: every later phase inherits it rather than re-deriving it.

## 9. Sub-problems to solve here

- **Blank-space / cold-start emission.** Petacat must emit *something* before it has
  learned anything — the minimal me-turn is a single space. This is the emission
  analogue of "I don't know yet," and the base case that keeps the recurrence from
  stalling. What is the minimal viable me-turn, and how is it produced with no rule
  in hand?
- **The `local-llm` system prompt.** The other's behaviour is shaped entirely by its
  system prompt. It must be a *good other*: responsive enough to be analogisable,
  simple enough not to drown Petacat, and ideally **scaffolding** — starting small
  and enriching as Petacat can handle more (curriculum via prompt).

## 10. Exit criteria

- The recurrence runs for N turns without deadlock, and either escapes the degenerate
  fixed point or produces a clear characterisation of why it does not.
- Dual-labelled elements arise and **demonstrably change behaviour** — not merely
  appear.
- A `love` signal measurably increases what persists; a `not-love` signal measurably
  decreases it (mechanism A), without destabilising the run.
- B creates at least one concept traceable to the activated path that produced it,
  and that concept is subsequently *used*.
- The seed ontology is provably un-removable by `not-love`.
- Slipnet size stays bounded under sustained alternating valence (homeostasis).
- **The valence channel is implemented as a general non-workspace percept path**, not
  a valence-specific hook — verifiable by whether a second such channel could be added
  without redesigning the first, *and* by the valence channel remaining independent of
  any channel so added.
- **Valence flows both ways.** Petacat expresses `love`/`not-love` toward the other, not
  only receives it, and does so as a reserved primitive rather than through the
  four-slot machinery.
- **The act → sense → value loop closes**, repeatedly and stably, in its text form.

## 11. Open questions

1. **Projection/ingestion triggers**, and whether me/not-me labels are `Description`s.
2. **Mechanics of B** — precise definition of "deepest activated paths"; the built
   concept's depth, links, and initial activation; the `not-love` removal target; the
   merge/dedup rule for near-duplicates.
3. **Valence strength** — is the signal graded or binary here? (Phase 4's corpus mode
   supplies a graded signal; this phase may start binary.)
4. **Record-replay** for `local-llm` calls.
5. **Where the transcript belongs** — see the assumption flagged at the top.

## Glossary

| Term | Meaning |
|------|---------|
| **me / not-me** | Deepest Slipnet nodes; origin of material (emitted vs. received), sliplinked as opposites |
| **Dialogue transcript** | The perceptual field: interleaved me/not-me turns perceived over time |
| **Projection** | Codelet attaches `not-me` to a `me` element ("the other may be as I am") |
| **Ingestion** | Codelet attaches `me` to a `not-me` element ("I take on what the other did") |
| **Dual-labelled element** | Carries both labels; site of self/other recognition |
| **Sliding 4-slot window** | The transcript scrolling through the classic `(1):(2)::(3):(4)` slots |
| **Turn recurrence** | `(1+2+3)→1′, (4)→2′, (5)→3′`, Petacat emits `4′`; repeats forever |
| **love / not-love** | A soul-level channel expressing the mother/child, `not-me`/`me` relation; independent of every other channel; supplies the fitness signal |
| **Reserved primitive** | Valence is not analogised — it is an underlying API, like a tokenizer's reserved tokens: present, uncomposed, undiscovered from data |
| **Valence out** | Petacat *expressing* love/not-love toward the other, emitted directly rather than derived through `(1):(2)::(3):(4)` |
| **act → sense → value** | The loop established in this phase and unchanged thereafter; later phases vary only the physical means of acting and sensing |
| **Non-workspace percept** | A percept reaching the Slipnet without entering the four-slot workspace; valence is the first, Phase 5 adds further *independent* ones |
| **Generality of mechanism, independence of channel** | The construction pattern is reused; the channels never merge |
| **Global valence modulation (A)** | Uniform boost/nerf to the permanence of all current structures |
| **Backward pass (B)** | love reifies the deepest activated paths into a new concept; not-love removes a learned one |
| **Homeostasis** | The requirement that growth and pruning rates balance |
