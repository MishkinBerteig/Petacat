"""Coderack pressure counters (v2.0, increment 4, stage D).

The Coderack counts, per run, three plain integers and nothing else changes: ``full_posts`` (a codelet posted while the
rack holds ``max_size``), ``overflowing_batches`` (a deferred batch that takes the rack past ``max_size``) and ``evicted``
(codelets removed to make room).  The engine never reads them; a turn's evidence reports them.  Reading them changes no
answer, codelet count or random draw.
"""

from __future__ import annotations

import os

import pytest

from server.engine.coderack import Codelet, Coderack
from server.engine.metadata import MetadataProvider
from server.engine.rng import RNG
from server.engine.runner import EngineRunner
from server.services import config_document as cd
from server.services import training_base as tb

pytestmark = pytest.mark.numeric_matrix

SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "seed_data")


@pytest.fixture(scope="module")
def meta() -> MetadataProvider:
    return MetadataProvider.from_standard_configuration(SEED_DIR)


def codelet(stamp: int = 0) -> Codelet:
    return Codelet("bottom-up-bond-scout", 35, time_stamp=stamp)


def filled(meta, size: int = 5) -> Coderack:
    rack = Coderack(meta)
    rack.max_size = size
    rack.rng = RNG(7)
    return rack


def counts(rack: Coderack) -> tuple[int, int, int]:
    return rack.full_posts, rack.overflowing_batches, rack.evicted


def test_a_new_rack_has_counted_nothing(meta):
    assert counts(Coderack(meta)) == (0, 0, 0)


def test_posts_below_the_size_are_not_full_posts(meta):
    rack = filled(meta)
    for i in range(5):
        rack.post(codelet(i), i)
    assert counts(rack) == (0, 0, 0) and rack.total_count == 5


def test_a_post_to_a_full_rack_is_a_full_post_and_evicts_one(meta):
    rack = filled(meta)
    for i in range(5):
        rack.post(codelet(i), i)
    rack.post(codelet(10), 10)
    assert counts(rack) == (1, 0, 1) and rack.total_count == 5
    rack.post(codelet(11), 11)
    assert counts(rack) == (2, 0, 2)


def test_a_deferred_batch_that_fits_is_not_overflowing(meta):
    rack = filled(meta)
    rack.post_deferred([codelet(1), codelet(2), codelet(3)], 1)
    assert counts(rack) == (0, 0, 0) and rack.total_count == 3
    rack.post_deferred([codelet(4), codelet(5)], 2)  # lands exactly on the size
    assert counts(rack) == (0, 0, 0) and rack.total_count == 5


def test_a_deferred_batch_past_the_size_is_one_overflowing_batch_and_evicts_the_surplus(meta):
    rack = filled(meta)
    for i in range(4):
        rack.post(codelet(i), i)
    rack.post_deferred([codelet(10), codelet(11), codelet(12)], 10)  # 4 + 3 - 5 = 2 evicted, one batch
    assert counts(rack) == (0, 1, 2) and rack.total_count == 5


def test_a_batch_as_large_as_the_rack_overflows_and_flushes(meta):
    rack = filled(meta)
    for i in range(3):
        rack.post(codelet(i), i)
    rack.post_deferred([codelet(20 + i) for i in range(5)], 20)
    assert rack.overflowing_batches == 1 and rack.total_count == 5
    assert rack.evicted == 3  # the flush (the Scheme's clear) evicts the 3 codelets the rack held, to make room


def test_remove_old_codelets_counts_what_it_removes(meta):
    rack = filled(meta, 50)
    for i in range(6):
        rack.post(codelet(i), i)
    removed = rack.remove_old_codelets(10, 4, rack.rng)
    assert len(removed) == 4 and rack.evicted == 4 and counts(rack) == (0, 0, 4)


def outcome(runner):
    ctx = runner.ctx
    answer = ctx.workspace.answer_string
    return (str(runner.status), answer.text if answer else None, ctx.codelet_count, ctx.rng.call_count,
            float(ctx.temperature.value))


@pytest.mark.parametrize("problem,config", [(("abc", "abd", "ijk"), "standard"), (("abc", "abd", "xy1"), "v2")])
def test_reading_the_counters_changes_no_answer_codelet_or_draw(meta, problem, config):
    provider = meta if config == "standard" else cd.provider(tb.resolve_base().document)
    plain = EngineRunner(provider)
    plain.init_mcat(*problem, None, seed=3)
    plain.run_mcat(max_steps=1200)
    watched = EngineRunner(provider)
    watched.init_mcat(*problem, None, seed=3)
    reads = []
    original = Coderack.post

    def post(self, *a, **k):  # read the counters at every post
        reads.append(counts(self))
        return original(self, *a, **k)

    Coderack.post = post
    try:
        watched.run_mcat(max_steps=1200)
    finally:
        Coderack.post = original
    assert reads
    assert outcome(plain) == outcome(watched)
    rack = watched.ctx.coderack
    assert counts(rack) == counts(plain.ctx.coderack)
    assert rack.evicted >= rack.full_posts  # every full post evicts at least one codelet
