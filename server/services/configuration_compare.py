"""Compare two configurations and apply rows from one to the other (configuration plan 3.10.6).

* ``compare(session, a, b)``: a row-level diff by table and natural key between any two
  configurations, or one and the Metacat Standard Configuration.  ``a`` and ``b`` are a
  configuration id, the word ``standard`` or the word ``training-v2`` (the v2.0 Base).  A row is *added* when only ``a`` has it,
  *removed* when only ``b`` has it, and *changed* when both have it with different values
  (the differing columns, with both sides' values).
* ``apply_from(session, target, source, rows, ...)``: make the chosen rows of ``target`` equal
  those of ``source`` (a configuration or ``standard``).  It generalises restore-selected,
  which is the case ``source = standard``.  It is an ordinary change batch (``source =
  restore``) sent through the change API, so it has a preview (``dry_run``), a reason (the
  note), a journal entry and a revision, and a live session takes it in memory.

Reads only stored state, like every configuration read until a live source is registered.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from server.services import config_document as cd
from server.services import configuration_admin as admin
from server.services import configurations
from server.services.configuration_writer import ChangeService

STANDARD = "standard"
STANDARD_NAME = "Metacat Standard Configuration"
#: The Training Mode Base Configuration, v2.0 (``training_base/v2.0/``), resolved over the
#: Standard when it is read.  A side like ``standard``: read-only, never a target.
V2_BASE = "training-v2"
V2_BASE_NAME = "Training Mode Base Configuration, v2.0"
_NAMED = (STANDARD, V2_BASE)

SOURCE_RESTORE = "restore"


class CompareError(configurations.ConfigurationError):
    """A comparison or apply-from the request cannot name."""


def parse_ref(ref: Any) -> int | str:
    """A configuration id or ``standard`` from the text a route was given."""
    if isinstance(ref, int) and not isinstance(ref, bool):
        return ref
    if isinstance(ref, str):
        if ref.strip().lower() in _NAMED:
            return ref.strip().lower()
        if ref.strip().isdigit():
            return int(ref.strip())
    raise CompareError(f"{ref!r} is not a configuration id, 'standard' or 'training-v2'")


async def _side(session: AsyncSession, ref: int | str) -> tuple[dict[str, Any], cd.ConfigDocument]:
    """``({id, name, mode_label, revision}, document)`` of one side."""
    if ref == STANDARD:
        return ({"id": STANDARD, "name": STANDARD_NAME, "mode_label": STANDARD_NAME,
                 "revision": None}, admin.reference_document())
    if ref == V2_BASE:
        document = configurations._resolve_training_base(V2_BASE).document
        return ({"id": V2_BASE, "name": V2_BASE_NAME, "mode_label": V2_BASE_NAME,
                 "revision": None}, document)
    row = await configurations.get_row(session, int(ref))
    document = await configurations.current_document(session, int(ref))
    summary = await configurations.summary(session, int(ref))
    return ({"id": row["id"], "name": row["name"], "mode_label": summary["mode_label"],
             "revision": row["revision"]}, document)


async def compare(session: AsyncSession, a: Any, b: Any) -> dict[str, Any]:
    """The rows added, removed or changed in *a* against *b*."""
    ref_a, ref_b = parse_ref(a), parse_ref(b)
    head_a, doc_a = await _side(session, ref_a)
    head_b, doc_b = await _side(session, ref_b)
    rows = []
    for item in admin.compare(doc_a, doc_b):
        rows.append({
            "table": item["table"], "key": item["key"], "change": item["change"],
            "a": item["current"], "b": item["standard"], "columns": item["columns"],
        })
    return {
        "a": head_a, "b": head_b,
        "same": not rows,
        "count": len(rows),
        "added": sum(r["change"] == admin.CHANGE_ADDED for r in rows),
        "removed": sum(r["change"] == admin.CHANGE_REMOVED for r in rows),
        "changed": sum(r["change"] == admin.CHANGE_CHANGED for r in rows),
        "rows": rows,
    }


def _ops(
    target: cd.ConfigDocument, source: cd.ConfigDocument, changes: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Generic change-API ops that make the chosen rows of *target* equal *source*'s."""
    ops: list[dict[str, Any]] = []
    for ch in changes:
        table, key = ch["table"], ch["key"]
        if ch["change"] == admin.CHANGE_ADDED:  # only the target has it: remove it
            ops.append({"op": "delete", "table": table, "key": key})
        elif ch["change"] == admin.CHANGE_REMOVED:  # only the source has it: add it
            ops.append({"op": "insert", "table": table,
                        "row": dict(source.tables[table][tuple(key.values())])})
        else:
            src = source.tables[table][tuple(key.values())]
            ops.append({"op": "update", "table": table, "key": key,
                        "fields": {c: src.get(c) for c in ch["columns"]}})
    return admin._order(ops)


async def apply_from(
    session: AsyncSession,
    target_id: int,
    source: Any,
    rows: Sequence[Mapping[str, Any]],
    *,
    actor: str = "admin",
    note: str = "",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Make the chosen rows (``{"table", "key"}``) of configuration *target_id* equal *source*'s.

    Raises :class:`CompareError` for a source that is the target itself, and
    ``admin.UnknownRow`` for a row that neither side has.  A chosen row that already matches
    is listed in ``skipped``.  The change API's refusals (``ChangeError``) pass through.
    """
    ref = parse_ref(source)
    if ref == target_id:
        raise CompareError("a configuration cannot be applied from itself")
    await configurations.get_row(session, target_id)
    head, source_doc = await _side(session, ref)
    target_doc = await configurations.current_document(session, target_id)
    by_row = {(c["table"], tuple(c["key"].values())): c for c in admin.compare(target_doc, source_doc)}
    chosen: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for item in rows:
        table, key = item.get("table"), item.get("key")
        if table not in cd.TABLE_NAMES or not isinstance(key, Mapping):
            raise admin.UnknownRow(f"{table!r} with key {key!r} is not a configuration table and key")
        columns = cd.key_columns(table)
        if set(key) != set(columns):
            raise admin.UnknownRow(f"{table}: the key columns are {list(columns)}, not {sorted(key)}")
        tup = tuple("" if key[c] is None else key[c] for c in columns)
        found = by_row.get((table, tup))
        if found is not None:
            chosen.append(found)
        elif tup in target_doc.tables[table] or tup in source_doc.tables[table]:
            skipped.append({"table": table, "key": dict(key)})
        else:
            raise admin.UnknownRow(
                f"{table}: no row with key {dict(key)!r} in either configuration")
    ops = _ops(target_doc, source_doc, chosen)
    if not ops:
        row = await configurations.get_row(session, target_id)
        return {"ok": True, "configuration_id": target_id, "wrote": False, "persisted": False,
                "revision": row["revision"], "ops": 0, "skipped": skipped,
                "source": head["id"]}
    report = await ChangeService.apply(session, {
        "configuration_id": target_id, "source": SOURCE_RESTORE, "actor": actor,
        "channel": "admin_compare", "base_mode": "rebase", "dry_run": dry_run,
        "note": note or f"Applied {len(chosen)} row(s) from {head['name']}", "ops": ops,
    })
    report["wrote"] = bool(report.get("persisted"))
    report["ops"] = len(ops)
    report["skipped_rows"] = skipped
    report["source"] = head["id"]
    return report
