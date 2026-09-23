# Style-Diff Integrity Review

2026-09-08. Reviewed `support-set-oracles-final.md.diff` before changing the
submission manuscript. All 31 hunks matched the existing source exactly.
The proposed diff is not exclusively stylistic. The applied version accepts
its style edits except for the protections recorded below. No new scientific
claim, experiment, study result, or reference is approved by this review.

## Material Findings

- The missing-answer guarantee lost the condition that the answer belongs to
  the tested p50 head. A deleted answer outside that head need not be flagged.
- The human-speech example changed **at least half** to **half** and weakened
  its hypothetical status and sampling assumptions.
- Winner coverage became conditional only on an episode answering, omitting
  completion. Incomplete error episodes can answer but contribute no winner.
- The appendix could be read as excluding all tied winners, rather than
  counting the earliest selected winner. A retry restriction also lost its
  scientific-observation qualifier.
- Several rewrites made categorical claims about independence, detection,
  sampling difficulty, or the programs' underlying behaviour that the original
  qualified or did not assert.
- Historical intervention attribution, MLX hardware identification, pilot-plan
  history, and incomplete-attempt accounting became stronger or less precise.
- Cost descriptions changed partial omissions to complete omissions, or treated
  failed coverage as an established cost-benefit result.
- The packaging description incorrectly said the original licence was not
  redistributed. The existing licence-preservation wording is retained.
- The process-novelty claim in the abstract, bounded prior-work comparison, and
  explicit future population-selection hypothesis remain as approved earlier.

The review also accepts many deletions of repetitive caveats where their
substance remains clearly stated elsewhere. The protected passages below are
not a count of distinct scientific errors: some preserve prior author direction
or prevent ambiguity rather than correct a numerical mistake.

## Protected Passages

Line numbers refer to the applied Markdown source. The accompanying
`style-review-2026-09-08.json` records each proposed and retained passage exactly.
These identify the style-review revision by its recorded hash; subsequent
pagination-only edits can shift the source-line links and change artifact hashes.

1. [Source line 4](../support-set-oracles-final.md#L4): Keep the author's explicit process-novelty contribution in the abstract; the proposed list alone no longer states that claim.

2. [Source line 36](../support-set-oracles-final.md#L36): Sharing a seed does not solve cross-language comparison; saying it does not help at all is a stronger, unsupported claim.

3. [Source line 51](../support-set-oracles-final.md#L51): Retain the explicit distinction between an investigation flag, a port defect, and an incomplete reference, without the less precise 'port may be right' shorthand.

4. [Source line 157](../support-set-oracles-final.md#L157): A concentrated large or infinite answer space can be manageable; changing 'can be' and 'may be' into categorical sampling claims is not merely stylistic.

5. [Source line 328](../support-set-oracles-final.md#L328): The method compares observed answer populations, not the unknown complete populations.

6. [Source line 346](../support-set-oracles-final.md#L346): Coverage requires a complete answered episode; an incomplete error episode may contain answers but supplies no winner.

7. [Source line 349](../support-set-oracles-final.md#L349): The proposed sentence assigns an independence assumption to p50 head selection itself. Keep the original separation between deterministic selection and probabilistic sampling assumptions.

8. [Source line 387](../support-set-oracles-final.md#L387): Keep explicit that reference qualification neither validates a p50 head nor proves port fidelity; the new cross-reference covered only transfer of the bound.

9. [Source line 478](../support-set-oracles-final.md#L478): Fresh audit samples and known-defect tests remain important; saying they guard against adaptive reuse can suggest a guarantee not established here.

10. [Source line 517](../support-set-oracles-final.md#L517): The certainty-of-detection statement applies only to a deleted answer included in the tested head. The proposed wording drops that condition.

11. [Source line 552](../support-set-oracles-final.md#L552): The theory permits the programs to agree or differ. The proposed blanket assertion that they have different distributions is not an assumption or a result of this general argument.

12. [Source line 563](../support-set-oracles-final.md#L563): The unconditional detection calculation does not establish that conditioning on observing every head member leaves the odds unchanged.

13. [Source line 596](../support-set-oracles-final.md#L596): The novelty claim concerns the complete workflow, not inventing a frozen reference record alone; retain the original bounded comparison with prior work.

14. [Source line 625](../support-set-oracles-final.md#L625): Preserve the scope limit on the prior-work novelty search.

15. [Source line 725](../support-set-oracles-final.md#L725): The new wording identifies the historical MLX execution as GPU execution. The incomplete historical build record does not establish that additional hardware claim.

16. [Source line 745](../support-set-oracles-final.md#L745): The direction reversal can conceal the error in the unchanged displayed string; the proposed version makes this an unconditional transformation claim.

17. [Source line 753](../support-set-oracles-final.md#L753): Keep the reported historical intervention attributed to its development account, including which two flagged outcomes it reproduced and the separate evidence for the third.

18. [Source line 790](../support-set-oracles-final.md#L790): The saved episodic ratios do not certify the target; the proposed wording can imply all 500-episode references are known to fall short.

19. [Source line 810](../support-set-oracles-final.md#L810): Endpoint checks do not test all implemented reminding and explanatory behaviours or establish improved learning. The new last sentence overstates their scope.

20. [Source line 909](../support-set-oracles-final.md#L909): Incomplete attempt records are not extra independent data, but verified results from interrupted work can be admitted once. 'Never counted' obscures that accounting.

21. [Source line 915](../support-set-oracles-final.md#L915): Retain the explicit post-failure continuation description without the new assertion that the study departed from its original plan in exactly one respect.

22. [Source line 1006](../support-set-oracles-final.md#L1006): The records do not fully include the listed overheads. Saying they omit every listed category changes the cost-accounting claim.

23. [Source line 1022](../support-set-oracles-final.md#L1022): Keep the precise pilot-reuse and freeze protocol without asserting the existence or contents of a distinct pre-pilot plan.

24. [Source line 1065](../support-set-oracles-final.md#L1065): Failed coverage is not evidence of learning-induced collection efficiency. 'The cheap construction here was no saving' instead makes an unmeasured cost-benefit claim.

25. [Source line 1073](../support-set-oracles-final.md#L1073): Retain the author's explicit, conditional future hypothesis that another conceptually meaningful population may suit Good-Turing collection better.

26. [Source line 1111](../support-set-oracles-final.md#L1111): Keep the distinction between conditional winner coverage and how often an episode answers or completes.

27. [Source line 1167](../support-set-oracles-final.md#L1167): Unequal-budget comparisons do not establish superiority; saying they settle nothing about cost or detection discards the descriptive evidence they do provide.

28. [Source line 1184](../support-set-oracles-final.md#L1184): Proposed memory controls would help assess detection; the data do not establish in advance that those controls would resolve the question.

29. [Source line 1200](../support-set-oracles-final.md#L1200): Keep 'not all' costs rather than 'none', and keep future controlled comparisons conditional rather than guaranteed to quantify benefit.

30. [Source line 1226](../support-set-oracles-final.md#L1226): Applications beyond the evaluated case remain proposals, not demonstrated transfers.

31. [Source line 1233](../support-set-oracles-final.md#L1233): The speech example must retain 'at least half', sampling assumptions as well as the sampling unit, and its status as a proposed experiment.

32. [Source line 1260](../support-set-oracles-final.md#L1260): The proposed phrase 'as easily as a defect' suggests an unsupported relative likelihood; preserve the existing sampling-versus-defect caveat and hypothetical application status.

33. [Source line 1325](../support-set-oracles-final.md#L1325): The original licence is retained. Claiming it is not redistributed contradicts the existing licence-preservation description.

34. [Source line 1383](../support-set-oracles-final.md#L1383): One earliest selected tied winner contributes to the counts; saying tied winners are excluded can describe a different selection rule.

35. [Source line 1432](../support-set-oracles-final.md#L1432): Retain the distinction between static implementation differences and demonstrated episode-level root causes.

36. [Source line 1510](../support-set-oracles-final.md#L1510): The restriction concerns replacement scientific observations, not every possible diagnostic retry.

37. [Source line 1130](../support-set-oracles-final.md#L1130): The value is unchanged; retaining its numeric spelling keeps the existing numeric-inventory guard without weakening that guard.

38. [Source line 506](../support-set-oracles-final.md#L506): An empirical reference share is not an established lower bound on a port probability; the proposed wording asserted that it could not be a lower bound at all.

## Verification Scope

The incoming diff preserves all 34 cited reference keys, 12 generated-table
references, 34 section labels, and nine displayed equations. Its sole lost
numeric token was `99`, rewritten as `Ninety-nine`; the value was unchanged.
The applied source retains `99` so that the existing numeric-inventory check
needs no exception. The existing scope restrictions remain in force.

All 85 tests pass. The TDD phrase check accepts sentence-initial capitalization;
no numerical or scientific-content check was relaxed. The anonymous-format and
all-page text-bound checks pass, all 24 PDF fonts are embedded, and no overfull
boxes or undefined citations/references remain. The 30-page PDF and changed
sections were visually inspected. A clean extraction of the source bundle
rebuilds identical LaTeX and identical extracted PDF text. The experimental
bundle and all 29 guarded earlier-draft/evidence files are unchanged.

The normal builder and submission verifier record the applied source and
artifact hashes in `build.json` and `verification.json`. The earlier draft
and shared evidence remain under the existing 29-file preservation guard.
No engine experiment, commit, push, or submission is part of this update.
Final manual author review and approval remain pending.
