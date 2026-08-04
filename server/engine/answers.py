"""Answer finding, reporting, and commentary generation.

Scheme source: answers.ss
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from server.engine.memory import AnswerDescription
from server.engine.rules import rule_signature

if TYPE_CHECKING:
    from server.engine.metadata import MetadataProvider
    from server.engine.rng import RNG
    from server.engine.rules import Rule
    from server.engine.workspace import Workspace


class AnswerResult:
    """Result of an answer-finding attempt."""

    def __init__(
        self,
        answer_string: str | None = None,
        top_rule: Rule | None = None,
        bottom_rule: Rule | None = None,
        quality: float = 0.0,
        temperature: float = 100.0,
        snag: bool = False,
        snag_reason: str = "",
    ) -> None:
        self.answer_string = answer_string
        self.top_rule = top_rule
        self.bottom_rule = bottom_rule
        self.quality = quality
        self.temperature = temperature
        self.snag = snag
        self.snag_reason = snag_reason

    @property
    def found(self) -> bool:
        return self.answer_string is not None

    def __repr__(self) -> str:
        if self.found:
            return f"AnswerResult('{self.answer_string}', quality={self.quality:.0f})"
        return f"AnswerResult(snag={self.snag})"


def compute_answer_quality(
    rule_quality: float,
    temperature: float,
    meta: MetadataProvider,
) -> float:
    """Compute answer quality from rule quality and temperature.

    Scheme: trace.ss:392-402.
    quality = weighted_average([rule_quality, 100-temp], [60, 40])
    """
    rw = meta.get_formula_coeff("answer_quality_rule_weight")  # 60
    tw = meta.get_formula_coeff("answer_quality_temperature_weight")  # 40
    total = rw + tw
    if total == 0:
        return rule_quality
    return round((rule_quality * rw + (100.0 - temperature) * tw) / total)


def get_quality_phrase(quality: float, meta: MetadataProvider) -> str:
    """Get a natural language phrase for the quality level.

    Scheme: answers.ss:95-105.
    """
    from server.engine.answer_comparison import quality_phrase

    return quality_phrase(quality, meta.commentary_templates) or "unknown"


def get_coherence_phrase(answer: Any, meta: MetadataProvider) -> str:
    """How coherent this answer looks, as a phrase rather than a boolean.

    Scheme: ``coherence-phrase`` (``answers.ss:919-926``) — a band table the original
    defines and never calls.  ``answer-incoherent?`` two definitions earlier
    (``answers.ss:909-916``) is the same judgement collapsed to a boolean, and its
    threshold tells you what the table's argument is: the signed gap between the
    answer's rule abstractness and its theme abstractness.  §4.7.3 describes the
    negative end of that gap for ``dyz`` — abstract themes over "a literal-minded
    interpretation of abc => abd".
    """
    from server.engine.answer_comparison import coherence_phrase, coherence_score

    return coherence_phrase(coherence_score(answer), meta.commentary_templates)


# §4.7.1 footnote 18: only these vertical theme categories may appear in an
# answer description, and Bond-Facet only in its "different" form.  Mirrored in
# seed_data/theme_dimensions.json as ``answer_description_theme_types``.
_ANSWER_DESCRIPTION_THEME_TYPES = (
    "plato-string-position-category",
    "plato-alphabetic-position-category",
    "plato-direction-category",
    "plato-group-category",
    "plato-bond-facet",
)


def create_answer_description(
    workspace: Workspace,
    top_rule: Rule | None,
    bottom_rule: Rule | None,
    quality: float,
    temperature: float,
    themes: dict[str, Any],
    unjustified_slippages: list[Any] | None = None,
    trace: Any = None,
    meta: Any = None,
) -> AnswerDescription:
    """Distil an answer description for long-term memory.

    §4.7.1: the description keeps separate **top**, **vertical** and **bottom**
    theme-patterns, the rules, and an unjustified theme-pattern representing the
    slippages the program never came to terms with.
    """
    answer_text = workspace.answer_string.text if workspace.answer_string else ""

    allowed = _ANSWER_DESCRIPTION_THEME_TYPES
    if meta is not None:
        allowed = tuple(
            getattr(meta, "answer_description_theme_types", None) or allowed
        )

    vertical = _filter_vertical_themes(themes.get("vertical_bridge", {}), allowed)
    vertical = _distil_vertical_pattern(vertical, workspace, trace, allowed)

    return AnswerDescription(
        problem=(
            workspace.initial_string.text,
            workspace.modified_string.text,
            workspace.target_string.text,
            answer_text,
        ),
        top_rule_description=top_rule.transcribe_to_english() if top_rule else "",
        bottom_rule_description=bottom_rule.transcribe_to_english() if bottom_rule else "",
        top_rule_quality=top_rule.quality if top_rule else 0.0,
        bottom_rule_quality=bottom_rule.quality if bottom_rule else 0.0,
        quality=quality,
        temperature=temperature,
        themes=vertical,
        top_themes=dict(themes.get("top_bridge", {})),
        vertical_themes=vertical,
        bottom_themes=dict(themes.get("bottom_bridge", {})),
        unjustified_themes=_unjustified_themes(unjustified_slippages or []),
        unjustified_slippages=[str(cm) for cm in (unjustified_slippages or [])],
        top_rule_abstractness=top_rule.abstractness if top_rule else 0.0,
        bottom_rule_abstractness=bottom_rule.abstractness if bottom_rule else 0.0,
        # ``memory.ss:117`` stores the clause lists so ``answer-present?`` can compare
        # them structurally.  The English transcription cannot stand in for this.
        top_rule_signature=rule_signature(top_rule),
        bottom_rule_signature=rule_signature(bottom_rule),
        theme_abstractness=average_theme_abstractness(
            vertical, _unjustified_themes(unjustified_slippages or []), meta
        ),
    )


_STRING_POSITION = "plato-string-position-category"


def _distil_vertical_pattern(
    dominant: dict[str, Any],
    workspace: Workspace,
    trace: Any,
    allowed: tuple[str, ...],
) -> dict[str, Any]:
    """Build the answer's vertical theme-pattern from the Trace as well as the Themespace.

    §4.7.1: "To create the vertical theme-pattern, Metacat examines the activations of
    vertical themes in the Themespace, **along with recent group and slippage events
    appearing in the Temporal Trace**.  If slippages have recently been made ... the
    themes associated with these slippage events will be included."

    Scheme: ``abstract-answer-description-theme-pattern`` (``answers.ss:155-220``).  Two
    of its rules are reproduced here:

    * non-identity themes drawn from recent, still-present vertical slippage events take
      precedence over the merely-dominant pattern;
    * ``;; Always include a string-position theme no matter what`` (``answers.ss:204``)
      — falling back to String-Position: identity.

    The second matters out of proportion to its size.  Without it an answer could be
    stored with an *empty* theme-pattern, and §2.4.1 makes that pattern the index the
    answer is stored and retrieved under — an answer with no themes has no index, and
    every distance computed against it degenerates.
    """
    pattern = dict(dominant)

    for dimension, relation in _trace_slippage_themes(workspace, trace).items():
        if dimension in allowed:
            pattern[dimension] = relation

    if _STRING_POSITION in allowed and _STRING_POSITION not in pattern:
        pattern[_STRING_POSITION] = "identity"

    return pattern


def _trace_slippage_themes(workspace: Workspace, trace: Any) -> dict[str, str]:
    """Non-identity themes from vertical slippage events that are still current.

    ``relevant-for-answer-description?`` (``trace.ss:783-785``) admits a concept-mapping
    event when its bridge is vertical and still present in the Workspace — a slippage
    that has since been broken did not contribute to this answer.
    """
    if trace is None:
        return {}

    from server.engine.themes import relation_name_for_label
    from server.engine.trace import CONCEPT_MAPPING_BUILT

    live = {id(b) for b in getattr(workspace, "vertical_bridges", []) or []}
    found: dict[str, str] = {}
    for event in getattr(trace, "events", []):
        if event.event_type != CONCEPT_MAPPING_BUILT:
            continue
        for bridge in event.structures or []:
            if id(bridge) not in live:
                continue
            for cm in getattr(bridge, "concept_mappings", []) or []:
                if cm.is_identity:
                    continue
                dimension = getattr(cm.description_type1, "name", "")
                relation = relation_name_for_label(cm.label)
                if dimension and relation:
                    # Later events win: the most recent equivalent event is the one the
                    # Scheme keeps (``answers.ss:108-121``).
                    found[dimension] = relation
    return found


# §4.7.3 coherence.  These need the Slipnet's conceptual depths, so they run here,
# where ``meta`` is in scope, and the result is stored on the description.

_RELATION_NODES = {
    "identity": "plato-identity",
    "opposite": "plato-opposite",
    "successor": "plato-successor",
    "predecessor": "plato-predecessor",
}


def _conceptual_depth(node_name: str, meta: Any) -> float:
    specs = getattr(meta, "slipnet_node_specs", None) or {}
    spec = specs.get(node_name)
    return float(getattr(spec, "conceptual_depth", 0) or 0)


def _theme_abstractness(dimension: str, relation: str, meta: Any) -> float:
    """Scheme: ``theme-abstractness`` (``answers.ss:895-906``).

    ``identity`` scores 0 — it is the *least* abstract relation, not the most — and
    ``diff`` scores a flat 50; every other relation uses its own conceptual depth.
    """
    dimension_abstractness = _conceptual_depth(dimension, meta)
    if relation == "identity":
        relation_abstractness = 0.0
    elif relation == "diff":
        relation_abstractness = 50.0
    else:
        relation_abstractness = _conceptual_depth(
            _RELATION_NODES.get(relation, ""), meta
        )
    return round((dimension_abstractness + relation_abstractness) / 2.0)


def average_theme_abstractness(
    themes: dict[str, Any],
    unjustified_themes: dict[str, Any] | None,
    meta: Any,
) -> float:
    """Scheme: ``average-theme-abstractness`` (``answers.ss:885-892``).

    Averaged over the answer's themes *and* its unjustified themes.
    """
    if meta is None:
        return 0.0
    combined = list(themes.items()) + list((unjustified_themes or {}).items())
    if not combined:
        return 0.0
    values = [_theme_abstractness(dim, rel, meta) for dim, rel in combined]
    return round(sum(values) / len(values))


def _filter_vertical_themes(
    vertical: dict[str, Any], allowed: tuple[str, ...]
) -> dict[str, Any]:
    """Apply the §4.7.1 footnote-18 restriction to a vertical theme pattern."""
    result: dict[str, Any] = {}
    for dimension, relation in vertical.items():
        if dimension not in allowed:
            continue
        if dimension == "plato-bond-facet" and relation != "diff":
            continue
        result[dimension] = relation
    return result


def _unjustified_themes(slippages: list[Any]) -> dict[str, Any]:
    """The theme-pattern implied by slippages the program failed to justify."""
    from server.engine.themes import relation_name_for_label

    themes: dict[str, Any] = {}
    for cm in slippages:
        dimension = getattr(getattr(cm, "description_type1", None), "name", None)
        if dimension is None:
            continue
        themes[dimension] = relation_name_for_label(getattr(cm, "label", None))
    return themes


def make_translated_string(
    rule: Any,
    source: Workspace,
    slipnet: Any,
    workspace: Any = None,
    *,
    register_bridges: bool = True,
) -> Any:
    """Build the answer string *with the structure the rule implies*.

    Scheme: ``make-translated-string`` (``answers.ss:1035-1071``).  Applying a rule
    yields the answer's letters, but an answer is not a row of letters: the target's
    perceptual structure is carried across it.  ``mrrjjj`` seen as three sameness
    groups becomes ``mrrkkk`` seen as three sameness groups, and the Workspace display
    shows that because it is true, not as decoration.

    The Scheme walks the source's image twice — leaves first, then interior nodes
    bottom-up — instantiating a letter per leaf and a group per interior node.  Here
    the leaves *bind* to the letters ``WorkspaceString`` has already created rather
    than creating a second set, and the interior walk then builds the groups over
    them.

    Returns ``None`` when the rule cannot be applied, which is the caller's snag.

    ``register_bridges`` is what separates the two callers.  When a *run reaches an
    answer* the translated string becomes the Workspace's answer string, so the bridges
    drawn to it are real Workspace bridges and are filed as such.  When *justify mode*
    tests a translation (``justify.ss:107-112``) the Workspace already has an answer
    string of its own and the translation is only a hypothesis; filing its bridges would
    overwrite the real objects' ``horizontal_bridge`` and make ``Rule.supported``
    vacuously true of exactly the rule whose support is in question.  The Scheme never
    files them (``make-translated-rule-bridges``, ``answers.ss:1095-1127``, only marks
    them); ``workspace`` is still passed so the rule information can be resolved
    against the real strings.
    """
    from server.engine.images import ImageFailure
    from server.engine.rules import _generate_image_letters, apply_rule
    from server.engine.workspace import WorkspaceString

    transforms = apply_rule(rule, source, slipnet)
    if transforms is None:
        return None

    image = getattr(source, "image", None)
    if image is None:
        return None

    text = "".join(
        getattr(node, "short_name", "") for node in _generate_image_letters(source, slipnet)
    )
    string_type = "modified" if source.string_type == "initial" else "answer"
    translated = WorkspaceString(text, slipnet, string_type=string_type)
    if workspace is not None:
        translated.workspace = workspace

    _describe_letters(translated, slipnet)

    letters = translated.letters
    position = 0

    def bind_leaf(leaf_image: Any) -> None:
        nonlocal position
        if position < len(letters):
            leaf_image.instantiated_object = letters[position]
        position += 1

    try:
        image.do_walk("leaf_walk", bind_leaf)
        if position != len(letters):
            # The image and the generated text disagree about how many letters there
            # are; instantiating groups over that would misplace them.
            return translated
        image.do_walk(
            "postorder_interior_walk", lambda node: node.instantiate_as_group(translated)
        )
    except ImageFailure:
        # A group that could not be instantiated leaves the letters, which are still
        # the answer.  Better a string with no groups than no answer at all.
        return translated

    for group in [o for o in translated.objects if o not in letters]:
        group.proposal_level = getattr(group, "BUILT", group.proposal_level)
        for bond in getattr(group, "group_bonds", ()) or ():
            bond.proposal_level = getattr(bond, "BUILT", bond.proposal_level)
            translated.add_bond(bond)

    bridges = _bridge_to_translation(
        source,
        translated,
        slipnet,
        workspace if register_bridges else None,
        transforms,
    )
    # ``answers.ss:1069`` — the last thing ``make-translated-string`` does is hand the
    # bridges it drew back to the rule, which is where a translated rule gets its
    # supporting bridges and its theme pattern.  Until then it rests on nothing, and
    # ``supported?`` is vacuously true of it.
    if hasattr(rule, "set_translated_rule_information"):
        rule.set_translated_rule_information(bridges, workspace, slipnet)
    return translated


def _bridge_to_translation(
    source: Any, translated: Any, slipnet: Any, workspace: Any, transforms: Any = None
) -> list:
    """Bridge each source object the rule *transformed* to the object it became.

    Scheme: ``make-translated-rule-bridges`` (``answers.ss:1095-1127``).  The bridges
    are what say *which* part of the answer each part of the target turned into — the
    ``m`` stayed ``m``, the ``jjj`` became ``kkk`` — and they are built rather than
    proposed, because the translation has already happened: there is nothing left to
    decide, only something to record.  Without them the answer sits beside the target
    with no stated relation to it.

    *transforms* is ``apply-rule``'s own result: the objects the rule named and what it
    did to each.  Only those are bridged, plus — when the rule spoke about the string
    as a whole — the string's top-level objects it did not name individually.  Bridging
    every object regardless is not merely broader: those bridges become the translated
    rule's supporting bridges, and ``supported?`` is an ``andmap`` over them, so a rule
    about one letter would have to be underwritten by a horizontal bridge on every
    object in the string before it counted as supported.
    """
    from server.engine.bridges import (
        BRIDGE_BOTTOM,
        BRIDGE_TOP,
        Bridge,
        make_concept_mappings,
    )
    from server.engine.rules import _get_constituent_objects, _is_workspace_string

    # Which horizontal pair the bridges belong to follows from which string was
    # translated: the initial string becomes the modified string (a top pair), the
    # target string becomes the answer (a bottom pair).  Justify mode translates a
    # bottom rule into a top one, so the initial-string case is reachable, and filing
    # those bridges under ``bottom`` would have misreported the bottom mapping.
    bridge_type = (
        BRIDGE_TOP if getattr(source, "string_type", "") == "initial" else BRIDGE_BOTTOM
    )

    if transforms is None:
        # No transform record to scope by (a verbatim rule returns none): fall back to
        # the whole string, which is what the display needs.
        subjects = list(getattr(source, "objects", []))
    else:
        named = [obj for obj, _ in transforms if not _is_workspace_string(obj)]
        string_transform = next(
            (t for t in transforms if _is_workspace_string(t[0])), None
        )
        subjects = list(named)
        if string_transform is not None:
            for obj in _get_constituent_objects(string_transform[0]):
                if not any(o is obj for o in subjects):
                    subjects.append(obj)

    identity = slipnet.nodes.get("plato-identity")
    bridges = []
    for obj in subjects:
        image = getattr(obj, "image", None)
        counterpart = getattr(image, "instantiated_object", None) if image else None
        if counterpart is None:
            continue
        bridge = Bridge(
            object1=obj,
            object2=counterpart,
            bridge_type=bridge_type,
            concept_mappings=make_concept_mappings(
                obj, counterpart, bridge_type, identity
            ),
        )
        bridge.proposal_level = getattr(bridge, "BUILT", bridge.proposal_level)
        bridges.append(bridge)
        if workspace is not None:
            workspace.add_bridge(bridge)
    return bridges


def _describe_letters(string: Any, slipnet: Any) -> None:
    """Give a freshly built string's letters the descriptions ``init_mcat`` gives.

    A string created after initialisation misses them, and a letter with no
    letter-category description has no descriptor for a bond to relate — so the groups
    instantiated over it come out with no internal bonds, and the answer draws as
    unconnected letters.
    """
    from server.engine.descriptions import Description

    letter_category = slipnet.nodes.get("plato-letter-category")
    object_category = slipnet.nodes.get("plato-object-category")
    letter_node = slipnet.nodes.get("plato-letter")
    if letter_category is None:
        return

    for letter in string.letters:
        if not letter.description_type_present(letter_category):
            letter.add_description(
                Description(letter, letter_category, letter.letter_category)
            )
        if object_category is not None and letter_node is not None:
            if not letter.description_type_present(object_category):
                letter.add_description(
                    Description(letter, object_category, letter_node)
                )
