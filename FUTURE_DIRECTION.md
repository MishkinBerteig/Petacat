# Future Direction

Four open questions about where Petacat might go next — not a roadmap, but
an invitation to think along with me about four tangled threads in the same
cloth. I'd rather start a conversation than ship a spec.

The threads are numbered 0 through 3 deliberately. The first of them is the
ground floor that gives the other three their meaning.

---

## 0. What would it mean for a Metacat-like system to have a self?

Metacat watches itself, but it does not *know* it is a self. The Themespace
monitors patterns of processing; those patterns are "its own" only in the
sense that nobody else is watching them. There is no concept node in the
slipnet for "me" or "not-me" — nothing that could participate in slippages
and bridges and rules the way `successor` or `leftmost` already do.

Suppose we added that. Suppose the self/other distinction became the deepest
ground floor of the slipnet — deeper than any existing concept — with the
two nodes linked to each other by the same sliplink machinery that already
lets opposites slip into each other. The wager is that self-awareness and
theory of mind are not faculties to be bolted on to a cognitive architecture.
They might emerge from exactly the same perceptual machinery that makes
letter-string analogies, simply pointed inward.

The philosophical anchor is the author's own hypothesis: an infant feels,
signals, and acts; an adult signals and acts; the missing piece — the
other's inner life — is inferred by analogy. Inside Petacat, the system's
internal states (activations, theme patterns, codelet traces) might *be*
qualia in the only sense that matters to the system: there is nothing
behind them; they are what the system is from the inside. A codelet
execution is an act. An inquiry is a communication. And the act of
noticing that the pattern in the other mirrors the pattern in the self
would itself be a new internal state — a new qualia of recognition.

The question is whether all of that can live inside the workspace / slipnet
/ coderack machinery without becoming a parody of cognition. The bet is that
it can, and that the difference between *"abc is to abd as xyz is to ?"* and
*"I notice _I'm_ stuck — is the _other_ also stuck?"* might not be a difference
in kind. It might be the same architecture, the same codelets, the same
slippages, applied at different levels of abstraction to different kinds of
objects.

## 1. What if the workspace weren't hardcoded to 26 letters?

The workspace is currently a perceptual environment for strings of a–z.
There is no deep reason for it to be. Metacat's architecture does not
actually care that the atoms are Latin letters — it cares that the atoms
have relationships and that groups can form over them.

What would it take to lift that restriction? Atoms might be any glyphs in
Unicode: CJK characters with their radicals and stroke counts, emoji with
their modifier families, mathematical symbols with their algebraic
structure. And atoms might themselves be composite — characters forming
words, words forming phrases — with the workspace holding perceptual
structures at multiple layers simultaneously and bridges that span layers.

> *"Doctor what's wrong with me?"* is to *"Gastroenterologist what's wrong
> with my tummy?"* as *"Teacher is educating me."* is to *?*

That is still an analogy problem. The slippages and bridges just live at
different levels of abstraction. The harder question is not the engine
surgery — the database-driven design makes much of that feasible without
touching the engine — it is *what concepts a richer workspace actually
wants in its slipnet*, and that is precisely the question the other three
threads begin to answer.

## 2. Can Petacat/Metacat tune itself?

Every run of Petacat produces a sequence of codelet executions. That
sequence is a phenotype; the genotype is the system's configuration, and
the database already holds that configuration as tunable data.

The wager: fitness is something like *answer quality divided by effort*,
runs are deterministic given a seed, and a population of configurations is
cheap to materialise. Can evolutionary pressure, applied across many runs
against a curated problem suite, find configurations that perceive better
than the hand-tuned baseline? What kinds of changes do the better
configurations represent — gentle nudges to the existing dynamics, or
qualitatively different styles of seeing? Does speed trade against depth,
or do both rise together? Metacat's behaviour is already emergent from the
interaction of many small parameters; evolution is well-suited to systems
like that, where the map from parameters to behaviour is nonlinear and
surprising. I genuinely don't know what the answers look like, and the
cheapness of running Petacat makes them the kind of questions that can be
asked empirically instead of guessed at.

## 3. Can Petacat learn by asking — and understand the answer the same way it makes analogies?

A generalised workspace will routinely encounter symbols the system has
never seen. The current system has no way to say *"I don't know what this
is."* But it could. Imagine a curiosity parameter sitting alongside
temperature, rising when the workspace contains objects the slipnet cannot
describe, and biasing codelet selection toward a new family of inquiry
codelets whose job is not to build perceptual structures but to expand the
slipnet itself.

The deep move, though, is not asking the user a question. The deep move is
what happens when the answer comes back. The response must not be parsed
deterministically. Understanding the user's explanation *is itself an
analogy problem*, and the system solves it by running another perceptual
pass through its own machinery. If "X is like Y but more formal" arrives,
the system treats *"more formal than Y"* as a structure to perceive, and
whatever bonds, bridges, and slippages emerge while perceiving it become
the new slipnet content for X. And if, while perceiving the response, the
system encounters yet another novel element, it asks again — analogies
nested inside analogies, recursing downward until they bottom out in
concepts the system already knows.

This is the *meta* on Metacat that creates Petacat. There is no separate
learning module. Perception, analogy-making, and concept acquisition are
the same process, applied at different levels of abstraction to different
kinds of objects. The system learns by perceiving its teacher.

---

## The arc, and the bet underneath it

These four threads are not independent. Self/other grounding (0) gives the
system something to be. A generalised workspace (1) gives it a richer world
to perceive. Evolutionary learning (2) tunes it to perceive well.
Interactive curiosity (3) lets it grow its conceptual vocabulary by asking
— and understanding the answers through the same analogical machinery it
uses for everything else. Each one makes the others more powerful. Without
a richer workspace, evolution has little to optimise and curiosity has
little to ask about. Without evolution, the concepts curiosity acquires
stay shallow. Without the self/other ground floor, the whole enterprise is
just noise: there is no *one* who notices what it doesn't understand.

Petacat is a place to test that bet.

---

## Join the conversation

If any of this resonates — if there is a disagreement you want to argue,
a missing link you want to point at, a place where you think the whole
edifice breaks, or an entirely different direction you think is more
fruitful — I would love to talk about it. This is not a plan I want to
execute alone. It is a conversation I want to start.

You can reach me on LinkedIn: <https://www.linkedin.com/in/mishkinberteig>.

— Mishkin Berteig
April 12, 2026
