"""Petacat snapshots (spec §8): one record at the end of every update cycle.

Every object is written by its canonical name (``naming.py``), not through
``serialize_workspace_state``, which keys strings by their text and would collide on
problems like ``abc -> d; abc``.  Each section is built independently so a failure in
one writes ``{"?": "<error>"}`` for that section instead of losing the snapshot.

Sections, as in the spec's table: ``temperature``, ``slipnet`` (activation and frozen
flag per node), ``themes`` (activation per theme (all of them, as Metacat's)), ``coderack`` (each
codelet's name, bin and time stamp, and the clamped types), ``structures`` (built
structures with strengths, proposed ones by name) and ``trace`` (event counts and
whether a snag or clamp period is under way).
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Callable

from tests.lockstep.naming import (
    bond_name, bridge_name, codelet_name, description_name, group_name, node_name,
    rule_name, theme_name,
)


def _temperature(ctx: Any) -> dict:
    return {"value": float(ctx.temperature.value), "clamped": bool(ctx.temperature.clamped)}


def _slipnet(ctx: Any) -> dict:
    return {
        node_name(n): [float(n.activation), bool(n.frozen)]
        for n in ctx.slipnet.nodes.values()
    }


def _themes(ctx: Any) -> dict:
    out = {}
    for cluster in ctx.themespace.clusters:
        for t in cluster.themes:
            out[theme_name(t)] = float(t.activation)
    return dict(sorted(out.items()))


def _coderack(ctx: Any) -> dict:
    codelets = sorted(
        [codelet_name(c), b.bin_number, c.time_stamp]
        for b in ctx.coderack.bins for c in b.codelets
    )
    return {
        "codelets": codelets,
        "clamped": sorted(ctx.coderack.clamped_urgencies),
    }


def _strengths(structs: list, namer: Callable[[Any], str]) -> list:
    built = sorted([namer(s), float(s.strength)] for s in structs if s.is_built)
    return built


def _proposed(structs: list, namer: Callable[[Any], str]) -> list:
    return sorted(namer(s) for s in structs if not s.is_built)


def _structures(ctx: Any) -> dict:
    ws = ctx.workspace
    bonds = [b for s in ws.all_strings for b in s.bonds]
    groups = [g for s in ws.all_strings for g in s.groups]
    bridges = ws.top_bridges + ws.bottom_bridges + ws.vertical_bridges
    rules = ws.top_rules + ws.bottom_rules
    descriptions = [d for o in ws.all_objects for d in o.descriptions]
    return {
        "bonds": _strengths(bonds, bond_name),
        "groups": _strengths(groups, group_name),
        "bridges": _strengths(bridges, bridge_name),
        "descriptions": sorted(
            [description_name(d), float(d.strength)] for d in descriptions
        ),
        "rules": _strengths(rules, rule_name),
        "proposed": {
            "bonds": _proposed(bonds, bond_name),
            "groups": _proposed(groups, group_name),
            "bridges": _proposed(bridges, bridge_name),
        },
    }


def _trace(ctx: Any) -> dict:
    return {
        "events": dict(sorted(Counter(e.event_type for e in ctx.trace.events).items())),
        "snag": bool(ctx.trace.within_snag_period),
        "clamp": bool(ctx.trace.within_clamp_period),
    }


SECTIONS: dict[str, Callable[[Any], Any]] = {
    "temperature": _temperature,
    "slipnet": _slipnet,
    "themes": _themes,
    "coderack": _coderack,
    "structures": _structures,
    "trace": _trace,
}


def snapshot_record(ctx: Any, u: int | None, c: int) -> dict[str, Any]:
    rec: dict[str, Any] = {"t": "snapshot", "u": u, "c": c}
    for name, build in SECTIONS.items():
        try:
            rec[name] = build(ctx)
        except Exception as exc:  # a snapshot must never crash the run it describes
            rec[name] = {"?": f"{type(exc).__name__}: {exc}"}
    return rec
