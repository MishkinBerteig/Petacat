"""SnapshotService — serializes/deserializes full engine state to/from DB.

Handles cycle_snapshot round-trip: save current EngineContext state as a
JSONB row, and restore it back to a live EngineContext.
"""

from __future__ import annotations

import pickle
import base64
from typing import Any

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from server.engine.runner import EngineContext
from server.models.run import CycleSnapshot


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
    """Serialize themespace activations."""
    clusters = []
    for cluster in ctx.themespace.clusters:
        themes = [
            {
                "dimension": t.dimension,
                "relation": t.relation,
                "activation": t.activation,
                "positive_activation": t.positive_activation,
                "negative_activation": t.negative_activation,
                "frozen": t.frozen,
            }
            for t in cluster.themes
        ]
        clusters.append({
            "theme_type": cluster.theme_type,
            "dimension": cluster.dimension,
            "frozen": cluster.frozen,
            "themes": themes,
        })
    return {
        "clusters": clusters,
        "active_theme_types": list(ctx.themespace.active_theme_types),
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
        })
    return {
        "obj1_string": bridge.object1.string.text if hasattr(bridge.object1, "string") and bridge.object1.string else "?",
        "obj1_pos": bridge.object1.left_string_pos,
        "obj2_string": bridge.object2.string.text if hasattr(bridge.object2, "string") and bridge.object2.string else "?",
        "obj2_pos": bridge.object2.left_string_pos,
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
    }


def _serialize_rule(rule: Any) -> dict:
    """Serialize a rule for workspace display."""
    return {
        "type": "top" if rule.is_top_rule else "bottom",
        "quality": round(rule.quality),
        "english": rule.transcribe_to_english(),
        "built": rule.is_built,
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


async def save_cycle_snapshot(
    session: AsyncSession,
    run_id: int,
    ctx: EngineContext,
) -> int:
    """Serialize full engine state to a cycle_snapshot row. Returns snapshot ID."""
    snapshot = CycleSnapshot(
        run_id=run_id,
        codelet_count=ctx.codelet_count,
        temperature=ctx.temperature.value,
        rng_state=serialize_rng_state(ctx),
        workspace_state=serialize_workspace_state(ctx),
        slipnet_state=serialize_slipnet_state(ctx),
        coderack_state=serialize_coderack_state(ctx),
        themespace_state=serialize_themespace_state(ctx),
        trace_state=serialize_trace_state(ctx),
        runner_state=serialize_runner_state(ctx),
    )
    session.add(snapshot)
    await session.flush()
    return snapshot.id


def restore_slipnet_state(ctx: EngineContext, state: dict) -> None:
    """Restore slipnet activations from a snapshot."""
    for name, node_state in state.items():
        node = ctx.slipnet.nodes.get(name)
        if node:
            node.activation = node_state["activation"]
            node.activation_buffer = node_state["activation_buffer"]
            node.frozen = node_state["frozen"]
            node.clamp_cycles_remaining = node_state["clamp_cycles_remaining"]


def restore_trace_state(ctx: EngineContext, state: dict) -> None:
    """Restore trace clamp/snag state from a snapshot."""
    ctx.trace.within_clamp_period = state["within_clamp_period"]
    ctx.trace.within_snag_period = state["within_snag_period"]
    ctx.trace.last_clamp_time = state["last_clamp_time"]
    ctx.trace.last_unclamp_time = state["last_unclamp_time"]
    ctx.trace.clamp_count = state["clamp_count"]
    ctx.trace.snag_count = state["snag_count"]


def restore_runner_state(ctx: EngineContext, state: dict) -> None:
    """Restore runner control state from a snapshot."""
    ctx.codelet_count = state["codelet_count"]
    ctx.temperature.value = state["temperature"]
    ctx.temperature.clamped = state["temperature_clamped"]
    ctx.temperature.clamp_value = state["temperature_clamp_value"]
    ctx.temperature.clamp_cycles_remaining = state["temperature_clamp_cycles"]
    ctx.justify_mode = state["justify_mode"]
    ctx.self_watching_enabled = state["self_watching_enabled"]


def restore_rng_state(ctx: EngineContext, state: dict) -> None:
    """Restore RNG state from a snapshot."""
    internal_state = pickle.loads(base64.b64decode(state["internal_state"]))
    ctx.rng.set_state((state["seed"], state["call_count"], internal_state))


async def prune_old_snapshots(
    session: AsyncSession,
    run_id: int,
    keep_n: int = 10,
) -> int:
    """Remove all but the latest N cycle_snapshots for a run. Returns count removed."""
    result = await session.execute(
        select(CycleSnapshot.id)
        .where(CycleSnapshot.run_id == run_id)
        .order_by(CycleSnapshot.id.desc())
    )
    all_ids = [row[0] for row in result.all()]
    if len(all_ids) <= keep_n:
        return 0
    ids_to_delete = all_ids[keep_n:]
    await session.execute(
        delete(CycleSnapshot).where(CycleSnapshot.id.in_(ids_to_delete))
    )
    return len(ids_to_delete)
