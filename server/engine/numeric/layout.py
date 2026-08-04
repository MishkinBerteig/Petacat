"""Contiguous layouts for the engine's numeric state.

Everything the numeric substrate computes is expressed here as flat arrays of
scalars, deliberately divorced from the object graphs that own them.  Two things
motivate that, and the second is the one that decides the shape of this module.

The first is ordinary: a backend cannot vectorise over ``SlipnetNode`` instances,
so *something* has to flatten them.

The second is that the Slipnet is going to get very much larger.  The Phase 0 plan
sizes this work for a Slipnet growing toward ~300,000 nodes — LLM-vocabulary scale
— at which point sparse activation spreading is the dominant numeric cost and the
object graph is no longer a viable representation at all: 300,000 ``SlipnetNode``
instances plus a million ``SlipnetLink`` instances is gigabytes of Python objects
before any activation has been spread.  The layouts below are therefore designed
to be the *primary* representation, with ``from_slipnet``/``apply_to_slipnet``
being an adapter for today's 59-node object graph rather than the intended
long-term route in.  ``synthetic.py`` builds these structures directly, with no
object graph anywhere, which is what a 300,000-node Slipnet will do.

Why the edge list is destination-major
--------------------------------------
The reference implementation spreads *from* each source::

    for node in nodes:                      # slipnet.ss:383
        if node.activation >= threshold:
            for link in node.outgoing_links:
                link.to_node.activation_buffer += round(w * node.activation)

which is a scatter: many sources write into the same destination buffer.  On a GPU
a scatter needs atomics, and atomics make the summation order non-deterministic,
which is precisely what a reproducible cognitive architecture cannot have.

Grouping the same edges by *destination* turns the scatter into a gather plus a
segmented reduction — each destination node reads its own incoming edges and
writes its own buffer slot exactly once.  No atomics, no contention, and a fixed
summation order that is identical on every run and on every backend.

The reordering is safe because the per-edge contributions are *integers*
(``round`` is applied per edge, not to the sum), and a sum of at most a few
thousand integers each ≤ 100 is exact in both float64 and float32.  Summing them
in a different order therefore gives the same answer bit-for-bit.  See
``docs`` in ``python_backend.spread`` for where a genuine ordering difference does
remain, and how large it is.

Why the weights are static
--------------------------
``SlipnetLink.intrinsic_degree_of_association`` uses the *intrinsic* link length
always, never the shrunk one (slipnet.ss:330-333), so it depends on nothing that
changes during a run.  The entire sparse matrix is therefore constant, built once
and reused for every update cycle for the life of the Slipnet.  That is what makes
a CSR layout the right choice rather than merely a convenient one: there is no
rebuild cost to amortise.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Sequence

if TYPE_CHECKING:  # pragma: no cover - typing only
    from server.engine.slipnet import Slipnet


# ---------------------------------------------------------------------------
# Activation constants
#
# Scheme: ``%max-activation%`` (slipnet.ss:20) and
# ``%full-activation-threshold%`` (slipnet.ss:22).  They live here, in the module
# every backend and ``slipnet.py`` already imports, because the probabilistic
# jump's eligibility window is stated in four places — the object-graph loop and
# the three backend ``jump_candidates`` — and four copies of a bare ``50.0`` is
# exactly how the backends would drift apart.
# ---------------------------------------------------------------------------

#: ``%max-activation%``: the ceiling, and what "fully active" means exactly.
MAX_ACTIVATION = 100.0

#: ``%full-activation-threshold%``: the floor of ``above-threshold?``, and hence
#: of ``partially-active?`` (slipnet.ss:397-404).
FULL_ACTIVATION_THRESHOLD = 50.0


# ---------------------------------------------------------------------------
# Slipnet
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SlipnetTopology:
    """The static half of the Slipnet: shape, decay rates, and the sparse graph.

    Immutable for the life of a run.  A backend uploads it once (``open_slipnet``)
    and never touches it again, which is why the mutable state below is a separate
    object rather than fields on this one.
    """

    #: Node names in index order.  Kept so that a backend-side result can be
    #: matched back to the object graph without relying on dictionary order
    #: twice; also what makes a synthetic topology inspectable.
    node_names: tuple[str, ...]

    #: ``1 - (conceptual_depth/100) ** (update_cycle_length/15)`` per node,
    #: precomputed by ``SlipnetNode.compute_rate_of_decay``.
    decay_rate: tuple[float, ...]

    conceptual_depth: tuple[float, ...]

    #: CSR row pointers over *destinations*: incoming edges of node ``d`` are
    #: ``[in_indptr[d], in_indptr[d+1])``.  Length ``n_nodes + 1``.
    in_indptr: tuple[int, ...]

    #: Source node index of each incoming edge, grouped by destination.
    in_source: tuple[int, ...]

    #: ``intrinsic_degree_of_association / 100`` per edge — the association
    #: fraction, pre-divided so the per-cycle work is one multiply.
    in_weight: tuple[float, ...]

    #: Destination node index of each edge, in the same order as ``in_source``.
    #: Redundant with ``in_indptr`` but lets a backend that reduces with a
    #: bincount-style primitive skip reconstructing it every cycle.
    in_dest: tuple[int, ...]

    @property
    def n_nodes(self) -> int:
        return len(self.node_names)

    @property
    def n_edges(self) -> int:
        return len(self.in_source)

    @classmethod
    def from_slipnet(cls, slipnet: Slipnet) -> SlipnetTopology:
        """Flatten a live ``Slipnet`` object graph.

        Node order is dictionary insertion order, which is seed-data order and is
        stable across runs; the reference implementation iterates the same
        dictionary, so index ``i`` here is the ``i``-th node the reference visits.
        That correspondence is what lets the two paths be compared element-wise.
        """
        names = tuple(slipnet.nodes.keys())
        index = {name: i for i, name in enumerate(names)}
        nodes = list(slipnet.nodes.values())

        # Collect edges source-major first, because that is how the object graph
        # stores them, then bucket them by destination.
        by_dest: list[list[tuple[int, float]]] = [[] for _ in names]
        for src_i, node in enumerate(nodes):
            for link in node.outgoing_links:
                dest_i = index.get(link.to_node.name)
                if dest_i is None:  # pragma: no cover - links always resolve
                    continue
                by_dest[dest_i].append(
                    (src_i, link.intrinsic_degree_of_association() / 100.0)
                )

        indptr = [0]
        source: list[int] = []
        weight: list[float] = []
        dest: list[int] = []
        for dest_i, edges in enumerate(by_dest):
            for src_i, w in edges:
                source.append(src_i)
                weight.append(w)
                dest.append(dest_i)
            indptr.append(len(source))

        return cls(
            node_names=names,
            decay_rate=tuple(n._rate_of_decay for n in nodes),
            conceptual_depth=tuple(float(n.conceptual_depth) for n in nodes),
            in_indptr=tuple(indptr),
            in_source=tuple(source),
            in_weight=tuple(weight),
            in_dest=tuple(dest),
        )


@dataclass
class SlipnetState:
    """The mutable half: what one update cycle reads and writes.

    Plain Python lists rather than a backend array type, because this is the
    interchange format between the engine's object graph and whichever backend is
    in use, and the pure-Python backend must work with no third-party package
    installed at all.  A backend that keeps its own device-side copy converts on
    ``open_slipnet`` and only materialises back into these lists when the engine
    asks for them.
    """

    activation: list[float]
    buffer: list[float]
    frozen: list[bool]
    clamp_remaining: list[int]

    @classmethod
    def from_slipnet(cls, slipnet: Slipnet) -> SlipnetState:
        nodes = list(slipnet.nodes.values())
        return cls(
            activation=[n.activation for n in nodes],
            buffer=[n.activation_buffer for n in nodes],
            frozen=[n.frozen for n in nodes],
            clamp_remaining=[n.clamp_cycles_remaining for n in nodes],
        )

    def apply_to_slipnet(self, slipnet: Slipnet) -> None:
        """Write this state back onto the object graph.

        ``activation`` and ``activation_buffer`` are always written; ``frozen``
        and ``clamp_cycles_remaining`` are written too, because ``tick_clamps`` is
        part of the substrate and a clamp that expired on the backend has to
        expire on the node as well.
        """
        for node, act, buf, frz, rem in zip(
            slipnet.nodes.values(),
            self.activation,
            self.buffer,
            self.frozen,
            self.clamp_remaining,
        ):
            node.activation = act
            node.activation_buffer = buf
            node.frozen = frz
            node.clamp_cycles_remaining = rem


# ---------------------------------------------------------------------------
# Themespace
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ThemeLayout:
    """Theme clusters padded into a rectangular ``(n_clusters, n_slots)`` grid.

    Clusters hold between two and four themes today, so a ragged structure would
    cost more in bookkeeping than the padding costs in arithmetic.  Padding slots
    are marked invalid and contribute nothing; the alternative — a CSR over
    clusters — buys nothing at this aspect ratio and would obscure the fact that
    the intra-cluster dynamics are dense all-pairs within a cluster.

    Clusters are mutually independent, which is the property the vectorisation
    rests on: the substrate walks *slots* sequentially and *clusters* in parallel.
    """

    n_clusters: int
    n_slots: int
    #: ``valid[c * n_slots + s]`` — whether slot ``s`` of cluster ``c`` is a real
    #: theme rather than padding.
    valid: tuple[bool, ...]
    #: Number of real themes in each cluster.  Enters the sigmoid's ``alpha`` as
    #: ``1 / n_relations``, so it is a per-cluster constant, not just a count.
    n_relations: tuple[int, ...]

    @classmethod
    def from_themespace(cls, themespace: Any) -> ThemeLayout:
        clusters = themespace.clusters
        n_slots = max((len(c.themes) for c in clusters), default=0)
        valid: list[bool] = []
        for cluster in clusters:
            count = len(cluster.themes)
            valid.extend(True for _ in range(count))
            valid.extend(False for _ in range(n_slots - count))
        return cls(
            n_clusters=len(clusters),
            n_slots=n_slots,
            valid=tuple(valid),
            n_relations=tuple(max(1, len(c.themes)) for c in clusters),
        )


@dataclass
class ThemeState:
    """One signed activation per theme slot, row-major over clusters.

    §4.2: a theme's activation ranges between -100 and +100.  Scheme:
    ``make-generic-theme`` (``themes.ss:574``).
    """

    activation: list[float]
    #: Per-slot freeze (a clamped theme is skipped entirely).
    frozen: list[bool]
    #: Per-cluster freeze (a frozen cluster spreads no activation at all).
    cluster_frozen: list[bool]

    @classmethod
    def from_themespace(cls, themespace: Any, layout: ThemeLayout) -> ThemeState:
        act: list[float] = []
        frz: list[bool] = []
        for cluster in themespace.clusters:
            for theme in cluster.themes:
                act.append(theme.activation)
                frz.append(theme.frozen)
            for _ in range(layout.n_slots - len(cluster.themes)):
                act.append(0.0)
                # Padding is frozen so that every backend skips it by the same
                # rule it already applies to a clamped theme, rather than needing
                # a second exclusion test in the inner loop.
                frz.append(True)
        return cls(
            activation=act,
            frozen=frz,
            cluster_frozen=[c.frozen for c in themespace.clusters],
        )

    def apply_to_themespace(self, themespace: Any, layout: ThemeLayout) -> None:
        for c, cluster in enumerate(themespace.clusters):
            base = c * layout.n_slots
            for s, theme in enumerate(cluster.themes):
                theme.activation = self.activation[base + s]


@dataclass(frozen=True)
class ThemeParams:
    """The coefficients ``ThemeCluster.spread_activation`` reads from metadata.

    Hoisted out of the inner loop deliberately: the reference re-reads all seven
    of them from the ``MetadataProvider`` once per *theme*, which at 81 themes is
    567 dictionary lookups per update cycle for values that cannot change during
    a run.
    """

    decay: float
    neg_to_neg: float
    neg_to_pos: float
    pos_to_neg: float
    pos_to_pos: float
    self_weight: float
    spread_amount: float
    sensitivity: float

    @classmethod
    def from_metadata(cls, meta: Any) -> ThemeParams:
        return cls(
            decay=meta.get_param("theme_decay_amount", 25),
            neg_to_neg=meta.get_formula_coeff("theme_intra_cluster_neg_to_neg_weight"),
            neg_to_pos=meta.get_formula_coeff("theme_intra_cluster_neg_to_pos_weight"),
            pos_to_neg=meta.get_formula_coeff("theme_intra_cluster_pos_to_neg_weight"),
            pos_to_pos=meta.get_formula_coeff("theme_intra_cluster_pos_to_pos_weight"),
            self_weight=meta.get_formula_coeff("theme_intra_cluster_self_weight"),
            spread_amount=meta.get_param("theme_spread_amount", 20),
            sensitivity=meta.get_formula_coeff("theme_net_effect_default_sensitivity"),
        )


# ---------------------------------------------------------------------------
# Workspace object values
# ---------------------------------------------------------------------------

#: ``_string_type()`` returns one of these; the arithmetic that combines
#: unhappiness and salience branches on it, so it travels as a small integer
#: code rather than a string.  Anything unrecognised maps to ``OTHER``, which
#: reproduces the reference's ``else`` branch.
STRING_INITIAL = 0
STRING_MODIFIED = 1
STRING_TARGET = 2
STRING_ANSWER = 3
STRING_OTHER = 4

_STRING_TYPE_CODES = {
    "initial": STRING_INITIAL,
    "modified": STRING_MODIFIED,
    "target": STRING_TARGET,
    "answer": STRING_ANSWER,
}


def string_type_code(name: str | None) -> int:
    return _STRING_TYPE_CODES.get(name or "", STRING_OTHER)


@dataclass
class ObjectValueBatch:
    """One string's objects, reduced to the scalars the combination stage needs.

    The object-value update splits cleanly into an irregular part and an
    arithmetic part.  Raw importance walks a description list; intra-string
    unhappiness walks incident bonds and an enclosing group; inter-string
    unhappiness walks bridges.  All three are pointer-chasing over structures that
    change shape every codelet, and none of them vectorises.

    What follows is pure arithmetic on four scalars per object — average
    unhappiness and three saliences — and *that* is what this batch carries.
    Splitting there rather than trying to vectorise the traversals is what keeps
    the change to ``workspace.py`` a reordering of existing calls rather than a
    reimplementation of them.

    The split is sound because no step reads another object's unhappiness or
    salience: ``calculate_local_support`` counts description *types* on
    neighbours, not their strengths, and intra-string unhappiness reads bond and
    group *strengths*, which the previous phase has already fixed.

    Relative importance is an *input* here, not an output, and that is a
    correction rather than a design preference.  It is ``round(100 * raw / Σraw)``,
    a ratio whose numerator and denominator are sums of decayed activations and
    can legitimately be on the order of 1e-48 — a magnitude float32 cannot
    represent at all, and which MLX flushes to zero even in a float64 graph
    because it routes Python scalars through float32.  The ratio is perfectly
    well-defined; only the magnitudes are not.  Computing it on the host in
    float64, as the reference already does in its own separate pass
    (workspace-strings.ss:322-338, step 2), keeps every value the backends see
    inside [0, 100] and makes relative importance bit-identical on every backend
    by construction.
    """

    #: ``round(100 * raw_importance / Σ raw_importance)``, computed by the caller
    #: in float64 — an input here rather than an output, for the reason above.
    relative_importance: list[int]
    intra_unhappiness: list[float]
    horizontal_unhappiness: list[float]
    vertical_unhappiness: list[float]
    salience_clamped: list[bool]
    string_type: list[int]
    justify_mode: list[bool]
    #: Inter-string salience as it stands *before* the update.  A ``modified``
    #: object never has its vertical salience recomputed, and a non-justifying
    #: ``target`` object never has its horizontal salience recomputed, so those
    #: slots must survive the round trip.  Carrying the old value and writing it
    #: back unchanged is equivalent to the reference's "don't touch it", and it
    #: keeps the outputs rectangular, which a ``None`` sentinel would not.
    prev_horizontal_salience: list[float]
    prev_vertical_salience: list[float]

    # Outputs, filled by the backend.  Every one of these is an *integer* in the
    # reference, because each is the result of a bare ``round()``; the backends
    # return Python ints so the object graph keeps the types it had, and so
    # element-wise agreement between backends can be asserted exactly rather than
    # within a tolerance.
    average_unhappiness: list[int] = field(default_factory=list)
    intra_salience: list[int] = field(default_factory=list)
    horizontal_salience: list[int] = field(default_factory=list)
    vertical_salience: list[int] = field(default_factory=list)
    average_salience: list[int] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.relative_importance)


def relative_importances(objects: Sequence[Any]) -> list[int]:
    """Step 2 of the object-value update, on the host and in float64.

    Character for character the reference's own two lines
    (``WorkspaceString.update_object_values``).  Kept out of the backends for the
    dynamic-range reason given on ``ObjectValueBatch``.
    """
    total_raw = sum(o.raw_importance for o in objects)
    if total_raw == 0:
        # Scheme: ``update-all-relative-importances`` (workspace-strings.ss:326-329)
        # spreads importance *evenly* when nothing is described yet, rather than
        # leaving every object at zero.  The difference is visible downstream: the
        # weighted averages that read these weights return 0 when they all vanish
        # (utilities.ss:388-392), which reads as "no unhappiness" rather than "no
        # information".
        n = len(objects)
        return [round(100.0 / n)] * n if n else []
    return [round(100.0 * o.raw_importance / total_raw) for o in objects]


def gather_object_values(objects: Sequence[Any]) -> ObjectValueBatch:
    """Read the combination stage's inputs off a string's objects."""
    return ObjectValueBatch(
        relative_importance=[o.relative_importance for o in objects],
        intra_unhappiness=[o.intra_string_unhappiness for o in objects],
        horizontal_unhappiness=[
            o.inter_string_unhappiness["horizontal"] for o in objects
        ],
        vertical_unhappiness=[o.inter_string_unhappiness["vertical"] for o in objects],
        salience_clamped=[o.salience_clamped for o in objects],
        string_type=[string_type_code(o._string_type()) for o in objects],
        justify_mode=[o._justify_mode() for o in objects],
        prev_horizontal_salience=[o.salience["horizontal_inter"] for o in objects],
        prev_vertical_salience=[o.salience["vertical_inter"] for o in objects],
    )


def scatter_object_values(batch: ObjectValueBatch, objects: Sequence[Any]) -> None:
    """Write the combination stage's outputs back onto the objects."""
    for i, obj in enumerate(objects):
        obj.average_unhappiness = batch.average_unhappiness[i]
        obj.salience["intra"] = batch.intra_salience[i]
        obj.salience["horizontal_inter"] = batch.horizontal_salience[i]
        obj.salience["vertical_inter"] = batch.vertical_salience[i]
        obj.salience["average"] = batch.average_salience[i]
