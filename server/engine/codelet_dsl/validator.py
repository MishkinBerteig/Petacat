"""Codelet DSL Validator — validates codelet programs at load time."""

from __future__ import annotations

from server.engine.codelet_dsl.interpreter import CompiledCodelet


class ValidationError(Exception):
    """Raised when a DSL program fails validation."""
    pass


def validate_codelet(compiled: CompiledCodelet) -> list[str]:
    """Validate a compiled codelet program.

    Returns a list of warnings (empty if valid).
    """
    warnings: list[str] = []
    if compiled.is_empty:
        warnings.append(f"Codelet '{compiled.name}' has empty execute_body")
    return warnings


def validate_all(compiled_map: dict[str, CompiledCodelet]) -> dict[str, list[str]]:
    """Validate all compiled codelets. Returns name -> warnings."""
    results = {}
    for name, compiled in compiled_map.items():
        warnings = validate_codelet(compiled)
        if warnings:
            results[name] = warnings
    return results
