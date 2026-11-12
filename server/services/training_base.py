"""The Training Mode Base Configuration, v2.0 ("the v2.0 Base"): a delta over the Standard.

The Base is the folder ``training_base/v2.0/`` at the repository root: ``delta.json`` (an ordered
change-API batch), ``codelets/*.py`` (bodies as real files) and a README.  It is **not** a copy of
anything.  Each time it is needed it is resolved over the current Metacat Standard Configuration
(``configuration_admin.reference_document()``), so it cannot drift from the Standard, and a
Standard change that breaks it fails loudly (:class:`BaseOutOfDate`).

How an op takes its text from a file: any string value inside an op may be ``{"$file": "<path
under the version folder>"}``; it is replaced by the file's text.  A ``set_codelet_body`` op that
overrides a Standard body carries ``"standard_sha256"``, the sha256 of the Standard body it was
written against; resolution refuses when the Standard body no longer has that hash.  The key is
removed before the batch reaches the change API.

Only Training Mode reaches this module (session creation, and the Admin view's and the CLI's
comparison against the Base).  Nothing on Metacat Mode's run path imports it
(``tests/architecture/test_training_base_stays_out_of_metacat_mode.py``).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from server.services import config_document as cd

#: The ``configuration_base`` value of the v2.0 Base.
BASE_V2 = "training-v2"
BASE_NAMES = (BASE_V2,)
BASE_TITLE = "Training Mode Base Configuration, v2.0"
#: Where each Base lives, relative to :data:`BASES_DIR`.
_FOLDERS = {BASE_V2: "v2.0"}
BASES_DIR = Path(__file__).resolve().parents[2] / "training_base"


class BaseOutOfDate(Exception):
    """The Base cannot be resolved over the current Metacat Standard Configuration."""


@dataclass(frozen=True)
class ResolvedBase:
    name: str
    #: The ops as asked (file text in place), what the journal records as ``proposed``.
    proposed: list
    #: The delta's ops as resolved against the Standard, to be journaled as the creation batch.
    resolved: list
    #: The Standard with the delta applied: the Base as a document.
    document: cd.ConfigDocument
    standard_hash: str
    #: sha256 of the canonical JSON of ``proposed`` (so a body edit changes it).
    delta_hash: str

    @property
    def note(self) -> str:
        return (f"{BASE_TITLE}: delta {self.delta_hash} over the Metacat Standard Configuration "
                f"{self.standard_hash}")


def _expand(value: Any, folder: Path) -> Any:
    if isinstance(value, dict):
        if set(value) == {"$file"}:
            path = (folder / value["$file"]).resolve()
            if folder.resolve() not in path.parents:
                raise BaseOutOfDate(f"{value['$file']!r} is outside {folder}")
            try:
                return path.read_text(encoding="utf-8")
            except OSError as exc:
                raise BaseOutOfDate(f"cannot read {value['$file']!r}: {exc}") from exc
        return {k: _expand(v, folder) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v, folder) for v in value]
    return value


def folder_of(name: str) -> Path:
    if name not in _FOLDERS:
        raise BaseOutOfDate(f"{name!r} is not a Training Mode Base; known: {list(_FOLDERS)}")
    return BASES_DIR / _FOLDERS[name]


def load_delta(name: str = BASE_V2) -> list[dict]:
    """The delta's ops with every ``$file`` replaced by its text (``standard_sha256`` kept)."""
    folder = folder_of(name)
    try:
        data = json.loads((folder / "delta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BaseOutOfDate(f"cannot read {folder / 'delta.json'}: {exc}") from exc
    return _expand(data["ops"], folder)


def resolve_base(name: str = BASE_V2, standard: cd.ConfigDocument | None = None) -> ResolvedBase:
    """Resolve the Base over the Metacat Standard Configuration (read now)."""
    from server.services import configuration_writer as writer
    from server.services.configuration_admin import reference_document

    standard = standard if standard is not None else reference_document()
    ops = load_delta(name)
    standard_bodies = standard.tables["codelet_type_defs"]
    to_resolve = []
    for op in ops:
        op = dict(op)
        expected = op.pop("standard_sha256", None)
        if expected is not None:
            row = standard_bodies.get((op["name"],))
            have = hashlib.sha256((row or {}).get("execute_body", "").encode("utf-8")).hexdigest()
            if row is None or have != expected:
                raise BaseOutOfDate(
                    f"the {BASE_TITLE} overrides the body of codelet {op['name']!r}, written against "
                    f"Standard body sha256 {expected}; the Metacat Standard Configuration's is now "
                    f"{have if row else 'absent'}. Bring training_base/{_FOLDERS[name]}/codelets/"
                    f"{op['name']}.py up to date with the Standard body, then set standard_sha256 in delta.json.")
        to_resolve.append(op)
    batch = {"configuration_id": 0, "source": "creation", "actor": "system", "ops": to_resolve}
    try:
        writer.check_envelope(batch)
        resolved, _report = writer._resolve_function()(standard, batch)
    except Exception as exc:  # noqa: BLE001 - say which Base and why
        translated = writer._translate(exc)
        why = translated or exc
        raise BaseOutOfDate(
            f"the {BASE_TITLE} no longer resolves over the Metacat Standard Configuration: {why}") from exc
    resolved = list(resolved)
    return ResolvedBase(
        name=name,
        proposed=to_resolve,
        resolved=resolved,
        document=cd.apply_resolved(standard, resolved),
        standard_hash=cd.config_hash(standard),
        delta_hash=hashlib.sha256(
            json.dumps(ops, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
    )
