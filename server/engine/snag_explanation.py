"""The sentence a snag is explained by.

Scheme: ``get-explanation`` of the snag event (``trace.ss:1097-1125``) and
``snag-object-phrase`` (``trace.ss:1258-1268``), built from the **failure-result** the
rule application reports (``answers.ss:1145-1150``)::

    (SWAP objects dimension)
    (CONFLICT object1 dimension1 object2 dimension2)
    (CHANGE object transform)

Metacat computes the sentence from that result when the snag happens and uses it three
times: in the commentary (``answers.ss:1166-1172``, capitalised), in the snag
description kept in Episodic Memory (``memory.ss:289-332``), and in the "avoids a snag
that would otherwise arise from the fact that ..." caveat of an answer explanation
(``answers.ss:302-307``).  So it is computed once, here, from the live objects, and the
resulting *string* is what is stored and quoted afterwards.

The English is in ``seed_data/commentary_templates.json`` under ``snag_explanation``
(Step 0), the same place as every other phrase the engine speaks; slipnode names come
from the nodes as ``get-lowercase-name`` gives them (``rule_english._lc``).

``capitalize_string`` is ``capitalize-string`` (``utilities.ss:330-336``): the first
character upper-cased, nothing else touched.
"""

from __future__ import annotations

from typing import Any

from server.engine.answer_comparison import _fill, resolve_templates
from server.engine.images import ImageFailure, is_platonic_relation
from server.engine.rule_english import _lc


def capitalize_string(text: str) -> str:
    """Scheme ``capitalize-string``: upper-case the first character, keep the rest."""
    if text == "":
        return ""
    return text[0].upper() + text[1:]


def _section(templates: dict[str, Any] | None) -> dict[str, str]:
    section = resolve_templates(templates).get("snag_explanation")
    return section if isinstance(section, dict) else {}


def _print_name(obj: Any) -> str:
    """Scheme ``(tell object 'print-name)`` for a letter, group or string."""
    from server.engine.workspace import WorkspaceString

    if isinstance(obj, WorkspaceString):
        return obj.text
    return "".join(_lc(letter.letter_category) for letter in obj.get_letters()) if hasattr(
        obj, "get_letters"
    ) else _lc(obj.letter_category)


def snag_object_phrase(obj: Any, templates: dict[str, Any] | None = None) -> str:
    """Scheme ``snag-object-phrase`` (``trace.ss:1258``)."""
    from server.engine.workspace import WorkspaceString
    from server.engine.workspace_objects import Letter

    section = _section(templates)
    if isinstance(obj, WorkspaceString):
        return _fill(section.get("object_string", ""), name=obj.text)
    if isinstance(obj, Letter):
        return _fill(section.get("object_letter", ""), name=_lc(obj.letter_category))
    return _fill(section.get("object_group", ""), letters=_print_name(obj))


def _punctuate(items: list[str], section: dict[str, str]) -> str:
    """Scheme ``punctuate`` (``rules.ss:1824``), with its conjunctions as templates."""
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return _fill(section.get("list_pair", ""), first=items[0], second=items[1])
    return "".join(f"{x}, " for x in items[:-1]) + _fill(
        section.get("list_last", ""), last=items[-1]
    )


def _string_of(obj: Any) -> Any:
    """Scheme ``(tell object 'get-string)``: a string is its own string."""
    from server.engine.workspace import WorkspaceString

    return obj if isinstance(obj, WorkspaceString) else obj.string


def failure_result_of(failure: ImageFailure | None) -> tuple | None:
    """The Scheme's ``<failure-result>`` (``answers.ss:1145-1150``) for a failure.

    ``("SWAP", objects, dimension)``, ``("CONFLICT", object1, dimension1, object2,
    dimension2)`` or ``("CHANGE", object, transform)``, as plain data -- which is what
    the snag event keeps (``get-failure-result``, ``trace.ss:1127``) and what a captured
    run state can hold.  ``None`` for a failure that names no object.
    """
    if failure is None or not failure.objects:
        return None
    objects = list(failure.objects)
    if failure.kind == ImageFailure.SWAP:
        return ("SWAP", objects, failure.dimension)
    if failure.kind == ImageFailure.CONFLICT:
        second = objects[1] if len(objects) > 1 else None
        return ("CONFLICT", objects[0], failure.dimension, second, failure.dimension2)
    return ("CHANGE", objects[0], failure.transform)


def explain_failure(
    failure: Any, templates: dict[str, Any] | None = None
) -> str | None:
    """The snag's explanation, or ``None`` when the failure does not carry enough.

    ``failure`` is a failure-result (see ``failure_result_of``) or the ``ImageFailure``
    it comes from.  ``None`` is the signal to fall back
    (``caveat_templates.snag_explanation``): a raise site in Petacat that has no Scheme
    counterpart -- an object with no image -- reports no dimension or transform, and
    inventing one would be the invented sentence this module replaces.
    """
    if isinstance(failure, ImageFailure):
        failure = failure_result_of(failure)
    if not failure:
        return None
    section = _section(templates)
    kind = failure[0]

    if kind == "SWAP":
        _, objects, dimension = failure
        if not objects or dimension is None:
            return None
        return _fill(
            section.get("swap", ""),
            dimension=_lc(dimension),
            objects=_punctuate([snag_object_phrase(o, templates) for o in objects], section),
            string=_print_name(_string_of(objects[0])),
        )

    if kind == "CONFLICT":
        _, object1, dimension1, object2, dimension2 = failure
        if None in (object1, object2, dimension1, dimension2):
            return None
        return _fill(
            section.get("conflict", ""),
            dimension1=_lc(dimension1),
            object1=snag_object_phrase(object1, templates),
            dimension2=_lc(dimension2),
            object2=snag_object_phrase(object2, templates),
            string=_print_name(_string_of(object1)),
        )

    _, obj, transform = failure
    if not transform or obj is None:
        return None
    string = _print_name(_string_of(obj))
    if getattr(transform[0], "name", "") == "plato-group-category":
        if len(transform) < 3 or transform[2] is None:
            return None
        return _fill(
            section.get("change_group_reversal", ""),
            facet=_lc(transform[2]),
            object=snag_object_phrase(obj, templates),
            string=string,
        )
    descriptor = transform[1]
    template = "descriptor_relation" if is_platonic_relation(descriptor) else "descriptor_literal"
    return _fill(
        section.get("change", ""),
        dimension=_lc(transform[0]),
        object=snag_object_phrase(obj, templates),
        descriptor=_fill(section.get(template, ""), name=_lc(descriptor)),
        string=string,
    )


def fallback_explanation(
    rule_english: str, target: str, templates: dict[str, Any] | None = None
) -> str:
    """The pre-Metacat sentence, kept only for snags with no recorded explanation.

    Used for rows written before the explanation was stored, and for the one failure
    Petacat can raise that Metacat's rule application cannot (no image for a
    reference object).  A rule's English is a list of lines, so run them on.
    """
    rule = "; ".join(line.strip() for line in rule_english.split("\n"))
    caveats = resolve_templates(templates).get("caveat_templates") or {}
    return _fill(caveats.get("snag_explanation", ""), rule=rule, target=target)


def snag_explanation_text(snag: Any, templates: dict[str, Any] | None = None) -> str:
    """Scheme ``(tell snag 'get-explanation)`` (``memory.ss:332``).

    The stored sentence; for a snag with none recorded, the fallback built from its
    rule and target string.
    """
    if snag.explanation:
        return snag.explanation
    target = snag.problem[2] if len(snag.problem) > 2 else ""
    return fallback_explanation(snag.description, target, templates)
