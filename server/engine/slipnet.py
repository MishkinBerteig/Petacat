"""Slipnet — semantic network of concept nodes.

The Slipnet is a graph of SlipnetNode objects connected by SlipnetLink objects.
Built at startup from the MetadataProvider. The graph topology, conceptual depths,
link lengths, and link types are all DB-driven. The activation spreading
*algorithm* is in code; the *data* it operates on is not.

Scheme source: slipnet.ss
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, Callable

from server.engine.numeric.backend import select_backend
from server.engine.numeric.layout import (
    FULL_ACTIVATION_THRESHOLD,
    MAX_ACTIVATION,
    SlipnetState,
    SlipnetTopology,
)

if TYPE_CHECKING:
    from server.engine.metadata import MetadataProvider, SlipnodeSpec, SlipnetLinkSpec
    from server.engine.rng import RNG


# ---------------------------------------------------------------------------
# Descriptor predicates
#
# Scheme: the ``(tell plato-x 'define-descriptor-predicate ...)`` block at
# slipnet.ss:508-610, where each predicate is a lambda attached to the node.
#
# In Petacat the predicate travels with the node in ``slipnet_nodes.json``, as a
# small DSL expression over ``obj``, and is compiled once at startup — the same
# arrangement as a codelet's ``execute_body``.  The helpers below are the
# vocabulary those expressions are written against; they are mechanism, while
# *which* predicate belongs to *which* concept is domain knowledge and lives in
# the seed data.
# ---------------------------------------------------------------------------


def _is_group(obj: Any) -> bool:
    return hasattr(obj, "objects")


def _spans_whole_string(obj: Any) -> bool:
    spans = getattr(obj, "spans_whole_string", None)
    return bool(spans()) if callable(spans) else False


def _string_spanning_group(obj: Any) -> bool:
    return _is_group(obj) and _spans_whole_string(obj)


def _group_length(obj: Any) -> int | None:
    return len(getattr(obj, "objects", [])) if _is_group(obj) else None


def _letter_category_name(obj: Any) -> str:
    for d in getattr(obj, "descriptions", []):
        if getattr(d.description_type, "name", "") == "plato-letter-category":
            return getattr(d.descriptor, "name", "")
    return getattr(getattr(obj, "letter_category", None), "name", "")


def _position_in_string(obj: Any, which: str) -> bool:
    string = getattr(obj, "string", None)
    if string is None:
        return False
    objects = [o for o in getattr(string, "objects", []) if not _is_group(o)]
    if not objects:
        return False
    left = min(o.left_string_pos for o in objects)
    right = max(o.right_string_pos for o in objects)
    if which == "leftmost":
        return obj.left_string_pos == left
    if which == "rightmost":
        return obj.right_string_pos == right
    # middle: exactly one object to the left and one to the right
    return (
        obj.left_string_pos == left + 1
        and obj.right_string_pos == right - 1
        and right - left == 2
    )


# The vocabulary a ``descriptor_predicate`` expression may use.
DESCRIPTOR_PREDICATE_NAMESPACE: dict[str, Any] = {
    "is_group": _is_group,
    "group_length": _group_length,
    "spans_whole_string": _spans_whole_string,
    "string_spanning_group": _string_spanning_group,
    "position_in_string": _position_in_string,
    "letter_category_name": _letter_category_name,
}


def compile_descriptor_predicate(
    source: str, node_name: str
) -> Callable[[Any], bool]:
    """Compile a seed-data descriptor predicate into a callable.

    Raises ``ValueError`` at startup on a bad expression, rather than failing
    silently mid-run — the same contract the codelet compiler offers.
    """
    try:
        code = compile(source, f"<descriptor-predicate:{node_name}>", "eval")
    except SyntaxError as exc:  # pragma: no cover - seed data is checked in
        raise ValueError(
            f"descriptor predicate for {node_name} does not compile: {exc}"
        ) from exc

    def predicate(obj: Any) -> bool:
        return bool(eval(code, {**DESCRIPTOR_PREDICATE_NAMESPACE, "obj": obj}))  # noqa: S307

    return predicate


def _descriptor_read_from_object(descriptor_name: str, obj: Any) -> bool:
    """Fallback for descriptors that are *read off* an object, not tested.

    Letter-category, direction, bond-category, group-category and bond-facet
    descriptors are properties the object already carries, so there is nothing to
    predicate — the node simply describes the object if the object says so.
    """
    for d in getattr(obj, "descriptions", []):
        if getattr(d.descriptor, "name", "") == descriptor_name:
            return True
    for attr in ("direction", "group_category", "bond_facet"):
        node = getattr(obj, attr, None)
        if node is not None and getattr(node, "name", "") == descriptor_name:
            return True
    return _letter_category_name(obj) == descriptor_name


class SlipnetNode:
    """A concept node in the Slipnet."""

    __slots__ = (
        "name",
        "short_name",
        "conceptual_depth",
        "descriptor_predicate",
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

    def fully_active(self, threshold: float = MAX_ACTIVATION) -> bool:
        """Is this concept at *full* activation?

        Scheme: ``fully-active?`` (slipnet.ss:392-394) —
        ``(= (tell node 'get-activation) %max-activation%)``, i.e. exactly 100,
        not merely past the threshold.  Written ``>=`` rather than ``==`` only
        because the activation is a float here; it is clipped to exactly 100.0
        by ``spread_activation``'s flush, by ``clamp`` and by the jump, so the
        two forms agree on every value the engine can produce.

        This is the predicate behind link shrinking and degree of association
        (slipnet.ss:90-91, 334-339), concept-mapping relevance
        (concept-mappings.ss:107-109) and description relevance
        (descriptions.ss:67).  It is *not* the predicate that gates top-down
        codelet posting — that one is ``above_threshold``, and conflating the
        two makes the whole 50-99 band behave as though it were saturated.
        """
        return self.activation >= threshold

    def above_threshold(
        self, threshold: float = FULL_ACTIVATION_THRESHOLD
    ) -> bool:
        """Is this concept active enough to exert top-down pressure?

        Scheme: ``above-threshold?`` (slipnet.ss:397-399) —
        ``(>= activation %full-activation-threshold%)``, with the threshold 50.
        Its sole consumer in the reference is
        ``attempt-to-post-top-down-codelets`` (slipnet.ss:212-213).
        """
        return self.activation >= threshold

    def partially_active(self) -> bool:
        """Above the threshold but not yet saturated — the jump's candidates.

        Scheme: ``partially-active?`` (slipnet.ss:402-404).
        """
        return (
            self.activation >= FULL_ACTIVATION_THRESHOLD
            and self.activation < MAX_ACTIVATION
        )

    def activate_from_workspace(self) -> None:
        """Jolt this node from the Workspace.

        Scheme: ``activate-from-workspace`` (slipnet.ss:171-172) —
        ``increment-activation-buffer %workspace-activation%``, i.e. +100 into
        the buffer, clipped when the buffer is flushed.

        This is what keeps the Slipnet alive: nodes decay fast (letter-category
        loses 70% of its activation per update cycle), and it is the constant
        stream of scouts, evaluators and builders re-activating the concepts
        they touch that holds the relevant ones up.
        """
        if self.frozen:
            return
        self.activation_buffer += 100.0

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

    # ------------------------------------------------------------------
    # Descriptor predicates  (Scheme: slipnet.ss:556-610)
    # ------------------------------------------------------------------

    def describes(self, obj: Any) -> bool:
        """Does this node validly describe *obj*?

        Scheme: ``define-descriptor-predicate``.  Answers "which descriptors along
        this dimension actually apply to this object", so codelets don't propose
        descriptions that are simply false.  The predicate itself comes from the
        node's seed data; descriptors that are read off the object rather than
        tested against it fall back to inspecting the object.
        """
        if self.descriptor_predicate is not None:
            return self.descriptor_predicate(obj)
        return _descriptor_read_from_object(self.name, obj)

    def get_possible_descriptors(self, obj: Any) -> list[SlipnetNode]:
        """Descriptors of this *category* node that apply to *obj*.

        Scheme: ``get-possible-descriptors`` / ``description-possible?``.
        """
        return [
            link.to_node
            for link in self.instance_links
            if link.to_node.describes(obj)
        ]

    def description_possible(self, obj: Any) -> bool:
        return bool(self.get_possible_descriptors(obj))

    def shrunk_link_length(self) -> int | None:
        """40% of intrinsic link length. Scheme: slipnet.ss:191."""
        if self.intrinsic_link_length is None:
            return None
        return round(0.4 * self.intrinsic_link_length)

    def degree_of_assoc(self) -> float:
        """How strongly this *label* concept associates the things it labels.

        Scheme: ``get-degree-of-assoc`` on a slipnode (slipnet.ss:90-91) —
        ``100 - (fully-active? ? shrunk-link-length : intrinsic-link-length)``.
        Distinct from ``SlipnetLink.degree_of_association``, which asks the same
        question of a particular link; this asks it of the relating concept
        itself, and is what sets the probability of an auxiliary slippage in
        ``look-for-auxiliary-slippages`` (themes.ss:920-924).
        """
        if self.intrinsic_link_length is None:
            return 0.0
        if self.fully_active():
            shrunk = self.shrunk_link_length()
            if shrunk is not None:
                return max(0.0, 100.0 - shrunk)
        return max(0.0, 100.0 - self.intrinsic_link_length)

    @property
    def is_instance(self) -> bool:
        """Is this node an instance of some category?  Scheme: slipnet.ss:94."""
        return bool(self.category_links)

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
        """Stochastic jump to full activation, for a *partially active* node.

        Scheme: ``update-slipnet-activations`` (slipnet.ss:387-389) draws only
        for nodes passing ``partially-active?`` — activation in [50, 100) — with
        probability ``(activation/100)^3``.

        The floor matters.  Without it a node at 30 jumps to full with
        probability 0.027 per update cycle and a residual activation never stops
        being a candidate, so concepts the run has finished with keep firing back
        to saturation, spreading, shrinking their links and posting top-down
        codelets.  The cube alone does not suppress that: it is the threshold
        that decides *whether* a concept is in the running at all, and the cube
        that decides how readily one already in the running commits.
        """
        if not self.partially_active():
            return
        prob = (self.activation / MAX_ACTIVATION) ** 3
        if rng.prob(prob):
            self.activation = MAX_ACTIVATION

    @property
    def category(self) -> SlipnetNode | None:
        """Return the category node (to_node of the first category link), or None.

        Scheme: slipnet.ss:95-98.
        """
        if self.category_links:
            return self.category_links[0].to_node
        return None

    def get_related_node(self, relation: SlipnetNode | str) -> SlipnetNode | None:
        """Find the neighbor node connected via a link labeled with *relation*.

        Scheme: slipnet.ss:114-129.
        - If *relation* is the identity node, return self.
        - Otherwise, walk outgoing links for ones whose label_node is *relation*.
        - If exactly one match, return it.
        - If multiple matches, prefer the one sharing self's category.
        - If none, return None.

        *relation* may be given as a node **or** as a node name.  Callers deep in
        the Workspace — group and bond flipping — hold no Slipnet handle to reach
        ``plato-opposite`` with, and passing the name used to raise
        ``AttributeError`` into a bare ``except`` at both call sites, so a
        "flipped" group silently kept its original direction and category.
        Matching by name is exact: node names are unique within a Slipnet.
        """
        relation_name = (
            relation if isinstance(relation, str) else getattr(relation, "name", "")
        )
        # Identity relation -> return self
        if relation_name == "plato-identity":
            return self

        related_nodes: list[SlipnetNode] = []
        for link in self.outgoing_links:
            if link.label_node is not None and link.label_node.name == relation_name:
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
                # §3.4.1: a coattail slippage happens only sometimes, with
                # probability given by the sliplink's degree of association.
                # Without an RNG we make no speculative slippage at all —
                # firing every eligible coattail would mean, for instance, that
                # a first=>last slippage *always* dragged successor=>predecessor
                # along, which is precisely the determinism §3.4 rejects.
                if rng is None:
                    continue
                prob = sliplink.degree_of_association() / 100.0
                if rng.prob(prob):
                    related = self.get_related_node(label)
                    if related is not None:
                        return related

        # No slippage applied
        return self

    def __repr__(self) -> str:
        return f"SlipnetNode({self.short_name}, act={self.activation:.0f}, depth={self.conceptual_depth})"


def opposite_node(node: Any) -> Any:
    """The concept *node* relates to by ``plato-opposite``, or *node* itself.

    Scheme: ``(tell node 'get-related-node plato-opposite)`` as used by
    ``make-flipped-version`` (bonds.ss:125, groups.ss:334-338).  A concept with no
    opposite — sameness, or a group with no direction — is its own reflection, so
    returning it unchanged is what "flipping" means for it.

    Resolved through ``getattr`` because flipping is also exercised against
    stand-in descriptor objects that carry a name and nothing else; a stand-in
    with no Slipnet links has no opposite to offer, which is the same answer as a
    real concept without one.
    """
    if node is None:
        return None
    get_related_node = getattr(node, "get_related_node", None)
    if get_related_node is None:
        return node
    related = get_related_node("plato-opposite")
    return related if related is not None else node


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
        (or shrunk length if fully active).

        Scheme: ``get-degree-of-assoc`` on a link (slipnet.ss:334-339) — the
        shrunk length applies only when the label node is ``fully-active?``,
        i.e. at exactly 100.  A label merely past the threshold does not shrink
        its links.
        """
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


#: Sentinel distinguishing "the substrate has not been resolved yet" from "the
#: substrate resolved to *no backend*, run the reference loops".  Both are common
#: and ``None`` cannot mean both.
_UNRESOLVED = object()


class Slipnet:
    """The full semantic network."""

    def __init__(self) -> None:
        self.nodes: dict[str, SlipnetNode] = {}
        # Resolved on first use rather than here, because ``from_metadata``
        # computes the decay rates *after* constructing the Slipnet and the
        # numeric layout needs them.
        self._numeric: Any = _UNRESOLVED

    @classmethod
    def from_metadata(cls, meta: MetadataProvider) -> Slipnet:
        """Construct full graph from DB-loaded specs."""
        slipnet = cls()

        # Create nodes
        for spec in meta.slipnet_node_specs.values():
            node = SlipnetNode(spec.name, spec.short_name, spec.conceptual_depth)
            if spec.descriptor_predicate:
                node.descriptor_predicate = compile_descriptor_predicate(
                    spec.descriptor_predicate, spec.name
                )
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
        # NB: the buffers are deliberately *not* cleared here.  Between update
        # cycles, codelets pour Workspace activation into them via
        # ``activate_from_workspace``, and the Themespace adds its contribution
        # just before this runs.  Clearing first threw all of that away, which
        # let the Slipnet decay to zero a few hundred codelets into every run.
        # Scheme: ``update-slipnet-activations`` (slipnet.ss:377-389) decays,
        # spreads, then flushes — it never clears up front.

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

    # ------------------------------------------------------------------
    # The numeric substrate  (WP4.5)
    # ------------------------------------------------------------------

    def _numeric_session(self) -> Any:
        """A prepared ``SlipnetSession``, or ``None`` to run the loops above.

        The topology is flattened once and the session holds it for the life of
        the Slipnet, which is what makes the substrate worth having at scale: the
        sparse matrix is entirely static (``intrinsic_degree_of_association``
        never consults an activation), so there is no rebuild to amortise.

        ``None`` is the answer for a 59-node Slipnet under the default policy, and
        deliberately so — see ``numeric/backend.py``.
        """
        if self._numeric is not _UNRESOLVED:
            return self._numeric
        backend = select_backend(len(self.nodes))
        if backend is None:
            self._numeric = None
        else:
            self._numeric = backend.open_slipnet(SlipnetTopology.from_slipnet(self))
        return self._numeric

    def invalidate_numeric_layout(self) -> None:
        """Discard the flattened topology, forcing a rebuild on next use.

        Needed only if the graph is edited after construction — the admin surface
        can rewrite link lengths — because the layout caches the association
        weights that such an edit changes.
        """
        self._numeric = _UNRESOLVED

    def update_activations(self, rng: RNG, threshold: int = 100) -> None:
        """Spread activation and do probabilistic jumps.

        Scheme: slipnet.ss:377-389.
        Note: theme→slipnet spreading should be called BEFORE this method;
        the activation_buffer may already contain contributions from themes.

        The RNG is consumed identically on both paths, and that is the constraint
        the substrate's interface is shaped around.  A draw happens for a node
        that is ``partially-active?`` — activation in [50, 100) — and for no
        other: below 50 the node is not a candidate at all, and at exactly 100
        ``RNG.prob`` short-circuits without touching the stream.  The substrate
        therefore hands back only the nodes that *would* consume a draw, in index
        order, and the loop below draws for exactly those.  Same draws, same
        order, same count as the reference — which is what keeps a seeded run
        comparable across the change.
        """
        ucl = 15  # Will be parameterized later
        session = self._numeric_session()
        if session is None:
            self.spread_activation(ucl, threshold=threshold)
            # Probabilistic jump, for partially-active nodes only (50-99).
            for node in self.nodes.values():
                node.probabilistic_jump_to_full(rng)
            return

        session.load(SlipnetState.from_slipnet(self))
        session.update(float(threshold), ucl / 15.0)
        indices, probabilities = session.jump_candidates()
        session.apply_jumps(
            [i for i, p in zip(indices, probabilities) if rng.prob(p)]
        )
        session.store().apply_to_slipnet(self)

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
