"""Slipnet — semantic network of concept nodes.

The Slipnet is a graph of SlipnetNode objects connected by SlipnetLink objects.
Built at startup from the MetadataProvider. The graph topology, conceptual depths,
link lengths, and link types are all DB-driven. The activation spreading
*algorithm* is in code; the *data* it operates on is not.

Scheme source: slipnet.ss
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from server.engine.metadata import MetadataProvider, SlipnodeSpec, SlipnetLinkSpec
    from server.engine.rng import RNG


class SlipnetNode:
    """A concept node in the Slipnet."""

    __slots__ = (
        "name",
        "short_name",
        "conceptual_depth",
        "activation",
        "activation_buffer",
        "frozen",
        "clamp_cycles_remaining",
        "category_links",
        "instance_links",
        "property_links",
        "lateral_links",
        "lateral_sliplinks",
        "incoming_links",
        "intrinsic_link_length",
        "_rate_of_decay",
        "descriptor_predicate",
    )

    def __init__(self, name: str, short_name: str, conceptual_depth: int) -> None:
        self.name = name
        self.short_name = short_name
        self.conceptual_depth = conceptual_depth
        self.activation: float = 0.0
        self.activation_buffer: float = 0.0
        self.frozen: bool = False
        self.clamp_cycles_remaining: int = 0
        self.category_links: list[SlipnetLink] = []
        self.instance_links: list[SlipnetLink] = []
        self.property_links: list[SlipnetLink] = []
        self.lateral_links: list[SlipnetLink] = []
        self.lateral_sliplinks: list[SlipnetLink] = []
        self.incoming_links: list[SlipnetLink] = []
        self.intrinsic_link_length: int | None = None
        self._rate_of_decay: float = 0.0
        self.descriptor_predicate: Callable[..., bool] | None = None

    def compute_rate_of_decay(self, update_cycle_length: int) -> None:
        """Scheme: slipnet.ss:72-73."""
        self._rate_of_decay = 1.0 - (self.conceptual_depth / 100.0) ** (
            update_cycle_length / 15.0
        )

    def fully_active(self, threshold: int = 50) -> bool:
        return self.activation >= threshold

    def decay(self) -> None:
        """Reduce activation by rate_of_decay. Frozen nodes don't decay."""
        if self.frozen:
            return
        self.activation_buffer -= self._rate_of_decay * self.activation

    def spread_activation_to_neighbors(self, update_cycle_length: int) -> None:
        """Spread activation to linked nodes.

        Scheme: slipnet.ss:183-185.
        amount = round((ucl/15) * (association/100) * activation)
        """
        if self.activation <= 0:
            return
        scale = update_cycle_length / 15.0
        for link in self.outgoing_links:
            assoc = link.intrinsic_degree_of_association()
            amount = round(scale * (assoc / 100.0) * self.activation)
            if amount > 0:
                link.to_node.activation_buffer += amount

    @property
    def outgoing_links(self) -> list[SlipnetLink]:
        return (
            self.category_links
            + self.instance_links
            + self.property_links
            + self.lateral_links
            + self.lateral_sliplinks
        )

    def shrunk_link_length(self) -> int | None:
        """40% of intrinsic link length. Scheme: slipnet.ss:191."""
        if self.intrinsic_link_length is None:
            return None
        return round(0.4 * self.intrinsic_link_length)

    def clamp(self, cycles: int) -> None:
        self.frozen = True
        self.clamp_cycles_remaining = cycles
        self.activation = 100.0

    def unclamp(self) -> None:
        self.frozen = False
        self.clamp_cycles_remaining = 0

    def tick_clamp(self) -> None:
        """Decrement clamp counter and unclamp if expired."""
        if self.frozen and self.clamp_cycles_remaining > 0:
            self.clamp_cycles_remaining -= 1
            if self.clamp_cycles_remaining == 0:
                self.unclamp()

    def probabilistic_jump_to_full(self, rng: RNG) -> None:
        """Stochastic jump to full activation when above threshold.

        Scheme: slipnet.ss:388-389.
        probability = (activation / 100) ^ 3
        """
        if self.activation > 0:
            prob = (self.activation / 100.0) ** 3
            if rng.prob(prob):
                self.activation = 100.0

    @property
    def category(self) -> SlipnetNode | None:
        """Return the category node (to_node of the first category link), or None.

        Scheme: slipnet.ss:95-98.
        """
        if self.category_links:
            return self.category_links[0].to_node
        return None

    def get_related_node(self, relation: SlipnetNode) -> SlipnetNode | None:
        """Find the neighbor node connected via a link labeled with *relation*.

        Scheme: slipnet.ss:114-129.
        - If *relation* is the identity node, return self.
        - Otherwise, walk outgoing links for ones whose label_node is *relation*.
        - If exactly one match, return it.
        - If multiple matches, prefer the one sharing self's category.
        - If none, return None.
        """
        # Identity relation -> return self
        if relation.name == "plato-identity":
            return self

        related_nodes: list[SlipnetNode] = []
        for link in self.outgoing_links:
            if link.label_node is relation:
                related_nodes.append(link.to_node)

        if not related_nodes:
            return None
        if len(related_nodes) == 1:
            return related_nodes[0]

        # Multiple matches: pick the one in the same category as self
        my_cat = self.category
        for node in related_nodes:
            if node.category is my_cat:
                return node

        # Fallback: return first
        return related_nodes[0]

    def possible_descriptor(self, obj: object) -> bool:
        """Check if this node can describe *obj*.

        Scheme: slipnet.ss:198-199 (possible-descriptor?).
        Uses the stored descriptor_predicate callable (set during Slipnet
        initialization). Returns False if no predicate is defined.
        """
        if self.descriptor_predicate is None:
            return False
        return self.descriptor_predicate(obj)

    def get_possible_descriptors(self, obj: object) -> list[SlipnetNode]:
        """Return instance nodes that can describe *obj*.

        Scheme: slipnet.ss:204-206. Walk instance links, collect to_nodes whose
        possible_descriptor returns True for *obj*.
        """
        return [
            link.to_node
            for link in self.instance_links
            if link.to_node.possible_descriptor(obj)
        ]

    def apply_slippages(
        self,
        slippages: list[object],
        rng: RNG | None = None,
    ) -> SlipnetNode:
        """Apply a list of slippages (ConceptMappings) to this node.

        Returns the slipped version of this node.  Each slippage has
        ``descriptor1``, ``descriptor2``, ``label``, and ``description_type1``
        (the CM-type in Scheme terminology).

        The algorithm (Scheme: slipnet.ss:257-277):
        1. Walk the slippages in order.
        2. If this node *is* the slippage's descriptor1, return descriptor2
           (direct slippage).
        3. Otherwise, attempt a **coattail slippage**: if the slippage has a
           label, the label is not the same category as this node's category,
           and this node has a lateral-sliplink labeled with that label, then
           probabilistically return the node related to self via that label.
        4. If no slippage applies, return self unchanged.
        """
        for slippage in slippages:
            # Direct match: this node is the one being slipped
            if slippage.descriptor1 is self:
                return slippage.descriptor2

            # Attempt coattail slippage
            label = slippage.label
            if label is None:
                continue

            # Skip coattail if the slippage's CM-type (description_type1) is
            # the same as this node's category — coattail slippages only apply
            # across different conceptual dimensions.
            # Scheme: (eq? (tell (1st slippages) 'get-CM-type)
            #              (tell self 'get-category))
            cm_type = slippage.description_type1
            if cm_type is self.category:
                continue

            # Look for a lateral sliplink on self that is labeled with *label*
            sliplink = None
            for link in self.lateral_sliplinks:
                if link.label_node is label:
                    sliplink = link
                    break

            if sliplink is not None:
                # Coattail slippage probability = degree_of_association / 100
                prob = sliplink.degree_of_association() / 100.0
                if rng is not None and rng.prob(prob):
                    related = self.get_related_node(label)
                    if related is not None:
                        return related
                elif rng is None:
                    # Without RNG, always apply coattail (deterministic mode)
                    related = self.get_related_node(label)
                    if related is not None:
                        return related

        # No slippage applied
        return self

    def __repr__(self) -> str:
        return f"SlipnetNode({self.short_name}, act={self.activation:.0f}, depth={self.conceptual_depth})"


class SlipnetLink:
    """A directed link between two SlipnetNodes."""

    __slots__ = (
        "from_node",
        "to_node",
        "label_node",
        "link_type",
        "fixed_length",
        "_fixed_link_length",
    )

    def __init__(
        self,
        from_node: SlipnetNode,
        to_node: SlipnetNode,
        link_type: str,
        label_node: SlipnetNode | None = None,
        fixed_link_length: int | None = None,
    ) -> None:
        self.from_node = from_node
        self.to_node = to_node
        self.link_type = link_type
        self.label_node = label_node
        self.fixed_length = fixed_link_length is not None
        self._fixed_link_length = fixed_link_length

    def link_length(self) -> int:
        """Current link length. Dynamic links use label node's intrinsic length
        (or shrunk length if fully active)."""
        if self.fixed_length:
            return self._fixed_link_length  # type: ignore
        if self.label_node is not None:
            if self.label_node.fully_active():
                shrunk = self.label_node.shrunk_link_length()
                if shrunk is not None:
                    return shrunk
            if self.label_node.intrinsic_link_length is not None:
                return self.label_node.intrinsic_link_length
        return 50  # Default fallback

    def intrinsic_degree_of_association(self) -> float:
        """Scheme: slipnet.ss:330-333. Always uses intrinsic length, never shrunk."""
        if self.fixed_length:
            return max(0.0, 100.0 - self._fixed_link_length)  # type: ignore
        if self.label_node is not None:
            if self.label_node.intrinsic_link_length is not None:
                return max(0.0, 100.0 - self.label_node.intrinsic_link_length)
        return 50.0  # Default fallback

    def degree_of_association(self) -> float:
        """Scheme: slipnet.ss:334-339. Dynamic — uses shrunk length when label is fully active."""
        return max(0.0, 100.0 - self.link_length())

    def __repr__(self) -> str:
        label = f", label={self.label_node.short_name}" if self.label_node else ""
        return f"SlipnetLink({self.from_node.short_name}->{self.to_node.short_name}, {self.link_type}{label})"


class Slipnet:
    """The full semantic network."""

    def __init__(self) -> None:
        self.nodes: dict[str, SlipnetNode] = {}

    @classmethod
    def from_metadata(cls, meta: MetadataProvider) -> Slipnet:
        """Construct full graph from DB-loaded specs."""
        slipnet = cls()

        # Create nodes
        for spec in meta.slipnet_node_specs.values():
            node = SlipnetNode(spec.name, spec.short_name, spec.conceptual_depth)
            slipnet.nodes[spec.name] = node

        # Set intrinsic link lengths from engine params
        intrinsic_lengths = meta.get_param("intrinsic_link_lengths", {})
        for node_name, length in intrinsic_lengths.items():
            if node_name in slipnet.nodes:
                slipnet.nodes[node_name].intrinsic_link_length = length

        # Create links
        for link_spec in meta.slipnet_link_specs:
            from_node = slipnet.nodes.get(link_spec.from_node)
            to_node = slipnet.nodes.get(link_spec.to_node)
            if from_node is None or to_node is None:
                continue

            label_node = None
            if link_spec.label_node:
                label_node = slipnet.nodes.get(link_spec.label_node)

            link = SlipnetLink(
                from_node=from_node,
                to_node=to_node,
                link_type=link_spec.link_type,
                label_node=label_node,
                fixed_link_length=link_spec.link_length if link_spec.fixed_length else None,
            )

            # Attach to appropriate list on from_node
            if link_spec.link_type == "category":
                from_node.category_links.append(link)
            elif link_spec.link_type == "instance":
                from_node.instance_links.append(link)
            elif link_spec.link_type == "property":
                from_node.property_links.append(link)
            elif link_spec.link_type == "lateral":
                from_node.lateral_links.append(link)
            elif link_spec.link_type == "lateral_sliplink":
                from_node.lateral_sliplinks.append(link)

            to_node.incoming_links.append(link)

        # Compute decay rates
        ucl = meta.get_param("update_cycle_length", 15)
        for node in slipnet.nodes.values():
            node.compute_rate_of_decay(ucl)

        return slipnet

    def get_node(self, name: str) -> SlipnetNode:
        return self.nodes[name]

    def spread_activation(
        self, update_cycle_length: int = 15, threshold: int = 100
    ) -> None:
        """One round of activation spreading across all nodes.

        Args:
            update_cycle_length: Number of codelets per update cycle (default 15).
            threshold: Minimum activation level for a node to spread to neighbors.
                At 100 (default), only fully-active nodes spread — matching
                the original Scheme behaviour (slipnet.ss:383).
                At 0, all active nodes spread (pre-fix behaviour).
        """
        # Clear buffers
        for node in self.nodes.values():
            node.activation_buffer = 0.0

        # Decay all nodes
        for node in self.nodes.values():
            node.decay()

        # Spread only from nodes at or above threshold
        for node in self.nodes.values():
            if node.activation >= threshold:
                node.spread_activation_to_neighbors(update_cycle_length)

        # Apply buffers
        for node in self.nodes.values():
            node.activation = max(0.0, min(100.0, node.activation + node.activation_buffer))
            node.activation_buffer = 0.0

    def update_activations(self, rng: RNG, threshold: int = 100) -> None:
        """Spread activation and do probabilistic jumps.

        Scheme: slipnet.ss:377-389.
        Note: theme→slipnet spreading should be called BEFORE this method;
        the activation_buffer may already contain contributions from themes.
        """
        ucl = 15  # Will be parameterized later
        self.spread_activation(ucl, threshold=threshold)
        # Probabilistic jump for partially-active nodes (50-99)
        for node in self.nodes.values():
            node.probabilistic_jump_to_full(rng)

    def clamp_initially_relevant(self, meta: MetadataProvider) -> None:
        """Clamp initially-relevant slipnet nodes.

        Scheme: run.ss init-mcat.
        """
        initially_clamped = meta.get_param("initially_clamped_slipnodes", [])
        clamp_cycles = meta.get_param("initial_slipnode_clamp_cycles", 50)
        for node_name in initially_clamped:
            if node_name in self.nodes:
                self.nodes[node_name].clamp(clamp_cycles)

    def tick_clamps(self) -> None:
        """Decrement all clamp counters."""
        for node in self.nodes.values():
            node.tick_clamp()

    def reset_activations(self) -> None:
        """Set all activations to 0 and unclamp everything."""
        for node in self.nodes.values():
            node.activation = 0.0
            node.activation_buffer = 0.0
            node.frozen = False
            node.clamp_cycles_remaining = 0

    # ------------------------------------------------------------------
    # Query functions (Scheme: slipnet.ss ~287-365)
    # ------------------------------------------------------------------

    def get_label(
        self, from_node: SlipnetNode, to_node: SlipnetNode
    ) -> SlipnetNode | None:
        """Return the label node of the link connecting *from_node* to *to_node*.

        Scheme: slipnet.ss:287-296.
        - If from_node *is* to_node, return the identity node.
        - Otherwise walk to_node's incoming links to find one whose from_node
          matches, and return its label_node.
        """
        if from_node is to_node:
            return self.nodes.get("plato-identity")

        for link in to_node.incoming_links:
            if link.from_node is from_node:
                return link.label_node
        return None

    def relationship_between(
        self, nodes: list[SlipnetNode]
    ) -> SlipnetNode | None:
        """Return the common pairwise relationship among consecutive *nodes*.

        Scheme: slipnet.ss:299-306.
        Applies ``get_label`` to each adjacent pair.  If all labels exist and
        are the same node, return that relationship; otherwise return None.
        """
        if not nodes or any(n is None for n in nodes):
            return None

        if len(nodes) < 2:
            return None

        # adjacency-map: apply get_label to each consecutive pair
        relations: list[SlipnetNode | None] = []
        for i in range(len(nodes) - 1):
            relations.append(self.get_label(nodes[i], nodes[i + 1]))

        # All must exist and be the same
        if any(r is None for r in relations):
            return None
        if len(set(id(r) for r in relations)) != 1:
            return None

        return relations[0]

    def related(self, node1: SlipnetNode, node2: SlipnetNode) -> bool:
        """True if *node1* and *node2* are the same node or connected by any link.

        Scheme: slipnet.ss:352-354.
        """
        if node1 is node2:
            return True
        return self.linked(node1, node2)

    def linked(self, node1: SlipnetNode, node2: SlipnetNode) -> bool:
        """True if *node1* has any outgoing link (any type) to *node2*.

        Scheme: slipnet.ss:357-359.
        """
        return any(link.to_node is node2 for link in node1.outgoing_links)

    def slip_linked(self, node1: SlipnetNode, node2: SlipnetNode) -> bool:
        """True if *node1* has a lateral-sliplink to *node2*.

        Scheme: slipnet.ss:362-365.
        """
        return any(
            link.to_node is node2 for link in node1.lateral_sliplinks
        )

    @staticmethod
    def apply_slippages(
        node: SlipnetNode,
        slippages: list[object],
        rng: RNG | None = None,
    ) -> SlipnetNode:
        """Apply *slippages* to *node* and return the (possibly slipped) result.

        Convenience wrapper around ``SlipnetNode.apply_slippages``.
        See ``SlipnetNode.apply_slippages`` for full documentation.
        """
        return node.apply_slippages(slippages, rng=rng)

    @staticmethod
    def get_slipped_node(
        node: SlipnetNode,
        slippages: list[object],
        rng: RNG | None = None,
    ) -> SlipnetNode:
        """Return the slipped version of *node* given *slippages*.

        If *node* appears as ``descriptor1`` in any slippage, the corresponding
        ``descriptor2`` is returned.  Coattail slippages are attempted for
        non-matching slippages.  If no slippage matches, *node* is returned
        unchanged.

        This is the primary entry point for rule translation.
        """
        return node.apply_slippages(slippages, rng=rng)

    def __repr__(self) -> str:
        active = [n for n in self.nodes.values() if n.activation > 0]
        return f"Slipnet({len(self.nodes)} nodes, {len(active)} active)"
