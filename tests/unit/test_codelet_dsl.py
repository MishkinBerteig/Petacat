"""Compiling a codelet body: what the interpreter accepts and what it refuses."""

import pytest
from server.engine.codelet_dsl.interpreter import CodeletInterpreter


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
