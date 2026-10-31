"""Named, versioned inputs: the config hash and the memory hash (WP3.5).

A Run's behaviour is not determined by ``(problem, seed)``.  It is determined by
``(complete starting state, problem, seed)``, and two parts of that starting state come
from outside the Run: the **metadata** it executes under, and the **Episodic Memory** it
inherits from the episodic runs before it.  Neither was recorded, so two runs that behaved
differently for good reason were indistinguishable in the record.

These hashes make *which* configuration and *which* memory a run saw part of the run's
identity.  That is close to bookkeeping today, when the metadata rarely changes and
memory only accumulates answers.  It stops being bookkeeping in Phase 1, which puts the
concept vocabulary into Episodic Memory, and in Phase 2, which writes love-born concepts
into it: from then on the memory a run inherited is the largest single determinant of
what the run could think, and a record that does not say which memory that was cannot be
interpreted at all.

Both hashes are content hashes over a canonical JSON encoding, so they are stable across
processes and across runs — unlike anything derived from object identity or insertion
order, which would make an unchanged configuration look different on every restart.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, fields, is_dataclass
from typing import Any

#: Truncated to keep the column narrow and readable in a listing. 128 bits of SHA-256
#: is far beyond what distinguishing a handful of configurations requires, and these
#: identify rather than authenticate.
_DIGEST_CHARS = 32


def _canonical(value: Any) -> Any:
    """Reduce a value to something JSON can encode deterministically.

    Sets and dict ordering are the two traps.  A ``set`` iterates in an order that
    depends on hash randomisation, so it is sorted; a ``dict`` is dumped with
    ``sort_keys``. Without both, the same metadata would hash differently between
    processes and the field would be worse than useless — it would report spurious
    change.
    """
    if is_dataclass(value) and not isinstance(value, type):
        return _canonical(asdict(value))
    if isinstance(value, dict):
        return {str(k): _canonical(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (set, frozenset)):
        return sorted(_canonical(v) for v in value)
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return repr(value)


def _digest(payload: Any) -> str:
    encoded = json.dumps(_canonical(payload), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:_DIGEST_CHARS]


#: The provider fields ``config_hash`` leaves out, by name.  Everything else the provider
#: holds is hashed, so a new configuration table or field is covered the day it is added
#: without anyone remembering to add it.  Adding a name here is a decision, and
#: ``tests/unit/test_config_hash_guard.py`` pins this exact set.
#:
#: * ``demo_problems`` -- a catalogue of examples; editing one changes no run's thinking.
#: * ``slipnet_layout`` -- where a node is drawn.
#: * ``enum_values`` -- the engine's own vocabularies, mirrored from lookup tables.
HASH_EXCLUDED_FIELDS = frozenset({"demo_problems", "slipnet_layout", "enum_values"})

#: Part of every digest, so a hash of this scheme can never equal a hash of another.
HASH_SCHEME = 2


def _canonical_ordered(value: Any) -> Any:
    """Like :func:`_canonical`, but a dict keeps its order.

    The order of the nodes, the links, the posting rules and the keys of a JSON value is
    behaviour (it fixes the float accumulation order and which node each random draw is
    spent on), so a configuration that differs only in order is a different configuration.
    Sets still sort.
    """
    if is_dataclass(value) and not isinstance(value, type):
        return _canonical_ordered({f.name: getattr(value, f.name) for f in fields(value)})
    if isinstance(value, dict):
        return [[str(k), _canonical_ordered(v)] for k, v in value.items()]
    if isinstance(value, (set, frozenset)):
        return sorted(_canonical(v) for v in value)
    if isinstance(value, (list, tuple)):
        return [_canonical_ordered(v) for v in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return [type(value).__name__, value] if isinstance(value, (int, float)) and not isinstance(value, bool) else value
    return repr(value)


def _field_digest(value: Any) -> str:
    encoded = json.dumps(_canonical_ordered(value), separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:_DIGEST_CHARS]


def hashed_field_names(meta: Any) -> list[str]:
    """The provider's field names the hash covers: every field but the excluded ones."""
    return [f.name for f in fields(meta) if f.name not in HASH_EXCLUDED_FIELDS]


def field_digests(meta: Any) -> dict[str, str]:
    """``{field name: digest of that one field}`` over the hashed provider fields.

    A caller that knows which fields changed recomputes only those digests and
    :func:`combine` the result.
    """
    return {name: _field_digest(getattr(meta, name)) for name in hashed_field_names(meta)}


def combine(digests: dict[str, str]) -> str:
    """The configuration hash from per-field digests (scheme 2)."""
    return _digest({"scheme": HASH_SCHEME, "fields": digests})


def config_hash(meta: Any) -> str:
    """Identify the metadata a run executed under: ``combine(field_digests(meta))``.

    The hash is taken over every field of the provider except
    :data:`HASH_EXCLUDED_FIELDS`, by reflection, so it covers the Slipnet (nodes, links,
    roles, theme relations), the codelet sources, the posting rules and patterns, the
    parameters, urgency levels, formula coefficients, theme dimensions and the
    commentary templates (which carry text that changes stored output).  Order and the
    type of a number (``5`` against ``5.0``) are part of the value.
    """
    return combine(field_digests(meta))


def memory_hash(memory: Any) -> str:
    """Identify the state of an Episodic Memory.

    Hashed over what a run can actually be influenced by: the problems, rules, qualities
    and theme patterns of the stored answers, and the problems and theme patterns of the
    stored snags. Reminding compares theme patterns and rules, so those are the content;
    ``answer_id`` and ``activation`` are not, being respectively a position in this
    memory and a value the next run overwrites.

    An empty memory hashes to a stable value rather than to a special case, so a Run at
    the start of a sequence of episodic runs is recorded as what it is.
    """
    answers = [
        {
            "problem": list(a.problem),
            "top_rule": a.top_rule_description,
            "bottom_rule": a.bottom_rule_description,
            "quality": a.quality,
            "themes": a.themes,
        }
        for a in getattr(memory, "answers", [])
    ]
    snags = [
        {"problem": list(s.problem), "theme_pattern": s.theme_pattern}
        for s in getattr(memory, "snags", [])
    ]
    return _digest({"answers": answers, "snags": snags})
