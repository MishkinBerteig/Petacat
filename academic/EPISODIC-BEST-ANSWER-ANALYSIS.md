# Selecting an Episode's Best Conceptual Answer

Analysis date: 2026-09-06. Status: proposal for discussion, not a frozen study
protocol. No new Metacat or Petacat engine runs were performed for this review.
No study harness, engine, or manuscript was changed.

## Conclusion

The intended object of comparison is the conceptual result reached during an
episode, not its trajectory. Requiring sequence matching would change the
research question unnecessarily. The existing last-successful-answer endpoint
remains a legitimate fixed-horizon behavioral projection; it is not, however,
the only or the strongest available approximation to the best answer.

Metacat has TWO relevant native evaluations:

1. A numerical answer-quality score combining rule quality and answer-time
   temperature.
2. A qualitative pairwise preference based on coherence, justification,
   comparable-rule abstractness, and richness of ideas. This judgment consults
   remembered snags and need not agree with the numerical score.

My recommendation is to evaluate best-by-native-quality and best-by-native-
conceptual-preference as separate episode-level projections, retaining the old
last-success projection as a baseline. Lowest answer-temperature is a useful
additional sensitivity analysis. These can all be computed from the same episode
without constructing an oracle over ordered sequences.

For the strongest specifically memory-dependent evidence, add a small, separate
memory-conditioned answer-judgment case, rather than assuming that repeated
answer generation exercises every aspect of episodic understanding.

## Sources and Scope

The primary sources are Marshall's [1999 dissertation](https://science.slc.edu/jmarshall/metacat/dissertation.pdf)
and the [original Metacat 1.2 archive](https://science.slc.edu/jmarshall/metacat/Metacat-1.2.tgz).
The complete dissertation text was searched; the relevant discussions, worked
examples, and limitations were examined, including visual inspection of Figures
4.14 and 5.12 and the comparison panels on printed page 253. This is a focused
analysis of answer evaluation across the dissertation, not a claim to have
independently validated every mechanism described in its 306 pages.

Dissertation reading map, using PRINTED page numbers:

| Section | Pages | Relevant topic |
| --- | --- | --- |
| 1.5.6 | 28-30 | Temperature and quality |
| 2.3.3-2.3.5 | 47-49 | Memory, comparison, and justification |
| 3.3.5 | 96-103 | Rule-quality measures |
| 4.6 | 178-184 | Numerical and qualitative commentary |
| 4.7.1-4.7.5 | 184-200 | Answer descriptions, snags, comparison, reminding |
| 5.2.3 | 247-255 | Worked comparisons |
| 5.3 | 256-270 | Evaluation limitations |
| 6.2 | 277-280 | Proposed extensions |

The dissertation deliberately separates abstract answer descriptions from full
processing histories. It also documents incorrect conceptual judgments: a
mischaracterized `yyz` can be preferred to `wyz` because its stored themes appear
richer. Native preference is therefore a target for PORT FIDELITY, not a claim
of objectively correct human aesthetic judgment.

All Scheme line references below refer to the unmodified archive, not to the
Python port or to shifted line numbers after patch application. The archive
SHA-256 matches [the repository manifest](../Metacat/manifest.json):

`ec73bdc18b4e91f5a9f38fcc5af06028b8d7fe0c4bcfdbcc50e6b3c239971f4d`

All 48 extracted upstream file hashes were checked against that manifest with
no mismatches. `answers.ss`, `memory.ss`, `trace.ss`, `formulas.ss`, and
`workspace-objects.ss` are byte-identical in the inspected reconstructed source.
The changes to `rules.ss` concern rule application to letter/group constituents,
not its quality functions. Upstream source is not copied into this repository.

## 1. Native Numerical Answer Quality

`trace.ss:392-403`, in `make-answer-event`, defines:

```text
Q(answer) = round(0.60 * R(top_rule) + 0.40 * (100 - T_answer))
```

`Q` is the number the program reports as answer quality and stores in episodic
memory. Larger is better according to this metric. `T_answer` is the temperature
captured when the answer event is created (`trace.ss:231-235`).

Important details:

- It uses the TOP rule's absolute quality, not the average of the top and bottom
  rules and not the best of all rules encountered during search.
- The reporting path first updates the system, then handles any outstanding
  clamp, then creates the answer event (`answers.ss:20-32`). Read the saved answer
  description's temperature and quality, not a later run's current temperature.
- `get-quality` calls `get-absolute-quality`. A comment in `memory.ss:429` calls
  the stored value relative quality, but that comment disagrees with the invoked
  implementation. The executable definition is the relevant authority.
- The separate relative rule quality is a rank among currently existing
  workspace rules (`rules.ss:244-251`). It is context-dependent and is not the
  appropriate substitute for the absolute quality used in `Q`.
- `compute-rule-intrinsic-quality` is another, older-looking function. It is not
  the rule-quality value used by `Q`; its getter has no other callers in the
  inspected upstream source. Its verbatim-rule constant must not be substituted
  for the active formula.

### What Rule Quality Includes

`rules.ss:1544-1637` defines:

```text
R = round((U / 100) * (3*A + 2*S) / 5)
```

Here `U`, `A`, and `S` are uniformity, abstractness, and succinctness, each on a
0-100 scale. Consequently, conceptual depth is ALREADY part of native numerical
answer quality; temperature is not its sole determinant.

- **Uniformity:** rewards compatible descriptive choices across rule clauses.
  It considers object-description attributes, consistency of relational versus
  literal changes, and mixing intrinsic and extrinsic clause types. The combined
  uniformity is adjusted nonlinearly before entering `R`.
- **Abstractness:** uses conceptual depths of the rule's object-description
  attributes, intrinsic change descriptors, and extrinsic swap dimensions.
  The nonzero category averages are averaged, passed through the native sigmoid,
  scaled, and rounded. This is not an average over every active Slipnet node.
- **Succinctness:** uses weighted clause cost. An intrinsic clause costs one;
  an extrinsic clause naming multiple objects costs two, otherwise one.
  For ordinary rules, `S = round(400 / (3 + total_clause_cost))`.
- **Special cases:** identity has `U=A=S=100`; verbatim copying has `U=S=100`
  and `A=0`, yielding active rule quality 40, not 10.

The practical implication is that blindly preferring deeper concepts or shorter
rules would discard safeguards already present in the native score. A deep but
inconsistently described rule can score poorly.

### Candidate: Best-Q Answer

Among successfully reported answers in the episode, select the maximum saved
`Q`. Keep all tied answer letters as an unordered co-winner set, or declare a
deterministic tie-break before collecting the main data. Do not let insertion
order silently turn this into another first/last-answer measure.

This is the clearest quantitative replacement for the historical endpoint. It
is simple, native, and cheap to compute. It remains an assessment of a specific
answer occurrence: the same letters reached using different rules can have
different qualities. Rank occurrences before collapsing their answer letters.
Here "best" always means best encountered within the fixed episode budget,
not the globally best answer the system could ever produce.

## 2. Native Conceptual Preference

`answers.ss:434-882`, especially the final decision at `825-882`, implements
the program's explicit comparison of two answer descriptions. This is more
directly responsive to "which answer does Metacat consider conceptually better?"
than inventing a new weighted score.

The branch order matters:

1. **Both answers incoherent:** prefer one only if its average theme abstractness
   and number of themes are both no greater than the other's, with at least one
   strictly smaller. Otherwise give no explicit winner in this branch.
2. **Only one incoherent:** prefer the coherent one.
3. **Both coherent, different numbers of unjustified themes:** prefer fewer
   unjustified themes, after removing the themes justified by remembered snags.
4. **Still unresolved, same themes and structurally comparable top rules:**
   prefer the answer with the more abstract top rule.
5. **Still unresolved, different theme counts:** prefer more themes.
6. **Otherwise:** no explicit winner; report the answers' numerical quality
   categories. This fallback does not return a strict preference merely because
   the numerical qualities differ.

The source does not implement an episode-wide `best-answer` function. Extending
these pairwise judgments to a group is therefore a declared evaluation choice,
not an existing native total ranking.

### Coherence Is Not Simply More Depth

`answers.ss:885-916` computes average theme abstractness from the stored vertical
themes and unjustified themes. For each theme, the dimension's conceptual depth
is averaged with the relation's abstractness: identity contributes 0, `diff`
contributes 50, and other relations contribute their conceptual depths.

Writing `H` for average theme abstractness and `A` for top-rule abstractness,
the native incoherence predicate is:

```text
H > 50 and A < H and H - A > 25
```

It detects an abstract interpretation of the relationship between situations
combined with a substantially more literal rule. It is directional. A highly
abstract rule with simple themes is not rejected by the reverse inequality.

Maximizing `A-H`, or minimizing `abs(A-H)`, is NOT the native preference rule.
The standalone `coherence-phrase` table at `answers.ss:919-926` is never called
elsewhere in the original source. The port's continuous `coherence_score` is a
useful diagnostic convention, not evidence of a native continuous best-answer
ranking.

### Where Episodic Memory Changes the Judgment

`get-snag-justified-themes` (`answers.ss:285-299`) asks memory for a snag matching
the problem and top-rule clauses. It identifies themes present in the answer
but absent from that snag, and intersects them with the answer's unjustified
themes. Those themes can then be treated as snag-justified during comparison.
Matching uses structural rules, not English descriptions (`memory.ss:84-96`).

Thus the same stored answer descriptions can receive a different conceptual
comparison after relevant experience has been remembered, even if their saved
numerical qualities do not change. Score all candidates against the SAME
end-of-episode memory if the intended question is what the system understands
after the episode. Do not compare one answer's earlier judgment with another's
later judgment under different memories.

There is an important scope distinction: ordinary solve-mode `answer-finder`
passes an empty unjustified-slippage list when reporting an answer
(`answers.ss:999-1001`). Repeated solve-only episodes therefore do not by
themselves exercise this snag-based reassessment of suggested, partly
unjustified answers. They still exercise memory's restriction on rediscovering
stored answers and the quality of the alternatives found.

### Candidate: Conceptually Preferred Answer

At episode end, compare the stored answers using the native preference criteria.
For eight answers, there are at most 28 unordered pairs; this is evaluation of
answer descriptions already in memory, not additional search runs.

One defensible output is the unordered set of answers that no other candidate
is explicitly preferred to. Retain genuinely unresolved cases rather than
claiming that Metacat supplies a unique best answer in every episode. Check
order symmetry and whether the proposed aggregation is well-defined; no
preference-cycle behavior has been empirically assessed here. A sequential
winner-takes-next tournament is not a substitute for defining this properly.

If a single winner is required, choosing maximum `Q` among these candidates,
followed by a fixed tie-break, is a possible study-defined hybrid. It must be
labelled as such. Do not describe the added tie-breaking as original Metacat
behavior.

## 3. Other Candidates and Their Limitations

| Candidate | Native grounding | Suggested role |
| --- | --- | --- |
| Maximum answer quality `Q` | Explicit reported and stored score | Primary quantitative best-answer projection |
| Native qualitative preference | Explicit better-answer decision, including memory-conditioned justification | Conceptual companion projection |
| Minimum answer-time temperature | Workspace organization and rule support | Sensitivity analysis, not a complete quality definition |
| Maximum top-rule quality `R` | Uniformity, abstractness, succinctness | Diagnostic isolating the rule component |
| Highest abstractness among coherent answers | Uses native quantities, but adds a new selection policy | Optional exploratory projection |
| Coherent, justified, conceptually rich answers | Components of native preference | Use the actual priority order rather than a new arbitrary weighted sum |
| Highest salience | Allocation of attention to workspace objects | Reject as an answer-quality selector |
| Highest memory activation | Similarity to a recently stored answer | Reject as an answer-quality selector |
| Deepest active Slipnet concepts | Potentially includes irrelevant or clamped concepts | Reject in favor of concepts actually used by the answer's rules/themes |
| Last successful answer | Existing fixed-horizon endpoint | Retain as historical baseline |

Temperature is computed, when unclamped, as 70% workspace average unhappiness
plus 30% a rule-support factor (`formulas.ss:62-79`). It captures structural
organization rather than directly scoring conceptual elegance. Read the
temperature of successful answers, not the minimum temperature reached anywhere
during a failed search.

Salience is specifically the wrong direction to treat as intrinsic merit:
workspace-object salience combines relative importance with UNHAPPINESS and can
be clamped to 100 (`workspace-objects.ss:519-559`). An object may attract
attention because it needs work, not because an answer involving it is best.

Memory activation is also distinct: a newly stored answer is assigned 100, and
older answers' activations depend on distance from it (`memory.ss:97-104,
209-227`). Selecting by activation risks selecting the newest or most similar
answer rather than the best one. Similarity and desirability are different
questions.

## 4. What the Existing Data Can Already Tell Us

A historical raw reference archive was located at the logical project path
`Metacat/oracle/raw/episodes.json.gz` in the separate Metacat checkout. It is
not currently part of the paper supplement. This refines the earlier review's
statement about the absence of raw episodic reference evidence in that
supplement: the raw archive does exist and was inspected for this analysis.

Archive SHA-256:

`7ba3d53dc3b80368eeb1e19a36762d5faa73733b41928fa20bb6d60cf30ff48b`

Its declared parameters are 500 episodes per problem, eight runs per episode,
19 problems, seed base 100000, and a 100000-codelet cap per run. It contains
9500 episodes and 76000 run records. The records include `quality` and
`answer_temperature`, but not the structural rule and theme fields needed to
reconstruct native qualitative comparisons.

Read-only checks found no discrepancies in episode lengths, per-problem episode
counts, unique episode identities, seed/index progression, successful-answer
increments in memory counts, missing-score sentinels, or successful score ranges.
These are archive-consistency checks, NOT an independent regeneration of its
engine results or a verification of its historical build provenance.

For each episode, successful records exclude `*CAP*`, `*NONE*`, and `*ERROR*`.
The last-success baseline is the final such record. Best-Q candidates include
ALL successful records tied at the episode's largest saved quality; coolest
candidates include ALL tied at its smallest saved answer temperature.

| Saved-data observation | Count | Fraction of 9499 answering episodes |
| --- | ---: | ---: |
| Last successful run itself has maximum quality | 1172 | 12.34% |
| Last-success answer letters appear among maximum-quality candidates | 3809 | 40.10% |
| Maximum-quality and minimum-temperature candidates share no answer letters | 3214 | 33.84% |
| Maximum quality is tied across multiple answer strings | 890 | 9.37% |

One episode has no successful answer and is retained as a separate no-answer
outcome, not assigned a fictitious quality of zero. Mean best quality among
answering episodes is 86.61 versus 69.22 for the last successful answer.

These observations support using an explicit best-answer definition. They do
not invalidate the old endpoint as a behavioral comparison. Nor does the
larger best-of-eight score establish a learning benefit: taking a maximum over
several opportunities raises scores even without memory-dependent learning.

There is no new port comparison in these numbers. The archived port episode
records inspected in `academic/data/vs-metacat.json` retain answer-state strings,
not the corresponding quality and temperature measurements. They cannot be
retrospectively assigned Best-Q or native conceptual winners from those strings.
The historical cap mismatch also remains unresolved for a new comparison.

## 5. Testing Conceptual Results Without Sequence Oracles

For a fixed problem and episode budget, use a declared reduction:

```text
episode -> its selected best conceptual result
```

The answer search still runs normally and retains episodic memory. At the end,
the evaluator examines the answer descriptions already stored by the system,
computes the selected result, and emits a compact episode record. There is no
need to persist an ordered answer list, codelet history, Slipnet activation
history, or a set of possible trajectories as the comparison target.

A minimal record can contain:

- Episode identifier, seed specification, problem, fixed budget, and completion
  status, including caps or errors as separate accounting fields.
- Best-Q answer letters or unordered co-winner letters, quality, and the
  corresponding answer-time temperature.
- Conceptual-preference winner letters or unordered unresolved alternatives.
- Only the selected answer descriptions' conceptual summaries: vertical themes,
  top-rule abstractness, coherence, and justification status. A structural rule
  signature for a selected answer is optional diagnostic evidence, not a demand
  to match internal execution histories.
- Last successful answer as the legacy baseline; minimum-temperature winner
  only if that projection is included in the declared evaluation.

Exact field choices should be agreed before a new collection. Not retaining
other answer descriptions means that arbitrary later changes to the definition
of best may require new data. That is a reason to settle a small set of useful
projections now, not a reason to collect every sequence.

### Statistical Interpretation

Independent reset episodes remain the sampling units. A deterministic reduction
to Best-Q letters or an unordered co-winner set does not require the runs inside
an episode to be independent. Good-Turing and support/p50 checks can target the
distribution of the DECLARED reduced outcome. The full episode need not itself
be the observable outcome.

Do not count tied winners as independent draws. An unordered winner set can be
one categorical observation, or the protocol can choose exactly one winner with
a declared tie-break. Checking each member of a winner set against a marginal
letter oracle is a different test from checking the complete set as an outcome.

Use the score to SELECT the answer, not automatically as an exact support key.
Joint keys containing every numerical and conceptual field may need far more
reference data. Winner letters give the closest extension of the existing
method; a separate predeclared theme-based projection can test whether matching
letters also express similar concepts. The original quality categories provide
one native option for coarse quality reporting, but are not calibrated
statistical confidence levels.

Reference construction, held-out validation, and small port checks must all
apply the same selection policy. If several projections can trigger a failure,
calibrate that combined decision rule, not just each projection in isolation.
Freeze choices before using new held-out data. Do not silently add unexpected
port winners to the oracle.

The same expensive reference episodes can feed all agreed projections. Their
additional evaluation cost is small compared with search; it is not another
large campaign per metric. Measure that cost rather than assuming a speedup.
The question remains whether a large reusable reference enables small,
informative checks of these conceptual results.

## 6. A Direct Memory-Conditioned Judgment Case

The dissertation's printed page 253 compares `aaabaaa` for
`eqe -> qeq; abbba -> ?` with `aaabccc` for
`eqe -> qeq; abbbc -> ?`, before and after remembering a relevant snag.
Afterward, Metacat explicitly prefers `aaabccc` because its otherwise
unjustified idea avoids the remembered obstacle. This illustrates a changed
conceptual conclusion, not a requirement to reproduce a path.

A focused extension could use a fixed experience stage followed by a fixed
answer-justification/comparison query. The observed result would be only the
final preference, justification classification, and conceptual reason category.
The supplied answers are targets of a judgment test, not claimed discoveries
of the solve-mode generator.

Use a memory-retained arm, a matched memory-cleared arm, and an irrelevant-snag
control. For an end-to-end experience stage, retain all scheduled trials,
including those that did not encounter the needed snag; do not silently select
only successful exposures. A hand-constructed matching snag is useful as a
deterministic component test, but must be labelled separately from naturally
acquired experience. Both approaches avoid a sequence-distribution oracle.

This is additional evidence, not an instruction to expand the main study into
every possible training history. It targets a mechanism the pure eight-repeat
solve protocol does not directly exercise.

## 7. What Is Already Implemented in Petacat

The necessary concepts are substantially present:

| Mechanism | Existing implementation |
| --- | --- |
| Numerical answer quality | [compute_answer_quality](../server/engine/answers.py), line 51 |
| Rule quality and its three components | [Rule.compute_quality](../server/engine/rules.py), line 1115 |
| Saved quality, temperature, abstractness, themes, signatures | [AnswerDescription](../server/engine/memory.py), line 18 |
| Directional coherence predicate | [AnswerDescription.is_coherent](../server/engine/memory.py), line 69 |
| Structured pairwise verdict and priority order | [AnswerComparison.verdict](../server/engine/answer_comparison.py), line 1184 |
| Snag-based justification | [snag_justified_themes](../server/engine/answer_comparison.py), line 180 |
| Quality recomputation after the final update | [_report_answer_locked](../server/engine/codelet_dsl/builtins.py), line 2492 |

Existing tests include numeric rule-quality fixtures, coherence and preference
priority cases, equal-letter answer comparisons, snag justification, and the
worked conceptual comparison. See [test_rule_quality.py](../tests/seed_unit/test_rule_quality.py),
[test_answer_comparison.py](../tests/seed_unit/test_answer_comparison.py), and
[test_dissertation_parity.py](../tests/module/test_dissertation_parity.py).
Their definitions were inspected; they were not executed in this review.

What is missing is a frozen cross-engine episode-reduction protocol and its
reference/port dataset, not an entirely new theory of answer quality. The
upstream comparison returns prose; an evaluator needs an audited structured
equivalent of its decision branches, not ad hoc English parsing. The port's
existing preferred-answer field alone is insufficient to distinguish two
candidate descriptions that spell the same answer. Winner identity and the
conceptual summary must be handled before collapsing to letters.

Before collection, verify the selector and score extraction on small fixed
fixtures independently of the port's own implementation. Otherwise an error
in the port's evaluator could contaminate both the observations and their
interpretation. Such verification is a proposed next step, not completed work.

## Proposed Decision

Keep the study at the conceptual-result level. Prefer the native Best-Q
projection for a simple quantitative endpoint and the native conceptual
preference projection for a richer account of what the system considers best.
Keep last-success as a baseline and lowest answer-temperature as a sensitivity
check if desired. Add the focused memory-conditioned judgment case to test
understanding that actually changes through remembered experience.

Do not substitute salience, raw activation, or an invented depth/coherence
weighted sum for mechanisms that Metacat already has. Do not require ordered
trajectory matching. Settle ties, conceptual summaries, and failure accounting
before selecting budgets or starting any new remote runs.
