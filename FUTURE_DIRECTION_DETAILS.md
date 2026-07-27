# Future Direction — Design Details

Living design notes for the "self-knowing Petacat" work sketched in
`FUTURE_DIRECTION.md`. Where that document poses four open questions, this one
records the concrete decisions, critiques, and mechanisms worked out in
conversation as we converge on a buildable plan.

This is a working document, not a spec. Sections marked **[decided]** are
choices we have committed to; **[leading proposal]** are recommendations not yet
ratified; **[open]** are questions still to resolve before planning. **§14 sorts
everything below into research phases** — read it as the map.

The through-line: threads 0 (self/other), 1 (generalised workspace), and 3
(learning by asking) are **not three features** — they are one mechanism seen
from three angles. The design below tries to make that literally true.

**The larger framing.** What this design amounts to is *a new attention-and-
completion architecture built on a Slipnet instead of a back-propagation neural
net.* The functional decomposition of a transformer is preserved but the
substrate is swapped:

| Transformer | This design |
|-------------|-------------|
| Context window of tokens | The ~2048-byte sliding window over the transcript (§2, §8) |
| Tokenizer (offline BPE, fixed vocab) | Emergent, hierarchical, utility-gated tokeniser (§4), growable at runtime |
| Attention (softmax over Q·K) | Salience / importance / unhappiness + spreading activation focusing codelets |
| Weights (frozen float matrices) | The Slipnet — an interpretable symbolic graph of nodes/links |
| Next-token completion (sample a softmax) | Emit slot (4) by rule-application / analogy (§11 Q1) |
| Training (gradient descent, backprop) | The `love`/`not-love` backward pass (§11) + consolidation (§9); trainable on a corpus via a deterministic nearness signal |
| Hardware: dense matmul saturating a GPU | Heterogeneous Apple-silicon execution — symbolic codelets across CPU cores, the numeric substrate on GPU cores, sharing unified memory (§12) |

The bet is that an *interpretable, online, self-watching, self-modifying* system
can occupy the same functional niche. The open risk is expressivity: backprop
over massive data finds representations no one designs; whether Slipnet
crystallisation can discover comparably rich structure is exactly what the
`local-llm`-as-teacher is there to bootstrap.

---

## 1. What plays the role of the "other" — [decided]

- **`me`** = Petacat's own processing and productions.
- **`not-me`** = the `local-llm` (an OpenAI-compatible chat endpoint at
  `127.0.0.1:1234/v1`).

`local-llm` is treated as a **swappable identifier for "the other mind."** The
specific model behind it will change over time and may eventually become several
LLMs, other Petacat instances, or a mix. The architecture must not assume a
particular model — only that there is *an other* on the far side of the channel.
For now: keep it simple and specific — one LLM, one other.

`me` and `not-me` become the **deepest nodes in the Slipnet** — deeper than
`object-category` (depth 90), per `FUTURE_DIRECTION.md` §0 ("deeper than any
existing concept"). They are joined to each other by a **sliplink of the
`opposite` family**, so that a `me`↔`not-me` slippage is possible using exactly
the machinery that already lets `leftmost` slip to `rightmost`.

## 2. The perceptual field is a dialogue transcript — [decided]

The workspace is **no longer four fixed strings**. It becomes a single,
**growing dialogue transcript**: interleaved *turns* from `me` (Petacat) and
`not-me` (the `local-llm`), perceived over time by the same analogy machinery.

- The ~2048-byte "large input" target is reinterpreted: it bounds the **window of
  attention**, not one giant analogy string. The classic Copycat skeleton is
  *preserved* — the workspace still holds four slots forming one analogy
  `(1):(2)::(3):(4)` — but the transcript **scrolls through** those slots (see
  §8). The engine surgery is therefore small: same four slots, but they slide, and
  slot (4) is *emitted* rather than derived-and-displayed.
- Behind the window is an **append-only raw history** of all turns. For now it is
  stored but **cannot be recalled**; recall is future work. Learning happens not
  by recall but by *consolidation* into the Slipnet (see §9).
- **Deterministic labelling by origin:** every byte the system *receives* is
  labelled `not-me`; every byte the system *emits* is labelled `me`. No
  heuristic guesses origin — the harness knows who produced each byte.

Why a transcript and not four labelled strings: me/not-me labels only do
cognitive work when the two kinds of element sit **adjacent in one perceivable
field** and the system must build bridges *across* the self/other boundary. In a
four-string layout, "not-me" would collapse into "you're in the input string" —
positional, trivial, inert. In a transcript, `me` and `not-me` chunks are
neighbours, and bridging them is the whole point.

Theory of mind, in this framing, is **speaker-attribution plus bridging**:
perceiving that the other's contribution mirrors, answers, or diverges from the
system's own.

## 3. me/not-me grounding and the projection/ingestion codelet — [decided]

The self/other distinction is not just a pair of labels; it is made *active* by a
new codelet family that attaches the **opposite** label to an element that
already carries one. Both labels may co-exist on a single element.

- **Projection** — an element labelled `me` gains an additional `not-me` label.
  The system hypothesises that the other shares this state.
  *"I notice I'm stuck → perhaps the other is stuck too."*
- **Ingestion** — an element labelled `not-me` gains an additional `me` label.
  The system adopts the other's structure as its own.
  *"The other used rule R → let me perceive R as mine."*

A **dual-labelled** element (`me` *and* `not-me`) is the concrete site of the
"recognition" qualia §0 gestures at: the moment the pattern in the other is felt
to mirror the pattern in the self. This codelet family is the operational form of
the `me`↔`not-me` sliplink — slippage as an act rather than a static link.

**[open]** What triggers projection/ingestion? Candidates: thematic pressure when
a me/not-me theme becomes dominant; a spike in curiosity; a snag on the `me`
side prompting a projection to check the `not-me` side. **[open]** Is the extra
label a `Description` added to the object, and does it participate in salience /
strength like other descriptions?

## 4. The emergent tokenizer — [leading proposal]

Something must turn a flat byte stream into perceivable units. The original
proposal was: accumulate byte-sequence frequencies and crystallise frequent
sequences into Slipnet "token" nodes, dynamically, as the system runs. The
critique reshaped this into a **two-level, utility-gated** design that fits
Petacat's native machinery:

- **Level 1 — Groups (ephemeral, per-run).** Copycat *already* has emergent
  chunking: a group is "adjacent atoms bonded and treated as a single
  higher-level object." Byte chunking should reuse this, not reinvent it.
- **Level 2 — Crystallised token-nodes (persistent, cross-run).** A group
  *pattern* that recurs across runs **and earns its keep** is promoted into a
  permanent Slipnet concept — a learned "Platonic chunk," the true analogue of a
  BPE merge, but grounded in Petacat.

**Promotion is gated by analogical utility, not raw frequency.** Frequency is an
LLM heuristic borrowed from a setting (giant corpus, offline) we do not have.
Petacat has a better signal: did this chunk participate in bonds, bridges, and
rules that actually lowered temperature? A frequent-but-useless byte-pair is a
worse token than a rare-but-pivotal one.

Tokenisation is **also forced on us by scale** (see §6): it is the attention /
compression mechanism that makes a large transcript tractable, so it must be
**hierarchical / recursive** (bytes → tokens → phrases), matching §1's "composite
atoms, multiple layers simultaneously."

### 4a. Why not raw bytes as atoms — [decided rationale]

Copycat's power comes from atoms living in a **small, totally-ordered,
richly-related** space. Raw bytes break this: successor-over-bytes is mostly
semantic noise (`'z'`=122, `'A'`=65, `' '`=32), sameness only fires on exact byte
equality, and UTF-8 fragments a single character across 1–4 atoms. Bytes do not
expand the perceptual space — they **dilute** the structure the engine runs on.
Tokenisation's first job is to *rebuild* the relational structure that dropping
to bytes threw away. **[open]** Preserve a–z (and their curated links) as
pre-seeded tokens so existing letter-string competence does not regress.

## 5. Wiring new tokens — the teacher relationship returns — [leading proposal]

A crystallised token has an *identity* but no **links**, and §0's own criterion is
that a concept must "participate in slippages and bridges and rules the way
`successor` does" — which it can only do through links. So the hard part is not
*creating* token nodes, it is *wiring* them.

This is where the "other" re-enters at the perceptual level: when the system
forms a chunk it cannot relate to anything, **curiosity rises** (§3) and it asks
the `local-llm` *"what is this like?"* The answer is perceived through the same
machinery and its emergent bonds/bridges become the new token's links. So the
earlier mirror-vs-teacher question is not dead — it sits **downstream** of the
tokenizer: the teacher is *how emergent tokens get their links.*

## 6. Hard constraints to design around — [decided]

- **Scale.** Copycat is roughly O(objects²) in bridges/salience and was built for
  ~3–7 atoms. A flat 2048-byte string is both computationally infeasible and
  cognitively wrong. Hierarchical tokenisation is *required*, not optional, to
  keep the number of simultaneously-perceived objects small. Tokenisation attacks
  the exponent; **parallel execution (§12) attacks the constant** — they are
  complementary, and neither alone is sufficient.
- **Cold start.** One transcript is far too little data for frequency to discover
  good tokens. "Emergent over time" must mean **across runs**, accumulated in
  Episodic Memory. Tokens are a **long-term learned asset**, which ties the
  tokenizer to the learning/evolution loop (§2).
- **Determinism.** Petacat is deterministic given a seed; the `local-llm` is not
  (and will be swapped). For a "deterministic harness" to hold, every LLM call
  must be **journaled and record-replayed** so any run reproduces exactly.
  Parallel execution (§12) threatens determinism from a *second* direction —
  nondeterministic interleaving — and must be designed against just as carefully.

## 7. How the threads become one mechanism

- **§0 self/other** — `me`/`not-me` as deepest Slipnet nodes; projection/ingestion
  as the sliplink-in-action.
- **§1 generalised workspace** — the dialogue transcript + hierarchical emergent
  tokeniser.
- **§3 learning by asking** — curiosity on un-linkable tokens; the teacher wires
  them; understanding the answer is itself a perceptual pass.
- **§2 self-tuning** — the deterministic harness that runs many transcripts,
  scores them, and (eventually) evolves configuration; also what accumulates the
  cross-run token vocabulary.

Perception, analogy-making, concept acquisition, and self/other recognition are
the **same process** applied to different objects at different levels.

---

## 8. The turn recurrence — the sliding 4-slot window — [decided]

The Copycat skeleton is preserved: the workspace always holds four implicit slots
forming one analogy —

    (1) is to (2)   as   (3) is to (4)

(1), (2), (3) are given; **(4) is the turn Petacat must produce.** The
append-only transcript scrolls *through* these four slots.

- **Bootstrap.** The `local-llm` opens by emitting a **three-word statement**;
  its words (as letters) seed slots (1), (2), (3). Petacat produces (4) — a
  response of *any* length (no byte limit).
- **Exchange.** (4) is sent to the `local-llm`, which replies (5) under the
  constraints of its system prompt.
- **Reconfigure (the recurrence).** The window slides:
  `(1)+(2)+(3) → (1′)`, `(4) → (2′)`, `(5) → (3′)`, Petacat generates `(4′)`.
  Then again, forever.

**Semantics.** The top pair `(1′→2′)` is *Petacat's own previous behaviour*
(prior context → the response it gave); the bottom pair `(3′→4′)` is (the other's
newest input → Petacat's next response). Each turn Petacat extracts the rule of
*its own last turn* and applies it, by analogy, to what the other just said.
Continuity of self is literally an analogy to one's own past.

**The degenerate fixed point.** Because the top pair is Petacat's own last turn, a
trivial turn breeds trivial turns: if (4) is blank, the rule becomes "produce
blank," and the system can lock into silence. Two things break the attractor:
(a) the novelty the `local-llm` injects as (5)/(3′), which Petacat can *ingest*;
(b) snags / jootsing / curiosity forcing exploration. This makes the "other"
essential to development and makes blank-emission (§10) load-bearing, not
cosmetic — the system *learns to speak by learning to perceive*, early utterances
near-blank and richening as vocabulary grows (the §0 infant/adult arc, for free).

## 9. Lifelong learning: consolidation and self-construction — [decided direction]

There is **no end** to the conversation; the goal is a system that **learns
forever.** Attention stays on the bounded window; learning happens by
*consolidating* the passing conversation into long-term structure.

- **Raw history** — the byte stream of all turns is stored append-only; for now it
  **cannot be recalled** (recall is future work).
- **Consolidation** — periodically the current conversation is *instantiated in
  memory* as **Slipnet nodes and links** (and, later, codelets). This is
  crystallisation (§4) generalised beyond tokens to arbitrary learned structure.
  It is the "training" of this architecture (see framing table).
- **The learning signal is self-watching.** Themes, the Temporal Trace, and
  coderack activity are mined for regularities; those that recur *and* prove
  useful are **reified**:
  - recurrent dominant **themes** → new nodes / links;
  - recurrent **trace** event-patterns → new posting-rules / attention habits;
  - productive **codelet** activity → the fitness signal for codelet-level change.
- **Staging (important).** Reifying *data* (nodes, links, posting-rules) is safe
  and native to the DB-driven design — new knowledge is just new rows. Reifying
  *code* (self-constructed codelets) is program synthesis that can corrupt the
  workspace, so it is **explicitly deferred** behind a safety boundary. Data-level
  growth now; code-level growth later.

Hard resets to "start from scratch" remain a development affordance throughout.

## 10. Flagged sub-problems — [open]

- **Blank-space / cold-start emission.** Petacat must emit *something* before it
  has learned anything — the minimal me-turn is a single space. This is the
  emission analogue of "I don't know yet," and the base case that keeps the
  recurrence from stalling (§8). What is the minimal viable me-turn, and how is it
  produced with no rule in hand?
- **The `local-llm` system prompt.** The other's behaviour is shaped entirely by
  its system prompt. It must be a *good other*: responsive enough to be
  analogisable, simple enough not to drown Petacat, and ideally **scaffolding** —
  starting small and enriching as Petacat can handle more (curriculum via prompt).

## 11. Completion, the harness, and the valence axis (love / not-love) — [decided]

**Completion is pure rule-application.** Slot (4) is produced by applying the
`(1′→2′)` rule to `(3′)`; no LLM in the decode path. Grounding: Hofstadter's claim
that *all* cognition is perception and analogy-making, so a system built purely
from those two operations is what we build and train. A corollary is that the
architecture is inherently **multi-modal-ready** — any percept, not just text, can
enter the same workspace. Other modalities are a deferred future path; near-term
focus is text-completion-by-stochastic-analogy.

**The harness is a shuttle plus a valence injector.** At first it only
orchestrates send/receive between Petacat and its `not-me` (`local-llm`). Its
second job is to deliver the fitness signal, below.

**Love / not-love — a separate valence mechanism — [decided].** By deliberate
design choice (a philosophical stance we want), valence is *not* modelled as
percepts inside the workspace. It is a **separate perceptual mechanism** that
reads an external `love`/`not-love` signal and couples to the rest of the system
in two ways:

- **(A) Global, undirected plasticity modulation.** A `love` signal gives
  *everything* in Petacat a small boost toward **permanence** (lower decay /
  higher strength-floor); `not-love` gives everything a small nerf toward
  **impermanence**. Uniform — *no credit assignment* — the "how sticky is this
  moment" neuromodulator (dopamine-like).
- **(B) A structural backward pass.** A `love` signal triggers a
  **memory-formation codelet**: read the *whole context*, follow the *deepest
  activated paths* in the workspace, and **reify that path as a new Slipnet
  concept** (a "memory"), linked to the nodes it was abstracted from. The
  activation pattern is the gradient; the new concept is the weight update. A
  `not-love` signal triggers the dual — a **forgetting codelet** that finds a
  *learned* concept on the deepest activated paths and weakens or removes it.

Because a love-born concept is linked to its constituent path by construction, **B
absorbs the old token-wiring problem (§5)** — new concepts are not inert islands.

**Homeostasis and safety are now requirements.** `love` grows the Slipnet,
`not-love` prunes it, so their rates must balance and near-duplicate concepts must
**merge**; and only **learned** concepts are removable — the innate seed ontology
(a–z, the relations, `me`/`not-me`) is protected from `not-love`, or the system can
lobotomise itself. B (love-gated, one-shot, supervised) and the frequency
tokeniser (§4, unsupervised) are **complementary** and both kept.

**What B may create — the goal is (c), approached in stages — [decided].** The
**goal** is the most expressive form: B may create not only new nodes and new
links but **new relation types** — genuine *ontology bootstrap*, a system that can
invent relational primitives it was not born with, and in principle rediscover
structures like the alphabet on its own. That is the endgame we build toward. It
will be *reached in stages*, because (c) is a research problem of its own (what a
new relation *is* operationally, how bonds/bridges/rules consume it) and carries
the most risk: **(a)** new nodes (compositions of existing concepts) → **(b)**
+ new links between existing nodes (the graph topology learns) → **(c)** + new
relation types. Early phases ship (a)/(b); (c) remains the north star.

**Who triggers it.** The **harness** (Claude Code or a human now, learned criteria
later) and the **`local-llm`** (social approval). This resolves the old
"fitness / Claude's role" question: the guider's role *is* to deliver love.

**Corpus mode — deterministic, LLM-free fast training — [decided direction].**
Because valence is an externally-supplied signal, it can be driven by a **corpus**
instead of the slow `local-llm`: draw the `not-me` turns from real text, let
Petacat emit (4), and set the `love`/`not-love` **strength** deterministically from
a *graded* **nearness/distance function** between (4) and the corpus's actual next
segment. This turns the system into a trainable **completion mechanism** with a
dense, deterministic signal — ideal for rapid testing, for bootstrapping the
vocabulary, and as the quantitative **fitness metric** for evolutionary tuning
(§2). Pipeline: *corpus pre-training → graduate to live `local-llm` dialogue.*

## 12. Execution substrate: Apple silicon and true parallelism — [decided constraint]

**The constraint.** Petacat targets **Apple M-series silicon only.** No portability
budget is spent on x86, CUDA, or Linux GPUs. The implementation must achieve **true
parallelism**: codelets executing simultaneously across multiple **CPU cores**, and
the system's numeric work executing on the **GPU cores**.

**Why this is principled and not arbitrary.** Apple silicon's **unified memory
architecture (UMA)** lets CPU and GPU address the same physical memory with no
copy. That is the enabling property, not a convenience. This design needs a
*fine-grained* handoff — the workspace's numeric substrate is touched every update
cycle (~15 codelets), on state that symbolic codelets mutate in between. On a
discrete GPU that round-trip would be dominated by bus transfer and the whole idea
would be a loss. On M-series the codelets and the kernels read the same buffers.
The single-vendor constraint buys a capability that is genuinely unavailable
elsewhere at this granularity.

**Where the current code stands (measured, not assumed).**

- `server/engine/runner.py` — `step_mcat()` runs **exactly one codelet**. There is
  no seam for concurrency; the parallelism boundary has to be introduced.
- `server/engine/rng.py` — a **single shared `random.Random`** with a mutating call
  counter, documented as "the single source of all non-determinism in the engine."
  Under threads this is simultaneously a data race and a reproducibility break. It
  must become **splittable / counter-based per-codelet streams**, seeded
  deterministically from `(run_seed, wave_index, slot_index)`.
- `server/engine/codelet_dsl/interpreter.py` — each codelet `exec()`s into a fresh
  namespace, so codelet *code* is already isolated; all contention lives in the
  shared-state mutations inside `codelet_dsl/builtins.py`. **That file is the
  concurrency boundary**, which is fortunate: it is one place, not scattered.
- **Docker is the immediate casualty.** The engine runs today in a
  `python:3.12-slim` Linux container. Docker Desktop's Linux VM does not expose
  Metal to containers, and CPython 3.12 holds the GIL — the current deployment
  target forecloses *both* halves of this constraint. **The engine must run
  natively on macOS.** Postgres, the client, and the API surface may stay
  containerised; the hot loop moves to the host.

### 12a. What can and cannot go on the GPU — [decided]

Codelets **cannot** run on GPU cores, and no amount of engineering changes this.
They are branchy, pointer-chasing, allocating, data-dependent symbolic agents that
`exec()` interpreted source. GPU cores are SIMT — thousands of lanes executing the
same instruction over different data. The two are categorically mismatched. Stating
this plainly matters, because the honest reading of "codelets use the GPU" is a
**split by kind of work**, and that split is the real design:

| Layer | Runs on | Character |
|-------|---------|-----------|
| **Symbolic agents** — scouts, evaluators, builders, breakers, jootsers, projection/ingestion | **CPU** (P- and E-cores), truly concurrent | Irregular, branchy, mutating a shared object graph |
| **Numeric substrate** — the system's "physics" | **GPU** (Metal / MLX) | Regular, dense or sparse-but-structured, homogeneous |

What is genuinely GPU-shaped in this architecture:

- **Slipnet activation spreading** — sparse mat-vec over the node/link graph.
  Negligible today (59 nodes, 226 links) but §4 crystallisation and §9
  consolidation are explicitly *designed to grow it*, plausibly to 10⁴–10⁶ nodes.
  This kernel is written for the Slipnet we are building, not the one we have.
- **Candidate scoring over O(n²) object pairs** — the bond/bridge proposal space.
  This is the single largest win: it is exactly the cost that makes §6's larger
  window infeasible, and it is embarrassingly parallel and homogeneous.
- **Salience / importance / unhappiness** recomputed over all objects — elementwise.
- **Themespace intra- and inter-cluster dynamics** — small dense matrices.
- **Temperature** — a reduction over structure strengths.
- **Corpus-mode distance function (§11)** — scored every turn, trivially batched.
- **"Deepest activated paths" (§11B)** — frontier expansion over the Slipnet, i.e.
  a BFS/SSSP-shaped traversal, which maps well to GPU graph kernels.

**The larger near-term GPU win is population parallelism.** A single run's Slipnet
is far too small to saturate a GPU, and we should not pretend otherwise. But §2
(evolutionary tuning) and §11 (corpus-mode training) both need **many runs**.
Batching K independent runs turns a tiny mat-vec into a fat *batched* matmul the
GPU is actually built for. Expect population/corpus batching to pay before
single-run acceleration does.

**Contention with the other.** The `local-llm` almost certainly occupies the same
GPU. Petacat's kernels and the other's inference compete for one piece of silicon,
and that contention is worst exactly during live dialogue. This is a further
argument for **corpus mode (§11)** as the primary training path: it is both
LLM-free and GPU-uncontended.

**[open]** Framework choice for the numeric layer: **MLX** (Apple's array
framework — Python-native, lazy, unified-memory-aware, and by far the lowest
friction) for everything expressible as array ops, with hand-written **Metal**
compute kernels reserved for the irregular traversals MLX cannot express well.

### 12b. What parallelism does to the model — the goal is free-running — [decided]

This is not merely an implementation concern; it changes the system's semantics.
MetaCat's coderack selects **one codelet at a time**, and Hofstadter was explicit
that the "parallel terraced scan" is a *probabilistic approximation* of parallelism
forced by serial hardware. So there is a defensible reading in which **true
parallelism removes a hardware artifact rather than a theoretical commitment** —
this design is arguably closer to the original vision than the original
implementation was.

**The goal is to get as close to free-running threads as possible** — codelets
executing continuously and independently, with no global barrier, the coderack
sharded across cores. That is the north star, and reaching it will likely require
**reconceptualising how codelets work**, not merely wrapping the existing ones in
locks. The long-term answer is expected to be a **mix of techniques**, applied to
different parts of the system, relaxed progressively across the research phases
(§13). Bulk-synchronous waves are the *first* step on that path, not the
destination.

The obstacle is shared mutable state: concurrent codelets read **stale state**, two
builders may build conflicting structures, a breaker may destroy what a builder is
mid-way through evaluating. The ladder of relaxation, loosest synchronisation last:

- **(i) Serial semantics, parallel substrate.** Codelets still run one at a time;
  only the numeric work inside each cycle goes wide. Bit-identical to today, and it
  already captures the O(n²) win. *Taken regardless* — the floor, not an option.
- **(ii) Bulk-synchronous waves.** W codelets run **genuinely concurrently**, then a
  barrier resolves conflicts and commits in a **deterministic order** (by slot
  index, never by completion order), then the update cycle runs. The existing update
  cycle is already a barrier every 15 codelets, so W ≈ `update_cycle_length` is a
  natural wave size and the surgery is structurally small. Reproducible from a seed;
  dynamics differ from serial because codelets act on stale state.
- **(iii) Region-partitioned execution.** Codelets claim disjoint regions of the
  workspace and run without a barrier when regions do not overlap. Copycat codelets
  are already extraordinarily *local* — a bond scout touches two adjacent objects —
  so disjointness is the common case, not the exception.
- **(iv) Optimistic / transactional execution.** A codelet runs speculatively,
  recording a read-set and a write-set, and commits only if nothing it read has
  changed. Barrier-free; contention is resolved per-structure rather than globally.
- **(v) Free-running.** Continuous execution, sharded coderack with work-stealing,
  no global barrier at all. **The goal.**

**Why Copycat is unusually well-suited to this.** Two properties of the existing
architecture do most of the work for us:

- **Conflict → fizzle is semantically free.** `fizzle` is already a native,
  meaningful codelet outcome: a codelet that finds its object gone or its structure
  too weak simply does nothing. A codelet that *loses a race* can fizzle for exactly
  the same reason, and nothing in the model needs a new concept to describe it.
  Under contention the fizzle rate rises — which reads, correctly, as *the workspace
  being busy*. Most concurrency designs must invent a failure mode; this one
  inherits an apt one.
- **The proposal lifecycle is already a staged commit.** `%proposed%` →
  `%evaluated%` → `%built%` is a two-phase commit protocol wearing cognitive
  clothing. Reconceptualising codelets as *pure read-phase plus a proposed delta*,
  with application separated from computation, is far less violent to the design
  than it would be in most systems — it makes explicit a structure that is already
  there.

**Reproducibility survives — by replay, not by schedule.** The objection to
free-running is that §11 corpus training and §2 evolution need reproducible runs.
But reproducibility does not require the *schedule* to be predictable, only
**recordable**: journal the actual commit order and a run replays exactly. §6
already commits to journaling `local-llm` calls for the same reason; the commit log
is the same mechanism extended to the scheduler. The honest cost is not to validity
but to **sample efficiency** — a free-running run is one draw from a distribution,
so evolutionary fitness needs more runs per configuration to see through the
interleaving noise. Population parallelism (§12a) is exactly what pays for that,
which is a pleasing closure: the technique that makes free-running affordable to
evaluate is the same technique that makes the GPU worth using.

**Serial reference mode is retained permanently**, at every phase, for fidelity
cross-validation against Marshall's semantics: parallel Petacat and serial Petacat
should agree in distribution, and where they diverge we should know why.

**[open]** Runtime for the symbolic layer: **free-threaded CPython** (3.13
experimental, 3.14+ officially supported) keeps the codelet DSL in Python and thus
preserves the load-bearing property that *adding a codelet is a database change* —
which §9's self-constructed codelets depend on absolutely. The alternative, a
native core (Rust/Swift + Metal), is faster but must either embed an interpreter or
re-host the DSL, putting §9 at risk. Leaning free-threaded Python; the risk to
check is free-threading readiness of SQLAlchemy/asyncpg, mitigated by keeping the
engine a **pure in-memory core with the database strictly at the boundary** —
close to how it is already structured.

## 13. Persistence modes and the database boundary — Phase 0 — [decided]

A **technical phase, foundational, and permanent**: it introduces no new cognition,
but every subsequent phase runs inside the structure it establishes. Phase 3's
corpus training and Phase 6's evolutionary tuning need to discard thousands of runs
per hour; Phase 5 needs to keep a conversation; debugging any of them needs total
recall. Those are three different persistence regimes over **one engine**.

### 13a. Where the database actually is — assessment of the current code

**The headline: the engine is already database-free.** All 19 modules of
`server/engine/` (~14.6k LOC) contain **zero** SQLAlchemy imports, zero session
handling, and zero `await`ed I/O. `EngineRunner(meta)` plus
`MetadataProvider.from_seed_data(seed_dir)` runs a complete problem with no
Postgres, no Docker, and no FastAPI — this is what `smoke_test.py` already does and
what ~100 unit and module tests already rely on. The measurements below were taken
on a checkout where **SQLAlchemy is not installed at all**, and the engine ran fine.

Phase 0 is therefore **not a rewrite**. It is making an existing property
*explicit, enforced, and switchable* rather than incidental.

The database boundary is confined to eight files:

| Module | Role at the boundary |
|--------|----------------------|
| `server/db.py` | Async engine + session factory |
| `server/main.py` | Lifespan: `create_all`, JSON→DB seeding, help-topic sync |
| `server/services/run_service.py` | **The only writer of run state** |
| `server/services/snapshot_service.py` | State serializers + `save_cycle_snapshot` |
| `server/services/metadata_service.py` | DB → `MetadataProvider` |
| `server/models/{run,metadata}.py` | ORM definitions |
| `server/api/{runs,admin,memory,docs}.py` | 74 endpoints taking `Depends(get_session)` |

Notably `server/api/controls.py` and `server/api/ws.py` take **no session at all** —
breakpoints, clamping, and threshold control are already pure in-memory operations.

**Exactly three things write during a run**, all in `run_service.py`:

1. `_persist_new_trace_events` — checked **after every codelet**;
2. `_persist_answer` — on an answer;
3. `save_cycle_snapshot` — **every 15 codelets** (`update_cycle_length`), plus on
   create and reset; followed by an `update(Run)` and a `commit()` per API call.

**Measured cost** (this machine, engine-only, no DB attached):

| Problem (seed) | Codelets | Engine wall | Rate | Trace rows | Snapshots | JSONB written |
|---|---|---|---|---|---|---|
| `abc→abd; xyz?` (7) | 551 | 28 ms | 19,300/s | 52 | 36 | ~2.7 MB |
| `abc→abd; xyz?` (42) | 1,356 | 74 ms | 18,300/s | 93 | 90 | ~12.2 MB |
| `abc→abd; mrrjjj?` (42) | 2,484 | 225 ms | 11,000/s | 161 | 165 | ~45.3 MB |

Metadata loads from JSON in **4 ms**. And the decisive number: serialising **one**
snapshot costs **2.46 ms** of CPU, so the 165 snapshots of the `mrrjjj` run cost
**~405 ms — roughly 180% of the engine's own 225 ms of thinking — before a single
byte reaches Postgres.** Persistence is not a tax on this system; it is the
majority of it. (`run_to_completion` adds a further `await asyncio.sleep(0)` per
codelet, ~16 µs, another ~40 ms on that run.)

**Three defects the assessment turned up**, each of which Phase 0 should fix rather
than inherit:

- **Snapshots are write-only.** `restore_slipnet_state`, `restore_trace_state`,
  `restore_runner_state`, and `restore_rng_state` are defined in
  `snapshot_service.py` and **called from nowhere**; there is no
  `restore_coderack_state` or `restore_workspace_state` *at all*. Meanwhile the
  snapshot payload is **88% coderack**, 5% themespace, 3% slipnet, and only 2%
  workspace. The single largest cost in the system is writing a blob that no code
  path can read back. `prune_old_snapshots(keep_n=10)` is likewise never called, so
  the rows accumulate without bound.
- **Episodic memory is a process-global singleton — a latent coupling, not a bug
  today.** `run_service.py:33` holds one `EpisodicMemory()` shared by every run.
  Cross-run sharing is *correct by design*: reminding is a core MetaCat feature and
  `engine/memory.py` says so explicitly ("scoped to the user/session, not to
  individual runs"). The engine already does the right thing — `init_mcat(memory=…)`
  takes it as an injected dependency; only the service layer hardcodes one instance.
  And today it cannot perturb cognition: `find_remindings` is called once, inside
  `report_answer`, *after* the answer exists, and its only effect is
  `emit_reminding` into the commentary log — it consumes no RNG, touches no
  structure, and cannot alter a run's trajectory. What is true today is narrower:
  a run's **commentary** depends on which runs preceded it in the process, and
  `AnswerDescription._next_id` / `SnagDescription._next_id` are class-level counters
  so even the IDs carry process history. Both are output-level, not cognition-level.
  The concern is prospective: §4/§6 put the **cross-run token vocabulary** in
  Episodic Memory, §9 consolidates into long-term structure, and §11B writes
  love-born concepts — at which point memory *does* feed perception, and shared
  mutable memory becomes both a reproducibility break and, under Phase 1's
  concurrent runs, a genuine race. The fix is not to make memory per-run — that
  would delete reminding — but to make it a **named, versioned input** to a run.
  (`rehydrate_memory` also appends without clearing, so it is not idempotent; it is
  called once at startup today.)
- **Pure serializers are welded to the ORM.** `snapshot_service.py` mixes
  side-effect-free serialization functions with SQLAlchemy imports, so *reading*
  engine state requires importing the database layer. This was hit directly while
  measuring: the pure functions had to be extracted textually to be called at all.

### 13b. The three modes — [decided]

Persistence mode is a property **of a run**, chosen at creation — not a global
setting — because the harness (§11) will legitimately want a Fast corpus-training
population and a Normal live dialogue in the same process.

| | **Fast Run** | **Normal** | **Audit** |
|---|---|---|---|
| **Purpose** | Rapid iterative testing; runs are discarded | Ordinary operation; human-inspectable, reproducible | Production audit trail; total verification |
| **Unit of persistence** | **none, ever** | **the turn** (§8) | **the tick** |
| **When it writes** | never | at turn end, once the workspace has finished responding | continuously, *as it runs* |
| **Writes** | nothing | turn start state (incl. RNG state), turn end state, the emitted response, valence, answers/snags | every codelet, every structure transition, every activation update, every valence event |
| **DB attached** | **no** | yes | yes |
| **Execution** | full parallelism | full parallelism | **serial — no parallelism, no batching** |
| **Expected cost** | full engine rate (11k–19k codelets/s today) | one transaction per turn | extremely slow, by design |

**Fast Run stores nothing in the database at any point — including at the end of the
run.** There is no final flush, no summary row, no answer record. The run happens
and is gone; whatever the caller wants it must read from memory while the run is
live or as a returned value. This is stricter than "batched" or "deferred," and the
strictness is the point: the mode is defined by the *absence of a database
connection*, not by write-frequency tuning. Phases 3, 4, and 6 live here — corpus
training and evolutionary populations — and on today's numbers simply not
snapshotting is a ~2.8× speedup before any parallelism is applied.

**Normal records start and end state per turn — nothing in between.** The turn is
the natural transaction: it is the unit the recurrence (§8) advances by and the unit
valence (§11) is delivered against. Reproducibility here is **by re-execution, not
by replay**: recording the RNG state at turn start alongside the config-hash means
the turn can be re-run to the same end state, without a journal of what happened
between. Mid-run detail is deliberately not kept — that is Audit's job. This makes
Normal cheap enough to be the everyday mode while remaining genuinely inspectable.

**Audit writes everything, every tick, as it runs — serially, unbatched, and very
slowly.** It is the production-grade verification mode: the record must be complete
and *contemporaneous*, so no batching may defer a write past the tick that caused
it, and no parallelism may make the ordering ambiguous. Slowness is an accepted
consequence, not a defect to be optimised away.

**Audit mode and §12b's serial reference mode are the same thing** — a serial,
fully-recorded execution is exactly the artefact needed for fidelity
cross-validation against Marshall's semantics. Building one satisfies both.

**The limitation to state plainly:** because Audit removes concurrency, it cannot
reproduce concurrency-dependent behaviour. A defect that only manifests under
free-running (§12b (v)) will not appear in Audit. So Audit is *not* the debugging
tool for parallelism, and §12b's **commit journal remains a separate mechanism** —
Audit answers "what did the system do, tick by tick," while the commit journal
answers "in what order did concurrent codelets land." Both are needed; neither
substitutes for the other.

### 13b-i. Review UX — a Phase 0 deliverable

Normal and Audit exist to be *looked at*, and today nothing looks at them: the
persisted rows have no reader (§13a). Phase 0 must therefore ship the review
surfaces alongside the writers, or it will repeat the write-only mistake it was
convened to fix. Two distinct surfaces, because the two modes answer different
questions:

- **Normal review** — a run/turn browser: list runs, open a run, step through its
  turns, and see start state → emitted response → end state, with the valence signal
  and any answers or snags. Comparative, coarse-grained, and fast to scan. This is
  the everyday window into what the system has been doing.
- **Audit review** — a tick-level inspector: scrub through a single run's timeline,
  and at any tick see the codelet that ran, the structures that changed, and the
  activation and temperature state at that instant. Deep, narrow, and slow to
  produce — the tool used when a specific run must be explained.

Both build on the existing client (`WorkspaceView`, `SlipnetView`, `TraceView`,
`ThemespaceView`) rendering *recorded* state rather than live state — the same
components pointed at a different source. **[open]** How far the live views can be
reused unchanged versus needing a recorded-state variant.

### 13c. The mechanism: one code path, three sinks — [decided]

The three modes must be **the same code path with a different sink**, never three
code paths. Concretely, a `RunSink` port with methods the engine calls at defined
moments (`on_run_created`, `on_codelet`, `on_trace_event`, `on_structure_change`,
`on_turn_end`, `on_answer`, `on_valence`), and three implementations: a null sink,
a batching sink, and an audit sink.

Four rules make this hold up:

- **The engine never learns its mode.** No `if mode == "fast"` anywhere in
  `server/engine/`. The moment mode becomes a conditional inside the engine, the
  modes drift and Fast stops being a faithful preview of Normal.
- **Serialisation happens *inside* the sink, lazily.** Sink methods receive the live
  context, not a pre-built payload. If the null sink received an already-serialised
  snapshot, Fast mode would still pay the 2.46 ms — the entire point would be lost.
- **Mode must not change results.** Same seed, same mode-independent inputs → the
  same codelet count, temperature, and answer in all three modes. This is the
  **acceptance test for Phase 0**, and it is cheap to run continuously.
- **The DB-free property becomes an enforced invariant.** A test that fails if
  anything under `server/engine/**` imports SQLAlchemy. It is true today by
  discipline; Phase 0 makes it true by construction, and every later phase inherits
  the guarantee.

### 13d. Consequences — [decided]

- **Mid-run snapshots are retired, not repaired.** The 15-codelet cycle snapshot is
  write-only dead weight (§13a) and no mode needs it: Fast writes nothing, Normal
  needs only turn boundaries, and Audit records every tick anyway. Deleting it
  removes the largest write in the system. Resume-mid-run, if ever wanted, comes
  from re-execution or from the Audit record — not from a 45 MB blob nothing reads.
- **Reproducibility is by re-execution.** A turn re-runs to the same end state from
  **(RNG state at turn start, config-hash, memory-hash)**. No journal is required
  for Normal; §12b's commit journal is a separate mechanism serving concurrency, not
  this.
- **Metadata gets a config-hash.** Re-execution is only valid against identical
  configuration, and §2's evolution deliberately varies it. Every run records the
  hash of the `MetadataProvider` it ran under.
- **Episodic memory becomes a named, versioned input** — an explicit argument at run
  creation with a recorded `memory-hash`, not a module global. Sharing stays
  available (reminding depends on it); what changes is that *which* memory a run saw
  becomes part of the run's identity, and an isolated or empty memory becomes
  selectable. Fast Run defaults to an ephemeral in-process memory, since it must not
  contaminate anything that outlives it.
- **Serializers split from the ORM** — a pure `serialization` module with no
  database imports, and a separate repository module that persists what it produces.
- **The API keeps working in every mode.** `controls.py` and `ws.py` are already
  session-free, so live inspection of a Fast run costs nothing extra — Fast means
  *not written down*, not *not observable*.

## 14. Research phases — [leading proposal]

Everything above is sorted here into phases. This is a **research** programme, not
a delivery schedule: each phase is a *runnable system* that answers a question we
cannot currently answer, and a phase ends when its question is answered — not when
a feature list is exhausted. A negative result is a valid exit.

Two rules hold across all phases. **Every phase ships a runnable system** — no
phase is pure infrastructure whose value is deferred. And **every phase preserves
serial reference mode** (§12b) and the existing letter-string competence as a
regression suite; if a phase makes `abc→abd; xyz→?` worse, that is a finding, not
an acceptable cost.

Parallelism is not a phase. It is a **dimension that advances in every phase**,
climbing the §12b ladder toward free-running.

| Phase | Question it answers | Draws on | Parallelism rung (§12b) |
|-------|--------------------|----------|------------------------|
| **0. Persistence modes** | Can one engine serve throwaway, kept, and audited runs? | §13 | (i) serial — unchanged; Audit stays serial *forever* |
| **1. Parallel ground floor** | Can the engine go wide without changing what it perceives? | §12, §1, §6 | **(ii) bulk-synchronous waves** |
| **2. The turn** | Can Petacat take a turn — emit by pure analogy, forever? | §2, §8, §10, §11 (completion, harness) | (ii) waves, hardened |
| **3. Valence** | Is the system *trainable*? | §11 (A, B-stage-a, corpus mode) | (iii) region-partitioned |
| **4. Vocabulary** | Can it grow its own perceptual units, and stay tractable? | §4, §4a, §5 (persistence), §6 | (iv) optimistic / transactional |
| **5. The other** | Can it bridge the self/other boundary with a live other? | §3, §5, §10, §6 (replay) | **(v) free-running** + replay journal |
| **6. Ontology** | Can it invent structure it was not born with? | §9, §11 (B-stages-b/c), evolutionary tuning | (v) free-running, tuned by evolution |

### Phase 0 — Persistence modes

The `RunSink` port and its three implementations; Fast / Normal / Audit selectable
per run; **the Normal and Audit review UX** (§13b-i); serializers split from the
ORM; episodic memory as a named versioned input; the config-hash; the
engine-imports-no-SQLAlchemy invariant test; and the retirement of write-only
snapshots.

*Proves:* that one engine can serve three persistence regimes without three code
paths. *Exit:* identical cognition across all three modes from the same seed; Fast
Run demonstrably opening **no database connection at all**; Normal turns
re-executing to their recorded end state; Audit reconstructing a run tick by tick in
its inspector. Purely technical, no new cognition, and **permanent**: every later
phase runs inside this structure, and Audit doubles as the serial reference mode
that Phase 1 onward validates against.

### Phase 1 — Parallel ground floor

Native macOS execution (off Docker; Postgres and client may stay containerised);
splittable per-codelet RNG streams replacing the shared generator; the commit
journal; GPU numeric substrate v1 — pair-scoring and activation spreading;
**bulk-synchronous waves**; and, as a data change, the `me`/`not-me` nodes seeded
at maximum depth with their `opposite` sliplink.

*Proves:* that concurrency and the deepest-node addition leave perception intact.
Everything here is measurable against the **existing** problem suite, with no new
cognition to evaluate — which is exactly why it goes first. *Exit:* the demo suite
passes at parity with serial, and wall-clock on the largest problems improves.

### Phase 2 — The turn

The transcript workspace with deterministic origin labelling; the sliding 4-slot
recurrence; completion as pure rule-application; blank/minimal emission; the
harness as a bare shuttle; append-only raw history.

*Proves:* that the recurrence runs forever without stalling, and that slot (4) can
be produced by analogy alone. *Exit:* N turns without deadlock or collapse into the
degenerate fixed point — or a clear characterisation of why it collapses, which is
equally informative. **This is the first phase with a genuine risk of a negative
result**, and it should be run before anything is built on top of it.

### Phase 3 — Valence

Global modulation (A); corpus mode with a graded distance function; the
memory-formation codelet (B) at **stage (a) — new nodes only**; the forgetting
codelet with seed-ontology protection and a homeostasis check.

*Proves:* trainability — the first real learning result. *Exit:* measurable
improvement in corpus completion across training, and a Slipnet that neither
explodes nor lobotomises itself. Corpus mode precedes live dialogue deliberately:
deterministic, fast, and GPU-uncontended.

### Phase 4 — Vocabulary

The two-level utility-gated tokeniser; cross-run vocabulary persistence in Episodic
Memory; hierarchical/recursive chunking; a–z preserved as pre-seeded tokens. GPU
work grows up here — **population batching** and larger Slipnet kernels.

*Proves:* that useful perceptual units emerge from experience and that a larger
window stays tractable. *Exit:* vocabulary that demonstrably lowers effort on
problems it was not crystallised from — utility, not frequency.

### Phase 5 — The other

Live `local-llm` dialogue replacing the corpus; curiosity and inquiry codelets
wiring unlinked tokens by asking; the system-prompt curriculum; record-replay of
LLM calls. **Projection/ingestion becomes load-bearing here** — theory of mind has
something to be about only once there is a real other.

*Proves:* the §0 wager — that self/other recognition falls out of ordinary
perceptual machinery pointed inward. *Exit:* dual-labelled elements arise and
demonstrably change behaviour.

### Phase 6 — Ontology

Consolidation of themes, trace, and coderack activity into Slipnet structure; B
advancing to **stage (b) new links** and then **stage (c) new relation types**;
evolutionary tuning over populations (possible from Phase 4, worthwhile once there
is something worth tuning); self-constructed codelets last, behind the safety
boundary of §9.

*Proves:* ontology bootstrap — the north star of §11. *Exit:* open-ended by
construction.

## 15. Open questions toward a plan

These remain to settle **during planning/implementation** — the load-bearing
architectural decisions are now made (§1–§14). Each is tagged with the phase that
must resolve it.

1. **Sink event vocabulary** *(Phase 0)* — the exact `RunSink` call sites, and what
   a "turn" means for Normal before §8's turn recurrence exists (interim: the run).
   Also how much of the live client can be reused for recorded-state review (§13b-i).
2. **Runtime and framework choices** *(Phase 1)* — free-threaded CPython vs. a
   native core (§12b); MLX vs. hand-written Metal kernels (§12a); per-codelet RNG
   stream derivation; the commit-journal format.
3. **Projection/ingestion triggers** *(seeded Phase 1, load-bearing Phase 5)* — what
   fires them, and whether me/not-me labels are `Description`s participating in
   salience and strength.
4. **Corpus-mode distance function** *(Phase 3)* — byte-, token-, or
   structure-level nearness; must be *graded* so valence has strength, not just sign.
5. **Mechanics of B / not-love** *(Phase 3 for stage (a); Phase 6 for (b)/(c))* —
   precise definition of "deepest activated paths"; the built concept's depth,
   links, and initial activation; the `not-love` removal target; the merge/dedup
   rule for near-duplicates; and what a *new relation type* is operationally.
6. **Tokenizer mechanics** *(Phase 4)* — ratify the two-level utility-gated design;
   define the promotion criterion and vocabulary persistence (distinct from B).
7. **Determinism / record-replay** for `local-llm` calls *(Phase 5)* — corpus mode
   is already deterministic; live dialogue is not.
8. **Codelet reconceptualisation for free-running** *(Phases 3–5)* — read-set /
   write-set discipline, region granularity, and how far the `%proposed%` →
   `%evaluated%` → `%built%` lifecycle can be repurposed as the commit protocol.

*Resolved this pass: the backward pass's expressiveness — the **goal is (c)**
(new relation types / genuine ontology bootstrap), approached in stages
(a) nodes → (b) + links → (c) + relation types.*

## Glossary (new terms)

| Term | Meaning |
|------|---------|
| **me / not-me** | Deepest Slipnet nodes; origin of a byte (emitted vs received), sliplinked as opposites |
| **Dialogue transcript** | The new perceptual field: interleaved me/not-me turns perceived over time |
| **Projection** | Codelet attaches `not-me` to a `me` element ("the other may be as I am") |
| **Ingestion** | Codelet attaches `me` to a `not-me` element ("I take on what the other did") |
| **Dual-labelled element** | Carries both me and not-me; site of self/other recognition |
| **Crystallisation** | Promotion of a recurrent, useful group pattern into a permanent Slipnet token-node |
| **Token (Petacat sense)** | A learned chunk concept, hierarchical, wired by asking the other |
| **Sliding 4-slot window** | The transcript scrolling through the classic `(1):(2)::(3):(4)` analogy slots |
| **Turn recurrence** | `(1+2+3)→1′, (4)→2′, (5)→3′`, Petacat emits `4′`; repeats forever |
| **Consolidation** | Crystallising a passing conversation into Slipnet nodes/links — this architecture's "training" |
| **Raw history** | Append-only byte log of all turns; stored but not yet recallable |
| **love / not-love** | Separate valence mechanism supplying the external fitness signal |
| **Global valence modulation (A)** | love/not-love uniformly boost/nerf the permanence of all current structures |
| **Backward pass (B)** | love reifies the deepest activated paths into a new concept; not-love removes a learned one |
| **Corpus mode** | Drive valence from nearness of emitted (4) to a corpus's next segment — deterministic, LLM-free training |
| **Symbolic layer** | The codelets — irregular, branchy, run concurrently across CPU cores |
| **Numeric substrate** | The system's "physics" — activation, salience, pair-scoring, temperature — run on GPU cores |
| **Wave (BSP)** | A batch of codelets run concurrently, then conflict-resolved and committed in deterministic order |
| **Free-running** | The parallelism goal: continuous barrier-free codelet execution, sharded coderack, no global synchronisation |
| **Fast Run / Normal / Audit** | The three persistence modes: no database at all / turn start+end state / every tick as it runs, serial (§13) |
| **`RunSink`** | The port the engine emits events to; mode is which implementation is attached, and the engine never knows which |
| **Config-hash** | Hash of the `MetadataProvider` a run executed under; replay is only valid against a matching hash |
| **Conflict → fizzle** | A codelet that loses a race fizzles — reusing an outcome the architecture already has |
| **Replay-determinism** | Reproducibility from a journaled commit order rather than a predictable schedule |
| **Serial reference mode** | Permanently retained one-codelet-at-a-time execution, for fidelity cross-validation |
| **Population parallelism** | Batching K independent runs so the GPU sees fat batched kernels — the near-term GPU win |
