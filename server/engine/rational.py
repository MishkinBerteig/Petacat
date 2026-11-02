"""The rational value kind: an exact ``n/m`` in the configuration.

Where the engine (following Metacat) computes with an exact rational, the configuration holds
that rational exactly, never a rounded decimal.  A seed file gives one as the JSON string
``"n/m"``; the database holds the same text; the provider holds a ``fractions.Fraction``.
Nothing on the way goes through a float.
"""

from __future__ import annotations

import re
from fractions import Fraction

#: Two integers and a slash; the denominator is positive.  ASCII digits only, no spaces
#: inside, so ``"2/3"`` is the one spelling a person types.
_RATIONAL = re.compile(r"([+-]?[0-9]+)/([0-9]+)", re.ASCII)

RATIONAL_REFUSAL = "a rational is two integers written n/m with a positive denominator, such as 2/3"


def parse_rational(text: str) -> Fraction:
    """``"n/m"`` as a ``Fraction``; ``ValueError`` (with a clear message) when it is not one."""
    match = _RATIONAL.fullmatch(text.strip()) if isinstance(text, str) else None
    if match is None:
        raise ValueError(f"{text!r} is not a rational: {RATIONAL_REFUSAL}")
    numerator, denominator = int(match.group(1)), int(match.group(2))
    if denominator <= 0:
        raise ValueError(f"{text!r} is not a rational: {RATIONAL_REFUSAL}")
    return Fraction(numerator, denominator)


def format_rational(value: Fraction) -> str:
    """The canonical ``"n/m"`` of *value*: lowest terms, always with the denominator."""
    return f"{value.numerator}/{value.denominator}"


def canonical_rational(text: str) -> str:
    """``parse_rational`` then ``format_rational``: how a rational is stored and shown."""
    return format_rational(parse_rational(text))
