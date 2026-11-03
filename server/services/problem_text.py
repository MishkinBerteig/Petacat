"""The one check every problem string passes: initial, modified, target and answer.

Any Unicode text is a valid problem string, in Metacat Mode and in Training Mode alike:
any script, emoji and combining sequences, spaces, tabs, line breaks, punctuation, any
case, any length.  A string is stored and returned exactly as given: no trimming, no case
change and no Unicode normalisation, so the NFC and NFD spellings of one letter are two
different strings (duplicates are exact string matches only).

This check refuses only what cannot be text in the database:

* a string containing U+0000, which PostgreSQL ``text`` and ``jsonb`` cannot store;
* a string that is not valid Unicode (a lone surrogate, such as JSON ``"\\ud800"``), which
  cannot be encoded as UTF-8.

Structure is separate and the same in both modes: ``initial``, ``modified`` and ``target`` must be
non-empty and ``answer`` absent (discovery) or non-empty, because an empty string crashes or hangs the
engine; every request model and ``RunService.create_run`` pass ``require_nonempty=True`` for that.
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
