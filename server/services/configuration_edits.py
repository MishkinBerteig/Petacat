"""Edit-all: one edit sent to chosen or all configurations, with a preview (configuration plan 3.10.3).

An *edit* is one change batch (3.12) sent to several configurations: the global configuration
(Metacat Mode's) and Training Mode Sessions' configurations.  Nothing about the ops depends on
the target.  Editing "all" is a human Admin action, so every batch sent here has ``source =
admin``, ``actor = admin``, exactly one ``configuration_id`` and, on commit, the edit's shared
``group_id`` (M3).  Each target takes the batch through :meth:`ChangeService.apply`, the one door,
so a live session takes it in memory (``persisted: false``, 3.16.3) and a stored target in its own
transaction, journal entry and revision bump.  Nothing here is a second writer.

The result per target (3.10.3):

=====================  ==========================================================================
``apply``              the batch applies (preview) / was applied (commit)
``no_change``          already equal
``differs``            an ``expect`` does not match; ``overwrite`` re-sends without ``expect``
``not_applicable``     a key or reference the target lacks; ``apply_rest`` re-sends the ops that do
                       apply (``on_op_failure = skip``)
``stale``              the target's revision moved since the preview; the commit re-previews it
                       (``re_preview``) and writes nothing to it
``skipped_by_selection``  the target is ``frozen`` (a default of "all"), or a session in Starting
                       or Stopping ("changing state"); never sent
=====================  ==========================================================================

**The preview token** is the preview's own state, base64 of JSON: the ops, the note and each
target's id with the revision its preview was computed on.  It holds no secret and nothing a
caller could not send directly (this is the Admin API), so it is not signed.

**Commit.**  Per target all-or-nothing, in order (the global configuration first, then sessions by
id).  A target that is not reached never blocks another.  ``all_or_nothing`` is defined as in
3.16.3: every target is re-validated first (``dry_run``); if any reached target is not
``apply`` or ``no_change`` nothing is written to any target; otherwise the stored targets are
written in one database transaction, then the live ones are applied in memory.  The live targets'
locks are not held across the stored commit (the session service takes them per batch); a live
target whose revision moved in that gap reports ``stale`` and ``persisted: false`` while the
stored targets stay committed, and the group's report says so.
"""

from __future__ import annotations

import base64
import json
import uuid
from typing import Any, Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.models.journal import GLOBAL_CONFIGURATION_ID, KIND_GLOBAL, Configuration
from server.services import configurations, journal
from server.services import configuration_writer as writer
from server.services.configuration_store import live_state
from server.services.configuration_writer import ChangeError, ChangeService

APPLY = "apply"
NO_CHANGE = "no_change"
DIFFERS = "differs"
NOT_APPLICABLE = "not_applicable"
STALE = "stale"
SKIPPED_BY_SELECTION = "skipped_by_selection"
RESULTS = (APPLY, NO_CHANGE, DIFFERS, NOT_APPLICABLE, STALE, SKIPPED_BY_SELECTION)
#: Results that make an all-or-nothing commit write nothing.
BLOCKING = frozenset({DIFFERS, NOT_APPLICABLE, STALE})

ACTOR = "admin"
CHANNEL = "edit_all"
TOKEN_VERSION = 1


class EditError(Exception):
    """The request, not a target, is wrong (HTTP ``status``)."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


# ---------------------------------------------------------------------------
# Targets
# ---------------------------------------------------------------------------


async def _targets(session: AsyncSession) -> dict[int, dict[str, Any]]:
    """Every configuration as a target: its selection facts and the revision a batch is checked
    against (the live revision for a live session, the stored one otherwise)."""
    rows = (await session.execute(select(Configuration).order_by(Configuration.id))).scalars().all()
    names = await configurations._session_names(session)
    out: dict[int, dict[str, Any]] = {}
    for row in rows:
        is_global = row.kind == KIND_GLOBAL
        live = None if is_global else live_state(row.session_id)
        session_name = None if is_global else names.get(row.session_id)
        out[row.id] = {
            "configuration_id": row.id,
            "name": row.name,
            "mode": configurations.MODE_GLOBAL if is_global else configurations.MODE_SESSION,
            "mode_label": configurations.MODE_GLOBAL if is_global
            else f"{configurations.MODE_SESSION}: {session_name}",
            "session_id": row.session_id,
            "session_state": None if is_global else (live.state if live else "stopped"),
            "frozen": bool(row.frozen),
            "revision": live.revision if live is not None else row.revision,
            "live": live is not None,
        }
    return out


def _selection_skip(target: Mapping[str, Any], *, by_default: bool) -> str | None:
    if target["session_state"] in ("starting", "stopping"):
        return "changing state"
    if by_default and target["frozen"]:
        return "frozen"
    return None


def _describe(target: Mapping[str, Any], result: str, **extra: Any) -> dict[str, Any]:
    keys = ("configuration_id", "name", "mode", "mode_label", "session_id", "session_state", "frozen")
    out = {k: target[k] for k in keys}
    out["result"] = result
    out.update(extra)
    return out


# ---------------------------------------------------------------------------
# Batches and classification
# ---------------------------------------------------------------------------


def _strip_expect(ops: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [{k: v for k, v in op.items() if k != "expect"} for op in ops]


def _batch(
    target: Mapping[str, Any], ops: Sequence[Mapping[str, Any]], *, base_version: Any, note: str,
    dry_run: bool, group_id: str | None = None, overwrite: bool = False, apply_rest: bool = False,
) -> dict[str, Any]:
    batch: dict[str, Any] = {
        "configuration_id": target["configuration_id"],
        "source": "admin",
        "actor": ACTOR,
        "channel": CHANNEL,
        "note": note,
        "base_version": base_version,
        "base_mode": "strict",
        "on_op_failure": "skip" if apply_rest else "abort",
        "dry_run": dry_run,
        "ops": _strip_expect(ops) if overwrite else [dict(op) for op in ops],
    }
    if group_id is not None:
        batch["group_id"] = group_id
    return batch


def _classify_report(report: Mapping[str, Any]) -> tuple[str, str]:
    applied = report.get("applied") or []
    skipped = report.get("skipped") or []
    if applied:
        return APPLY, ""
    if skipped:
        first = skipped[0].get("reason") or {}
        return NOT_APPLICABLE, first.get("message", "no op applies to this configuration")
    return NO_CHANGE, "already equal"


def _classify_error(exc: ChangeError) -> tuple[str, str]:
    """A refusal as a result.  A malformed or unauthorised batch is the request's fault and is
    raised again for the caller (it would be the same for every target)."""
    if exc.code == writer.BUSY:
        return SKIPPED_BY_SELECTION, "changing state"
    if exc.code == "stale":
        fields = {p.get("field") for p in exc.problems}
        return (STALE if "base_version" in fields or not fields else DIFFERS), exc.message
    if exc.code in ("unknown_reference", "key_exists", "does_not_compile"):
        return NOT_APPLICABLE, exc.message
    raise exc


async def _evaluate(
    session: AsyncSession, target: Mapping[str, Any], batch: dict[str, Any]
) -> tuple[str, str, dict[str, Any] | None]:
    """Send *batch* through the one door: ``(result, reason, report)``."""
    try:
        report = await ChangeService.apply(session, batch)
    except ChangeError as exc:
        result, reason = _classify_error(exc)
        return result, reason, None
    result, reason = _classify_report(report)
    return result, reason, report


def _written(target: Mapping[str, Any], result: str, reason: str, report: Mapping[str, Any] | None,
             revision: int | None, **extra: Any) -> dict[str, Any]:
    out = _describe(target, result, reason=reason, revision=revision, **extra)
    if report is not None:
        out["report"] = dict(report)
        out["persisted"] = bool(report.get("persisted"))
    return out


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


def encode_token(
    ops: Sequence[Mapping[str, Any]], note: str, revisions: Mapping[int, tuple[int | None, str | None]]
) -> str:
    """*revisions* maps each target to ``(revision, skip)``: the revision its preview was
    computed on, or ``None`` and the reason it was skipped by selection."""
    body = {
        "v": TOKEN_VERSION, "ops": list(ops), "note": note,
        "targets": [{"id": i, "revision": r, "skip": k} for i, (r, k) in revisions.items()],
    }
    return base64.urlsafe_b64encode(json.dumps(body, separators=(",", ":")).encode()).decode()


def decode_token(token: str) -> dict[str, Any]:
    try:
        body = json.loads(base64.urlsafe_b64decode(token.encode()))
        if body["v"] != TOKEN_VERSION or not isinstance(body["ops"], list):
            raise ValueError("version")
        body["targets"] = [(int(t["id"]), t["revision"], t["skip"]) for t in body["targets"]]
    except Exception as exc:
        raise EditError(400, "the preview token is not valid: preview again") from exc
    return body


def _choose(
    targets: Mapping[int, Mapping[str, Any]], ids: Sequence[int] | None, all_: bool
) -> list[int]:
    if all_ == bool(ids):
        raise EditError(400, "give targets as {ids: [...]} or {all: true}")
    if all_:
        return list(targets)
    unknown = [i for i in ids if i not in targets]
    if unknown:
        raise EditError(404, f"no configuration {unknown[0]}")
    return sorted(set(ids))


async def preview(
    session: AsyncSession,
    ops: Sequence[Mapping[str, Any]],
    *,
    ids: Sequence[int] | None = None,
    all_: bool = False,
    base_revisions: Mapping[int, int] | None = None,
    note: str = "",
) -> dict[str, Any]:
    """``dry_run`` the edit on each target: one result per target and the preview token.

    ``all_`` selects every configuration (a ``frozen`` one is ``skipped_by_selection``);
    ``ids`` selects those named, which are sent even when ``frozen`` (naming it is the
    selection).  ``base_revisions`` is the revision the caller's editor read, per target; a
    target not named is previewed at its head.  A target whose revision is not the one named is
    ``stale``.
    """
    targets = await _targets(session)
    chosen = _choose(targets, ids, all_)
    base_revisions = dict(base_revisions or {})
    results: list[dict[str, Any]] = []
    revisions: dict[int, tuple[int | None, str | None]] = {}
    for cid in chosen:
        target = targets[cid]
        skip = _selection_skip(target, by_default=all_)
        if skip:
            revisions[cid] = (None, skip)
            results.append(_describe(target, SKIPPED_BY_SELECTION, reason=skip,
                                     revision=target["revision"]))
            continue
        base = base_revisions.get(cid, target["revision"])
        revisions[cid] = (base, None)
        result, reason, report = await _evaluate(
            session, target, _batch(target, ops, base_version=base, note=note, dry_run=True))
        extra = {"current_revision": target["revision"]} if result == STALE else {}
        results.append(_written(target, result, reason, report, base, **extra))
    return {
        "preview_token": encode_token(ops, note, revisions),
        "targets": results,
        "counts": _counts(results),
    }


def _counts(results: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts = {name: 0 for name in RESULTS}
    for r in results:
        counts[r["result"]] += 1
    return counts


# ---------------------------------------------------------------------------
# Commit
# ---------------------------------------------------------------------------


async def commit(
    session: AsyncSession,
    preview_token: str,
    *,
    overwrite: Sequence[int] = (),
    apply_rest: Sequence[int] = (),
    all_or_nothing: bool = False,
    reason: str = "",
) -> dict[str, Any]:
    """Commit the previewed edit.  ``overwrite`` and ``apply_rest`` name targets to re-send
    without ``expect`` and with the ops that do apply.  Returns ``group_id`` and one result per
    target; ``committed`` is false only when ``all_or_nothing`` held every target back."""
    token = decode_token(preview_token)
    ops: list[dict[str, Any]] = token["ops"]
    note = reason or token["note"]
    overwrite_ids, rest_ids = set(overwrite), set(apply_rest)
    group_id = f"edit-all-{uuid.uuid4().hex}"
    targets = await _targets(session)
    plan = [(targets.get(cid), cid, base, skip) for cid, base, skip in token["targets"]]

    if all_or_nothing:
        return await _commit_all_or_nothing(
            session, plan, ops, note, group_id, overwrite_ids, rest_ids)

    results: list[dict[str, Any]] = []
    for target, cid, base, skip in plan:
        results.append(await _commit_one(
            session, target, cid, base, skip, ops, note, group_id, overwrite_ids, rest_ids))
    return {"group_id": group_id, "committed": True, "all_or_nothing": False,
            "targets": results, "counts": _counts(results)}


def _gone(cid: int) -> dict[str, Any]:
    return {"configuration_id": cid, "result": SKIPPED_BY_SELECTION,
            "reason": "the configuration no longer exists", "revision": None}


async def _commit_one(session, target, cid, base, skip_at_preview, ops, note, group_id, overwrite_ids, rest_ids):
    if target is None:
        return _gone(cid)
    skip = _skip_at_commit(target, skip_at_preview)
    if skip:
        return _describe(target, SKIPPED_BY_SELECTION, reason=skip, revision=target["revision"])
    if base is None:  # skipped at the preview, reachable now: the preview does not cover it
        return await _stale(session, target, ops, note,
                            "the target was not reachable at the preview; preview again")
    overwrite, rest = cid in overwrite_ids, cid in rest_ids
    batch = _batch(target, ops, base_version=base, note=note, dry_run=False, group_id=group_id,
                   overwrite=overwrite, apply_rest=rest)
    result, why, report = await _evaluate(session, target, batch)
    if result == STALE:
        return await _stale(session, target, ops, note, why)
    if result == SKIPPED_BY_SELECTION:
        return _describe(target, result, reason=why, revision=target["revision"])
    out = _written(target, result, why, report, base)
    if report is not None and result == APPLY:
        out.update(batch_id=report.get("batch_id"), version_before=report.get("version_before"),
                   version_after=report.get("version_after"))
    return out


def _skip_at_commit(target, skip_at_preview):
    """A target skipped at the preview for ``frozen`` stays skipped (that was the selection); one
    skipped for "changing state" is skipped only while it still is.  A target sent at the preview
    is skipped now only if it is changing state."""
    if skip_at_preview == "frozen":
        return "frozen"
    return _selection_skip(target, by_default=False)


async def _stale(session, target, ops, note, why):
    """Re-preview a target whose revision moved: write nothing, say what it would do now."""
    fresh, fresh_why, _ = await _evaluate(
        session, target, _batch(target, ops, base_version="head", note=note, dry_run=True))
    return _describe(
        target, STALE, reason=why, revision=target["revision"],
        re_preview={"result": fresh, "reason": fresh_why, "revision": target["revision"]})


# --- all or nothing (3.16.3) -----------------------------------------------


async def _commit_all_or_nothing(session, plan, ops, note, group_id, overwrite_ids, rest_ids):
    results: dict[int, dict[str, Any]] = {}
    reached: list[tuple[Mapping[str, Any], int, int]] = []
    for target, cid, base, skip_at_preview in plan:
        if target is None:
            results[cid] = _gone(cid)
            continue
        skip = _skip_at_commit(target, skip_at_preview)
        if skip:
            results[cid] = _describe(target, SKIPPED_BY_SELECTION, reason=skip,
                                     revision=target["revision"])
        elif base is None:
            results[cid] = await _stale(session, target, ops, note,
                                        "the target was not reachable at the preview; preview again")
        else:
            reached.append((target, cid, base))

    def batch_for(target, cid, base, dry_run):
        return _batch(target, ops, base_version=base, note=note, dry_run=dry_run, group_id=group_id,
                      overwrite=cid in overwrite_ids, apply_rest=cid in rest_ids)

    # 1. Validate every reached target (a dry run through the one door; each ends its transaction).
    validated: dict[int, tuple[str, str, Any]] = {}
    for target, cid, base in reached:
        validated[cid] = await _evaluate(session, target, batch_for(target, cid, base, True))
    blocked = [cid for cid, (r, _why, _rep) in validated.items()
               if r in BLOCKING or r == SKIPPED_BY_SELECTION]
    if blocked:
        for target, cid, base in reached:
            r, why, report = validated[cid]
            if r == STALE:
                results[cid] = await _stale(session, target, ops, note, why)
            else:
                results[cid] = _written(target, r, why, report, base, committed=False)
        ordered = [results[c] for _, c, _, _ in plan]
        return {"group_id": group_id, "committed": False, "all_or_nothing": True,
                "blocked_by": blocked, "targets": ordered, "counts": _counts(ordered)}

    # 2. Commit the stored targets that change, in one database transaction, locks in id order.
    stored = [(t, c, b) for t, c, b in reached if not t["live"] and validated[c][0] == APPLY]
    live = [(t, c, b) for t, c, b in reached if t["live"] and validated[c][0] == APPLY]
    for target, cid, base in reached:
        if validated[cid][0] == NO_CHANGE:
            results[cid] = _written(target, NO_CHANGE, validated[cid][1], validated[cid][2], base)
    try:
        written = await _write_stored(session, stored, batch_for)
    except ChangeError as exc:
        # A revision moved between validation and the locks: nothing was written.
        await session.rollback()
        moved = getattr(exc, "configuration_id", None)
        for target, cid, base in reached:
            if cid in results:
                continue
            if cid == moved:
                results[cid] = await _stale(session, target, ops, note, exc.message)
            else:
                results[cid] = _written(target, APPLY, "", None, base, committed=False)
        ordered = [results[c] for _, c, _, _ in plan]
        return {"group_id": group_id, "committed": False, "all_or_nothing": True,
                "blocked_by": [], "targets": ordered, "counts": _counts(ordered)}
    for (target, cid, base), report in zip(stored, written):
        results[cid] = _written(
            target, APPLY, "", report, base, committed=True, batch_id=report["batch_id"],
            version_before=report["version_before"], version_after=report["version_after"])
    # 3. Apply the live targets in memory.
    for target, cid, base in live:
        results[cid] = await _commit_one(session, target, cid, base, None, ops, note, group_id,
                                         overwrite_ids, rest_ids)
        results[cid]["committed"] = results[cid]["result"] == APPLY
    ordered = [results[c] for _, c, _, _ in plan]
    return {"group_id": group_id, "committed": True, "all_or_nothing": True,
            "persisted_false": [r["configuration_id"] for r in ordered if r.get("persisted") is False
                                and r["result"] == APPLY],
            "targets": ordered, "counts": _counts(ordered)}


async def _write_stored(session, stored, batch_for) -> list[dict[str, Any]]:
    """Lock, re-resolve and write every stored target in one transaction, then commit."""
    from server.services import config_document

    reports: list[dict[str, Any]] = []
    global_changed = False
    try:
        for target, cid, base in sorted(stored, key=lambda s: s[1]):
            batch = batch_for(target, cid, base, False)
            try:
                locked = await journal._lock_configuration(session, cid)
            except journal.JournalError as exc:
                raise ChangeError(writer.UNKNOWN_CONFIGURATION, str(exc)) from exc
            journal._check_source(locked["kind"], batch["source"])
            if locked["revision"] != base:
                exc = ChangeError("stale", f"base_version {base} is not the current version "
                                  f"{locked['revision']}",
                                  [{"error": "stale", "status": 409, "field": "base_version"}])
                exc.configuration_id = cid
                raise exc
            if locked["kind"] == KIND_GLOBAL:
                cfg = await config_document.document_from_db(session, version=locked["revision"])
            else:
                cfg = await configurations.current_document(session, cid)
            resolve_batch = {n: batch[n] for n in writer._RESOLVE_FIELDS if n in batch}
            resolved, report = writer._resolve_function()(cfg, resolve_batch)
            resolved = list(resolved)
            report = dict(report)
            for name in ("skipped", "cascaded", "dangling", "affected", "effects", "advisories"):
                report[name] = list(report.get(name) or [])
            report.update(ok=True, configuration_id=cid, version_before=locked["revision"])
            report["effects"].extend(writer.run_start_effects(cfg, resolved))
            result = await journal.write_immediate(
                session, ops=resolved, proposed=list(batch["ops"]), source=batch["source"],
                actor=ACTOR, configuration_id=cid, channel=CHANNEL, note=batch["note"],
                group_id=batch["group_id"], expected_revision=base, commit=False)
            report.update(version_after=result.revision, batch_id=result.entry_id,
                          persisted=result.changed)
            reports.append(report)
            global_changed = global_changed or (cid == GLOBAL_CONFIGURATION_ID and result.changed)
        await session.commit()
    except BaseException as exc:
        await session.rollback()
        translated = writer._translate(exc)
        if translated is not None and translated is not exc:
            raise translated from exc
        raise
    if global_changed:
        await journal._run_global_commit_hook(session)
    return reports
