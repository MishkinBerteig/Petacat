"""The change API's pure core (configuration plan 3.12; package C14a).

``resolve(cfg, batch) -> (resolved_ops, report)`` is deterministic and has no side effects.
It expands convenience ops, performs cascades, validates on a working copy and turns
relative ops into absolute values; ``schema(registry)`` is the data of
``GET /api/configurations/{id}/schema``.  See ``core.py`` for the details and
``errors.py`` for the refusal type.
"""

from __future__ import annotations

from server.services.change_resolve.core import resolve  # noqa: F401
from server.services.change_resolve.errors import ChangeRefused  # noqa: F401
from server.services.change_resolve.spec import schema  # noqa: F401
