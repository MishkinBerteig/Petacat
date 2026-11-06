"""Configurations as entities (configuration plan 3.10, 3.14): the manager's reads and the
creation of a Training Mode Session's configuration.

A *configuration* belongs to exactly one mode.  The global configuration (id 1) is Metacat Mode's;
a Training Mode Session's own configuration is Training Mode's.  This module is the service over
the ``configurations`` entity:

* **Reading a document.** :func:`current_document` is a configuration's document now (the
  global one from its relational tables, a session's from its stored current state);
  :func:`config_at` is the document at an earlier revision or Training episode version.  For a
  session it is the immutable base snapshot plus the journal's resolved ops, applied with
  ``apply_resolved`` (no validation), or, for a revision before the base, the base with the
  creation batch undone by its before-images.  ``ConfigurationStore.provider`` builds the
  ``MetadataProvider`` from these.
* **Creating a session's configuration.** :func:`create_session_configuration` runs in the
  caller's transaction (S3 calls it from session creation).  The base is the global
  configuration, the Metacat Standard Configuration or another session's current configuration.
  The creation overrides are one batch of ordinary ops with ``source = creation``, resolved by
  ``change_resolve.resolve`` and journaled; the state it leaves is the Starting Conceptual State
  and is saved as the immutable base snapshot.  The session never reads Metacat Mode's
  configuration afterwards, and nothing it does writes it.
* **The manager's list, summary, rows and export, and the meta edit** (name, note and ``frozen``,
  a journaled entry with no ops).

Every write goes through the journal layer (``server/services/journal.py``); this module only
reads, resolves and calls it.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.models.journal import (
    GLOBAL_CONFIGURATION_ID,
    KIND_GLOBAL,
    KIND_SESSION,
    SNAPSHOT_BASE,
    SNAPSHOT_CURRENT,
    Configuration,
    ConfigurationSnapshot,
    JournalEntry,
)
from server.services import config_document as cd
from server.services import journal, journal_views
from server.services.problem_text import ProblemTextError, check_string

_CONFIGURATIONS = Configuration.__table__
_SNAPSHOTS = ConfigurationSnapshot.__table__
_JOURNAL = JournalEntry.__table__


class ConfigurationError(Exception):
    """A request these functions cannot carry out; the message says why."""


class UnknownConfiguration(ConfigurationError):
    """No configuration has that id."""


class UnknownRevision(ConfigurationError):
    """The configuration never had that revision."""


class UnknownTable(ConfigurationError):
    """Not a configuration table."""


class BadBase(ConfigurationError):
    """``base`` is not ``'global'``, ``'standard'`` or ``{"session_id": n}``."""


# ──────────────────────────────────────────────────────────────────
# Reading a configuration
# ──────────────────────────────────────────────────────────────────


async def get_row(session: AsyncSession, configuration_id: int) -> dict:
    """The ``configurations`` row (``UnknownConfiguration`` when there is none)."""
    row = (
        await session.execute(select(_CONFIGURATIONS).where(_CONFIGURATIONS.c.id == configuration_id))
    ).mappings().first()
    if row is None:
        raise UnknownConfiguration(f"configuration {configuration_id} does not exist")
    return dict(row)


async def row_for_session(session: AsyncSession, session_id: int) -> dict:
    """The configuration of Training Mode Session ``session_id``."""
    row = (
        await session.execute(select(_CONFIGURATIONS).where(_CONFIGURATIONS.c.session_id == session_id))
    ).mappings().first()
    if row is None:
        raise UnknownConfiguration(f"Training Mode Session {session_id} has no configuration")
    return dict(row)


async def _snapshot(session: AsyncSession, configuration_id: int, role: str) -> dict:
    row = (
        await session.execute(
            select(_SNAPSHOTS).where(
                _SNAPSHOTS.c.configuration_id == configuration_id, _SNAPSHOTS.c.role == role
            )
        )
    ).mappings().first()
    if row is None:
        raise UnknownConfiguration(f"configuration {configuration_id} has no {role} snapshot")
    return dict(row)


async def current_document(session: AsyncSession, configuration_id: int) -> cd.ConfigDocument:
    """The configuration as stored now, at its ``revision``.

    A live session's in-memory state is not here: that is the store's second source.
    """
    row = await get_row(session, configuration_id)
    if row["kind"] == KIND_GLOBAL:
        return await cd.document_from_db(session, version=row["revision"])
    snapshot = await _snapshot(session, configuration_id, SNAPSHOT_CURRENT)
    return cd.from_data({**snapshot["data"], "version": row["revision"]})


async def base_document(session: AsyncSession, configuration_id: int) -> cd.ConfigDocument:
    """A session configuration's Starting Conceptual State (the immutable base snapshot)."""
    row = await get_row(session, configuration_id)
    if row["kind"] != KIND_SESSION:
        raise ConfigurationError("only a session configuration has a base snapshot")
    snapshot = await _snapshot(session, configuration_id, SNAPSHOT_BASE)
    return cd.from_data({**snapshot["data"], "version": snapshot["revision"]})


async def base_revision(session: AsyncSession, configuration_id: int) -> int:
    """The revision of a session configuration's base snapshot: 0, or 1 when the creation
    batch had overrides."""
    return (await _snapshot(session, configuration_id, SNAPSHOT_BASE))["revision"]


async def _revision_of_episode_version(
    session: AsyncSession, configuration_id: int, episode_version: int, floor: int
) -> int:
    """The revision after the last entry whose Training episode version is at most
    ``episode_version`` (``floor`` when there is none)."""
    revision = floor
    for entry in await journal_views.read_entries(session, configuration_id, after=floor):
        if entry["episode_version"] is not None and entry["episode_version"] <= episode_version:
            revision = entry["revision"]
    return revision


async def config_at(
    session: AsyncSession,
    configuration_id: int,
    revision: int | None = None,
    episode_version: int | None = None,
) -> cd.ConfigDocument:
    """The configuration at ``revision`` (or at a Training episode version; ``revision`` wins).

    * The global configuration is reconstructed from its relational tables by the journal's
      before-images.
    * A session's is its base snapshot plus the resolved ops of the entries up to the
      revision, applied with ``apply_resolved``.  A revision before the base (revision 0 of a
      configuration whose creation batch had overrides) undoes that batch by its
      before-images.  With neither argument it is the stored current state.
    """
    row = await get_row(session, configuration_id)
    top = row["revision"]
    if row["kind"] == KIND_SESSION and revision is None and episode_version is not None:
        floor = await base_revision(session, configuration_id)
        revision = await _revision_of_episode_version(
            session, configuration_id, episode_version, floor
        )
    if revision is None or revision == top:
        return await current_document(session, configuration_id)
    if not 0 <= revision <= top:
        raise UnknownRevision(
            f"configuration {configuration_id} has revisions 0 to {top}, not {revision}"
        )
    if row["kind"] == KIND_GLOBAL:
        state = await journal_views.as_of(session, configuration_id, revision)
        return cd.from_rows({t: rows.values() for t, rows in state.items()}, version=revision)
    base = await base_document(session, configuration_id)
    floor = base.version
    if revision >= floor:
        entries = await journal_views.read_entries(
            session, configuration_id, after=floor, upto=revision
        )
        ops = [op for entry in entries for op in entry["resolved"]]
        return cd.apply_resolved(base, ops, version=revision)
    entries = await journal_views.read_entries(
        session, configuration_id, after=revision, upto=floor
    )
    return cd.apply_resolved(base, journal_views.inverse_ops(entries), version=revision)


# ──────────────────────────────────────────────────────────────────
# Creating a session's configuration
# ──────────────────────────────────────────────────────────────────


async def base_document_for(
    session: AsyncSession, base: Any
) -> tuple[cd.ConfigDocument, int | None, int | None]:
    """``(document, created_from_configuration_id, created_from_revision)``."""
    if base is None or base == "global":
        row = await get_row(session, GLOBAL_CONFIGURATION_ID)
        return (
            await cd.document_from_db(session, version=row["revision"]),
            GLOBAL_CONFIGURATION_ID, row["revision"],
        )
    if base == "standard":
        from server.services.configuration_admin import reference_document

        return reference_document(), None, None
    if isinstance(base, Mapping) and set(base) == {"session_id"} and isinstance(
        base["session_id"], int
    ) and not isinstance(base["session_id"], bool):
        row = await row_for_session(session, base["session_id"])
        return await current_document(session, row["id"]), row["id"], row["revision"]
    raise BadBase("base must be 'global', 'standard' or {\"session_id\": <number>}")


async def create_session_configuration(
    session: AsyncSession,
    session_id: int,
    base: Any = "global",
    overrides: Sequence[Mapping[str, Any]] | None = None,
    *,
    name: str | None = None,
    actor: str = "system",
    note: str = "",
) -> int:
    """Create Training Mode Session ``session_id``'s configuration; return its id.

    Runs in the caller's transaction and does not commit (the session row must already be
    flushed).  ``base`` is ``'global'`` (the default), ``'standard'`` or ``{"session_id": n}``
    (that session's current stored configuration).  ``overrides`` is a list of ordinary change
    ops (convenience ops allowed); they are resolved against the base and written as the
    creation batch (``source = creation``, revision 1).  A refused override raises
    ``ChangeError`` and nothing is written.  ``name`` defaults to the session's name.
    """
    from server.models.training_mode_session import TrainingModeSession

    document, from_id, from_revision = await base_document_for(session, base)
    if name is None:
        name = (
            await session.execute(
                select(TrainingModeSession.__table__.c.name).where(
                    TrainingModeSession.__table__.c.id == session_id
                )
            )
        ).scalar_one_or_none()
        if name is None:
            raise ConfigurationError(f"Training Mode Session {session_id} does not exist")
    resolved: list[dict] = []
    overrides = list(overrides or [])
    if overrides:
        resolved = _resolve_overrides(document, overrides, actor)
    result = await journal.create_session_configuration_rows(
        session,
        session_id=session_id,
        name=name,
        document=document,
        creation_ops=resolved,
        proposed=overrides,
        actor=actor,
        note=note or "Starting Conceptual State: creation overrides",
        created_from_configuration_id=from_id,
        created_from_revision=from_revision,
    )
    return result.configuration_id


def _resolve_overrides(document: cd.ConfigDocument, overrides: list, actor: str) -> list[dict]:
    from server.services import configuration_writer as writer

    batch = {"configuration_id": 0, "source": "creation", "actor": actor, "ops": overrides}
    writer.check_envelope(batch)
    try:
        ops, _report = writer._resolve_function()(document, batch)
    except Exception as exc:
        translated = writer._translate(exc)
        if translated is not None:
            raise translated from exc
        raise
    return list(ops)


# ──────────────────────────────────────────────────────────────────
# The manager: list, summary, rows, export, meta edit
# ──────────────────────────────────────────────────────────────────

MODE_GLOBAL = "Metacat Mode"
MODE_SESSION = "Training Mode"


async def _last_change(session: AsyncSession, configuration_id: int) -> dict | None:
    row = (
        await session.execute(
            select(_JOURNAL.c.revision, _JOURNAL.c.source, _JOURNAL.c.actor, _JOURNAL.c.channel,
                   _JOURNAL.c.recorded_at)
            .where(_JOURNAL.c.configuration_id == configuration_id)
            .order_by(_JOURNAL.c.revision.desc())
            .limit(1)
        )
    ).mappings().first()
    if row is None:
        return None
    return {**row, "recorded_at": row["recorded_at"].isoformat() if row["recorded_at"] else None}


async def _session_names(session: AsyncSession) -> dict[int, str]:
    from server.models.training_mode_session import TrainingModeSession

    table = TrainingModeSession.__table__
    return {i: n for i, n in (await session.execute(select(table.c.id, table.c.name))).all()}


async def _summarize(
    session: AsyncSession, row: dict, session_names: Mapping[int, str], reference: cd.ConfigDocument
) -> dict[str, Any]:
    from server.services import configuration_admin as admin
    from server.services.configuration_store import live_state

    is_session = row["kind"] == KIND_SESSION
    document = await current_document(session, row["id"])
    digest = row["config_hash"] or cd.config_hash(document)
    equals = digest == cd.config_hash(reference)
    session_name = session_names.get(row["session_id"]) if is_session else None
    live = live_state(row["session_id"]) if is_session else None
    summary: dict[str, Any] = {
        "id": row["id"],
        "name": row["name"],
        "note": row["note"],
        "kind": row["kind"],
        "mode": MODE_SESSION if is_session else MODE_GLOBAL,
        "mode_label": f"{MODE_SESSION}: {session_name}" if is_session else MODE_GLOBAL,
        "session_id": row["session_id"],
        "session_name": session_name,
        "session_state": (live.state if live else "stopped") if is_session else None,
        "revision": row["revision"],
        "config_hash": digest,
        "base_snapshot_hash": row["base_snapshot_hash"],
        "frozen": row["frozen"],
        "created_from_configuration_id": row["created_from_configuration_id"],
        "created_from_revision": row["created_from_revision"],
        "equals_standard": equals,
        "differs_from_standard_rows": 0 if equals else len(admin.compare(document, reference)),
        "last_change": await _last_change(session, row["id"]),
        "source": "stored",
    }
    if live is not None:
        summary.update(
            source="live", live_revision=live.revision, saved_through=live.saved_through,
            saved_at=live.saved_at.isoformat() if live.saved_at else None, unsaved=live.unsaved,
        )
    return summary


async def list_configurations(session: AsyncSession) -> list[dict[str, Any]]:
    """One summary per configuration, the global one first, then the sessions' by id."""
    from server.services.configuration_admin import reference_document

    rows = (
        await session.execute(select(_CONFIGURATIONS).order_by(_CONFIGURATIONS.c.id))
    ).mappings().all()
    names = await _session_names(session)
    reference = reference_document()
    return [await _summarize(session, dict(r), names, reference) for r in rows]


async def summary(session: AsyncSession, configuration_id: int) -> dict[str, Any]:
    from server.services.configuration_admin import reference_document

    row = await get_row(session, configuration_id)
    return await _summarize(session, row, await _session_names(session), reference_document())


async def rows(
    session: AsyncSession, configuration_id: int, table: str | None = None
) -> dict[str, Any]:
    """The rows of one table (``UnknownTable`` when it is not a configuration table); with no
    table, the table names with their row counts."""
    document = await current_document(session, configuration_id)
    if table is None:
        return {
            "configuration_id": configuration_id,
            "revision": document.version,
            "tables": {t: len(document.tables[t]) for t in cd.TABLE_NAMES},
        }
    if table not in cd.TABLE_NAMES:
        raise UnknownTable(f"{table!r} is not a configuration table")
    listed = [dict(r) for r in document.tables[table].values()]
    return {
        "configuration_id": configuration_id,
        "revision": document.version,
        "table": table,
        "key_columns": list(cd.key_columns(table)),
        "count": len(listed),
        "rows": listed,
    }


async def export(session: AsyncSession, configuration_id: int) -> dict[str, Any]:
    """The whole configuration as one bundle: its summary and ``config_document.to_data``."""
    document = await current_document(session, configuration_id)
    head = await summary(session, configuration_id)
    return {"format": "petacat-configuration", "configuration": head, "data": cd.to_data(document)}


def _check_text(field: str, value: str) -> None:
    try:
        check_string(field, value)
    except ProblemTextError as exc:
        raise ConfigurationError(str(exc)) from exc


async def update_meta(
    session: AsyncSession,
    configuration_id: int,
    *,
    name: str | None = None,
    note: str | None = None,
    frozen: bool | None = None,
    actor: str = "admin",
) -> dict[str, Any]:
    """Change the name, note or ``frozen`` flag: one journaled entry (no ops, next revision)."""
    fields: dict[str, Any] = {}
    if name is not None:
        if not isinstance(name, str) or not name.strip():
            raise ConfigurationError("name must be text with at least one character besides spaces")
        _check_text("name", name)
        fields["name"] = name.strip()
    if note is not None:
        if not isinstance(note, str):
            raise ConfigurationError("note must be text")
        _check_text("note", note)
        fields["note"] = note
    if frozen is not None:
        if not isinstance(frozen, bool):
            raise ConfigurationError("frozen must be true or false")
        fields["frozen"] = frozen
    await get_row(session, configuration_id)
    if fields:
        await journal.update_configuration_meta(session, configuration_id, fields, actor=actor)
    return await summary(session, configuration_id)
