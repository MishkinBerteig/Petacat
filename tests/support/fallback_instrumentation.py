"""Count the engine's silent fallbacks without editing the engine (EN0, instrumentation).

The plan (B10, gate G3) asks how often the corpus reaches each silent fallback before any
of them is narrowed: the three blanket ``except Exception`` blocks of ``justify.py`` and
every ``slipnet.nodes.get(name) is None`` style lookup that finds nothing.  Under the
Metacat Standard Configuration the expected count is zero.  This module observes both
from test code only:

* **Handled exceptions** are seen through ``sys.monitoring`` (``EXCEPTION_HANDLED``).  Each
  event is mapped to the ``except`` clause of ``server/engine/**`` source that caught it,
  found by parsing the file's AST once.  Every handler is counted; the report separates
  the *blanket* ones (``except Exception``, ``except BaseException``, bare ``except``)
  from the narrow ones.
* **Missing nodes** are seen by giving each Slipnet a counting ``dict`` for ``nodes``: a
  ``get`` (or ``[]``) of a name the Slipnet does not hold is recorded with the file and
  line of the caller.  The dict is a subclass that behaves exactly as a ``dict`` does, and
  it is installed by wrapping ``Slipnet.from_metadata`` for the duration of the
  observation, so the engine source is untouched and a run draws exactly what it drew.

``Observation`` is a context manager; read ``.report()`` afterwards.
"""

from __future__ import annotations

import ast
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
ENGINE_DIR = REPO_ROOT / "server" / "engine"

_BLANKET = {"Exception", "BaseException"}


def _handler_text(handler: ast.ExceptHandler) -> str:
    return "bare except" if handler.type is None else "except " + ast.unparse(handler.type)


def _is_blanket(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return True
    names = [handler.type] if not isinstance(handler.type, ast.Tuple) else list(handler.type.elts)
    return any(isinstance(n, ast.Name) and n.id in _BLANKET for n in names)


class _CountingNodes(dict):
    """A ``dict`` that records the lookups that find nothing."""

    def __init__(self, data: Any, sink: "Observation") -> None:
        super().__init__(data)
        self._sink = sink

    def get(self, key: Any, default: Any = None) -> Any:  # type: ignore[override]
        self._sink.node_gets += 1
        if key not in self:
            self._sink.record_missing("get", key, sys._getframe(1))
        return super().get(key, default)

    def __getitem__(self, key: Any) -> Any:
        self._sink.node_gets += 1
        if key not in self:
            self._sink.record_missing("[]", key, sys._getframe(1))
        return super().__getitem__(key)


class Observation:
    """Observe the engine while it runs; see the module docstring."""

    TOOL_NAME = "petacat-fallback-observation"

    def __init__(self) -> None:
        self.handled: Counter[tuple[str, int]] = Counter()
        self.handler_info: dict[tuple[str, int], tuple[str, bool]] = {}
        self.missing: Counter[tuple[str, int, str, str]] = Counter()
        self.node_gets = 0
        self._handlers_by_file: dict[str, list[tuple[int, int, ast.ExceptHandler]]] = {}
        self._tool_id: int | None = None
        self._resolved: dict[str, str] = {}
        self._original_from_metadata: Any = None

    # -- handlers -------------------------------------------------------------------

    def _handlers_of(self, filename: str) -> list[tuple[int, int, ast.ExceptHandler]]:
        if filename not in self._handlers_by_file:
            handlers: list[tuple[int, int, ast.ExceptHandler]] = []
            try:
                tree = ast.parse(Path(filename).read_text())
            except (OSError, SyntaxError):
                tree = None
            if tree is not None:
                for node in ast.walk(tree):
                    if isinstance(node, ast.ExceptHandler):
                        handlers.append((node.lineno, node.end_lineno or node.lineno, node))
            self._handlers_by_file[filename] = handlers
        return self._handlers_by_file[filename]

    def _on_handled(self, code: Any, offset: int, exc: BaseException) -> None:
        filename = self._resolved.get(code.co_filename)
        if filename is None:
            # a module imported through a path like ``tests/../server/engine`` has a
            # co_filename that is not normalised
            filename = self._resolved[code.co_filename] = os.path.normpath(os.path.abspath(code.co_filename))
        if not filename.startswith(str(ENGINE_DIR)):
            return
        # The handler's first instruction carries no line; the next one that does is on
        # the ``except`` line (or, for a bare ``except``, in its body), inside the clause.
        line = next((ln for start, end, ln in code.co_lines()
                     if ln is not None and end > offset), None)
        if line is None:
            return
        best = None
        for start, end, node in self._handlers_of(filename):
            if start <= line <= end and (best is None or start >= best[0]):
                best = (start, node)
        if best is None:
            return
        rel = str(Path(filename).relative_to(REPO_ROOT))
        key = (rel, best[0])
        self.handled[key] += 1
        self.handler_info[key] = (_handler_text(best[1]), _is_blanket(best[1]))

    # -- missing nodes --------------------------------------------------------------

    def record_missing(self, how: str, name: Any, frame: Any) -> None:
        try:
            rel = str(Path(os.path.normpath(os.path.abspath(frame.f_code.co_filename))).relative_to(REPO_ROOT))
        except ValueError:
            rel = frame.f_code.co_filename
        self.missing[(rel, frame.f_lineno, how, str(name))] += 1

    # -- context manager ------------------------------------------------------------

    def __enter__(self) -> "Observation":
        from server.engine.slipnet import Slipnet

        mon = sys.monitoring
        for tool in range(mon.PROFILER_ID, 6):
            if mon.get_tool(tool) is None:
                self._tool_id = tool
                break
        if self._tool_id is None:
            raise RuntimeError("no free sys.monitoring tool id")
        mon.use_tool_id(self._tool_id, self.TOOL_NAME)
        mon.register_callback(self._tool_id, mon.events.EXCEPTION_HANDLED, self._on_handled)
        mon.set_events(self._tool_id, mon.events.EXCEPTION_HANDLED)

        observation = self
        original = Slipnet.from_metadata.__func__  # type: ignore[attr-defined]
        self._original_from_metadata = Slipnet.__dict__["from_metadata"]

        def counting_from_metadata(cls: Any, meta: Any) -> Any:
            slipnet = original(cls, meta)
            slipnet.nodes = _CountingNodes(slipnet.nodes, observation)
            return slipnet

        Slipnet.from_metadata = classmethod(counting_from_metadata)  # type: ignore[method-assign]
        return self

    def __exit__(self, *exc: Any) -> None:
        from server.engine.slipnet import Slipnet

        mon = sys.monitoring
        if self._tool_id is not None:
            mon.set_events(self._tool_id, 0)
            mon.register_callback(self._tool_id, mon.events.EXCEPTION_HANDLED, None)
            mon.free_tool_id(self._tool_id)
            self._tool_id = None
        Slipnet.from_metadata = self._original_from_metadata  # type: ignore[method-assign]

    # -- report ---------------------------------------------------------------------

    def report(self) -> dict[str, Any]:
        handlers = [
            {"site": f"{path}:{line}", "clause": self.handler_info[(path, line)][0],
             "blanket": self.handler_info[(path, line)][1], "hits": n}
            for (path, line), n in sorted(self.handled.items())
        ]
        missing = [
            {"site": f"{path}:{line}", "how": how, "name": name, "hits": n}
            for (path, line, how, name), n in sorted(self.missing.items())
        ]
        return {"handled_exceptions": handlers, "missing_node_lookups": missing,
                "node_lookups": self.node_gets}


def blanket_sites(path: Path) -> list[tuple[int, str]]:
    """The ``(line, clause)`` of every blanket handler in ``path``."""
    tree = ast.parse(path.read_text())
    return sorted((n.lineno, _handler_text(n)) for n in ast.walk(tree)
                  if isinstance(n, ast.ExceptHandler) and _is_blanket(n))
