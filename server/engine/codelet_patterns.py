"""The named codelet patterns MetaCat offers for manual clamping.

Scheme: ``trace.ss:1597-1668``.  A codelet pattern is a set of ``(codelet type,
urgency)`` pairs clamped together, so that clamping one pins a whole line of work at
high urgency rather than a single codelet type: a scout at very-high urgency alongside
the evaluator and builder at extremely-high, which is what it takes for the structures
that scout proposes to actually get built.

``gui.ss:597-603`` puts five of them on the Options menu — top-down, bottom-up, rule,
bridge and group — and those five are what this module exposes.

Urgencies are named rather than numeric: the values live in ``urgency_levels`` seed
data, so a pattern says *which* level and the run resolves it.
"""

from __future__ import annotations

VERY_HIGH = "very_high"
EXTREMELY_HIGH = "extremely_high"

#: Pattern name -> ((codelet type, urgency level name), ...).
#: Keys and order follow ``gui.ss:599-603``.
CODELET_PATTERNS: dict[str, tuple[tuple[str, str], ...]] = {
    "top_down": (
        ("top-down-bond-scout:direction", VERY_HIGH),
        ("top-down-group-scout:direction", VERY_HIGH),
        ("top-down-bond-scout:category", VERY_HIGH),
        ("top-down-group-scout:category", VERY_HIGH),
        ("top-down-description-scout", VERY_HIGH),
        ("bond-evaluator", EXTREMELY_HIGH),
        ("bond-builder", EXTREMELY_HIGH),
        ("group-evaluator", EXTREMELY_HIGH),
        ("group-builder", EXTREMELY_HIGH),
        ("description-evaluator", EXTREMELY_HIGH),
        ("description-builder", EXTREMELY_HIGH),
    ),
    "bottom_up": (
        ("bottom-up-bond-scout", VERY_HIGH),
        ("bond-evaluator", EXTREMELY_HIGH),
        ("bond-builder", EXTREMELY_HIGH),
        ("group-scout:whole-string", VERY_HIGH),
        ("group-evaluator", EXTREMELY_HIGH),
        ("group-builder", EXTREMELY_HIGH),
        ("bottom-up-bridge-scout", VERY_HIGH),
        ("important-object-bridge-scout", VERY_HIGH),
        ("bridge-evaluator", EXTREMELY_HIGH),
        ("bridge-builder", EXTREMELY_HIGH),
        ("bottom-up-description-scout", VERY_HIGH),
        ("description-evaluator", EXTREMELY_HIGH),
        ("description-builder", EXTREMELY_HIGH),
        ("rule-scout", VERY_HIGH),
        ("rule-evaluator", EXTREMELY_HIGH),
        ("rule-builder", EXTREMELY_HIGH),
    ),
    "rule": (
        ("rule-scout", VERY_HIGH),
        ("rule-evaluator", EXTREMELY_HIGH),
        ("rule-builder", EXTREMELY_HIGH),
    ),
    "bridge": (
        ("bottom-up-bridge-scout", VERY_HIGH),
        ("important-object-bridge-scout", VERY_HIGH),
        ("bridge-evaluator", EXTREMELY_HIGH),
        ("bridge-builder", EXTREMELY_HIGH),
    ),
    "group": (
        ("group-scout:whole-string", VERY_HIGH),
        ("group-evaluator", EXTREMELY_HIGH),
        ("group-builder", EXTREMELY_HIGH),
    ),
}

#: What the menu calls each one (``gui.ss:599-603``).
PATTERN_LABELS: dict[str, str] = {
    "top_down": "Top-down codelet pattern",
    "bottom_up": "Bottom-up codelet pattern",
    "rule": "Rule codelet pattern",
    "bridge": "Bridge codelet pattern",
    "group": "Group codelet pattern",
}


def pattern_names() -> list[str]:
    """The clampable patterns, in the order the menu lists them."""
    return list(CODELET_PATTERNS)


def pattern_entries(name: str) -> tuple[tuple[str, str], ...]:
    """The ``(codelet type, urgency level)`` pairs *name* clamps.

    Raises ``KeyError`` for a name that is not one of the five.
    """
    return CODELET_PATTERNS[name]
