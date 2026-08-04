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
    from server.engine.rng import RNG
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
        # Two lists the Scheme keeps alongside the main one and consults in
        # different places (bridges.ss:150-172).  ``bond_concept_mappings`` holds
        # the mappings between two groups' *bond* descriptions, computed at build
        # time (bridges.ss:1386-1393); they are deliberately outside
        # ``concept_mappings``, so they never enter strength, incompatibility,
        # support, or rule abstraction.  ``symmetric_slippages`` holds the reverse
        # of every slippage the bridge carries, which is what lets an established
        # mapping be looked up from either side.
        self.bond_concept_mappings: list[ConceptMapping] = []
        self.symmetric_slippages: list[ConceptMapping] = []
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

    # ------------------------------------------------------------------
    # The three concept-mapping lists  (Scheme: bridges.ss:150-238)
    # ------------------------------------------------------------------

    def get_all_concept_mappings(self) -> list[ConceptMapping]:
        """``get-all-concept-mappings`` (bridges.ss:161) — main list plus bond CMs."""
        return self.concept_mappings + self.bond_concept_mappings

    def get_non_symmetric_slippages(self) -> list[ConceptMapping]:
        """``get-non-symmetric-slippages`` (bridges.ss:162-163) — over *all* CMs."""
        return [cm for cm in self.get_all_concept_mappings() if cm.is_slippage]

    def get_non_symmetric_non_bond_slippages(self) -> list[ConceptMapping]:
        """``get-non-symmetric-non-bond-slippages`` (bridges.ss:164-165).

        The main list only — this is what a rule is abstracted from.
        """
        return [cm for cm in self.concept_mappings if cm.is_slippage]

    def get_slippages(self) -> list[ConceptMapping]:
        """``get-slippages`` (bridges.ss:167-170) — non-symmetric plus symmetric."""
        return self.get_non_symmetric_slippages() + self.symmetric_slippages

    def get_bond_slippages(self) -> list[ConceptMapping]:
        """``get-bond-slippages`` (bridges.ss:171-172).

        The slippages between two groups' *bond* descriptions.  Rule translation
        adds these to the slippages a clause is translated by when the clause's
        reference objects sit inside groups that are themselves bridged
        (``answers.ss:1487-1490``) — a successor group standing for a predecessor
        group is a fact about the enclosing groups, not about their members.
        """
        return [cm for cm in self.get_slippages() if cm.bond_concept_mapping]

    def get_letter_span(self) -> int:
        """``get-letter-span`` (bridges.ss:178-180) — span(object1) + span(object2).

        The weight both sides carry into a bridge-vs-bridge fight, so a spanning
        bridge over ``abc`` meets a letter bridge at 6 to 2.
        """
        return int(getattr(self.object1, "span", 1)) + int(
            getattr(self.object2, "span", 1)
        )

    def add_concept_mappings(self, cms: list[ConceptMapping]) -> None:
        """``add-concept-mappings`` (bridges.ss:210-213)."""
        self.concept_mappings.extend(cms)

    def add_bond_concept_mapping(self, cm: ConceptMapping) -> None:
        """``add-bond-concept-mapping`` (bridges.ss:222-225)."""
        self.bond_concept_mappings.append(cm)

    def add_symmetric_slippage(self, slippage: ConceptMapping) -> None:
        """``add-symmetric-slippage`` (bridges.ss:226-230)."""
        self.symmetric_slippages.append(slippage.symmetric_mapping())

    def concept_mapping_present(self, cm: ConceptMapping) -> bool:
        """``concept-mapping-present?`` (bridges.ss:231-233).

        ``CMs-equal?`` (concept-mappings.ss:175-178) compares the two
        **descriptors** and nothing else, so a mapping already made along one
        dimension is not re-made along another that happens to share them.
        """
        return any(
            other.descriptor1 is cm.descriptor1 and other.descriptor2 is cm.descriptor2
            for other in self.get_all_concept_mappings()
        )

    def cm_type_present(self, description_type: Any) -> bool:
        """``CM-type-present?`` (bridges.ss:234-235)."""
        return any(
            cm.description_type1 is description_type
            for cm in self.get_all_concept_mappings()
        )

    def delete_concept_mapping_type(self, description_type: Any) -> None:
        """``delete-concept-mapping-type`` (bridges.ss:214-221).

        Drops one mapping of the given dimension from the main list and its
        symmetric counterpart from the slippage list.  Used when a ``middle``
        string-position description is invalidated out from under a bridge.
        """
        for cm in list(self.concept_mappings):
            if cm.description_type1 is description_type:
                self.concept_mappings.remove(cm)
                break
        for slippage in list(self.symmetric_slippages):
            if slippage.description_type1 is description_type:
                self.symmetric_slippages.remove(slippage)
                break

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

    def calculate_external_strength(self, rng: RNG | None = None) -> float:
        """External strength from supporting bridges.

        Scheme: bridges.ss:400-410, 794-804.

        *rng* is accepted to match the base signature and unused: a bridge's
        external strength counts peers, it does not walk neighbours.
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

        Bond descriptions are *not* walked: ``boost-themes`` (bridges.ss:311-312)
        and ``get-associated-thematic-relations`` (bridges.ss:321-322) both pass
        ``get-descriptions``, the plain list.  Reading the bond ones as well gave
        Bond-Category and Bond-Facet themes workspace activation the reference
        never gives them, from which they could go on to appear in dominant
        patterns, in answer indexing, and in the theme pattern a snag clamps.
        """
        from server.engine.themes import relation_name_for_label

        relations: list[tuple[str, str]] = []
        for d1 in _plain_descriptions(self.object1):
            for d2 in _plain_descriptions(self.object2):
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
        """Per-theme support in -1..+1: negative if incompatible, positive if supported.

        One value per theme of every *active* type — ``get-active-themes``
        (themes.ss:181-186) returns the whole cluster set, not only the themes
        that happen to carry activation, and ``get-theme-support-values``
        (bridges.ss:280-288) maps over all of them, contributing 0 for a theme
        the bridge neither supports nor contradicts.  Skipping the zeroes shrank
        ``n``, and ``n`` is what sets the negative weight ``2n``
        (bridges.ss:275) — so the "incompatible themes drown out compatible ones"
        asymmetry of §4.1.2 was weaker than the reference's by exactly the
        proportion of quiet themes.
        """
        themespace = WorkspaceStructure.get_themespace()
        if themespace is None:
            return []
        values: list[float] = []
        for theme in themespace.get_active_themes(self.theme_type):
            if self.incompatible_with_theme(theme):
                values.append(-theme.activation / 100.0)
            elif self.supported_by_theme(theme):
                values.append(theme.activation / 100.0)
            else:
                values.append(0.0)
        return values

    def incompatible_with_theme(self, theme: Any) -> bool:
        """Scheme: ``incompatible-with-theme?`` (bridges.ss:254-267).

        The second half asks ``(tell dimension 'description-possible? object)`` —
        whether the object *could* be described along the theme's dimension, not
        whether it happens to be already.  Testing presence instead penalised a
        bridge under pressure for a dimension neither side had got round to being
        described along, which is the situation thematic pressure exists to
        remedy.
        """
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

        Scheme: bridges.ss:324-338 (horizontal), 728-741 (vertical) — three
        sources appended: the same-type bridges the pairwise predicate rejects,
        the group-level conflicts, and, when both objects are spanning groups
        carrying a Direction mapping, the sub-bridges whose left-to-right
        ordering contradicts it.
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

        if _string_spanning_group(self.object1) and _string_spanning_group(self.object2):
            direction_cm = next(
                (cm for cm in self.concept_mappings if _is_direction_cm(cm)), None
            )
            if direction_cm is not None:
                result.extend(
                    direction_incompatible_bridges(
                        self.orientation, self.object1, self.object2, direction_cm
                    )
                )

        # Remove duplicates
        seen: set[int] = set()
        unique: list[Bridge] = []
        for b in result:
            if id(b) not in seen:
                seen.add(id(b))
                unique.append(b)
        return unique

    def get_incompatible_bond(self) -> Any:
        """The bond on object2's side that this bridge's mappings contradict.

        Scheme: ``get-incompatible-bond`` (bridges.ss:339-361 horizontal,
        742-764 vertical).  Take the bond running *into the string* from each
        object — the right bond if the object is leftmost, else the left bond —
        require both to be directed, and ask whether a Direction-Category
        mapping between those two directions would be incompatible with any
        mapping the bridge already carries.  If so the loser is ``bond2``, and
        the builder fights it 3 to 2.

        The probe mapping is built from ``plato-direction-category``
        **unconditionally** (bridges.ss:350-357).  Sourcing that node from a
        Direction CM the bridge already had made the whole method vacuous in the
        case it exists for: a bridge whose mappings are ``StrPosCtgy:
        lmost=(opp)=>rmost`` and no direction mapping at all is exactly the one
        whose reading of the string contradicts a directed bond, and it could
        never find the node to say so.
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

        dir_cat_node = _slipnet_node(obj1, "plato-direction-category") or _slipnet_node(
            obj2, "plato-direction-category"
        )
        if dir_cat_node is None:
            return None

        # ``make-concept-mapping`` computes the label from the two descriptors;
        # Petacat's constructor takes it, so it is computed here.  Without it
        # ``right => right`` arrives unlabelled and ``_incompatible_cms``
        # declines on the spot, which is the same trap ``Bond`` and ``Group``
        # already had to step around.
        label = _label_node(dir1, dir2)
        if label is _IDENTITY_SENTINEL:
            label = _slipnet_node(obj1, "plato-identity") or _slipnet_node(
                obj2, "plato-identity"
            )

        direction_cm = ConceptMapping(
            description_type1=dir_cat_node,
            descriptor1=dir1,
            description_type2=dir_cat_node,
            descriptor2=dir2,
            label=label,
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

        Scheme: ``supports-theme-pattern?`` (bridges.ss:239-246, 643-650) — the
        cross-product of the pattern's entries and the bridge's **all**
        concept-mappings minus the whole/single ones, matching a CM's type
        against the entry's dimension and its *label* against the entry's
        relation.

        The comparison is by theme-relation name, not by node name.  Comparing
        ``cm.label.name`` ("plato-identity") to a pattern relation ("identity")
        could never match, so this returned ``False`` unconditionally.
        """
        from server.engine.themes import relation_name_for_label

        filtered_cms = [
            cm for cm in self.get_all_concept_mappings()
            if not _is_whole_or_single_cm(cm)
        ]

        for dim, rel in pattern.items():
            for cm in filtered_cms:
                cm_type_name = getattr(cm.description_type1, "name", "")
                if cm_type_name != dim:
                    continue
                if relation_name_for_label(cm.label) == rel:
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


def _plain_descriptions(obj: Any) -> list[Any]:
    """Descriptions of *obj*, *excluding* a group's bond descriptions.

    Scheme: ``get-descriptions``.  The reference keeps the bond descriptions of
    a group in a separate list precisely so that the things that count an
    object's descriptions do not see them, and everything in this file that
    walks descriptions — concept-mapping construction, theme boosting, theme
    compatibility — passes the plain list.
    """
    return list(getattr(obj, "descriptions", []))


def _relevant_descriptions(obj: Any) -> list[Any]:
    """The descriptions currently able to justify a bridge.

    Scheme: ``get-relevant-descriptions`` (workspace-objects.ss) — those whose
    *description type* is fully active right now.  §"contradictory assumptions"
    (bridges.ss:1069-1082): a bridge is built out of the concepts the program is
    attending to at that instant, so a momentarily-cold Direction-Category
    simply does not participate.
    """
    getter = getattr(obj, "get_relevant_descriptions", None)
    if callable(getter):
        return list(getter())
    return [d for d in _plain_descriptions(obj) if d.is_relevant()]


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
    """Scheme: ``check-descriptions`` (themes.ss:1033-1040).

    ``get-descriptions``, the plain list — a group's bond descriptions are not
    what a bridge's theme compatibility is judged on.
    """
    for d1 in _plain_descriptions(object1):
        for d2 in _plain_descriptions(object2):
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

    Scheme: ``description-possible?`` on a Slipnet category node
    (slipnet.ss:200-201) — "is there a descriptor of this category that would
    apply", which is a question about the object, not about its description
    list.  The dimension node is reached through the object's string, since a
    theme names its dimension by name and holds no Slipnet handle.
    """
    node = _slipnet_node(obj, dimension_name)
    if node is not None:
        return bool(node.description_possible(obj))
    # No Slipnet in reach (unit tests with hand-built objects): fall back to
    # presence, which is what the possibility test would answer for anything
    # already described.
    for d in _plain_descriptions(obj):
        if getattr(d.description_type, "name", "") == dimension_name:
            return True
    return False


def _slipnet_node(obj: Any, name: str) -> Any:
    """The Slipnet node called *name*, reached from a Workspace object."""
    slipnet = _slipnet_of(obj)
    if slipnet is None:
        return None
    return slipnet.nodes.get(name)


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
    """Scheme: ``letter-category-mappable-objects?`` (bridges.ss:1515-1522)::

        (or (and (letter? o1) (letter? o2))
            (and (letter? o1) (group? o2) (tell o2 'all-letter-group?))
            (and (group? o1) (tell o1 'all-letter-group?) (letter? o2))
            (and (group? o1) (group? o2)
                 (related? (tell o1 'get-group-category)
                           (tell o1 'get-group-category))))

    Three things differ from the bond-facet test this used to be.  A letter
    pairs with a group only when the group is an **all-letter** group — every
    constituent a letter, not merely a letter-category facet — so ``[[ab][cd]]``
    is out even though its facet qualifies.  A group pairs with a *letter* on
    the same test, but a group pairs with a **group** unconditionally: the
    Scheme's own last clause compares ``object1``'s group category with itself,
    which is always related.  That is a slip in the reference, not in the
    reading of it, and it is load-bearing — it is what lets two length-facet
    groups carry a letter-category mapping at all.  The reference's file-head
    comment reasons about it explicitly ("object1 and object2 will never be
    Bfacet:length groups because such groups do not have LettCtgy
    descriptions"), so the effect is bounded by what descriptions exist.
    """
    g1, g2 = _is_group(object1), _is_group(object2)
    if not g1 and not g2:
        return True
    if not g1 and g2:
        return _all_letter_group(object2)
    if g1 and not g2:
        return _all_letter_group(object1)
    return True


def _all_letter_group(group: Any) -> bool:
    """Scheme: ``all-letter-group?`` — every constituent is a letter."""
    objects = getattr(group, "objects", None)
    if not objects:
        return False
    return all(not _is_group(o) for o in objects)


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
    descriptions1: list[Any] | None = None,
    descriptions2: list[Any] | None = None,
) -> list[ConceptMapping]:
    """Build the concept-mappings supporting a bridge of *bridge_type*.

    Scheme: ``all-possible-bridge-CMs`` (bridges.ss:1491-1509), which takes the
    two description *lists* as arguments — every caller decides which
    descriptions may justify the bridge it is making.  ``propose-bridge`` passes
    the relevant ones (bridges.ss:1090-1097); ``build-bridge`` passes the bond
    ones to fill the separate bond list (bridges.ss:1387-1390).  The default
    here is the plain list, so a group's bond descriptions never leak into the
    main set the way ``get_all_descriptions`` let them.

    Applies the §3.3.1 horizontal/vertical asymmetry, so a vertical a-i bridge
    gets no ``LetterCategory: a => i`` slippage while the horizontal one does.
    """
    from server.engine.concept_mappings import ConceptMapping

    if descriptions1 is None:
        descriptions1 = _plain_descriptions(object1)
    if descriptions2 is None:
        descriptions2 = _plain_descriptions(object2)

    cms: list[ConceptMapping] = []
    seen: set[tuple[int, int, int]] = set()
    for d1 in descriptions1:
        for d2 in descriptions2:
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


def bridge_cm_descriptions(obj: Any) -> list[Any]:
    """The descriptions that may justify a bridge to *obj*.

    Scheme: the ``if`` inside ``propose-bridge`` (bridges.ss:1092-1097) — the
    relevant descriptions, **except** for a string-spanning group, which
    contributes all of them.  The reference calls that a hack and explains why
    in the comment above it (bridges.ss:1069-1082): without it a momentarily
    cold Direction-Category leaves a spanning bridge with no direction mapping,
    and a flipped re-reading is then judged compatible with the sub-bridges it
    contradicts.
    """
    if _string_spanning_group(obj):
        return _plain_descriptions(obj)
    return _relevant_descriptions(obj)


def possible_bridge_cms(
    bridge_type: str, object1: Any, object2: Any, identity_node: Any = None
) -> list[ConceptMapping]:
    """The mappings a scout weighs before deciding whether to propose at all.

    Scheme: the ``all-possible-bridge-CMs`` call in each scout
    (bridges.ss:924-927, 1022-1025) — over both objects' **relevant**
    descriptions, with no spanning-group exception, since nothing is being
    flipped yet.
    """
    return make_concept_mappings(
        object1,
        object2,
        bridge_type,
        identity_node,
        descriptions1=_relevant_descriptions(object1),
        descriptions2=_relevant_descriptions(object2),
    )


def reverse_direction_orientation(concept_mappings: list[ConceptMapping]) -> bool:
    """Should a spanning-group pair be bridged to the *flipped* second group?

    Scheme: ``reverse-direction-orientation?`` (bridges.ss:1060-1066)::

        (and (ormap-meth cms 'CM-type? plato-direction-category)
             (andmap-meth (filter-meth cms 'reversible-CM-type?) 'opposite-mapping?)
             (not (fully-active? plato-opposite)))

    Three conjuncts, and the third is the interesting one.  The pair is re-read
    backwards only when the concept of oppositeness is *not* saturated: while
    ``plato-opposite`` is fully active the program is happy to see ``>abc>`` and
    ``<cba<`` as opposites and leaves them be, and it is when oppositeness is
    cold that reinterpreting one group as running the other way is the cheaper
    reading.
    """
    reversible = [cm for cm in concept_mappings if cm.reversible_cm_type]
    if not any(
        getattr(cm.description_type1, "name", "") == "plato-direction-category"
        for cm in concept_mappings
    ):
        return False
    if not all(cm.opposite_mapping for cm in reversible):
        return False
    opposite = None
    for cm in concept_mappings:
        opposite = _slipnet_node(cm.object1, "plato-opposite") or _slipnet_node(
            cm.object2, "plato-opposite"
        )
        if opposite is not None:
            break
    if opposite is None:
        return True
    return not opposite.fully_active()


def propose_bridge(
    bridge_type: str,
    object1: Any,
    flip1: bool,
    object2: Any,
    flip2: bool,
    identity_node: Any = None,
    ctx: Any = None,
) -> Bridge:
    """Build a proposed bridge, optionally against a reversed reading of a group.

    Scheme: ``propose-bridge`` (bridges.ss:1085-1146).  When a side is flipped the
    bridge is made to the flipped group — a genuinely different object, with the
    opposite direction and group-category — and the original is remembered so the
    builder can fight it and then swap it out.

    Note the mappings are computed *after* flipping, which is the whole point:
    ``>abc>`` and ``<cba<`` share no Direction concept-mapping, while ``>abc>``
    and ``>cba>`` do.

    Two things happen here besides making the bridge, and both are recruitment.
    Every mapping jolts its description types and descriptors
    (bridges.ss:1109-1110), which is one of the three points in a bridge's life
    where the concepts it rests on are re-warmed.  And a *horizontal* proposal
    between objects of different platonic lengths (bridges.ss:1120-1145)
    activates ``plato-length``, posts a length description-scout into each
    string, and — where one side is a letter and the other a group — activates
    that group's category and posts a group-scout for it into the letter's
    string.  That last is the targeted loop for ``mrrjjj``: the moment ``c``
    faces ``jjj``, the program starts looking for a group around ``c``.

    *ctx* carries the codelet-posting hook; without one the side-effect block
    still activates the concepts but posts nothing, which is what a
    unit-constructed bridge wants.
    """
    obj1 = object1.make_flipped_version() if flip1 else object1
    obj2 = object2.make_flipped_version() if flip2 else object2
    bridge = Bridge(
        obj1,
        obj2,
        bridge_type,
        make_concept_mappings(
            obj1,
            obj2,
            bridge_type,
            identity_node,
            descriptions1=bridge_cm_descriptions(obj1),
            descriptions2=bridge_cm_descriptions(obj2),
        ),
    )
    # ``make_flipped_version`` returns the group itself when there is no direction
    # to reverse, and a bridge to an object that *is* the original is not a flip.
    if flip1 and obj1 is not object1:
        bridge.flipped_group1 = object1
    if flip2 and obj2 is not object2:
        bridge.flipped_group2 = object2

    for cm in bridge.concept_mappings:
        cm.activate_descriptions()

    _propose_bridge_side_effects(bridge_type, object1, object2, ctx)
    return bridge


def _propose_bridge_side_effects(
    bridge_type: str, object1: Any, object2: Any, ctx: Any
) -> None:
    """Scheme: bridges.ss:1120-1145 — the recruitment block of ``propose-bridge``.

    Note the group-scout posting is *nested inside* the differing-lengths test in
    the reference, not a sibling of it: a letter facing a group only recruits a
    group-scout when the two have different platonic lengths, which in practice
    is every letter/multi-letter-group pairing.
    """
    if bridge_type == BRIDGE_VERTICAL:
        return
    if platonic_length(object1) is platonic_length(object2):
        return

    length_node = _slipnet_node(object1, "plato-length") or _slipnet_node(
        object2, "plato-length"
    )
    if length_node is not None and hasattr(length_node, "activate_from_workspace"):
        length_node.activate_from_workspace()

    if ctx is None or length_node is None:
        return
    urgency = ctx.meta.get_urgency("very_high")
    # The reference hands each scout a *scope* as well as a node; Petacat's
    # top-down scouts choose their own scope, so only the node is passed.
    for _ in (object1, object2):
        ctx.coderack.post(
            _top_down_codelet(
                ctx, "top-down-description-scout", urgency, length_node
            )
        )

    for letter, group in ((object1, object2), (object2, object1)):
        if _is_group(letter) or not _is_group(group):
            continue
        category = getattr(group, "group_category", None)
        if category is None:
            continue
        if hasattr(category, "activate_from_workspace"):
            category.activate_from_workspace()
        ctx.coderack.post(
            _top_down_codelet(
                ctx, "top-down-group-scout:category", urgency, category
            )
        )


def _top_down_codelet(ctx: Any, codelet_type: str, urgency: int, node: Any) -> Any:
    from server.engine.coderack import Codelet

    return Codelet(
        codelet_type,
        urgency,
        arguments={"slipnode": node},
        time_stamp=ctx.codelet_count,
    )


def platonic_length(obj: Any) -> Any:
    """The Slipnet number node standing for *obj*'s length.

    Scheme: ``get-platonic-length`` — ``plato-one`` for a letter
    (workspace-objects.ss), ``(number->platonic-number group-length)`` for a
    group (groups.ss:81, 230), where the length is the count of *constituent
    objects*.  ``None`` above five, which is where the Slipnet's numbers stop.
    """
    if not _is_group(obj):
        return _slipnet_node(obj, "plato-one")
    from server.engine.images import number_to_platonic_number

    slipnet = _slipnet_of(obj)
    if slipnet is None:
        return None
    return number_to_platonic_number(len(getattr(obj, "objects", [])), slipnet)


def _slipnet_of(obj: Any) -> Any:
    string = getattr(obj, "string", None)
    workspace = getattr(string, "workspace", None) if string is not None else None
    return getattr(workspace, "slipnet", None) if workspace is not None else None


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



def _letter_category_or_length_slippage(cm: ConceptMapping) -> bool:
    """Scheme: ``letter-category/length-slippage?`` (bridges.ss:1487-1492)."""
    return cm.is_slippage and getattr(cm.description_type1, "name", "") in (
        "plato-letter-category",
        "plato-length",
    )


def _nested_member(container: Any, obj: Any) -> bool:
    """Scheme: ``nested-member?`` — is *obj* inside *container* at any depth?

    A letter contains nothing (workspace-objects.ss), and an object is not a
    member of itself.
    """
    members = getattr(container, "objects", None)
    if not members:
        return False
    for member in members:
        if member is obj or _nested_member(member, obj):
            return True
    return False


def _enclosing_bridge(b1: Bridge, b2: Bridge) -> bool:
    """Scheme: ``enclosing-bridge?`` (bridges.ss:1459-1462) — b1 spans b2 on both ends."""
    return _nested_member(b1.object1, b2.object1) and _nested_member(
        b1.object2, b2.object2
    )


def _incompatible_bridges(b1: Bridge, b2: Bridge, orientation: str) -> bool:
    """Two bridges are incompatible if they share an object or have
    incompatible CM lists.

    Scheme: ``incompatible-horizontal-bridges?`` (bridges.ss:1551-1580) and
    ``incompatible-vertical-bridges?`` (bridges.ss:1641-1669).  The two differ in
    exactly one way and agree in the other, and the raw cross-product this used
    to be had neither.

    **Letter-category and length slippages are exempt, horizontally.**  The
    reference's own example: in ``abc -> abcc`` the spanning bridge carries
    ``Length: 3=>3`` and the ``c -> cc`` bridge carries ``Length: 1=>2``; those
    two labels differ, so the cross-product calls them incompatible and the
    spanning bridge has to break the very sub-bridge that justifies it.  They
    are not in conflict — one describes the string, the other a letter inside
    it.  Vertical bridges need no such exemption, and the reference says why:
    letter-category and length slippages cannot underlie a vertical bridge in
    the first place.

    **A Direction-Category mapping only counts when the bridge encloses the
    other.**  Two same-direction whole-string groups mapped crosswise
    (``[[xy][fg]] -> [[fg][xy]]``) both carry ``DirCtgy: right=>right``, which
    contradicts the ``StrPosCtgy: lmost=(opp)=>rmost`` of the sub-bridges; but a
    sub-bridge's direction mapping has no business speaking about the layout of
    the string above it.  Only a bridge that *contains* the other on both sides
    may bring its direction mapping to the comparison.
    """
    # Shared objects => incompatible
    if b1.object1 is b2.object1 or b1.object2 is b2.object2:
        return True

    b1_cms = b1.concept_mappings
    b2_cms = b2.concept_mappings
    if orientation == ORIENTATION_HORIZONTAL:
        b1_cms = [cm for cm in b1_cms if not _letter_category_or_length_slippage(cm)]
        b2_cms = [cm for cm in b2_cms if not _letter_category_or_length_slippage(cm)]

    if not _enclosing_bridge(b1, b2):
        b1_cms = [cm for cm in b1_cms if not _is_direction_cm(cm)]
    if not _enclosing_bridge(b2, b1):
        b2_cms = [cm for cm in b2_cms if not _is_direction_cm(cm)]

    for cm1 in b1_cms:
        for cm2 in b2_cms:
            if _incompatible_cms(cm1, cm2):
                return True
    return False


def _is_direction_cm(cm: ConceptMapping) -> bool:
    return getattr(cm.description_type1, "name", "") == "plato-direction-category"


def direction_incompatible_bridges(
    orientation: str, group1: Any, group2: Any, direction_cm: ConceptMapping
) -> list[Bridge]:
    """Sub-bridges whose position ordering contradicts a spanning direction mapping.

    Scheme: ``direction-incompatible-bridges`` (bridges.ss:869-892).  Two
    spanning groups mapped with ``DirCtgy: identity`` should have their
    constituents mapped in the *same* left-to-right order; mapped with
    ``opposite``, in reversed order.  Partition the bridges shared by the two
    groups' constituents into mutually-order-compatible sets, keep the largest,
    and everything outside it is incompatible with the spanning reading.

    Without this a spanning bridge could be built straight over a set of
    crossing sub-mappings and leave them all standing — the false-negative half
    of BR-8.
    """
    label_name = getattr(direction_cm.label, "name", "")
    if label_name == "plato-identity":
        pred1, pred2 = (lambda a, b: a < b), (lambda a, b: a > b)
    elif label_name == "plato-opposite":
        pred1, pred2 = (lambda a, b: a > b), (lambda a, b: a < b)
    else:
        return []

    shared = [
        b
        for b in _subobject_bridges(group1, orientation)
        if b in _subobject_bridges(group2, orientation)
    ]
    if not shared:
        return []

    def compatible(b1: Bridge, b2: Bridge) -> bool:
        p1a = getattr(b1.object1, "left_string_pos", 0)
        p1b = getattr(b1.object2, "left_string_pos", 0)
        p2a = getattr(b2.object1, "left_string_pos", 0)
        p2b = getattr(b2.object2, "left_string_pos", 0)
        if p1a < p2a:
            return pred1(p1b, p2b)
        if p1a > p2a:
            return pred2(p1b, p2b)
        return False

    # ``partition`` (utilities.ss:...) is built tail-first: the list is
    # partitioned from the last element back, and each earlier element joins the
    # first block *all* of whose members it satisfies the predicate against,
    # otherwise starting a new block at the end.  ``select-longest-list`` then
    # keeps the first block of maximal length.
    blocks: list[list[Bridge]] = []
    for bridge in reversed(shared):
        for block in blocks:
            if all(compatible(bridge, other) for other in block):
                block.insert(0, bridge)
                break
        else:
            blocks.append([bridge])
    keep = max(blocks, key=len) if blocks else []
    return [b for b in shared if b not in keep]


def _subobject_bridges(group: Any, orientation: str) -> list[Bridge]:
    """Scheme: ``get-subobject-bridges`` — the bridges of a group's constituents."""
    attribute = (
        "horizontal_bridge" if orientation == ORIENTATION_HORIZONTAL else "vertical_bridge"
    )
    result: list[Bridge] = []
    for sub in getattr(group, "objects", []) or []:
        bridge = getattr(sub, attribute, None)
        if bridge is not None:
            result.append(bridge)
    return result


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
