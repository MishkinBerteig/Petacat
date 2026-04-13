"""Codelet DSL Compiler — validates and compiles Python source at startup."""

from __future__ import annotations

from server.engine.codelet_dsl.interpreter import CodeletInterpreter, CompiledCodelet


def compile_all_codelets(
    codelet_specs: dict,
    interpreter: CodeletInterpreter,
) -> dict[str, CompiledCodelet]:
    """Compile all codelet execute_body sources.

    Returns a dict of name -> CompiledCodelet.
    Raises ValueError on syntax errors.
    """
    compiled = {}
    for name, spec in codelet_specs.items():
        body = getattr(spec, "execute_body", "")
        compiled[name] = interpreter.compile(body, name=name)
    return compiled
