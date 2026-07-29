# Phase 6 Plan — Remainder

**Goal.** The bucket phase. Everything that does not belong to Phases 0–5 lands here:
the most ambitious items, the deliberately deferred ones, and the synthesis that ties
the programme together.

**Depends on.** Everything. Nothing here is startable early, and most of it is only
meaningful once Phases 0–5 have produced something to tune, prune, or explain.

**Read this phase differently.** Phases 0–5 are sequenced work. This is a holding
area, and its items are largely independent of each other. Some are near-certain to be
attempted (evolutionary tuning); one is the north star of the whole programme
(stage (c)); one may never be needed (recall).

---

## 1. Learning by asking — curiosity, inquiry codelets, and the teacher

Phases 1 and 3 grow the Slipnet **purely internally**: frequency accumulation,
utility, participation history, and the love-gated backward pass. None of them
involves the system *asking anyone anything*. That was a deliberate constraint, and
this is where it is lifted.

**Curiosity.** A parameter sitting alongside temperature, rising when the workspace
contains objects the Slipnet cannot describe, and biasing codelet selection toward a
new family of **inquiry codelets** whose job is not to build perceptual structures but
to expand the Slipnet itself. The current system has no way to say *"I don't know what
this is"*; this gives it one.

**The deep move is not asking — it is what happens when the answer comes back.** The
response must **not** be parsed deterministically. Understanding the explanation *is
itself an analogy problem*, solved by running another perceptual pass through the same
machinery. If *"X is like Y but more formal"* arrives, the system treats *"more formal
than Y"* as a structure to perceive, and whatever bonds, bridges, and slippages emerge
while perceiving it become the new Slipnet content for X. If a novel element appears
*while* perceiving the response, it asks again — analogies nested inside analogies,
recursing downward until they bottom out in concepts the system already knows.

There is no separate learning module. Perception, analogy-making, and concept
acquisition are the same process at different levels of abstraction. **The system
learns by perceiving its teacher.**

**Why this is parked here rather than earlier.** Asking is the most powerful mechanism
in the design and therefore the one most likely to mask a failure of the internal
ones. If Phase 1 had been allowed to ask, we would never learn whether internal
evidence can supply relational structure — the teacher would quietly do the work and
the question would go unanswered. Deferring it makes Phases 1 and 3 honest experiments.

**The dependency to watch.** If Phase 1 returns a negative result — internal evidence
cannot supply links — then this item stops being a Phase 6 ambition and becomes a
**prerequisite for Phase 3**, and the programme's ordering has to change. That is the
single most likely way this plan gets restructured, and it should be checked at
Phase 1's exit rather than discovered later.

**[open]** Who the teacher is. The `local-llm` of Phase 2 is the obvious answer; a
human is the other. Both are `not-me`, which means this item is also where the
identity axis and the concept-acquisition machinery finally meet.

## 2. Stage (c) — new relation types, and genuine ontology bootstrap

The backward pass (Phase 2, mechanism B) creates structure in three escalating forms:

- **(a)** new nodes — compositions of existing concepts;
- **(b)** new links between existing nodes — the graph topology learns;
- **(c)** **new relation types** — the system invents relational primitives it was not
  born with.

**(c) is the goal — the north star of the entire design.** A system that can invent
relational primitives could, in principle, rediscover structures like the alphabet on
its own rather than being handed them. Phases 1–4 ship (a) and (b); (c) waits here
because it is a research problem in its own right and carries the most risk.

**The question that must be answered first**, and which no earlier phase answers:
*what is a new relation, operationally?* Concretely — how do bonds, bridges, and rules
**consume** a relation type that did not exist when they were written? Today the
relation vocabulary (`sameness`, `successor`, `predecessor`, and the facets) is
threaded through bond formation, group formation, concept-mappings, rule clauses, and
the theme dimensions. A genuinely new relation type has to be legible to all of them.

Two sub-questions worth separating:

- **Representation.** Is a new relation a new row in a table the existing machinery
  already reads generically, or does it require the machinery to become generic first?
  The DB-driven design makes the former plausible, which is the main reason to think
  (c) is reachable at all.
- **Discovery.** What evidence would justify positing a new relation? The honest
  answer is probably: a recurring pattern of bridges that no existing relation
  describes — which makes (c) a consumer of Phase 4's consolidation machinery.

## 3. Evolutionary self-tuning

Every run produces a sequence of codelet executions. That sequence is a **phenotype**;
the **genotype** is the system's configuration, and the database already holds that
configuration as tunable data.

The wager: fitness is something like *answer quality divided by effort*, runs are
reproducible given a seed, and a population of configurations is cheap to materialise.
Can evolutionary pressure, applied across many runs against a curated problem suite,
find configurations that perceive better than the hand-tuned baseline?

Everything this needs is delivered by earlier phases, which is why it sits here rather
than earlier:

- **A fitness metric** — Phase 4's corpus distance function.
- **Cheap runs** — Phase 0's Fast Run.
- **Population throughput** — Phase 0's GPU population batching, which is the one
  workload that genuinely saturates the hardware.
- **Reproducibility** — Phase 0's config-hash and re-execution guarantees.

**The sample-efficiency caveat.** Under free-running each run is one draw from a
distribution rather than a deterministic outcome, so fitness needs more runs per
configuration to see through interleaving noise. Population batching is what pays for that — the technique that makes
free-running affordable to evaluate is the same one that makes the GPU worth using.

**The interesting questions are empirical, not engineering:** what *kinds* of change do
better configurations represent — gentle nudges to existing dynamics, or qualitatively
different styles of seeing? Does speed trade against depth, or do both rise together?
Metacat's behaviour is already emergent from many interacting parameters, and evolution
suits systems where the map from parameters to behaviour is nonlinear and surprising.

## 4. Recall of raw history

From Phase 2 onward, the byte stream of all turns is stored **append-only** and
explicitly **cannot be recalled**. Learning happens by *consolidation* into Slipnet
structure (Phase 4), not by retrieval.

That was a deliberate simplification, and it may well be permanent. The open question
is whether a system that consolidates well ever *needs* retrieval — and the
architecture's own bet is that it does not, because a concept abstracted from
experience is more useful than the experience.

Worth attempting only if Phases 4–5 surface a concrete failure that recall would fix.
**Do not build it speculatively**; the interesting result would be discovering that it
is unnecessary.

## 5. How the threads become one mechanism — the synthesis

The four threads of `FUTURE_DIRECTION.md` are not independent features. Restated
against the phases that deliver them:

- **§0 self/other** — `me`/`not-me` as deepest Slipnet nodes; projection/ingestion as
  the sliplink-in-action. *(Phase 2)*
- **§1 generalised workspace** — the dialogue transcript and the hierarchical emergent
  tokeniser. *(Phases 2, 3)*
- **§3 learning by asking** — curiosity on un-linkable concepts; the teacher wires
  them; understanding the answer is itself a perceptual pass. *(Phase 6, §1 — held back
  deliberately so Phases 1 and 3 test the internal mechanisms honestly)*
- **§2 self-tuning** — the deterministic harness running many transcripts, scoring
  them, evolving configuration. *(Phases 4, 6)*

Perception, analogy-making, concept acquisition, and self/other recognition are the
**same process** applied to different objects at different levels. Every phase is a
test of that sentence; this phase is where it either stands or does not.

## 6. The larger framing, for the record

What this design amounts to is *a new attention-and-completion architecture built on a
Slipnet instead of a back-propagation neural net.* The functional decomposition of a
transformer is preserved; the substrate is swapped:

| Transformer | This design | Phase |
|-------------|-------------|-------|
| Context window of tokens | The sliding window over the transcript | 2 |
| Tokenizer (offline BPE, fixed vocab) | Emergent, hierarchical, utility-gated tokeniser, growable at runtime | 3 |
| Attention (softmax over Q·K) | Salience / importance / unhappiness + spreading activation focusing codelets | — (existing) |
| Weights (frozen float matrices) | The Slipnet — an interpretable symbolic graph | 1 |
| Next-token completion (sample a softmax) | Emit slot (4) by rule-application / analogy | 2 |
| Training (gradient descent, backprop) | The `love`/`not-love` backward pass + consolidation | 2, 4 |
| Hardware: dense matmul saturating a GPU | Heterogeneous Apple-silicon execution — symbolic codelets on CPU cores, numeric substrate on GPU cores, unified memory | 0 |

The bet is that an *interpretable, online, self-watching, self-modifying* system can
occupy the same functional niche. **The open risk is expressivity:** backprop over
massive data finds representations no one designs, and whether Slipnet crystallisation
can discover comparably rich structure is the question the whole programme exists to
answer. The `local-llm`-as-teacher is there to bootstrap it; stage (c) is where it
would either become self-sufficient or be shown not to.

## 7. Also parked here

- **Justification mode — retirement, not extension.** The existing mode that validates a
  *given* answer rather than discovering one. **It is not carried forward past Phase 0**
  and is deliberately excluded from the expected-range baseline, so nothing in Phases
  1–5 depends on it. What remains open is only whether the *capacity* it represents —
  evaluating a supplied answer rather than producing one — is worth reconstructing once
  the workspace is a transcript, which is a different question from keeping the mode.
- **Other "others."** Phase 2 fixes `not-me` as a single `local-llm`. Multiple
  simultaneous others — several LLMs, other Petacat instances — is the natural
  extension and is where theory of mind gets genuinely interesting, because the system
  must model *different* minds rather than *an* other.
- **Re-opening Phase 0**, if Phase 5's real-time deadline turns out not to be met by
  the free-running engine Phase 0 delivers. All scheduling work belongs there, not here
  — this entry exists only to name where the trigger would come from.

## 8. Open questions

1. **Whether learning by asking is a Phase 6 ambition or a Phase 3 prerequisite** (§1)
   — decided by Phase 1's result, and the most consequential open question here.
2. **Who the teacher is** (§1) — `local-llm`, human, or both.
3. **What a new relation type is, operationally** (§2) — the hardest open question in
   the programme.
4. **What evidence justifies positing one** (§2).
5. **Fitness definition** for evolution beyond *quality ÷ effort* (§3).
6. **Whether recall is ever needed** (§4).
7. **Multiple simultaneous others** (§7).

## Glossary

| Term | Meaning |
|------|---------|
| **Curiosity** | A parameter alongside temperature, rising when the workspace holds objects the Slipnet cannot describe |
| **Inquiry codelet** | A codelet whose job is to expand the Slipnet rather than build perceptual structure |
| **Learning by perceiving the teacher** | The answer to a question is not parsed but *perceived* — another analogy pass, recursing until it bottoms out |
| **Stage (a) / (b) / (c)** | The escalating expressiveness of the backward pass: new nodes / + new links / + new relation types |
| **Ontology bootstrap** | A system inventing relational primitives it was not born with |
| **Genotype / phenotype** | The configuration in the database vs. the sequence of codelet executions it produces |
| **Recall** | Retrieval from raw history — deliberately not built, possibly never needed |
