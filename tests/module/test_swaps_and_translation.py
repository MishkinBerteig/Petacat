"""Swap rules, translation failure, and the conflict check.

Real Slipnet, real Workspace, real rule pipeline; no database and no HTTP.

Four things the reference does that Petacat did not:

* an instantiated **extrinsic** clause carries the conceptual dimensions whose
  descriptors are swapped (``rules.ss:871-875``), and ``get-extrinsic-transforms``
  reads them (``rules.ss:1430``).  Built with an empty change list, as Petacat
  built it, every swap rule applied as a no-op — so it failed ``currently-works?``
  and was never built, and the whole extrinsic family of §3.3.4 was unreachable;
* a translation drops each conceptual dimension of its transform slippages with
  probability 0.4 (``answers.ss:1364-1371``), so the same rule and the same mapping
  yield different translated rules on different attempts;
* conflicting transforms are found with the full ``intrinsic-implies-intrinsic?``
  battery (``rules.ss:1321-1338``), not just "same object, same dimension";
* a translated clause that is not well-formed fails the translation outright
  (``answers.ss:1304-1305``) rather than being silently skipped at application time.
"""

from __future__ import annotations

import os

import pytest

from server.engine.images import ImageFailure
from server.engine.metadata import MetadataProvider
from server.engine.rules import (
    CLAUSE_EXTRINSIC,
    CLAUSE_INTRINSIC,
    RULE_BOTTOM,
    RULE_TOP,
    Rule,
    RuleChange,
    RuleClause,
    _generate_image_letters,
    apply_rule,
    build_rule_from_bridges,
)
from server.engine.runner import EngineRunner

pytestmark = pytest.mark.numeric_matrix

SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")


@pytest.fixture(scope="module")
def meta() -> MetadataProvider:
    return MetadataProvider.from_seed_data(SEED_DIR)


@pytest.fixture
def ctx(meta):
    """A workspace on ``eqe -> qeq; abbba`` — §5.2.3's swap problem."""
    runner = EngineRunner(meta)
    runner.init_mcat("eqe", "qeq", "abbba", seed=7)
    return runner.ctx


def _node(ctx, name):
    return ctx.slipnet.nodes[name]


def _letters(ctx, string):
    return "".join(n.short_name for n in _generate_image_letters(string, ctx.slipnet))


def _bridge(ctx, obj1, obj2, bridge_type):
    from server.engine.bridges import Bridge, make_concept_mappings

    bridge = Bridge(
        object1=obj1,
        object2=obj2,
        bridge_type=bridge_type,
        concept_mappings=make_concept_mappings(
            obj1, obj2, bridge_type, _node(ctx, "plato-identity")
        ),
    )
    bridge.proposal_level = bridge.BUILT
    ctx.workspace.add_bridge(bridge)
    return bridge


def _od(ctx, object_type, attribute, descriptor):
    return (
        _node(ctx, object_type) if object_type != "string" else "string",
        _node(ctx, attribute),
        _node(ctx, descriptor),
    )


# ── RU-1: an extrinsic clause is only a swap if it carries its dimensions ───


def test_a_swap_rule_abstracted_from_bridges_actually_swaps(ctx):
    """End to end: abstract a rule from ``eqe -> qeq``'s bridges, then apply it.

    The three top bridges e--q, q--e, e--q hold a Letter-Category symmetry, which
    ``abstract-change-descriptions`` turns into an extrinsic change-description
    (``rules.ss:576-605``) and ``instantiate-rule-clause-template`` into an
    ``('extrinsic <object-descriptions> <dimensions>)`` clause.  Applying that to
    ``eqe`` has to give back ``qeq``: that is ``currently-works?``, and a rule that
    fails it is discarded by the evaluator (``rules.ss:463-465``).

    Before RU-1 the clause was built with ``changes=[]`` and its dimensions thrown
    away, so this application was the identity and no swap rule was ever built.
    """
    ws = ctx.workspace
    initial = list(ws.initial_string.objects)
    modified = list(ws.modified_string.objects)
    bridges = [_bridge(ctx, initial[i], modified[i], "top") for i in range(3)]

    rule = None
    for _ in range(60):
        candidate = build_rule_from_bridges(
            RULE_TOP, bridges, ctx.slipnet, rng=ctx.rng,
            temperature=ctx.temperature.value, meta=ctx.meta, workspace=ws,
        )
        if candidate is not None and candidate.extrinsic_clauses:
            rule = candidate
            break
    assert rule is not None, "no extrinsic clause was abstracted in 60 attempts"

    clause = rule.extrinsic_clauses[0]
    assert clause.dimensions, "the instantiated extrinsic clause lost its dimensions"

    apply_rule(rule, ws.initial_string, ctx.slipnet)
    assert _letters(ctx, ws.initial_string) == "qeq"
    assert rule.currently_works(ws, ctx.slipnet)


def _bbb_group(ctx):
    """Read ``abbba`` as ``a [bbb] a`` — the reading ``baaab`` rests on."""
    from server.engine.groups import Group

    ws = ctx.workspace
    letters = list(ws.target_string.letters)
    group = Group(
        ws.target_string,
        _node(ctx, "plato-samegrp"),
        _node(ctx, "plato-letter-category"),
        None,
        letters[1:4],
        [],
    )
    group.proposal_level = group.BUILT
    ws.target_string.add_group(group)
    return group


def test_a_hand_built_swap_rule_swaps_the_strings_components(ctx):
    """"Swap the letter-categories of the whole string's components".

    A one-object extrinsic clause denotes that object's *constituents*
    (``rules.ss:1425-1429``), so on ``a [bbb] a`` the three components are ``a``,
    the ``bbb`` group and ``a``: two descriptors, ``a`` and ``b``, swapped gives
    ``b [aaa] b`` — ``baaab``, the answer §5.2.3 compares against ``aaabaaa`` and
    the one the ``eqe-baaab`` demo is named for.  Petacat could not reach it at all
    while extrinsic clauses were built with their dimensions discarded.
    """
    ws = ctx.workspace
    _bbb_group(ctx)
    clause = RuleClause(
        clause_type=CLAUSE_EXTRINSIC,
        object_description=(
            "string",
            _node(ctx, "plato-string-position-category"),
            _node(ctx, "plato-whole"),
        ),
        dimensions=[_node(ctx, "plato-letter-category")],
    )
    rule = Rule(RULE_BOTTOM, [clause], workspace=ws)

    assert apply_rule(rule, ws.target_string, ctx.slipnet) is not None
    assert _letters(ctx, ws.target_string) == "baaab"


def test_naming_the_letters_individually_swaps_only_those_letters(ctx):
    """The same dimension over three *letters* is a different rule, and says so.

    ends ``a``, middle ``b`` → ends ``b``, middle ``a``, with positions 1 and 3
    untouched: ``bbabb``.  Pinned beside the previous case because the difference
    between them is exactly the one-object rule of ``rules.ss:1426`` — what a swap
    denotes depends on how many objects the clause names.
    """
    ws = ctx.workspace
    clause = RuleClause(
        clause_type=CLAUSE_EXTRINSIC,
        extrinsic_objects=[
            _od(ctx, "plato-letter", "plato-string-position-category", "plato-leftmost"),
            _od(ctx, "plato-letter", "plato-string-position-category", "plato-middle"),
            _od(ctx, "plato-letter", "plato-string-position-category", "plato-rightmost"),
        ],
        dimensions=[_node(ctx, "plato-letter-category")],
    )
    rule = Rule(RULE_BOTTOM, [clause], workspace=ws)

    assert apply_rule(rule, ws.target_string, ctx.slipnet) is not None
    assert _letters(ctx, ws.target_string) == "bbabb"


def test_a_swap_over_overlapping_objects_is_a_swap_snag(ctx):
    """``rules.ss:1433-1434`` — a swap among objects that are not pairwise disjoint.

    "Swap the letter-categories of the ``bbb`` group and the middle letter" cannot
    be carried out: the group contains that letter.  The reference calls the
    failure action with ``(SWAP <objects> <dimension>)`` and aborts, which is the
    SWAP snag kind the Trace records — a kind that could never occur while
    extrinsic clauses applied as no-ops.
    """
    ws = ctx.workspace
    _bbb_group(ctx)

    clause = RuleClause(
        clause_type=CLAUSE_EXTRINSIC,
        extrinsic_objects=[
            _od(ctx, "plato-group", "plato-group-category", "plato-samegrp"),
            _od(ctx, "plato-letter", "plato-string-position-category", "plato-middle"),
        ],
        dimensions=[_node(ctx, "plato-letter-category")],
    )
    rule = Rule(RULE_BOTTOM, [clause], workspace=ws)

    failures = []
    assert apply_rule(
        rule, ws.target_string, ctx.slipnet, failure_action=failures.append
    ) is None
    assert [f.kind for f in failures] == [ImageFailure.SWAP]


# ── RU-4: the conflict check is the implication battery, not one identity ───


def test_a_length_change_on_a_group_conflicts_with_a_letter_change_inside_it(ctx):
    """``rules.ss:1210-1213`` — case 2.3 of ``intrinsic-implies-intrinsic?``.

    "a LettCtgy change to an object should be ignored if the object has an
    enclosing group whose Length changes, since this might implicitly change the
    letter-categories of all the group's subobjects in a way that could be
    inconsistent with the object's own LettCtgy change" (``rules.ss:1160-1166``).

    Two objects, two dimensions: the old test — ``obj1 is obj2 and dim1 is dim2``
    — could not see it, and applied both changes in sequence, producing an answer
    string the reference refuses to produce.  This is also what makes the CONFLICT
    snag kind reachable at all.
    """
    from server.engine.groups import Group

    ws = ctx.workspace
    letters = list(ws.target_string.letters)
    group = Group(
        ws.target_string,
        _node(ctx, "plato-samegrp"),
        _node(ctx, "plato-letter-category"),
        None,
        letters[1:4],
        [],
    )
    group.proposal_level = group.BUILT
    ws.target_string.add_group(group)

    rule = Rule(
        RULE_BOTTOM,
        [
            RuleClause(
                clause_type=CLAUSE_INTRINSIC,
                object_description=_od(
                    ctx, "plato-group", "plato-group-category", "plato-samegrp"
                ),
                changes=[
                    RuleChange(
                        dimension=_node(ctx, "plato-length"),
                        relation=_node(ctx, "plato-successor"),
                    )
                ],
            ),
            RuleClause(
                clause_type=CLAUSE_INTRINSIC,
                object_description=_od(
                    ctx, "plato-letter", "plato-letter-category", "plato-b"
                ),
                changes=[
                    RuleChange(
                        dimension=_node(ctx, "plato-letter-category"),
                        relation=_node(ctx, "plato-successor"),
                    )
                ],
            ),
        ],
        workspace=ws,
    )

    failures = []
    assert apply_rule(
        rule, ws.target_string, ctx.slipnet, failure_action=failures.append
    ) is None
    assert [f.kind for f in failures] == [ImageFailure.CONFLICT]
    assert len(failures[0].objects) == 2


def test_two_changes_on_unrelated_objects_do_not_conflict(ctx):
    """The battery must not fire on a rule that is simply describing two changes.

    Different objects, different dimensions, neither enclosing the other: nothing
    in ``rules.ss:1194-1231`` matches, and the application goes through.
    """
    ws = ctx.workspace
    rule = Rule(
        RULE_BOTTOM,
        [
            RuleClause(
                clause_type=CLAUSE_INTRINSIC,
                object_description=_od(
                    ctx, "plato-letter", "plato-string-position-category", "plato-leftmost"
                ),
                changes=[
                    RuleChange(
                        dimension=_node(ctx, "plato-letter-category"),
                        relation=_node(ctx, "plato-successor"),
                    )
                ],
            ),
            RuleClause(
                clause_type=CLAUSE_INTRINSIC,
                object_description=_od(
                    ctx, "plato-letter", "plato-string-position-category", "plato-rightmost"
                ),
                changes=[
                    RuleChange(
                        dimension=_node(ctx, "plato-letter-category"),
                        to_descriptor=_node(ctx, "plato-z"),
                    )
                ],
            ),
        ],
        workspace=ws,
    )
    assert apply_rule(rule, ws.target_string, ctx.slipnet) is not None
    assert _letters(ctx, ws.target_string) == "bbbbz"


# ── RU-3: the p = 0.4 per-dimension drop is a source of answer variety ──────


def _vertical_mapping(ctx):
    """Bridge ``eqe``'s three letters to ``abbba``'s ends and middle.

    The mappings are stated outright rather than derived, because
    ``make_concept_mappings`` only relates descriptors the Slipnet actually links
    and ``e`` and ``a`` are not linked — a real ``eqe``/``abbba`` vertical mapping
    carries no Letter-Category slippage at all, which is why the answers to that
    problem keep the target's own letters.  What is under test here is what
    translation does *with* a slippage, so one is supplied.
    """
    from server.engine.concept_mappings import ConceptMapping

    initial = list(ctx.workspace.initial_string.letters)
    target = list(ctx.workspace.target_string.letters)
    letter_category = _node(ctx, "plato-letter-category")
    for source, destination in zip(initial, (target[0], target[2], target[4])):
        bridge = _bridge(ctx, source, destination, "vertical")
        bridge.concept_mappings.append(
            ConceptMapping(
                description_type1=letter_category,
                descriptor1=_node(ctx, "plato-q"),
                description_type2=letter_category,
                descriptor2=_node(ctx, "plato-b"),
                object1=source,
                object2=destination,
                slipnet=ctx.slipnet,
            )
        )
    return initial, target


def _q_to_b_rule(ctx):
    """"Change the letter-category of the letter ``e`` to ``q``"."""
    return Rule(
        RULE_TOP,
        [
            RuleClause(
                clause_type=CLAUSE_INTRINSIC,
                object_description=_od(
                    ctx, "plato-letter", "plato-letter-category", "plato-e"
                ),
                changes=[
                    RuleChange(
                        dimension=_node(ctx, "plato-letter-category"),
                        to_descriptor=_node(ctx, "plato-q"),
                    )
                ],
            )
        ],
        workspace=ctx.workspace,
    )


def test_one_workspace_state_yields_more_than_one_translated_rule(ctx, meta):
    """``answers.ss:1364-1371``: each dimension present among a clause's transform
    slippages is dropped with probability 0.4, **per attempt**.

    So translating the same rule against the same mapping repeatedly must not give
    the same result every time.  Petacat applied every applicable slippage
    deterministically, and the only randomness left in a translation was the
    coattail; the reachable set per Workspace state was correspondingly smaller,
    and this is a change to what is reachable rather than to how often.

    The mapping slips ``q => b`` on Letter-Category, so the translated rule either
    says "…to ``b``" (the dimension survived) or still says "…to ``q``" (it was
    dropped).  Both are results the reference can produce from this one state.
    """
    ws = ctx.workspace
    _vertical_mapping(ctx)
    rule = _q_to_b_rule(ctx)

    seen = set()
    for _ in range(80):
        translated = rule.translate(
            ws.initial_string, ws.target_string, ctx.slipnet, rng=ctx.rng, meta=meta
        )
        assert translated is not None
        change = translated.clauses[0].changes[0]
        seen.add((change.relation or change.to_descriptor).name)

    assert seen == {"plato-b", "plato-q"}, (
        "the same rule and the same mapping produced one translated rule every "
        f"time ({seen}); the per-dimension ignore is not firing"
    )


def test_the_object_description_is_translated_without_the_drop(ctx, meta):
    """The drop applies to the *transform* slippages only (``answers.ss:1362-1382``).

    ``translate-object-description`` has already run by then, and it uses the full
    ``applicable-object-description-slippages``.  So the clause's object-description
    is slipped every time even while its changes are sometimes not — which is what
    keeps a translated rule pointed at the right object however literal its change
    comes out.
    """
    ws = ctx.workspace
    _vertical_mapping(ctx)
    rule = Rule(
        RULE_TOP,
        [
            RuleClause(
                clause_type=CLAUSE_INTRINSIC,
                object_description=_od(
                    ctx, "plato-letter", "plato-letter-category", "plato-q"
                ),
                changes=[
                    RuleChange(
                        dimension=_node(ctx, "plato-letter-category"),
                        to_descriptor=_node(ctx, "plato-q"),
                    )
                ],
            )
        ],
        workspace=ws,
    )

    descriptors = set()
    for _ in range(40):
        translated = rule.translate(
            ws.initial_string, ws.target_string, ctx.slipnet, rng=ctx.rng, meta=meta
        )
        descriptors.add(translated.clauses[0].object_description[2].name)
    assert descriptors == {"plato-b"}


def test_the_drop_probability_is_configurable_and_off_at_zero(ctx, meta, monkeypatch):
    """At p = 0 every applicable slippage survives, which is the old behaviour.

    Pinned so the parameter is demonstrably the knob, and so the deterministic
    translation is available as a comparison rather than as the only mode.
    """
    ws = ctx.workspace
    _vertical_mapping(ctx)
    monkeypatch.setitem(meta.params, "slippage_ignore_probability", 0.0)
    rule = _q_to_b_rule(ctx)

    seen = set()
    for _ in range(40):
        translated = rule.translate(
            ws.initial_string, ws.target_string, ctx.slipnet, rng=ctx.rng, meta=meta
        )
        change = translated.clauses[0].changes[0]
        seen.add((change.relation or change.to_descriptor).name)
    assert seen == {"plato-b"}


# ── RU-11: a translation can fail, and failure is not an unchanged target ───


def test_a_clause_naming_a_missing_object_fails_the_translation(ctx, meta):
    """``answers.ss:1438-1439`` — ``(if* (null? from-objects) (fail))``.

    The rule speaks about a letter ``z`` the initial string does not contain, so
    there is nothing to translate and ``translate`` returns ``#f``; the
    answer-finder then reports "Couldn't translate chosen rule" and fizzles.
    Petacat had no failure at all here: the clause survived, matched nothing at
    application time, was silently skipped, and the run answered with the target
    unchanged.
    """
    ws = ctx.workspace
    _vertical_mapping(ctx)
    rule = Rule(
        RULE_TOP,
        [
            RuleClause(
                clause_type=CLAUSE_INTRINSIC,
                object_description=_od(
                    ctx, "plato-letter", "plato-letter-category", "plato-z"
                ),
                changes=[
                    RuleChange(
                        dimension=_node(ctx, "plato-letter-category"),
                        relation=_node(ctx, "plato-successor"),
                    )
                ],
            )
        ],
        workspace=ws,
    )
    assert rule.translate(
        ws.initial_string, ws.target_string, ctx.slipnet, rng=ctx.rng, meta=meta
    ) is None


def test_an_ill_formed_translated_clause_fails_the_translation(ctx, meta):
    """``valid-rule-clause?`` (``answers.ss:1536-1557``) via ``valid-change?``.

    A change whose descriptor is not of its stated dimension's category — here
    Letter-Category paired with ``leftmost`` — is nonsense, and the reference
    rejects the whole translation rather than letting it reach ``apply-rule``.
    """
    ws = ctx.workspace
    _vertical_mapping(ctx)
    rule = Rule(
        RULE_TOP,
        [
            RuleClause(
                clause_type=CLAUSE_INTRINSIC,
                object_description=_od(
                    ctx, "plato-letter", "plato-letter-category", "plato-e"
                ),
                changes=[
                    RuleChange(
                        dimension=_node(ctx, "plato-letter-category"),
                        to_descriptor=_node(ctx, "plato-leftmost"),
                    )
                ],
            )
        ],
        workspace=ws,
    )
    assert rule.translate(
        ws.initial_string, ws.target_string, ctx.slipnet, rng=ctx.rng, meta=meta
    ) is None


# ── a reference object can be a letter, and letters have no constituents ────


@pytest.fixture
def ijkk_ctx(meta):
    runner = EngineRunner(meta)
    runner.init_mcat("aabc", "aabd", "ijkk", seed=35)
    return runner


def test_a_letter_reference_object_makes_the_clause_denote_nothing(ijkk_ctx):
    """``constituent-objects-of`` (``utilities.ss:110-114``): a letter has none.

    A reference object *is* a letter whenever the rule names an object the string
    resolves to a letter — "change all objects in the rightmost group to letters"
    against ``ijkk``, when the rightmost object is the letter ``k`` rather than a
    group.  The Scheme's two rule-application sites (``rules.ss:1432``,
    ``rules.ss:1540``) used to send ``'get-constituent-objects`` to whatever came
    back, which a letter does not answer, and the run was abandoned through
    ``report-error-and-halt``.

    Both of Petacat's counterparts go through ``_get_constituent_objects``, which
    states the empty list rather than inheriting it from a ``getattr`` default.
    The clause then denotes fewer than two objects, contributes no transforms, and
    the rule simply does not apply — the string comes back unchanged and the
    application *succeeds*, which is the outcome the surrounding code handles.
    """
    from server.engine.rules import (
        SCOPE_SUBOBJECTS,
        _get_constituent_objects,
        _get_extrinsic_transforms,
        _get_intrinsic_transforms,
        _get_reference_objects_for_clause,
    )

    ctx = ijkk_ctx.ctx
    ws = ctx.workspace
    rightmost = _od(ctx, "plato-letter", "plato-string-position-category", "plato-rightmost")

    extrinsic = RuleClause(
        clause_type=CLAUSE_EXTRINSIC,
        object_description=rightmost,
        dimensions=[_node(ctx, "plato-letter-category")],
    )
    intrinsic = RuleClause(
        clause_type=CLAUSE_INTRINSIC,
        object_description=rightmost,
        changes=[
            RuleChange(
                dimension=_node(ctx, "plato-object-category"),
                to_descriptor=_node(ctx, "plato-letter"),
                referent=SCOPE_SUBOBJECTS,
            )
        ],
    )

    for clause, transforms_of in (
        (extrinsic, _get_extrinsic_transforms),
        (intrinsic, _get_intrinsic_transforms),
    ):
        references = _get_reference_objects_for_clause(clause, ws.target_string, ctx.slipnet)
        assert references and all(
            _get_constituent_objects(obj) == [] for obj in references
        ), "the reference object should be a letter, and letters have no constituents"

        rule = Rule(RULE_BOTTOM, [clause], workspace=ws)
        assert transforms_of(rule, ws.target_string, ctx.slipnet) == []
        assert apply_rule(rule, ws.target_string, ctx.slipnet) == []
        assert _letters(ctx, ws.target_string) == "ijkk"


def test_the_reference_reproducer_completes(ijkk_ctx):
    """``aabc -> aabd; ijkk`` at seed 35 — the Scheme's own reproducer.

    Kept as a whole run rather than only as the unit above, because what the defect
    did was abandon the *run*: the halt was inside the answer-finder, under a
    ``(reset)``, and invisible except as a shard that never finished.  Petacat has
    no blanket ``except Exception`` in ``apply_rule`` any more, so an equivalent
    defect would surface here as an exception rather than as a silent snag.
    """
    ijkk_ctx.run_mcat(max_steps=100_000)
    assert ijkk_ctx.status in ("answer_found", "gave_up", "halted")


def test_a_one_letter_swap_clause_is_ill_formed(ctx, meta):
    """``answers.ss:1541-1542`` — a swap naming one *letter* has nothing to swap.

    A one-object extrinsic clause swaps that object's components among themselves,
    and a letter has none.  The reference tests this on the *translated* clause,
    because a ``group => letter`` slippage is exactly how a well-formed one becomes
    ill-formed.
    """
    ws = ctx.workspace
    _vertical_mapping(ctx)
    rule = Rule(
        RULE_TOP,
        [
            RuleClause(
                clause_type=CLAUSE_EXTRINSIC,
                object_description=_od(
                    ctx, "plato-letter", "plato-letter-category", "plato-e"
                ),
                dimensions=[_node(ctx, "plato-letter-category")],
            )
        ],
        workspace=ws,
    )
    assert rule.translate(
        ws.initial_string, ws.target_string, ctx.slipnet, rng=ctx.rng, meta=meta
    ) is None
