"""Complete, restorable capture of a run's state (WP3.4, fixes defect D1).

Normal mode records the whole of Petacat at the two Run boundaries, and its promise is
that a recorded Run can be **re-executed**: reload the start state, run, and arrive at
the recorded end state.  That promise needs a capture that is genuinely complete, and
nothing before this module was.

What was there instead
----------------------
``serialize_workspace_state`` is documented "for display": built structures as counts,
no proposal levels, no descriptions, no object identity.  ``serialize_coderack_state``
dropped every object-valued codelet argument outright —
``{k: str(v) for k, v in c.arguments.items() if not hasattr(v, '__dict__')}`` — and
those arguments are not incidental: a live rack carries ``Bond``, ``Bridge``, ``Rule``
and ``SlipnetNode`` values in them, so a restored rack would have held evaluators and
builders pointing at nothing.  There was no coderack or workspace restore at all, and
the four ``restore_*`` functions that did exist were called from nowhere.  The largest
write in the system could not be read back.

Why the capture is reflective
-----------------------------
Fields are read from ``vars(obj)`` rather than enumerated per class.  Enumeration is
how the display serializer rotted: a field added to ``Bond`` is simply absent from a
hand-written list, and nothing fails — the capture just quietly stops being complete,
which is the one property this module exists to provide.  Reflection makes the default
"captured", so forgetting is not an available mistake.

Why identity is explicit
------------------------
The graph has cycles and cross-references everywhere: an object holds its bonds, each
bond holds its objects, a bridge joins objects in different strings, a group contains
objects that point back at the group, and a trace event holds the structures it
describes.  Structural serialisation cannot express that.  So every graph object is
emitted once, into a flat table, and every reference to it becomes ``{"$ref": n}``.
Restoring is two passes — create the shells, then wire them — which is what makes
cycles fall out for free.

What is *not* captured, and why that is right
---------------------------------------------
Three kinds of thing are deliberately referenced rather than copied:

- **Slipnet nodes** appear as ``{"$node": "plato-a"}``.  A node's identity is its name
  and its structure comes from the metadata; only its *mutable* state — activation,
  buffer, frozen, clamp — is state, and that is captured separately by name.  Copying
  the 59 nodes and their 202 links into every capture would store the configuration in
  every run's record.
- **Workspace strings** appear as ``{"$string": "initial"}`` when referenced from
  elsewhere, because there are exactly four and their roles name them.
- **Environment** — the ``MetadataProvider``, the ``Slipnet``, the back-reference from
  a string to its ``Workspace``, the ``RNG`` the coderack holds — is re-linked on
  restore rather than stored.  These are not run state; they are the things the run is
  running inside.

Format
------
An id-based graph, JSON-serialisable throughout: inspectable, diffable, versionable
via ``FORMAT_VERSION``, and directly renderable by the review UI (WP3.9) without a
second representation.
"""

from __future__ import annotations

import base64
import pickle
from typing import Any

from server.engine.bonds import Bond
from server.engine.bridges import Bridge
from server.engine.coderack import Codelet
from server.engine.concept_mappings import ConceptMapping
from server.engine.descriptions import Description
from server.engine.groups import Group
from server.engine.images import Image, StringImage
from server.engine.memory import AnswerDescription, SnagDescription
from server.engine.rules import (
    ExtrinsicChangeDescription,
    IntrinsicChangeDescription,
    Rule,
    RuleChange,
    RuleClause,
)
from server.engine.trace import AnswerEvent, ClampEvent, SnagEvent, TraceEvent
from server.engine.workspace import WorkspaceString
from server.engine.workspace_objects import Letter

FORMAT_VERSION = 1

#: Classes emitted into the reference table.  Anything else with a ``__dict__``
#: encountered during the walk is an error rather than a silent omission — a new
#: structure type must be added here deliberately, which is the point.
GRAPH_TYPES: tuple[type, ...] = (
    WorkspaceString,
    Letter,
    Group,
    Bond,
    Bridge,
    Description,
    Rule,
    RuleClause,
    RuleChange,
    IntrinsicChangeDescription,
    ExtrinsicChangeDescription,
    ConceptMapping,
    Image,
    StringImage,
    Codelet,
    TraceEvent,
    # The rich event types must be listed *individually*, not left to be covered by
    # their base class.  ``isinstance`` on capture matches the base, so capturing
    # worked; the reader keys on the concrete type *name*, so restoring did not.  The
    # effect was that any Run-end capture from a run that answered, snagged or clamped
    # could not be reloaded — which is nearly every interesting Normal run, and exactly
    # the capture reproducibility-by-re-execution depends on.
    AnswerEvent,
    ClampEvent,
    SnagEvent,
    AnswerDescription,
    SnagDescription,
)

_TYPES_BY_NAME = {cls.__name__: cls for cls in GRAPH_TYPES}

#: Fields that are environment rather than state.  Dropped on capture and re-linked on
#: restore; see the module docstring.
_ENVIRONMENT_FIELDS = frozenset({"slipnet", "meta", "workspace", "rng"})

#: The four Workspace strings, by the role that names them.
_STRING_ROLES = ("initial", "modified", "target", "answer")


class StateGraphError(RuntimeError):
    """The graph could not be captured or restored faithfully."""


# ─────────────────────────────────────────────────────────────────────────────
# Capture
# ─────────────────────────────────────────────────────────────────────────────


class _Writer:
    """Assigns each graph object a stable index and emits its fields once."""

    def __init__(self, strings: dict[int, str]) -> None:
        self._records: list[dict] = []
        self._index: dict[int, int] = {}
        #: ``id()`` of each Workspace string mapped to its role, so a reference to one
        #: from anywhere in the graph resolves by role instead of by index.
        self._strings = strings

    def ref(self, obj: Any) -> dict:
        """Return a reference to ``obj``, emitting it if this is the first sighting."""
        key = id(obj)
        if key in self._strings:
            return {"$string": self._strings[key]}
        if key in self._index:
            return {"$ref": self._index[key]}

        # Reserve the index *before* walking the fields.  An object that reaches
        # itself — a group inside its own object list, a bond whose objects hold it —
        # must find the reservation rather than recurse forever.
        index = len(self._records)
        self._index[key] = index
        record: dict = {"type": type(obj).__name__, "fields": {}}
        self._records.append(record)
        record["fields"] = {
            name: self.value(value)
            for name, value in vars(obj).items()
            if name not in _ENVIRONMENT_FIELDS
        }
        return {"$ref": index}

    def value(self, value: Any) -> Any:
        """Encode one field value."""
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        if isinstance(value, GRAPH_TYPES):
            return self.ref(value)
        if isinstance(value, (list, tuple)):
            return {"$list": [self.value(v) for v in value]}
        if isinstance(value, dict):
            # Keys are always strings or ints in this graph; values may be anything.
            return {"$dict": [[k, self.value(v)] for k, v in value.items()]}
        if hasattr(value, "name") and hasattr(value, "conceptual_depth"):
            # A SlipnetNode.  Duck-typed rather than imported to keep this module free
            # of a dependency it needs for one isinstance check.
            return {"$node": value.name}
        if hasattr(value, "from_node") and hasattr(value, "link_type"):
            # A SlipnetLink.  Configuration, like the nodes it joins, and identified by
            # the same triple the metadata defines it with.  A concept-mapping holds
            # one to record *why* two descriptors correspond, so it must come back as
            # the very link the Slipnet spreads along rather than a copy of it.
            return {
                "$link": [value.from_node.name, value.to_node.name, value.link_type]
            }
        raise StateGraphError(
            f"cannot capture a value of type {type(value).__name__!r}: it is neither a "
            f"scalar, a container, a Slipnet node, nor one of the graph types in "
            f"GRAPH_TYPES. Add it to GRAPH_TYPES if it is run state, or to "
            f"_ENVIRONMENT_FIELDS if it is not."
        )

    @property
    def records(self) -> list[dict]:
        return self._records


class _Reader:
    """Rebuilds the object graph in two passes: shells, then wiring."""

    def __init__(self, records: list[dict], slipnet: Any, strings: dict[str, Any]) -> None:
        self._records = records
        self._slipnet = slipnet
        self._strings = strings
        # Pass one: an empty instance per record.  ``__new__`` bypasses ``__init__``
        # deliberately — the constructors compute derived state from arguments this
        # module does not have, and every field is about to be assigned anyway.
        self._objects: list[Any] = []
        for record in records:
            cls = _TYPES_BY_NAME.get(record["type"])
            if cls is None:
                raise StateGraphError(
                    f"unknown graph type {record['type']!r}; the capture was written "
                    f"by a version of this module that knows a type this one does not"
                )
            self._objects.append(cls.__new__(cls))

    def build(self) -> list[Any]:
        """Pass two: fill in every field, resolving references."""
        for obj, record in zip(self._objects, self._records):
            for name, encoded in record["fields"].items():
                setattr(obj, name, self.value(encoded))
        return self._objects

    def value(self, encoded: Any) -> Any:
        if encoded is None or isinstance(encoded, (bool, int, float, str)):
            return encoded
        if isinstance(encoded, dict):
            if "$ref" in encoded:
                return self._objects[encoded["$ref"]]
            if "$string" in encoded:
                return self._strings[encoded["$string"]]
            if "$node" in encoded:
                return self._slipnet.nodes.get(encoded["$node"])
            if "$link" in encoded:
                return self._find_link(*encoded["$link"])
            if "$list" in encoded:
                return [self.value(v) for v in encoded["$list"]]
            if "$dict" in encoded:
                return {k: self.value(v) for k, v in encoded["$dict"]}
        raise StateGraphError(f"unrecognised encoded value: {encoded!r}")

    def _find_link(self, from_name: str, to_name: str, link_type: str) -> Any:
        """Recover the live link joining two nodes.

        Searched rather than indexed because a concept-mapping holding a link is
        uncommon and the Slipnet's outgoing lists are short. Returning ``None`` when
        the link is absent matches the field's own default: a mapping without a
        recorded link is an identity rather than a slippage.
        """
        node = self._slipnet.nodes.get(from_name)
        if node is None:
            return None
        for group in (
            node.category_links,
            node.instance_links,
            node.property_links,
            node.lateral_links,
            node.lateral_sliplinks,
        ):
            for link in group:
                if link.to_node.name == to_name and link.link_type == link_type:
                    return link
        return None

    def resolve(self, encoded: Any) -> Any:
        return self.value(encoded)


# ─────────────────────────────────────────────────────────────────────────────
# The whole run
# ─────────────────────────────────────────────────────────────────────────────


def capture_run_state(ctx: Any) -> dict:
    """The complete state of a run, as an id-based graph.

    Everything a Run needs to be resumed: the Workspace and every structure in it, the
    Coderack with its codelets *and their object-valued arguments*, Slipnet and
    Themespace activations, the Temporal Trace, Temperature, Episodic Memory, the RNG,
    and the identifier counters.

    The identifier counters travel with the state because they are not derivable from
    it: a structure that was proposed, took an id and then fizzled leaves nothing
    behind, so a restored run that recounted from the surviving objects would re-issue
    identifiers it had already used.
    """
    ws = ctx.workspace
    strings = {
        id(ws.initial_string): "initial",
        id(ws.modified_string): "modified",
        id(ws.target_string): "target",
    }
    if ws.answer_string is not None:
        strings[id(ws.answer_string)] = "answer"

    writer = _Writer(strings)

    workspace_state = {
        "strings": {
            role: {
                "text": getattr(ws, f"{role}_string").text,
                "objects": [writer.ref(o) for o in getattr(ws, f"{role}_string").objects],
                "bonds": [writer.ref(b) for b in getattr(ws, f"{role}_string").bonds],
                "groups": [writer.ref(g) for g in getattr(ws, f"{role}_string").groups],
                "justify_mode": getattr(ws, f"{role}_string").justify_mode,
                "string_type": getattr(ws, f"{role}_string").string_type,
                # ``image`` is built lazily, so a string that has not needed one
                # yet simply has no attribute rather than a null.
                "image": writer.value(
                    getattr(getattr(ws, f"{role}_string"), "image", None)
                ),
            }
            for role in _STRING_ROLES
            if getattr(ws, f"{role}_string", None) is not None
        },
        "top_bridges": [writer.ref(b) for b in ws.top_bridges],
        "bottom_bridges": [writer.ref(b) for b in ws.bottom_bridges],
        "vertical_bridges": [writer.ref(b) for b in ws.vertical_bridges],
        "top_rules": [writer.ref(r) for r in ws.top_rules],
        "bottom_rules": [writer.ref(r) for r in ws.bottom_rules],
        "clamped_rules": writer.value(list(ws.clamped_rules)),
    }

    coderack_state = {
        "bins": [[writer.ref(c) for c in b.codelets] for b in ctx.coderack.bins],
        "clamped_urgencies": dict(ctx.coderack.clamped_urgencies),
        "current_time": ctx.coderack.current_time,
        "max_size": ctx.coderack.max_size,
    }

    trace_state = {
        "events": [writer.ref(e) for e in ctx.trace.events],
        "within_clamp_period": ctx.trace.within_clamp_period,
        "within_snag_period": ctx.trace.within_snag_period,
        "last_clamp_time": ctx.trace.last_clamp_time,
        "last_unclamp_time": ctx.trace.last_unclamp_time,
        "clamp_count": ctx.trace.clamp_count,
        "snag_count": ctx.trace.snag_count,
        "last_significant_event_time": ctx.trace._last_significant_event_time,
    }

    memory_state = {
        "answers": [writer.ref(a) for a in ctx.memory.answers],
        "snags": [writer.ref(s) for s in ctx.memory.snags],
        "ids": ctx.memory.ids.snapshot(),
    }

    return {
        "format_version": FORMAT_VERSION,
        "problem": {
            "initial": ws.initial_string.text,
            "modified": ws.modified_string.text,
            "target": ws.target_string.text,
            "answer": ws.answer_string.text if ws.answer_string else None,
        },
        "runner": {
            "codelet_count": ctx.codelet_count,
            "justify_mode": ctx.justify_mode,
            "self_watching_enabled": ctx.self_watching_enabled,
            "spreading_activation_threshold": ctx.spreading_activation_threshold,
            "staleness_delay": ctx.staleness_delay,
        },
        # The run parameters this Run actually resolved.  A capture that omitted them
        # could only be re-executed against whatever the *global* configuration happened
        # to be at review time, so an inspector showed a Themespace the recorded Run
        # never had — a dominance margin edited since the Run would silently rewrite its
        # history.  The **resolved** set rather than the overrides, for the reason
        # migration 010 gives: overrides alone would be read against today's defaults,
        # so the record would change meaning whenever the configuration did.
        "parameters": dict(getattr(ctx.meta, "params", None) or {}),
        "ids": ctx.ids.snapshot(),
        "rng": _capture_rng(ctx.rng),
        "temperature": {
            "value": ctx.temperature.value,
            "clamped": ctx.temperature.clamped,
            "clamp_value": ctx.temperature.clamp_value,
            "clamp_cycles_remaining": ctx.temperature.clamp_cycles_remaining,
        },
        "slipnet": {
            name: [
                node.activation,
                node.activation_buffer,
                node.frozen,
                node.clamp_cycles_remaining,
            ]
            for name, node in ctx.slipnet.nodes.items()
        },
        "themespace": {
            "active_theme_types": list(ctx.themespace.active_theme_types),
            "clusters": [
                {
                    "theme_type": c.theme_type,
                    "dimension": c.dimension,
                    "frozen": c.frozen,
                    "themes": [
                        [t.relation, t.activation, t.frozen, t._net_input_buffer]
                        for t in c.themes
                    ],
                }
                for c in ctx.themespace.clusters
            ],
        },
        "workspace": workspace_state,
        "coderack": coderack_state,
        "trace": trace_state,
        "memory": memory_state,
        "graph": writer.records,
    }


def _capture_rng(rng: Any) -> dict:
    seed, call_count, internal = rng.get_state()
    return {
        "seed": seed,
        "call_count": call_count,
        # ``random.Random``'s internal state is a tuple of large integers with no
        # documented JSON form. Pickling it is the only faithful option, and it is the
        # one place in the capture that is not human-readable.
        "internal_state": base64.b64encode(pickle.dumps(internal)).decode("ascii"),
    }


def restore_run_state(runner: Any, state: dict) -> None:
    """Load a captured state into ``runner``, replacing whatever it held.

    ``runner`` must already have been through ``init_mcat`` for the same problem: that
    is what builds the Slipnet from metadata and the four Workspace strings this graph
    refers to by role and by name.
    """
    version = state.get("format_version")
    if version != FORMAT_VERSION:
        raise StateGraphError(
            f"state was written in format version {version}, this module reads "
            f"{FORMAT_VERSION}"
        )

    ctx = runner.ctx
    ws = ctx.workspace
    ws_state = state["workspace"]

    # A run that answered created an answer string during execution, so a runner
    # initialised for the same problem in discovery mode does not have one yet.  It has
    # to exist *before* the graph is read, because references to it were captured as
    # ``{"$string": "answer"}`` and resolve by role.  Built the way ``report_answer``
    # builds it; its fields are then overwritten from the capture like any other string.
    if "answer" in ws_state["strings"] and ws.answer_string is None:
        from server.engine.workspace import WorkspaceString

        ws.answer_string = WorkspaceString(
            ws_state["strings"]["answer"]["text"], ctx.slipnet, string_type="answer"
        )
        ws.answer_string.workspace = ws

    strings = {role: getattr(ws, f"{role}_string") for role in _STRING_ROLES
               if getattr(ws, f"{role}_string", None) is not None}
    reader = _Reader(state["graph"], ctx.slipnet, strings)
    reader.build()

    # -- Workspace ----------------------------------------------------
    for role, s_state in ws_state["strings"].items():
        target = strings.get(role)
        if target is None:
            continue
        target.text = s_state["text"]
        target.objects = [reader.resolve(o) for o in s_state["objects"]]
        target.bonds = [reader.resolve(b) for b in s_state["bonds"]]
        target.groups = [reader.resolve(g) for g in s_state["groups"]]
        target.justify_mode = s_state["justify_mode"]
        target.string_type = s_state["string_type"]
        image = reader.resolve(s_state["image"])
        # Re-link the environment the capture deliberately omitted.
        target.workspace = ws
        if image is not None:
            target.image = image
            image.string = target
            image.slipnet = ctx.slipnet

    ws.top_bridges = [reader.resolve(b) for b in ws_state["top_bridges"]]
    ws.bottom_bridges = [reader.resolve(b) for b in ws_state["bottom_bridges"]]
    ws.vertical_bridges = [reader.resolve(b) for b in ws_state["vertical_bridges"]]
    ws.top_rules = [reader.resolve(r) for r in ws_state["top_rules"]]
    ws.bottom_rules = [reader.resolve(r) for r in ws_state["bottom_rules"]]
    ws.clamped_rules = reader.resolve(ws_state["clamped_rules"])

    # -- Coderack -----------------------------------------------------
    ctx.coderack.clear()
    for bin_index, codelet_refs in enumerate(state["coderack"]["bins"]):
        for ref in codelet_refs:
            ctx.coderack.bins[bin_index].add(reader.resolve(ref))
    ctx.coderack._total_count = sum(len(b.codelets) for b in ctx.coderack.bins)
    ctx.coderack.clamped_urgencies = dict(state["coderack"]["clamped_urgencies"])
    ctx.coderack.current_time = state["coderack"]["current_time"]
    ctx.coderack.max_size = state["coderack"]["max_size"]
    ctx.coderack.rng = ctx.rng

    # -- Trace --------------------------------------------------------
    trace_state = state["trace"]
    ctx.trace.events = [reader.resolve(e) for e in trace_state["events"]]
    ctx.trace.within_clamp_period = trace_state["within_clamp_period"]
    ctx.trace.within_snag_period = trace_state["within_snag_period"]
    ctx.trace.last_clamp_time = trace_state["last_clamp_time"]
    ctx.trace.last_unclamp_time = trace_state["last_unclamp_time"]
    ctx.trace.clamp_count = trace_state["clamp_count"]
    ctx.trace.snag_count = trace_state["snag_count"]
    ctx.trace._last_significant_event_time = trace_state["last_significant_event_time"]

    # -- Memory -------------------------------------------------------
    ctx.memory.answers = [reader.resolve(a) for a in state["memory"]["answers"]]
    ctx.memory.snags = [reader.resolve(s) for s in state["memory"]["snags"]]
    ctx.memory.ids.restore(state["memory"]["ids"])

    # -- Slipnet ------------------------------------------------------
    for name, values in state["slipnet"].items():
        node = ctx.slipnet.nodes.get(name)
        if node is None:
            continue
        (node.activation, node.activation_buffer,
         node.frozen, node.clamp_cycles_remaining) = values

    # -- Themespace ---------------------------------------------------
    # A list, not a set: ``Themespace.thematic_pressure_on`` appends to it, and
    # restoring it as a set left a run that later turned thematic pressure on
    # raising ``'set' object has no attribute 'append'`` — well after the restore,
    # and only on runs that got as far as clamping a negative theme pattern.
    ctx.themespace.active_theme_types = list(
        state["themespace"]["active_theme_types"]
    )
    by_key = {(c.theme_type, c.dimension): c for c in ctx.themespace.clusters}
    for c_state in state["themespace"]["clusters"]:
        cluster = by_key.get((c_state["theme_type"], c_state["dimension"]))
        if cluster is None:
            continue
        cluster.frozen = c_state["frozen"]
        themes = {t.relation: t for t in cluster.themes}
        for relation, act, frozen, buffered in c_state["themes"]:
            theme = themes.get(relation)
            if theme is None:
                continue
            theme.activation = act
            theme.frozen = frozen
            theme._net_input_buffer = buffered

    # -- Temperature, RNG, counters, runner control -------------------
    temp = state["temperature"]
    ctx.temperature.value = temp["value"]
    ctx.temperature.clamped = temp["clamped"]
    ctx.temperature.clamp_value = temp["clamp_value"]
    ctx.temperature.clamp_cycles_remaining = temp["clamp_cycles_remaining"]

    rng_state = state["rng"]
    ctx.rng.set_state((
        rng_state["seed"],
        rng_state["call_count"],
        pickle.loads(base64.b64decode(rng_state["internal_state"])),
    ))

    ctx.ids.restore(state["ids"])

    runner_state = state["runner"]
    ctx.codelet_count = runner_state["codelet_count"]
    ctx.justify_mode = runner_state["justify_mode"]
    ctx.self_watching_enabled = runner_state["self_watching_enabled"]
    ctx.spreading_activation_threshold = runner_state["spreading_activation_threshold"]
    ctx.set_staleness_delay(runner_state["staleness_delay"])
