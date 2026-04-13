"""Workspace — the central problem-solving space.

Contains four letter strings arranged in two rows. Holds all perceptual
structures built during a run.

Scheme source: workspace.ss, workspace-strings.ss
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from server.engine.workspace_objects import Letter, WorkspaceObject

if TYPE_CHECKING:
    from server.engine.bonds import Bond
    from server.engine.bridges import Bridge
    from server.engine.concept_mappings import ConceptMapping
    from server.engine.groups import Group
    from server.engine.metadata import MetadataProvider
    from server.engine.rng import RNG
    from server.engine.rules import Rule
    from server.engine.slipnet import Slipnet


class WorkspaceString:
    """A string of letters in the workspace."""

    def __init__(self, text: str, slipnet: Slipnet, string_type: str = "initial") -> None:
        self.text = text
        self.string_type: str = string_type
        self.justify_mode: bool = False
        self.objects: list[WorkspaceObject] = []
        self.bonds: list[Bond] = []
        self.groups: list[Group] = []

        # Create Letter objects
        for i, ch in enumerate(text):
            node_name = f"plato-{ch}"
            letter_node = slipnet.nodes.get(node_name)
            letter = Letter(self, i, letter_node)
            self.objects.append(letter)

    @property
    def length(self) -> int:
        return len(self.text)

    @property
    def letters(self) -> list[Letter]:
        return [o for o in self.objects if isinstance(o, Letter)]

    def get_object_at(self, pos: int) -> WorkspaceObject | None:
        for obj in self.objects:
            if obj.left_string_pos <= pos <= obj.right_string_pos:
                return obj
        return None

    def add_bond(self, bond: Bond) -> None:
        self.bonds.append(bond)
        # Attach to objects
        left = bond.left_object
        right = bond.right_object
        if left.right_string_pos < right.left_string_pos or left is bond.from_object:
            bond.from_object.right_bond = bond
            bond.to_object.left_bond = bond
        else:
            bond.from_object.left_bond = bond
            bond.to_object.right_bond = bond

    def remove_bond(self, bond: Bond) -> None:
        if bond in self.bonds:
            self.bonds.remove(bond)
        if bond.from_object.left_bond is bond:
            bond.from_object.left_bond = None
        if bond.from_object.right_bond is bond:
            bond.from_object.right_bond = None
        if bond.to_object.left_bond is bond:
            bond.to_object.left_bond = None
        if bond.to_object.right_bond is bond:
            bond.to_object.right_bond = None

    def add_group(self, group: Group) -> None:
        self.groups.append(group)
        self.objects.append(group)
        for obj in group.objects:
            obj.enclosing_group = group

    def remove_group(self, group: Group) -> None:
        if group in self.groups:
            self.groups.remove(group)
        if group in self.objects:
            self.objects.remove(group)
        for obj in group.objects:
            if obj.enclosing_group is group:
                obj.enclosing_group = None

    def get_average_intra_string_unhappiness(self) -> float:
        if not self.objects:
            return 0.0
        total = sum(o.intra_string_unhappiness for o in self.objects)
        return total / len(self.objects)

    def get_num_unrelated_objects(self) -> int:
        """Count objects not in any bond or group."""
        return sum(
            1
            for o in self.objects
            if isinstance(o, Letter)
            and o.left_bond is None
            and o.right_bond is None
            and o.enclosing_group is None
        )

    def get_num_ungrouped_objects(self) -> int:
        """Count objects not in any group."""
        return sum(
            1
            for o in self.objects
            if isinstance(o, Letter) and o.enclosing_group is None
        )

    def bond_present(self, bond: Bond) -> bool:
        """Check if an equivalent bond already exists in this string.

        Scheme: workspace-strings.ss:127-128.
        Two bonds are equivalent if they connect the same from/to objects
        with the same bond category and direction.
        """
        return self.get_equivalent_bond(bond) is not None

    def get_equivalent_bond(self, bond: Bond) -> Bond | None:
        """Find an existing bond equivalent to the given one.

        Scheme: workspace-strings.ss:129-137.
        Equivalence: same from_object, same to_object, same bond category,
        same direction.
        """
        for existing in self.bonds:
            if (
                existing.from_object is bond.from_object
                and existing.to_object is bond.to_object
                and existing.bond_category is bond.bond_category
                and existing.direction is bond.direction
            ):
                return existing
        return None

    def group_present(self, group: Group) -> bool:
        """Check if an equivalent group already exists in this string.

        Scheme: workspace-strings.ss:208-209.
        """
        return self.get_equivalent_group(group) is not None

    def get_equivalent_group(self, group: Group) -> Group | None:
        """Find an existing group equivalent to the given one.

        Scheme: workspace-strings.ss:227-240.
        Equivalence: same leftmost position, same group category,
        same direction, and same length (number of objects).
        """
        from server.engine.groups import Group as GroupClass
        for existing in self.groups:
            if not isinstance(existing, GroupClass):
                continue
            if existing is group:
                return existing
            if (
                existing.left_string_pos == group.left_string_pos
                and existing.right_string_pos == group.right_string_pos
                and existing.group_category is group.group_category
                and existing.direction is group.direction
                and len(existing.objects) == len(group.objects)
            ):
                return existing
        return None

    def get_spanning_group(self) -> Group | None:
        """Get the group that spans the whole string, if any.

        Scheme: workspace-strings.ss:414-415.
        """
        from server.engine.groups import Group as GroupClass
        for g in self.groups:
            if isinstance(g, GroupClass) and g.spans_whole_string():
                return g
        return None

    def spanning_group_exists(self) -> bool:
        """Check if a spanning group exists in this string.

        Scheme: workspace-strings.ss:412-413.
        """
        return self.get_spanning_group() is not None

    def get_bond_category_relevance(self, bond_category: Any) -> float:
        """How relevant is a bond category to this string?

        Scheme: workspace-strings.ss:377-378.
        Fraction of non-spanning objects whose right_bond has the given
        bond category, expressed as a percentage (0-100).
        """
        return self._get_relevance("bond_category", bond_category)

    def get_direction_relevance(self, direction: Any) -> float:
        """How relevant is a direction to this string?

        Scheme: workspace-strings.ss:379-380.
        Fraction of non-spanning objects whose right_bond has the given
        direction, expressed as a percentage (0-100).
        """
        return self._get_relevance("direction", direction)

    def _get_relevance(self, attr_name: str, category: Any) -> float:
        """Generic relevance computation.

        Scheme: workspace-strings.ss:360-376.
        """
        non_spanning = [o for o in self.objects if not o.spans_whole_string()]
        if len(non_spanning) <= 1:
            return 0.0
        count = 0
        for obj in non_spanning:
            rb = obj.right_bond
            if rb is not None and getattr(rb, attr_name, None) is category:
                count += 1
        return round(100.0 * count / (len(non_spanning) - 1))

    def choose_object(self, weight_key: str, rng: RNG) -> WorkspaceObject | None:
        """Choose an object weighted by a salience/importance measure."""
        if not self.objects:
            return None
        weights = [
            max(0.1, getattr(o, weight_key, 1.0))
            if isinstance(getattr(o, weight_key, None), (int, float))
            else o.salience.get(weight_key, 1.0)
            for o in self.objects
        ]
        return rng.weighted_pick(self.objects, weights)

    def update_object_values(self) -> None:
        """Recompute importance, unhappiness, salience for all objects.

        Scheme update order (workspace-objects.ss:594-601,
        workspace-strings.ss:322-338):
          1. update_raw_importance
          2. update_relative_importance
          3. update_intra_string_unhappiness
          4. update_inter_string_unhappiness
          5. update_average_unhappiness
          6. update_intra_string_salience
          7. update_inter_string_salience
          8. update_average_salience
          9. update_description_strengths
        """
        # 1. Raw importances
        for obj in self.objects:
            obj.update_importance()

        # 2. Relative importances
        total_raw = sum(o.raw_importance for o in self.objects) or 1.0
        for obj in self.objects:
            obj.relative_importance = round(100.0 * obj.raw_importance / total_raw)

        # 3-9. Full per-object update cycle
        for obj in self.objects:
            obj.update_object_values()

    def __repr__(self) -> str:
        return f"WorkspaceString('{self.text}', {len(self.bonds)} bonds, {len(self.groups)} groups)"


class Workspace:
    """The central workspace containing four strings."""

    def __init__(
        self,
        initial: str,
        modified: str,
        target: str,
        answer: str | None,
        slipnet: Slipnet,
    ) -> None:
        self.initial_string = WorkspaceString(initial, slipnet, string_type="initial")
        self.modified_string = WorkspaceString(modified, slipnet, string_type="modified")
        self.target_string = WorkspaceString(target, slipnet, string_type="target")
        self.answer_string = (
            WorkspaceString(answer, slipnet, string_type="answer") if answer else None
        )

        self.top_bridges: list[Bridge] = []
        self.bottom_bridges: list[Bridge] = []
        self.vertical_bridges: list[Bridge] = []

        self.top_rules: list[Rule] = []
        self.bottom_rules: list[Rule] = []
        self.clamped_rules: list[Rule] = []

        self.slipnet = slipnet

    @property
    def all_strings(self) -> list[WorkspaceString]:
        strings = [self.initial_string, self.modified_string, self.target_string]
        if self.answer_string:
            strings.append(self.answer_string)
        return strings

    @property
    def all_objects(self) -> list[WorkspaceObject]:
        objects = []
        for s in self.all_strings:
            objects.extend(s.objects)
        return objects

    @property
    def all_structures(self) -> list[Any]:
        structures: list[Any] = []
        for s in self.all_strings:
            structures.extend(s.bonds)
            structures.extend(s.groups)
        structures.extend(self.top_bridges)
        structures.extend(self.bottom_bridges)
        structures.extend(self.vertical_bridges)
        structures.extend(self.top_rules)
        structures.extend(self.bottom_rules)
        return structures

    def add_bridge(self, bridge: Bridge) -> None:
        from server.engine.bridges import BRIDGE_TOP, BRIDGE_BOTTOM
        if bridge.bridge_type == BRIDGE_TOP:
            self.top_bridges.append(bridge)
        elif bridge.bridge_type == BRIDGE_BOTTOM:
            self.bottom_bridges.append(bridge)
        else:
            self.vertical_bridges.append(bridge)
        # Set bridge references on objects
        if bridge.is_horizontal:
            bridge.object1.horizontal_bridge = bridge
            bridge.object2.horizontal_bridge = bridge
        else:
            bridge.object1.vertical_bridge = bridge
            bridge.object2.vertical_bridge = bridge

    def remove_bridge(self, bridge: Bridge) -> None:
        from server.engine.bridges import BRIDGE_TOP, BRIDGE_BOTTOM
        if bridge.bridge_type == BRIDGE_TOP:
            self.top_bridges = [b for b in self.top_bridges if b is not bridge]
        elif bridge.bridge_type == BRIDGE_BOTTOM:
            self.bottom_bridges = [b for b in self.bottom_bridges if b is not bridge]
        else:
            self.vertical_bridges = [b for b in self.vertical_bridges if b is not bridge]
        if bridge.object1.horizontal_bridge is bridge:
            bridge.object1.horizontal_bridge = None
        if bridge.object1.vertical_bridge is bridge:
            bridge.object1.vertical_bridge = None
        if bridge.object2.horizontal_bridge is bridge:
            bridge.object2.horizontal_bridge = None
        if bridge.object2.vertical_bridge is bridge:
            bridge.object2.vertical_bridge = None

    def add_rule(self, rule: Rule) -> None:
        if self.rule_present(rule):
            return
        if rule.is_top_rule:
            self.top_rules.append(rule)
        else:
            self.bottom_rules.append(rule)

    def remove_rule(self, rule: Rule) -> None:
        if rule.is_top_rule:
            self.top_rules = [r for r in self.top_rules if r is not rule]
        else:
            self.bottom_rules = [r for r in self.bottom_rules if r is not rule]

    def get_supported_rules(self, rule_type_top: bool = True) -> list[Rule]:
        rules = self.top_rules if rule_type_top else self.bottom_rules
        return [r for r in rules if r.is_built and r.supporting_bridges]

    def get_average_unhappiness(self) -> float:
        """Workspace-level average unhappiness, weighted by relative importance.

        Scheme: workspace.ss:581-585.
        When all importances are 0 (early in a run, before descriptions are
        activated), falls back to an unweighted average so temperature
        correctly reflects the lack of structure.
        """
        objects = self.all_objects
        if not objects:
            return 100.0
        total_weight = sum(o.relative_importance for o in objects)
        if total_weight > 0:
            weighted_sum = sum(
                o.intra_string_unhappiness * o.relative_importance for o in objects
            )
            return round(weighted_sum / total_weight)
        else:
            # No importance assigned yet — use unweighted average
            return round(sum(o.intra_string_unhappiness for o in objects) / len(objects))

    def get_mapping_strength(self, bridge_type_name: str) -> float:
        """Mapping strength for bridges of a given type.

        Scheme: workspace.ss:586-624.
        raw_strength = 100 - average_inter_string_unhappiness
        Then adjusted based on spanning-bridge / spanning-group-possible / maximal-mapping:
        - spanning bridge exists: raw_strength (full credit)
        - spanning groups possible on both strings: raw_strength * 0.5
        - maximal mapping: 100 * tanh(raw_strength / 40)
        - else: raw_strength
        """
        bridges = self.get_bridges(bridge_type_name)
        built = [b for b in bridges if b.is_built]
        if not built:
            return 0.0

        # Compute average inter-string unhappiness for relevant objects
        string1, string2 = self._get_bridge_type_strings(bridge_type_name)
        objects = list(string1.objects)
        if string2 is not None:
            objects.extend(string2.objects)

        if not objects:
            return 0.0

        orientation = "horizontal" if bridge_type_name in ("top", "bottom") else "vertical"
        total_weight = sum(o.relative_importance for o in objects)
        if total_weight > 0:
            avg_unhappiness = sum(
                o.inter_string_unhappiness.get(orientation, 100.0) * o.relative_importance
                for o in objects
            ) / total_weight
        else:
            avg_unhappiness = sum(
                o.inter_string_unhappiness.get(orientation, 100.0)
                for o in objects
            ) / len(objects)

        raw_strength = 100.0 - avg_unhappiness

        if self.spanning_bridge_exists(bridge_type_name):
            return round(raw_strength)

        if (
            string2 is not None
            and self._spanning_group_possible(string1)
            and self._spanning_group_possible(string2)
        ):
            return round(0.5 * raw_strength)

        if self.maximal_mapping(bridge_type_name):
            return round(100.0 * math.tanh(raw_strength / 40.0))

        return round(raw_strength)

    def get_num_unmapped_objects(self, bridge_type: str = "vertical") -> int:
        """Count objects that don't have a bridge of the given type.

        Scheme: workspace.ss:629-630, 708-716 (unmapped?).
        Only counts objects in the strings relevant to the bridge type.
        """
        string1, string2 = self._get_bridge_type_strings(bridge_type)
        count = 0
        strings = [string1]
        if string2 is not None:
            strings.append(string2)
        for s in strings:
            for obj in s.objects:
                if bridge_type == "vertical":
                    if obj.vertical_bridge is None:
                        count += 1
                else:
                    if obj.horizontal_bridge is None:
                        count += 1
        return count

    def get_average_intra_string_unhappiness(self) -> float:
        """Average intra-string unhappiness across all strings."""
        strings = self.all_strings
        if not strings:
            return 100.0
        return sum(s.get_average_intra_string_unhappiness() for s in strings) / len(strings)

    def has_supported_rule(self) -> bool:
        return len(self.get_supported_rules(True)) > 0

    def update_all_object_values(self) -> None:
        for s in self.all_strings:
            s.update_object_values()

    def update_all_structure_strengths(self) -> None:
        for structure in self.all_structures:
            if hasattr(structure, "update_strength"):
                structure.update_strength()

    def choose_object(self, weight_key: str, rng: RNG) -> WorkspaceObject | None:
        """Choose an object from any string, weighted by salience."""
        all_objs = self.all_objects
        if not all_objs:
            return None
        weights = []
        for o in all_objs:
            if isinstance(getattr(o, weight_key, None), (int, float)):
                weights.append(max(0.1, getattr(o, weight_key)))
            elif isinstance(o.salience, dict) and weight_key in o.salience:
                weights.append(max(0.1, o.salience[weight_key]))
            else:
                weights.append(1.0)
        return rng.weighted_pick(all_objs, weights)

    # ------------------------------------------------------------------
    # Bridge queries
    # ------------------------------------------------------------------

    def get_bridges(self, bridge_type: str) -> list[Bridge]:
        """Return bridges of the given type.

        Scheme: workspace.ss:148-152.
        """
        type_map = {
            "top": self.top_bridges,
            "bottom": self.bottom_bridges,
            "vertical": self.vertical_bridges,
        }
        return type_map.get(bridge_type, [])

    def bridge_present(self, bridge: Bridge) -> bool:
        """Check if an equivalent bridge already exists.

        Scheme: workspace.ss:266-267.
        """
        return self.get_equivalent_bridge(bridge) is not None

    def get_equivalent_bridge(self, bridge: Bridge) -> Bridge | None:
        """Find an existing bridge equivalent to the given one.

        Scheme: workspace.ss:268-301.
        Equivalence: same bridge type, and connects equivalent objects
        in the same orientation.
        """
        bridge_list = self.get_bridges(bridge.bridge_type)

        # If bridge is already in the list, return it directly
        if bridge in bridge_list:
            return bridge

        # Look for a built bridge between equivalent objects
        for existing in bridge_list:
            if (
                existing.object1 is bridge.object1
                and existing.object2 is bridge.object2
            ):
                return existing
            # Also check if bridge objects have equivalents
            # (e.g. same position letters in translated strings)
            if (
                existing.object1.left_string_pos == bridge.object1.left_string_pos
                and existing.object1.right_string_pos == bridge.object1.right_string_pos
                and existing.object1.string is bridge.object1.string
                and existing.object2.left_string_pos == bridge.object2.left_string_pos
                and existing.object2.right_string_pos == bridge.object2.right_string_pos
                and existing.object2.string is bridge.object2.string
            ):
                return existing
        return None

    def spanning_bridge_exists(self, bridge_type: str) -> bool:
        """Check if a bridge between spanning objects exists.

        Scheme: workspace.ss:314-315.
        A spanning bridge connects two objects that each span their
        whole string (either spanning groups or single-letter strings).
        """
        for b in self.get_bridges(bridge_type):
            if self._bridge_is_spanning(b):
                return True
        return False

    def get_spanning_bridge(self, bridge_type: str) -> Bridge | None:
        """Get the spanning bridge of the given type, if any.

        Scheme: workspace.ss:316-317.
        """
        for b in self.get_bridges(bridge_type):
            if self._bridge_is_spanning(b):
                return b
        return None

    def get_all_slippages(self, bridge_type: str) -> list[ConceptMapping]:
        """Collect all slippages from bridges of the given type.

        Scheme: workspace.ss:302-304.
        Slippages are concept mappings where descriptor1 != descriptor2,
        plus their symmetric counterparts.
        """
        result: list[ConceptMapping] = []
        for bridge in self.get_bridges(bridge_type):
            for cm in bridge.concept_mappings:
                if cm.is_slippage:
                    result.append(cm)
                    # Add symmetric mapping
                    sym = cm.symmetric_mapping()
                    if sym is not cm:
                        result.append(sym)
        return result

    def get_all_non_symmetric_slippages(self, bridge_type: str) -> list[ConceptMapping]:
        """Non-symmetric slippages only from bridges of the given type.

        Scheme: workspace.ss:305-308.
        """
        result: list[ConceptMapping] = []
        for bridge in self.get_bridges(bridge_type):
            for cm in bridge.concept_mappings:
                if cm.is_slippage:
                    result.append(cm)
        return result

    def get_possible_bridge_objects(self, bridge_type: str) -> list[WorkspaceObject]:
        """Objects that could participate in bridges of the given type.

        Scheme: workspace.ss:173-178.
        Returns all objects from the two strings involved in this bridge type.
        """
        string1, string2 = self._get_bridge_type_strings(bridge_type)
        objects = list(string1.objects)
        if string2 is not None:
            objects.extend(string2.objects)
        return objects

    def maximal_mapping(self, bridge_type: str) -> bool:
        """Check if bridges of this type cover all letters in both strings.

        Scheme: workspace.ss:529-540.
        True if the union of letters covered by all bridges equals
        the union of all letters in both strings.
        """
        string1, string2 = self._get_bridge_type_strings(bridge_type)
        if string2 is None:
            return False

        # Collect all letters from both strings
        all_letters: set[int] = set()
        for ltr in string1.letters:
            all_letters.add(id(ltr))
        for ltr in string2.letters:
            all_letters.add(id(ltr))

        # Collect covered letters from all bridges of this type
        covered: set[int] = set()
        for bridge in self.get_bridges(bridge_type):
            # Letters covered by object1
            obj1 = bridge.object1
            if isinstance(obj1, Letter):
                covered.add(id(obj1))
            elif hasattr(obj1, "objects"):
                for sub in self._get_nested_letters(obj1):
                    covered.add(id(sub))
            # Letters covered by object2
            obj2 = bridge.object2
            if isinstance(obj2, Letter):
                covered.add(id(obj2))
            elif hasattr(obj2, "objects"):
                for sub in self._get_nested_letters(obj2):
                    covered.add(id(sub))

        return all_letters == covered

    # ------------------------------------------------------------------
    # Rule management
    # ------------------------------------------------------------------

    def rule_present(self, rule: Rule) -> bool:
        """Check if an equivalent rule already exists.

        Scheme: workspace.ss:473-474.
        """
        return self.get_equivalent_rule(rule) is not None

    def get_equivalent_rule(self, rule: Rule) -> Rule | None:
        """Find existing equivalent rule.

        Scheme: workspace.ss:475-478.
        Two rules are equivalent if they have the same rule type and
        equal clause structures (same clause types, same number of
        changes, same dimensions/descriptors/relations in changes).
        """
        rules = self.top_rules if rule.is_top_rule else self.bottom_rules
        for existing in rules:
            if existing is rule:
                return existing
            if self._rules_equal(existing, rule):
                return existing
        return None

    def clamp_rule(self, rule: Rule) -> None:
        """Add rule to clamped rules list.

        Scheme: workspace.ss:412-415.
        """
        self.clamped_rules.append(rule)

    def unclamp_rule(self, rule: Rule) -> None:
        """Remove rule from clamped rules list.

        Scheme: workspace.ss:417-419.
        """
        self.clamped_rules = [r for r in self.clamped_rules if r is not rule]

    def unclamp_rules(self) -> None:
        """Unclamp all rules.

        Scheme: workspace.ss:422-429.
        """
        self.clamped_rules = []

    def get_clamped_rules(self) -> list[Rule]:
        """Return the clamped rules list.

        Scheme: workspace.ss:411.
        """
        return self.clamped_rules

    def check_if_rules_possible(self) -> dict[str, bool]:
        """Determine which rule types can currently be formed.

        Scheme: workspace.ss:454-472.
        A rule is possible for a bridge type if all letters in both
        strings are covered by rule-describable bridges. Returns a
        dict with 'top' and 'bottom' keys.
        """
        result = {"top": False, "bottom": False}

        # Top rule: check if all letters in initial + modified are covered
        # by rule-describable top bridges
        top_describable = [b for b in self.top_bridges if self._rule_describable_bridge(b)]
        if top_describable:
            covered: set[int] = set()
            for b in top_describable:
                for ltr in self._get_bridge_covered_letters(b):
                    covered.add(id(ltr))
            all_top_letters = set(
                id(ltr)
                for ltr in self.initial_string.letters + self.modified_string.letters
            )
            result["top"] = all_top_letters.issubset(covered)

        # Bottom rule: only possible in justify mode (answer_string exists)
        if self.answer_string is not None:
            bottom_describable = [
                b for b in self.bottom_bridges if self._rule_describable_bridge(b)
            ]
            if bottom_describable:
                covered_b: set[int] = set()
                for b in bottom_describable:
                    for ltr in self._get_bridge_covered_letters(b):
                        covered_b.add(id(ltr))
                all_bottom_letters = set(
                    id(ltr)
                    for ltr in self.target_string.letters
                    + (self.answer_string.letters if self.answer_string else [])
                )
                result["bottom"] = all_bottom_letters.issubset(covered_b)

        return result

    # ------------------------------------------------------------------
    # Workspace activity
    # ------------------------------------------------------------------

    EXPIRATION_PERIOD = 500
    NUM_YOUNGEST_STRUCTURES = 3

    def get_activity(self, codelet_count: int = 0) -> float:
        """Measure of how much structure has been built recently.

        Scheme: workspace.ss:179-182.
        Based on the average age of the youngest structures.
        100 = very active (structures built recently), 0 = inactive.
        """
        avg_age = self._get_youngest_structures_average_age(codelet_count)
        return round(100.0 - 100.0 * min(1.0, avg_age / self.EXPIRATION_PERIOD))

    def _get_youngest_structures_average_age(self, codelet_count: int) -> float:
        """Average age of the N youngest structures.

        Scheme: workspace.ss:183-192.
        """
        structures = self.all_structures
        if not structures:
            return 0.0

        # Sort by age ascending (youngest first)
        ages = sorted(
            max(0, codelet_count - getattr(s, "time_stamp", 0))
            for s in structures
        )
        n = min(len(ages), self.NUM_YOUNGEST_STRUCTURES)
        youngest_ages = ages[:n]
        if not youngest_ages:
            return 0.0
        return sum(youngest_ages) / len(youngest_ages)

    # ------------------------------------------------------------------
    # Object counts (per string)
    # ------------------------------------------------------------------

    def get_num_unrelated_objects(self, string: WorkspaceString) -> int:
        """Count objects without bonds in the given string.

        Scheme: workspace.ss:625-626, 692-698 (unrelated?).
        An object is unrelated if it is not in a group AND has insufficient
        incident bonds (0 for edge objects, < 2 for middle objects).
        """
        count = 0
        for obj in string.objects:
            if obj.enclosing_group is not None:
                continue
            # Check if object spans whole string (skip if so)
            from server.engine.groups import Group as GroupClass
            if isinstance(obj, GroupClass) and obj.spans_whole_string():
                continue
            num_bonds = 0
            if obj.left_bond is not None:
                num_bonds += 1
            if obj.right_bond is not None:
                num_bonds += 1
            is_edge = (
                obj.left_string_pos == 0
                or obj.right_string_pos == string.length - 1
            )
            if is_edge:
                if num_bonds == 0:
                    count += 1
            else:
                if num_bonds < 2:
                    count += 1
        return count

    def get_num_ungrouped_objects(self, string: WorkspaceString) -> int:
        """Count objects not in any group in the given string.

        Scheme: workspace.ss:627-628, 700-704 (ungrouped?).
        An object is ungrouped if it doesn't span the whole string
        and has no enclosing group.
        """
        from server.engine.groups import Group as GroupClass
        count = 0
        for obj in string.objects:
            if isinstance(obj, GroupClass) and obj.spans_whole_string():
                continue
            if obj.enclosing_group is None:
                count += 1
        return count

    def get_num_unmapped_objects_in_string(
        self, string: WorkspaceString, bridge_type: str
    ) -> int:
        """Count objects without bridges of the given type in a specific string.

        Scheme: workspace.ss:629-630, 708-716 (unmapped?).
        """
        count = 0
        orientation = "horizontal" if bridge_type in ("top", "bottom") else "vertical"
        for obj in string.objects:
            if orientation == "vertical":
                if obj.vertical_bridge is None:
                    count += 1
            else:
                if obj.horizontal_bridge is None:
                    count += 1
        return count

    # ------------------------------------------------------------------
    # String partner lookups
    # ------------------------------------------------------------------

    def get_other_string(
        self, string: WorkspaceString, bridge_type: str
    ) -> WorkspaceString | None:
        """Given a string and bridge type, return the partner string.

        Scheme: workspace.ss:161-172.
        """
        if string is self.initial_string:
            if bridge_type in ("top", "horizontal"):
                return self.modified_string
            else:  # vertical
                return self.target_string
        elif string is self.modified_string:
            return self.initial_string
        elif string is self.target_string:
            if bridge_type in ("bottom", "horizontal"):
                return self.answer_string
            else:  # vertical
                return self.initial_string
        elif string is self.answer_string:
            return self.target_string
        return None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_bridge_type_strings(
        self, bridge_type: str
    ) -> tuple[WorkspaceString, WorkspaceString | None]:
        """Return the pair of strings for a given bridge type."""
        if bridge_type == "top":
            return self.initial_string, self.modified_string
        elif bridge_type == "bottom":
            return self.target_string, self.answer_string
        else:  # vertical
            return self.initial_string, self.target_string

    def _bridge_is_spanning(self, bridge: Bridge) -> bool:
        """Check if a bridge connects two spanning objects.

        Scheme: workspace-objects.ss:669-672 (both-spanning-objects?).
        An object spans its whole string if it covers all positions.
        """
        return self._object_spans_string(
            bridge.object1
        ) and self._object_spans_string(bridge.object2)

    @staticmethod
    def _object_spans_string(obj: WorkspaceObject) -> bool:
        """Check if an object spans its entire string."""
        from server.engine.groups import Group as GroupClass
        if isinstance(obj, GroupClass):
            return obj.spans_whole_string()
        # A letter spans the string only if the string has exactly one letter
        if obj.string is None:
            return False
        return len(obj.string.letters) == 1

    def _spanning_group_possible(self, string: WorkspaceString) -> bool:
        """Check if a spanning group could potentially be formed.

        Scheme: workspace.ss:664-680 (spanning-group-possible?).
        True if a spanning group already exists, or if all adjacent
        top-level objects share some bond relation along some facet.
        """
        if string.spanning_group_exists():
            return True

        # Get top-level (non-enclosed) objects sorted by position
        top_level = sorted(
            [o for o in string.objects if o.enclosing_group is None],
            key=lambda o: o.left_string_pos,
        )
        if len(top_level) < 2:
            return True  # Single object trivially can form spanning group

        # Check if all adjacent pairs have a consistent bond relation
        for i in range(len(top_level) - 1):
            obj1 = top_level[i]
            obj2 = top_level[i + 1]
            # Check right bond of obj1 or left bond of obj2
            if obj1.right_bond is None and obj2.left_bond is None:
                return False

        return True

    def _get_nested_letters(self, obj: WorkspaceObject) -> list[Letter]:
        """Get all letters nested within an object (recursively for groups)."""
        if isinstance(obj, Letter):
            return [obj]
        result: list[Letter] = []
        for sub in getattr(obj, "objects", []):
            result.extend(self._get_nested_letters(sub))
        return result

    def _get_bridge_covered_letters(self, bridge: Bridge) -> list[Letter]:
        """Get all letters covered by a bridge's two objects."""
        letters: list[Letter] = []
        letters.extend(self._get_nested_letters(bridge.object1))
        letters.extend(self._get_nested_letters(bridge.object2))
        return letters

    def _rule_describable_bridge(self, bridge: Bridge) -> bool:
        """Check if a bridge can be used to describe a rule change.

        Scheme: rules.ss:528-541.
        Conditions based on object types (letter vs group) and bond facets.
        """
        from server.engine.groups import Group as GroupClass
        obj1 = bridge.object1
        obj2 = bridge.object2
        obj1_is_letter = isinstance(obj1, Letter)
        obj2_is_letter = isinstance(obj2, Letter)
        obj1_is_group = isinstance(obj1, GroupClass)
        obj2_is_group = isinstance(obj2, GroupClass)

        # letter -> letter: always ok
        if obj1_is_letter and obj2_is_letter:
            return True
        # letter -> group: only sameness group based on letter-category
        if obj1_is_letter and obj2_is_group:
            bf = getattr(obj2, "bond_facet", None)
            gc = getattr(obj2, "group_category", None)
            bf_name = getattr(bf, "name", "") if bf else ""
            gc_name = getattr(gc, "name", "") if gc else ""
            return bf_name == "plato-letter-category" and gc_name == "plato-samegrp"
        # group -> letter: ok if group based on letter-category
        if obj1_is_group and obj2_is_letter:
            bf = getattr(obj1, "bond_facet", None)
            bf_name = getattr(bf, "name", "") if bf else ""
            return bf_name == "plato-letter-category"
        # group -> group: both must share same bond-facet
        if obj1_is_group and obj2_is_group:
            bf1 = getattr(obj1, "bond_facet", None)
            bf2 = getattr(obj2, "bond_facet", None)
            return bf1 is bf2 and bf1 is not None

        return False

    @staticmethod
    def _rules_equal(rule1: Rule, rule2: Rule) -> bool:
        """Check if two rules have equivalent clause structures.

        Scheme: rules.ss:364-368 (rules-equal?).
        """
        if rule1.rule_type != rule2.rule_type:
            return False
        c1 = rule1.clauses
        c2 = rule2.clauses
        if len(c1) != len(c2):
            return False
        for clause1, clause2 in zip(c1, c2):
            if clause1.clause_type != clause2.clause_type:
                return False
            if len(clause1.changes) != len(clause2.changes):
                return False
            for ch1, ch2 in zip(clause1.changes, clause2.changes):
                if ch1.dimension is not ch2.dimension:
                    return False
                if ch1.from_descriptor is not ch2.from_descriptor:
                    return False
                if ch1.to_descriptor is not ch2.to_descriptor:
                    return False
                if ch1.relation is not ch2.relation:
                    return False
        return True

    def __repr__(self) -> str:
        ans = f"'{self.answer_string.text}'" if self.answer_string else "?"
        return (
            f"Workspace('{self.initial_string.text}' -> '{self.modified_string.text}'; "
            f"'{self.target_string.text}' -> {ans})"
        )
