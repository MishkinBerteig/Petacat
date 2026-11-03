"""A live Training Mode Session's own configuration, in memory (the S3a half of S3).

The Training Mode Session service holds one :class:`LiveConfiguration` for each live session
(Running, Paused, Stopping).  It is the session's evolving configuration: the stored current
state it was started from, plus every batch applied since, from every learning source (the
in-worker learner, the external route, the Admin view).  Nothing here touches the database, the
clock (it is injected) or Episodic Memory (the caller passes the merge in as a callable), so the
whole of it runs in a unit test.

One counter, two numbers
------------------------
:class:`~server.services.session_episode.EpisodeLog` keeps the **episode version**: one counter
over Episodic Memory and the whole configuration; every entry takes the next number.  The
**configuration revision** is the configuration entity's own counter
(``configurations.revision``): the number of batches that changed the configuration, stored
state included.  It is the compare-and-set token an editor sends as ``base_version``, the number
a run records, and the number a journal entry carries.  ``version >= revision`` always.
:class:`LiveEpisodeLog` is the episode log with its ``configuration_revision`` counting that way
(S1 reports the episode version of the last change instead, which is not what an editor holds).

Entries, and what the Stop write gets
-------------------------------------
Every entry that changed the configuration also produces a :class:`~server.services.journal.PendingEntry`
(with the batch asked, the resolved ops exactly as the journal layer would store them, and the
before-images), kept in revision order in :attr:`LiveConfiguration.changes`.  The Stop write (S5)
passes :meth:`LiveConfiguration.pending_entries` to ``journal.write_deferred`` and
``self.document`` to ``journal.store_current_state``.

The after-run seam and failure
------------------------------
A learner's batch rides in the run-finish entry (:meth:`LiveConfiguration.finish_run`); a batch
the layer refuses never fails its run, it becomes a diagnostic.  An external or Admin batch
(:meth:`LiveConfiguration.submit`) raises what ``resolve`` raised.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from server.engine.metadata import MetadataProvider
from server.services import config_document as cd
from server.services import journal
from server.services.session_episode import EpisodeLog, SubmitResult

#: The batch fields ``resolve`` reads (the writer passes the same set).
_RESOLVE_FIELDS = (
    "configuration_id", "base_version", "base_mode", "source", "actor", "note", "ops",
    "on_op_failure", "dry_run",
)
NODES_TABLE = "slipnet_node_defs"
LINKS_TABLE = "slipnet_link_defs"


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ConfigRef:
    """The configuration a run starts under, taken at the moment it is dispatched.

    Taken together with the run's ``MemoryRef`` and with no ``await`` between them, so a run's
    inputs are one consistent cut.  ``version`` is the episode version, ``configuration_revision``
    the revision of the last configuration change at or before it.
    """

    session_id: int
    version: int
    configuration_revision: int
    config_hash: str
    provider: MetadataProvider


@dataclass(frozen=True)
class LiveChange:
    """One configuration-changing entry held in memory until the Stop write."""

    pending: journal.PendingEntry
    #: ``(problem_id, seed)`` of the run whose finish carried it (a learner's batch), else ``None``.
    run: tuple[int, int] | None = None


class LiveEpisodeLog(EpisodeLog):
    """:class:`EpisodeLog` whose ``configuration_revision`` is the entity's revision counter.

    It also normalises every batch ``resolve`` returns through the journal layer
    (``journal.normalize_ops``), so the ops an entry holds are the ops the Stop write stores, and
    it remembers the before-images of the last batch it resolved.
    """

    def __init__(
        self, base: cd.ConfigDocument, *, revision: int, configuration_id: int,
        resolve: Callable[..., Any] | None = None,
    ) -> None:
        self._configuration_id = configuration_id
        self._inner = resolve
        self._revision = revision
        self._base_revision = revision
        #: Before-images of the ops of the last batch resolved (``None`` before any).
        self.last_before: list[dict | None] | None = None
        super().__init__(base, resolve=self._resolve_and_normalise)

    def _resolve_and_normalise(self, cfg: cd.ConfigDocument, batch: Mapping[str, Any]):
        inner = self._inner
        if inner is None:
            from server.services.change_resolve import resolve as inner
        given = {name: batch[name] for name in _RESOLVE_FIELDS if name in batch}
        given.setdefault("configuration_id", self._configuration_id)
        ops, report = inner(cfg, given)
        resolved, before = journal.normalize_ops(cfg, ops)
        self.last_before = before
        return resolved, report

    @property
    def configuration_revision(self) -> int:
        return self._revision

    def configuration_revision_at(self, v: int) -> int:
        revision = self._base_revision
        for entry in self._entries:
            if entry.seq > v:  # type: ignore[operator]
                break
            if entry.resolved_ops:
                revision += 1
        return revision

    def _append(self, kind, memory, run, batch, ops, report, error) -> SubmitResult:
        result = super()._append(kind, memory, run, batch, ops, report, error)
        if ops:
            self._revision += 1
        return result


@dataclass(frozen=True)
class Submitted:
    """What :meth:`LiveConfiguration.submit` did."""

    #: The report, in the shape ``ChangeService.apply`` returns, with ``persisted: False``.
    report: dict[str, Any]
    #: The configuration changed (a new revision, a new episode version).
    applied: bool
    change: LiveChange | None = None


@dataclass(frozen=True)
class Finished:
    """What :meth:`LiveConfiguration.finish_run` did."""

    #: The episode version the entry took (always one).
    version: int
    #: What the memory merge returned.
    memory: Any
    applied: bool
    change: LiveChange | None = None
    #: The reason a proposed batch was refused outright (the run was not failed), else ``None``.
    error: str | None = None


class LiveConfiguration:
    """A live session's configuration: the document, the episode log, the held entries."""

    def __init__(
        self,
        document: cd.ConfigDocument,
        *,
        configuration_id: int,
        revision: int,
        episode_version: int,
        base_hash: str | None = None,
        frozen: bool = False,
        last_change_version: int | None = None,
        saved_at: datetime | None = None,
        resolve: Callable[..., Any] | None = None,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        """*document* is the stored current state (at *revision*); *episode_version* is the
        session's Episodic Memory version at Start, where the episode counter resumes."""
        self.configuration_id = configuration_id
        self.base_hash = base_hash
        self.frozen = frozen
        #: The revision the database holds (the last Stop's), what ``saved_through`` reports.
        self.saved_revision = revision
        self.saved_at = saved_at
        #: The episode version of the last configuration change (``None`` if none is known).
        self.last_change_version = last_change_version
        #: What happened that nobody asked for and nobody saw: a learner that raised, a learner's
        #: batch the layer refused.  In memory only.
        self.diagnostics: list[dict[str, Any]] = []
        self._clock = clock
        self._log = LiveEpisodeLog(
            cd.apply_resolved(document, [], version=episode_version),
            revision=revision, configuration_id=configuration_id, resolve=resolve,
        )
        self.changes: list[LiveChange] = []
        self._provider = cd.provider(self._log.current)

    # -- state ----------------------------------------------------------------------------

    @property
    def log(self) -> LiveEpisodeLog:
        return self._log

    @property
    def document(self) -> cd.ConfigDocument:
        return self._log.current

    @property
    def revision(self) -> int:
        return self._log.configuration_revision

    @property
    def version(self) -> int:
        """The episode version."""
        return self._log.version

    @property
    def provider(self) -> MetadataProvider:
        return self._provider

    @property
    def config_hash(self) -> str:
        return cd.config_hash(self._log.current)

    def ref(self, session_id: int) -> ConfigRef:
        """The configuration a run dispatched now starts under."""
        return ConfigRef(session_id, self.version, self.revision, self.config_hash, self._provider)

    def pending_entries(self) -> list[journal.PendingEntry]:
        """The entries the Stop write stores, in revision order (``journal.write_deferred``)."""
        return [c.pending for c in self.changes]

    def summary(self) -> dict[str, Any]:
        """The ``configuration`` block of a live session's summary."""
        tables = self._log.current.tables
        return {
            "id": self.configuration_id, "version": self.revision, "hash": self.config_hash,
            "base_hash": self.base_hash, "nodes": len(tables[NODES_TABLE]),
            "links": len(tables[LINKS_TABLE]), "last_change_version": self.last_change_version,
            "frozen": self.frozen,
        }

    # -- writing --------------------------------------------------------------------------

    def _after_change(self, previous: cd.ConfigDocument) -> None:
        self._provider = cd.provider(self._log.current, previous)
        self.last_change_version = self._log.version

    def _record(
        self, result: SubmitResult, before_doc: cd.ConfigDocument, batch: Mapping[str, Any],
        run: tuple[int, int] | None, default_source: str, default_actor: str,
    ) -> LiveChange:
        entry = result.entry
        pending = journal.PendingEntry(
            revision=self.revision,
            source=batch.get("source") or default_source,
            actor=batch.get("actor") or default_actor,
            proposed=list(batch.get("ops") or ()),
            resolved=[dict(op) for op in entry.resolved_ops],
            before=list(self._log.last_before or []),
            occurred_at=self._clock(),
            channel=batch.get("channel") or "",
            note=batch.get("note") or "",
            group_id=batch.get("group_id"),
            episode_version=entry.seq,
            config_hash=entry.config_hash,
        )
        change = LiveChange(pending, run)
        self.changes.append(change)
        self._after_change(before_doc)
        return change

    def submit(self, batch: Mapping[str, Any]) -> Submitted:
        """An external or Admin batch: no memory part.

        It takes the next episode version and revision when something applies, and reaches every
        run dispatched afterward.  ``dry_run`` changes nothing.  A refused batch raises (what
        ``resolve`` raised, ``journal.KeyExists`` / ``MissingKey``, or ``StaleBatch`` for a
        ``strict`` batch whose ``base_version`` is not the revision) and changes nothing.
        """
        from server.services import configuration_writer as writer

        before_doc, revision_before = self.document, self.revision
        self._log.last_before = None
        if batch.get("dry_run"):
            ops, base_report = self._log.preview(batch)
            applied, change, resolved = False, None, list(ops)
        else:
            result = self._log.submit_batch(batch)
            base_report = result.report or {}
            applied = result.applied
            resolved = list(result.entry.resolved_ops)
            change = (
                self._record(result, before_doc, batch, None, "external", "system") if applied else None
            )
        report: dict[str, Any] = dict(base_report)
        report.setdefault("ok", True)
        for name in ("skipped", "cascaded", "dangling", "affected", "effects", "advisories"):
            report[name] = list(report.get(name) or [])
        report["effects"].extend(writer.run_start_effects(before_doc, resolved))
        report.update(
            configuration_id=self.configuration_id, version_before=revision_before,
            version_after=self.revision, batch_id=None, persisted=False,
            episode_version=self.version,
        )
        if batch.get("dry_run"):
            report["dry_run"] = True
        return Submitted(report, applied, change)

    def finish_run(
        self,
        *,
        memory_merge: Callable[[], Any] | None,
        batch: Mapping[str, Any] | None = None,
        run: tuple[int, int] | None = None,
        started_revision: int | None = None,
        learner: str = "learner",
    ) -> Finished:
        """The run-finish entry: the memory merge, then the learner's batch, then one version.

        A learner's batch is filled in as the after-run seam promises: ``source = learner``,
        ``actor = learner:<name>``, ``base_version`` the revision the run started from with
        ``base_mode = rebase`` and ``on_op_failure = skip`` (all unless the learner set them).
        """
        before_doc = self.document
        self._log.last_before = None
        if batch is not None:
            filled = {
                "source": "learner", "actor": f"learner:{learner}", "base_mode": "rebase",
                "on_op_failure": "skip", **batch,
            }
            if started_revision is not None:
                filled.setdefault("base_version", started_revision)
            batch = filled
        result = self._log.finish_run(memory_merge=memory_merge, batch=batch, run=run)
        change = (
            self._record(result, before_doc, batch or {}, run, "learner", f"learner:{learner}")
            if result.applied else None
        )
        error = result.entry.error
        if error is not None:
            self.diagnostics.append({
                "kind": "learner_batch_refused", "run": run, "episode_version": result.version,
                "message": error,
            })
        return Finished(result.version, result.entry.memory, result.applied, change, error)

    def diagnose(self, kind: str, message: str, *, run: tuple[int, int] | None = None) -> None:
        """Record something that went wrong without failing anything (a learner that raised)."""
        self.diagnostics.append({"kind": kind, "run": run, "episode_version": self.version,
                                 "message": message})
