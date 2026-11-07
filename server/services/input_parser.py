"""Metacat's input parser, ported for Metacat Mode (and only for Metacat Mode).

Metacat reads a problem from one line the person types into the control panel:
``abc abd xyz``, optionally followed by an answer and a seed.  That reading is part of
Metacat's perception (``THE-THREE-SYSTEMS.md``), so Metacat Mode does it the same way.  This
module is a port of ``tokenize-string`` and ``char-noise?`` (``gui.ss:95-139``),
``valid-token-list?``, ``valid-number?`` and ``symbol-or-valid-number?``
(``syntactic-sugar.ss:51``, as patched by ``0003-non-english-letter-invalid-input.patch``) and of
how tokens become a problem (``update-current-problem``, ``gui.ss:742-752``).

What it does, by kind of character (the characters are lowered first):

* a letter starts or continues a string, and a string may hold only letters;
* a character that is neither a letter nor a digit (punctuation, a space, emoji, a combining
  mark) ends the string before it, so ``abc abd x-z`` is the tokens ``abc abd x z``;
* a digit starts or continues a number, and a number may hold only digits.  A digit inside a
  string, or a letter inside a number, makes the whole line invalid;
* three strings may be followed by one more string (the answer), or by a number (the seed), or by
  both; any other count of tokens is invalid;
* a string may hold only letters the Slipnet has a node for (the patch), so ``é`` and ``日本``
  are invalid and not a crash;
* a seed is a whole number from 1 to the largest seed.

**Nothing that decides any of this is in this file.**  The control flow is here.  Which characters
are letters or digits, how a character is lowered, which letters are readable, and the largest seed
are rows of the Metacat Standard Configuration (``input_character_ranges``,
``input_lowering_ranges``, the Slipnet's glyph nodes and the ``largest_seed`` engine parameter),
so that a scenario changes them without changing code and a Python upgrade cannot change what
Metacat Mode perceives.  ``scripts/generate_input_parser_seed.py`` writes the two tables from
Metacat's own recording (``tests/lockstep/data/parser_metacat.json.gz``).

**Where it sits.**  At Metacat Mode's doors only: ``RunService.create_run``, ``POST /api/swarm``
and Admin's demo problems.  A Training Mode Session never goes through it: its problems are any
UTF-8 text, kept exactly as given (``problem_text.py``), and a session never reads this
configuration.

**The fields.**  Petacat has separate fields where Metacat has one line.  The fields are read
left to right as one line, ``initial modified target [answer] [seed]``, so the same text gives the
same tokens as Metacat's: ``x-z`` in the Target field is the tokens ``x z``, which is target
``x`` with the answer ``z``.
"""

from __future__ import annotations

import secrets
from bisect import bisect_right
from dataclasses import dataclass
from typing import Any

#: The message for every input the parser cannot read.  Metacat's own text (``gui.ss:150``).
INVALID_INPUT = "Invalid input!"

#: The kinds of character a row of ``input_character_ranges`` names.  Closed: the parser's control
#: flow asks exactly these two questions (``char-alphabetic?`` and ``char-numeric?``).
KIND_ALPHABETIC = "alphabetic"
KIND_NUMERIC = "numeric"
CHARACTER_KINDS = (KIND_ALPHABETIC, KIND_NUMERIC)

#: The Unicode scalar values, and the surrogate block that holds none.
_MAX_SCALAR = 0x10FFFF
_SURROGATES = range(0xD800, 0xE000)


class InvalidInput(ValueError):
    """The input is not a problem Metacat's parser accepts; ``str(exc)`` is ``Invalid input!``."""

    def __init__(self) -> None:
        super().__init__(INVALID_INPUT)


class ParserConfigurationError(ValueError):
    """The configuration lacks something the parser needs; the message says what.

    The parser has no fallback: a scenario that removes the largest seed, every character
    range or every glyph node stops the request with this error instead of silently reading
    differently.
    """


@dataclass(frozen=True)
class ParserRules:
    """The parser's rules as read from one configuration, ready to ask about a character."""

    #: ``(first, last, step, delta)`` sorted by ``first``: the characters ``first``,
    #: ``first + step``, ... up to ``last`` lower to the character ``delta`` further on.
    lowering: tuple[tuple[int, int, int, int], ...]
    #: Per kind, the sorted ``(first, last)`` ranges of the characters of that kind.
    ranges: dict[str, tuple[tuple[int, int], ...]]
    #: The letters a string may be made of: the Slipnet's glyph nodes.
    readable: frozenset[str]
    largest_seed: int

    # -- the questions the parser asks of one character ---------------------------------------

    def lower(self, char: str) -> str:
        """``char-downcase``."""
        code = ord(char)
        starts = self._lowering_starts
        i = bisect_right(starts, code) - 1
        if i >= 0:
            first, last, step, delta = self.lowering[i]
            if code <= last and (code - first) % step == 0:
                return chr(code + delta)
        return char

    def is_kind(self, kind: str, char: str) -> bool:
        code = ord(char)
        starts = self._range_starts[kind]
        i = bisect_right(starts, code) - 1
        return i >= 0 and code <= self.ranges[kind][i][1]

    def is_alphabetic(self, char: str) -> bool:
        return self.is_kind(KIND_ALPHABETIC, char)

    def is_numeric(self, char: str) -> bool:
        return self.is_kind(KIND_NUMERIC, char)

    def is_noise(self, char: str) -> bool:
        """``char-noise?``: neither alphabetic nor numeric."""
        return not self.is_alphabetic(char) and not self.is_numeric(char)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_lowering_starts", [row[0] for row in self.lowering])
        object.__setattr__(
            self, "_range_starts", {k: [r[0] for r in v] for k, v in self.ranges.items()}
        )

    def valid_number(self, token: object) -> bool:
        """``valid-number?``: a whole number from 1 to the largest seed."""
        return (
            isinstance(token, int) and not isinstance(token, bool) and 0 < token <= self.largest_seed
        )

    def valid_letter_symbol(self, token: object) -> bool:
        """The patched ``valid-letter-symbol?``: a string made only of readable letters."""
        return isinstance(token, str) and all(c in self.readable for c in token)


def rules_from(meta: Any) -> ParserRules:
    """The parser's rules from a configuration (a ``MetadataProvider``).

    The readable letters are the Slipnet's glyph nodes, the same definition as
    ``Alphabet.build`` (``slipnet.py``): a node with a glyph is a letter.  Raises
    :class:`ParserConfigurationError` when the configuration lacks a part of the parser.
    """
    largest = meta.get_param("largest_seed")
    if not isinstance(largest, int) or isinstance(largest, bool) or largest < 1:
        raise ParserConfigurationError(
            "the configuration has no valid 'largest_seed' engine parameter, so Metacat Mode "
            "cannot read a seed"
        )
    ranges: dict[str, list[tuple[int, int]]] = {k: [] for k in CHARACTER_KINDS}
    for kind, first, last in meta.input_character_ranges:
        if kind not in ranges:
            raise ParserConfigurationError(
                f"input_character_ranges row {first:#x}-{last:#x} has the kind "
                f"{kind!r}; the kinds are {', '.join(CHARACTER_KINDS)}"
            )
        ranges[kind].append((first, last))
    if not ranges[KIND_ALPHABETIC]:
        raise ParserConfigurationError(
            "the configuration has no 'input_character_ranges' row of the kind 'alphabetic', "
            "so Metacat Mode cannot tell a letter from a separator"
        )
    for kind in CHARACTER_KINDS:
        ranges[kind].sort()
    lowering = tuple(
        sorted(tuple(r) for r in meta.input_lowering_ranges)
    )
    readable = frozenset(
        spec.glyph for spec in meta.slipnet_node_specs.values() if spec.glyph is not None
    )
    if not readable:
        raise ParserConfigurationError(
            "the Slipnet has no letter node (a node with a glyph), so Metacat Mode has no "
            "letter it can read"
        )
    return ParserRules(
        lowering=lowering,
        ranges={k: tuple(v) for k, v in ranges.items()},
        readable=readable,
        largest_seed=largest,
    )


# ----------------------------------------------------------------------------------------------
# tokenize-string
# ----------------------------------------------------------------------------------------------

#: The three states of ``tokenize-string``: between tokens, inside a string, inside a number.
_NOISE, _LETTERS, _DIGITS = range(3)


def _number(word: str) -> int | None:
    """``string->number`` of a run of digits: the integer, or ``None`` where Scheme gives ``#f``
    (digits that are not the ASCII digits) or where Python will not make the integer (a run longer
    than its integer-string conversion limit).  In Metacat such a run is a bignum above the largest
    seed, so ``None`` is refused by ``valid_token_list`` by the same route as ``#f``: a seed must be
    a valid number, and a number is never a string of the problem."""
    if not word.isascii():
        return None
    try:
        return int(word)
    except ValueError:
        return None


def tokenize(rules: ParserRules, text: str) -> list[object] | None:
    """``tokenize-string``: the tokens of *text*, or ``None`` where Metacat answers ``'error``.

    A string token is a ``str``; a number token is an ``int``, or ``None`` where Scheme's
    ``string->number`` gives ``#f`` (digits that are not the ASCII digits).  A lone surrogate
    cannot reach Metacat at all, so it is not a character here: the text is refused.
    """
    for char in text:
        if ord(char) in _SURROGATES:
            return None
    chars = [rules.lower(c) for c in text]
    tokens: list[object] = []
    buffer: list[str] = []
    state = _NOISE

    def flush() -> None:
        word = "".join(buffer)
        if state == _LETTERS:
            tokens.append(word)
        else:
            tokens.append(_number(word))
        buffer.clear()

    for char in chars:
        if state == _NOISE:
            if rules.is_noise(char):
                continue
            state = _LETTERS if rules.is_alphabetic(char) else _DIGITS
            buffer.append(char)
        elif state == _LETTERS:
            if rules.is_noise(char):
                flush()
                state = _NOISE
            elif rules.is_alphabetic(char):
                buffer.append(char)
            else:
                return None
        else:
            if rules.is_noise(char):
                flush()
                state = _NOISE
            elif rules.is_numeric(char):
                buffer.append(char)
            else:
                return None
    if state != _NOISE:
        flush()
    return tokens


def valid_token_list(rules: ParserRules, tokens: list[object] | None) -> bool:
    """``valid-token-list?``, with the patch's readable-letter rule."""
    if tokens is None or len(tokens) < 3:
        return False
    if not all(rules.valid_letter_symbol(t) for t in tokens[:3]):
        return False
    if len(tokens) == 3:
        return True
    if len(tokens) == 4:
        return rules.valid_letter_symbol(tokens[3]) or rules.valid_number(tokens[3])
    if len(tokens) == 5:
        return rules.valid_letter_symbol(tokens[3]) and rules.valid_number(tokens[4])
    return False


# ----------------------------------------------------------------------------------------------
# From the line to a problem
# ----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ParsedProblem:
    """What the parser read: the strings Metacat Mode runs, and a seed or ``None``."""

    initial: str
    modified: str
    target: str
    #: ``None`` is discovery; a string is an answer to justify.
    answer: str | None
    #: ``None`` when the line gave no seed (``update-current-problem`` then picks a random one).
    seed: int | None


def parse_line(rules: ParserRules, text: str) -> ParsedProblem:
    """The problem on one line, as ``update-current-problem`` reads it; raises ``InvalidInput``."""
    tokens = tokenize(rules, text)
    if not valid_token_list(rules, tokens):
        raise InvalidInput()
    assert tokens is not None
    if len(tokens) == 3:
        return ParsedProblem(tokens[0], tokens[1], tokens[2], None, None)  # type: ignore[arg-type]
    if len(tokens) == 5:
        return ParsedProblem(*tokens)  # type: ignore[arg-type]
    if isinstance(tokens[3], str):
        return ParsedProblem(tokens[0], tokens[1], tokens[2], tokens[3], None)  # type: ignore[arg-type]
    return ParsedProblem(tokens[0], tokens[1], tokens[2], None, tokens[3])  # type: ignore[arg-type]


def random_seed(rules: ParserRules) -> int:
    """A seed for a problem that gave none (Metacat's ``randomize``): 1 to the largest seed."""
    return secrets.randbelow(rules.largest_seed) + 1


def read_fields(
    rules: ParserRules,
    initial: Any,
    modified: Any,
    target: Any,
    answer: Any = None,
    seed: Any = None,
    *,
    seed_allowed: bool = True,
) -> ParsedProblem:
    """Read the fields of a request as one line; the seed is *not* made random here.

    The fields are read left to right as ``initial modified target [answer] [seed]``.  A field
    that is not text, a seed that is not a whole number from 1 to the largest seed, or a line
    Metacat would refuse, raises :class:`InvalidInput`.  With ``seed_allowed`` false (Swarm,
    whose seeds come separately) a seed on the line is refused too.
    """
    for value in (initial, modified, target):
        if not isinstance(value, str):
            raise InvalidInput()
    if answer is not None and not isinstance(answer, str):
        raise InvalidInput()
    parts = [initial, modified, target]
    if answer is not None:
        parts.append(answer)
    if seed is not None:
        if isinstance(seed, bool) or not isinstance(seed, int) or not rules.valid_number(seed):
            raise InvalidInput()
        parts.append(str(seed))
    parsed = parse_line(rules, " ".join(parts))
    if parsed.seed is not None and not seed_allowed:
        raise InvalidInput()
    return parsed


def check_seeds(rules: ParserRules, seeds: list[int]) -> None:
    """Every seed in the list must be a whole number from 1 to the largest seed."""
    for seed in seeds:
        if isinstance(seed, bool) or not isinstance(seed, int) or not rules.valid_number(seed):
            raise InvalidInput()


def read_problem(
    meta: Any, initial: Any, modified: Any, target: Any, answer: Any = None, seed: Any = None,
) -> ParsedProblem:
    """The door's one call: the fields of a request read through Metacat's parser.

    The result always has a seed: the one given, the one on the line, or, as in Metacat, a random
    one picked here (the caller records it and shows it).  Raises :class:`InvalidInput`, or
    :class:`ParserConfigurationError` when the configuration lacks part of the parser.
    """
    rules = rules_from(meta)
    parsed = read_fields(rules, initial, modified, target, answer, seed)
    if parsed.seed is None:
        parsed = ParsedProblem(
            parsed.initial, parsed.modified, parsed.target, parsed.answer, random_seed(rules)
        )
    return parsed
