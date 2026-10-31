"""Reduced configurations for the any-configuration suite (gate G9, fixtures only).

From the Metacat Standard Configuration (``seed_data/*.json``) this module produces the
configurations the plan's G9 runs the engine on from EN3 on:

* ``role_unbound(role)``       the node a role is bound to, removed with its cascade (the
                               role tables arrive in EN2; until then "a role unbound"
                               is "the node it names today removed", from
                               ``role_table``).  For an ordered role, ``ordinal`` picks
                               the element.  A codelet role removes the codelet type.
* ``node_removed(name)``       one node removed with its cascade.
* ``letter_removed(letter)``   one letter's node removed (``plato-<letter>``).
* ``alphabet(letters)``        every letter outside ``letters`` removed; ``a_d_w_z()`` is
                               the plan's a-d/w-z alphabet.
* ``ladder_with_gap(missing)`` a number node removed from the ladder of one to five
                               (default ``plato-three``).

Each returns a ``Reduced`` (``name``, the ``documents``, the cascade ``report``).  Nothing
here runs the engine; G9 will.  ``provider(reduced)`` builds the ``MetadataProvider`` for
it through ``from_standard_configuration`` on a temporary directory, which is the only loader that
exists for files, so a reduced configuration is read by the same code as the real one.

``all_single_role_removals`` and ``all_node_removals`` enumerate the families G9 loops
over.  The cascade is ``configuration_cascade`` (a throwaway until C14's ``resolve``).
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from tests.support import configuration_cascade as cascade
from tests.support.configuration_cascade import Documents, Report
from tests.support.role_table import (
    CODELET_ROLES, LETTER_NODES, NUMBER_NODES, ORDERED_ROLES, SINGLE_ROLES,
)


@dataclass
class Reduced:
    name: str
    documents: Documents
    report: Report

    @property
    def removed_nodes(self) -> list[str]:
        return self.report.removed_nodes

    @property
    def removed_codelet_types(self) -> list[str]:
        return self.report.removed_codelet_types


def _apply(name: str, nodes: list[str] = (), codelet_types: list[str] = ()) -> Reduced:  # type: ignore[assignment]
    docs = cascade.load_documents()
    report = Report()
    for node in nodes:
        report.merge(cascade.remove_node(docs, node))
    for ctype in codelet_types:
        report.merge(cascade.remove_codelet_type(docs, ctype))
    return Reduced(name, docs, report)


def standard() -> Reduced:
    """The Metacat Standard Configuration itself, unreduced."""
    return Reduced("standard", cascade.load_documents(), Report())


def node_removed(name: str) -> Reduced:
    return _apply(f"node removed: {name}", nodes=[name])


def role_unbound(role: str, ordinal: int = 0) -> Reduced:
    if role in SINGLE_ROLES:
        return _apply(f"role unbound: {role}", nodes=[SINGLE_ROLES[role]])
    if role in ORDERED_ROLES:
        return _apply(f"role unbound: {role}[{ordinal}]", nodes=[ORDERED_ROLES[role][ordinal]])
    if role in CODELET_ROLES:
        return _apply(f"role unbound: {role}", codelet_types=[CODELET_ROLES[role]])
    raise KeyError(role)


def letter_removed(letter: str) -> Reduced:
    if len(letter) != 1 or f"plato-{letter}" not in LETTER_NODES:
        raise KeyError(letter)
    return _apply(f"letter removed: {letter}", nodes=[f"plato-{letter}"])


def alphabet(letters: str) -> Reduced:
    keep = {f"plato-{c}" for c in letters}
    unknown = keep - set(LETTER_NODES)
    if unknown:
        raise KeyError(sorted(unknown))
    return _apply(f"alphabet: {letters}", nodes=[n for n in LETTER_NODES if n not in keep])


def a_d_w_z() -> Reduced:
    """The plan's example: an alphabet of a-d and w-z."""
    return alphabet("abcdwxyz")


def ladder_with_gap(missing: str = "plato-three") -> Reduced:
    if missing not in NUMBER_NODES:
        raise KeyError(missing)
    return _apply(f"ladder with a gap: {missing}", nodes=[missing])


def all_single_role_removals() -> Iterator[Reduced]:
    """Each role unbound in turn: 24 single-node roles, every element of the two ordered
    roles, the five codelet roles."""
    for role in SINGLE_ROLES:
        yield role_unbound(role)
    for role, names in ORDERED_ROLES.items():
        for i in range(len(names)):
            yield role_unbound(role, i)
    for role in CODELET_ROLES:
        yield role_unbound(role)


def all_node_removals() -> Iterator[Reduced]:
    """Each of the 59 nodes removed one at a time."""
    for name in cascade.node_names(cascade.load_documents()):
        yield node_removed(name)


def write(reduced: Reduced, directory: Path) -> Path:
    """Write the documents as a seed-file directory (what ``from_standard_configuration`` reads)."""
    directory.mkdir(parents=True, exist_ok=True)
    for fname, doc in reduced.documents.items():
        (directory / fname).write_text(json.dumps(doc, indent=1))
    return directory


def provider(reduced: Reduced) -> Any:
    """The ``MetadataProvider`` of a reduced configuration, loaded from files like any other."""
    from server.engine.metadata import MetadataProvider

    with tempfile.TemporaryDirectory(prefix="petacat-reduced-") as tmp:
        return MetadataProvider.from_standard_configuration(str(write(reduced, Path(tmp))))
