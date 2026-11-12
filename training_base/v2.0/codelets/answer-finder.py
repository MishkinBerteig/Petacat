# v2.0 Base: wait until every letter of the Workspace has its letter-category description.
# An answer built while a symbol is still unperceived silently drops it: a Letter with no
# letter-category node has no image, so the answer string is generated without it.  The scouts
# that perceive a symbol (symbol-scout, symbol-builder) are posted every update cycle, so the
# wait ends.  Nothing is drawn here: this runs before the first prob() of the seed body, and
# on a problem with no unperceived symbol it changes nothing.
from server.engine.workspace_objects import Letter
letter_category = role('dimension.letter_category')
if letter_category and any(
    isinstance(o, Letter) and o.get_descriptor_for(letter_category) is None
    for o in get_objects()
):
    fizzle()

# Answer finder (S3.4)
# Scheme: answers.ss:928-1000, step for step.
from server.engine.answers import compute_answer_quality
from server.engine.formulas import temp_adjusted_values

# Codelets "probabilistically decide whether or not to attempt answer creation on
# the basis of the overall strengths of the horizontal and vertical mappings
# between strings (as long as these mappings are weak, codelets are unlikely to
# try)."  Scheme: (stochastic-if* (1- (^3 (* (% top-strength) (% vertical-strength)))))
# -- a graded discouragement, not a threshold.
top_strength = mapping_strength(role('bridge_type.top'))
vert_strength = mapping_strength(role('bridge_type.vertical'))
if prob(1.0 - ((top_strength / 100.0) * (vert_strength / 100.0)) ** 3):
    if verbose:
        say('mappings-not-strong-enough')
    fizzle()
if verbose:
    say('trying-to-translate')
    say('top-mapping-strength', top_strength)
    say('vertical-mapping-strength', vert_strength)

supported = workspace.get_supported_rules(True)
if not supported:
    if verbose:
        say('no-supported-rules')
    fizzle()

# Rules are picked by temperature-adjusted *strength* (answers.ss:943-945); a rule's
# internal strength is its relative quality (rules.ss:286).
# `stochastic-pick` over all-zero weights falls back to `random-pick`
# (utilities.ss:485-490), so a field of strength-0 rules is still picked from.
weights = temp_adjusted_values([r.strength for r in supported], temperature.value, meta)
chosen_rule = weighted_pick(supported, weights)

# A separate gate on how well the Workspace still supports the rule that was picked
# (answers.ss:946-950).  Vacuously 100 for a rule resting on no bridges.
if verbose:
    say('answer-finder-chose-rule', [exact(w) for w in weights])
    vprint(chosen_rule)
degree_of_support = chosen_rule.get_degree_of_support(workspace)
if verbose:
    say('degree-of-support', round(degree_of_support))
if prob(1.0 - degree_of_support / 100.0):
    if verbose:
        say('not-enough-support')
    fizzle()

# "Chosen rule no longer works" (answers.ss:951-953).
if not chosen_rule.currently_works(workspace, slipnet):
    if verbose:
        say('chosen-rule-no-longer-works')
    fizzle()

translated = translate_rule(chosen_rule)
if translated is None:
    if verbose:
        say('could-not-translate-chosen-rule')
    fizzle()
if verbose:
    say('rule-translated')

answer_text = apply_rule(translated)
if answer_text is None:
    # A snag: the translated rule cannot be applied to the target string.
    record_snag(chosen_rule, translated)
    fizzle()

# v2.0 Base: no "already found this answer" refusal (answers.ss:982).  Metacat consults Episodic
# Memory here so the search carries on toward a DIFFERENT answer; in a Training Mode Session a
# repeated problem must keep answering, so a repeated lesson is not refused.  Memory still
# records every answer.

quality = compute_answer_quality(chosen_rule.quality, temperature.value, meta)
report_answer(
    answer_text, quality,
    top_rule=chosen_rule,
    bottom_rule=translated,
    unjustified_slippages=getattr(translated, 'unjustified_slippages', []),
)
