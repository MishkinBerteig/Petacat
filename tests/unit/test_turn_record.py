"""The window and the turn seed of a multi-turn run (``server/services/turn_record.py``): pure functions."""

from __future__ import annotations

import hashlib

from server.services import turn_record as tr


def test_turn_one_runs_with_the_run_seed_so_a_single_turn_problem_is_unchanged():
    for seed in (0, 1, 7, 2_147_483_647):
        assert tr.turn_seed(seed, 1) == seed


def test_a_later_turn_seed_is_a_fixed_function_of_the_seed_and_the_turn():
    # Pinned: the first eight bytes of SHA-256 over "petacat-turn:<seed>:<turn>", big-endian, low 63 bits.
    expect = int.from_bytes(hashlib.sha256(b"petacat-turn:5:2").digest()[:8], "big") & (2 ** 63 - 1)
    assert tr.turn_seed(5, 2) == expect
    assert tr.turn_seed(5, 2) == tr.turn_seed(5, 2)
    seen = {tr.turn_seed(seed, turn) for seed in range(1, 40) for turn in range(2, 40)}
    assert len(seen) == 39 * 38  # no two (seed, turn) share a stream
    assert all(0 <= s < 2 ** 63 for s in seen)  # fits a bigint


def test_the_window_joins_context_second_string_and_input_with_single_spaces():
    # one:two::1:? answered 2, then the input 3  =>  `one two 1:2::3:?`
    assert tr.next_window("one", "two", "1", "2", "3") == ("one two 1", "2", "3")
    # turn 3's context is turn 2's three positions joined, and so on
    context, second, input_text = tr.next_window("bad", "good", "less", "worse", "more")
    assert (context, second, input_text) == ("bad good less", "worse", "more")
    assert tr.next_window(context, second, input_text, "better", "even more") == (
        "bad good less worse more", "better", "even more")


def test_the_window_keeps_every_string_exactly():
    odd = ("  a\tb\n", "ψ́", "😀  ", "x ", " y")
    context, second, input_text = tr.next_window(odd[0], odd[1], odd[2], odd[3], odd[4])
    assert context == f"{odd[0]} {odd[1]} {odd[2]}"  # no trimming, no normalising, doubled spaces kept
    assert (second, input_text) == (odd[3], odd[4])
