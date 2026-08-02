"""The codelet registry built from the codelet types in ``seed_data/``."""

import os
import pytest
from server.engine.codelet_dsl.builtins import get_builtins
from server.engine.codelet_dsl.interpreter import CodeletInterpreter, CodeletRegistry
from server.engine.metadata import MetadataProvider


SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")


@pytest.fixture
def meta():
    return MetadataProvider.from_seed_data(SEED_DIR)


@pytest.fixture
def interpreter():
    return CodeletInterpreter(builtins=get_builtins())


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
