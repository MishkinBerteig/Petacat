"""Unit tests for Verbose mode's building blocks (``server/engine/verbose.py``).

The narration of a whole run is checked against Metacat 1.2 in
``tests/lockstep/test_verbose.py``; these test the pieces on their own: how Scheme prints
a value, the bounded log, and the two rules the DSL wiring depends on -- the narration
builtins exist in a codelet's namespace only when Verbose mode is on, and ``verbose`` is
read from the context afresh for every codelet.
"""

from __future__ import annotations

from fractions import Fraction
from types import SimpleNamespace

import pytest

from server.engine import verbose as V
from server.engine.codelet_dsl.builtins import get_builtins
from server.engine.codelet_dsl.interpreter import VERBOSE_ONLY, CodeletInterpreter


# -- how Scheme prints a value -------------------------------------------------


@pytest.mark.parametrize(
    "value,text",
    [
        ("abc", "abc"),
        (7, "7"),
        (0.5, "0.5"),
        (100.0, "100.0"),
        (1e-05, "1e-5"),
        (True, "#t"),
        (False, "#f"),
        (None, "#f"),
        ([1, 2.5, "x"], "(1 2.5 x)"),
        ((0.9, 0.9), "(0.9 0.9)"),
        ([], "()"),
        (Fraction(1, 3), "1/3"),
        (Fraction(4, 2), "2"),
        (float("inf"), "+inf.0"),
    ],
)
def test_display_prints_as_scheme_does(value, text):
    assert V.display(value) == text


def test_exact_turns_an_integral_flonum_into_the_integer_metacat_holds():
    assert V.exact(100.0) == 100 and isinstance(V.exact(100.0), int)
    assert V.exact(33.5) == 33.5
    assert V.exact("x") == "x"
    assert V.exact(float("nan")) != V.exact(float("nan"))  # left alone


def test_round_to_100ths_is_an_inexact_number():
    assert V.round_to_100ths(0.285) in (0.28, 0.29)
    assert V.display(V.round_to_100ths(1)) == "1.0"
    assert V.display(V.round_to_100ths(0.9)) == "0.9"


# -- the log -------------------------------------------------------------------


class _Meta:
    commentary_templates = {"verbose_messages": {"greet": "Hello {} and {}", "plain": "Plain."}}


def _log(capacity=100):
    log = V.VerboseLog(capacity)
    log.bind(_Meta())
    return log


def test_say_fills_the_template_with_schemes_display():
    log = _log()
    log.say("greet", 0.5, [1, 2])
    log.say("plain")
    assert log.since(0)["lines"] == ["Hello 0.5 and (1 2)", "Plain."]


def test_an_unknown_key_still_says_something_rather_than_raising():
    log = _log()
    log.say("not-in-the-catalogue", 1, 2)
    assert log.since(0)["lines"] == ["[not-in-the-catalogue] 1 2"]


def test_emit_splits_on_newlines_and_drops_one_trailing_newline():
    log = _log()
    log.emit("a\nb\n")
    log.emit("\nc")
    assert log.since(0)["lines"] == ["a", "b", "", "c"]


def test_the_database_catalogue_overlays_the_seed_data_catalogue():
    from server.engine.metadata import verbose_messages

    merged = verbose_messages(_Meta())
    assert merged["greet"] == "Hello {} and {}"          # the provider's own
    assert merged["chose-object"] == "Chose object {}"   # a message the seed data adds


def test_the_buffer_is_bounded_and_says_how_much_fell_off():
    log = _log(capacity=5)
    for i in range(12):
        log.emit(f"line {i}")
    snap = log.since(0)
    assert snap["lines"] == [f"line {i}" for i in range(7, 12)]
    assert snap["first"] == 7 and snap["next"] == 12 and snap["total"] == 12
    assert snap["dropped"] == 7
    # Asking from where the last reply ended reads only what is new.
    log.emit("line 12")
    assert log.since(12)["lines"] == ["line 12"] and log.since(12)["dropped"] == 0


def test_clear_empties_the_buffer_but_numbering_goes_on():
    log = _log()
    log.emit("a")
    log.clear()
    log.emit("b")
    snap = log.since(0)
    assert snap["lines"] == ["b"] and snap["next"] == 2


def test_capture_holds_narration_back_until_it_is_replayed():
    log = _log()
    log.emit("before")
    held = log.capture(lambda: (log.emit("one"), log.emit("two")))
    log.emit("after")
    assert held == ["one", "two"]
    assert log.since(0)["lines"] == ["before", "after"]
    log.replay(held)
    assert log.since(0)["lines"] == ["before", "after", "one", "two"]


def test_every_codelet_opens_with_a_dashed_line_and_its_type():
    log = _log()
    log.banner("bottom-up-bond-scout")
    assert log.since(0)["lines"] == ["-" * 46, "In bottom-up-bond-scout codelet..."]


def test_a_structure_is_new_proposed_or_evaluated_until_it_is_built():
    proposed = SimpleNamespace(proposal_level="proposed")
    built = SimpleNamespace(proposal_level="built")
    assert V.level_suffix(proposed) == " (proposed)"
    assert V.level_suffix(proposed, "new") == " (new)"
    assert V.level_suffix(built) == ""


def test_a_structure_built_before_is_not_new_when_it_is_built_again():
    log = _log()
    bond = SimpleNamespace(id=5)
    assert log.fresh(bond) == "new"
    log.mark_built(bond)
    assert log.fresh(bond) == "built"


# -- the DSL wiring --------------------------------------------------------------


def test_the_narration_builtins_are_registered_and_only_for_verbose_mode():
    builtins = get_builtins()
    assert VERBOSE_ONLY <= set(builtins)
    assert {"say", "vprint", "ascii_name", "generic_name", "round_to_100ths"} <= VERBOSE_ONLY


def _ctx(verbose):
    return SimpleNamespace(
        workspace=None, slipnet=None, coderack=None, themespace=None, trace=None,
        memory=None, temperature=None, commentary=None, rng=None, meta=None,
        codelet_count=0, justify_mode=False, self_watching_enabled=True, verbose=verbose,
    )


def test_a_codelet_namespace_has_the_narration_builtins_only_when_verbose_is_on():
    interp = CodeletInterpreter(builtins=get_builtins())
    program = interp.compile("seen.append((verbose, 'say' in dir(), 'vprint' in dir()))\n"
                             "seen.append(('say' in globals(), 'ascii_name' in globals()))")
    seen = []
    import builtins as py_builtins

    py_builtins.seen = seen
    try:
        interp.execute(program, _ctx(False))
        interp.execute(program, _ctx(True))
    finally:
        del py_builtins.seen
    assert seen[1] == (False, False)        # off: no narration builtins, ``verbose`` false
    assert seen[3] == (True, True)          # on: both bound
    assert seen[0][0] is False and seen[2][0] is True
