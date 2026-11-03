"""Status, diff, reset to the Metacat Standard Configuration, restore-selected and verify.

The Admin view's configuration-wide actions and the command line
(``python -m server.config ...``) share these functions.  Each takes a configuration (the
global one, id 1, by default, or a Training Mode Session's configuration).  The Metacat
Standard Configuration is the reference for both.

* The *reference* is the Metacat Standard Configuration as the seed files hold it, read once
  and kept read only (``document_from_standard_files``).  Nothing here writes the files.
* ``status`` and ``diff`` compare the configuration in the database with the reference, row
  by row (per table and natural key).  The count is information only.
* ``reset_to_standard`` and ``restore_selected`` turn the comparison into resolved ops and
  write them through the journal layer (``source = reset`` or ``restore``), so each is one
  journal entry with its before-images, and undo can reverse it.  They touch configuration
  tables only: runs, Episodic Memory and sessions are not read or written.
* ``verify_journal`` is ``journal_views.verify_journal``.

Reaching the next run is the configuration store's job (C3's post-commit hook in the
journal layer), not this module's.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.config import SEED_DATA_DIR
from server.models.configuration_state import ConfigurationState
from server.models.journal import GLOBAL_CONFIGURATION_ID, KIND_GLOBAL, Configuration
from server.services import config_document as cd
from server.services import configurations, journal, journal_views

SOURCE_RESET = "reset"
SOURCE_RESTORE = "restore"

CHANGE_ADDED = "added"      # in the configuration, not in the reference
CHANGE_REMOVED = "removed"  # in the reference, not in the configuration
CHANGE_CHANGED = "changed"  # in both, with different values


class ConfigurationAdminError(Exception):
    """A request these functions cannot carry out; the message says why."""


UnknownConfiguration = configurations.UnknownConfiguration


class UnknownRow(ConfigurationAdminError):
    """A row named for restore-selected is not a table and natural key of the configuration."""


# ──────────────────────────────────────────────────────────────────
# The reference and the current document
# ──────────────────────────────────────────────────────────────────

_reference_cache: dict[str, cd.ConfigDocument] = {}


def reference_document(seed_dir: str | None = None) -> cd.ConfigDocument:
    """The Metacat Standard Configuration as a read-only document, read from the files once."""
    seed_dir = seed_dir or SEED_DATA_DIR
    if seed_dir not in _reference_cache:
        _reference_cache[seed_dir] = cd.document_from_standard_files(seed_dir)
    return _reference_cache[seed_dir]


async def _require(session: AsyncSession, configuration_id: int) -> Configuration:
    row = (
        await session.execute(select(Configuration).where(Configuration.id == configuration_id))
    ).scalar_one_or_none()
    if row is None:
        raise UnknownConfiguration(f"configuration {configuration_id} does not exist")
    return row


# ──────────────────────────────────────────────────────────────────
# Row-level comparison
# ──────────────────────────────────────────────────────────────────


def _key_dict(table: str, key: tuple) -> dict[str, Any]:
    return dict(zip(cd.key_columns(table), key))


def compare(current: cd.ConfigDocument, reference: cd.ConfigDocument) -> list[dict[str, Any]]:
    """Rows added, removed or changed in *current* against *reference*, per table and key.

    An *added* row is one the reference lacks; a *removed* row is one the reference has and
    the configuration lacks.  A *changed* row names the columns that differ, with both values.
    """
    out: list[dict[str, Any]] = []
    for table in cd.TABLE_NAMES:
        cur, ref = current.tables[table], reference.tables[table]
        if cur is ref:
            continue
        for key, row in cur.items():
            if key not in ref:
                out.append({"table": table, "key": _key_dict(table, key),
                            "change": CHANGE_ADDED, "current": dict(row), "standard": None,
                            "columns": []})
        for key, row in ref.items():
            if key not in cur:
                out.append({"table": table, "key": _key_dict(table, key),
                            "change": CHANGE_REMOVED, "current": None, "standard": dict(row),
                            "columns": []})
                continue
            mine = cur[key]
            if mine != row:
                columns = sorted(c for c in set(mine) | set(row) if mine.get(c) != row.get(c))
                out.append({"table": table, "key": _key_dict(table, key),
                            "change": CHANGE_CHANGED,
                            "current": {c: mine.get(c) for c in columns},
                            "standard": {c: row.get(c) for c in columns},
                            "columns": columns})
    return out


def _order(ops: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deletes first and children before parents, then updates and inserts parents first.

    The journal layer deletes a row's ``ON DELETE CASCADE`` dependents itself, so a later
    delete of one of them would find nothing; deleting the later tables first avoids that.
    """
    position = {t: i for i, t in enumerate(cd.TABLE_NAMES)}
    deletes = [o for o in ops if o["op"] == "delete"]
    rest = [o for o in ops if o["op"] != "delete"]
    deletes.sort(key=lambda o: -position[o["table"]])  # stable: keeps a table's own order
    return deletes + rest


def _ops_for_rows(
    current: cd.ConfigDocument, reference: cd.ConfigDocument, changes: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    ops: list[dict[str, Any]] = []
    for ch in changes:
        table, key = ch["table"], ch["key"]
        kind = ch["change"]
        if kind == CHANGE_ADDED:
            ops.append({"op": "delete", "table": table, "key": key})
        elif kind == CHANGE_REMOVED:
            ops.append({"op": "insert", "table": table, "key": key,
                        "row": dict(reference.tables[table][tuple(key.values())])})
        else:
            ref_row = reference.tables[table][tuple(key.values())]
            ops.append({"op": "update", "table": table, "key": key,
                        "set": {c: ref_row.get(c) for c in ch["columns"]}})
    return _order(ops)


# ──────────────────────────────────────────────────────────────────
# The functions
# ──────────────────────────────────────────────────────────────────


async def status(
    session: AsyncSession, configuration_id: int = GLOBAL_CONFIGURATION_ID
) -> dict[str, Any]:
    """The revision, ``config_hash``, ``standard_hash`` and the count of differing rows.

    ``standard_hash`` is the digest of the Metacat Standard Configuration files the database
    was first loaded from (provenance only).  ``standard_config_hash`` is the ``config_hash``
    of the start-up reference, which is what ``config_hash`` is compared with.
    """
    row = await _require(session, configuration_id)
    current = await configurations.current_document(session, configuration_id)
    reference = reference_document()
    # The files digest and origin are the global configuration's first load (provenance only).
    state = (
        await session.execute(select(ConfigurationState).where(ConfigurationState.id == 1))
    ).scalar_one_or_none() if row.kind == KIND_GLOBAL else None
    differing = len(compare(current, reference))
    config_hash = cd.config_hash(current)
    standard_config_hash = cd.config_hash(reference)
    return {
        "configuration_id": configuration_id,
        "kind": row.kind,
        "revision": row.revision,
        "config_hash": config_hash,
        "standard_hash": state.standard_hash if state else None,
        "origin": state.origin if state else None,
        "loaded_at": state.loaded_at.isoformat() if state and state.loaded_at else None,
        "standard_config_hash": standard_config_hash,
        "differs_rows": differing,
        "equals_standard": config_hash == standard_config_hash,
    }


async def diff(
    session: AsyncSession, configuration_id: int = GLOBAL_CONFIGURATION_ID
) -> dict[str, Any]:
    """Rows added, removed or changed against the start-up reference."""
    row = await _require(session, configuration_id)
    changes = compare(await configurations.current_document(session, configuration_id), reference_document())
    return {
        "configuration_id": configuration_id,
        "revision": row.revision,
        "count": len(changes),
        "added": sum(c["change"] == CHANGE_ADDED for c in changes),
        "removed": sum(c["change"] == CHANGE_REMOVED for c in changes),
        "changed": sum(c["change"] == CHANGE_CHANGED for c in changes),
        "rows": changes,
    }


def _result(configuration_id: int, result: journal.WriteResult, **extra: Any) -> dict[str, Any]:
    return {
        "configuration_id": configuration_id,
        "revision": result.revision,
        "wrote": result.changed,
        "entry_id": result.entry_id,
        "ops": len(result.resolved),
        "config_hash": result.config_hash,
        **extra,
    }


async def reset_to_standard(
    session: AsyncSession,
    configuration_id: int = GLOBAL_CONFIGURATION_ID,
    *,
    actor: str = "admin",
    channel: str = "admin_config",
    note: str = "",
) -> dict[str, Any]:
    """Make the configuration equal the Metacat Standard Configuration, as one journal entry.

    ``source = reset``.  A configuration that already equals the reference gets no entry
    (nothing changed).  Runs, Episodic Memory and sessions are untouched.
    """
    await _require(session, configuration_id)
    ops = _order(cd.diff(await configurations.current_document(session, configuration_id), reference_document()))
    if not ops:
        row = await _require(session, configuration_id)
        return {"configuration_id": configuration_id, "revision": row.revision, "wrote": False,
                "entry_id": None, "ops": 0, "config_hash": row.config_hash}
    result = await journal.write_immediate(
        session, ops=ops, source=SOURCE_RESET, actor=actor, configuration_id=configuration_id,
        channel=channel, note=note or "Reset to the Metacat Standard Configuration",
    )
    return _result(configuration_id, result)


async def restore_selected(
    session: AsyncSession,
    rows: Sequence[Mapping[str, Any]],
    configuration_id: int = GLOBAL_CONFIGURATION_ID,
    *,
    actor: str = "admin",
    channel: str = "admin_config",
    note: str = "",
) -> dict[str, Any]:
    """Restore the chosen rows (``{"table": ..., "key": {...}}``) to the reference, as one entry.

    ``source = restore``.  Only rows that differ are touched; a chosen row that already
    equals the reference is listed in ``skipped``.  A table or key that does not exist in
    either the configuration or the reference raises :class:`UnknownRow`.
    """
    await _require(session, configuration_id)
    current = await configurations.current_document(session, configuration_id)
    reference = reference_document()
    by_row = {(c["table"], tuple(c["key"].values())): c for c in compare(current, reference)}
    chosen: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for item in rows:
        table, key = item.get("table"), item.get("key")
        if table not in cd.TABLE_NAMES or not isinstance(key, Mapping):
            raise UnknownRow(f"{table!r} with key {key!r} is not a configuration table and key")
        columns = cd.key_columns(table)
        if set(key) != set(columns):
            raise UnknownRow(f"{table}: the key columns are {list(columns)}, not {sorted(key)}")
        tup = tuple("" if key[c] is None else key[c] for c in columns)
        found = by_row.get((table, tup))
        if found is not None:
            chosen.append(found)
        elif tup in current.tables[table] or tup in reference.tables[table]:
            skipped.append({"table": table, "key": dict(key)})
        else:
            raise UnknownRow(f"{table}: no row with key {dict(key)!r} in the configuration "
                             "or the Metacat Standard Configuration")
    ops = _ops_for_rows(current, reference, chosen)
    if not ops:
        row = await _require(session, configuration_id)
        return {"configuration_id": configuration_id, "revision": row.revision, "wrote": False,
                "entry_id": None, "ops": 0, "config_hash": row.config_hash, "skipped": skipped}
    result = await journal.write_immediate(
        session, ops=ops, source=SOURCE_RESTORE, actor=actor, configuration_id=configuration_id,
        channel=channel,
        note=note or f"Restored {len(chosen)} row(s) to the Metacat Standard Configuration",
    )
    return _result(configuration_id, result, skipped=skipped)


async def verify_journal(
    session: AsyncSession, configuration_id: int = GLOBAL_CONFIGURATION_ID
) -> dict[str, Any]:
    """Replay the journal and compare with the stored current state and ``config_hash``.

    The global configuration replays from nothing and compares with its tables.  A session's
    configuration replays its entries after the base snapshot onto the base and compares with
    its stored current state, then undoes them by their before-images and compares with the
    base.
    """
    row = await _require(session, configuration_id)
    if row.kind == KIND_GLOBAL:
        return asdict(await journal_views.verify_journal(session, configuration_id))
    return asdict(await _verify_session(session, row))


def _rows_equal(a: cd.ConfigDocument, b: cd.ConfigDocument) -> bool:
    """Same rows in every table, without regard to the order of a table."""
    return all(dict(a.tables[t]) == dict(b.tables[t]) for t in cd.TABLE_NAMES)


async def _verify_session(session: AsyncSession, row: Configuration) -> journal_views.VerifyReport:
    configuration_id = row.id
    entries = await journal_views.read_entries(session, configuration_id)
    report = journal_views.VerifyReport(True, configuration_id, row.revision, len(entries))
    problems = report.problems
    if [e["revision"] for e in entries] != list(range(1, len(entries) + 1)):
        problems.append("the entries' revisions are not 1..n without a gap")
    if row.revision != len(entries):
        problems.append(f"configuration revision {row.revision} but {len(entries)} entries")
    base = await configurations.base_document(session, configuration_id)
    current = await configurations.current_document(session, configuration_id)
    if not problems:
        after = [e for e in entries if e["revision"] > base.version]
        ops = [op for e in after for op in e["resolved"]]
        try:
            replayed = cd.apply_resolved(base, ops, version=row.revision)
            if not replayed.content_equals(current):
                problems.append("replaying the journal onto the base snapshot does not give "
                                "the stored current state")
            back = cd.apply_resolved(current, journal_views.inverse_ops(after))
            if not _rows_equal(back, base):
                problems.append("undoing the journal by its before-images does not reach the "
                                "base snapshot")
        except Exception as exc:  # the recorded ops do not apply
            problems.append(f"the recorded ops do not replay: {exc}")
    digest = cd.config_hash(current)
    if row.config_hash != digest:
        problems.append(f"stored config_hash {row.config_hash} but the state hashes to {digest}")
    if row.base_snapshot_hash != cd.config_hash(base):
        problems.append("the base snapshot does not hash to base_snapshot_hash")
    report.ok = not problems
    return report
