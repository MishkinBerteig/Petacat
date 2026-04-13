"""Tests for the Codelet DSL interpreter and registry."""

import os
import pytest
from server.engine.codelet_dsl.builtins import get_builtins
from server.engine.codelet_dsl.interpreter import (
    CodeletFizzle,
    CodeletInterpreter,
    CodeletRegistry,
    CompiledCodelet,
)
from server.engine.metadata import MetadataProvider
from server.engine.runner import EngineContext, EngineRunner


SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")


@pytest.fixture
def meta():
    return MetadataProvider.from_seed_data(SEED_DIR)


@pytest.fixture
def interpreter():
    return CodeletInterpreter(builtins=get_builtins())


def test_compile_empty():
    interp = CodeletInterpreter()
    compiled = interp.compile("", name="empty")
    assert compiled.is_empty


def test_compile_valid():
    interp = CodeletInterpreter()
    compiled = interp.compile("x = 1 + 1", name="simple")
    assert not compiled.is_empty
    assert compiled.name == "simple"


def test_compile_syntax_error():
    interp = CodeletInterpreter()
    with pytest.raises(ValueError, match="Syntax error"):
        interp.compile("def foo(", name="bad")


def test_execute_simple(meta):
    runner = EngineRunner(meta)
    runner.init_mcat("abc", "abd", "xyz", seed=42)
    interp = CodeletInterpreter(builtins=get_builtins())
    compiled = interp.compile("result = temperature.value", name="test")
    interp.execute(compiled, runner.ctx)


def test_execute_fizzle(meta):
    runner = EngineRunner(meta)
    runner.init_mcat("abc", "abd", "xyz", seed=42)
    interp = CodeletInterpreter(builtins=get_builtins())
    compiled = interp.compile("fizzle()", name="test-fizzle")
    # Should not raise — fizzle is caught internally
    interp.execute(compiled, runner.ctx)


def test_execute_with_builtins(meta):
    runner = EngineRunner(meta)
    runner.init_mcat("abc", "abd", "xyz", seed=42)
    interp = CodeletInterpreter(builtins=get_builtins())
    compiled = interp.compile(
        "obj = choose_object('intra')",
        name="test-builtin",
    )
    interp.execute(compiled, runner.ctx)


def test_registry_from_metadata(meta, interpreter):
    registry = CodeletRegistry.from_metadata(meta, interpreter)
    assert len(registry.names) == 27
    # All should be compiled (non-empty) now
    for name in registry.names:
        compiled = registry.get_compiled(name)
        assert not compiled.is_empty, f"{name} should have execute_body"


def test_registry_missing_codelet(meta, interpreter):
    registry = CodeletRegistry.from_metadata(meta, interpreter)
    compiled = registry.get_compiled("nonexistent-codelet")
    assert compiled.is_empty


def test_breaker_codelet_executes(meta):
    """The breaker codelet should execute without errors."""
    runner = EngineRunner(meta)
    runner.init_mcat("abc", "abd", "xyz", seed=42)
    interp = CodeletInterpreter(builtins=get_builtins())
    compiled = runner._registry.get_compiled("breaker")
    assert not compiled.is_empty
    # Execute it — may fizzle (normal) but should not error
    interp.execute(compiled, runner.ctx)


def test_bond_scout_codelet_executes(meta):
    """The bottom-up-bond-scout should execute without errors."""
    runner = EngineRunner(meta)
    runner.init_mcat("abc", "abd", "xyz", seed=42)
    interp = CodeletInterpreter(builtins=get_builtins())
    compiled = runner._registry.get_compiled("bottom-up-bond-scout")
    assert not compiled.is_empty
    interp.execute(compiled, runner.ctx)


def test_description_scout_codelet_executes(meta):
    """The bottom-up-description-scout should execute without errors."""
    runner = EngineRunner(meta)
    runner.init_mcat("abc", "abd", "xyz", seed=42)
    interp = CodeletInterpreter(builtins=get_builtins())
    compiled = runner._registry.get_compiled("bottom-up-description-scout")
    assert not compiled.is_empty
    interp.execute(compiled, runner.ctx)


def test_runner_executes_codelets(meta):
    """Runner should dispatch codelets through the interpreter."""
    runner = EngineRunner(meta)
    runner.init_mcat("abc", "abd", "xyz", seed=42)
    # Run 100 steps — all codelets should execute via the interpreter
    result = runner.run_mcat(max_steps=100)
    assert result.codelet_count == 100
