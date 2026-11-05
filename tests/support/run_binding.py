"""Rebinding the current run's configuration or Themespace inside one test.

``tests/conftest.py`` binds a run (the Metacat Standard Configuration, a fresh identifier
allocator) around every test.  A test that needs structures to read another configuration, or
another Themespace, replaces that binding with ``rebind``; the fixture restores the previous
one when the test ends, so nothing leaks into the next test.
"""

from __future__ import annotations

from typing import Any

from server.engine.run_binding import _RUN, RunBinding, current


def rebind(meta: Any = None, themespace: Any = None) -> RunBinding:
    """Bind a new run binding for the rest of the test: *meta* (default: the current
    configuration) and *themespace* (default none)."""
    binding = RunBinding.for_meta(meta if meta is not None else current().meta, themespace)
    _RUN.set(binding)
    return binding
