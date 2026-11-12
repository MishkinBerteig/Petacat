# Rule scout (S3.3.6; rules.ss:397-442)
#
# Abstract a rule from the slippages underlying a horizontal mapping.  This runs
# the real abstraction pipeline: intrinsic changes from individual slippages,
# extrinsic changes from symmetries, "all components of X" changes, then the
# rule-abstraction heuristics that sieve out redundant changes.
from server.engine.rules import build_rule_from_bridges, Rule, RuleClause

# rules.ss:399-412.  The verbatim branch is drawn FIRST and unconditionally, at
# 1%, whatever the workspace looks like: S3.3.6's "some (small) chance that the
# codelet will simply ignore the bridges".  It is not a fallback for having no
# bridges -- taking it whenever the bridge set was empty meant a verbatim rule
# with probability 1 for the whole early run, and a verbatim top rule is
# vacuously supported, so it opened the answer-finder gate and translated
# straight into the modified string as an answer.
verbatim_probability = meta.get_param('verbatim_rule_probability')
if prob(verbatim_probability):
    rule_type = rng.pick([role('rule_type.top'), role('rule_type.bottom')]) if justify_mode else role('rule_type.top')
    result_string = workspace.modified_string if rule_type == role('rule_type.top') else workspace.answer_string
    if result_string is None:
        fizzle()
    letters = [letter_node(ch) for ch in result_string.text]
    # v2.0 Base: letter_node returns a falsy Absent token for a symbol with no node, never None.
    if any(not l for l in letters):
        fizzle()
    rule = Rule(rule_type, [RuleClause(clause_type=role('clause_type.verbatim'), verbatim_letters=letters)], workspace=workspace)
    if verbose:
        say('proposing-verbatim-rule', rule_type)
    rule.set_verbatim_rule_information()
    rule.time_stamp = codelet_count
    rule.compute_quality(meta)
    rule.transcribe_to_english(meta)
    # rules.ss:411 -- a verbatim rule's evaluator goes in at %low-urgency%,
    # a fixed value.  Ranking it by the rule's own quality gave the least
    # informative rule MetaCat can make the same standing as the best.
    post_codelet('rule-evaluator', meta.get_urgency('low'), structure=rule)
    fizzle()

# rules.ss:413-416.  Otherwise a rule has to actually be POSSIBLE: every letter of
# both strings of the pair covered by rule-describable bridges.  Without the gate,
# rules were abstracted from whatever partial bridge set happened to exist -- "change
# the rightmost letter to d" from a lone c-d bridge, long before the reference
# allows any rule at all.  The flags are set once per update cycle by
# check_if_rules_possible (run.ss:305), so a scout reads the last cycle's verdict.
possible_rule_types = workspace.get_possible_rule_types()
if not possible_rule_types:
    if verbose:
        say('no-rule-possible')
    fizzle()

rule_type = rng.pick(possible_rule_types)
rule = build_rule_from_bridges(
    rule_type, get_built_bridges(role('bridge_type.top') if rule_type == role('rule_type.top') else role('bridge_type.bottom')), slipnet,
    rng=rng, temperature=temperature.value, themespace=themespace, meta=meta,
    workspace=workspace,
)
if rule is None:
    if verbose:
        say('rule-objects-not-describable')
    fizzle()

rule.time_stamp = codelet_count
rule.compute_quality(meta)
rule.transcribe_to_english(meta)

# rules.ss:442 -- %high-urgency%, fixed.
post_codelet('rule-evaluator', meta.get_urgency('high'), structure=rule)
