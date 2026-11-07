"""The problem-string check of Training Mode: any UTF-8 text, kept exactly.

**Training Mode only.**  A Training Mode Session takes any Unicode text as a problem string: any
script, emoji and combining sequences, spaces, tabs, line breaks, punctuation, any case, any length.  A
string is stored and returned exactly as given: no trimming, no case change and no Unicode
normalisation, so the NFC and NFD spellings of one letter are two different strings (duplicates are
exact string matches only).  Perceiving new kinds of input is what Training Mode is for.

Metacat Mode does not use this check for its problems.  Its three doors (``RunService.create_run``,
``POST /api/swarm`` and the Admin view's Demo Problems) read every problem through a port of Metacat's own
input parser (``server/services/input_parser.py``), whose rules are in the Metacat Standard
Configuration: uppercase is lowered, punctuation separates strings, and a digit inside a string or a
letter outside a to z is ``Invalid input!``.  ``check_string`` and ``check_deep`` are still used for
configuration and journal text in both modes, because they refuse only what the database cannot store.

This check refuses only what cannot be text in the database:

* a string containing U+0000, which PostgreSQL ``text`` and ``jsonb`` cannot store;
* a string that is not valid Unicode (a lone surrogate, such as JSON ``"\\ud800"``), which
  cannot be encoded as UTF-8.

Structure is separate: ``initial``, ``modified`` and ``target`` must be non-empty and ``answer`` absent
(discovery) or non-empty, because an empty string crashes or hangs the engine; the Training Mode
Session request model and ``training_mode_session_service`` pass ``require_nonempty=True`` for that.
"""

from __future__ import annotations

from typing import Any, Mapping


class ProblemTextError(ValueError):
    """A problem string that cannot be stored; the message names the field and the reason."""


def check_string(field: str, value: str) -> None:
    """Refuse a string the database cannot hold; accept every other string."""
    if "\x00" in value:
        raise ProblemTextError(
            f"{field} contains the character U+0000 (NUL), which the database cannot store "
            "as text; remove it"
        )
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ProblemTextError(
            f"{field} is not valid Unicode text (it contains a lone surrogate, which cannot "
            "be encoded as UTF-8); replace it with a real character"
        ) from None


def check_deep(field: str, value: Any) -> None:
    """Run :func:`check_string` over every string in *value*, keys included.

    *value* may be a string or any nesting of mappings and lists (a change batch's ops, a
    journal ``proposed`` document).  The name in the message is the path to the bad string,
    such as ``ops[2]['values']['glyph']``.  Non-strings are not looked at.
    """
    if isinstance(value, str):
        check_string(field, value)
    elif isinstance(value, Mapping):
        for key, item in value.items():
            if isinstance(key, str):
                check_string(f"a key of {field}" if field else "a key", key)
            check_deep(f"{field}[{key!r}]" if field else repr(key), item)
    elif isinstance(value, (list, tuple)):
        for i, item in enumerate(value):
            check_deep(f"{field}[{i}]", item)


def check_problem(
    initial: Any, modified: Any, target: Any, answer: Any = None, *, require_nonempty: bool = False,
) -> None:
    """Check one problem's four strings; raise ``ProblemTextError`` on the first bad one."""
    for field, value in (("initial", initial), ("modified", modified), ("target", target)):
        if not isinstance(value, str):
            raise ProblemTextError(f"{field} must be a string")
        if require_nonempty and value == "":
            raise ProblemTextError(f"{field} must not be empty")
        check_string(field, value)
    if answer is not None:
        if not isinstance(answer, str):
            raise ProblemTextError("answer must be a string or null")
        if require_nonempty and answer == "":
            raise ProblemTextError("answer must not be empty (use null for discovery)")
        check_string("answer", answer)


def check_problem_mapping(p: Mapping[str, Any], *, require_nonempty: bool = False) -> None:
    check_problem(p.get("initial"), p.get("modified"), p.get("target"), p.get("answer"),
                  require_nonempty=require_nonempty)
