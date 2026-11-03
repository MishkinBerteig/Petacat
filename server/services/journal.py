"""The journal layer: the only writer of configuration (configuration plan 3.11).

One layer over SQLAlchemy writes every configuration table and every journal table.  No
statement outside this module does (``tests/architecture/test_journal_only_writer.py``
enforces it over the table list computed by model introspection), and nothing in it updates
or deletes a journal entry.  There are no database triggers: the layer being the only
writer, that test, and ``verify_journal`` (in ``journal_views.py``) are the guarantee.

Two doors
=========
``write_immediate(session, ...)``
    Any route, in its own transaction: applies a batch of resolved ops to the
    configuration's current-state tables, bumps the configuration's ``revision`` and
    appends the entry, all in one transaction.  The global configuration (Metacat Mode,
    configuration 1) is written this way.  A session's configuration state belongs to the
    configuration entity (C8); until it lands, ``write_immediate`` refuses a non-global
    configuration.

``write_deferred(session, ...)``
    Callable only from a session's Stop write.  Appends entries that were produced in
    memory earlier, each carrying its own ``occurred_at``; ``recorded_at`` is the Stop
    write.  It writes the entries and the revision and nothing else: the Stop write writes
    the session's runs, memory snapshot and current state in the same transaction, passing
    ``commit=False``.  The architecture test allows no caller outside its allowlist.

Resolved ops
============
Plain dicts, in application order, naming a table by its database name and a row by its
natural key (``server/services/config_registry.py``)::

    {"op": "insert", "table": t, "key": {...}, "row": {...}}
    {"op": "update", "table": t, "key": {...}, "set": {...}}
    {"op": "delete", "table": t, "key": {...}}

The layer returns the ops it applied (``WriteResult.resolved``), which can differ from the
ops it was given:

* an insert's ``row`` is completed with the stored defaults (``sort_order``, ``ordinal``),
  so every value is absolute, and never carries the surrogate ``id`` (not stable across
  configurations);
* an update's ``set`` keeps only the columns that change; an update that changes nothing
  is dropped;
* a delete is preceded by explicit deletes of the rows the database would cascade to (the
  foreign keys declared ``ON DELETE CASCADE``), so a journal replay needs no foreign keys.

A ``before`` list parallels ``resolved``: the old row of an update or a delete, else ``None``.
Re-keying a row that other rows reference by ``ON UPDATE CASCADE`` is refused here; the
change API's rename (C14) must list the dependents itself.

Concurrency: the configuration's row is locked ``FOR UPDATE`` for the batch, so two
writers of one configuration take consecutive revisions.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from sqlalchemy import delete, func, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from server.models.journal import (
    GLOBAL_CONFIGURATION_ID,
    KIND_GLOBAL,
    KIND_SESSION,
    SOURCES,
    TRAINING_MODE_SOURCES,
    Configuration,
    JournalEntry,
)
from server.services.config_registry import LAYER_REGISTRY, TableSpec

logger = logging.getLogger("petacat")

_CONFIGURATIONS = Configuration.__table__
_JOURNAL = JournalEntry.__table__

#: The post-commit hook for the global configuration: ``await hook(session)``, called by
#: ``write_immediate`` only after a change to the global configuration has committed (never
#: for a write that changed nothing, a ``commit=False`` write, or a failed one).  The
#: ``ConfigurationStore`` installs its ``refresh`` here (``set_configuration_store``), so an
#: edit reaches the next run before the write returns.
_global_commit_hook = None


def set_global_commit_hook(hook) -> None:
    """Install (or, with ``None``, remove) the post-commit hook for global changes."""
    global _global_commit_hook
    _global_commit_hook = hook


# ──────────────────────────────────────────────────────────────────
# Errors and results
# ──────────────────────────────────────────────────────────────────


class JournalError(Exception):
    """A batch the layer cannot apply.  Nothing was written."""


class KeyExists(JournalError):
    """An insert names a natural key the table already holds."""


class MissingKey(JournalError):
    """An update or delete names a natural key the table does not hold."""


class StaleRevision(JournalError):
    """The caller's ``expected_revision`` is not the configuration's revision (compare-and-set)."""


class SourceRefused(JournalError):
    """The global configuration (Metacat Mode) refuses a Training Mode source (M2)."""


class ConfigurationNotAdopted(JournalError):
    """A global change committed, but the post-commit hook failed.

    The change is in the database and in the journal; the configuration the runs use is
    still the previous one, until the database holds a configuration it can be built from.
    """


@dataclass
class WriteResult:
    """What a write did.  ``rows`` parallels the ops that were *given*."""

    configuration_id: int
    #: The configuration's revision after the write (unchanged when nothing changed).
    revision: int
    #: The journal entry's id, or ``None`` when no op changed anything.
    entry_id: int | None
    changed: bool
    #: The ops applied, in order, with the stored defaults and the cascades.
    resolved: list[dict] = field(default_factory=list)
    #: ``before[i]`` is the old row of ``resolved[i]``, else ``None``.
    before: list[dict | None] = field(default_factory=list)
    #: For each op given: the row as it now stands (with its surrogate ``id``), or ``None``
    #: for a delete.
    rows: list[dict | None] = field(default_factory=list)
    config_hash: str | None = None


@dataclass(frozen=True)
class PendingEntry:
    """An entry produced in memory by a live session, written by the Stop write."""

    revision: int
    source: str
    actor: str
    proposed: Any
    resolved: list[dict]
    before: list[dict | None]
    occurred_at: datetime
    channel: str = ""
    note: str = ""
    group_id: str | None = None
    causing_run_id: int | None = None
    episode_version: int | None = None
    config_hash: str | None = None


# ──────────────────────────────────────────────────────────────────
# Small helpers
# ──────────────────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _spec(table: str) -> TableSpec:
    spec = LAYER_REGISTRY.get(table)
    if spec is None:
        raise JournalError(f"{table!r} is not a configuration table")
    return spec


def _key_clause(spec: TableSpec, key: Mapping[str, Any]) -> list:
    """WHERE clauses for a natural key; a nullable key column is compared as ``''``."""
    clauses = []
    for name in spec.key:
        column = spec.table.c[name]
        value = key.get(name)
        if column.nullable:
            clauses.append(func.coalesce(column, "") == ("" if value is None else value))
        else:
            if value is None:
                raise JournalError(f"{spec.name}: the key column {name!r} is missing")
            clauses.append(column == value)
    return clauses


async def _select_row(
    session: AsyncSession, spec: TableSpec, key: Mapping[str, Any], *, lock: bool = True
) -> dict | None:
    stmt = select(spec.table).where(*_key_clause(spec, key))
    if lock:
        stmt = stmt.with_for_update()
    rows = (await session.execute(stmt)).mappings().all()
    if len(rows) > 1:
        raise JournalError(f"{spec.name}: the key {dict(key)!r} matches {len(rows)} rows")
    return dict(rows[0]) if rows else None


def _stored(spec: TableSpec, row: Mapping[str, Any]) -> dict:
    """``row`` as a journal records it: every column but the surrogate ``id``."""
    return {c: row[c] for c in spec.stored_columns}


def _cascade_children(spec: TableSpec) -> list[tuple[TableSpec, str, str]]:
    """``(child, child_column, parent_column)`` for each ``ON DELETE CASCADE`` foreign key
    into ``spec``'s table from another configuration table."""
    out = []
    for child in LAYER_REGISTRY.values():
        for fk in child.table.foreign_keys:
            if fk.column.table is spec.table and (fk.ondelete or "").upper() == "CASCADE":
                out.append((child, fk.parent.name, fk.column.name))
    return out


def _check_source(configuration_kind: str, source: str) -> None:
    if source not in SOURCES:
        raise JournalError(f"unknown source {source!r}; one of {', '.join(SOURCES)}")
    if configuration_kind == KIND_GLOBAL and source in TRAINING_MODE_SOURCES:
        raise SourceRefused(
            f"the global configuration (Metacat Mode) refuses source {source!r}: nothing in "
            "Training Mode may change Metacat Mode"
        )


async def compute_config_hash(session: AsyncSession) -> str | None:
    """``config_hash`` of the global configuration as this session's transaction sees it.

    Reads through a probe session that shares the caller's connection (so it sees
    uncommitted rows and a fresh identity map).  ``None`` when the tables do not load.
    """
    from server.engine.hashing import config_hash
    from server.services.metadata_service import load_metadata_from_db

    try:
        connection = await session.connection()
        async with AsyncSession(bind=connection, expire_on_commit=False) as probe:
            return config_hash(await load_metadata_from_db(probe))
    except Exception as exc:  # the configuration may be one a run would refuse
        logger.warning("config_hash could not be computed (%s: %s)", type(exc).__name__, exc)
        return None


# ──────────────────────────────────────────────────────────────────
# Applying ops to the current-state tables
# ──────────────────────────────────────────────────────────────────


class _Applier:
    """Applies a batch to the tables and collects the resolved ops and before-images."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.resolved: list[dict] = []
        self.before: list[dict | None] = []
        self.rows: list[dict | None] = []

    async def apply(self, op: Mapping[str, Any]) -> None:
        kind = op.get("op")
        spec = _spec(op.get("table", ""))
        if kind == "insert":
            self.rows.append(await self._insert(spec, op))
        elif kind == "update":
            self.rows.append(await self._update(spec, op))
        elif kind == "delete":
            await self._delete_key(spec, op.get("key") or {})
            self.rows.append(None)
        else:
            raise JournalError(f"unknown op {kind!r}")

    def _record(self, op: dict, before: dict | None) -> None:
        self.resolved.append(op)
        self.before.append(before)

    def _columns(self, spec: TableSpec, values: Mapping[str, Any]) -> dict:
        unknown = set(values) - set(spec.columns)
        if unknown:
            raise JournalError(f"{spec.name}: no such column {sorted(unknown)}")
        sid = spec.surrogate
        return {c: v for c, v in values.items() if c != sid}

    async def _insert(self, spec: TableSpec, op: Mapping[str, Any]) -> dict:
        row = self._columns(spec, {**(op.get("key") or {}), **(op.get("row") or {})})
        key = spec.key_of(row)
        if await _select_row(self.session, spec, key, lock=False) is not None:
            raise KeyExists(f"{spec.name}: {key!r} already exists")
        returned = (
            await self.session.execute(insert(spec.table).values(**row).returning(*spec.table.c))
        ).mappings().one()
        stored = _stored(spec, returned)
        self._record(
            {"op": "insert", "table": spec.name, "key": spec.key_of(returned), "row": stored}, None
        )
        return dict(returned)

    async def _update(self, spec: TableSpec, op: Mapping[str, Any]) -> dict:
        key = op.get("key") or {}
        old = await _select_row(self.session, spec, key)
        if old is None:
            raise MissingKey(f"{spec.name}: {dict(key)!r} does not exist")
        changed = {
            c: v for c, v in self._columns(spec, op.get("set") or {}).items() if old[c] != v
        }
        if not changed:
            return old
        if set(changed) & set(spec.key):
            await self._check_rekey(spec, old, changed)
        result = await self.session.execute(
            update(spec.table).where(*_key_clause(spec, spec.key_of(old))).values(**changed)
        )
        if result.rowcount != 1:
            raise JournalError(f"{spec.name}: the key {spec.key_of(old)!r} is not unique")
        self._record(
            {"op": "update", "table": spec.name, "key": spec.key_of(old), "set": changed},
            _stored(spec, old),
        )
        return {**old, **changed}

    async def _check_rekey(self, spec: TableSpec, old: dict, changed: dict) -> None:
        new_key = spec.key_of({**old, **changed})
        if new_key != spec.key_of(old) and await _select_row(
            self.session, spec, new_key, lock=False
        ) is not None:
            raise KeyExists(f"{spec.name}: {new_key!r} already exists")
        for child in LAYER_REGISTRY.values():
            for fk in child.table.foreign_keys:
                if fk.column.table is spec.table and fk.column.name in changed:
                    hit = await self.session.execute(
                        select(func.count()).select_from(child.table).where(
                            child.table.c[fk.parent.name] == old[fk.column.name]
                        )
                    )
                    if hit.scalar_one():
                        raise JournalError(
                            f"{spec.name}: re-keying {fk.column.name!r} would cascade to "
                            f"{child.name}; list the dependents' updates explicitly"
                        )

    async def _delete_key(self, spec: TableSpec, key: Mapping[str, Any]) -> None:
        old = await _select_row(self.session, spec, key)
        if old is None:
            raise MissingKey(f"{spec.name}: {dict(key)!r} does not exist")
        await self._delete_row(spec, old)

    async def _delete_row(self, spec: TableSpec, old: dict) -> None:
        # The rows the database would cascade to go first, explicitly, so that the journal
        # holds them (and a replay needs no foreign keys).
        for child, child_column, parent_column in _cascade_children(spec):
            dependents = (
                await self.session.execute(
                    select(child.table)
                    .where(child.table.c[child_column] == old[parent_column])
                    .with_for_update()
                )
            ).mappings().all()
            for dependent in dependents:
                await self._delete_row(child, dict(dependent))
        key = spec.key_of(old)
        result = await self.session.execute(delete(spec.table).where(*_key_clause(spec, key)))
        if result.rowcount != 1:
            raise JournalError(f"{spec.name}: the key {key!r} is not unique")
        self._record({"op": "delete", "table": spec.name, "key": key}, _stored(spec, old))


# ──────────────────────────────────────────────────────────────────
# The configuration row
# ──────────────────────────────────────────────────────────────────


async def _lock_configuration(session: AsyncSession, configuration_id: int) -> dict:
    """The configuration's row, locked.  The global configuration's row is created on demand."""
    if configuration_id == GLOBAL_CONFIGURATION_ID:
        created = await session.execute(
            pg_insert(_CONFIGURATIONS)
            .values(id=GLOBAL_CONFIGURATION_ID, kind=KIND_GLOBAL, revision=0)
            .on_conflict_do_nothing()
        )
        if created.rowcount:
            # The row carries an explicit id; move the sequence past it so that the ids of
            # the session configurations created later do not collide with it.
            await session.execute(
                text("SELECT setval(pg_get_serial_sequence('configurations', 'id'), :id, true)"),
                {"id": GLOBAL_CONFIGURATION_ID},
            )
    row = (
        await session.execute(
            select(_CONFIGURATIONS).where(_CONFIGURATIONS.c.id == configuration_id).with_for_update()
        )
    ).mappings().first()
    if row is None:
        raise JournalError(f"configuration {configuration_id} does not exist")
    return dict(row)


def _entry_values(configuration_id: int, revision: int, **fields: Any) -> dict:
    return {"configuration_id": configuration_id, "revision": revision, **fields}


# ──────────────────────────────────────────────────────────────────
# Door 1: write_immediate
# ──────────────────────────────────────────────────────────────────


async def write_immediate(
    session: AsyncSession,
    *,
    ops: Sequence[Mapping[str, Any]],
    source: str,
    actor: str,
    configuration_id: int = GLOBAL_CONFIGURATION_ID,
    channel: str = "",
    note: str = "",
    proposed: Any = None,
    group_id: str | None = None,
    causing_run_id: int | None = None,
    episode_version: int | None = None,
    compute_hash: bool = True,
    commit: bool = True,
    expected_revision: int | None = None,
) -> WriteResult:
    """Apply ``ops`` to the configuration's tables and append the entry, in one transaction.

    ``proposed`` is what was asked for (the ops as submitted); it defaults to ``ops``.
    ``commit=False`` leaves the transaction to the caller (the Metacat Standard
    Configuration's first load writes ``configuration_state`` in the same one); the batch
    is still all-or-nothing, inside a savepoint.

    ``expected_revision`` is an optional compare-and-set: once the configuration's row is
    locked, a revision other than this raises :class:`StaleRevision` and nothing is written.

    Raises :class:`KeyExists`, :class:`MissingKey`, :class:`SourceRefused`,
    :class:`StaleRevision` or :class:`JournalError`; a database error (a foreign key, for one) propagates.  Either
    way nothing was written.
    """
    ops = list(ops)
    try:
        if commit:
            result = await _write(
                session, ops, source, actor, configuration_id, channel, note, proposed,
                group_id, causing_run_id, episode_version, compute_hash,
                expected_revision,
            )
            await session.commit()
        else:
            async with session.begin_nested():
                result = await _write(
                    session, ops, source, actor, configuration_id, channel, note, proposed,
                    group_id, causing_run_id, episode_version, compute_hash,
                    expected_revision,
                )
            await session.flush()
    except BaseException:
        if commit:
            await session.rollback()
        raise
    if commit and result.changed and configuration_id == GLOBAL_CONFIGURATION_ID:
        await _run_global_commit_hook(session)
    return result


async def _run_global_commit_hook(session: AsyncSession) -> None:
    """Call the post-commit hook.  The change is already committed, so a failure here is
    reported as :class:`ConfigurationNotAdopted` and rolls nothing back."""
    if _global_commit_hook is None:
        return
    try:
        await _global_commit_hook(session)
    except Exception as exc:
        logger.exception("The configuration was saved but could not be loaded")
        raise ConfigurationNotAdopted(
            "The edit was saved, but the configuration it leaves could not be loaded "
            f"({exc}); the previous configuration stays in force until this is fixed."
        ) from exc


async def _write(
    session, ops, source, actor, configuration_id, channel, note, proposed, group_id,
    causing_run_id, episode_version, compute_hash, expected_revision=None,
) -> WriteResult:
    configuration = await _lock_configuration(session, configuration_id)
    _check_source(configuration["kind"], source)
    if expected_revision is not None and configuration["revision"] != expected_revision:
        raise StaleRevision(
            f"configuration {configuration_id} is at revision {configuration['revision']}, "
            f"not the expected {expected_revision}"
        )
    if configuration["kind"] != KIND_GLOBAL:
        raise NotImplementedError(
            "write_immediate writes the global configuration; a session's configuration "
            "state is written by the configuration entity (C8)"
        )
    applier = _Applier(session)
    for op in ops:
        await applier.apply(op)
    revision = configuration["revision"]
    if not applier.resolved:
        return WriteResult(
            configuration_id, revision, None, False, [], [], applier.rows,
            configuration["config_hash"],
        )
    revision += 1
    digest = await compute_config_hash(session) if compute_hash else None
    now = _now()
    entry_id = (
        await session.execute(
            insert(_JOURNAL)
            .values(
                **_entry_values(
                    configuration_id, revision, group_id=group_id, source=source, actor=actor,
                    channel=channel, note=note, causing_run_id=causing_run_id,
                    episode_version=episode_version,
                    proposed=ops if proposed is None else proposed,
                    resolved=applier.resolved, before=applier.before, config_hash=digest,
                    occurred_at=now, recorded_at=now,
                )
            )
            .returning(_JOURNAL.c.id)
        )
    ).scalar_one()
    await session.execute(
        update(_CONFIGURATIONS)
        .where(_CONFIGURATIONS.c.id == configuration_id)
        .values(revision=revision, config_hash=digest)
    )
    return WriteResult(
        configuration_id, revision, entry_id, True, applier.resolved, applier.before,
        applier.rows, digest,
    )


# ──────────────────────────────────────────────────────────────────
# Door 2: write_deferred
# ──────────────────────────────────────────────────────────────────


async def write_deferred(
    session: AsyncSession,
    *,
    configuration_id: int,
    entries: Sequence[PendingEntry],
    commit: bool = False,
) -> list[int]:
    """Append entries a live session produced in memory.  Only a session's Stop write calls this.

    The entries' revisions must continue the configuration's ``revision`` without a gap.
    Each keeps its own ``occurred_at``; ``recorded_at`` is now.  Only the entries and the
    revision are written: the Stop write writes the session's runs, memory snapshot and
    current state in the same transaction (``commit=False``, the default).  Returns the
    entries' real ids, in order.
    """
    entries = list(entries)
    try:
        configuration = await _lock_configuration(session, configuration_id)
        if configuration["kind"] != KIND_SESSION:
            raise JournalError(
                "write_deferred is a session's Stop write; the global configuration is "
                "written at once, by write_immediate"
            )
        expected = configuration["revision"]
        recorded_at = _now()
        ids: list[int] = []
        digest = configuration["config_hash"]
        for entry in entries:
            expected += 1
            if entry.revision != expected:
                raise JournalError(
                    f"entry revision {entry.revision} does not follow revision {expected - 1}"
                )
            _check_source(configuration["kind"], entry.source)
            ids.append(
                (
                    await session.execute(
                        insert(_JOURNAL)
                        .values(
                            **_entry_values(
                                configuration_id, entry.revision, group_id=entry.group_id,
                                source=entry.source, actor=entry.actor, channel=entry.channel,
                                note=entry.note, causing_run_id=entry.causing_run_id,
                                episode_version=entry.episode_version, proposed=entry.proposed,
                                resolved=entry.resolved, before=entry.before,
                                config_hash=entry.config_hash, occurred_at=entry.occurred_at,
                                recorded_at=recorded_at,
                            )
                        )
                        .returning(_JOURNAL.c.id)
                    )
                ).scalar_one()
            )
            digest = entry.config_hash or digest
        if entries:
            await session.execute(
                update(_CONFIGURATIONS)
                .where(_CONFIGURATIONS.c.id == configuration_id)
                .values(revision=expected, config_hash=digest)
            )
        if commit:
            await session.commit()
        else:
            await session.flush()
        return ids
    except BaseException:
        if commit:
            await session.rollback()
        raise
