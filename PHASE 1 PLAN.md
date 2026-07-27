# Phase 1 Plan — Growing the Slipnet: New Concepts and Connections

**Goal.** Work out how Petacat creates **new concept nodes and new links** in the
Slipnet, staying entirely within letter-string analogies but introducing **capital
letters**, which the system does not currently know.

**Source.** Partitioned from `FUTURE_DIRECTION_DETAILS.md` §4a (relational structure),
the (a)/(b) staging of §11, and the frequency-accumulation idea that opens §4.

**Scope — purely internal.** The mechanism must be **self-contained**: no teacher, no
external inquiry, no dependence on anything Phases 2–5 introduce. It builds on what
the system already has — the **existing episodic memory**, **new codelets**, and a
**sub-perceptual frequency-accumulation system modelled on BPE** — and nothing else.
Learning by asking (curiosity, inquiry codelets, a teacher who supplies links) is
explicitly **Phase 6** work and must not leak into this phase; if the internal
mechanism can only be made to work by asking someone, that is a finding to report,
not a licence to import Phase 6.

**Depends on.** Phase 0 (Fast Run makes the many short experiments here affordable;
Audit mode is how a single acquisition episode gets explained).

**Why capitals.** They are the smallest possible expansion of the perceptual space
that is still a genuine one. Unlike arbitrary bytes (Phase 3), capitals arrive with
an *intended* relational structure we can check the system against: `A` is a
successor of nothing and predecessor of `B`; `A` corresponds to `a`; the whole
sequence `A…Z` is isomorphic to `a…z`. So we can ask a sharp, falsifiable question —
did the system discover that structure, or merely memorise instances? Arbitrary
bytes cannot be graded that way. This phase is the controlled experiment that Phase 3
generalises.

---

## 1. The concrete starting point

Today's entire perceptual apparatus is four lines, `server/engine/workspace.py:39-43`:

```python
for i, ch in enumerate(text):
    node_name = f"plato-{ch}"
    letter_node = slipnet.nodes.get(node_name)
    letter = Letter(self, i, letter_node)
    self.objects.append(letter)
```

`slipnet.nodes.get("plato-A")` returns `None`. Verified behaviour on
`abc → abd; XYZ → ?`:

- Initialisation **succeeds** — no exception.
- The target string's three objects are created with `node = None`.
- The run **halts at the step limit with no answer** (800 codelets, none found).

So the failure mode is **silent degradation, not a crash**: nodeless letters carry no
letter-category description, so they cannot be bonded by letter-category, cannot be
bridged by identity or slippage, and cannot be grouped. The workspace looks populated
and perceives nothing.

This is a good starting point precisely because it is quiet. The first deliverable is
to make the system *notice* — an object it cannot describe should raise a signal, not
be silently inert.

## 2. What this phase must produce

Three capabilities, in dependency order:

- **(0) Noticing.** The system can tell that an object is unrelatable — that it has
  no concept, or a concept with no useful links. Today it cannot.
- **(a) New nodes.** A concept is created for a novel symbol and takes its place in
  the Slipnet with a conceptual depth.
- **(b) New links.** The new node is *wired* — related to existing nodes by
  successor / predecessor / sameness / correspondence — because a node without links
  cannot participate in bonds, bridges, or rules, and `FUTURE_DIRECTION.md` §0's
  criterion is exactly that a concept must "participate in slippages and bridges and
  rules the way `successor` does."

**(b) is the hard part, and the point of the phase.** Creating a node is a database
insert. Wiring it is the research problem, and everything downstream — Phase 3's
tokens, Phase 2's love-born concepts, Phase 4's consolidated structure — depends on
solving it here in the easiest domain available.

## 3. Three internal mechanisms — the design space

The valence signal (`love`/`not-love`) that later drives concept formation does not
exist until Phase 2, and asking a teacher is Phase 6. So the mechanism must be built
from what the system already has. Three candidates, to be used singly or in
combination:

### 3a. A sub-perceptual frequency accumulator, modelled on BPE

The closest working analogue in machine learning is how a tokenizer builds a
vocabulary: count adjacent-pair occurrences across a corpus, merge the most frequent
pair into a new unit, repeat, and let a hierarchy emerge from nothing but counting.

Applied here, this runs **beneath perception** — not as codelets competing in the
coderack, but as a statistical layer accumulating across runs, proposing candidate
concepts that the perceptual layer then either uses or ignores. Two properties make
this attractive as the Phase 1 spine:

- It is **unsupervised and self-contained** — exactly the constraint of this phase.
- It has a **known-good precedent** at scale, so a failure is informative: if
  BPE-style accumulation cannot find structure in something as regular as `A…Z`, the
  approach will not survive contact with arbitrary bytes in Phase 3 either.

The departure from BPE is what happens *after* a candidate is proposed. A tokenizer
merges on frequency alone; here the candidate must be **wired into the Slipnet**, and
frequency says nothing about what a thing is *related to*. Frequency proposes;
something else must dispose.

### 3b. Utility — earning a place in the Slipnet

Petacat has a signal a corpus tokenizer does not: **did this candidate participate in
bonds, bridges, and rules that actually lowered temperature?** A frequent-but-useless
pattern is a worse concept than a rare-but-pivotal one.

This is the natural counterpart to 3a: frequency accumulates candidates cheaply,
utility decides which are promoted and which decay. It also generalises directly to
Phase 3, where it becomes the tokeniser's promotion gate.

### 3c. Episodic memory as the accumulator

Cross-run accumulation needs somewhere to live, and the **existing episodic memory**
is already cross-run by design and already stores rich structural descriptions of
answers — including the themes and rules that produced them. Reusing it, rather than
building a parallel store, keeps the phase honest about building on what exists.

This is also where Phase 0's work first earns its keep: episodic memory as a **named,
versioned input** with a recorded `memory-hash` means a growing concept vocabulary
does not silently break reproducibility.

**[open — the load-bearing decision of this phase]** Which of these carries the
weight, and specifically **what supplies the links**. Frequency and utility both
identify *that* something is a unit; neither says *what it resembles*. The most
promising internal answer is that links come from the **structures the candidate
already participated in** — if a chunk was repeatedly bridged to `a` with a slippage,
that bridge history is the evidence for a link. Whether that is sufficient, or whether
internal evidence fundamentally cannot supply relational structure, is the question
this phase exists to answer.

## 4. Why relational structure is the thing being learned

Copycat's power comes from atoms living in a **small, totally-ordered, richly-related
space**. What makes `a…z` work is not that there are 26 of them but that they are
densely connected: successor, predecessor, sameness, and the alphabetic-position
facet. A newly created node with no such relations is inert regardless of how
correctly it was created.

So the measure of success in this phase is **not** "does `plato-A` exist" but "does
`A` behave like a letter" — can it be bonded, bridged, grouped, and slipped. That
distinction is what keeps (a) from being mistaken for (b).

## 5. Design constraints

- **Do not regress a–z.** The existing curated Slipnet is the reference. The demo
  suite must continue to pass unchanged; any degradation is a finding, not a cost.
- **Learned vs. innate must be distinguishable.** Every node and link gains a
  provenance marker. Phase 2's `not-love` removal, and every later pruning mechanism,
  depends on being able to protect the seed ontology from self-lobotomy. Establishing
  the distinction here is cheap; retrofitting it later is not.
- **Growth is data, not code.** New nodes and links are new rows — native to the
  DB-driven design. No engine changes are needed to *hold* new concepts, only to
  create and wire them.
- **Persistence across runs.** A concept learned in one run must survive into the
  next, or nothing accumulates. This is where the episodic-memory-as-named-input work
  from Phase 0 first earns its keep.

## 6. Exit criteria

- The system **notices** unrelatable objects rather than degrading silently.
- Capitals acquire concepts *and* links, with provenance recorded.
- `abc → abd; XYZ → ?` is solved — and, more tellingly, solved with the same rule and
  comparable temperature as `abc → abd; xyz → ?`.
- **Transfer, not memorisation:** having encountered some capitals, the system
  generalises to capitals it never encountered. This is the criterion that separates a
  real result from a lookup table, and it should be the headline measurement of the
  phase.
- The a↔A correspondence is discovered, not hardcoded — visible as a bridge with a
  slippage, not as a seeded link.
- All of the above **without any external input** beyond the problems themselves.
- a–z competence unregressed.

**A negative result is informative here, and is a live possibility.** The internal
mechanisms in §3 identify *units* well; whether they can supply *relations* is
genuinely uncertain. If capitals can only be acquired by effectively hand-authoring
their links, that is the finding: internal evidence is insufficient for wiring, and
the case for Phase 6's learning-by-asking becomes an argument from necessity rather
than ambition. Phase 3's tokeniser and Phase 2's backward pass would both need
rethinking before being built on top.

## 7. Open questions

1. **Which mechanism carries the weight** (§3) — frequency accumulation, utility, or
   episodic accumulation, singly or combined.
2. **What supplies the links** (§3) — the load-bearing question. Is participation
   history (which structures a candidate appeared in) sufficient evidence for a
   relation, or is relational structure fundamentally not recoverable from internal
   evidence alone?
3. **Where the frequency accumulator lives.** Sub-perceptual statistical layer,
   episodic memory, or new codelets — and if codelets, how a statistical process that
   spans runs fits a coderack that does not.
4. **Conceptual depth of a learned node.** Where does a new concept sit relative to
   the curated depths, and is depth learned or assigned?
5. **Link typing.** Can the system only create links of *existing* types (category,
   instance, property, lateral, sliplink), or must it eventually invent new relation
   types? The latter is Phase 6; this phase stays within existing types and notes
   where that pinches.
6. **Merge/dedup.** What happens when the same concept is discovered twice.

## Glossary

| Term | Meaning |
|------|---------|
| **Sub-perceptual accumulator** | A statistical layer beneath the coderack, counting across runs and proposing candidate concepts |
| **Frequency proposes, utility disposes** | Cheap counting generates candidates; participation in temperature-lowering structures decides which are kept |
| **Wiring** | Giving a new node links, without which it cannot participate in bonds, bridges, or rules |
| **Participation history** | The record of which structures a candidate appeared in — the leading internal source of evidence for links |
| **Provenance** | Marker distinguishing learned nodes/links from the innate seed ontology |
| **Transfer** | Generalising to untaught instances — the criterion separating learning from memorisation |
