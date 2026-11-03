"""Views over the journal (configuration plan 3.11): read it, and write only through the layer.

* **replay** re-applies the recorded resolved ops (no validation); **reconstruction** reads
  the before-images backwards from the current-state tables.  The round-trip test holds the
  two equal at every revision.
* ``as_of`` is an entity or the whole configuration at a revision.
* ``restore_entity`` and ``undo`` build ops and send them through ``write_immediate``: each
  is a new entry (``source = restore``), never a rewrite.
* ``provenance`` answers "from the Starting Conceptual State" or "changed by source S,
  actor A, at version V".
* ``verify_journal`` replays the journal and compares the result with the current-state
  tables and ``config_hash``.

A *state* is ``{table: {key tuple: row}}`` where a row holds every column but the surrogate
``id`` (the same shape a journal records), so states from replay, reconstruction and the
tables compare with ``==``.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.models.journal import (
    BASELINE_SOURCES,
    GLOBAL_CONFIGURATION_ID,
    KIND_GLOBAL,
    Configuration,
    JournalEntry,
)
from server.services.config_registry import LAYER_REGISTRY
from server.services.journal import (
    JournalError,
    MissingKey,
    WriteResult,
    compute_config_hash,
    write_immediate,
)

State = dict[str, dict[tuple, dict]]

_CONFIGURATIONS = Configuration.__table__
_JOURNAL = JournalEntry.__table__


class ReplayError(JournalError):
    """The recorded ops do not apply to the state they were replayed onto."""


# ──────────────────────────────────────────────────────────────────
# Pure: states, replay, reconstruction
# ──────────────────────────────────────────────────────────────────


def empty_state() -> State:
    return {name: {} for name in LAYER_REGISTRY}


def _kt(table: str, key: Mapping[str, Any]) -> tuple:
    return LAYER_REGISTRY[table].key_tuple(key)


def apply_ops(state: State, ops: Sequence[Mapping[str, Any]]) -> None:
    """Replay resolved ops onto ``state``, in order, in place."""
    for op in ops:
        table = op["table"]
        spec = LAYER_REGISTRY[table]
        rows = state[table]
        if op["op"] == "insert":
            kt = _kt(table, op["key"])
            if kt in rows:
                raise ReplayError(f"{table}: insert of {kt!r}, which exists")
            rows[kt] = copy.deepcopy(dict(op["row"]))
        elif op["op"] == "update":
            kt = _kt(table, op["key"])
            if kt not in rows:
                raise ReplayError(f"{table}: update of {kt!r}, which does not exist")
            new = {**rows.pop(kt), **copy.deepcopy(dict(op["set"]))}
            rows[spec.key_tuple(spec.key_of(new))] = new
        elif op["op"] == "delete":
            kt = _kt(table, op["key"])
            if rows.pop(kt, None) is None:
                raise ReplayError(f"{table}: delete of {kt!r}, which does not exist")
        else:
            raise ReplayError(f"unknown op {op['op']!r}")


def unapply_entry(state: State, ops: Sequence[Mapping[str, Any]], before: Sequence[Any]) -> None:
    """Undo one entry on ``state`` from its before-images, newest op first, in place."""
    for op, old in reversed(list(zip(ops, before))):
        table = op["table"]
        spec = LAYER_REGISTRY[table]
        rows = state[table]
        if op["op"] == "insert":
            if rows.pop(_kt(table, op["key"]), None) is None:
                raise ReplayError(f"{table}: the inserted row {op['key']!r} is not there to remove")
        elif op["op"] == "update":
            current = {**old, **op["set"]}
            if rows.pop(spec.key_tuple(spec.key_of(current)), None) is None:
                raise ReplayError(f"{table}: the updated row {op['key']!r} is not there")
            rows[spec.key_tuple(spec.key_of(old))] = copy.deepcopy(dict(old))
        elif op["op"] == "delete":
            rows[spec.key_tuple(spec.key_of(old))] = copy.deepcopy(dict(old))
        else:
            raise ReplayError(f"unknown op {op['op']!r}")


def replay(
    entries: Sequence[Mapping[str, Any]], *, base: State | None = None, upto: int | None = None
) -> State:
    """The state after the entries up to revision ``upto`` (all when ``None``), forward from
    ``base`` (empty by default: the global journal starts at its ``standard_load``)."""
    state = copy.deepcopy(base) if base is not None else empty_state()
    for entry in sorted(entries, key=lambda e: e["revision"]):
        if upto is not None and entry["revision"] > upto:
            break
        apply_ops(state, entry["resolved"])
    return state


def reconstruct(
    current: State, entries: Sequence[Mapping[str, Any]], to_revision: int
) -> State:
    """The state at ``to_revision``, backward from ``current`` by the before-images."""
    state = copy.deepcopy(current)
    for entry in sorted(entries, key=lambda e: e["revision"], reverse=True):
        if entry["revision"] <= to_revision:
            break
        unapply_entry(state, entry["resolved"], entry["before"])
    return state


# ──────────────────────────────────────────────────────────────────
# Reading
# ──────────────────────────────────────────────────────────────────


async def read_entries(
    session: AsyncSession,
    configuration_id: int = GLOBAL_CONFIGURATION_ID,
    *,
    after: int = 0,
    upto: int | None = None,
    group_id: str | None = None,
) -> list[dict]:
    """The configuration's entries in revision order (never by id or ``recorded_at``)."""
    stmt = select(_JOURNAL).where(
        _JOURNAL.c.configuration_id == configuration_id, _JOURNAL.c.revision > after
    )
    if upto is not None:
        stmt = stmt.where(_JOURNAL.c.revision <= upto)
    if group_id is not None:
        stmt = stmt.where(_JOURNAL.c.group_id == group_id)
    rows = (await session.execute(stmt.order_by(_JOURNAL.c.revision))).mappings().all()
    return [dict(r) for r in rows]


async def current_state(session: AsyncSession) -> State:
    """The global configuration's current-state tables, as a state."""
    state = empty_state()
    for name, spec in LAYER_REGISTRY.items():
        columns = [spec.table.c[c] for c in spec.stored_columns]
        for row in (await session.execute(select(*columns))).mappings():
            row = dict(row)
            state[name][spec.key_tuple(spec.key_of(row))] = row
    return state


async def _kind(session: AsyncSession, configuration_id: int) -> str:
    kind = (
        await session.execute(
            select(_CONFIGURATIONS.c.kind).where(_CONFIGURATIONS.c.id == configuration_id)
        )
    ).scalar_one_or_none()
    if kind is None:
        raise JournalError(f"configuration {configuration_id} does not exist")
    return kind


async def as_of(
    session: AsyncSession,
    configuration_id: int,
    revision: int,
    *,
    table: str | None = None,
    key: Mapping[str, Any] | None = None,
    base: State | None = None,
) -> Any:
    """The whole configuration (a state), one table, or one row, as of ``revision``.

    The global configuration is reconstructed from its current tables by the before-images.
    Any other is replayed from ``base`` (its Starting Conceptual State, from C8).  A row
    that did not exist then is ``None``.
    """
    entries = await read_entries(session, configuration_id)
    if await _kind(session, configuration_id) == KIND_GLOBAL:
        state = reconstruct(await current_state(session), entries, revision)
    else:
        state = replay(entries, base=base, upto=revision)
    if table is None:
        return state
    if key is None:
        return state[table]
    return state[table].get(_kt(table, key))


# ──────────────────────────────────────────────────────────────────
# Restore and undo: new entries through the layer
# ──────────────────────────────────────────────────────────────────


def _dependents(state: State, table: str, row: Mapping[str, Any]) -> list[tuple[str, dict]]:
    """Rows of ``state`` that cascade from ``row`` (``ON DELETE CASCADE``), in the order to
    insert them: each row before its own dependents."""
    out: list[tuple[str, dict]] = []
    spec = LAYER_REGISTRY[table]
    for child in LAYER_REGISTRY.values():
        for fk in child.table.foreign_keys:
            if fk.column.table is spec.table and (fk.ondelete or "").upper() == "CASCADE":
                for dependent in state[child.name].values():
                    if dependent[fk.parent.name] == row[fk.column.name]:
                        out.append((child.name, dependent))
                        out.extend(_dependents(state, child.name, dependent))
    return out


async def restore_entity(
    session: AsyncSession,
    configuration_id: int,
    table: str,
    key: Mapping[str, Any],
    as_of_revision: int,
    *,
    actor: str,
    note: str = "",
    channel: str = "admin_restore",
    group_id: str | None = None,
) -> WriteResult:
    """Put one row back as it was at ``as_of_revision``: a deleted row with its dependents,
    or an edited row's old values.  A new entry (``source = restore``)."""
    then = await as_of(session, configuration_id, as_of_revision)
    spec = LAYER_REGISTRY[table]
    kt = spec.key_tuple(spec.key_of(key))
    old = then[table].get(kt)
    if old is None:
        raise MissingKey(f"{table}: {dict(key)!r} did not exist at revision {as_of_revision}")
    now = await current_state(session)
    ops: list[dict] = []
    if kt not in now[table]:
        for name, row in [(table, old)] + _dependents(then, table, old):
            child = LAYER_REGISTRY[name]
            if child.key_tuple(child.key_of(row)) not in now[name]:
                ops.append({"op": "insert", "table": name, "key": child.key_of(row), "row": dict(row)})
    else:
        changed = {c: v for c, v in old.items() if now[table][kt][c] != v}
        if changed:
            ops.append({"op": "update", "table": table, "key": spec.key_of(now[table][kt]),
                        "set": changed})
    return await write_immediate(
        session, ops=ops, source="restore", actor=actor, channel=channel,
        note=note or f"restore {table} {dict(key)!r} as of revision {as_of_revision}",
        configuration_id=configuration_id, group_id=group_id,
    )


def inverse_ops(entries: Sequence[Mapping[str, Any]]) -> list[dict]:
    """The ops that undo ``entries`` (newest entry first, each entry's ops last first)."""
    ops: list[dict] = []
    for entry in sorted(entries, key=lambda e: e["revision"], reverse=True):
        for op, old in reversed(list(zip(entry["resolved"], entry["before"]))):
            spec = LAYER_REGISTRY[op["table"]]
            if op["op"] == "insert":
                ops.append({"op": "delete", "table": op["table"], "key": op["key"]})
            elif op["op"] == "update":
                ops.append({
                    "op": "update", "table": op["table"],
                    "key": spec.key_of({**old, **op["set"]}),
                    "set": {c: old[c] for c in op["set"]},
                })
            else:
                ops.append({"op": "insert", "table": op["table"], "key": op["key"],
                            "row": dict(old)})
    return ops


async def undo(
    session: AsyncSession,
    configuration_id: int = GLOBAL_CONFIGURATION_ID,
    *,
    entry_id: int | None = None,
    group_id: str | None = None,
    actor: str,
    note: str = "",
    channel: str = "admin_undo",
    new_group_id: str | None = None,
) -> WriteResult:
    """Undo one entry (by id) or every entry of a ``group_id`` in this configuration, as one
    new entry (``source = restore``).  Raises when a later change makes the inverse not apply."""
    if (entry_id is None) == (group_id is None):
        raise JournalError("undo takes an entry_id or a group_id")
    if entry_id is not None:
        entries = [
            e for e in await read_entries(session, configuration_id) if e["id"] == entry_id
        ]
    else:
        entries = await read_entries(session, configuration_id, group_id=group_id)
    if not entries:
        raise MissingKey("no such journal entry in this configuration")
    revisions = ", ".join(str(e["revision"]) for e in entries)
    return await write_immediate(
        session, ops=inverse_ops(entries), source="restore", actor=actor, channel=channel,
        note=note or f"undo revision {revisions}", configuration_id=configuration_id,
        group_id=new_group_id,
    )


# ──────────────────────────────────────────────────────────────────
# Provenance
# ──────────────────────────────────────────────────────────────────


async def provenance(
    session: AsyncSession, configuration_id: int, table: str, key: Mapping[str, Any]
) -> dict:
    """Where a row came from: ``{"from_starting_conceptual_state": True}`` when no entry
    after the baseline entry (``standard_load`` or ``creation``) touches it, else its last
    entry's source, actor, revision and version.  ``text`` is the wording the Admin view shows."""
    spec = LAYER_REGISTRY[table]
    wanted = spec.key_tuple(spec.key_of(key))
    last = None
    for entry in sorted(await read_entries(session, configuration_id),
                        key=lambda e: e["revision"], reverse=True):
        if any(_touches(op, entry_before, wanted, table)
               for op, entry_before in zip(entry["resolved"], entry["before"])):
            last = entry
            break
    if last is None or last["source"] in BASELINE_SOURCES:
        return {"from_starting_conceptual_state": True,
                "text": "from the Starting Conceptual State"}
    version = last["episode_version"] if last["episode_version"] is not None else last["revision"]
    return {
        "from_starting_conceptual_state": False,
        "source": last["source"], "actor": last["actor"], "revision": last["revision"],
        "version": version,
        "text": f"changed by source {last['source']}, actor {last['actor']}, at version {version}",
    }


def _touches(op: Mapping[str, Any], before: Any, wanted: tuple, table: str) -> bool:
    if op["table"] != table:
        return False
    spec = LAYER_REGISTRY[table]
    if spec.key_tuple(op["key"]) == wanted:
        return True
    if op["op"] == "update":  # a re-key: the row now has another key
        return spec.key_tuple(spec.key_of({**before, **op["set"]})) == wanted
    return False


# ──────────────────────────────────────────────────────────────────
# verify-journal
# ──────────────────────────────────────────────────────────────────


@dataclass
class VerifyReport:
    ok: bool
    configuration_id: int
    revision: int
    entries: int
    problems: list[str] = field(default_factory=list)


def _state_diff(a: State, b: State, label_a: str, label_b: str, limit: int = 5) -> list[str]:
    out: list[str] = []
    for table in sorted(a):
        for kt in sorted(set(a[table]) | set(b[table]), key=repr):
            if a[table].get(kt) != b[table].get(kt):
                where = f"in {label_a} only" if kt not in b[table] else (
                    f"in {label_b} only" if kt not in a[table] else "differs")
                out.append(f"{table} {kt!r} {where}")
                if len(out) >= limit:
                    return out
    return out


async def verify_journal(
    session: AsyncSession,
    configuration_id: int = GLOBAL_CONFIGURATION_ID,
    *,
    current: State | None = None,
) -> VerifyReport:
    """Replay the journal and compare with the current-state tables and ``config_hash``.

    Checks that the revisions run 1..n and equal the configuration's ``revision``; that
    replay from nothing equals the current state; that reconstructing backwards by the
    before-images reaches nothing; and that the recomputed ``config_hash`` equals the
    stored one.  For a session's configuration pass ``current`` (its stored current state,
    from C8); the hash check is the global configuration's.  A write made outside the
    application shows up as a difference.
    """
    configuration = (
        await session.execute(
            select(_CONFIGURATIONS).where(_CONFIGURATIONS.c.id == configuration_id)
        )
    ).mappings().first()
    if configuration is None:
        raise JournalError(f"configuration {configuration_id} does not exist")
    entries = await read_entries(session, configuration_id)
    report = VerifyReport(True, configuration_id, configuration["revision"], len(entries))
    problems = report.problems

    if [e["revision"] for e in entries] != list(range(1, len(entries) + 1)):
        problems.append("the entries' revisions are not 1..n without a gap")
    if configuration["revision"] != len(entries):
        problems.append(
            f"configuration revision {configuration['revision']} but {len(entries)} entries"
        )
    is_global = configuration["kind"] == KIND_GLOBAL
    if is_global:
        current = await current_state(session)
    if not problems and current is not None:
        try:
            replayed = replay(entries)
            if replayed != current:
                problems.append(
                    "replay differs from the current-state tables: "
                    + "; ".join(_state_diff(replayed, current, "replay", "tables"))
                )
            back = reconstruct(current, entries, 0)
            if back != empty_state():
                problems.append("reconstruction by before-images does not reach the empty start")
        except ReplayError as exc:
            problems.append(f"the recorded ops do not replay: {exc}")
    if is_global:
        digest = await compute_config_hash(session)
        if digest is None:
            problems.append("config_hash cannot be recomputed: the tables do not load")
        elif configuration["config_hash"] != digest:
            problems.append(
                f"stored config_hash {configuration['config_hash']} but the tables hash to {digest}"
            )
    report.ok = not problems
    return report
