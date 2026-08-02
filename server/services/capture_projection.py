"""Render a recorded ``state_graph`` capture in the shapes the existing views expect.

WP3.9's whole point is that Normal and Audit exist to be *looked at*.  What they write
is the id-based object graph of ``server/engine/state_graph.py``, and what the client's
``WorkspaceView``, ``SlipnetView``, ``ThemespaceView`` and ``TraceView`` read is the
display shape produced by ``server/engine/serialization.py`` from a live
``EngineContext``.  This module is the bridge, and it is deliberately the *only* new
representation Phase 0 adds: it emits exactly the shapes those views already consume,
so the review surfaces reuse the components rather than growing parallel ones.

Why this reads the record instead of restoring it
-------------------------------------------------
The obvious alternative is to call ``restore_run_state`` into a throwaway runner and
then run the live serializers over it — no display logic duplicated at all.  It was
tried and rejected, for two reasons.

The first is a property worth having.  A reader that rebuilds live objects and then
serializes them proves that the *objects* can produce a display; it does not prove that
the **record** contains the display.  A field that the capture happened to omit but
that a reconstructed object recomputes from its neighbours would go unnoticed, which is
precisely the failure mode ("we wrote it, nothing read it back") this work package
exists to prevent.  Projecting straight from the record makes the record answerable for
its own completeness.

The second is that restoring is, today, not available for the captures that matter.
``state_graph.GRAPH_TYPES`` lists ``TraceEvent`` but none of its three subclasses —
``AnswerEvent``, ``ClampEvent``, ``SnagEvent`` — so ``_Reader`` raises
``StateGraphError: unknown graph type 'AnswerEvent'`` on any Run-end capture from a run
that found an answer, hit a snag, or clamped a theme pattern.  Capture is unaffected
(it writes ``type(obj).__name__``, which is correct); only the read side cannot find
the class.  That is an engine-side defect and is reported rather than worked around
here, and the review surface is built so that it is not blocked by it.

Faithfulness is pinned by a test, not by care
---------------------------------------------
``tests/module/test_capture_projection.py`` captures a mid-run state, projects it *and*
restores it into a runner and serializes that with the live serializers, and requires
the two to be equal.  A display field that drifts in ``serialization.py`` without
drifting here fails that test, which is what stops this module from becoming the second
hand-maintained representation the state-graph docstring warns about.
"""

from __future__ import annotations

from typing import Any

#: The four Workspace strings, by the role that names them — the same roles
#: ``state_graph`` references strings by.
_STRING_ROLES = ("initial", "modified", "target", "answer")


class CaptureFormatError(ValueError):
    """The capture cannot be rendered — usually a format version this code predates."""


# ─────────────────────────────────────────────────────────────────────────────
# Walking the graph
# ─────────────────────────────────────────────────────────────────────────────


class _Graph:
    """Resolves the encodings ``state_graph`` writes, without building live objects.

    ``state_graph._Writer`` emits five encodings: ``$ref`` into the flat record table,
    ``$string`` for one of the four Workspace strings, ``$node`` and ``$link`` for
    Slipnet configuration, and ``$list``/``$dict`` for containers.  This resolves them
    to plain data — a record index stays an index, a node stays its name — because the
    projection only ever needs to read fields, never to traverse an object.
    """

    def __init__(self, state: dict) -> None:
        self._records: list[dict] = state["graph"]
        #: role → the string's text, so ``{"$string": "initial"}`` can become "abc".
        self._string_text = {
            role: s["text"] for role, s in state["workspace"]["strings"].items()
        }

    def record(self, ref: Any) -> dict | None:
        """The fields of the record ``ref`` points at, or ``None`` for a non-ref."""
        if isinstance(ref, dict) and "$ref" in ref:
            return self._records[ref["$ref"]]["fields"]
        return None

    def record_type(self, ref: Any) -> str | None:
        if isinstance(ref, dict) and "$ref" in ref:
            return self._records[ref["$ref"]]["type"]
        return None

    def items(self, encoded: Any) -> list:
        """The elements of a captured list, or ``[]`` when the field is absent."""
        if isinstance(encoded, dict) and "$list" in encoded:
            return encoded["$list"]
        return []

    def mapping(self, encoded: Any) -> dict:
        """A captured dict as a plain dict."""
        if isinstance(encoded, dict) and "$dict" in encoded:
            return dict(encoded["$dict"])
        return {}

    def node(self, encoded: Any) -> str | None:
        """The Slipnet node name a field refers to, if it refers to one."""
        if isinstance(encoded, dict) and "$node" in encoded:
            return encoded["$node"]
        return None

    def string_text(self, encoded: Any) -> str | None:
        """The text of the Workspace string a field refers to."""
        if isinstance(encoded, dict) and "$string" in encoded:
            return self._string_text.get(encoded["$string"])
        return None

    def by_type(self, type_name: str) -> list[dict]:
        return [r["fields"] for r in self._records if r["type"] == type_name]


# ─────────────────────────────────────────────────────────────────────────────
# Workspace
# ─────────────────────────────────────────────────────────────────────────────


def _short_name(meta: Any, node_name: str | None, default: str | None = "?") -> str | None:
    """A Slipnet node's display abbreviation.

    Captures reference nodes by name because a node's structure is configuration
    rather than run state; the short name therefore comes from the metadata the
    capture was taken under, exactly as the live serializer takes it from the live
    Slipnet.
    """
    if node_name is None:
        return default
    spec = meta.slipnet_node_specs.get(node_name)
    return spec.short_name if spec is not None else node_name


def _object_extent(g: _Graph, ref: Any) -> tuple[int, int]:
    """A Letter's or Group's ``(left_string_pos, right_string_pos)``."""
    fields = g.record(ref)
    if fields is None:
        return (0, 0)
    return (fields.get("left_string_pos", 0), fields.get("right_string_pos", 0))


def _nesting_level(g: _Graph, group_fields: dict) -> int:
    """How deeply a group is enclosed, counted by walking ``enclosing_group``.

    The live serializer calls ``Group.get_nesting_level()``; the record holds the
    chain that method walks, so the same number falls out of following the refs.
    Bounded by the record count so a malformed capture cannot spin here.
    """
    depth = 0
    fields: dict | None = group_fields
    seen: set[int] = set()
    while fields is not None:
        ref = fields.get("enclosing_group")
        if not isinstance(ref, dict) or "$ref" not in ref:
            break
        index = ref["$ref"]
        if index in seen:
            break
        seen.add(index)
        depth += 1
        fields = g.record(ref)
    return depth


def _project_bond(g: _Graph, meta: Any, fields: dict) -> dict:
    return {
        "from_pos": _object_extent(g, fields.get("from_object"))[0],
        "to_pos": _object_extent(g, fields.get("to_object"))[0],
        "category": _short_name(meta, g.node(fields.get("bond_category"))),
        "direction": _short_name(meta, g.node(fields.get("direction")), None),
        "strength": round(fields.get("strength", 0.0)),
        "built": fields.get("proposal_level") == "built",
    }


def _project_group(g: _Graph, meta: Any, fields: dict) -> dict:
    return {
        "left_pos": fields.get("left_string_pos", 0),
        "right_pos": fields.get("right_string_pos", 0),
        "category": _short_name(meta, g.node(fields.get("group_category"))),
        "direction": _short_name(meta, g.node(fields.get("direction")), None),
        "strength": round(fields.get("strength", 0.0)),
        "built": fields.get("proposal_level") == "built",
        "depth": _nesting_level(g, fields),
        # ``Group.length`` is ``len(self.objects)`` — a property, so it is not a
        # captured field, but the list it counts is.
        "length": len(g.items(fields.get("objects"))),
    }


def _project_bridge(g: _Graph, meta: Any, fields: dict) -> dict:
    mappings = []
    for cm_ref in g.items(fields.get("concept_mappings")):
        cm = g.record(cm_ref)
        if cm is None:
            continue
        d1 = g.node(cm.get("descriptor1"))
        d2 = g.node(cm.get("descriptor2"))
        mappings.append({
            "from": _short_name(meta, d1),
            "to": _short_name(meta, d2),
            "label": _short_name(meta, g.node(cm.get("label")), None),
            # ``ConceptMapping.is_identity`` is ``descriptor1 is descriptor2``.  Both
            # sides are captured as node names, and a node's name is its identity, so
            # comparing the names is the same test.
            "is_slippage": d1 != d2,
        })

    obj1, obj2 = g.record(fields.get("object1")), g.record(fields.get("object2"))
    left1, right1 = _object_extent(g, fields.get("object1"))
    left2, right2 = _object_extent(g, fields.get("object2"))
    return {
        "obj1_string": (g.string_text(obj1.get("string")) if obj1 else None) or "?",
        "obj1_pos": left1,
        "obj1_right_pos": right1,
        "obj2_string": (g.string_text(obj2.get("string")) if obj2 else None) or "?",
        "obj2_pos": left2,
        "obj2_right_pos": right2,
        "strength": round(fields.get("strength", 0.0)),
        "built": fields.get("proposal_level") == "built",
        "concept_mappings": mappings,
    }


def _project_rule(g: _Graph, fields: dict) -> dict:
    theme_pattern = g.items(fields.get("theme_pattern"))
    return {
        "type": fields.get("rule_type", "top"),
        "quality": round(fields.get("quality", 0.0)),
        "uniformity": round(fields.get("uniformity", 0.0)),
        "abstractness": round(fields.get("abstractness", 0.0)),
        "succinctness": round(fields.get("succinctness", 0.0)),
        "clause_count": len(g.items(fields.get("clauses"))),
        # ``Rule.is_verbatim_rule`` is "any clause is of the verbatim type".
        "verbatim": any(
            (g.record(c) or {}).get("clause_type") == "verbatim"
            for c in g.items(fields.get("clauses"))
        ),
        # Transcription is cached on the Rule as it is built, so the English the run
        # actually produced is in the record rather than being re-derived here.
        "english": fields.get("english_transcription") or "",
        "built": fields.get("proposal_level") == "built",
        # The head of a rule's theme pattern is its bridge type; the display wants the
        # dimensions only, matching ``_serialize_rule``'s ``theme_pattern[1:]``.
        "theme_pattern": [_plain(item) for item in theme_pattern[1:]],
    }


def _plain(encoded: Any) -> Any:
    """A captured container as ordinary JSON, for fields the display only echoes."""
    if isinstance(encoded, dict):
        if "$list" in encoded:
            return [_plain(v) for v in encoded["$list"]]
        if "$dict" in encoded:
            return {k: _plain(v) for k, v in encoded["$dict"]}
        if "$node" in encoded:
            return encoded["$node"]
    return encoded


def project_workspace(state: dict, meta: Any) -> dict:
    """The recorded Workspace in ``serialize_workspace_state``'s shape."""
    g = _Graph(state)
    ws = state["workspace"]
    strings = ws["strings"]

    # Keyed by string *text*, as the live serializer keys them: the display looks
    # bonds up by the text it is drawing.  Two strings with the same text collapse
    # into one entry there too, so this matches rather than improves on it.
    def built_only(role: str, key: str, project) -> list[dict]:
        out = []
        for ref in strings[role][key]:
            fields = g.record(ref)
            if fields is not None and fields.get("proposal_level") == "built":
                out.append(project(fields))
        return out

    bonds = {
        strings[role]["text"]: built_only(role, "bonds", lambda f: _project_bond(g, meta, f))
        for role in _STRING_ROLES
        if role in strings
    }
    groups = {
        strings[role]["text"]: built_only(role, "groups", lambda f: _project_group(g, meta, f))
        for role in _STRING_ROLES
        if role in strings
    }

    def bridges(key: str) -> list[dict]:
        out = []
        for ref in ws[key]:
            fields = g.record(ref)
            if fields is not None and fields.get("proposal_level") == "built":
                out.append(_project_bridge(g, meta, fields))
        return out

    def rules(key: str) -> list[dict]:
        out = []
        for ref in ws[key]:
            fields = g.record(ref)
            if fields is not None and fields.get("proposal_level") == "built":
                out.append(_project_rule(g, fields))
        return out

    problem = state["problem"]
    return {
        "initial": problem["initial"],
        "modified": problem["modified"],
        "target": problem["target"],
        "answer": problem["answer"],
        "num_top_bridges": len(ws["top_bridges"]),
        "num_bottom_bridges": len(ws["bottom_bridges"]),
        "num_vertical_bridges": len(ws["vertical_bridges"]),
        "num_top_rules": len(ws["top_rules"]),
        "num_bottom_rules": len(ws["bottom_rules"]),
        "bonds_per_string": {text: len(v) for text, v in bonds.items()},
        "groups_per_string": {text: len(v) for text, v in groups.items()},
        "bonds": bonds,
        "groups": groups,
        "top_bridges": bridges("top_bridges"),
        "vertical_bridges": bridges("vertical_bridges"),
        "bottom_bridges": bridges("bottom_bridges"),
        "top_rules": rules("top_rules"),
        "bottom_rules": rules("bottom_rules"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# The other components
# ─────────────────────────────────────────────────────────────────────────────


def project_slipnet(state: dict, meta: Any) -> dict:
    """Node activations in the shape ``GET /api/runs/{id}/slipnet`` serves.

    That endpoint builds its three fields inline in ``RunService`` rather than through
    ``serialization.py``, and the graph view reads exactly those three, so this matches
    the endpoint rather than the serializer.  Conceptual depth is configuration and is
    read from the metadata, as it is there.
    """
    out = {}
    for name, (activation, _buffer, frozen, _clamp) in state["slipnet"].items():
        spec = meta.slipnet_node_specs.get(name)
        out[name] = {
            "activation": activation,
            "conceptual_depth": spec.conceptual_depth if spec is not None else 0,
            "frozen": frozen,
        }
    return out


def project_coderack(state: dict) -> dict:
    """Codelet counts by type, in the shape ``GET /api/runs/{id}/coderack`` serves."""
    g = _Graph(state)
    counts: dict[str, int] = {}
    total = 0
    for bin_refs in state["coderack"]["bins"]:
        for ref in bin_refs:
            fields = g.record(ref)
            if fields is None:
                continue
            total += 1
            name = fields.get("codelet_type", "?")
            counts[name] = counts.get(name, 0) + 1
    return {"total_count": total, "type_counts": counts}


def project_themespace(state: dict, meta: Any) -> dict:
    """Theme clusters in ``serialize_themespace_state``'s shape.

    Dominance is recomputed here with the engine's own rule — rank by *absolute*
    activation, the leader must itself be positive and must beat the runner-up by more
    than the margin — because it is not a captured field.  Recomputing it rather than
    letting the client decide keeps the recorded view and the live view saying the same
    thing about which themes were locked in.
    """
    margin = meta.get_param("dominant_theme_margin", 90)
    justify_mode = state["runner"]["justify_mode"]

    clusters = []
    for c in state["themespace"]["clusters"]:
        themes = [
            {
                "dimension": c["dimension"],
                "relation": relation,
                "activation": activation,
                "frozen": frozen,
                "dominant": False,
            }
            for relation, activation, frozen, _buffer in c["themes"]
        ]
        dominant = _dominant_theme(themes, margin)
        if dominant is not None:
            dominant["dominant"] = True
        clusters.append({
            "theme_type": c["theme_type"],
            "dimension": c["dimension"],
            "frozen": c["frozen"],
            "dominant_relation": dominant["relation"] if dominant else None,
            "themes": themes,
        })

    active = list(state["themespace"]["active_theme_types"])
    return {
        "clusters": clusters,
        # ``Themespace.possible_theme_types`` is a function of justify mode, which the
        # capture records under ``runner``.
        "possible_theme_types": (
            ["top_bridge", "vertical_bridge", "bottom_bridge"]
            if justify_mode
            else ["top_bridge", "vertical_bridge"]
        ),
        "active_theme_types": active,
        "thematic_pressure": bool(active),
        "dominant_theme_margin": margin,
    }


def _dominant_theme(themes: list[dict], margin: float) -> dict | None:
    """``ThemeCluster.get_dominant_theme``, applied to projected themes."""
    if not themes:
        return None
    ranked = sorted(themes, key=lambda t: abs(t["activation"]), reverse=True)
    top = ranked[0]
    if top["activation"] <= 0:
        return None
    runner_up = abs(ranked[1]["activation"]) if len(ranked) > 1 else 0.0
    if abs(top["activation"]) - runner_up > margin:
        return top
    return None


def project_trace(state: dict) -> list[dict]:
    """Recorded Trace events, in the shape ``GET /api/runs/{id}/trace`` serves."""
    g = _Graph(state)
    events = []
    for ref in state["trace"]["events"]:
        fields = g.record(ref)
        if fields is None:
            continue
        events.append({
            "event_number": fields.get("event_number", 0),
            "event_type": fields.get("event_type", ""),
            "codelet_count": fields.get("codelet_count", 0),
            "temperature": fields.get("temperature", 0.0),
            "description": fields.get("description") or "",
            "theme_pattern": _plain(fields.get("theme_pattern")),
        })
    return events


def project_memory(state: dict) -> dict:
    """The Episodic Memory the run held, in ``GET /api/memory``'s shape.

    This is the one component that crosses Run boundaries, so a Run-start capture's
    memory is what the Run *inherited* from the Training Session and a Run-end
    capture's is what it left behind.  Seeing both is the point of recording it.
    """
    g = _Graph(state)

    def answers() -> list[dict]:
        out = []
        for ref in state["memory"]["answers"]:
            f = g.record(ref)
            if f is None:
                continue
            out.append({
                "answer_id": f.get("answer_id", 0),
                "problem": _plain(f.get("problem")) or [],
                "top_rule_description": f.get("top_rule_description") or "",
                "bottom_rule_description": f.get("bottom_rule_description") or "",
                "top_rule_quality": f.get("top_rule_quality", 0),
                "bottom_rule_quality": f.get("bottom_rule_quality", 0),
                "quality": f.get("quality", 0),
                "temperature": f.get("temperature", 0),
                "themes": _plain(f.get("themes")) or {},
                "unjustified_slippages": _plain(f.get("unjustified_slippages")) or [],
                "activation": f.get("activation", 0),
            })
        return out

    def snags() -> list[dict]:
        out = []
        for ref in state["memory"]["snags"]:
            f = g.record(ref)
            if f is None:
                continue
            out.append({
                "snag_id": f.get("snag_id", 0),
                "problem": _plain(f.get("problem")) or [],
                "codelet_count": f.get("codelet_count", 0),
                "temperature": f.get("temperature", 0),
                "description": f.get("description") or "",
            })
        return out

    return {"answers": answers(), "snags": snags()}


# ─────────────────────────────────────────────────────────────────────────────
# The whole capture
# ─────────────────────────────────────────────────────────────────────────────

#: Capture format versions this module knows how to render.  Checked rather than
#: assumed, because a review surface that silently renders a format it predates would
#: show plausible nonsense — worse than refusing.
SUPPORTED_FORMAT_VERSIONS = frozenset({1})


def project_capture(state: dict, meta: Any) -> dict:
    """Everything the review views need from one recorded capture."""
    version = state.get("format_version")
    if version not in SUPPORTED_FORMAT_VERSIONS:
        raise CaptureFormatError(
            f"capture is in state-graph format version {version}; this build renders "
            f"{sorted(SUPPORTED_FORMAT_VERSIONS)}"
        )
    return {
        "problem": state["problem"],
        "codelet_count": state["runner"]["codelet_count"],
        "temperature": state["temperature"]["value"],
        "temperature_detail": state["temperature"],
        "runner": state["runner"],
        "workspace": project_workspace(state, meta),
        "slipnet": project_slipnet(state, meta),
        "coderack": project_coderack(state),
        "themespace": project_themespace(state, meta),
        "trace": project_trace(state),
        "memory": project_memory(state),
    }
