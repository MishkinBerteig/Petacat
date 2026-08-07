"""The named codelet patterns MetaCat offers for manual clamping.

Scheme: ``trace.ss:1597-1668``.  A codelet pattern is a set of ``(codelet type,
urgency)`` pairs clamped together, so that clamping one pins a whole line of work at
high urgency rather than a single codelet type: a scout at very-high urgency alongside
the evaluator and builder at extremely-high, which is what it takes for the structures
that scout proposes to actually get built.

``gui.ss:597-603`` puts five of them on the Options menu — top-down, bottom-up, rule,
bridge and group — and those five are what this module exposes.

**There used to be two definitions of a pattern**, which is `PHASE 1 PLAN.md` §0.2(c)'s
example: this module held those five as a Python dict for the control API, while the
engine's own clamp sites read a different set of *nine* from the database
(``jootsing.py:253``, ``jootsing.py:429``, ``justify.py:403``).  Same concept, two
definitions, different contents.  The five were content-identical to their database
counterparts when checked, which is luck rather than design — nothing had ever compared
them, and nothing would have said so if an edit to one had moved it away from the other.

So the dict is gone.  ``meta.codelet_patterns`` is the definition, and this module is
the projection of it the menu needs: *which* five are clampable, and what to call them.
That is real information and it is a parameter now — ``clampable_codelet_patterns`` —
rather than a second copy of the patterns themselves.

Urgencies are named rather than numeric: the values live in ``urgency_levels`` seed
data, so a pattern says *which* level and the run resolves it
(``Coderack._pattern_entry``).  This module's docstring said that before the seed data
did; the seed data stored 77 and 91, and now names the tiers.
"""

from __future__ import annotations

from typing import Any

#: How the menu's short name spells the seed data's key.  ``gui.ss`` calls it
#: ``rule``; ``trace.ss`` defines ``rule-codelet-pattern``.
_KEY_SUFFIX = "-codelet-pattern"


def pattern_key(name: str) -> str:
    """The ``meta.codelet_patterns`` key for a menu name.

    ``rule`` -> ``rule-codelet-pattern``.  ``Coderack._pattern_name`` accepts either
    spelling at the clamp sites; this is the one direction the menu needs.
    """
    return name.replace("_", "-") + _KEY_SUFFIX


def clampable_patterns(meta: Any) -> dict[str, str]:
    """Menu name -> label, in the order ``gui.ss:599-603`` lists them."""
    return dict(meta.get_param("clampable_codelet_patterns", {}) or {})


def pattern_names(meta: Any) -> list[str]:
    """The clampable patterns, in the order the menu lists them."""
    return list(clampable_patterns(meta))


def pattern_label(meta: Any, name: str) -> str:
    """What the menu calls *name*."""
    return clampable_patterns(meta)[name]


def pattern_entries(meta: Any, name: str) -> tuple[tuple[str, str], ...]:
    """The ``(codelet type, urgency level)`` pairs *name* clamps.

    Raises ``KeyError`` for a name the menu does not offer, or one whose pattern is
    missing from the configuration — the callers turn that into a 400 naming the
    patterns that do exist.
    """
    if name not in clampable_patterns(meta):
        raise KeyError(name)
    return tuple(
        (codelet_type, level) for codelet_type, level in meta.codelet_patterns[pattern_key(name)]
    )
