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
* ``list_entries``, ``get_entry`` and ``name_story`` are the History views (C13): the
  filtered journal (a live session's pending entries merged in, labelled "not yet saved"),
  one entry in full, and "where did this name go".  ``check_names`` says which names a
  memory holds that the configuration no longer has.

A *state* is ``{table: {key tuple: row}}`` where a row holds every column but the surrogate
``id`` (the same shape a journal records), so states from replay, reconstruction and the
tables compare with ``==``.
"""

from __future__ import annotations

import copy
from datetime import datetime
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


def state_of_document(document: Any) -> State:
    """A ``ConfigDocument``'s tables as a state (the same shape the journal records)."""
    state = empty_state()
    for name in state:
        state[name] = {kt: dict(row) for kt, row in document.tables[name].items()}
    return state


async def current_state_for(session: AsyncSession, configuration_id: int) -> State:
    """The stored current state of any configuration (a live session's memory is not here)."""
    from server.services import configurations

    if await _kind(session, configuration_id) == KIND_GLOBAL:
        return await current_state(session)
    return state_of_document(await configurations.current_document(session, configuration_id))


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
    A session's is read through ``configurations.config_at`` (its base snapshot plus the
    resolved ops), or, when ``base`` is given, replayed from that state.  A row that did
    not exist then is ``None``.  Stored revisions only: a live session's pending entries
    are not in the database.
    """
    if await _kind(session, configuration_id) == KIND_GLOBAL:
        entries = await read_entries(session, configuration_id)
        state = reconstruct(await current_state(session), entries, revision)
    elif base is not None:
        state = replay(await read_entries(session, configuration_id), base=base, upto=revision)
    else:
        from server.services import configurations

        state = state_of_document(await configurations.config_at(session, configuration_id, revision))
    if table is None:
        return state
    if table not in state:
        raise JournalError(f"{table!r} is not a configuration table")
    if key is None:
        return state[table]
    return state[table].get(_kt(table, key))


async def revision_at_time(session: AsyncSession, configuration_id: int, when: datetime) -> int:
    """The configuration's revision at ``when``: its last stored entry that happened (by
    ``occurred_at``) at or before it, or 0."""
    revision = 0
    for entry in await read_entries(session, configuration_id):
        if entry["occurred_at"] <= when:
            revision = entry["revision"]
    return revision


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
    now = await current_state_for(session, configuration_id)
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


# ──────────────────────────────────────────────────────────────────
# History views (C13): the filtered journal, one entry, a name's story
# ──────────────────────────────────────────────────────────────────

#: The tables whose rows are the names an Episodic Memory can hold, and what to call one.
NAME_TABLES: Mapping[str, str] = {
    "slipnet_node_defs": "node",
    "theme_relations": "theme relation",
    "codelet_type_defs": "codelet type",
}

NOT_YET_SAVED = "not yet saved"


def _op_counts(resolved: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts = {"insert": 0, "update": 0, "delete": 0}
    for op in resolved:
        counts[op["op"]] = counts.get(op["op"], 0) + 1
    return counts


def _entry_view(entry: Mapping[str, Any], *, detail: bool, pending: bool) -> dict:
    """One entry as the History shows it: the summary, plus the three bodies when ``detail``."""
    resolved = entry["resolved"] or []
    out = {
        "id": None if pending else entry["id"],
        "configuration_id": entry["configuration_id"],
        "revision": entry["revision"],
        "group_id": entry["group_id"],
        "source": entry["source"],
        "actor": entry["actor"],
        "channel": entry["channel"],
        "note": entry["note"],
        "causing_run_id": entry["causing_run_id"],
        "episode_version": entry["episode_version"],
        "config_hash": entry["config_hash"],
        "occurred_at": entry["occurred_at"],
        "recorded_at": None if pending else entry["recorded_at"],
        "counts": _op_counts(resolved),
        "tables": sorted({op["table"] for op in resolved}),
        "pending": pending,
        "saved": not pending,
        "label": NOT_YET_SAVED if pending else "",
    }
    if detail:
        out.update(proposed=entry["proposed"], resolved=resolved, before=entry["before"] or [])
    return out


def _key_filter(table: str | None, key: Mapping[str, Any] | None) -> tuple | None:
    if key is None:
        return None
    if table is None:
        raise JournalError("a key filter needs its table")
    if table not in LAYER_REGISTRY:
        raise JournalError(f"{table!r} is not a configuration table")
    spec = LAYER_REGISTRY[table]
    if set(key) != set(spec.key):
        raise JournalError(f"{table}: the key columns are {list(spec.key)}, not {sorted(key)}")
    return spec.key_tuple(key)


def _entry_matches(entry: Mapping[str, Any], table: str | None, wanted: tuple | None) -> bool:
    if table is None:
        return True
    before = entry["before"] or []
    for i, op in enumerate(entry["resolved"] or []):
        if op["table"] != table:
            continue
        if wanted is None or _touches(op, before[i] if i < len(before) else None, wanted, table):
            return True
    return False


def _pending_entries(session_id: int | None, stored_revisions: set[int]) -> tuple[list[dict], Any]:
    """A live session's pending entries (as dicts shaped like stored ones) and its live state.

    The live source's state carries them as ``pending`` (a list of ``journal.PendingEntry``);
    a source that reports none gives an empty list.  Entries whose revision is already stored
    are not repeated.
    """
    from dataclasses import asdict, is_dataclass

    from server.services.configuration_store import live_state

    live = live_state(session_id)
    if live is None:
        return [], None
    out = []
    for p in getattr(live, "pending", None) or []:
        d = asdict(p) if is_dataclass(p) else dict(p)
        if d["revision"] in stored_revisions:
            continue
        for k in ("channel", "note", "group_id", "causing_run_id", "episode_version", "config_hash"):
            d.setdefault(k, "" if k in ("channel", "note") else None)
        d["id"] = None
        out.append(d)
    return out, live


async def list_entries(
    session: AsyncSession,
    *,
    configuration_id: int | None = None,
    table: str | None = None,
    key: Mapping[str, Any] | None = None,
    source: str | None = None,
    actor: str | None = None,
    group_id: str | None = None,
    revision_from: int | None = None,
    revision_to: int | None = None,
    time_from: datetime | None = None,
    time_to: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
    detail: bool = False,
) -> dict:
    """The journal, filtered, newest first.

    Order: one configuration by revision; several by ``occurred_at`` then ``(configuration,
    revision)`` (never by row id or ``recorded_at``).  ``table`` keeps the entries that touch
    that table, and ``table`` with ``key`` those that touch that row (a re-key included).
    For one session configuration that is live, the pending entries are merged in with
    ``pending: true`` and the label "not yet saved"; ``live`` then says where it stands.
    """
    wanted = _key_filter(table, key)
    if table is not None and table not in LAYER_REGISTRY:
        raise JournalError(f"{table!r} is not a configuration table")
    stmt = select(_JOURNAL)
    for column, value in (
        (_JOURNAL.c.configuration_id, configuration_id), (_JOURNAL.c.source, source),
        (_JOURNAL.c.actor, actor), (_JOURNAL.c.group_id, group_id),
    ):
        if value is not None:
            stmt = stmt.where(column == value)
    if revision_from is not None:
        stmt = stmt.where(_JOURNAL.c.revision >= revision_from)
    if revision_to is not None:
        stmt = stmt.where(_JOURNAL.c.revision <= revision_to)
    if time_from is not None:
        stmt = stmt.where(_JOURNAL.c.occurred_at >= time_from)
    if time_to is not None:
        stmt = stmt.where(_JOURNAL.c.occurred_at <= time_to)
    rows = [dict(r) for r in (await session.execute(stmt)).mappings().all()]
    views = [(e, False) for e in rows if _entry_matches(e, table, wanted)]

    live_info = None
    if configuration_id is not None:
        from server.services import configurations

        row = await configurations.get_row(session, configuration_id)
        if row["kind"] != KIND_GLOBAL:
            stored = {e["revision"] for e in await read_entries(session, configuration_id)}
            pending, live = _pending_entries(row["session_id"], stored)
            if live is not None:
                live_info = {"state": live.state, "revision": live.revision,
                             "saved_through": live.saved_through, "unsaved": live.unsaved}
            for p in pending:
                p["configuration_id"] = configuration_id
                if source not in (None, p["source"]) or actor not in (None, p["actor"]):
                    continue
                if group_id is not None and p["group_id"] != group_id:
                    continue
                if revision_from is not None and p["revision"] < revision_from:
                    continue
                if revision_to is not None and p["revision"] > revision_to:
                    continue
                if time_from is not None and p["occurred_at"] < time_from:
                    continue
                if time_to is not None and p["occurred_at"] > time_to:
                    continue
                if _entry_matches(p, table, wanted):
                    views.append((p, True))

    if configuration_id is not None:
        views.sort(key=lambda v: v[0]["revision"], reverse=True)
    else:
        views.sort(key=lambda v: (v[0]["occurred_at"], v[0]["configuration_id"], v[0]["revision"]),
                   reverse=True)
    page = views[offset: offset + limit]
    return {
        "entries": [_entry_view(e, detail=detail, pending=pending) for e, pending in page],
        "total": len(views),
        "limit": limit,
        "offset": offset,
        "live": live_info,
    }


async def get_entry(session: AsyncSession, entry_id: int) -> dict:
    """One stored entry in full: what was proposed, what changed, and the before-images."""
    row = (
        await session.execute(select(_JOURNAL).where(_JOURNAL.c.id == entry_id))
    ).mappings().first()
    if row is None:
        raise MissingKey(f"no journal entry {entry_id}")
    return _entry_view(dict(row), detail=True, pending=False)


def _proposed_ops(proposed: Any) -> list[dict]:
    if isinstance(proposed, Mapping):
        proposed = proposed.get("ops", [])
    if not isinstance(proposed, (list, tuple)):
        return []
    return [p for p in proposed if isinstance(p, Mapping)]


def _name_events(entry: Mapping[str, Any], name: str) -> list[dict]:
    """What one entry did to ``name`` (a node, theme relation or codelet type)."""
    resolved = entry["resolved"] or []
    before = entry["before"] or []
    asked = _proposed_ops(entry["proposed"])
    events: list[dict] = []
    for i, op in enumerate(resolved):
        table = op["table"]
        if table not in NAME_TABLES:
            continue
        kind = NAME_TABLES[table]
        key_name = op["key"].get("name")
        if op["op"] == "insert" and key_name == name:
            events.append({"event": "created", "kind": kind, "table": table})
        elif op["op"] == "delete" and key_name == name:
            into = None
            for q in asked:
                if q.get("op") == "merge_nodes" and q.get("drop") == name:
                    into = q.get("keep")
            if into is None:  # a merge not asked as one: references moved from this name
                for j, other in enumerate(resolved):
                    was = before[j] if j < len(before) else None
                    if other["op"] == "update" and was:
                        for col, new in other["set"].items():
                            if was.get(col) == name and isinstance(new, str) and new != name:
                                into = new
            events.append({"event": "merged_into" if into else "deleted", "kind": kind,
                           "table": table, "into": into})
        elif op["op"] == "update" and "name" in op["set"]:
            if key_name == name and op["set"]["name"] != name:
                events.append({"event": "renamed", "kind": kind, "table": table,
                               "to": op["set"]["name"]})
            elif op["set"]["name"] == name and key_name != name:
                events.append({"event": "renamed_from", "kind": kind, "table": table,
                               "from": key_name})
        elif op["op"] == "update" and key_name == name:
            events.append({"event": "edited", "kind": kind, "table": table,
                           "columns": sorted(op["set"])})
    return _net_reinserts(events, resolved, before, name)


def _net_reinserts(events: list[dict], resolved: Sequence[Mapping[str, Any]],
                   before: Sequence[Any], name: str) -> list[dict]:
    """A delete and an insert of the same row in one entry is a rewrite (the cascade of a
    node rename re-keys the theme relation that names the node): report one ``edited``."""
    out: list[dict] = []
    for table in {e["table"] for e in events}:
        gone = [e for e in events if e["table"] == table and e["event"] in ("deleted", "merged_into")]
        made = [e for e in events if e["table"] == table and e["event"] == "created"]
        if gone and made:
            old = next((before[i] for i, op in enumerate(resolved)
                        if op["table"] == table and op["op"] == "delete"
                        and op["key"].get("name") == name), None) or {}
            new = next((op["row"] for op in resolved
                        if op["table"] == table and op["op"] == "insert"
                        and op["key"].get("name") == name), {})
            columns = sorted(c for c in new if new[c] != old.get(c))
            out.append({"event": "edited", "kind": gone[0]["kind"], "table": table,
                        "columns": columns})
            events = [e for e in events if e not in gone and e not in made]
    return events + out


def _describe(event: Mapping[str, Any], name: str) -> str:
    e = event["event"]
    kind = event["kind"]
    if e == "created":
        return f"the {kind} {name!r} was created"
    if e == "deleted":
        return f"the {kind} {name!r} was deleted"
    if e == "merged_into":
        return f"the {kind} {name!r} was merged into {event['into']!r}"
    if e == "renamed":
        return f"the {kind} {name!r} was renamed {event['to']!r}"
    if e == "renamed_from":
        return f"the {kind} {event['from']!r} was renamed {name!r}"
    return f"the {kind} {name!r} was edited ({', '.join(event['columns'])})"


async def _names_present(session: AsyncSession, configuration_id: int) -> dict[str, str]:
    """``{name: kind}`` for every name the configuration has now (a live session's memory
    state when it is live, else the stored one)."""
    from server.services import configurations
    from server.services.configuration_store import live_state

    row = await configurations.get_row(session, configuration_id)
    live = live_state(row["session_id"]) if row["kind"] != KIND_GLOBAL else None
    if live is not None:
        tables = {t: live.document.tables[t].values() for t in NAME_TABLES}
    else:
        state = await current_state_for(session, configuration_id)
        tables = {t: state[t].values() for t in NAME_TABLES}
    present: dict[str, str] = {}
    for table, rows in tables.items():
        for r in rows:
            present.setdefault(r["name"], NAME_TABLES[table])
    return present


async def name_story(
    session: AsyncSession, name: str, configuration_id: int = GLOBAL_CONFIGURATION_ID,
    *, _present: dict[str, str] | None = None, _depth: int = 0,
) -> dict:
    """Where a node, theme relation or codelet type name went: its events from the journal,
    oldest first, whether it resolves now, the name it carries now (after renames and
    merges) and, when it is gone, the revision to restore it from."""
    present = _present if _present is not None else await _names_present(session, configuration_id)
    entries = await read_entries(session, configuration_id)
    events: list[dict] = []
    for entry in entries:
        for ev in _name_events(entry, name):
            events.append({
                **ev, "text": _describe(ev, name),
                "entry_id": entry["id"], "revision": entry["revision"],
                "source": entry["source"], "actor": entry["actor"], "channel": entry["channel"],
                "note": entry["note"], "group_id": entry["group_id"],
                "occurred_at": entry["occurred_at"],
            })
    resolves = name in present
    current_name = name if resolves else None
    restorable = None
    last = next((e for e in reversed(events) if e["event"] != "edited"), None)
    if not resolves and last is not None:
        successor = last.get("to") or last.get("into")
        if successor is not None and _depth < 20:
            current_name = (await name_story(
                session, successor, configuration_id, _present=present, _depth=_depth + 1
            ))["current_name"]
        if last["event"] in ("deleted", "merged_into", "renamed"):
            table = next(t for t, k in NAME_TABLES.items() if k == last["kind"])
            restorable = {"table": table, "key": {"name": name},
                          "as_of_revision": last["revision"] - 1, "entry_id": last["entry_id"]}
    if resolves:
        text = f"{name!r} is in the configuration"
        if events:
            text += f"; {events[-1]['text']} at revision {events[-1]['revision']}"
    elif not events:
        text = f"{name!r} is not in the configuration and the journal has no record of it"
    else:
        at = last or events[-1]
        text = (f"{at['text']} at revision {at['revision']} by source {at['source']}, "
                f"actor {at['actor']}")
        if current_name and current_name != name:
            text += f"; it is now {current_name!r}"
    return {
        "name": name, "configuration_id": configuration_id, "resolves": resolves,
        "kind": present.get(name), "current_name": current_name, "events": events,
        "restorable": restorable, "text": text,
    }


async def check_names(
    session: AsyncSession, names: Sequence[str], configuration_id: int = GLOBAL_CONFIGURATION_ID
) -> dict:
    """Which of ``names`` the configuration lacks, each with its story.  The panels call it
    with the names found in an Episodic Memory: ``unresolved`` is the panel's list."""
    present = await _names_present(session, configuration_id)
    unique = sorted({n for n in names if isinstance(n, str) and n})
    unresolved = [await name_story(session, n, configuration_id, _present=present)
                  for n in unique if n not in present]
    return {"configuration_id": configuration_id, "checked": len(unique),
            "unresolved": unresolved}
