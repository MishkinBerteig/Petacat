# Phase 3 Plan — Arbitrary Bytes and the Emergent Tokenizer

**Goal.** Expand the workspace to accept **arbitrary input bytes**, and generalise
Phase 1's concept-and-link creation from the controlled capital-letter case to
open-ended chunk discovery — leveraging the existing episodic memory as the
vocabulary store, with byte-pair encoding as the guiding analogy.

**Depends on.** Phase 1 heavily — that phase establishes both the concept/link
creation mechanism *and* the BPE-style frequency accumulator, in a domain where the
right answer is known. This phase generalises both rather than inventing anything.
Phase 2 (valence can gate promotion; the transcript is what gets tokenised). Phase 0
(the O(n²) GPU pair-scoring kernel is what makes a large window computationally
possible at all).

---

## 1. Why raw bytes are not enough — and why this is the whole problem

Copycat's power comes from atoms living in a **small, totally-ordered,
richly-related** space. Raw bytes break every part of that:

- successor-over-bytes is mostly semantic noise (`'z'`=122, `'A'`=65, `' '`=32);
- sameness fires only on exact byte equality;
- UTF-8 fragments a single character across 1–4 atoms.

Bytes do not expand the perceptual space — they **dilute** the structure the engine
runs on. **Tokenisation's first job is to rebuild the relational structure that
dropping to bytes threw away.** That is the sentence this entire phase turns on.

Phase 1 proved the mechanism on capitals, where the target structure was known in
advance and success was gradable. Here the structure is *not* known in advance, which
is exactly what makes it research rather than engineering.

**[open]** Preserve a–z (and their curated links) as pre-seeded tokens so existing
letter-string competence does not regress. Almost certainly yes; the question is
whether capitals from Phase 1 are also pre-seeded or re-learned.

## 2. Tokenisation is forced by scale, not chosen

Copycat is roughly **O(objects²)** in bridges and salience and was built for ~3–7
atoms. A flat 2048-byte string is both computationally infeasible and cognitively
wrong. Hierarchical tokenisation is **required**, not optional, to keep the number of
simultaneously-perceived objects small.

Two independent attacks on the same wall, and neither alone suffices:

- **Tokenisation attacks the exponent** — fewer, larger objects.
- **Phase 0's GPU pair-scoring attacks the constant** — the same O(n²) done wide.

## 3. The two-level design

- **Level 1 — Groups (ephemeral, per-run).** Copycat *already* has emergent chunking:
  a group is "adjacent atoms bonded and treated as a single higher-level object."
  Byte chunking must reuse this, not reinvent it.
- **Level 2 — Crystallised token-nodes (persistent, cross-run).** A group *pattern*
  that recurs across runs **and earns its keep** is promoted to a permanent Slipnet
  concept — a learned "Platonic chunk," the true analogue of a BPE merge, but
  grounded in Petacat's own machinery.

Tokenisation must be **hierarchical / recursive** (bytes → tokens → phrases), matching
the "composite atoms, multiple layers simultaneously" ambition of
`FUTURE_DIRECTION.md` §1.

## 4. Frequency proposes, utility disposes

Phase 1 establishes this division of labour on capitals; Phase 3 carries it into open
territory. Frequency accumulation — the BPE-style sub-perceptual layer — is a cheap
way to *propose* candidates. It is not a good way to *decide*, because it was borrowed
from a setting we do not have (giant corpus, offline, one-shot vocabulary
construction) and because it says nothing about what a candidate is related to.

Petacat has a signal a corpus tokenizer does not: **did this chunk participate in
bonds, bridges, and rules that actually lowered temperature?** A frequent-but-useless
byte-pair is a worse token than a rare-but-pivotal one.

Phase 2's supervised, one-shot, love-gated concept formation and this phase's
unsupervised, gradual, frequency-and-utility crystallisation are complementary:
**both are kept.**

## 5. Cold start — why this depends on episodic memory

One transcript is far too little data for frequency to discover good tokens.
"Emergent over time" must mean **across runs**, accumulated in **Episodic Memory**.
Tokens are a **long-term learned asset**, which is precisely why Phase 0 made episodic
memory a named, versioned input with a recorded `memory-hash`: the vocabulary a run
saw becomes part of that run's identity, and reproducibility survives a growing
vocabulary.

This is also the first phase where memory stops being commentary-only and starts
**feeding perception** — the prospective concern noted in Phase 0 becomes live here.

## 6. Wiring tokens — inherited from Phase 1, at scale

A crystallised token has an *identity* but no **links**, and the criterion from
`FUTURE_DIRECTION.md` §0 is that a concept must "participate in slippages and bridges
and rules the way `successor` does" — which it can only do through links. So the hard
part is not *creating* token nodes; it is **wiring** them.

Phase 3 does not invent a wiring mechanism. It inherits whichever internal mechanism
Phase 1 established — participation history, utility, or whatever survived that
phase's central open question — and applies it where the target structure is no longer
known in advance.

Phase 2's backward pass (B) provides a second, complementary route: a love-born
concept is linked to its constituent path *by construction*, and unlike the internal
mechanisms it is supervised and one-shot.

**If Phase 1 returned a negative result** — if internal evidence proved insufficient to
supply relations — then this phase inherits that problem in a harder form, and the
learning-by-asking work parked in Phase 6 becomes a prerequisite rather than a
future direction. That dependency should be resolved before this phase starts, not
discovered inside it.

## 7. Exit criteria

- Arbitrary bytes enter the workspace without silent degradation (the Phase 1
  noticing mechanism generalises).
- A vocabulary accumulates **across runs** and persists.
- **Utility beats frequency**: a vocabulary promoted on utility outperforms one
  promoted on frequency alone, measured by effort-to-answer on held-out material.
  This is the phase's central claim and must be measured, not assumed.
- Crystallised tokens **demonstrably lower effort on problems they were not
  crystallised from** — transfer, as in Phase 1, is the anti-memorisation criterion.
- A 2048-byte window is tractable: object counts stay bounded by hierarchical
  chunking, and wall-clock stays acceptable with the GPU substrate.
- a–z competence unregressed.

## 8. Open questions

1. **Promotion criterion** — the precise utility measure, threshold, and how it
   interacts with frequency as a candidate-proposer.
2. **Vocabulary persistence** — schema and lifecycle in Episodic Memory; how it
   relates to (and is distinguished from) Phase 2's love-born concepts.
3. **Recursion depth** — how many levels of hierarchy, and what stops runaway
   chunking.
4. **Demotion.** Tokens that stop earning their keep — does `not-love` handle them, or
   does the tokeniser need its own decay? Homeostasis applies here too.
5. **Pre-seeding** — a–z certainly; capitals and whitespace open.
6. **UTF-8** — whether the atom is a byte or a codepoint, given the fragmentation
   problem in §1.

## Glossary

| Term | Meaning |
|------|---------|
| **Crystallisation** | Promotion of a recurrent, useful group pattern into a permanent Slipnet token-node |
| **Token (Petacat sense)** | A learned chunk concept, hierarchical, wired by asking the other |
| **Utility gate** | Promotion criterion based on participation in structures that lowered temperature |
| **Level 1 / Level 2** | Ephemeral per-run groups vs. persistent cross-run token-nodes |
| **Cold start** | The problem that one transcript is too little data to discover good tokens |
