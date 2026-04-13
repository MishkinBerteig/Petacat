"""Tests for WorkspaceObject and Letter."""

from server.engine.workspace_objects import Letter, WorkspaceObject
from server.engine.slipnet import SlipnetNode


def test_letter_creation():
    node = SlipnetNode("plato-a", "a", 10)
    letter = Letter(string=None, position=0, letter_category=node)
    assert letter.left_string_pos == 0
    assert letter.right_string_pos == 0
    assert letter.span == 1


def test_initial_unhappiness():
    node = SlipnetNode("plato-a", "a", 10)
    letter = Letter(string=None, position=0, letter_category=node)
    assert letter.intra_string_unhappiness == 100.0


def test_salience_update():
    node = SlipnetNode("plato-a", "a", 10)
    letter = Letter(string=None, position=0, letter_category=node)
    letter.relative_importance = 50
    letter.intra_string_unhappiness = 80
    letter.update_salience()
    # intra: 0.8*80 + 0.2*50 = 74
    assert letter.salience["intra"] == 74
