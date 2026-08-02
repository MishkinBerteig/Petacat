"""Pure serializers — engine state to plain JSON-compatible data.

Every function here reads a live :class:`EngineContext` and returns dicts and
lists of primitives. Nothing is written, nothing is queried, and no database
name is imported: the module depends on the standard library and on
``server.engine`` alone, so reading engine state costs nothing more than having
the engine itself.

That independence is the point of the module. These functions used to live in
``server/services/snapshot_service.py`` alongside ``sqlalchemy`` and
``server.models.run`` imports (defect D2 in the Phase 0 plan), which meant that
anything wanting to look at engine state — a benchmark, a fuzzer, a test on a
checkout with no database layer installed — had to drag in the ORM to get at
functions that never touch it. The benchmark harness worked around this by
stubbing out SQLAlchemy; the split removes the need.

Persisting what these functions produce is the other half of the story, and it
lives in ``server/services/snapshot_repository.py``.

``pickle`` and ``base64`` appear below, and both are fine here: they are
standard library, and the RNG's internal state is an opaque tuple that only
``random`` itself can interpret, so round-tripping it through pickle is the only
way to store it faithfully.
"""

from __future__ import annotations

import base64
import pickle
from typing import Any

from server.engine.runner import EngineContext


def serialize_rng_state(ctx: EngineContext) -> dict:
    """Serialize RNG state for JSON storage."""
    state = ctx.rng.get_state()
    # state is (seed, call_count, rng_internal_state)
    # rng_internal_state is a tuple from random.getstate() — pickle it
    return {
        "seed": state[0],
        "call_count": state[1],
        "internal_state": base64.b64encode(pickle.dumps(state[2])).decode("ascii"),
    }


def serialize_slipnet_state(ctx: EngineContext) -> dict:
    """Serialize slipnet node activations and clamp state."""
    nodes = {}
    for name, node in ctx.slipnet.nodes.items():
        nodes[name] = {
            "activation": node.activation,
            "activation_buffer": node.activation_buffer,
            "frozen": node.frozen,
            "clamp_cycles_remaining": node.clamp_cycles_remaining,
        }
    return nodes


def serialize_coderack_state(ctx: EngineContext) -> dict:
    """Serialize coderack contents."""
    bins = []
    for b in ctx.coderack.bins:
        codelets = [
            {
                "codelet_type": c.codelet_type,
                "urgency": c.urgency,
                "time_stamp": c.time_stamp,
                "arguments": {k: str(v) for k, v in c.arguments.items()
                              if not hasattr(v, '__dict__')},
            }
            for c in b.codelets
        ]
        bins.append(codelets)
    return {
        "bins": bins,
        "clamped_urgencies": ctx.coderack.clamped_urgencies,
    }


def serialize_themespace_state(ctx: EngineContext) -> dict:
    """Serialize themespace activations, dominance and thematic pressure.

    Dominance is decided server-side (margin of 90 over the runner-up, ranked by
    absolute activation) so the UI shows the same "locked-in" themes the engine
    acts on, rather than recomputing it with a different rule.
    """
    margin = ctx.meta.get_param("dominant_theme_margin", 90)
    clusters = []
    for cluster in ctx.themespace.clusters:
        dominant = cluster.get_dominant_theme(margin)
        themes = [
            {
                "dimension": t.dimension,
                "relation": t.relation,
                "activation": t.activation,
                "frozen": t.frozen,
                "dominant": t is dominant,
            }
            for t in cluster.themes
        ]
        clusters.append({
            "theme_type": cluster.theme_type,
            "dimension": cluster.dimension,
            "frozen": cluster.frozen,
            "dominant_relation": dominant.relation if dominant else None,
            "themes": themes,
        })
    return {
        "clusters": clusters,
        "possible_theme_types": list(ctx.themespace.possible_theme_types),
        # Theme types currently exerting top-down pressure (empty most of the
        # time — themes are passive until a pattern is clamped).
        "active_theme_types": list(ctx.themespace.active_theme_types),
        "thematic_pressure": ctx.themespace.has_thematic_pressure(),
        "dominant_theme_margin": margin,
    }


def serialize_trace_state(ctx: EngineContext) -> dict:
    """Serialize trace clamp/snag period state (not all events)."""
    return {
        "within_clamp_period": ctx.trace.within_clamp_period,
        "within_snag_period": ctx.trace.within_snag_period,
        "last_clamp_time": ctx.trace.last_clamp_time,
        "last_unclamp_time": ctx.trace.last_unclamp_time,
        "clamp_count": ctx.trace.clamp_count,
        "snag_count": ctx.trace.snag_count,
        "event_count": len(ctx.trace.events),
    }


def serialize_runner_state(ctx: EngineContext) -> dict:
    """Serialize runner control state."""
    return {
        "codelet_count": ctx.codelet_count,
        "temperature": ctx.temperature.value,
        "temperature_clamped": ctx.temperature.clamped,
        "temperature_clamp_value": ctx.temperature.clamp_value,
        "temperature_clamp_cycles": ctx.temperature.clamp_cycles_remaining,
        "justify_mode": ctx.justify_mode,
        "self_watching_enabled": ctx.self_watching_enabled,
    }


def _serialize_bond(bond: Any) -> dict:
    """Serialize a single bond for workspace display."""
    return {
        "from_pos": bond.from_object.left_string_pos,
        "to_pos": bond.to_object.left_string_pos,
        "category": getattr(bond.bond_category, "short_name", "?"),
        "direction": getattr(bond.direction, "short_name", None) if bond.direction else None,
        "strength": round(bond.strength),
        "built": bond.is_built,
    }


def _serialize_bridge(bridge: Any) -> dict:
    """Serialize a single bridge for workspace display."""
    cms = []
    for cm in getattr(bridge, "concept_mappings", []):
        cms.append({
            "from": getattr(cm.descriptor1, "short_name", "?"),
            "to": getattr(cm.descriptor2, "short_name", "?"),
            "label": getattr(cm.label, "short_name", None) if cm.label else None,
            # A slippage is the interesting half of a bridge's mappings; the
            # identities are numerous and mostly noise on screen, so the display
            # needs to be able to tell them apart rather than printing all of
            # them at equal weight.
            "is_slippage": bool(cm.is_slippage),
        })
    return {
        "obj1_string": bridge.object1.string.text if hasattr(bridge.object1, "string") and bridge.object1.string else "?",
        "obj1_pos": bridge.object1.left_string_pos,
        # The right edge as well, so a bridge to a *group* can be drawn to the
        # middle of that group instead of to its first letter.
        "obj1_right_pos": bridge.object1.right_string_pos,
        "obj2_string": bridge.object2.string.text if hasattr(bridge.object2, "string") and bridge.object2.string else "?",
        "obj2_pos": bridge.object2.left_string_pos,
        "obj2_right_pos": bridge.object2.right_string_pos,
        "strength": round(bridge.strength),
        "built": bridge.is_built,
        "concept_mappings": cms,
    }


def _serialize_group(group: Any) -> dict:
    """Serialize a single group for workspace display."""
    return {
        "left_pos": group.left_string_pos,
        "right_pos": group.right_string_pos,
        "category": getattr(group.group_category, "short_name", "?"),
        "direction": getattr(group.direction, "short_name", None) if group.direction else None,
        "strength": round(group.strength),
        "built": group.is_built,
        # Nesting level so the display can inset enclosed groups instead of
        # drawing every box at the same offset (group-graphics.ss draws nested
        # enclosures with padding proportional to depth).
        "depth": group.get_nesting_level(),
        "length": group.length,
    }


def _serialize_rule(rule: Any) -> dict:
    """Serialize a rule, including its three quality measures (§3.3.5)."""
    return {
        "type": "top" if rule.is_top_rule else "bottom",
        "quality": round(rule.quality),
        "uniformity": round(rule.uniformity),
        "abstractness": round(rule.abstractness),
        "succinctness": round(rule.succinctness),
        "clause_count": len(rule.clauses),
        "verbatim": rule.is_verbatim_rule,
        "english": rule.transcribe_to_english(),
        "built": rule.is_built,
        "theme_pattern": rule.theme_pattern[1:] if rule.theme_pattern else [],
    }


def serialize_workspace_state(ctx: EngineContext) -> dict:
    """Serialize workspace structures for display."""
    ws = ctx.workspace

    def string_bonds(s: Any) -> list[dict]:
        return [_serialize_bond(b) for b in s.bonds if b.is_built]

    def string_groups(s: Any) -> list[dict]:
        return [_serialize_group(g) for g in s.groups if g.is_built]

    return {
        "initial": ws.initial_string.text,
        "modified": ws.modified_string.text,
        "target": ws.target_string.text,
        "answer": ws.answer_string.text if ws.answer_string else None,
        "num_top_bridges": len(ws.top_bridges),
        "num_bottom_bridges": len(ws.bottom_bridges),
        "num_vertical_bridges": len(ws.vertical_bridges),
        "num_top_rules": len(ws.top_rules),
        "num_bottom_rules": len(ws.bottom_rules),
        "bonds_per_string": {
            s.text: len([b for b in s.bonds if b.is_built]) for s in ws.all_strings
        },
        "groups_per_string": {
            s.text: len([g for g in s.groups if g.is_built]) for s in ws.all_strings
        },
        # Detailed structure data for workspace visualization
        "bonds": {
            s.text: string_bonds(s) for s in ws.all_strings
        },
        "groups": {
            s.text: string_groups(s) for s in ws.all_strings
        },
        "top_bridges": [_serialize_bridge(b) for b in ws.top_bridges if b.is_built],
        "vertical_bridges": [_serialize_bridge(b) for b in ws.vertical_bridges if b.is_built],
        "bottom_bridges": [_serialize_bridge(b) for b in ws.bottom_bridges if b.is_built],
        "top_rules": [_serialize_rule(r) for r in ws.top_rules if r.is_built],
        "bottom_rules": [_serialize_rule(r) for r in ws.bottom_rules if r.is_built],
    }


def describe_structure(structure: Any) -> dict:
    """A Workspace structure named well enough to be pointed at in the UI.

    §4.4: an event records "the Workspace structures ... that exist at the time of the
    event", and MetaCat's Trace display highlights exactly those (``trace.ss:311-327``).
    Descriptive rather than a reference: the structure may since have been broken and
    rebuilt, and a persisted event outlives the objects entirely, so what a reader needs
    is to see *which* structure it was, not to hold it.
    """
    string = getattr(structure, "string", None)
    return {
        "kind": type(structure).__name__,
        "label": str(structure),
        "string": getattr(string, "text", None),
        "left_index": getattr(structure, "left_index", None),
        "right_index": getattr(structure, "right_index", None),
        "strength": getattr(structure, "strength", None),
    }
