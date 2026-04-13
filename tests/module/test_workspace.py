"""Module integration tests for Workspace."""

import os
import pytest
from server.engine.metadata import MetadataProvider
from server.engine.slipnet import Slipnet
from server.engine.workspace import Workspace, WorkspaceString
from server.engine.workspace_objects import Letter
from server.engine.rng import RNG


SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")


@pytest.fixture
def meta():
    return MetadataProvider.from_seed_data(SEED_DIR)


@pytest.fixture
def slipnet(meta):
    return Slipnet.from_metadata(meta)


def test_workspace_string_creation(slipnet):
    ws = WorkspaceString("abc", slipnet)
    assert ws.length == 3
    assert len(ws.objects) == 3
    assert isinstance(ws.objects[0], Letter)
    assert ws.objects[0].letter_category.name == "plato-a"
    assert ws.objects[2].letter_category.name == "plato-c"


def test_workspace_creation(slipnet):
    w = Workspace("abc", "abd", "xyz", None, slipnet)
    assert w.initial_string.text == "abc"
    assert w.modified_string.text == "abd"
    assert w.target_string.text == "xyz"
    assert w.answer_string is None


def test_workspace_with_answer(slipnet):
    w = Workspace("abc", "abd", "xyz", "wyz", slipnet)
    assert w.answer_string is not None
    assert w.answer_string.text == "wyz"


def test_all_objects(slipnet):
    w = Workspace("abc", "abd", "xyz", None, slipnet)
    objects = w.all_objects
    # 3 + 3 + 3 = 9 letters total
    assert len(objects) == 9


def test_choose_object(slipnet):
    w = Workspace("abc", "abd", "xyz", None, slipnet)
    rng = RNG(42)
    obj = w.choose_object("intra", rng)
    assert obj is not None
    assert isinstance(obj, Letter)


def test_average_unhappiness_initial(slipnet):
    w = Workspace("abc", "abd", "xyz", None, slipnet)
    # Initially all objects have 100 unhappiness, but importance is 0
    # so weighted average might be different
    w.update_all_object_values()
    unhappiness = w.get_average_unhappiness()
    assert 0 <= unhappiness <= 100


def test_update_object_values(slipnet):
    w = Workspace("abc", "abd", "xyz", None, slipnet)
    w.update_all_object_values()
    for obj in w.all_objects:
        assert 0 <= obj.relative_importance <= 100
