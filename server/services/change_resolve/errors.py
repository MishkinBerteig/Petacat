"""The refusal type of the change API's pure core.

``resolve`` raises :class:`ChangeRefused` when it cannot apply a batch (the four classes of
3.4(a)).  C5 maps it to HTTP: ``exc.status`` is the status code of the first problem and
``exc.as_dict()`` the body.  A 409 ``busy`` is the funnel's, not this module's.
"""

from __future__ import annotations

from typing import Any

from server.services.configuration_input import (  # noqa: F401  (re-exported)
    DOES_NOT_COMPILE,
    KEY_EXISTS,
    MALFORMED,
    STALE,
    STATUS,
    UNKNOWN_REFERENCE,
    InputProblem,
)


class ChangeRefused(ValueError):
    """The batch cannot be applied; nothing is written.

    ``problems`` holds one or more :class:`InputProblem` (class, message, op index, field,
    table, key, and for code the language, line and column).  All problems of one refusal
    share a class except for a reference check, which can list several.
    """

    def __init__(self, problems: list[InputProblem]):
        self.problems = list(problems)
        first = self.problems[0] if self.problems else None
        super().__init__(first.message if first else "the batch was refused")

    @property
    def kind(self) -> str:
        """``malformed``, ``unknown_reference``, ``does_not_compile``, ``stale`` or ``key_exists``."""
        return self.problems[0].kind

    @property
    def status(self) -> int:
        """400 malformed, 422 unknown_reference / does_not_compile, 409 stale / key_exists."""
        return self.problems[0].status

    def as_dict(self) -> dict[str, Any]:
        first = self.problems[0].as_dict()
        return {**first, "problems": [p.as_dict() for p in self.problems]}
