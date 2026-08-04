"""Abstract image representations for rule application.

Images are part of the machinery of rule application. Each letter or group
in a string, as well as the string itself, has an "image" that represents
what the object currently looks like. Normally, an image just looks like
the object itself. However, when a rule is applied to the string, the
appearance of these images may change. For example, if the rule "Increase
length of all objects in string" is applied to the string abc, the
resulting appearance of the string (i.e., its image) is aabbcc.

Scheme source: images.ss
"""

from __future__ import annotations

from copy import copy
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from server.engine.slipnet import Slipnet, SlipnetNode
    from server.engine.workspace_objects import Letter, WorkspaceObject


# ---------------------------------------------------------------------------
# Slipnet helper utilities
#
# These mirror the Scheme-level predicates and converters defined in
# slipnet.ss (platonic-letter?, platonic-number?, number->platonic-number,
# platonic-number->number, platonic-relation?, inverse, get-label,
# relationship-between, enumerate-letter).
#
# They operate on SlipnetNode references and a Slipnet instance so that
# callers do not need to hard-code node names.
# ---------------------------------------------------------------------------

# Canonical node-name lists (same order as slipnet.ss).
_LETTER_NAMES: list[str] = [f"plato-{chr(c)}" for c in range(ord("a"), ord("z") + 1)]
_NUMBER_NAMES: list[str] = [
    "plato-one",
    "plato-two",
    "plato-three",
    "plato-four",
    "plato-five",
]
_RELATION_NAMES: frozenset[str] = frozenset(
    ["plato-identity", "plato-opposite", "plato-predecessor", "plato-successor"]
)


def is_platonic_letter(node: SlipnetNode | None) -> bool:
    """Scheme: platonic-letter?"""
    return node is not None and node.name in _LETTER_NAMES


def is_platonic_number(node: SlipnetNode | None) -> bool:
    """Scheme: platonic-number?"""
    return node is not None and node.name in _NUMBER_NAMES


def is_platonic_relation(node: SlipnetNode | None) -> bool:
    """Scheme: platonic-relation?"""
    return node is not None and node.name in _RELATION_NAMES


def number_to_platonic_number(n: int, slipnet: Slipnet) -> SlipnetNode | None:
    """Scheme: number->platonic-number.

    Returns the platonic number node for *n* (1-indexed), or ``None`` if
    *n* is out of range (> 5).
    """
    if n < 1 or n > len(_NUMBER_NAMES):
        return None
    return slipnet.nodes.get(_NUMBER_NAMES[n - 1])


def platonic_number_to_number(node: SlipnetNode, slipnet: Slipnet) -> int:
    """Scheme: platonic-number->number. 1-indexed."""
    for i, name in enumerate(_NUMBER_NAMES):
        if slipnet.nodes.get(name) is node:
            return i + 1
    raise ValueError(f"{node} is not a platonic number node")


def get_related_node(
    node: SlipnetNode, relation: SlipnetNode, slipnet: Slipnet
) -> SlipnetNode | None:
    """Scheme: slipnet.ss get-related-node method.

    If *relation* is plato-identity, returns *node* itself.
    Otherwise, looks for an outgoing link whose label is *relation* and
    returns the target node (preferring one with the same category as *node*).
    """
    identity = slipnet.nodes.get("plato-identity")
    if relation is identity:
        return node

    # Collect all outgoing links labeled with *relation*.
    candidates: list[SlipnetNode] = []
    for link in node.outgoing_links:
        if link.label_node is relation:
            candidates.append(link.to_node)

    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    # Prefer a candidate with the same category as *node*.
    node_cat = _get_category(node)
    if node_cat is not None:
        for c in candidates:
            if _get_category(c) is node_cat:
                return c
    return candidates[0]


def _get_category(node: SlipnetNode) -> SlipnetNode | None:
    """Return the first category node reachable via a category link."""
    if node.category_links:
        return node.category_links[0].to_node
    return None


def inverse(node: SlipnetNode | None, slipnet: Slipnet) -> SlipnetNode | None:
    """Scheme: inverse.

    Returns the *opposite* of a slipnet node. For plato-identity returns
    itself; for others, follows the plato-opposite relation.
    """
    if node is None:
        return None
    identity = slipnet.nodes.get("plato-identity")
    if node is identity:
        return identity
    opposite = slipnet.nodes.get("plato-opposite")
    if opposite is None:
        return None
    return get_related_node(node, opposite, slipnet)


def get_label(
    from_node: SlipnetNode, to_node: SlipnetNode, slipnet: Slipnet
) -> SlipnetNode | None:
    """Scheme: get-label.

    Returns the label node on the link from *from_node* to *to_node*, or
    plato-identity if they are the same node, or ``None`` if no link exists.
    """
    if from_node is to_node:
        return slipnet.nodes.get("plato-identity")
    for link in to_node.incoming_links:
        if link.from_node is from_node:
            return link.label_node
    return None


def relationship_between(
    nodes: list[SlipnetNode | None], slipnet: Slipnet
) -> SlipnetNode | None:
    """Scheme: relationship-between.

    Given a list of nodes, checks that adjacent pairs all have the same
    label. Returns that label, or ``None`` if the relationship is not
    uniform (or any node is ``None``).
    """
    if not nodes or any(n is None for n in nodes):
        return None
    if len(nodes) == 1:
        return slipnet.nodes.get("plato-identity")

    labels: list[SlipnetNode | None] = []
    for a, b in zip(nodes[:-1], nodes[1:]):
        labels.append(get_label(a, b, slipnet))  # type: ignore[arg-type]

    if any(l is None for l in labels):
        return None
    if len(set(id(l) for l in labels)) != 1:
        return None
    return labels[0]


def enumerate_letter(
    start: SlipnetNode,
    relation: SlipnetNode | None,
    n: int,
    slipnet: Slipnet,
) -> list[SlipnetNode] | None:
    """Scheme: enumerate-letter.

    Starting from *start*, applies *relation* (successor/predecessor/identity)
    *n*-1 times to generate a list of *n* letter nodes. Returns ``None`` on
    failure (e.g. going past 'a' or 'z').
    """
    if n > 1 and relation is None:
        return None
    result: list[SlipnetNode] = [start]
    current = start
    for _ in range(n - 1):
        nxt = get_related_node(current, relation, slipnet)  # type: ignore[arg-type]
        if nxt is None:
            return None
        result.append(nxt)
        current = nxt
    return result


def change_length_first(
    length_arg: SlipnetNode | None,
    current_length: SlipnetNode | None,
    slipnet: Slipnet,
) -> bool:
    """Scheme: change-length-first?

    Returns ``True`` when a length change should be applied before a letter
    change. This is the case when:
    - *length_arg* is plato-predecessor, OR
    - *length_arg* is a platonic number that is smaller than *current_length*.
    """
    if length_arg is None:
        return False
    pred = slipnet.nodes.get("plato-predecessor")
    if length_arg is pred:
        return True
    if is_platonic_number(length_arg):
        if current_length is None:
            return True
        if is_platonic_number(current_length):
            return platonic_number_to_number(length_arg, slipnet) < platonic_number_to_number(
                current_length, slipnet
            )
    return False


# ---------------------------------------------------------------------------
# Failure sentinel
# ---------------------------------------------------------------------------

def _is_group(obj: Any) -> bool:
    """A workspace object with constituent objects of its own."""
    return bool(getattr(obj, "objects", None))


class ImageFailure(Exception):
    """Raised when an image transformation cannot be performed.

    This replaces the Scheme ``(fail)`` continuation. Callers should catch
    this to handle rule-application failures gracefully.

    ``objects`` carries the Workspace objects the failure happened *on*, which is
    the Scheme's ``<failure-result>`` (``answers.ss:1145-1150``): ``SWAP`` reports
    both swapped objects, ``CONFLICT`` the two in conflict, ``CHANGE`` the single
    object being changed.  ``make-snag-event`` (``trace.ss:1055-1059``) takes the
    snag objects from exactly there, so a snag names what actually went wrong
    rather than everything the rule mentioned.

    ``kind`` names *which* of the three shapes it is.  It is the first element of the
    Scheme's failure-result and ``make-snag-event`` records it as the snag type
    (``trace.ss:1053``), which decides the snag's own explanation
    (``trace.ss:1097-1125``).  Petacat hard-coded ``"change"`` for every snag, so a
    swap snag and a conflict snag were indistinguishable in the Trace and in memory.
    ``CHANGE`` is the default because it is the Scheme's own catch-all: every raise
    site that is not the string-position swap or the conflict check is a change.
    """

    SWAP = "swap"
    CONFLICT = "conflict"
    CHANGE = "change"

    def __init__(
        self,
        message: str = "",
        objects: list | None = None,
        kind: str = CHANGE,
    ) -> None:
        super().__init__(message)
        self.objects: list = objects or []
        self.kind: str = kind


# ---------------------------------------------------------------------------
# Image (base / letter image)
# ---------------------------------------------------------------------------

class Image:
    """A single letter-or-group image used during rule application.

    Mirrors the Scheme ``make-image`` closure. When ``sub_images`` is empty
    the image represents a single letter ("letter image"); otherwise it
    represents a group of sub-images.

    The original ``Image`` stub's ``matches()`` behaviour is preserved as a
    class method for backward compatibility.

    Parameters
    ----------
    slipnet : Slipnet
        A reference to the slipnet so that node lookups and ``get_related_node``
        calls can be made.
    start_letter : SlipnetNode
        The letter-category node (plato-a .. plato-z) at this image's position.
    bond_facet : SlipnetNode | None
        The bond facet (plato-letter-category or plato-length).  ``None`` for a
        pure letter image.
    letter_relation : SlipnetNode | None
        Relation between successive sub-image letters (successor, predecessor,
        identity, or ``None``).
    length_relation : SlipnetNode | None
        Relation between successive sub-image lengths.
    direction : SlipnetNode | None
        Direction of the group (plato-left or plato-right).
    sub_images : list[Image]
        Child images (empty for a letter image).
    """

    def __init__(
        self,
        slipnet: Slipnet,
        start_letter: SlipnetNode,
        bond_facet: SlipnetNode | None = None,
        letter_relation: SlipnetNode | None = None,
        length_relation: SlipnetNode | None = None,
        direction: SlipnetNode | None = None,
        sub_images: list[Image] | None = None,
    ) -> None:
        self.slipnet = slipnet
        self.start_letter = start_letter
        self.bond_facet = bond_facet
        self.letter_relation = letter_relation
        self.length_relation = length_relation
        self.direction = direction
        self.sub_images: list[Image] = sub_images if sub_images is not None else []

        # Save original state so we can reset.
        self._original_state = self._capture_state()

        # Swapped-image tracking (used by string-position swaps).
        self.swapped_image: Image | None = None

        # Workspace object created by instantiate_as_letter / instantiate_as_group.
        self.instantiated_object: Any = None

    # -- state snapshot / restore ------------------------------------------

    def _capture_state(self) -> tuple:
        return (
            self.start_letter,
            self.bond_facet,
            self.letter_relation,
            self.length_relation,
            self.direction,
            list(self.sub_images),
        )

    def get_state(self) -> tuple:
        return self._capture_state()

    def set_state(self, state: tuple) -> None:
        (
            self.start_letter,
            self.bond_facet,
            self.letter_relation,
            self.length_relation,
            self.direction,
            sub_images,
        ) = state
        # Copy: assigning the saved list directly aliases ``_original_state``,
        # so a later append would grow the "original" too and every subsequent
        # reset would restore a longer image than before.  That compounding is
        # what turned xyz into xxxxyyyyzzzz.
        self.sub_images = list(sub_images)

    def reset(self) -> None:
        """Restore image to its original (pre-rule-application) state."""
        self.set_state(self._original_state)
        self.swapped_image = None
        self.instantiated_object = None
        for sub in self.sub_images:
            sub.reset()

    # -- predicates --------------------------------------------------------

    @property
    def is_letter_image(self) -> bool:
        """Scheme: letter-image? — true when there are no sub-images."""
        return len(self.sub_images) == 0

    # -- getters (Scheme: get-letter, get-length, etc.) --------------------

    def get_letter(self) -> SlipnetNode:
        """Return the start-letter node."""
        return self.start_letter

    def get_length(self) -> SlipnetNode | None:
        """Platonic length of this image.

        Scheme: (get-length) — plato-one for letter images, otherwise the
        number of sub-images expressed as a platonic number.
        """
        if self.is_letter_image:
            return self.slipnet.nodes.get("plato-one")
        return number_to_platonic_number(len(self.sub_images), self.slipnet)

    # -- transformation operations -----------------------------------------

    def new_start_letter(self, arg: SlipnetNode | None) -> None:
        """Scheme: new-start-letter.

        *arg* is either a platonic relation (predecessor / successor / identity)
        or a platonic letter (plato-a .. plato-z).
        """
        if arg is None:
            raise ImageFailure("new_start_letter: arg is None")

        if self.is_letter_image:
            if is_platonic_relation(arg):
                new_letter = get_related_node(self.start_letter, arg, self.slipnet)
                if new_letter is None:
                    raise ImageFailure(
                        f"new_start_letter: no related node for "
                        f"{self.start_letter.name} via {arg.name}"
                    )
                self.start_letter = new_letter
            else:
                # arg is a literal letter node
                self.start_letter = arg
        elif is_platonic_relation(arg):
            for sub in self.sub_images:
                sub.new_start_letter(arg)
            new_start = get_related_node(self.start_letter, arg, self.slipnet)
            if new_start is not None:
                self.start_letter = new_start
        elif is_platonic_letter(arg):
            letters = enumerate_letter(
                arg, self.letter_relation, len(self.sub_images), self.slipnet
            )
            if letters is None:
                raise ImageFailure(
                    f"new_start_letter: enumerate_letter failed for "
                    f"{arg.name}, relation={getattr(self.letter_relation, 'name', None)}, "
                    f"n={len(self.sub_images)}"
                )
            self.replace_all("new_start_letter", letters)
            self.start_letter = arg

    def new_alpha_position_category(self, arg: SlipnetNode | None) -> None:
        """Scheme: new-alpha-position-category.

        *arg* is one of plato-alphabetic-first, plato-alphabetic-last, or
        plato-opposite.
        """
        if arg is None:
            raise ImageFailure("new_alpha_position_category: arg is None")

        alpha_first = self.slipnet.nodes.get("plato-alphabetic-first")
        alpha_last = self.slipnet.nodes.get("plato-alphabetic-last")
        opp = self.slipnet.nodes.get("plato-opposite")
        plato_a = self.slipnet.nodes.get("plato-a")
        plato_z = self.slipnet.nodes.get("plato-z")

        if arg is alpha_first or (arg is opp and self.start_letter is plato_z):
            self.new_start_letter(plato_a)
        elif arg is alpha_last or (arg is opp and self.start_letter is plato_a):
            self.new_start_letter(plato_z)
        else:
            raise ImageFailure(
                f"new_alpha_position_category: unhandled arg {arg.name}"
            )

    def new_length(self, arg: SlipnetNode | None) -> None:
        """Scheme: new-length.

        *arg* is a platonic relation (predecessor / successor / identity) or a
        platonic number (plato-one .. plato-five).
        """
        if arg is None:
            raise ImageFailure("new_length: arg is None")

        identity = self.slipnet.nodes.get("plato-identity")
        pred = self.slipnet.nodes.get("plato-predecessor")
        succ = self.slipnet.nodes.get("plato-successor")

        if arg is identity:
            return
        if is_platonic_number(arg) and self.get_length() is arg:
            return

        if self.is_letter_image:
            self._letter_to_singleton_group()
            self.new_length(arg)
            return

        if arg is pred:
            self.shorten()
            return
        if arg is succ:
            self.extend(self.letter_relation, self.length_relation)
            return

        if is_platonic_number(arg):
            target_n = platonic_number_to_number(arg, self.slipnet)
            current_n = len(self.sub_images)
            if target_n <= current_n:
                for _ in range(current_n - target_n):
                    self.shorten()
            else:
                for _ in range(target_n - current_n):
                    self.extend(self.letter_relation, self.length_relation)
            return

        raise ImageFailure(f"new_length: unhandled arg {arg.name}")

    def reverse_direction(self) -> None:
        """Scheme: reverse-direction."""
        self.direction = inverse(self.direction, self.slipnet)

    def reverse_medium(self, medium: SlipnetNode | None) -> None:
        """Scheme: reverse-medium.

        Reverses the order of sub-images along a given medium
        (plato-letter-category or plato-length).
        """
        if self.is_letter_image:
            return

        letter_category = self.slipnet.nodes.get("plato-letter-category")
        length_node = self.slipnet.nodes.get("plato-length")

        if medium is letter_category:
            letters = [sub.get_letter() for sub in self.sub_images]
            self.replace_all("new_start_letter", list(reversed(letters)))
            self.letter_relation = inverse(self.letter_relation, self.slipnet)
            self.start_letter = letters[-1]  # last of original = first of reversed
        elif medium is length_node:
            lengths = [sub.get_length() for sub in self.sub_images]
            self.replace_all("new_length", list(reversed(lengths)))
            self.length_relation = inverse(self.length_relation, self.slipnet)

    def replace_all(self, method_name: str, new_args: list) -> None:
        """Scheme: replace-all.

        Calls the named method on each sub-image with the corresponding arg.
        """
        for img, arg in zip(self.sub_images, new_args):
            getattr(img, method_name)(arg)

    def letter(self) -> None:
        """Scheme: letter — collapse this image to a letter image.

        Removes sub-images, bond-facet, relations, and direction. Fails if the
        bond-facet is length (can't "un-length" a length-based group to a letter).
        """
        if self.is_letter_image:
            return
        length_node = self.slipnet.nodes.get("plato-length")
        if self.bond_facet is length_node:
            raise ImageFailure("letter: cannot collapse a length-based group image to a letter")
        self.bond_facet = None
        self.letter_relation = None
        self.length_relation = None
        self.direction = None
        self.sub_images = []

    def group(self) -> None:
        """Scheme: group — ensure this image is a group image.

        If already a group image, does nothing. If a letter image, promotes to
        a singleton group.
        """
        if self.is_letter_image:
            self._letter_to_singleton_group()

    def shorten(self) -> None:
        """Scheme: shorten — remove the last sub-image."""
        if len(self.sub_images) < 2:
            raise ImageFailure("shorten: fewer than 2 sub-images")
        self.sub_images = self.sub_images[:-1]
        if len(self.sub_images) > 1:
            if self.letter_relation is None:
                self.letter_relation = relationship_between(
                    [sub.get_letter() for sub in self.sub_images], self.slipnet
                )
            if self.length_relation is None:
                self.length_relation = relationship_between(
                    [sub.get_length() for sub in self.sub_images], self.slipnet
                )

    def extend(
        self,
        letter_arg: SlipnetNode | None,
        length_arg: SlipnetNode | None,
    ) -> None:
        """Scheme: extend — add a new sub-image extrapolated from the last one."""
        if self.is_letter_image:
            self._letter_to_singleton_group()
            self.extend(letter_arg, length_arg)
            return

        new_image = self.sub_images[-1].copy()

        if change_length_first(length_arg, new_image.get_length(), self.slipnet):
            if length_arg is not None:
                new_image.new_length(length_arg)
            if letter_arg is not None:
                new_image.new_start_letter(letter_arg)
        else:
            if letter_arg is not None:
                new_image.new_start_letter(letter_arg)
            if length_arg is not None:
                new_image.new_length(length_arg)

        self.sub_images.append(new_image)
        self.letter_relation = relationship_between(
            [sub.get_letter() for sub in self.sub_images], self.slipnet
        )
        self.length_relation = relationship_between(
            [sub.get_length() for sub in self.sub_images], self.slipnet
        )

    def copy(self) -> Image:
        """Scheme: copy — deep copy of this image."""
        return Image(
            slipnet=self.slipnet,
            start_letter=self.start_letter,
            bond_facet=self.bond_facet,
            letter_relation=self.letter_relation,
            length_relation=self.length_relation,
            direction=self.direction,
            sub_images=[sub.copy() for sub in self.sub_images],
        )

    # -- generation / instantiation ----------------------------------------

    def generate(self) -> list[SlipnetNode]:
        """Scheme: generate.

        Returns a flat list of letter-category nodes representing the letters
        this image would produce. For a letter image this is just the
        start_letter. For a group image, it recursively generates sub-images
        (in the direction-appropriate order).
        """
        if self.is_letter_image:
            return [self.start_letter]

        plato_left = self.slipnet.nodes.get("plato-left")
        ordered = list(reversed(self.sub_images)) if self.direction is plato_left else self.sub_images
        result: list[SlipnetNode] = []
        for sub in ordered:
            result.extend(sub.generate())
        return result

    def instantiate_as_letter(
        self, string: Any, position: int
    ) -> Any:
        """Scheme: instantiate-as-letter.

        Creates a new Letter workspace object from this image's start_letter
        and adds it to *string*.
        """
        from server.engine.workspace_objects import Letter

        letter = Letter(string, position, self.start_letter)
        string.objects.append(letter)
        self.instantiated_object = letter
        return letter

    def instantiate_as_group(self, string: Any) -> Any:
        """Scheme: instantiate-as-group.

        Creates a new Group workspace object from this image's sub-images
        (which must already be instantiated) and adds it to *string*.
        """
        from server.engine.groups import Group

        plato_left = self.slipnet.nodes.get("plato-left")
        identity = self.slipnet.nodes.get("plato-identity")
        sameness = self.slipnet.nodes.get("plato-sameness")
        samegrp = self.slipnet.nodes.get("plato-samegrp")
        letter_category = self.slipnet.nodes.get("plato-letter-category")

        # Ordered objects based on direction
        if self.direction is plato_left:
            ordered_objects = [
                sub.instantiated_object for sub in reversed(self.sub_images)
            ]
        else:
            ordered_objects = [sub.instantiated_object for sub in self.sub_images]

        if not ordered_objects or any(o is None for o in ordered_objects):
            raise ImageFailure("instantiate_as_group: not all sub-images instantiated")

        # Determine bond and group categories
        if self.bond_facet is letter_category:
            if self.letter_relation is identity:
                bond_category = sameness
            else:
                bond_category = self.letter_relation
        else:
            if self.length_relation is identity:
                bond_category = sameness
            else:
                bond_category = self.length_relation

        # Get related group-category from bond-category
        group_category_node = self.slipnet.nodes.get("plato-group-category")
        group_category = None
        if bond_category is not None and group_category_node is not None:
            group_category = get_related_node(bond_category, group_category_node, self.slipnet)
        if group_category is None:
            group_category = samegrp  # fallback

        # Group direction: None for same-groups
        group_direction = None if group_category is samegrp else self.direction

        # The bonds a group of adjacent objects *is*.  An instantiated group with no
        # internal bonds is a claim the program cannot support: it says these objects
        # form a same-group without saying that consecutive members are the same.  It
        # also leaves the answer string drawn as unconnected letters, which is what the
        # Workspace display then honestly reports.
        group_bonds = _bonds_between(
            ordered_objects, bond_category, self.bond_facet, group_direction, self.slipnet
        )
        group = Group(
            string=string,
            group_category=group_category,
            bond_facet=self.bond_facet,
            direction=group_direction,
            objects=ordered_objects,
            bonds=group_bonds,
        )
        self.instantiated_object = group
        string.groups.append(group)
        string.objects.append(group)
        for obj in ordered_objects:
            obj.enclosing_group = group
        return group

    # -- tree walks --------------------------------------------------------

    def leaf_walk(self, action: Any) -> None:
        """Scheme: leaf-walk — call *action* on every leaf (letter) image."""
        if self.is_letter_image:
            action(self)
        else:
            plato_left = self.slipnet.nodes.get("plato-left")
            ordered = list(reversed(self.sub_images)) if self.direction is plato_left else self.sub_images
            for sub in ordered:
                sub.leaf_walk(action)

    def postorder_interior_walk(self, action: Any) -> None:
        """Scheme: postorder-interior-walk — call *action* on every interior
        (group) image, children first."""
        if self.is_letter_image:
            return
        plato_left = self.slipnet.nodes.get("plato-left")
        ordered = list(reversed(self.sub_images)) if self.direction is plato_left else self.sub_images
        for sub in ordered:
            sub.postorder_interior_walk(action)
        action(self)

    # -- private -----------------------------------------------------------

    def _letter_to_singleton_group(self) -> None:
        """Scheme: letter->singleton-group.

        Promotes a letter image to a singleton group image containing one
        sub-image that is a copy of this letter.
        """
        sub_image = self.copy()
        letter_category = self.slipnet.nodes.get("plato-letter-category")
        identity = self.slipnet.nodes.get("plato-identity")
        plato_right = self.slipnet.nodes.get("plato-right")
        plato_one = self.slipnet.nodes.get("plato-one")

        self.bond_facet = letter_category
        self.letter_relation = identity
        self.length_relation = identity
        self.direction = plato_right
        self.sub_images = [sub_image]
        # new-length plato-one is a no-op identity case, but we call it for
        # consistency with the Scheme version.
        if plato_one is not None:
            try:
                self.new_length(plato_one)
            except ImageFailure:
                pass  # identity case

    # -- compatibility: old Image.matches() --------------------------------

    def matches(self, other: Image) -> bool:
        """Structural equivalence check (preserves old stub interface).

        Compares two images recursively: same start_letter, same bond_facet,
        same direction, same number and structure of sub-images.
        """
        if self.start_letter is not other.start_letter:
            return False
        if self.bond_facet is not other.bond_facet:
            return False
        if self.direction is not other.direction:
            return False
        if len(self.sub_images) != len(other.sub_images):
            return False
        return all(
            s.matches(o) for s, o in zip(self.sub_images, other.sub_images)
        )

    def __repr__(self) -> str:
        letter_name = getattr(self.start_letter, "short_name", "?")
        if self.is_letter_image:
            return f"Image(letter={letter_name})"
        n = len(self.sub_images)
        dir_name = getattr(self.direction, "short_name", "?")
        return f"Image(letter={letter_name}, dir={dir_name}, subs={n})"


# ---------------------------------------------------------------------------
# StringImage — image for an entire workspace string
# ---------------------------------------------------------------------------

class StringImage:
    """Image for an entire workspace string.

    Mirrors the Scheme ``make-string-image`` closure. The string image wraps
    the individual images of the string's constituent (top-level) objects and
    provides bulk transformation operations.

    Parameters
    ----------
    string : Any
        The WorkspaceString this image belongs to.
    direction : SlipnetNode
        Initial direction (typically plato-right).
    slipnet : Slipnet
        Reference to the slipnet.
    """

    def __init__(
        self,
        string: Any,
        direction: SlipnetNode,
        slipnet: Slipnet,
    ) -> None:
        self.string = string
        self.direction = direction
        self.slipnet = slipnet

        # Verbatim mode: when a verbatim rule is applied, the sub-images are
        # replaced wholesale with synthesized letter images.
        self._verbatim_images: list[Image] | None = None
        self._verbatim: bool = False

    # -- sub-image access --------------------------------------------------

    def get_sub_images(self) -> list[Image]:
        """Scheme: get-sub-images.

        In verbatim mode returns the synthesized images; otherwise returns the
        images of the string's top-level (constituent) objects.
        """
        if self._verbatim:
            return self._verbatim_images or []
        return self._constituent_images()

    def get_ordered_sub_images(self) -> list[Image]:
        """Scheme: get-ordered-sub-images — sub-images in direction order."""
        plato_right = self.slipnet.nodes.get("plato-right")
        subs = self.get_sub_images()
        if self.direction is plato_right:
            return subs
        return list(reversed(subs))

    # -- generation --------------------------------------------------------

    def generate(self) -> list[SlipnetNode]:
        """Scheme: generate — generate all sub-images and return flat letter list."""
        result: list[SlipnetNode] = []
        for img in self.get_ordered_sub_images():
            result.extend(img.generate())
        return result

    # -- reset -------------------------------------------------------------

    def reset(self) -> None:
        """Scheme: reset — restore original state."""
        self._verbatim = False
        plato_right = self.slipnet.nodes.get("plato-right")
        self.direction = plato_right  # type: ignore[assignment]
        for img in self.get_sub_images():
            img.reset()

    # -- bulk transformations ----------------------------------------------

    def new_start_letter(self, arg: SlipnetNode | None) -> None:
        """Apply new_start_letter to every sub-image."""
        for img in self.get_sub_images():
            img.new_start_letter(arg)

    def new_alpha_position_category(self, arg: SlipnetNode | None) -> None:
        """Scheme: new-alpha-position-category on string-image delegates to
        new_start_letter for each sub-image (matching the Scheme source)."""
        for img in self.get_sub_images():
            img.new_start_letter(arg)

    def new_length(self, arg: SlipnetNode | None) -> None:
        """Scheme: new-length on a string-image always fails."""
        raise ImageFailure("new_length: not supported on string images")

    def reverse_direction(self) -> None:
        """Reverse the string-image direction."""
        self.direction = inverse(self.direction, self.slipnet)

    def reverse_medium(self, medium: SlipnetNode | None) -> None:
        """Scheme: reverse-medium on a string-image."""
        letter_category = self.slipnet.nodes.get("plato-letter-category")
        length_node = self.slipnet.nodes.get("plato-length")

        if medium is letter_category:
            letters = [sub.get_letter() for sub in self.get_sub_images()]
            self.replace_all("new_start_letter", list(reversed(letters)))
        elif medium is length_node:
            lengths = [sub.get_length() for sub in self.get_sub_images()]
            self.replace_all("new_length", list(reversed(lengths)))

    def replace_all(self, method_name: str, new_args: list) -> None:
        """Apply method_name to each sub-image with the corresponding arg."""
        for img, arg in zip(self.get_sub_images(), new_args):
            getattr(img, method_name)(arg)

    def new_appearance(self, letter_categories: list[SlipnetNode]) -> None:
        """Scheme: new-appearance — set verbatim letter images."""
        self._verbatim_images = [
            make_letter_image(lc, self.slipnet) for lc in letter_categories
        ]
        plato_right = self.slipnet.nodes.get("plato-right")
        self.direction = plato_right  # type: ignore[assignment]
        self._verbatim = True

    def get_length(self) -> SlipnetNode | None:
        """Platonic length of the string image (number of sub-images)."""
        return number_to_platonic_number(len(self.get_sub_images()), self.slipnet)

    # -- walk helpers ------------------------------------------------------

    def do_walk(self, walk_method: str, action: Any) -> None:
        """Scheme: do-walk — call a walk method on each ordered sub-image."""
        for img in self.get_ordered_sub_images():
            getattr(img, walk_method)(action)

    # -- disallowed operations on string images ----------------------------

    def letter(self) -> None:
        raise ImageFailure("letter: not supported on string images")

    def group(self) -> None:
        raise ImageFailure("group: not supported on string images")

    # -- private -----------------------------------------------------------

    def _constituent_images(self) -> list[Image]:
        """Get images from the string's constituent (top-level) objects.

        Constituent objects are sorted by left position, excluding those
        enclosed in a group. Each must have a ``get_image()`` method or an
        ``image`` attribute.
        """
        # Walk the string left to right and, at each position, take the widest
        # built object starting there.  This yields a partition that covers every
        # position exactly once.
        #
        # Selecting on ``enclosing_group is None`` alone is not safe: when two
        # groups claim the same member the later one wins the back-pointer, so the
        # earlier group *and* its now-orphaned members all look top-level and the
        # image generates those letters twice — "iijjkk" came out as
        # "iiijjkdijjkd".  A positional partition cannot double-count whatever
        # state the ``enclosing_group`` bookkeeping is in.
        top_level: list[Any] = []
        position = 0
        letters_end = max(
            (o.right_string_pos for o in self.string.objects if not _is_group(o)),
            default=-1,
        )
        while position <= letters_end:
            candidates = [
                o
                for o in self.string.objects
                if o.left_string_pos == position
                and o.right_string_pos <= letters_end
                and (not _is_group(o) or getattr(o, "is_built", True))
            ]
            if not candidates:
                position += 1
                continue
            widest = max(candidates, key=lambda o: o.right_string_pos)
            top_level.append(widest)
            position = widest.right_string_pos + 1

        images: list[Image] = []
        for obj in top_level:
            img = getattr(obj, "image", None)
            if img is None and hasattr(obj, "get_image"):
                img = obj.get_image()
            if img is None:
                # Every object needs an image, not just the ones a rule happens
                # to transform — otherwise ``generate`` returns only the changed
                # letters (applying "change rightmost to successor" to abc gave
                # "d" instead of "abd").
                img = self._make_image_for(obj)
            if img is not None:
                obj.image = img
                images.append(img)
        return images

    def _make_image_for(self, obj: Any) -> Image | None:
        """Build a fresh image mirroring *obj*'s current appearance.

        Sub-images are cached back onto their objects so the image tree is
        *shared*: a rule that transforms a letter nested inside a group has to
        mutate the very image the enclosing group will generate from, otherwise
        the change is silently lost (applying "change rightmost letter to
        successor" to iijjkk returned iijjkk).
        """
        sub_objects = getattr(obj, "objects", None)
        if not sub_objects:
            letter_category = getattr(obj, "letter_category", None)
            if letter_category is None:
                return None
            img = make_letter_image(letter_category, self.slipnet)
            obj.image = img
            return img

        sub_images = []
        for o in sub_objects:
            sub = self._make_image_for(o)
            if sub is None:
                return None
            o.image = sub
            sub_images.append(sub)
        first = sub_images[0]
        return make_group_image(
            self.slipnet,
            first.start_letter,
            getattr(obj, "bond_facet", None),
            _bond_relation(obj, "plato-letter-category"),
            _bond_relation(obj, "plato-length"),
            # Physical left-to-right order, *not* the group's bonding direction:
            # ``Group.objects`` is stored left-to-right, so an image seeded with a
            # left-going group's direction would generate its letters reversed and
            # an untouched image of "abc" came out as "acb" — making every rule
            # look broken to ``currently_works``.  A direction-reversal change
            # flips this to left, which is what produces cba.
            self.slipnet.nodes.get("plato-right"),
            sub_images,
        )

    def __repr__(self) -> str:
        dir_name = getattr(self.direction, "short_name", "?")
        n = len(self.get_sub_images())
        return f"StringImage(dir={dir_name}, subs={n})"


# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------

def _bond_relation(group: Any, facet_name: str) -> SlipnetNode | None:
    """The group's bond category, if its bonds run along *facet_name*."""
    facet = getattr(group, "bond_facet", None)
    if facet is None or getattr(facet, "name", "") != facet_name:
        return None
    bonds = getattr(group, "group_bonds", None) or []
    return bonds[0].bond_category if bonds else None


def make_letter_image(letter_category: SlipnetNode, slipnet: Slipnet) -> Image:
    """Scheme: make-letter-image.

    Creates a simple letter image (no sub-images, no bond-facet, no relations).
    """
    return Image(
        slipnet=slipnet,
        start_letter=letter_category,
    )


def make_group_image(
    slipnet: Slipnet,
    initial_letter_category: SlipnetNode,
    bond_facet: SlipnetNode,
    letter_relation: SlipnetNode | None,
    length_relation: SlipnetNode | None,
    direction: SlipnetNode,
    sub_images: list[Image],
) -> Image:
    """Create a group image with the given parameters.

    Mirrors the ``make-image`` call in groups.ss where a group's image is
    constructed from its constituent objects' images.
    """
    return Image(
        slipnet=slipnet,
        start_letter=initial_letter_category,
        bond_facet=bond_facet,
        letter_relation=letter_relation,
        length_relation=length_relation,
        direction=direction,
        sub_images=sub_images,
    )


def make_string_image(
    string: Any, direction: SlipnetNode, slipnet: Slipnet
) -> StringImage:
    """Scheme: make-string-image."""
    return StringImage(string=string, direction=direction, slipnet=slipnet)


def _bonds_between(
    objects: list, bond_category: Any, bond_facet: Any, direction: Any, slipnet: Any
) -> list:
    """Bonds joining each consecutive pair of *objects*, all of one kind.

    Used when a group is instantiated from an image (``instantiate-as-group``): the
    group's reading already fixes the category, facet and direction, so the bonds it
    implies are determined rather than discovered.
    """
    from server.engine.bonds import Bond

    if bond_category is None or bond_facet is None or len(objects) < 2:
        return []

    bonds = []
    for left, right in zip(objects, objects[1:]):
        from_descriptor = _descriptor_of(left, bond_facet)
        to_descriptor = _descriptor_of(right, bond_facet)
        if from_descriptor is None or to_descriptor is None:
            return []
        bond = Bond(
            from_object=left,
            to_object=right,
            bond_category=bond_category,
            bond_facet=bond_facet,
            from_descriptor=from_descriptor,
            to_descriptor=to_descriptor,
            direction=direction,
        )
        bonds.append(bond)
    return bonds


def _descriptor_of(obj: Any, facet: Any) -> Any:
    """The descriptor *obj* carries along *facet*, or ``None``.

    A bond relates two objects along one facet, so it needs each side's descriptor for
    that facet — the letter-category for a letter-category bond, the length for a
    length bond.
    """
    for description in obj.get_all_descriptions():
        if getattr(description, "description_type", None) is facet:
            return getattr(description, "descriptor", None)
    return None
