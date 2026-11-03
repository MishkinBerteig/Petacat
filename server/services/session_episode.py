"""The episode layer of a Training Mode Session: ``EpisodeLog``.

A pure library: no database, no clock, no randomness.  It holds, for one session, the base
configuration (the Starting Conceptual State, as a ``ConfigDocument``), the one version counter
over Episodic Memory and the whole configuration, and the entries that advanced it.

Entries
-------
* **A run-finish entry** (``finish_run``) is one entry, in this order: the memory merge (the
  caller's callable), then the run's change batch (resolved against the configuration as it stands
  now, which may be newer than the run's snapshot), then one version.  An empty entry still takes
  a version, as a memory merge does.
* **An external or Admin batch** (``submit_batch``) is an entry with no memory part.  When nothing
  applies it takes no version and is kept as a diagnostic (``seq`` None).

Merging is by ``resolve`` (the configuration plan's 3.12.0), which turns relative ops into absolute
values against the configuration as it stands and guards absolute ops with ``expect``; the log
supplies the current configuration and passes ``base_mode`` and ``on_op_failure`` through in the
batch.  First merged wins; a loser is a skipped op in its entry's report.

The configuration at version ``v`` is a pure function of the base and the entries up to ``v``
(``config_at``).  ``configuration_revision`` is the version of the last entry that changed the
configuration; ``version >= configuration_revision`` always.

Nothing here knows what Episodic Memory holds, so removing or renaming a node that memory names
is an ordinary op.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from server.services.config_document import ConfigDocument, apply_resolved, config_hash

Op = Mapping[str, Any]
Batch = Mapping[str, Any]
Resolve = Callable[[ConfigDocument, Batch], tuple[Sequence[Op], dict[str, Any]]]


def _default_resolve(cfg: ConfigDocument, batch: Batch) -> tuple[Sequence[Op], dict[str, Any]]:
    from server.services.change_resolve import resolve

    return resolve(cfg, batch)


class StaleBatch(ValueError):
    """A ``strict`` batch whose ``base_version`` is not the configuration revision (409 ``stale``).

    ``resolve`` does not read ``base_version``; the compare-and-set is the caller's.  For a
    session's configuration that caller is this log.  ``rebase`` never raises it.
    """

    kind = "stale"


@dataclass(frozen=True)
class Entry:
    """One advance of the episode (or, with ``seq`` None, a diagnostic that advanced nothing)."""

    seq: int | None
    kind: str  # "run" | "batch"
    memory: Any  # whatever the memory merge returned, or None
    run: Any  # the caller's run reference, or None
    proposed_batch: Mapping[str, Any] | None
    resolved_ops: tuple[Op, ...]
    skipped: tuple[Any, ...]
    report: Mapping[str, Any] | None
    error: str | None  # the reason a proposed batch was refused outright
    configuration_revision: int
    config_hash: str

    @property
    def changed_configuration(self) -> bool:
        return bool(self.resolved_ops)


@dataclass(frozen=True)
class SubmitResult:
    """What ``submit_batch`` and ``finish_run`` return."""

    entry: Entry
    version: int  # the log's version after the call
    applied: bool  # the configuration changed
    report: Mapping[str, Any] | None


class EpisodeLog:
    def __init__(self, base: ConfigDocument, resolve: Resolve | None = None) -> None:
        self._base = base
        self._resolve: Resolve = resolve or _default_resolve
        self._current = base
        self._version = base.version
        self._entries: list[Entry] = []
        self._diagnostics: list[Entry] = []

    # -- state ----------------------------------------------------------------------------

    @property
    def base(self) -> ConfigDocument:
        return self._base

    @property
    def current(self) -> ConfigDocument:
        return self._current

    @property
    def version(self) -> int:
        """The episode version: the ``seq`` of the last entry (the base's version when none)."""
        return self._version

    @property
    def configuration_revision(self) -> int:
        """The version of the last entry that changed the configuration (derived)."""
        return self._current.version

    @property
    def entries(self) -> tuple[Entry, ...]:
        return tuple(self._entries)

    @property
    def diagnostics(self) -> tuple[Entry, ...]:
        """External or Admin batches where nothing applied; they took no version."""
        return tuple(self._diagnostics)

    def config_hash(self) -> str:
        return config_hash(self._current)

    # -- reading ----------------------------------------------------------------------------

    def config_at(self, v: int) -> ConfigDocument:
        """The configuration at episode version *v*: the base plus the entries with ``seq <= v``."""
        if v < self._base.version or v > self._version:
            raise ValueError(f"version {v} outside {self._base.version}..{self._version}")
        cfg = self._base
        for e in self._entries:
            if e.seq > v:  # type: ignore[operator]
                break
            if e.resolved_ops:
                cfg = apply_resolved(cfg, e.resolved_ops, version=e.seq)
        return cfg

    def configuration_revision_at(self, v: int) -> int:
        return self.config_at(v).version

    def _admit(self, batch: Batch) -> None:
        """The compare-and-set on ``base_version`` (``strict`` only; ``rebase`` and ``head`` skip it)."""
        base_version = batch.get("base_version")
        if batch.get("base_mode", "strict") == "strict" and base_version not in (None, "head"):
            if base_version != self.configuration_revision:
                raise StaleBatch(
                    f"base_version {base_version} is not the configuration revision {self.configuration_revision}"
                )

    # -- writing ----------------------------------------------------------------------------

    def preview(self, batch: Batch) -> tuple[tuple[Op, ...], dict[str, Any]]:
        """Resolve *batch* against the current configuration and change nothing (dry run)."""
        self._admit(batch)
        ops, report = self._resolve(self._current, batch)
        return tuple(ops), dict(report)

    def submit_batch(self, batch: Batch, *, run: Any = None) -> SubmitResult:
        """An external or Admin batch: no memory part.

        Takes the next version only if something applies.  A batch that ``resolve`` refuses
        raises what ``resolve`` raised and changes nothing.  ``dry_run`` in the batch resolves
        and changes nothing.
        """
        self._admit(batch)
        ops, report = self._resolve(self._current, batch)
        ops = tuple(ops)
        if batch.get("dry_run"):
            entry = self._make_entry(None, "batch", None, run, batch, ops, report, None)
            return SubmitResult(entry, self._version, False, report)
        if not ops:
            entry = self._make_entry(None, "batch", None, run, batch, ops, report, None)
            self._diagnostics.append(entry)
            return SubmitResult(entry, self._version, False, report)
        return self._append("batch", None, run, batch, ops, report, None)

    def finish_run(
        self,
        *,
        memory_merge: Callable[[], Any] | None = None,
        batch: Batch | None = None,
        run: Any = None,
    ) -> SubmitResult:
        """The run-finish entry: the memory merge, then the run's batch, then one version.

        A batch the layer refuses outright (``resolve`` raises) never fails the run: the memory
        merge stands, the version is taken, and the entry records the reason in ``error``.
        """
        memory = memory_merge() if memory_merge is not None else None
        ops: tuple[Op, ...] = ()
        report: dict[str, Any] | None = None
        error: str | None = None
        if batch is not None:
            try:
                self._admit(batch)
                got, report = self._resolve(self._current, batch)
                ops = tuple(got)
            except Exception as exc:  # noqa: BLE001 - a learner's batch never fails its run
                report, error = None, f"{type(exc).__name__}: {exc}"
        return self._append("run", memory, run, batch, ops, report, error)

    # -- internals ------------------------------------------------------------------------------

    def _append(
        self,
        kind: str,
        memory: Any,
        run: Any,
        batch: Batch | None,
        ops: tuple[Op, ...],
        report: Mapping[str, Any] | None,
        error: str | None,
    ) -> SubmitResult:
        seq = self._version + 1
        cfg = apply_resolved(self._current, ops, version=seq) if ops else self._current
        entry = self._make_entry(seq, kind, memory, run, batch, ops, report, error, cfg)
        self._current = cfg
        self._entries.append(entry)
        self._version = seq
        return SubmitResult(entry, seq, bool(ops), report)

    def _make_entry(
        self,
        seq: int | None,
        kind: str,
        memory: Any,
        run: Any,
        batch: Batch | None,
        ops: tuple[Op, ...],
        report: Mapping[str, Any] | None,
        error: str | None,
        cfg: ConfigDocument | None = None,
    ) -> Entry:
        if cfg is None:  # nothing applied and no version: the configuration is the current one
            cfg = self._current
        skipped = tuple((report or {}).get("skipped", ()) or ())
        return Entry(
            seq=seq,
            kind=kind,
            memory=memory,
            run=run,
            proposed_batch=dict(batch) if batch is not None else None,
            resolved_ops=ops,
            skipped=skipped,
            report=report,
            error=error,
            configuration_revision=cfg.version,
            config_hash=config_hash(cfg),
        )
