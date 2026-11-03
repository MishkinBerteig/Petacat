"""The validation funnel: ``ChangeService.apply`` is the one entry point for every batch writer.

The configuration plan, 3.4, 3.12.0, 3.12.1 and 3.12.7.  Every writer that submits a batch (an
Admin editor, the Database editor, restore, reset, import, the external route, and the in-worker
learner after a run) calls :meth:`ChangeService.apply`.  It is the seam a learner calls; the
learner itself is not part of v2.0.

The steps, in order:

1. **The envelope** (400 ``malformed``): the batch is an object with only the known fields, each of
   the right type.  The ops themselves are read by ``resolve``.
2. **The target** is locked (``SELECT ... FOR UPDATE`` on its ``configurations`` row), so the
   compare-and-set below cannot race.  Only the global configuration is handled: a session's
   configuration raises ``NotImplementedError`` until C8.
3. **The source**: the global configuration (Metacat Mode) refuses ``learner`` and ``external``
   (M2), so a refused batch never reaches ``resolve`` and a ``dry_run`` is refused too.
4. **The compare-and-set** on ``base_version``.  Under ``strict`` a stale base is 409 ``stale``.
   Under ``rebase`` (or ``base_version: "head"``) the batch proceeds and each op's own ``expect``
   guards it.
5. **Resolve** (``change_resolve.resolve``) on the configuration's document: convenience ops and
   cascades are expanded, and the four classes of refusal of 3.4(a) are decided.  With
   ``dry_run`` the report is returned and nothing is written.
6. **Write** through ``journal.write_immediate``: proposed ops, resolved ops and provenance
   (``source``, ``actor``, ``channel``, ``note``, ``group_id``).  The journal re-checks the revision
   under its own lock (``expected_revision``).
7. **The report**: ``resolve``'s report plus ``batch_id`` (the journal entry id), ``version_before``,
   ``version_after`` and ``persisted``.

The **run-start check hook**: after resolution the configuration as it would stand is run through
the engine's run-start check (``server/engine/start_check.py``, I-1 and I-2) and what it would now
stop is listed in ``effects``.  It never refuses a change.

Errors are one exception type, :class:`ChangeError`, with the plan's codes; :func:`error_body` and
:func:`error_response` turn one into the HTTP answer for the endpoints.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from server.models.journal import GLOBAL_CONFIGURATION_ID, KIND_GLOBAL
from server.services import journal
from server.services.configuration_input import (
    BASE_MODES,
    DOES_NOT_COMPILE,
    KEY_EXISTS,
    MALFORMED,
    ON_OP_FAILURE,
    SOURCES,
    STALE,
    STATUS,
    UNKNOWN_REFERENCE,
    check_base_version,
)

logger = logging.getLogger(__name__)

#: The codes besides the four classes of ``configuration_input``.
SOURCE_REFUSED = "source_refused"
UNKNOWN_CONFIGURATION = "unknown_configuration"

#: HTTP status per code.  ``source_refused`` is the M2 refusal: the global configuration does not
#: take Training Mode sources.
HTTP_STATUS: dict[str, int] = {
    **STATUS,
    SOURCE_REFUSED: 403,
    UNKNOWN_CONFIGURATION: 404,
}

#: The batch fields ``resolve`` knows (``configuration_input.ENVELOPE_FIELDS``).
_RESOLVE_FIELDS = (
    "configuration_id", "base_version", "base_mode", "source", "actor", "note", "ops",
    "on_op_failure", "dry_run",
)
#: Provenance the funnel accepts besides: the finer route (3.12.1) and the group of an edit-all.
_FUNNEL_FIELDS = frozenset(_RESOLVE_FIELDS) | {"channel", "group_id"}


class ChangeError(Exception):
    """A batch refused; nothing was written.

    ``code`` is one of ``malformed``, ``unknown_reference``, ``does_not_compile``, ``stale``,
    ``key_exists``, ``source_refused`` and ``unknown_configuration``.  ``problems`` is a list of
    dicts naming the op (``op_index``, ``field``, ``table``, ``key``, ``language``, ``line``,
    ``column``, ``message``), the shape of ``InputProblem.as_dict``.
    """

    def __init__(self, code: str, message: str, problems: list[dict[str, Any]] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.problems = problems or []

    @property
    def status(self) -> int:
        return HTTP_STATUS.get(self.code, 400)


def error_body(exc: ChangeError) -> dict[str, Any]:
    """The JSON body of the HTTP answer for *exc*."""
    return {
        "ok": False,
        "error": exc.code,
        "status": exc.status,
        "message": exc.message,
        "problems": exc.problems,
    }


def error_response(exc: ChangeError):
    """A FastAPI ``JSONResponse`` for *exc*, for the endpoints (C14b)."""
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=exc.status, content=error_body(exc))


# ---------------------------------------------------------------------------
# The envelope
# ---------------------------------------------------------------------------


def _malformed(message: str, field: str | None = None) -> ChangeError:
    problem: dict[str, Any] = {"error": MALFORMED, "status": 400, "message": message}
    if field is not None:
        problem["field"] = field
    return ChangeError(MALFORMED, message, [problem])


def check_envelope(batch: Any) -> None:
    """Raise a 400 ``malformed`` :class:`ChangeError` unless *batch* is a well-formed envelope."""
    if not isinstance(batch, Mapping):
        raise _malformed("the batch must be an object")
    for name in batch:
        if name not in _FUNNEL_FIELDS:
            raise _malformed(f"unknown batch field {name!r}", str(name))
    ops = batch.get("ops")
    if not isinstance(ops, list):
        raise _malformed("ops must be a list", "ops")
    for i, op in enumerate(ops):
        if not isinstance(op, Mapping):
            problem = {"error": MALFORMED, "status": 400, "message": "an op must be an object",
                       "op_index": i, "field": "op"}
            raise ChangeError(MALFORMED, "an op must be an object", [problem])
    if "configuration_id" in batch:
        value = batch["configuration_id"]
        if isinstance(value, bool) or not isinstance(value, int):
            raise _malformed("configuration_id must be an integer", "configuration_id")
    if batch.get("source") not in SOURCES:
        raise _malformed(f"source must be one of {SOURCES}", "source")
    if "base_mode" in batch and batch["base_mode"] not in BASE_MODES:
        raise _malformed(f"base_mode must be one of {BASE_MODES}", "base_mode")
    if "on_op_failure" in batch and batch["on_op_failure"] not in ON_OP_FAILURE:
        raise _malformed(f"on_op_failure must be one of {ON_OP_FAILURE}", "on_op_failure")
    if "dry_run" in batch and not isinstance(batch["dry_run"], bool):
        raise _malformed("dry_run must be true or false", "dry_run")
    for name in ("actor", "note", "channel", "group_id"):
        if name in batch and batch[name] is not None and not isinstance(batch[name], str):
            raise _malformed(f"{name} must be text", name)
    if "base_version" in batch:
        value = batch["base_version"]
        if value != "head" and (isinstance(value, bool) or not isinstance(value, int)):
            raise _malformed('base_version must be an integer revision or "head"', "base_version")


# ---------------------------------------------------------------------------
# resolve: the real one (C14a) once it exists
# ---------------------------------------------------------------------------


def _stub_resolve(cfg: Any, batch: Mapping[str, Any]) -> tuple[list[dict], dict[str, Any]]:
    """Stands in for ``change_resolve.resolve`` until it lands: generic ops pass through."""
    report = {
        "ok": True, "applied": [], "skipped": [], "cascaded": [], "dangling": [], "affected": [],
        "effects": [], "advisories": [],
    }
    return list(batch["ops"]), report


def _resolve_function():
    try:
        from server.services.change_resolve import resolve
    except ImportError:
        return _stub_resolve
    return resolve


def _problem_dict(problem: Any) -> dict[str, Any]:
    if isinstance(problem, Mapping):
        return dict(problem)
    as_dict = getattr(problem, "as_dict", None)
    if callable(as_dict):
        return as_dict()
    return {"message": str(problem)}


def _translate(exc: BaseException) -> ChangeError | None:
    """Map what ``resolve`` or the journal raised to a :class:`ChangeError`; ``None`` if unknown."""
    if isinstance(exc, ChangeError):
        return exc
    if isinstance(exc, journal.SourceRefused):
        return ChangeError(SOURCE_REFUSED, str(exc))
    if isinstance(exc, journal.StaleRevision):
        return ChangeError(STALE, str(exc))
    if isinstance(exc, journal.KeyExists):
        return ChangeError(KEY_EXISTS, str(exc))
    if isinstance(exc, journal.MissingKey):
        return ChangeError(UNKNOWN_REFERENCE, str(exc))
    problems = getattr(exc, "problems", None)
    code = getattr(exc, "code", None) or getattr(exc, "kind", None)
    if problems and not code:
        code = _problem_dict(problems[0]).get("error") or getattr(problems[0], "kind", None)
    if code in STATUS:
        listed = [_problem_dict(p) for p in (problems or [])]
        return ChangeError(code, getattr(exc, "message", None) or str(exc), listed)
    return None


# ---------------------------------------------------------------------------
# The run-start check hook
# ---------------------------------------------------------------------------


def run_start_effects(cfg: Any, resolved_ops: list[dict] | None = None) -> list[dict[str, Any]]:
    """What the run-start check would stop on *cfg* after *resolved_ops*, as ``effects`` entries.

    Never raises: if the configuration cannot be turned into a provider, that is one more effect.
    """
    from server.engine.start_check import check_run_start
    from server.services import config_document

    try:
        after = config_document.apply_resolved(cfg, resolved_ops) if resolved_ops else cfg
        problems = check_run_start(config_document.provider(after))
    except Exception as exc:  # a configuration the run could not even load
        return [
            {
                "effect": "run_start_check",
                "check": "I-0",
                "kind": "configuration",
                "name": "",
                "where": "load",
                "message": f"a run would stop: the configuration cannot be loaded ({type(exc).__name__}: {exc})",
            }
        ]
    return [
        {
            "effect": "run_start_check",
            "check": p.check,
            "kind": p.kind,
            "name": p.name,
            "where": p.where,
            "message": f"a run would stop at its start: {p}",
        }
        for p in problems
    ]


# ---------------------------------------------------------------------------
# The service
# ---------------------------------------------------------------------------


class ChangeService:
    """The one entry point for every writer that submits a batch (3.12.7).

    A ``ChangeService`` holds nothing; it exists so that a caller (a learner, a route) holds one
    object whose ``apply`` is the seam.  :meth:`apply` is also a class-level call:
    ``await ChangeService.apply(session, batch)``.
    """

    @staticmethod
    async def apply(session: AsyncSession, batch: Mapping[str, Any]) -> dict[str, Any]:
        """Validate, resolve and write *batch*; return the report.  Raises :class:`ChangeError`.

        Nothing is written unless the call returns a report with ``persisted: true``.  On any
        refusal, and after a ``dry_run``, the transaction is rolled back so the configuration's
        row lock is released.
        """
        check_envelope(batch)
        configuration_id = batch.get("configuration_id", GLOBAL_CONFIGURATION_ID)
        try:
            return await _apply(session, batch, configuration_id)
        except BaseException as exc:
            await session.rollback()
            translated = _translate(exc)
            if translated is not None and translated is not exc:
                raise translated from exc
            raise


async def _apply(session: AsyncSession, batch: Mapping[str, Any], configuration_id: int) -> dict[str, Any]:
    from server.services import config_document

    try:
        locked = await journal._lock_configuration(session, configuration_id)
    except journal.JournalError as exc:
        raise ChangeError(UNKNOWN_CONFIGURATION, str(exc)) from exc
    if locked["kind"] != KIND_GLOBAL:
        raise NotImplementedError(
            "ChangeService.apply handles the global configuration; a session's configuration "
            "is written by the configuration entity (C8)"
        )
    source = batch["source"]
    journal._check_source(locked["kind"], source)

    revision = locked["revision"]
    base_mode = batch.get("base_mode", "strict")
    stale = check_base_version(batch.get("base_version"), revision, base_mode)
    if stale is not None:
        raise ChangeError(stale.kind, stale.message, [stale.as_dict()])

    cfg = await config_document.document_from_db(session, version=revision)
    resolve_batch = {name: batch[name] for name in _RESOLVE_FIELDS if name in batch}
    resolve_batch.setdefault("configuration_id", configuration_id)
    resolved_ops, resolve_report = _resolve_function()(cfg, resolve_batch)
    resolved_ops = list(resolved_ops)

    report: dict[str, Any] = dict(resolve_report)
    report.setdefault("ok", True)
    for name in ("skipped", "cascaded", "dangling", "affected", "effects", "advisories"):
        report[name] = list(report.get(name) or [])
    report["configuration_id"] = configuration_id
    report["version_before"] = revision
    report["effects"].extend(run_start_effects(cfg, resolved_ops))

    if batch.get("dry_run"):
        await session.rollback()
        report.update(version_after=revision, batch_id=None, persisted=False, dry_run=True)
        return report

    result = await journal.write_immediate(
        session,
        ops=resolved_ops,
        proposed=list(batch["ops"]),
        source=source,
        actor=batch.get("actor") or "system",
        configuration_id=configuration_id,
        channel=batch.get("channel") or "",
        note=batch.get("note") or "",
        group_id=batch.get("group_id"),
        expected_revision=revision,
    )
    report.update(
        version_after=result.revision,
        batch_id=result.entry_id,
        persisted=result.changed,
    )
    return report
