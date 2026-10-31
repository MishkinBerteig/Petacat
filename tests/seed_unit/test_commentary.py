"""The emit helpers that render from ``seed_data/commentary_templates.json``.

The templates come from a provider holding the Metacat Standard Configuration (the
emit helpers have no fallback to the files), so what these assert is which template
each event picks and how it is filled.
"""

import os

import pytest

from server.engine.commentary import (
    CommentaryLog,
    emit_answer_discovered,
    emit_answer_justified,
    emit_answer_unjustified,
    emit_give_up,
)
from server.engine.metadata import ConfigurationRequired, MetadataProvider

T = MetadataProvider.from_standard_configuration(
    os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")
).commentary_templates


# ---- emit_answer_discovered ----


def test_answer_discovered_high_quality():
    log = CommentaryLog()
    emit_answer_discovered(log, "xyd", 90.0, "great", 50.0, 100, 0, T)
    eliza = log.render(eliza_mode=True)
    tech = log.render(eliza_mode=False)
    assert '"xyd"' in eliza
    assert "great" in eliza
    assert "90" in tech


def test_answer_discovered_low_quality():
    log = CommentaryLog()
    emit_answer_discovered(log, "xyd", 40.0, "really terrible", 80.0, 100, 0, T)
    eliza = log.render(eliza_mode=True)
    assert "really terrible" in eliza


def test_answer_discovered_also():
    """Second answer should include 'also'."""
    log = CommentaryLog()
    emit_answer_discovered(log, "xyd", 85.0, "good", 50.0, 200, 1, T)
    eliza = log.render(eliza_mode=True)
    assert "also" in eliza


# ---- emit_answer_justified ----


def test_answer_justified():
    log = CommentaryLog()
    emit_answer_justified(log, 85.0, "pretty good", 100, T)
    eliza = log.render(eliza_mode=True)
    tech = log.render(eliza_mode=False)
    assert "Aha" in eliza
    assert "pretty good" in eliza
    assert "justified" in tech.lower()


# ---- emit_answer_unjustified ----


def test_answer_unjustified():
    log = CommentaryLog()
    emit_answer_unjustified(log, "leftmost->rightmost", 100, T)
    eliza = log.render(eliza_mode=True)
    tech = log.render(eliza_mode=False)
    assert "stumped" in eliza
    assert "leftmost->rightmost" in eliza
    assert "terminated" in tech.lower()


# ---- emit_give_up ----


def test_give_up():
    log = CommentaryLog()
    emit_give_up(log, 500, T)
    eliza = log.render(eliza_mode=True)
    tech = log.render(eliza_mode=False)
    assert "punch" in eliza
    assert "terminated" in tech.lower()


def test_emitting_without_templates_raises_rather_than_reading_the_files():
    log = CommentaryLog()
    with pytest.raises(ConfigurationRequired):
        emit_give_up(log, 500)
    with pytest.raises(ConfigurationRequired):
        emit_answer_unjustified(log, "leftmost->rightmost", 100)
    assert log.count == 0
