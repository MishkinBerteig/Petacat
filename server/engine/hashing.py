"""Named, versioned inputs: the config hash and the memory hash (WP3.5).

A Run's behaviour is not determined by ``(problem, seed)``.  It is determined by
``(complete starting state, problem, seed)``, and two parts of that starting state come
from outside the Run: the **metadata** it executes under, and the **Episodic Memory** it
inherits from its Training Session.  Neither was recorded, so two runs that behaved
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
from dataclasses import asdict, is_dataclass
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


def config_hash(meta: Any) -> str:
    """Identify the metadata a run executed under.

    Covers everything that changes what the engine *does*: the Slipnet's nodes and
    links, the codelet sources, the posting rules, the parameters, the urgency levels,
    the formula coefficients and the theme dimensions.

    Deliberately excluded: the demo-problem catalogue, the slipnet display layout, the
    commentary templates and the enum lookup tables. Editing a demo problem or moving a
    node in the display does not change how any run thinks, and a hash that changed on
    those would report differences that are not differences — which is exactly how a
    field like this stops being trusted.
    """
    return _digest(
        {
            "slipnet_nodes": meta.slipnet_node_specs,
            "slipnet_links": meta.slipnet_link_specs,
            "codelets": meta.codelet_specs,
            "posting_rules": meta.posting_rules,
            "params": meta.params,
            "urgency_levels": meta.urgency_levels,
            "formula_coefficients": meta.formula_coefficients,
            "theme_dimensions": meta.theme_dimensions,
        }
    )


def memory_hash(memory: Any) -> str:
    """Identify the state of an Episodic Memory.

    Hashed over what a run can actually be influenced by: the problems, rules, qualities
    and theme patterns of the stored answers, and the problems and theme patterns of the
    stored snags. Reminding compares theme patterns and rules, so those are the content;
    ``answer_id`` and ``activation`` are not, being respectively a position in this
    memory and a value the next run overwrites.

    An empty memory hashes to a stable value rather than to a special case, so a Fast
    Run against a fresh ephemeral memory is recorded as what it is.
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
