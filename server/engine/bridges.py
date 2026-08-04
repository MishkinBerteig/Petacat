"""Bridge structures — mappings between objects across strings.

Bridges carry concept-mappings that describe how descriptions correspond
(identity, slippage, coattail). Three bridge orientations: top (initial<->modified),
bottom (target<->answer), vertical (initial<->target, modified<->answer).

Scheme source: bridges.ss
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from server.engine.workspace_structures import WorkspaceStructure

if TYPE_CHECKING:
    from server.engine.bonds import Bond
    from server.engine.concept_mappings import ConceptMapping
    from server.engine.slipnet import SlipnetNode
    from server.engine.workspace_objects import WorkspaceObject

# Bridge type string constants (values live in DB bridge_types table)
BRIDGE_TOP = "top"
BRIDGE_BOTTOM = "bottom"
BRIDGE_VERTICAL = "vertical"

# Bridge orientation string constants (values live in DB bridge_orientations table)
ORIENTATION_HORIZONTAL = "horizontal"
ORIENTATION_VERTICAL = "vertical"


class Bridge(WorkspaceStructure):
    """A mapping between objects in different strings."""

    def __init__(
        self,
        object1: WorkspaceObject,
        object2: WorkspaceObject,
        bridge_type: str,
        concept_mappings: list[ConceptMapping],
    ) -> None:
        super().__init__()
        self.object1 = object1
        self.object2 = object2
        self.bridge_type = bridge_type
        self.concept_mappings = concept_mappings
        self.spanning: bool = False
        self.group_spanning: bool = False
        # The *original* group each side replaces, when the proposal rests on a
        # reversed reading of a spanning group.  Scheme: ``mark-flipped-group1`` /
        # ``mark-flipped-group2`` (bridges.ss:185-192).  The builder needs the
        # original to fight it and then to swap it out (bridges.ss:1295-1345);
        # ``None`` on both sides is the ordinary case.
        self.flipped_group1: Any = None
        self.flipped_group2: Any = None

    @property
    def orientation(self) -> str:
        if self.bridge_type in (BRIDGE_TOP, BRIDGE_BOTTOM):
            return ORIENTATION_HORIZONTAL
        return ORIENTATION_VERTICAL

    @property
    def is_horizontal(self) -> bool:
        return self.orientation == ORIENTATION_HORIZONTAL

    @property
    def is_vertical(self) -> bool:
        return self.orientation == ORIENTATION_VERTICAL

    def get_relevant_concept_mappings(self) -> list[ConceptMapping]:
        """Return CMs where both description types are relevant (fully active).

        Scheme: bridges.ss:248 (horizontal), 652 (vertical).
        """
        return [cm for cm in self.concept_mappings if cm.relevant()]

    def get_distinguishing_concept_mappings(self) -> list[ConceptMapping]:
        """Return CMs where both descriptors are distinguishing.

        Scheme: bridges.ss:249-250 (horizontal), 653-654 (vertical).
        """
        return [cm for cm in self.concept_mappings if cm.distinguishing()]

    def distinguishing_concept_mappings(self) -> list[ConceptMapping]:
        """Alias for get_distinguishing_concept_mappings for backward compat."""
        return self.get_distinguishing_concept_mappings()

    def get_relevant_distinguishing_concept_mappings(self) -> list[ConceptMapping]:
        """CMs that are both relevant and distinguishing.

        Scheme: bridges.ss:251-252 (horizontal), 655-656 (vertical).
        """
        return [cm for cm in self.concept_mappings if cm.relevant_distinguishing()]

    def calculate_internal_strength(self) -> float:
        """Bridge internal strength from concept mappings.

        Scheme: bridges.ss:377-399 (horizontal), 775-793 (vertical).
        avg_cm_strength * num_cm_factor * coherence_factor [* singleton_factor]
        Uses relevant-distinguishing CMs; if none, returns 0.
        """
        rel_dist_cms = self.get_relevant_distinguishing_concept_mappings()
        if not rel_dist_cms:
            return 0.0

        avg_strength = sum(cm.strength() for cm in rel_dist_cms) / len(rel_dist_cms)

        # Number-of-CMs factor
        n = len(rel_dist_cms)
        if n == 1:
            num_factor = 0.8
        elif n == 2:
            num_factor = 1.2
        else:
            num_factor = 1.6

        # Internal coherence factor
        coherent = self._is_internally_coherent()
        coherence_factor = 2.5 if coherent else 1.0

        result = avg_strength * num_factor * coherence_factor

        # Singleton factor (horizontal only)
        if self.is_horizontal:
            result *= self._singleton_factor()

        return min(100.0, round(result))

    def _is_internally_coherent(self) -> bool:
        """Check if CMs support each other.

        Scheme: bridges.ss:362-370 (horizontal), 765-773 (vertical).
        True if any pair of relevant-distinguishing CMs are supporting.
        Supporting CMs: equal, or share related descriptors with same label.
        """
        rel_dist_cms = self.get_relevant_distinguishing_concept_mappings()
        for i, cm1 in enumerate(rel_dist_cms):
            for cm2 in rel_dist_cms[i + 1:]:
                if _supporting_cms(cm1, cm2):
                    return True
        return False

    def _singleton_factor(self) -> float:
        """Penalise bridges that pair a *singleton* with a mismatched object type.

        Scheme: ``singleton-letter-factor`` (bridges.ss:808-822).  The penalty
        applies only when one side is a singleton letter (a letter wrapped in a
        length-one group) or a singleton group, and the other side is of the other
        object type.

        This used to penalise *every* letter-group bridge by 0.1, which made an
        a-aa bridge unable to compete with a-a — so the whole letter => group
        slippage family of §3.3.1 and Fig. 3.1 was effectively unreachable, and
        problems like "abc => aabbcc" could never be described at all.
        """
        o1, o2 = self.object1, self.object2
        if _is_singleton_letter(o1):
            return 1.0 if not _is_group(o2) else 0.1
        if _is_singleton_letter(o2):
            return 1.0 if not _is_group(o1) else 0.1
        if _is_singleton_group(o1):
            return 1.0 if _is_group(o2) else 0.1
        if _is_singleton_group(o2):
            return 1.0 if _is_group(o1) else 0.1
        return 1.0

    def calculate_external_strength(self) -> float:
        """External strength from supporting bridges.

        Scheme: bridges.ss:400-410, 794-804.
        """
        # Check for spanning singleton letter
        if self._is_spanning_singleton():
            return 100.0
        # Sum of supporting bridge strengths, capped at 100
        support = self._get_supporting_bridge_strength()
        return min(100.0, round(support))

    def _is_spanning_singleton(self) -> bool:
        """Does *either* object span its whole string as a lone letter?

        Scheme: ``bridges.ss:401-402`` and ``bridges.ss:795-796`` —

            (if (or (and (letter? object1) (tell object1 'spans-whole-string?))
                    (and (letter? object2) (tell object2 'spans-whole-string?)))
              100 ...)

        ``or``, not ``and``.  A lone letter has no siblings to draw support from, so
        it is granted full external strength rather than being starved of it; the
        earlier reading required *both* sides to be lone letters, which meant a
        multi-letter string mapping to a one-letter string — ``ab -> c`` — got no
        external support at all and could never build a horizontal bridge.
        """
        for obj in (self.object1, self.object2):
            if not hasattr(obj, "objects") and obj.spans_whole_string():
                return True
        return False

    def _get_supporting_bridge_strength(self) -> float:
        """Sum strength of supporting bridges in the same orientation.

        Scheme: bridges.ss:400-410 (horizontal), 794-804 (vertical).
        Supporting bridges are those in the same bridge_type that are not
        incompatible and share at least one supporting CM pair.
        """
        workspace = self._find_workspace()
        if workspace is None:
            return 0.0

        same_type_bridges = _get_bridges_of_type(workspace, self.bridge_type)
        total = 0.0
        for other in same_type_bridges:
            if other is self:
                continue
            if _supporting_bridges(self, other, self.orientation):
                total += other.strength
        return total

    @property
    def theme_type(self) -> str:
        """The Themespace theme type this bridge feeds."""
        from server.engine.themes import (
            THEME_BOTTOM_BRIDGE,
            THEME_TOP_BRIDGE,
            THEME_VERTICAL_BRIDGE,
        )

        return {
            BRIDGE_TOP: THEME_TOP_BRIDGE,
            BRIDGE_BOTTOM: THEME_BOTTOM_BRIDGE,
            BRIDGE_VERTICAL: THEME_VERTICAL_BRIDGE,
        }[self.bridge_type]

    @property
    def is_spanning_bridge(self) -> bool:
        """True when both bridged objects span their whole strings.

        Spanning bridges boost their themes twice as hard (bridges.ss:308-310).
        """
        return _spans_whole_string(self.object1) and _spans_whole_string(self.object2)

    def get_associated_thematic_relations(self) -> list[tuple[str, str]]:
        """(dimension, relation) pairs this bridge contributes to the Themespace.

        Scheme: ``get-associated-thematic-relations`` (bridges.ss:314-322) and
        ``boost-themes`` (bridges.ss:296-313).

        Note this walks the **cross-product of the two objects' descriptions**,
        not the bridge's concept-mappings.  Deriving relations from CMs (as this
        used to) silently drops every ``X: different`` theme, because those are
        exactly the label-less case — and the dissertation needs them: vertical
        ``Letter-Category: different`` and ``Object-Type: different`` are dominant
        in Figs. 4.1/4.2, and ``Bond-Facet: different`` carries the whole
        eqe/abbbc analysis of §4.7.2.
        """
        from server.engine.themes import relation_name_for_label

        relations: list[tuple[str, str]] = []
        for d1 in _all_descriptions(self.object1):
            for d2 in _all_descriptions(self.object2):
                if not descriptions_affect_themespace(d1, d2):
                    continue
                dimension = getattr(d1.description_type, "name", None)
                if dimension is None:
                    continue
                relation = relation_name_for_label(
                    _label_node(d1.descriptor, d2.descriptor)
                )
                relations.append((dimension, relation))
        return relations

    def get_theme_pattern(self) -> dict[str, Any]:
        """Dict view of :meth:`get_associated_thematic_relations`."""
        return dict(self.get_associated_thematic_relations())

    # ------------------------------------------------------------------
    # Thematic compatibility  (Scheme: bridges.ss:270-287)
    # ------------------------------------------------------------------

    def get_thematic_compatibility(self) -> float:
        """How well this bridge resonates with the active themes, in -1..+1.

        §4.1.2: themes "act like a set of knobs that can be used to smoothly
        vary the strengths of Workspace structures".  Returns 0 whenever
        thematic pressure is off, which is the normal case.
        """
        return _bridge_theme_compatibility_sigmoid(self.get_average_theme_support())

    def get_average_theme_support(self) -> float:
        """Weighted mean of per-theme support values, in -1..+1.

        Negative values carry weight ``2 * n`` against positives' weight 1, so
        "the incompatible themes will tend to drown out the compatible themes,
        even if the latter outnumber the former" (§4.1.2, p.143).
        """
        values = self.get_theme_support_values()
        if not values:
            return 0.0
        neg_weight = 2.0 * len(values)
        weights = [(neg_weight if v < 0 else 1.0) * abs(v) for v in values]
        if not any(weights):
            return 0.0
        return sum(v * w for v, w in zip(values, weights)) / sum(weights)

    def get_theme_support_values(self) -> list[float]:
        """Per-theme support in -1..+1: negative if incompatible, positive if supported."""
        themespace = WorkspaceStructure.get_themespace()
        if themespace is None:
            return []
        values: list[float] = []
        for theme in themespace.get_active_themes(self.theme_type):
            if theme.activation == 0:
                continue
            if self.incompatible_with_theme(theme):
                values.append(-theme.activation / 100.0)
            elif self.supported_by_theme(theme):
                values.append(theme.activation / 100.0)
            else:
                values.append(0.0)
        return values

    def incompatible_with_theme(self, theme: Any) -> bool:
        """Scheme: ``incompatible-with-theme?`` (bridges.ss:254-268)."""
        if _check_descriptions(self.object1, self.object2, _conflicts_with_theme, theme):
            return True
        # A theme whose dimension can describe one object but not the other is
        # itself evidence against the bridge.
        dim = theme.dimension
        possible1 = _description_possible(dim, self.object1)
        possible2 = _description_possible(dim, self.object2)
        if possible1 != possible2:
            return True
        return (
            dim == "plato-string-position-category"
            and not possible1
            and not possible2
        )

    def supported_by_theme(self, theme: Any) -> bool:
        """Scheme: ``supported-by-theme?`` (bridges.ss:268-269)."""
        return _check_descriptions(
            self.object1, self.object2, _supported_by_theme, theme
        )

    def get_incompatible_bridges(self, workspace: Any = None) -> list[Bridge]:
        """Find bridges that conflict with this one.

        Scheme: bridges.ss:324-338 (horizontal), 728-741 (vertical).
        Incompatible bridges share an object with this bridge or have
        incompatible concept mappings.
        """
        ws = workspace or self._find_workspace()
        if ws is None:
            return []

        same_type_bridges = _get_bridges_of_type(ws, self.bridge_type)
        result: list[Bridge] = []
        for other in same_type_bridges:
            if other is self:
                continue
            if _incompatible_bridges(other, self, self.orientation):
                result.append(other)

        # Also check group-incompatible bridges
        result.extend(_group_incompatible_bridges(
            self.orientation, self.object1, self.object2
        ))

        # Remove duplicates
        seen: set[int] = set()
        unique: list[Bridge] = []
        for b in result:
            if id(b) not in seen:
                seen.add(id(b))
                unique.append(b)
        return unique

    def get_incompatible_bond(self) -> Any:
        """Find bonds incompatible with this bridge's CMs.

        Scheme: bridges.ss:339-361 (horizontal), 742-764 (vertical).
        Checks if bonds adjacent to both bridged objects have directions
        that create incompatible concept mappings with this bridge.
        """
        obj1 = self.object1
        obj2 = self.object2

        # Get the relevant bond from each object
        bond1 = _get_edge_bond(obj1)
        bond2 = _get_edge_bond(obj2)

        if bond1 is None or bond2 is None:
            return None

        # Both must be directed
        if not getattr(bond1, "directed", False) or not getattr(bond2, "directed", False):
            return None

        # Check if the direction CM is incompatible with this bridge's CMs
        dir1 = bond1.direction
        dir2 = bond2.direction
        if dir1 is None or dir2 is None:
            return None

        from server.engine.concept_mappings import ConceptMapping

        # Create a direction-category CM between the two bonds' directions
        # Look for a plato-direction-category node from the existing CMs
        dir_cat_node = None
        for cm in self.concept_mappings:
            if getattr(cm.description_type1, "name", "") == "plato-direction-category":
                dir_cat_node = cm.description_type1
                break

        if dir_cat_node is None:
            return None

        direction_cm = ConceptMapping(
            description_type1=dir_cat_node,
            descriptor1=dir1,
            description_type2=dir_cat_node,
            descriptor2=dir2,
            object1=bond1,
            object2=bond2,
        )

        # Check if this direction CM is incompatible with any of the bridge's CMs
        for cm in self.concept_mappings:
            if _incompatible_cms(direction_cm, cm):
                return bond2

        return None

    def supports_theme_pattern(self, pattern: dict[str, Any]) -> bool:
        """Check if bridge's theme pattern supports a given pattern.

        Scheme: bridges.ss:239-246 (horizontal), 643-650 (vertical).
        True if any entry in the pattern matches a CM's type and label,
        excluding whole/single CMs.
        """
        # Filter out whole/single CMs
        filtered_cms = [
            cm for cm in self.concept_mappings
            if not _is_whole_or_single_cm(cm)
        ]

        for dim, rel in pattern.items():
            for cm in filtered_cms:
                cm_type_name = getattr(cm.description_type1, "name", "")
                cm_label_name = getattr(cm.label, "name", "") if cm.label else ""
                if cm_type_name == dim and cm_label_name == rel:
                    return True
        return False

    def _find_workspace(self) -> Any:
        """Try to find the workspace from the bridged objects."""
        for obj in (self.object1, self.object2):
            string = getattr(obj, "string", None)
            if string is not None:
                ws = getattr(string, "workspace", None)
                if ws is not None:
                    return ws
        return None

    def add_concept_mapping(self, cm: ConceptMapping) -> None:
        """Add a new concept mapping to this bridge."""
        if cm not in self.concept_mappings:
            self.concept_mappings.append(cm)

    def __repr__(self) -> str:
        n_cms = len(self.concept_mappings)
        return (
            f"Bridge({self.bridge_type}, {self.object1}->{self.object2}, "
            f"{n_cms} CMs, strength={self.strength:.0f})"
        )


# ---------------------------------------------------------------------------
# Object / description helpers
# ---------------------------------------------------------------------------


def _spans_whole_string(obj: Any) -> bool:
    spans = getattr(obj, "spans_whole_string", None)
    if callable(spans):
        return bool(spans())
    return False


def _is_group(obj: Any) -> bool:
    return hasattr(obj, "objects")


def _string_spanning_group(obj: Any) -> bool:
    """Scheme: ``string-spanning-group?`` (workspace-objects.ss:354)."""
    return _is_group(obj) and _spans_whole_string(obj)


def _is_singleton_group(obj: Any) -> bool:
    """Scheme: ``singleton-group?`` (groups.ss:269) — a group of exactly one object."""
    return _is_group(obj) and len(getattr(obj, "objects", [])) == 1


def _is_singleton_letter(obj: Any) -> bool:
    """Scheme: ``singleton-letter?`` (bridges.ss:818-822).

    A letter whose enclosing group wraps it and nothing else.
    """
    if _is_group(obj):
        return False
    enclosing = getattr(obj, "enclosing_group", None)
    return enclosing is not None and _is_singleton_group(enclosing)


def _all_descriptions(obj: Any) -> list[Any]:
    """Descriptions of *obj*, including a group's bond descriptions."""
    getter = getattr(obj, "get_all_descriptions", None)
    if callable(getter):
        return list(getter())
    return list(getattr(obj, "descriptions", []))


def _label_node(descriptor1: Any, descriptor2: Any) -> Any:
    """Scheme: ``get-label`` (slipnet.ss).

    Identical descriptors relate by identity; linked descriptors relate by the
    link's label; anything else has no relating concept at all.
    """
    if descriptor1 is descriptor2:
        return _IDENTITY_SENTINEL
    for link in getattr(descriptor1, "outgoing_links", []):
        if link.to_node is descriptor2:
            return link.label_node
    return None


class _IdentitySentinel:
    """Stands in for ``plato-identity`` where no Slipnet handle is available."""

    name = "plato-identity"
    short_name = "iden"


_IDENTITY_SENTINEL = _IdentitySentinel()


def _label_relation(descriptor1: Any, descriptor2: Any) -> str:
    """Bare theme-relation name relating two descriptors."""
    from server.engine.themes import relation_name_for_label

    return relation_name_for_label(_label_node(descriptor1, descriptor2))


def descriptions_affect_themespace(d1: Any, d2: Any) -> bool:
    """Should this description pair contribute a theme?

    Scheme: ``descriptions-affect-themespace?`` / ``ignore-descriptions?``
    (themes.ss:1093-1107).
    """
    if d1.description_type is not d2.description_type:
        return False
    if not d1.is_relevant() or not d2.is_relevant():
        return False

    dt_name = getattr(d1.description_type, "name", "")
    o1, o2 = d1.object, d2.object

    if dt_name == "plato-object-category" and (
        _string_spanning_group(o1) and _string_spanning_group(o2)
    ):
        return False
    if dt_name == "plato-string-position-category" and (
        _spans_whole_string(o1) and _spans_whole_string(o2)
    ):
        return False
    if (
        getattr(d1.descriptor, "name", "") == "plato-middle"
        and getattr(d2.descriptor, "name", "") == "plato-middle"
    ):
        return False
    return True


# ---------------------------------------------------------------------------
# Theme compatibility predicates  (Scheme: themes.ss:1033-1090)
# ---------------------------------------------------------------------------


def _check_descriptions(object1: Any, object2: Any, pred: Any, theme: Any) -> bool:
    """Scheme: ``check-descriptions`` (themes.ss:1033-1040)."""
    for d1 in _all_descriptions(object1):
        for d2 in _all_descriptions(object2):
            if d1.description_type is d2.description_type and pred(d1, d2, theme):
                return True
    return False


def _theme_dimension_applies(d1: Any, d2: Any, theme: Any) -> bool:
    dt_name = getattr(d1.description_type, "name", "")
    if dt_name == theme.dimension:
        return True
    return _special_direction_case(d1, d2, theme)


def _special_direction_case(d1: Any, d2: Any, theme: Any) -> bool:
    """Direction descriptions on two spanning groups speak for string position."""
    return (
        getattr(d1.description_type, "name", "") == "plato-direction-category"
        and _string_spanning_group(d1.object)
        and _string_spanning_group(d2.object)
        and theme.dimension == "plato-string-position-category"
    )


def _special_spanning_bridge_case(d1: Any, d2: Any, theme: Any) -> bool:
    dt_name = getattr(d1.description_type, "name", "")
    if (
        dt_name == "plato-object-category"
        and _string_spanning_group(d1.object)
        and _string_spanning_group(d2.object)
        and theme.dimension == "plato-object-category"
    ):
        return True
    return (
        dt_name == "plato-string-position-category"
        and _spans_whole_string(d1.object)
        and _spans_whole_string(d2.object)
        and theme.dimension == "plato-string-position-category"
    )


def _special_middle_middle_case(d1: Any, d2: Any, theme: Any) -> bool:
    from server.engine.themes import RELATION_OPPOSITE

    return (
        getattr(d1.descriptor, "name", "") == "plato-middle"
        and getattr(d2.descriptor, "name", "") == "plato-middle"
        and theme.dimension == "plato-string-position-category"
        and theme.relation == RELATION_OPPOSITE
    )


def _relation_consistent_with_theme(d1: Any, d2: Any, theme: Any) -> bool:
    from server.engine.themes import RELATION_DIFFERENT, RELATION_IDENTITY

    relation = _label_relation(d1.descriptor, d2.descriptor)
    if theme.relation == RELATION_DIFFERENT:
        return relation != RELATION_IDENTITY
    return relation == theme.relation


def _conflicts_with_theme(d1: Any, d2: Any, theme: Any) -> bool:
    """Scheme: ``conflicts-with-theme?`` (themes.ss:1047-1053)."""
    return (
        _theme_dimension_applies(d1, d2, theme)
        and not _special_spanning_bridge_case(d1, d2, theme)
        and not _special_middle_middle_case(d1, d2, theme)
        and not _relation_consistent_with_theme(d1, d2, theme)
    )


def _supported_by_theme(d1: Any, d2: Any, theme: Any) -> bool:
    """Scheme: ``supported-by-theme?`` (themes.ss:1055-1061)."""
    return (
        _theme_dimension_applies(d1, d2, theme)
        and not _special_spanning_bridge_case(d1, d2, theme)
        and (
            _special_middle_middle_case(d1, d2, theme)
            or _relation_consistent_with_theme(d1, d2, theme)
        )
    )


def objects_conflict_with_theme(object1: Any, object2: Any, theme: Any) -> bool:
    """Do the two objects' descriptions contradict *theme*?

    Scheme: the ``conflicts?`` half of ``theme-support-tester``
    (themes.ss:1023-1026) — plain ``check-descriptions``, with none of the
    description-possible asymmetry ``Bridge.incompatible_with_theme`` adds.  A
    thematic scout is asking whether a bridge *could* be built to support the
    themes, so it must judge the objects as they stand.
    """
    return _check_descriptions(object1, object2, _conflicts_with_theme, theme)


def objects_support_theme(object1: Any, object2: Any, theme: Any) -> bool:
    """Do the two objects' descriptions bear *theme* out?

    Scheme: the ``supports?`` half of ``theme-support-tester`` (themes.ss:1027-1028).
    """
    return _check_descriptions(object1, object2, _supported_by_theme, theme)


def _description_possible(dimension_name: str, obj: Any) -> bool:
    """Can *obj* be described along *dimension_name*?

    Scheme: ``description-possible?`` on a Slipnet category node.
    """
    for d in _all_descriptions(obj):
        if getattr(d.description_type, "name", "") == dimension_name:
            return True
    return False


def _bridge_theme_compatibility_sigmoid(x: float) -> float:
    """Sharpen a raw support value.  Scheme: themes.ss:1115, beta = 4."""
    import math

    beta = 4.0
    try:
        return 2.0 / (1.0 + math.exp(-2.0 * beta * x)) - 1.0
    except OverflowError:  # pragma: no cover - x is always within -1..+1
        return -1.0 if x < 0 else 1.0


# ---------------------------------------------------------------------------
# Mappable descriptions  (Scheme: bridges.ss)
#
# §3.3.1: "slippages involving length or letter-category, such as one => two or
# c => d, are only possible for horizontal bridges."  Horizontal concept-mappings
# ground both similarity and difference — a rule is abstracted from them — while
# vertical ones ground similarity only.
# ---------------------------------------------------------------------------


def _slip_linked(descriptor1: Any, descriptor2: Any) -> bool:
    return any(
        link.to_node is descriptor2
        for link in getattr(descriptor1, "lateral_sliplinks", [])
    )


def vertical_mappable_descriptions(d1: Any, d2: Any) -> bool:
    """Scheme: ``vertical-mappable-descriptions?`` (bridges.ss:1620-1630)."""
    if d1.description_type is not d2.description_type:
        return False
    return d1.descriptor is d2.descriptor or _slip_linked(d1.descriptor, d2.descriptor)


def horizontal_mappable_descriptions(d1: Any, d2: Any, object1: Any, object2: Any) -> bool:
    """Scheme: ``horizontal-mappable-descriptions?`` (bridges.ss)."""
    if d1.description_type is not d2.description_type:
        return False
    dt_name = getattr(d1.description_type, "name", "")
    if dt_name == "plato-letter-category":
        return _letter_category_mappable_objects(object1, object2)
    if dt_name in ("plato-string-position-category", "plato-length"):
        return True
    return d1.descriptor is d2.descriptor or _slip_linked(d1.descriptor, d2.descriptor)


def _letter_category_mappable_objects(object1: Any, object2: Any) -> bool:
    """Letter-category mappings need a letter-category to speak of on both sides.

    Scheme: ``letter-category-mappable-objects?``.  A group only has one when its
    bond facet is letter-category (``jjj`` is a "j" group; ``mrrjjj`` is not).
    """
    return _has_letter_category(object1) and _has_letter_category(object2)


def _has_letter_category(obj: Any) -> bool:
    if not _is_group(obj):
        return True
    facet = getattr(obj, "bond_facet", None)
    return getattr(facet, "name", "") == "plato-letter-category"


def mappable_descriptions(
    d1: Any, d2: Any, object1: Any, object2: Any, bridge_type: str
) -> bool:
    """Dispatch to the horizontal or vertical predicate for *bridge_type*."""
    if bridge_type == BRIDGE_VERTICAL:
        return vertical_mappable_descriptions(d1, d2)
    return horizontal_mappable_descriptions(d1, d2, object1, object2)


def make_concept_mappings(
    object1: Any,
    object2: Any,
    bridge_type: str,
    identity_node: Any = None,
) -> list[ConceptMapping]:
    """Build the concept-mappings supporting a bridge of *bridge_type*.

    Applies the §3.3.1 horizontal/vertical asymmetry, so a vertical a-i bridge
    gets no ``LetterCategory: a => i`` slippage while the horizontal one does.
    """
    from server.engine.concept_mappings import ConceptMapping

    cms: list[ConceptMapping] = []
    seen: set[tuple[int, int, int]] = set()
    for d1 in _all_descriptions(object1):
        for d2 in _all_descriptions(object2):
            if not mappable_descriptions(d1, d2, object1, object2, bridge_type):
                continue
            key = (id(d1.description_type), id(d1.descriptor), id(d2.descriptor))
            if key in seen:
                continue
            seen.add(key)
            label = _label_node(d1.descriptor, d2.descriptor)
            if label is _IDENTITY_SENTINEL:
                label = identity_node
            cms.append(
                ConceptMapping(
                    d1.description_type,
                    d1.descriptor,
                    d2.description_type,
                    d2.descriptor,
                    label,
                    object1=object1,
                    object2=object2,
                )
            )
    return cms


def propose_bridge(
    bridge_type: str,
    object1: Any,
    flip1: bool,
    object2: Any,
    flip2: bool,
    identity_node: Any = None,
) -> Bridge:
    """Build a proposed bridge, optionally against a reversed reading of a group.

    Scheme: ``propose-bridge`` (bridges.ss:1085-1105).  When a side is flipped the
    bridge is made to the flipped group — a genuinely different object, with the
    opposite direction and group-category — and the original is remembered so the
    builder can fight it and then swap it out.

    Note the mappings are computed *after* flipping, which is the whole point:
    ``>abc>`` and ``<cba<`` share no Direction concept-mapping, while ``>abc>``
    and ``>cba>`` do.
    """
    obj1 = object1.make_flipped_version() if flip1 else object1
    obj2 = object2.make_flipped_version() if flip2 else object2
    bridge = Bridge(
        obj1, obj2, bridge_type, make_concept_mappings(obj1, obj2, bridge_type, identity_node)
    )
    # ``make_flipped_version`` returns the group itself when there is no direction
    # to reverse, and a bridge to an object that *is* the original is not a flip.
    if flip1 and obj1 is not object1:
        bridge.flipped_group1 = object1
    if flip2 and obj2 is not object2:
        bridge.flipped_group2 = object2
    return bridge


# ---------------------------------------------------------------------------
# Module-level helper functions
# ---------------------------------------------------------------------------


def _supporting_cms(cm1: ConceptMapping, cm2: ConceptMapping) -> bool:
    """Two CMs support each other if they are equal or share related descriptors
    with the same label.

    Scheme: bridges.ss:1593-1600 (supporting-horizontal-CMs?), 1681-1688 (vertical).
    Both horizontal and vertical use the same logic.
    """
    # Equal CMs always support
    if cm1 == cm2:
        return True

    # Both must have labels
    if cm1.label is None or cm2.label is None:
        return False
    if cm1.label is not cm2.label:
        return False

    # Check related descriptors
    related1 = _nodes_related(cm1.descriptor1, cm2.descriptor1)
    related2 = _nodes_related(cm1.descriptor2, cm2.descriptor2)
    return related1 or related2


def _incompatible_cms(cm1: ConceptMapping, cm2: ConceptMapping) -> bool:
    """Two CMs are incompatible if they have related descriptors but different labels,
    and the label relationship differs between the descriptor pairs.

    Scheme: bridges.ss:1603-1615 (horizontal), 1691-1703 (vertical).
    """
    # Both must have labels
    if cm1.label is None or cm2.label is None:
        return False
    if cm1.label is cm2.label:
        return False

    # Check related descriptors
    related1 = _nodes_related(cm1.descriptor1, cm2.descriptor1)
    related2 = _nodes_related(cm1.descriptor2, cm2.descriptor2)
    if not (related1 or related2):
        return False

    # Check that the label relationship between the descriptor pairs differs
    # (i.e., get-label(cm1-desc1, cm2-desc1) != get-label(cm1-desc2, cm2-desc2)).
    # This is the §3.5 refinement: incompatibility needs *both* different
    # relations and differently-linked descriptor pairs.
    return _label_relation(cm1.descriptor1, cm2.descriptor1) != _label_relation(
        cm1.descriptor2, cm2.descriptor2
    )


def _nodes_related(node1: Any, node2: Any) -> bool:
    """Two nodes are related if they are the same or linked.

    Scheme: slipnet.ss:352-354.
    """
    if node1 is node2:
        return True
    # Check if linked via any outgoing link
    for link in getattr(node1, "outgoing_links", []):
        if link.to_node is node2:
            return True
    return False



def _incompatible_bridges(b1: Bridge, b2: Bridge, orientation: str) -> bool:
    """Two bridges are incompatible if they share an object or have
    incompatible CM lists.

    Scheme: bridges.ss:1551-1585 (horizontal), 1641-1674 (vertical).
    """
    # Shared objects => incompatible
    if b1.object1 is b2.object1 or b1.object2 is b2.object2:
        return True

    # Check CM-level incompatibility
    b1_cms = b1.concept_mappings
    b2_cms = b2.concept_mappings

    for cm1 in b1_cms:
        for cm2 in b2_cms:
            if _incompatible_cms(cm1, cm2):
                return True
    return False


def _supporting_bridges(b1: Bridge, b2: Bridge, orientation: str) -> bool:
    """Two bridges support each other if not incompatible and have at least
    one pair of supporting distinguishing CMs.

    Scheme: bridges.ss:1542-1548 (horizontal), 1632-1638 (vertical).
    """
    if _incompatible_bridges(b1, b2, orientation):
        return False

    b1_dist_cms = b1.get_distinguishing_concept_mappings()
    b2_dist_cms = b2.get_distinguishing_concept_mappings()

    for cm1 in b1_dist_cms:
        for cm2 in b2_dist_cms:
            if _supporting_cms(cm1, cm2):
                return True
    return False


def _get_bridges_of_type(workspace: Any, bridge_type: str) -> list[Bridge]:
    """Get all bridges of a given type from the workspace.

    This used to probe a ``workspace.bridges`` dict that does not exist, so
    ``getattr`` handed back ``{}`` and the function returned an empty list every
    single time — silently disabling both bridge support (external strength was
    always 0) and bridge incompatibility (mutually contradictory bridges such as
    a-a, a-b and a-d all stayed built at once).
    """
    attribute = {
        BRIDGE_TOP: "top_bridges",
        BRIDGE_BOTTOM: "bottom_bridges",
        BRIDGE_VERTICAL: "vertical_bridges",
    }.get(bridge_type)
    if attribute is None:
        return []
    return list(getattr(workspace, attribute, []))


def _group_incompatible_bridges(
    orientation: str, object1: Any, object2: Any
) -> list[Bridge]:
    """Find bridges on subobjects or enclosing groups that are incompatible.

    Scheme: bridges.ss:826-866 (group-incompatible-bridges).
    """
    result: list[Bridge] = []

    # Check subobject bridges for group objects
    for obj, other in ((object1, object2), (object2, object1)):
        if hasattr(obj, "objects"):  # It's a group
            bridge_attr = "horizontal_bridge" if orientation == "horizontal" else "vertical_bridge"
            for sub in getattr(obj, "objects", []):
                bridge = getattr(sub, bridge_attr, None)
                if bridge is not None:
                    # If other is a letter, all subobject bridges are incompatible
                    # If other is a group, only if the bridge's other object is not a
                    # top-level member of the other group
                    if not hasattr(other, "objects"):
                        result.append(bridge)
                    else:
                        other_obj = bridge.object2 if bridge.object1 is sub else bridge.object1
                        if other_obj not in getattr(other, "objects", []):
                            result.append(bridge)

    # Check enclosing group bridges
    for obj, other_obj in ((object1, object2), (object2, object1)):
        enc = getattr(obj, "enclosing_group", None)
        if enc is not None:
            bridge_attr = "horizontal_bridge" if orientation == "horizontal" else "vertical_bridge"
            group_bridge = getattr(enc, bridge_attr, None)
            if group_bridge is not None:
                # Incompatible if the other side's enclosing group doesn't match
                other_enc = getattr(other_obj, "enclosing_group", None)
                bridge_other = group_bridge.object2 if group_bridge.object1 is enc else group_bridge.object1
                if other_enc is None or other_enc is not bridge_other:
                    result.append(group_bridge)

    return result


def _get_edge_bond(obj: Any) -> Any:
    """Get the bond adjacent to this object at the edge of its string.

    Scheme: bridges.ss:340-345.
    If leftmost, get right bond; if rightmost (or default), get left bond.
    """
    if getattr(obj, "left_string_pos", -1) == 0:
        return getattr(obj, "right_bond", None)
    return getattr(obj, "left_bond", None)


def _is_whole_or_single_cm(cm: ConceptMapping) -> bool:
    """Check if a CM involves plato-whole or plato-single for string-position.

    Scheme: justify.ss:220-229 (remove-whole/single-concept-mappings).
    """
    dt_name = getattr(cm.description_type1, "name", "")
    if dt_name != "plato-string-position-category":
        return False
    d1_name = getattr(cm.descriptor1, "name", "")
    return d1_name in ("plato-whole", "plato-single")
