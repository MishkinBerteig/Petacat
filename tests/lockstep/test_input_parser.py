"""Metacat Mode's input parser equals Metacat's own, on every character and every line.

``tests/lockstep/data/parser_metacat.json.gz`` is what the patched Metacat's real ``tokenize-string``,
``char-noise?`` and ``valid-token-list?`` do (``tests/lockstep/metacat/record_parser.py`` records it;
the format is at the top of that script).  This compares ``server/services/input_parser.py``, run on
the rules of the Metacat Standard Configuration, with that recording:

* the lowering and the two character classes, on every Unicode scalar value;
* the tokens and the validity of the three lines ``abc abd x{c}z``, ``abc abd {c}`` and
  ``{c}bc abd xyz`` for every scalar value ``c``;
* about two hundred whole lines (seeds, answers, token counts, digit forms, non-ASCII digits, mixed
  case, punctuation, letters outside a to z).

Any difference is a defect in the port.  The recording is the parser's reference and is measured
against patched Metacat.  A lone surrogate cannot reach Metacat at all, so the port refuses it.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from server.services.input_parser import (
    InvalidInput, parse_line, rules_from, tokenize, valid_token_list,
)
from tests.support.standard_configuration import standard_meta

RECORDING = Path(__file__).resolve().parent / "data" / "parser_metacat.json.gz"
SURROGATES = range(0xD800, 0xE000)


@pytest.fixture(scope="module")
def recording() -> dict:
    return json.loads(gzip.open(RECORDING, "rt", encoding="utf-8").read())


@pytest.fixture(scope="module")
def rules():
    return rules_from(standard_meta())


def _in_ranges(ranges: list[list[int]], code: int, starts: list[int]) -> bool:
    from bisect import bisect_right

    i = bisect_right(starts, code) - 1
    return i >= 0 and code <= ranges[i][1]


def _scalars():
    for code in range(0x110000):
        if code not in SURROGATES:
            yield code


def _recorded_tokens(result: dict, char: str | None, lowered: str | None) -> list | None:
    """The recording's result as the port's tokens: ``None`` for ``'error``."""
    if result.get("error"):
        return None
    assert "tokens" in result, result
    out: list = []
    for token in result["tokens"]:
        if isinstance(token, str):
            out.append(token.replace("\u0001", lowered) if lowered is not None else token)
        elif isinstance(token, dict):
            assert set(token) == {"num"}, token
            out.append(token["num"])
        else:
            assert token is None
            out.append(None)
    return out


def test_the_recording_is_of_patched_metacat(recording):
    assert recording["format"] == "petacat-parser-recording-1"
    assert recording["revision"].endswith("+known-failure-fixes")


def test_lowering_and_character_classes_on_every_scalar_value(recording, rules):
    lowered = {}
    for first, last, delta in recording["downcase"]:
        for code in range(first, last + 1):
            lowered[code] = code + delta
    alpha, numeric, noise = (recording[k] for k in ("alphabetic", "numeric", "noise"))
    a_starts, n_starts, z_starts = ([r[0] for r in ranges] for ranges in (alpha, numeric, noise))
    wrong: list[str] = []
    for code in _scalars():
        char = chr(code)
        low = lowered.get(code, code)
        if ord(rules.lower(char)) != low:
            wrong.append(f"lower {code:#x}")
        # The recording states the class of the *lowered* form of each character; the parser asks
        # about the lowered character, so ask about that.
        low_char = rules.lower(char)
        if rules.is_alphabetic(low_char) != _in_ranges(alpha, code, a_starts):
            wrong.append(f"alphabetic {code:#x}")
        if rules.is_numeric(low_char) != _in_ranges(numeric, code, n_starts):
            wrong.append(f"numeric {code:#x}")
        if rules.is_noise(low_char) != _in_ranges(noise, code, z_starts):
            wrong.append(f"noise {code:#x}")
        if len(wrong) > 20:
            break
    assert not wrong, wrong


@pytest.mark.parametrize("stream", ["x_c_z", "abc_abd_c", "c_bc_abd_xyz"])
def test_the_three_lines_on_every_scalar_value(recording, rules, stream):
    template = {
        "x_c_z": "abc abd x{c}z", "abc_abd_c": "abc abd {c}", "c_bc_abd_xyz": "{c}bc abd xyz",
    }[stream]
    lowered = {}
    for first, last, delta in recording["downcase"]:
        for code in range(first, last + 1):
            lowered[code] = code + delta
    runs = recording["lines"][stream]
    covered = 0
    wrong: list[str] = []
    for first, last, result, valid in runs:
        for code in range(first, last + 1):
            covered += 1
            char = chr(code)
            low = chr(lowered.get(code, code)) if code >= 128 else None
            expected = _recorded_tokens(result, char, low)
            line = template.format(c=char)
            tokens = tokenize(rules, line)
            ok = tokens == expected and valid_token_list(rules, tokens) == valid
            if not ok:
                wrong.append(f"{code:#x} {line!r}: {tokens!r} {valid_token_list(rules, tokens)} vs {expected!r} {valid}")
                if len(wrong) > 10:
                    break
        if len(wrong) > 10:
            break
    assert not wrong, wrong
    assert covered == 0x110000 - len(SURROGATES)


def test_whole_lines(recording, rules):
    wrong: list[str] = []
    lines = recording["whole_lines"]
    assert len(lines) >= 190
    for entry in lines:
        line = entry["line"]
        expected = _recorded_tokens(entry["result"], None, None)
        tokens = tokenize(rules, line)
        valid = valid_token_list(rules, tokens)
        if tokens != expected or valid != entry["valid"]:
            wrong.append(f"{line!r}: {tokens!r} {valid} vs {expected!r} {entry['valid']}")
    assert not wrong, wrong


def test_a_lone_surrogate_is_invalid(rules):
    assert tokenize(rules, "abc abd x\ud800z") is None
    with pytest.raises(InvalidInput):
        parse_line(rules, "abc abd x\ud800z")
