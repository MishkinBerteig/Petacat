# Support-Set Oracles for Comparing Stochastic Systems

### A cheap two-sided test, saturated by Good–Turing, applied to a port of the Metacat cognitive architecture

**Mishkin Berteig**
Petacat Project · August 2026

---

## Abstract

Porting or re-implementing a stochastic program raises a verification problem that conventional regression testing does not address. There is no ground truth to check against, no seeded run of the original that the port can reproduce step for step, and no single output that is "the" correct answer. What exists is a *distribution* over outcomes, and the practical question is not "is the port correct" but "does the port behave the same, and if not, where."

This report describes the oracle we built to answer that question for **Petacat**, a Python re-implementation of James Marshall's **Metacat** cognitive architecture, and records what it found. The method has three parts. First, the reference implementation is sampled to *saturation* under the Good–Turing missing-mass estimate `f₁/n`, producing for each problem a **support set** — the set of outcomes the reference can reach — together with a quantified estimate of how much probability mass that set is still missing. Second, the system under test is sampled at two orders of magnitude fewer runs and compared against that reference by **set membership only**, never by frequency. Third, the comparison is deliberately **two-sided and asymmetric**: a missing *head* outcome (a member of the smallest most-frequent subset whose combined share reaches 50%, which we call the **p50 set**) is treated as strong evidence of divergence, while a *novel* outcome is treated as a question whose false-alarm rate is read directly off the reference's own
`f₁/n`.

We do not claim the ingredients are new. Good–Turing estimation dates to 1953; species-discovery statistics were introduced to software testing by Böhme's STADS framework in 2018; differential testing against a reference implementation is older still. The contribution of this report is a specific, cheap composition of those ingredients for the *cross-implementation comparison* case, a calibration procedure that makes both sides
of the test quantitative, and an account of applying it in practice.

The reference oracle cost 374,500 runs of Metacat. A routine comparison cycle costs 1,900 runs of Petacat — 100 per problem, roughly 197× fewer per problem — and carries a computed false-negative probability below 4 × 10⁻¹⁰ on the head test and an expected 0.17 spurious flags per cycle on the tail test. Across the 19 benchmark problems the oracle located a single defect in the port responsible for three of its five flagged variations, closed one harness artefact, and left one finding open, while never once firing the head test.

---

## 0. Background

The method of the following sections is a composition of well-known ingredients; §2 is explicit about this. What is specific to this project is the path by which the composition was reached and the composition itself. Two of the design decisions that carry the paper's weight — the saturation of the reference by the Good–Turing missing-mass estimate rather than by a fixed run count, and the comparison of outcome *supports* rather than of outcome *distributions* — were reached by elimination, under constraints that became visible only as the work proceeded. This section records that path.

### 0.1 The port, and where static comparison runs out

Petacat was produced by an iterative, model-assisted static porting effort: across many passes, large language models translated the reference implementation's Chez Scheme source into Python, holding the two sources against each other for consistency, with Marshall's dissertation [21] — which describes the architecture in prose the code does not always make explicit — as a second reference throughout. The process produced a functionally complete implementation, and it was the natural first phase of the work. It also exhausted its own evidence at the point where it stopped: a static comparison can only report that the two sources agree, and for a stochastic system, source agreement is not behavioural agreement.

### 0.2 The suspicion

The first manual exercises of the port produced behaviour that did not match, to the developer's own understanding of the architecture, what the reference and its documentation describe. The immediate response was to bring the reference itself into the local environment and to run both systems side by side. Even at extremely small sample sizes the mismatch was visible to inspection. But inspection at small sample sizes is the weakest evidence available for a system of this kind: a run is a single draw from a potentially heavy-tailed distribution as hinted by the samples from Marshall's dissertation, and a handful of draws from two such distributions, compared by eye, can neither confirm nor refute a behavioural divergence. The suspicion was worth acting on, but could not be the basis of a verdict.

### 0.3 The stopping problem

The requirement that followed was for reference data with a quantified completeness. The first naive design sketched for it was the direct one: sample the reference until no new outcomes are discovered after a fixed number of times for each problem (the author tried n=1000). The intention was to sample enough times to estimate the probability of each outcome on each problem, and compare the implementations' outcome probabilities. That design ran into two issues at the trial stage. The practical issue: for a system whose outcome space is large and long-tailed, the run count for both systems needed to estimate the tail to useful precision is large, and on capable hardware the one-off reference characterisation remained a major burden, particularly with a preference for fast iterative test and fix cycles. The conceptual issue, which is the decisive one: the stopping criterion was clearly arbitrary and for some problems obviously insufficient. A sample of a distribution whose support is unknown does not report when it is large enough or when all reachable outcomes are exhausted.

A short discussion with Gemini and a review of some options on Wikipedia dissolved the second issue. The Good–Turing missing-mass estimate, f₁/n computed on the reference system, estimates exactly the quantity a reference characterisation must be able to state for itself: how much probability mass the sample has not yet seen. Sampling the reference to a small target for f₁/n is therefore both a sufficient procedure and a self-certifying one. The saturation criterion of §3.3 is that idea adopted, together with the small-sample guard the same literature forces.

### 0.4 From distributions to supports

With a stopping rule in hand, the design still had to choose what the check compares. The obvious object was the outcome distribution itself — a divergence, a goodness-of-fit test, or a per-outcome comparison of estimated probabilities. Pursuing those routes showed them to be unnecessary, and still very expensive: resolving two multinomials over a support of this size to useful power requires tens or hundreds of thousands of runs per problem per check. But that would be several hours per check instead of the desired handful of minutes for an impatient human and AI agents. Remember: the original suspicion was that the port produced outputs that were simply wrong. The only rival hypothesis was that it produced rare but legitimate outputs — outcomes in the reference's support at probabilities too small to be visible in a small sample. Those two hypotheses are separated by a single question: *is the outcome in the reference's support?* Frequency is irrelevant to the question; membership suffices. Support comparison is therefore not a simplification adopted for convenience but the resolution of an ambiguity that distributional comparison could not resolve — and, for the reasons of §3.2, it is the comparison that is invariant to the legitimate engine changes (scheduler, random stream, numeric backend, concurrency) the project routinely makes.

Support membership is, by itself, one-sided: observing an outcome proves reachability; absence in a small check sample proves nothing. The second component of the method addresses the question of missing outcomes. The reference set is partitioned into a head — the p50 set, the smallest subset of outcomes whose combined reference share reaches one half of the mass — and a tail. A head member is frequent enough that its *absence* from a small check sample is itself evidence, with a per-member, computable false-negative rate; the tail is policed by the reference's own missing-mass figure, which bounds the false-alarm rate of a novelty flag. The head was added because the mirror image of the original suspicion is equally damaging: a port that silently ceases to produce a common reference outcome is as far from the reference as one that produces nonsense, and the support test alone cannot see it.

### 0.4 The benchmark, and what the reference harness found

The problem set was drawn, at first, from the analogy problems worked through in the dissertation [21]; a small number of near-trivial problems were added later to extend the benchmark, where the expected behaviour is obvious and a flag therefore carries exceptional weight. Building the reference had a secondary effect the plan did not anticipate: running the reference implementation under the sampling harness surfaced defects in that original code — genuine bugs in the Metacat source, which were subsequently corrected locally but which have not yet been corrected upstream. A reference is only as good as the build that is sampled, and the disposition rule of §3.5 — novel outcomes are never auto-admitted, and a human decides whether the set was incomplete or the reference itself defective — exists because of this experience.

### 0.5 The findings

With the reference sets, their saturation figures, and the two-sided decision rule in place, the comparison ran continuously over the remaining development of the port. It located a number of discrepancies, most of them defects of runtime behaviour — direction-sensitivity in rule application, a transformation cancelled by a later one at render time, scheduling and random-stream effects — the class of defect the static porting analysis cannot surface, because on paper the two sources agree. The oracle's central contribution in this project was therefore not a confirmation of the port's correctness but a change of epistemic status: it converted an exercise that had run out of static evidence into an empirical one, in which every flag carries a computed error rate, names the outcome at issue and allows for trace analysis to discover the appropriate remediation.

---

## 1. Introduction

### 1.1 The problem

Petacat is a from-scratch Python re-implementation of Metacat [21, 22], itself an extension of Copycat [23, 24], a model of analogy-making in the Copycat microdomain of letter-string analogies (e.g. `abc → abd; xyz → ?`). Both programs are stochastic by design: an answer emerges from thousands of small, probabilistically scheduled "codelets" competing to build structure in a workspace, under a temperature that modulates the randomness. Running the same problem twice gives different answers, and that is the intended behaviour, not a defect. `abc → abd; xyz → ?` has no right answer; it has a *distribution* of answers, and the distribution is the scientific object of interest.

We needed a mechanism to test the Petacat port behaviour against the Metacat reference across a small set of 19 letter-string analogy problems [Appendix C - Letter-String Analogy Problems].

This makes the usual regression apparatus useless in both directions:

- **No golden output.** There is no expected value for a test to assert.
- **No seeded replay.** The two implementations use different random number generators and consume draws at different points, so seed *s* in Metacat and seed *s* in Petacat index unrelated trajectories. Even where the two algorithms are identical, no run corresponds to any other run.
- **No specification.** Metacat is a research artefact whose specification is its own source code, in a language (Chez Scheme, with late binding and redefined numeric primitives) that resists pure static comparison against Python.

This is Weyuker's *non-testable program* [1] in a fairly pure form, and the reference implementation is the pseudo-oracle [2] — but a pseudo-oracle whose output is a random variable rather than a value, so the comparison itself has to be statistical.

### 1.2 What we wanted from the oracle

The design was driven by three requirements, in this order:

1. **It must be cheap enough to run often.** An oracle that costs hours is consulted after a release; an oracle that costs minutes is consulted after a change. The engine under test changes its scheduler, its RNG, its numeric backend and its update cycle routinely, and each of those is the sort of change that needs checking.
2. **It must be invariant to legitimate change.** Reordering codelets, changing the random stream, running the engine concurrently, or moving from float64 on the CPU to float32 on a GPU all change *which* outcome a given seed produces and *how often* each outcome occurs. None of them should change *which outcomes are reachable*. An oracle that finds too many false deviances is an oracle that stops being used.
3. **Every verdict must carry its own error rate.** A flag that cannot be weighed is a flag that gets ignored. Both the false-negative rate of the "missing" test and the false-positive rate of the "novel" test must be computable from the reference data.

Requirement 2 is what pushed us away from outcome distribution comparisons and towards support-set comparison. Requirement 3 is what pushed us to Good–Turing. Requirement 1 is what makes the whole arrangement worth sharing: the asymmetry between a very expensive one-off reference and a very cheap recurring check is the practical core of the technique.

### 1.3 Scope

This is a project report, not a novel-technique paper (although we did not find an identical approach our our background research). Section 2 situates the approach in existing literature. Section 3 states the method precisely enough to reproduce, and Section 4 gives the calibration arithmetic. Section 5 reports the application to the Petacat/Metacat project with measured numbers. Section 6 draws practical guidance and Section 7 states the limitations.

---

## 2. Background and related work

### 2.1 The oracle problem

Barr, Harman, McMinn, Shahbaz and Yoo's survey [3] organises test oracles into specified, derived, implicit and human categories, and identifies the absence of an oracle as *the* bottleneck for test automation. Our oracle is *derived*: it is obtained from a reference implementation, in McKeeman's differential-testing tradition [4], and from prior executions of that reference. Patel and Hierons [26] map the specific literature on testing non-testable systems and note that most published approaches fall back on metamorphic relations or on statistical characterisation — which is, broadly, what we do.

### 2.2 Testing randomized software

Where a program's output is a random variable, the natural move is to replace assertion with hypothesis test. Guderlei and Mayer's *statistical metamorphic testing* [6] executes the program repeatedly under related inputs and applies statistical tests to the resulting output samples. Yoo [27] applies metamorphic relations to stochastic optimisation specifically. Segura et al. [28] and Chen et al. [5] survey the metamorphic literature broadly, which originates with Chen, Cheung and Yiu [7]. Arcuri and Briand [31] give the standard treatment of statistical tests for randomized algorithms in software engineering, and are worth reading as a warning: naive application of significance tests to randomized software produces confident nonsense at an impressive rate.

Statistical model checking ("SMC") [15, 16] takes the same idea further, verifying temporal properties of stochastic systems by sampling traces and applying sequential hypothesis tests. The connection to our stopping rule is real — both stop sampling when a statistic crosses a threshold — but SMC verifies a *stated property* of a *single* system, whereas we are characterising an unstated distribution in order to compare two systems.

The metamorphic route was not available to us in any strong form. Metacat has few clean metamorphic relations: the microdomain's symmetries (letter-alphabet reflection, string reversal) are precisely the structures the program is *modelling*, and asserting them would assert the answer.

### 2.3 Species discovery in software testing

The closest prior work is Böhme's **STADS** framework [13], which imports three decades of ecological biostatistics into automated test generation, and the follow-on work of Böhme, Liyanage and Wüstholz on residual risk in greybox fuzzing [14]. The insight in both is that a fuzzing campaign is a sampling process over a population of "species" (branches, paths, bugs), so the ecologist's question — *how much of the population have I not yet seen?* — is exactly the tester's question about when to stop. Both papers use the Good–Turing estimator or close relatives, and [14] argues that discovery probability is a good upper bound on
residual risk.

Our use is the same statistic in a different role. STADS asks how complete a *test campaign* is. We ask how complete a *reference characterisation* is, and then use that completeness figure to calibrate the false-alarm rate of a downstream comparison. The species being counted are not code artefacts but externally observed outcomes.

The statistical machinery itself is old. Good [8] introduced the estimator, crediting Turing; Efron and Thisted [11] made it famous by estimating Shakespeare's unseen vocabulary; Chao [12] and Chao and Lee [30] gave the non-parametric richness and coverage estimators standard in ecology; Gale and Sampson [9] gave the practical smoothing recipe used in language modelling; McAllester and Schapire [10] supplied the finite-sample convergence analysis that Good and Turing did not; Orlitsky, Suresh and Wu [29] give the modern optimality results. Capture–recapture, the sibling technique, entered software engineering much earlier through defect-content estimation in inspections [25].

### 2.4 Replication of simulation models

The problem of establishing that two implementations of a stochastic model agree is better developed in agent-based social simulation than in software engineering. Axtell, Axelrod, Epstein and Cohen's *alignment of simulation models* ("docking") [19] and Wilensky and Rand's replication study [20] both confront exactly our situation: two programs, one conceptual model, stochastic outputs, no ground truth. Wilensky and Rand propose a hierarchy of replication standards — from *numerical identity* down to *distributional equivalence* and *relational alignment* — and their experience report matches ours, including the finding that ambiguities in the original are resolved differently by the replicator and only surface as behavioural differences.

Finally, the software-engineering literature usually treats output nondeterminism as pathology to be eliminated [17]. Our situation inverts that framing: the nondeterminism is the system's intended semantics, and the engineering problem is how to build a deterministic decision procedure on top of a genuinely random observable. Seeding, mocking and retry are all unavailable or wrong here, since seeding freezes the very thing being measured.

---

## 3. Method

### 3.1 Formal setting

Let the system under test be a randomized program *P* and the reference be *R*. For a fixed input *x* (in our case, one analogy problem), each execution produces an outcome drawn from a discrete distribution over a countable outcome space 𝒪. Write:

- **π<sub>R</sub>(·|x)** — the reference's outcome distribution, unknown, sampled only.
- **π<sub>P</sub>(·|x)** — the same for the system under test.
- **supp(π) = { o ∈ 𝒪 : π(o) > 0 }** — the *support*, the set of reachable outcomes.

The oracle tests a hypothesis about supports, not about distributions:

> **H₀:** supp(π<sub>P</sub>) = supp(π<sub>R</sub>)

with two directional alternatives (novel outcomes and missing outcomes) handled differently, because the evidence available for them is not symmetric.

**The outcome must be canonical and coarse.** In our application an outcome is the pair `(status, answer-string)`, flattened to a short key, with two reserved values for non-answers: `*NONE*` for a run that terminated without an answer and `*CAP*` for a run that exhausted its codelet budget. Both are treated as ordinary outcomes, deliberately: gaining or losing the ability to fail on a problem is exactly the kind of change the oracle exists to catch, and filtering non-answers out would hide it. The choice of outcome granularity is the single most consequential design decision in the whole method — too fine and the support is unbounded and never saturates; too coarse and real divergence is projected away.

### 3.2 Why the support, and not the distribution

The obvious oracle is distributional: sample both systems, compute a divergence (total-variation distance, KL, a χ² or Kolmogorov–Smirnov test), threshold it. We rejected this for three reasons, in decreasing order of importance:

**(a) It is not invariant to legitimate change.** Petacat's engine legitimately changes its codelet scheduler, its random stream, its numeric backend (float64 CPU vs float32 Metal GPU) and its concurrency model. Every one of those perturbs outcome *frequencies* while leaving the reachable set alone. A frequency oracle fires on all of them, and — crucially — cannot separate expected drift from regression, so every fire requires the same manual investigation as a genuine defect. Requirement 2 of §1.2 is violated outright.

**(b) It requires large samples at check time.** Distinguishing two multinomials over tens of outcomes with adequate power needs thousands of runs per problem per check, which puts the routine cost in the same order as the reference cost and destroys the economic asymmetry that makes the whole scheme worthwhile.

**(c) It gives an uninterpretable scalar.** "TVD = 0.19" localises nothing. Support membership gives the engineer a named outcome — *this string, which the reference produces and you do not* — which is directly actionable.

### 3.3 Building the reference: saturation by Good–Turing

The support set is only useful if it is nearly complete. An incomplete reference set turns every legitimate outcome it failed to sample into a spurious "novel" flag, and there is no way to distinguish that from a real one. So the sampling of *R* must stop on a criterion that estimates *its own incompleteness*.

Let a reference sample of *n* runs on problem *x* yield counts over outcomes, and let

$f_1 = \bigl|\{\, o : \text{count}(o) = 1 \,\}\bigr|$

be the number of outcomes seen exactly once (the *singletons*, or in ecological language the *singleton species*). The Good–Turing estimate of the **missing mass** — the total probability of outcomes not yet seen, i.e. the probability that the next run produces something new — is

$\widehat{M_0} \;=\; \frac{f_1}{n}$

Three properties make this the right stopping statistic here:

1. **It measures the thing we care about.** Not "how many outcomes exist" (Chao's richness question [12]) but "how much probability is in outcomes I have not seen". That is precisely the per-run false-alarm rate of the downstream novelty test.
2. **It is nearly unbiased and concentrates.** Good [8] showed near-unbiasedness; McAllester and Schapire [10] give high-probability finite-sample bounds of order O(n<sup>−1/2</sup>) independent of the size of the outcome space, which is what licenses using it on a support whose cardinality we do not know.
3. **It is directly a rate.** Multiplying by the check sample size gives an expected count of spurious flags. No further modelling is needed to interpret it.

**The stopping band.** We sample in batches and stop when

$\tau_{\text{lower}} \;<\; \frac{f_1}{n} \;\le\; \tau_{\text{upper}}$

with τ<sub>upper</sub> = 10⁻⁴ and τ<sub>lower</sub> = 6 × 10⁻⁵ in our instantiation. Only the upper bound is a stop condition. The lower bound exists so that a batch that overshoots — driving `f₁/n` far below the target and burning runs to no purpose — is *reported* rather than silently accepted, so the batch size can be tuned. Undershooting the band is harmless to correctness; the reference set is simply larger than it needed to be.

**The f₁ = 0 pathology, and the floor.** When no outcome has been seen exactly once, `f₁/n = 0`, and the estimator cannot distinguish "the support is complete" from "the sample is far too small". This is the classic small-sample failure of Good–Turing and it must be guarded explicitly. We require

$n \;\ge\; 1/\tau_{\text{upper}}$

before accepting an `f₁ = 0` stop, on the reasoning that `f₁ = 0` below that threshold is *weaker* evidence than `f₁ = 1` at that threshold, which the band itself would reject. This is not a theoretical nicety: in our data, two problems (`abc → cba; mrrjjj` and
`eqe → qeq; abbba`) reported `f₁ = 0` at n = 3,000 while their rarest observed outcome had been seen only two or three times. Without the floor, both would have been declared saturated with materially incomplete sets.

**Why a "no new outcome in k runs" rule is not adequate.** The obvious cheap alternative is to stop when *k* consecutive runs produce nothing new. We measured this against a deep sample and it can fail badly. On a deep sample of `abc → abd; xyz → ?`, the observed support had 35 outcomes, with six inter-discovery gaps longer than 1,000 runs (1,124 / 2,595 / 1,275 / 1,851 / 2,676 / 3,068). A "1,000 runs with no new outcome" rule stops at run 3,933 holding 22 of 35 outcomes — **37% of the support missing**. Every absent outcome would later present as a false regression. At that same point `f₁/n` stood at roughly 2 × 10⁻³, twenty-five times its eventual saturated value, correctly reporting *keep going*. The Good–Turing criterion sees the long tail that a gap rule cannot, because it reasons from the *shape* of the frequency spectrum rather than from the recent history of discovery.

**Sharding.** `f₁` is a global statistic over the whole sample, so parallel workers cannot decide when to stop. Our sampler splits each problem across *K* processes on disjoint, interleaved seed ranges (shard *s* takes indices *s*, *s+K*, *s+2K*, …); each shard writes per-outcome tallies after every chunk; a coordinator merges them, evaluates the criterion, and signals termination through a stop file. A problem's wall clock is then its run count divided by *K*. This matters — the reference took hours as it is.

**Checkpointing.** A problem that reaches a run ceiling without saturating stops there and *reports the fact* rather than grinding to the hard maximum. Its `f₁/n` at that point is recorded and travels with the set, so a downstream flag on that problem can be weighed appropriately. Three of our nineteen problems ended this way.

### 3.4 Deriving the head: the p50 set

Support membership is inherently a *one-sided* test. Observing an outcome proves it is reachable; *not* observing it in a small sample proves nothing, because most of the support is rare. If the check sample is 100 runs and an outcome has share 0.2%, its absence is expected, not informative.

So the reference set is partitioned. For each problem, take outcomes in decreasing order of share and accumulate until the cumulative share reaches 50%. Call the resulting outcomes the **p50 set** — the smallest group of most-frequent outcomes covering the top half of the reference's probability mass. This is a coverage-based head definition rather than a fixed threshold, which makes it adapt automatically to problems with very different support shapes: a problem with one outcome at 100% has a p50 set of size 1; a problem with a long flat distribution has a larger one.

> The near-degenerate case of an effectively flat distribution of a support set size ≫ number of sample runs can be handled case-by-case by observing the p50 support set size and adjusting the number of sample runs upward to accomodate the necessary certainty. However, a true degenerate support set with a precisely flat distribution cannot use this method. This might occur in a system where there is inherent non-repeatability such as with a GUID generator.

For a p50 member with reference share *p*, the probability that a correct implementation fails to produce it in *n* independent check runs is

$\Pr[\text{miss}] \;=\; (1-p)^{n}$

and this number is computed and stored per member alongside the set. It is the false-negative rate of the head test, exactly, under the assumption that the check runs are independent draws.

### 3.5 The two-sided decision rule

A check runs *n* samples of *P* on problem *x*, collects the observed outcome multiset, and emits two verdicts:

| verdict     | condition                                                             | strength                                | disposition                 |
| ----------- | --------------------------------------------------------------------- | --------------------------------------- | --------------------------- |
| **MISSING** | a p50 member of the reference set does not appear in the check sample | decisive; error rate (1−p)<sup>n</sup>  | strong signal of divergence |
| **NOVEL**   | the check sample contains an outcome not in the reference set at all  | as strong as the reference's saturation | adjudicate against `f₁/n`   |

Nothing else is compared. In particular the reference's own frequencies are never compared against the sample's; frequency enters at exactly one point, in the *definition* of the p50 set, where it is the reference's distribution deciding which outcomes are common enough that their absence carries information.

**Both verdicts are flags, not failures.** **This must be a deliberate decision for any system with no ground truth.** During porting activities that include architectural experiments on complex stochastic processes a flag is the *result being sought*. The comparison says *stable* or *changed*; it never says *pass* or *fail*. The corollary is that the harness's own decision logic must itself be under test. We keep a unit suite over the comparison logic for precisely this reason.

**Novel outcomes are never auto-admitted.** A novel outcome is reported to a human with the reference's saturation figure, the sample size, the configuration, and the seed that produced it. Widening the reference set is a human decision recorded in the fixture. Human judgement may require deep investigation to see if there is a clear discrepancy in the functioning of the stochastic system at a conceptual level that can then result in:

- acceptance of the novel outcome in which case:
  
  - the support set somehow missed something and needs further generation work to collect the missed outcome, OR
  
  - the origin system may have a defect,

- rejection of the novel outcome in which case the system under test needs to be analyzed for an error in conceptual logic/implementation vs. the reference system.

### 3.6 The cost asymmetry

Let the reference sample be *N* runs per problem and the check sample *n* runs per problem, with *N* ≫ *n*. The reference is paid once; the check is paid on every change to the system under test. Because the reference has been driven to `f₁/n ≤ τ`, the check inherits a quantified error rate on *both* sides without itself being large. In our instantiation N ≈ 19,700 on average and n = 100, a ratio of about 197 per problem — and the check still detects the loss of any head outcome with probability better than 1 − 4 × 10⁻¹⁰.

This is the transferable idea: **spend heavily, once, to characterise the reference to a known completeness; then spend trivially, often, to test membership against that characterisation.**

### 3.7 Algorithm summary

```
REFERENCE CONSTRUCTION (expensive, once per reference version)
  for each input x:
      counts ← ∅ ;  n ← 0
      repeat
          run R on x for BATCH independent sessions; update counts; n ← n + BATCH
          f1 ← |{o : counts[o] = 1}|
          if n < MIN_RUNS:                      continue
          if f1 = 0 and n < 1/τ_upper:          continue     # small-sample guard
          if f1 = 0:                            stop "no_singletons"
          if f1/n ≤ τ_upper:                    stop ("in_band" or "overshot")
      until n ≥ MAX_RUNS                        # backstop; record "unsaturated"
      emit  support(x)  = keys(counts)
            p50(x)      = smallest prefix of counts by share with Σ share ≥ 0.5
            f1_over_n(x)= f1/n
            miss_prob(x,o) = (1 − share(o))^n_check  for o ∈ p50(x)

ROUTINE CHECK (cheap, every change)
  for each input x:
      observed ← multiset of outcomes from n_check runs of P on x   # disjoint seeds
      MISSING ← { o ∈ p50(x)          : o ∉ observed }
      NOVEL   ← { o ∈ keys(observed)  : o ∉ support(x) }
      report MISSING with miss_prob, NOVEL with 1 − (1 − f1_over_n(x))^n_check
```

Two implementation details worth stating because both cost us time:

- **Check seeds can be disjoint from reference seeds.** Replaying the reference's own seeds tests might lead one to believe that we are testing *determinism under a fixed seed*, vs. *the reachable set*. Our checker offsets seeds by 10⁶.
- [UNCLEAR:]**The two halves [what two halves?] must agree exactly on what an outcome is,** including the per-run resource cap. A sample taken at a different cap is not comparable [why?]: raising the cap lets slow runs reach outcomes they were previously truncated short of, which appears as novelty entirely unrelated to the change under test. [/UNCLEAR]

---

## 4. Calibration

The method's claim to be more than a heuristic rests on both error rates being computable in advance from the reference data.

### 4.1 False negatives: how large must the check sample be?

To detect the loss of an outcome of reference share *p* with confidence 1 − δ, the check sample must satisfy

$n \;\ge\; \frac{\ln \delta}{\ln (1-p)}$

The binding constraint is the **least-frequent p50 member across the whole reference**; call its share *p*<sub>min</sub>. Every other p50 member has a higher share and therefore a smaller miss probability, so sizing *n* against *p*<sub>min</sub> bounds the head test's false-negative rate everywhere at once. A union bound over the *m* p50 members of a problem gives

$\Pr[\text{any p50 member missed}] \;\le\; m \,(1 - p_{\min})^{n}$

Because *p*<sub>min</sub> is by construction a head share — the p50 set covers the top half of the reference's mass, so no member of it can be individually rare — this quantity falls away geometrically in *n*, and a modest check sample suffices. Where it does, **a missing head outcome is not sampling luck and can be treated as a hard signal.**

Note what this does *not* say. It bounds the probability of missing an outcome that is still produced *at its reference rate*; it says nothing about an outcome whose rate has merely fallen sharply (§7).

### 4.2 False positives: how saturated must the reference be?

Assuming that the system under test is an accurate port of the reference, the probability that a check of *n* runs surfaces at least one outcome that is genuinely reachable but was never sampled by the reference is

$\alpha(x) \;=\; 1 - \bigl(1 - \widehat{M_0}(x)\bigr)^{n} \;\approx\; n \cdot \frac{f_1}{n}$

Over *P* problems in a cycle, the expected number of spurious novelty flags is approximately

$\mathbb{E}[\text{spurious}] \;\approx\; n \sum_{x} \widehat{M_0}(x) \;\le\; P \cdot n \cdot \tau_{\text{upper}}$

Choosing τ<sub>upper</sub> is therefore a direct budget decision, and it inverts: for a tolerated *E* spurious flags per cycle,

$\tau_{\text{upper}} \;\le\; \frac{E}{P \cdot n}$

The trade is asymmetric in both directions. Tightening τ costs more than a proportional increase in reference sampling, because the tail of these distributions is (presumed) long and the last decade of missing mass is by far the most expensive to buy. Loosening it is nearly free in compute but has a threshold effect on usefulness: once a cycle produces spurious flags at a rate comparable to real ones, the flag stops being read, and an unread flag has no error rate worth computing.

### 4.3 Choosing the outcome granularity

There is no formula for this, and it is where judgement enters. The practical test is whether `f₁/n` converges at all. If the outcome space is effectively unbounded — if the key is, say, a full execution trace — then `f₁/n` plateaus well above any usable τ and no amount of sampling will saturate. Failure to saturate is therefore diagnostic of the key rather than of the sampler.

The rule of thumb is to key on the *externally meaningful result*: what a consumer of the system observes, and what a change to the system would be argued about in terms of. Everything finer than that is projected away deliberately, and §7 states what that costs.

---

## 5. Application: Petacat against Metacat

### 5.1 The systems and the benchmark

Metacat [21] is Marshall's self-watching extension of Copycat [23, 24], written in Chez Scheme, in which a swarm of codelets builds and destroys perceptual structures in a workspace until an answer is found to a letter-string analogy problem. Petacat is a Python re-implementation with a web front-end and a relational configuration store, intended to carry the architecture forward into new experiments; fidelity to Metacat is therefore a prerequisite, not the goal.

The benchmark is 19 distinct letter-string analogy problems built from those that Metacat ships as demonstrations and including a small number of basic "obvious" problems, ranging from the trivial (`bc → d; bc → ?`, a single outcome at 100%) to the pathological (`eqe → qeq; abbbc → ?`, 80 distinct outcomes). Each run is its own session, with the architecture's Episodic Memory cleared beforehand, so runs are independent and a problem's runs can be split across processes with no interaction. (Note that we have also started building out the oracle methodology for the Episodic Memory runs which will be shared in a future report.)

The outcome key is the `(status, answer-string)` pair of §3.1, which is the *externally meaningful result* in the sense of §4.3: it is what a user of either program sees on screen at the end of a run, and what any claim about the architecture's behaviour is argued about in terms of. Everything finer — which structures were built, in what order, at what temperature — is projected away. That granularity proved usable in the operational sense that matters: `f₁/n` converged for sixteen of the nineteen problems and came within a factor of four of the target on the other three.

### 5.2 The reference

Metacat was run headless (no display layer) at a 100,000-codelet cap, for **374,500 runs** in total.

|                                                |                         |
| ---------------------------------------------- | -----------------------:|
| runs per problem                               | 10,250 – 51,000         |
| distinct outcomes, all problems                | 366                     |
| p50 members, all problems                      | 27                      |
| smallest p50 share                             | 0.1947 (`run3` / `wyz`) |
| head-test miss probability at n = 100          | **3.9 × 10⁻¹⁰**         |
| expected spurious novelty flags per test cycle | **0.17**                |

Per problem:

| problem      | analogy                    | n      | distinct | f₁  | f₁/n    | stop reason     | p50 size |
| ------------ | -------------------------- | ------:| --------:| ---:| -------:| --------------- | --------:|
| `misc4`      | `a → b; z → ?`             | 11,000 | 4        | 0   | 0.00000 | no_singletons   | 2        |
| `fig5.7`     | `aabc → aabd; ijkk → ?`    | 18,125 | 18       | 1   | 0.00006 | saturated       | 2        |
| `misc3`      | `abc → aabbcc; kkjjii → ?` | 19,000 | 54       | 4   | 0.00021 | stopped by hand | 2        |
| `misc5`      | `abc → abd; glz → ?`       | 11,125 | 8        | 1   | 0.00009 | saturated       | 3        |
| `misc2`      | `abc → abd; ijk → ?`       | 11,000 | 6        | 1   | 0.00009 | saturated       | 1        |
| `run1`       | `abc → abd; mrrjjj → ?`    | 11,000 | 11       | 0   | 0.00000 | no_singletons   | 1        |
| `run4`       | `abc → abd; xyz → ?`       | 11,000 | 10       | 1   | 0.00009 | saturated       | 2        |
| `misc1`      | `abc → cba; mrrjjj → ?`    | 30,750 | 18       | 3   | 0.00010 | saturated       | 1        |
| `fig5.4-top` | `eeqee → qeeq; xxixx → ?`  | 51,000 | 61       | 19  | 0.00037 | **checkpoint**  | 2        |
| `eqe-baaab`  | `eqe → qeq; abbba → ?`     | 51,000 | 51       | 13  | 0.00026 | **checkpoint**  | 1        |
| `run6`       | `eqe → qeq; abbbc → ?`     | 47,500 | 80       | 4   | 0.00008 | saturated       | 1        |
| `run3`       | `rst → rsu; xyz → ?`       | 21,000 | 12       | 2   | 0.00010 | saturated       | 2        |
| `run2`       | `xqc → xqd; mrrjjj → ?`    | 11,000 | 10       | 1   | 0.00009 | saturated       | 1        |
| `copy1`      | `ab → c; ab → ?`           | 10,875 | 2        | 0   | 0.00000 | no_singletons   | 1        |
| `copy2`      | `bc → d; bc → ?`           | 11,250 | 1        | 0   | 0.00000 | no_singletons   | 1        |
| `copy3`      | `xy → z; xy → ?`           | 11,000 | 1        | 0   | 0.00000 | no_singletons   | 1        |
| `copy4`      | `zy → x; zy → ?`           | 11,125 | 2        | 0   | 0.00000 | no_singletons   | 1        |
| `copy5`      | `aabb → cc; aabb → ?`      | 15,500 | 13       | 1   | 0.00006 | saturated       | 1        |
| `copy6`      | `abc → d; abc → ?`         | 10,250 | 4        | 1   | 0.00010 | saturated       | 1        |

Two observations are worth drawing out.

**Saturation cost is extremely uneven.** Four problems saturate at ~11,000 runs because their support is one or two outcomes; three problems consume 47,000–51,000 runs and two of those never reach the target. Support size and saturation cost are related but not identical: `run6` has the largest support (80) yet saturated, while `fig5.4-top` (61) did not, because `fig5.4-top`'s tail is flatter. A fixed run budget per problem would have been simultaneously wasteful and insufficient.

**Three problems are honestly unsaturated, and say so.** `fig5.4-top` (0.00037) and `eqe-baaab` (0.00026) hit the 50,000-run checkpoint with their supports still growing; `misc3` (0.00021) was stopped by hand. The practical cost is under 0.04 spurious flags per 100 runs each. This is recorded per problem rather than smoothed away, and it changes how a flag on those three is read — a novelty flag on `copy2` (f₁/n = 0) is far more interesting than one on `fig5.4-top`.

**The false-positive budget.** τ<sub>upper</sub> = 10⁻⁴ was chosen from the inversion in §4.2: with *P* = 19 problems and *n* = 100 check runs, it bounds the cycle at 19 × 100 × 10⁻⁴ = 0.19 spurious novelty flags, about one every five cycles, which is tolerable for a flag that triggers human adjudication. Summing the *actual* per-problem `f₁/n` above rather than the bound gives **0.17** — the three unsaturated problems consume most of it, and the eight at `f₁/n` = 0 contribute nothing.

### 5.3 The check

A routine comparison cycle runs **100 runs per problem** — 1,900 runs in total, against a reference that cost 374,500. An example check uses the float64 CPU backend, a 20,000-codelet working cap for speed, and a seed range disjoint from the reference's in order to avoid interpretation confusion.

*n* = 100 comes from §4.1. The least-frequent p50 member anywhere in the reference is `run3`'s `wyz` at share *p*<sub>min</sub> = 0.1947, and δ = 10⁻⁶ requires ln(10⁻⁶) / ln(1 − 0.1947) ≈ 64 runs. At *n* = 100 the actual miss probability for that member is (1 − 0.1947)<sup>100</sup> = 3.94 × 10⁻¹⁰ — about four chances in ten billion — and every other p50 member has a higher share and a smaller one. The head test is therefore decisive by a wide margin, and 100 was rounded up from 64 to buy that margin at negligible cost.

One methodological wrinkle deserves recording because it produced a false flag before it was fixed. The check's 20,000-codelet cap is one fifth of the reference's, so a Petacat `*CAP*` outcome is not comparable to a reference `*CAP*` — the run might well have answered given the reference's budget. Because each run is independent, this is resolvable: re-running that seed at the reference's cap is the same run continued, and whatever it reaches there is what gets compared. It is cheap because caps are rare — 23 of 1,900 runs in a cycle, 22 of them on the one problem where the reference also caps heavily and `*CAP*` is a legitimate member of the reference set in its own right. The general lesson is that a resource cap is part of the outcome definition, and where the two sides differ, the difference must be either resolved or explicitly declared incomparable.

### 5.4 Results

**The head test has never fired.** Across every cycle, on both numeric backends, **zero** missing p50 members. Given the computed miss probability of 3.9 × 10⁻¹⁰ this is meaningful evidence that Petacat reaches the reference's common outcomes at broadly comparable rates.

**The novelty test fired usefully.** The first full cycle produced five novel outcomes across five of the nineteen problems. Their disposition, after investigation:

| problem     | novel outcome | root cause ("RC")                                   |
| ----------- | ------------- | --------------------------------------------------- |
| `eqe-baaab` | `abbbb`       | **RC-A** — a defect in the port                     |
| `run6`      | `cdddb`       | **RC-A**                                            |
| `copy1`     | `*NONE*`      | **RC-A**                                            |
| `run1`      | `*CAP*`       | **RC-B** — the codelet-cap artefact of §5.3; closed |
| `copy5`     | `aac`         | **RC-C** — named cause measured and refuted; open   |

RC-A is the result that justifies the exercise. A group whose bonds run leftward — `[[a][bbb]]` in `abbba`, read right to left — was given an image asserting it ran rightward, which corrupted the sub-image order, the starting letter, and the letter and length relations all at once. It was invisible under ordinary inspection because a second reversal at rendering time cancelled the first, so an *untouched* image printed correctly; only rule application, which is direction-sensitive, exposed it. It was confirmed by intervention on *both* sides — probing the instrumented Python, and patching the Scheme with a one-hunk emulation of the defect to see whether the reference then produced Petacat's outcomes. It did.

After the RC-A repair and the RC-B harness fix, a full cycle on identical seeds gave:

|                | before | after                   |
| -------------- | ------ | ----------------------- |
| novel outcomes | 5      | **1** (`copy5` / `aac`) |
| missing p50    | 0      | **0**                   |

One further harness improvement generalises. We added cross-cycle recurrence marking: an outcome that appears in two consecutive cycles is flagged as recurring, because the Good–Turing argument that excuses a singleton is an argument about *one* sample. An outcome that keeps coming back is not missing mass, whatever its count in any individual cycle. It is cheap, and it materially raised the signal-to-noise of the flag.

---

## 6. Practical guidance

Distilled for someone facing the same problem — verifying a re-implementation, a port, a refactor, or a language migration of a stochastic system against a reference.

1. **Define the outcome coarsely and canonically, and write down what you are projecting away.** Include failure modes (timeout, give-up, resource exhaustion) as first-class outcomes; losing the ability to fail or stop early is a regression.
2. **Sample the reference to a stated missing-mass target rather than a fixed run count.** Use `f₁/n`. Set the target from your false-alarm budget: expected spurious flags per cycle ≈ (problems) × (check runs) × τ.
3. **Guard the `f₁ = 0` case with a run floor of 1/τ.** Without it, small samples declare themselves complete.
4. **Do not use a "k runs with no new outcome" stopping rule.** Measure it against a deep sample before trusting it; ours would have missed 37% of a support.
5. **Make the test two-sided and asymmetric.** A missing head outcome is decisive; a novel tail outcome is a question. Compute and publish both error rates per problem.
6. **Flag, do not fail — but put the flagging logic itself under test.** Ensuring correct functioning of the oracle harness is a critical prerequisite.
7. **Use disjoint seed ranges for reference and check,** or you may confuse testing determinism rather than reachability.
8. **Hold both sides to the same resource cap,** or resolve the difference explicitly.
9. **Never auto-admit a novel outcome into the reference set.** Human adjudication, recorded, with the seed attached resulting in either corrections to the reference, corrections to the system under test, or a deeper sampling run of the reference to get the novel outcome into the support.

The technique should transfer to any system with a discrete, canonical, moderately sized output space (possibly projected from a much larger system state space) and genuine run-to-run variation: simulation and agent-based model replication [19, 20], where this is essentially the docking problem; randomized and approximation algorithms; probabilistic programming system testing [18]; concurrent systems whose interleavings produce a bounded set of observable results; and — with the caveat that outcome canonicalisation becomes the whole problem — sampled generative model pipelines.

---

## 7. Limitations

**Reweighting inside the support is invisible.** The oracle compares membership, so a change that merely redistributes probability among outcomes it already knows will not fire. The head test recovers only the extreme case where a head outcome falls to approximately zero; an outcome dropping from 85% to 20% still appears in 100 runs with probability ≈ 1.

**Everything below the outcome key is invisible.** Two implementations reaching the same answers by entirely different internal routes are indistinguishable to this oracle. For a cognitive architecture whose *process* is the scientific claim, this is a real gap and needs a separate, possibly additional or complementary, testing strategy.

**The independence assumption is load-bearing.** The error arithmetic of §4 assumes check runs are independent draws from a stationary distribution, which holds here because each run starts from a cleared session and the sampler is non-adaptive. Any adaptive sampling bias would invalidate the plain `f₁/n` estimate; see [13, 14] for the corrected estimators.

**The oracle inherits its reference.** It measures agreement with a specific build of the reference implementation, not correctness, and **a change to the reference costs a full re-sampling**.

**Multiple comparisons are reported, not corrected.** Per-problem error rates and an expected spurious-flag count are given, but no family-wise correction is applied. The whole-cycle probability of at least one spurious novelty flag is 15.6% under our reference — small enough to leave alone, large enough that no single novelty flag should be treated as decisive on its own.

**One case study.** The calibration numbers are specific to a domain with small, discrete, canonical outcome spaces and a non-adaptive sampler. We make no claim about behaviour where outcomes are continuous, high-dimensional, or produced by a sampler with feedback.

---

## Acknowledgements

The Metacat architecture and its reference implementation are the work of James B. Marshall. Development of Petacat, its oracle harness, and the analysis reported here was supported by LLMs including both frontier-lab and open-weight models; all work was reviewed and tested by the author.

---

## References

[1] E. J. Weyuker. "On Testing Non-Testable Programs." *The Computer Journal*, 25(4):465–470, 1982. https://academic.oup.com/comjnl/article/25/4/465/366384

[2] M. D. Davis and E. J. Weyuker. "Pseudo-oracles for Non-testable Programs." In *Proc. ACM '81 Conference*, pp. 254–257, 1981.

[3] E. T. Barr, M. Harman, P. McMinn, M. Shahbaz, and S. Yoo. "The Oracle Problem in Software Testing: A Survey." *IEEE Transactions on Software Engineering*, 41(5):507–525, 2015. DOI: 10.1109/TSE.2014.2372785 · https://discovery.ucl.ac.uk/1471263/

[4] W. M. McKeeman. "Differential Testing for Software." *Digital Technical Journal*, 10(1):100–107, 1998. https://dblp.org/rec/journals/dtj/McKeeman98.html

[5] T. Y. Chen, F.-C. Kuo, H. Liu, P.-L. Poon, D. Towey, T. H. Tse, and Z. Q. Zhou. "Metamorphic Testing: A Review of Challenges and Opportunities." *ACM Computing Surveys*, 51(1), Article 4, 2018. DOI: 10.1145/3143561

[6] R. Guderlei and J. Mayer. "Statistical Metamorphic Testing — Testing Programs with Random Output by Means of Statistical Hypothesis Tests and Metamorphic Testing." In *Proc. 7th International Conference on Quality Software (QSIC 2007)*, pp. 404–409, 2007.

[7] T. Y. Chen, S. C. Cheung, and S. M. Yiu. "Metamorphic Testing: A New Approach for Generating Next Test Cases." Technical Report HKUST-CS98-01, Department of Computer Science, Hong Kong University of Science and Technology, 1998. (Reprinted as arXiv:2002.12543.)

[8] I. J. Good. "The Population Frequencies of Species and the Estimation of Population Parameters." *Biometrika*, 40(3–4):237–264, 1953.

[9] W. A. Gale and G. Sampson. "Good-Turing Frequency Estimation Without Tears." *Journal of Quantitative Linguistics*, 2(3):217–237, 1995.

[10] D. A. McAllester and R. E. Schapire. "On the Convergence Rate of Good-Turing Estimators." In *Proc. 13th Annual Conference on Computational Learning Theory (COLT 2000)*, pp. 1–6, 2000. https://www.learningtheory.org/colt2000/papers/McAllesterSchapire.pdf

[11] B. Efron and R. Thisted. "Estimating the Number of Unseen Species: How Many Words Did Shakespeare Know?" *Biometrika*, 63(3):435–447, 1976. https://academic.oup.com/biomet/article-abstract/63/3/435/270845

[12] A. Chao. "Nonparametric Estimation of the Number of Classes in a Population." *Scandinavian Journal of Statistics*, 11(4):265–270, 1984.

[13] M. Böhme. "STADS: Software Testing as Species Discovery." *ACM Transactions on Software Engineering and Methodology*, 27(2), Article 7, 2018. DOI: 10.1145/3210309 · https://mboehme.github.io/paper/TOSEM18.pdf

[14] M. Böhme, D. Liyanage, and V. Wüstholz. "Estimating Residual Risk in Greybox Fuzzing." In *Proc. 29th ACM Joint European Software Engineering Conference and Symposium on the Foundations of Software Engineering (ESEC/FSE 2021)*. DOI: 10.1145/3468264.3468570 · https://mboehme.github.io/paper/FSE21.pdf

[15] H. L. S. Younes and R. G. Simmons. "Probabilistic Verification of Discrete Event Systems Using Acceptance Sampling." In *Computer Aided Verification (CAV 2002)*, LNCS 2404, pp. 223–235, 2002.

[16] A. Legay, B. Delahaye, and S. Bensalem. "Statistical Model Checking: An Overview." In *Runtime Verification (RV 2010)*, LNCS 6418, pp. 122–135, 2010. https://link.springer.com/chapter/10.1007/978-3-642-16612-9_11

[17] Q. Luo, F. Hariri, L. Eloussi, and D. Marinov. "An Empirical Analysis of Flaky Tests." In *Proc. 22nd ACM SIGSOFT International Symposium on the Foundations of Software Engineering (FSE 2014)*, pp. 643–653. DOI: 10.1145/2635868.2635920

[18] S. Dutta, O. Legunsen, Z. Huang, and S. Misailovic. "Testing Probabilistic Programming Systems." In *Proc. ESEC/FSE 2018*, pp. 574–586. DOI: 10.1145/3236024.3236057 · https://www.cs.cornell.edu/~saikatd/papers/probfuzz-fse18.pdf

[19] R. Axtell, R. Axelrod, J. M. Epstein, and M. D. Cohen. "Aligning Simulation Models: A Case Study and Results." *Computational and Mathematical Organization Theory*, 1(2):123–141, 1996.

[20] U. Wilensky and W. Rand. "Making Models Match: Replicating an Agent-Based Model." *Journal of Artificial Societies and Social Simulation*, 10(4):2, 2007. https://www.jasss.org/10/4/2.html

[21] J. B. Marshall. *Metacat: A Self-Watching Cognitive Architecture for Analogy-Making and High-Level Perception.* PhD dissertation, Department of Computer Science, Indiana University, Bloomington, 1999. https://science.slc.edu/jmarshall/metacat/dissertation.pdf

[22] J. B. Marshall and D. R. Hofstadter. "The Metacat Project: A Self-Watching Model of Analogy-Making." *Cognitive Studies: Bulletin of the Japanese Cognitive Science Society*, 4(4):57–71, 1997. https://www.jstage.jst.go.jp/article/jcss/4/4/4_4_4_57/_article

[23] M. Mitchell. *Analogy-Making as Perception: A Computer Model.* MIT Press, 1993.

[24] D. R. Hofstadter and the Fluid Analogies Research Group. *Fluid Concepts and Creative Analogies: Computer Models of the Fundamental Mechanisms of Thought.* Basic Books, 1995.

[25] S. G. Eick, C. R. Loader, M. D. Long, L. G. Votta, and S. Vander Wiel. "Estimating Software Fault Content Before Coding." In *Proc. 14th International Conference on Software Engineering (ICSE 1992)*, pp. 59–65.

[26] K. Patel and R. M. Hierons. "A Mapping Study on Testing Non-testable Systems." *Software Quality Journal*, 26(4):1373–1413, 2018. DOI: 10.1007/s11219-017-9392-4

[27] S. Yoo. "Metamorphic Testing of Stochastic Optimisation." In *Proc. 3rd International Conference on Software Testing, Verification and Validation Workshops (ICSTW 2010)*, pp. 192–201. http://crest.cs.ucl.ac.uk/fileadmin/crest/sebasepaper/Yoo10.pdf

[28] S. Segura, G. Fraser, A. B. Sanchez, and A. Ruiz-Cortés. "A Survey on Metamorphic Testing." *IEEE Transactions on Software Engineering*, 42(9):805–824, 2016.

[29] A. Orlitsky, A. T. Suresh, and Y. Wu. "Optimal Prediction of the Number of Unseen Species." *Proceedings of the National Academy of Sciences*, 113(47):13283–13288, 2016. https://www.pnas.org/content/113/47/13283

[30] A. Chao and S.-M. Lee. "Estimating the Number of Classes via Sample Coverage." *Journal of the American Statistical Association*, 87(417):210–217, 1992.

[31] A. Arcuri and L. Briand. "A Hitchhiker's Guide to Statistical Tests for Assessing Randomized Algorithms in Software Engineering." *Software Testing, Verification and Reliability*, 24(3):219–250, 2014. DOI: 10.1002/stvr.1486

---

## Appendix A — Artefacts

These artefacts can be found in the GitHub repository for Petacat at https://github.com/MishkinBerteig/Petacat

| artefact                                     | role                                                                     |
| -------------------------------------------- | ------------------------------------------------------------------------ |
| `Metacat/docker/oracle.py`                   | Reference sampler: sharded, Good–Turing stopping band, checkpoint/resume |
| `Metacat/docker/make_derived_sets.py`        | Post-processing: support sets, p50 sets, absence probabilities           |
| `Metacat/docker/check_saturation.py`         | Re-computes `f₁/n` and the spurious-flag rate over growing subsamples    |
| `Metacat/oracle/raw/`                        | Raw reference emissions, never edited: 374,500 runs                      |
| `Metacat/oracle/derived/`                    | The support sets and p50 sets a comparison loads                         |
| `Metacat/ORACLE-USAGE.md`                    | The protocol                                                             |
| `Petacat/scripts/compare_to_metacat.py`      | The routine check; two flags, exits zero always                          |
| `Petacat/tests/unit/test_compare_harness.py` | Tests of the comparison's own decision logic                             |
| `Petacat/measurements/vs-metacat*.json`      | Cycle outputs                                                            |
| `Petacat/DISCREPANCIES4.md`                  | Every variation found, and its root cause                                |

## Appendix B — Notation

| symbol                               | meaning                                                          |
| ------------------------------------ | ---------------------------------------------------------------- |
| *R*, *P*                             | reference implementation; program under test                     |
| 𝒪                                   | outcome space (canonicalised stopping states)                    |
| π<sub>R</sub>, π<sub>P</sub>         | outcome distributions of *R* and *P* on a fixed input            |
| supp(π)                              | support: the set of outcomes with positive probability           |
| *N*, *n*                             | reference sample size; check sample size                         |
| f₁                                   | number of outcomes observed exactly once in a sample             |
| M̂₀ = f₁/N                           | Good–Turing missing-mass estimate                                |
| τ<sub>upper</sub>, τ<sub>lower</sub> | saturation band on M̂₀ (10⁻⁴ and 6 × 10⁻⁵ here)                  |
| p50(x)                               | smallest set of most-frequent outcomes whose shares sum to ≥ 0.5 |
| α(x)                                 | per-check probability of a spurious novelty flag on problem *x*  |

## Appendix C - Letter-String Analogy Problems

This is the complete set of problems along with a small sample of "solutions" that both Metacat and Petacat produce.
