"""The vocabulary payload the client compares through (server/services/vocabulary_payload.py)."""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace

from server.engine.roles import VocabularyBinding
from server.services.vocabulary_payload import run_vocabulary_payload, vocabulary_payload
from tests.support.standard_configuration import standard_meta


def _meta():
    return standard_meta()


def test_payload_holds_every_binding_and_every_link_type():
    meta = _meta()
    out = vocabulary_payload(meta)
    assert out["vocabulary"]["bridge_type.top"] == "top"
    assert out["vocabulary"]["event_type.answer_found"] == "answer_found"
    assert out["vocabulary"]["theme_type.top_bridge"] == "top_bridge"
    assert len(out["vocabulary"]) == len(meta.vocabulary_bindings)
    assert out["link_behaviours"]["lateral_sliplink"] == "slip"
    assert set(out["link_behaviours"]) == {s.name for s in meta.link_types}


def test_a_renamed_binding_is_published_under_its_role():
    meta = _meta()
    bindings = tuple(
        dataclasses.replace(b, name="x17") if b.role == "bridge_type.top" else b
        for b in meta.vocabulary_bindings
    )
    out = vocabulary_payload(dataclasses.replace(meta, vocabulary_bindings=bindings))
    assert out["vocabulary"]["bridge_type.top"] == "x17"
    assert out["vocabulary"]["bridge_type.bottom"] == "bottom"


def test_an_unbound_role_is_absent_from_the_payload():
    meta = _meta()
    bindings = tuple(b for b in meta.vocabulary_bindings if b.role != "bridge_type.top")
    out = vocabulary_payload(dataclasses.replace(meta, vocabulary_bindings=bindings))
    assert "bridge_type.top" not in out["vocabulary"]


def test_a_loaded_runner_answers_with_its_own_provider_else_the_store_current():
    own = _meta()
    renamed = dataclasses.replace(
        own,
        vocabulary_bindings=tuple(
            dataclasses.replace(b, name="x17") if b.role == "bridge_type.top" else b
            for b in own.vocabulary_bindings
        ),
    )
    runner = SimpleNamespace(ctx=SimpleNamespace(meta=renamed))
    svc = SimpleNamespace(get_runner=lambda rid: runner if rid == 1 else None, meta=own)
    assert run_vocabulary_payload(svc, 1)["vocabulary"]["bridge_type.top"] == "x17"
    assert run_vocabulary_payload(svc, 2)["vocabulary"]["bridge_type.top"] == "top"
