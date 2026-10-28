"""The trace context: which unit of work a decision belongs to (spec §3).

The engine's seam (``TraceSeam`` in ``server/engine/rng.py``) calls ``enter`` when a
unit starts and ``restore`` when an update cycle that ran inside a codelet is over;
``about`` is set around the walks and posting coins the two engines visit in different
orders.  ``about`` holds the object itself and is named only when a record is written.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class TraceContext:
    c: int = 1
    ctx: str = "init"
    who: str = "init-mcat"
    u: int | None = None
    n: int = 0
    about: Any = None

    def enter(self, c: int, ctx: str, who: str, u: int | None = None) -> tuple:
        """Start a unit; returns the previous one as a token for ``restore``."""
        token = self.token()
        self.c, self.ctx, self.who = c, ctx, who
        self.u = u if ctx == "update" else None
        self.n = 0
        self.about = None
        return token

    def token(self) -> tuple:
        return (self.c, self.ctx, self.who, self.u, self.n, self.about)

    def restore(self, token: tuple | None) -> None:
        if token is not None:
            self.c, self.ctx, self.who, self.u, self.n, self.about = token

    def set_about(self, about: Any) -> Any:
        previous, self.about = self.about, about
        return previous

    def unit_key(self) -> tuple:
        """The key decisions are grouped by (spec §7.2): update units are (u, who)."""
        if self.ctx == "update":
            return ("update", self.u, self.who)
        return (self.c, self.ctx, self.who)

    def next_n(self) -> int:
        n = self.n
        self.n += 1
        return n


class ReplayStop(BaseException):
    """Raised by the replay RNG to stop a run at a fatal failure (spec §7.4).

    A ``BaseException`` so no ``except Exception`` inside the engine can swallow it.
    """

    def __init__(self, fatal_class: str, detail: str) -> None:
        super().__init__(f"{fatal_class}: {detail}")
        self.fatal_class = fatal_class
        self.detail = detail
