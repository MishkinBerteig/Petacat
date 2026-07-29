# Phase 5 Plan — Multi-Modal Learning: Audio and Proprioception

**Goal.** Extend perception beyond text to **audio** and **proprioception** —
embodied AI — building directly on the `love`/`not-love` system from Phase 2.

**Depends on.** Phase 2 above all. Phase 3 (the workspace already accepts non-letter
atoms and chunks them hierarchically — audio and proprioception are the severe test of
whether that generalisation was real). Phase 0 (sensor streams make the numeric
substrate genuinely GPU-sized for the first time, and impose the first real-time
deadline the parallelism work has faced).

---

## 0. This phase adds channels; Phase 2 built the pattern

Petacat acquires its first non-workspace perceptual channel in **Phase 2**:
`love`/`not-love`, which reaches the Slipnet without passing through the four-slot
workspace. That channel is **independent and stays independent** (§5) — this phase
does not extend it, feed it, or generalise it. What this phase reuses is the
**construction pattern** Phase 2 was forced to invent, which answers every structural
question audio and proprioception will re-ask, in the smallest possible case:

| Question | Answered in Phase 2 for valence | Re-asked here, per new channel |
|---|---|---|
| How does a non-workspace percept reach the Slipnet? | one signed magnitude | continuous multi-dimensional streams |
| At what cadence does it arrive? | per turn, injected | continuously, at a rate we do not control |
| How persistent is its influence? | global modulation (A) + structural reification (B) | the same two mechanisms, richer input |
| How is it arbitrated against the workspace? | it modulates rather than competes | genuinely open |

So the work here is **building new channels to an established pattern**, not inventing
the notion of a channel. That materially reduces the risk of the phase — and it means
Phase 2's implementation choices constrain this one, which is why Phase 2's exit
criteria require the valence path to be built as a *general* non-workspace percept
path rather than a valence-specific hook.

## 1. The claim being tested

The architectural bet is that **perception, analogy-making, and concept acquisition
are the same process applied to different objects**. Text has been the only object so
far, and text is suspiciously convenient: discrete, sequential, and already
symbol-shaped.

Audio and proprioception are the honest test, because they are none of those things.
If the same workspace, the same codelets, and the same slipnet machinery can perceive
them, the claim survives. If each modality needs bespoke machinery, the claim was
about text all along.

**This phase is therefore falsification-shaped**, and should be planned as an
experiment rather than a feature.

## 2. Why these two modalities, and why together

They fail differently, which is the point:

- **Audio** is *continuous, dense, and exogenous* — it arrives whether or not the
  system acts, at a rate it does not control. It stresses **chunking and attention**:
  Phase 3's tokeniser must find units in a signal with no whitespace and no bytes.
- **Proprioception** is *continuous, low-dimensional, and endogenous* — it is the
  consequence of the system's own action. It stresses **the identity axis**: a
  proprioceptive percept is `me` in a far stronger sense than an emitted byte ever
  was, because the system caused it *and* feels it.

Together they give the **act → sense → value** loop its richest form. The loop itself
is not new — Phase 2 closes it with text, and it runs unchanged from there. What these
modalities change is the *acting* and the *sensing*: proprioception in particular makes
the consequence of an act directly perceptible, so the gap between what Petacat did and
what followed narrows to almost nothing. The **value** term remains what it has always
been — the independent valence channel — and is not derived from the body.

## 3. The central problem: getting continuous signal into a symbolic workspace

Phase 3 established the governing principle in its own domain, and it transfers
verbatim: **dropping to a lower-level representation dilutes structure; the first job
of chunking is to rebuild the relational structure that dropping threw away.** Raw
audio samples are to this phase what raw bytes were to Phase 3 — only worse, because
there is no equivalent of a byte boundary.

Three sub-problems, none solved:

- **Atoms.** What is the analogue of a letter? Candidates: spectral frames, onsets,
  quantised feature vectors, or learned units. Whatever is chosen must support
  **sameness** and some ordering relation, or the engine has nothing to bond with.
- **Relations.** `successor` over letters is given. Over pitch, loudness, or joint
  angle it is *available* — these are ordered dimensions — which is grounds for
  optimism: audio and proprioception may actually be **better** suited to Copycat's
  relational machinery than raw bytes were, because they are natively ordered and
  metric.
- **Rate and windowing.** Text arrives in turns; sensor data arrives continuously.
  The sliding 4-slot window (Phase 2) needs a temporal analogue, and "the turn" — the
  unit Phase 0's Normal mode persists at — must be redefined for a system that is
  never not perceiving.

## 4. Cross-modal bridges — where the real result would be

Petacat's native operation is the **bridge**: a mapping between objects in different
strings carrying concept-mappings. Nothing in that definition requires both objects to
be the same *kind*.

A bridge between an **auditory** structure and a **proprioceptive** one is a
cross-modal correspondence — *this rising tone is to that reaching motion as…* — and
it is the same machinery, unmodified. If that works, multi-modality is not a new
subsystem but a new *population of objects* in an unchanged workspace, which is
exactly the architectural claim in §1.

**This should be the headline experiment of the phase**, not an afterthought: the
first genuine cross-modal analogy is worth more than fluent single-modality
perception.

## 5. What this phase inherits from valence — the mechanism, not the channel

The relationship between Phase 2's valence work and this phase is easy to get wrong,
so it is worth stating precisely.

**`love`/`not-love` is not a sensory channel, and nothing in this phase feeds it.** It
is a philosophical stance made architectural: valence expresses the **mother/child,
`not-me`/`me` relationship** — a soul-level channel that is deliberately **independent
of every other perceptual channel**. It does not report on the world, and it does not
report on the body. Proprioception does not become a source of love; hearing does not
become a source of love. Conflating them would collapse the very distinction the
design is built to preserve.

**What transfers is the technical mechanism.** Phase 2 has to build a path for a
percept that reaches the Slipnet *without passing through the four-slot workspace*:
how it arrives, at what cadence, how it persists, how it influences structure. That
path is the reusable part. Phase 5 instantiates it **again, separately**, for audio and
for proprioception — as **new independent channels alongside valence**, not as inputs
to it.

**Every modality is a full input/output modality**, and they are **not separate
workspaces**. Text, audio, and proprioception share one analogy-making architecture —
the same `(1):(2)::(3):(4)` — and differ only in the *physical mechanism by which data
is ingested and emitted*:

| | In → Out | Machinery | Introduced |
|---|---|---|---|
| Text / symbols | text in → text out | `(1):(2)::(3):(4)` | existing |
| Audio / speech | audio in → audio out | the same | Phase 5 |
| Proprioception / movement | position in → position out | the same | Phase 5 |
| `love` / `not-love` | valence in → valence out | **not analogy-making** — a reserved primitive | Phase 2 |

The existing text modality is distantly analogous to **sight and personal appearance**:
text in is a way of seeing, text out is a way of presenting. Naming it that way makes
"text out" feel like a modality rather than like an answer, which is the right
intuition to carry into audio and movement.

**Valence is the exception in the table, and deliberately so.** It is not perceived
through the four-slot machinery, does not chunk, and is not discovered from data — it
is an underlying API, closer to a tokenizer's reserved tokens than to a percept. It is
nonetheless bidirectional like the others, and Phase 2 builds both directions.

**The Phase 2 design constraint this implies.** If Phase 2 builds the valence path as a
valence-*specific* hook, Phase 5 has to invent the pattern twice more. Phase 2's exit
criteria therefore require it to be built as a general non-workspace percept path —
generality serving reuse, while the channels themselves stay separate.

**[open]** How independent channels are arbitrated when they are simultaneously
active, given that they compete for the attention of one coderack.

## 6. Honest risks

- **Scope.** This is the largest expansion in the programme, and it depends on every
  prior phase having generalised properly rather than having been quietly specialised
  to text. Phase 3's exit criteria are the early-warning system: if bytes needed
  text-specific hacks, audio will not work.
- **Hardware and embodiment.** Proprioception implies a body — real or simulated. A
  simulated one is the sane starting point and keeps Phase 0's determinism guarantees
  intact; a physical one breaks reproducibility in the same way the `local-llm` does,
  and needs the same record-replay treatment.
- **Rate mismatch.** The engine runs at ~10⁴ codelets/second on text problems lasting
  ~10³ codelets. Real-time sensor streams impose a deadline the architecture has never
  faced. This may be the binding constraint, and it is what Phase 0's parallelism work
  ultimately has to pay for — free-running exists partly for this.
- **Evaluation.** Text completion has an obvious metric; "did it perceive the sound
  well" does not. Defining success *before* building is more important here than
  anywhere else in the programme.

## 7. Exit criteria (provisional)

- Audio and proprioceptive percepts enter the workspace and are chunked by the Phase 3
  mechanism **without modality-specific machinery**.
- Bonds and groups form over sensor atoms using existing relations.
- **At least one cross-modal bridge** is built and used in a rule.
- Audio and proprioception are each a **full input/output modality** running on the
  unchanged `(1):(2)::(3):(4)` machinery — audio in → audio out, position in → position
  out — with no modality-specific analogy path.
- They are instantiated as **independent channels** with **no coupling to the valence
  channel** — verifiable by the fact that `love`/`not-love` is unaffected by whether a
  body is attached.
- **The act → sense → value loop closes in each new modality**, exactly as it does for
  text in Phase 2: a proprioceptive percept arising from an act Petacat took is bridged
  to the act that produced it, and the value term remains the valence channel.

## 8. Open questions

1. **Atom definition** for each modality (§3).
2. **Temporal windowing** — the analogue of the turn for a continuously-perceiving
   system, and what Normal mode persists at.
3. **Simulated vs. physical embodiment**, and the determinism consequences.
4. **Arbitration between simultaneously-active independent channels** (§5) — they
   share one coderack and one Slipnet but must not collapse into one another.
5. **Evaluation criteria** — what "perceiving well" means, defined in advance.
6. **Real-time feasibility** — whether the free-running engine Phase 0 delivers reaches
   the required rate. If it does not, that is a constraint discovered here and resolved
   by re-opening Phase 0, not by scheduling work inside this phase.

## Glossary

| Term | Meaning |
|------|---------|
| **Modality** | A full input/output channel — text, audio, proprioception — all sharing one analogy-making architecture and differing only in physical ingest/emission |
| **Cross-modal bridge** | A bridge whose two objects come from different modalities |
| **Independent channel** | A channel that reaches the Slipnet on its own path and is not an input to any other |
| **Mechanism vs. channel** | Phase 5 reuses Phase 2's *construction pattern* for non-workspace percepts; it does **not** feed Phase 2's valence channel |
| **act → sense → value** | The loop established in Phase 2 with text; this phase varies only the physical means of acting and sensing, never the value term |
