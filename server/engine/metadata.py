"""MetadataProvider — Database-driven configuration.

There is no constants.py. All domain knowledge lives in Postgres and is
loaded at startup into an immutable MetadataProvider. For REPL/testing,
from_standard_configuration() loads from the seed_data/ JSON files directly.

Scheme source: constants.ss (replaced by seed_data/*.json -> Postgres)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any

from server.engine.rational import parse_rational
from server.engine.roles import Vocabulary, VocabularyBinding, vocabulary_bindings


class ConfigurationRequired(RuntimeError):
    """A configuration-dependent engine function was called without a ``MetadataProvider``.

    The engine takes every parameter, phrase and conceptual depth from the provider its
    run holds.  There is no fallback to the Metacat Standard Configuration files: a
    caller that has no provider must build one (``MetadataProvider.from_standard_configuration`` in a
    test, the database in a served run) and pass it.
    """


def require_meta(meta: Any, what: str) -> Any:
    """``meta``, or :class:`ConfigurationRequired` naming what needed it."""
    if meta is None:
        raise ConfigurationRequired(
            f"{what} needs the run's MetadataProvider (meta); none was given and the "
            "engine does not read the Metacat Standard Configuration files at run time"
        )
    return meta


def verbose_messages(meta: Any) -> dict[str, str]:
    """Verbose mode's message catalogue: ``meta.commentary_templates["verbose_messages"]``.

    Exactly what the provider holds (the database in a served run); nothing is overlaid
    from the Metacat Standard Configuration files.
    """
    require_meta(meta, "verbose_messages")
    held = getattr(meta, "commentary_templates", None) or {}
    return dict(held.get("verbose_messages") or {})


@dataclass(frozen=True)
class SlipnodeSpec:
    name: str
    short_name: str
    conceptual_depth: int
    # DSL expression over `obj` deciding whether this node validly describes a
    # Workspace object.  Scheme: ``define-descriptor-predicate`` (slipnet.ss:508-610),
    # where the predicate is a lambda attached to the node itself.  Keeping it in
    # the seed data means a new descriptor needs no code change, the same way a
    # new codelet type needs only its ``execute_body``.
    descriptor_predicate: str | None = None
    #: What code used to read off the name (``name[6:]``).  Names are opaque (plan 3.1).
    plain_name: str | None = None
    #: The character a letter node stands for; a node with a glyph is a letter.
    glyph: str | None = None
    #: The value of a number node; a node with a value is on the ladder.
    numeric_value: int | None = None
    #: Display only.  None falls back to ``plain_name`` or ``short_name``.
    full_name: str | None = None
    cm_short_name: str | None = None
    article_an: bool | None = None


@dataclass(frozen=True)
class SlipnetLinkSpec:
    from_node: str
    to_node: str
    link_type: str  # category, instance, property, lateral, lateral_sliplink
    label_node: str | None
    link_length: int | None  # None means dynamic (determined by label node)
    fixed_length: bool


@dataclass(frozen=True)
class CodeletSpec:
    name: str
    family: str  # bond, group, bridge, description, rule, answer, meta, breaker
    phase: str  # scout, evaluator, builder, other
    description: str
    source_file: str
    source_line: int
    execute_body: str


@dataclass(frozen=True)
class PostingRuleSpec:
    codelet_type: str
    direction: str  # bottom_up, top_down, thematic
    urgency_level: str | None  # a name in urgency_levels
    urgency_formula: str | None
    posting_formula: str
    count_formula: str
    count_values: dict[str, int | float] | None
    condition: str
    triggering_slipnodes: list[str] | None
    #: The rule's natural key (the codelet type when the file gives none).
    rule_key: str = ""


@dataclass(frozen=True)
class NodeRoleSpec:
    """A role bound to a Slipnet node.  ``ordinal`` is 0 for a single-node role and the
    list position for an ordered role."""

    role: str
    ordinal: int
    node_name: str


@dataclass(frozen=True)
class CodeletRoleSpec:
    """A role bound to a codelet type; the same shape as :class:`NodeRoleSpec`."""

    role: str
    ordinal: int
    codelet_type: str


@dataclass(frozen=True)
class ThemeRelationSpec:
    """A theme relation.  ``node_name`` is None for ``diff``; ``abstractness`` None means
    the node's conceptual depth."""

    name: str
    ordinal: int
    node_name: str | None
    abstractness: int | None
    description: str
    #: The engine's name for the relation (``theme_relation.opposite``), or None.
    role: str | None = None


@dataclass(frozen=True)
class LinkTypeSpec:
    """A link type and what the engine does with a link of that type (``behaviour``:
    ``category``, ``instance``, ``property``, ``lateral``, ``slip``, or None for none)."""

    name: str
    behaviour: str | None = None


@dataclass(frozen=True)
class ClampTypeSpec:
    """A clamp type: what its clamp holds the rest of the Coderack against, the factor its
    clamps give the jootsing probability, and what counts as progress for it."""

    name: str
    role: str | None
    #: The name of an urgency level, or None (no background).
    codelet_background_level: str | None
    jootsing_factor: float | None
    #: The factor applies only while the clamp is still the newest event of the Trace.
    jootsing_only_when_latest: bool
    #: The name of a progress focus.
    progress_focus: str | None
    #: The names of the codelet patterns (``meta.codelet_patterns``) a clamp of this type clamps.
    codelet_patterns: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProgressFocusSpec:
    """A progress focus: the event types (names) that count as progress."""

    name: str
    event_types: tuple[str, ...]


@dataclass(frozen=True)
class DemoProblem:
    name: str
    section: str
    initial: str
    modified: str
    target: str
    answer: str | None
    seed: int
    description: str


@dataclass(frozen=True)
class ThemeDimensionSpec:
    slipnet_node: str
    valid_relations: list[str]


@dataclass
class MetadataProvider:
    """Immutable cache of all metadata. Loaded from Postgres at startup,
    or from seed_data/ JSON files for REPL/testing."""

    slipnet_node_specs: dict[str, SlipnodeSpec] = field(default_factory=dict)
    slipnet_link_specs: list[SlipnetLinkSpec] = field(default_factory=list)
    codelet_specs: dict[str, CodeletSpec] = field(default_factory=dict)
    posting_rules: list[PostingRuleSpec] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)
    urgency_levels: dict[str, int] = field(default_factory=dict)
    formula_coefficients: dict[str, int | float | Fraction] = field(default_factory=dict)
    commentary_templates: dict[str, Any] = field(default_factory=dict)
    demo_problems: list[DemoProblem] = field(default_factory=list)
    theme_dimensions: list[ThemeDimensionSpec] = field(default_factory=list)
    slipnet_layout: dict[str, tuple[int, int]] = field(default_factory=dict)
    #: Pattern name -> ``[(codelet type, urgency *level name*), ...]``.  The level is
    #: named rather than numeric, and ``Coderack._pattern_entry`` resolves it against
    #: ``urgency_levels``; see `server/engine/codelet_patterns.py`.
    codelet_patterns: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    #: Role bindings, ordered by ``(role, ordinal)`` (byte order of the role name).  Nothing
    #: in the engine reads them yet (EN3 adds the mechanism).
    node_roles: tuple[NodeRoleSpec, ...] = ()
    codelet_roles: tuple[CodeletRoleSpec, ...] = ()
    #: Theme relations, ordered by ``ordinal``.
    theme_relations: tuple[ThemeRelationSpec, ...] = ()
    #: The rows of the enum tables bound to a role of the vocabulary
    #: (``server/engine/roles.py``), ordered by role name.  Hashed with the rest.
    vocabulary_bindings: tuple[VocabularyBinding, ...] = ()
    #: The link types and their behaviours, in table order.
    link_types: tuple[LinkTypeSpec, ...] = ()
    #: The clamp types, in table order.
    clamp_types: tuple[ClampTypeSpec, ...] = ()
    #: The progress focuses, in table order.
    progress_focuses: tuple[ProgressFocusSpec, ...] = ()
    #: The codelet families whose codelets run alone under the free-running executor.
    serialised_families: tuple[str, ...] = ()
    #: Parameter name -> what its value's names refer to (``engine_params.refers_to``:
    #: ``node_list``, ``trigger_node_list``, ``node_map``, ``codelet_type_list`` or
    #: ``urgency_level``); a parameter whose value names nothing is absent.
    param_refers_to: dict[str, str] = field(default_factory=dict)

    @property
    def vocabulary(self) -> Vocabulary:
        """The resolved vocabulary of this configuration (built once, on first use).

        ``vocabulary.bridge_type_top`` is the name of the row bound to ``bridge_type.top``
        or an ``AbsentName``.  A run reads it through its binding
        (``run_binding.constants().vocab`` on a hot path).
        """
        cached = self.__dict__.get("_vocabulary")
        if cached is None:
            cached = Vocabulary({b.role: b.name for b in self.vocabulary_bindings})
            self.__dict__["_vocabulary"] = cached
        return cached

    def params_referring_to(self, *kinds: str) -> tuple[str, ...]:
        """The names of the parameters whose ``refers_to`` is one of *kinds*, in the table's order."""
        return tuple(n for n in self.params if self.param_refers_to.get(n) in kinds)

    def get_param(self, name: str) -> Any:
        """The engine parameter *name*; ``None`` when the configuration lacks it.

        There is no default argument (bug B12: a code default hides a missing key and keeps a
        second copy of the value in the code).  Every name the engine or a codelet body reads is
        on the declared read list in ``start_check.py``, which stops a run at its start when one
        is missing.
        """
        return self.params.get(name)

    def with_overrides(self, overrides: dict[str, Any] | None) -> MetadataProvider:
        """A view of this metadata with some parameters replaced, for one Run.

        Returns ``self`` unchanged when there is nothing to override, so the ordinary
        case allocates nothing and every Run keeps sharing one provider.

        A shallow copy otherwise: only ``params`` is rebuilt, and the slipnet, codelet
        and posting-rule specs are shared by reference.  That is safe because they are
        read-only for the lifetime of a run, and it matters because those are the bulk —
        copying them per Run would put the 59 nodes, 202 links and 27 compiled codelet
        bodies behind every parameter change.
        """
        if not overrides:
            return self
        from dataclasses import replace

        return replace(self, params={**self.params, **overrides})

    def get_urgency(self, name: str) -> int:
        return self.urgency_levels[name]

    def get_formula_coeff(self, name: str) -> int | float | Fraction:
        return self.formula_coefficients[name]

    @classmethod
    def from_standard_configuration(cls, seed_dir: str) -> MetadataProvider:
        """Load metadata from seed_data/ JSON files (no DB needed)."""

        def _load(filename: str) -> Any:
            with open(os.path.join(seed_dir, filename)) as f:
                return json.load(f)

        # Slipnet nodes
        nodes_data = _load("slipnet_nodes.json")
        node_specs = {
            n["name"]: SlipnodeSpec(
                name=n["name"],
                short_name=n["short_name"],
                conceptual_depth=n["conceptual_depth"],
                descriptor_predicate=n.get("descriptor_predicate"),
                plain_name=n.get("plain_name"),
                glyph=n.get("glyph"),
                numeric_value=n.get("numeric_value"),
                full_name=n.get("full_name"),
                cm_short_name=n.get("cm_short_name"),
                article_an=n.get("article_an"),
            )
            for n in nodes_data
        }

        # Slipnet links
        links_data = _load("slipnet_links.json")
        link_specs = [
            SlipnetLinkSpec(
                from_node=lk["from_node"],
                to_node=lk["to_node"],
                link_type=lk["link_type"],
                label_node=lk.get("label_node"),
                link_length=lk.get("link_length"),
                fixed_length=lk["fixed_length"],
            )
            for lk in links_data
        ]

        # Engine params
        params = _load("engine_params.json")

        refs = _load("engine_param_refs.json")
        param_refers_to = {n: refs[n] for n in params if n in refs}

        # Urgency levels
        urgency_levels = _load("urgency_levels.json")

        # Formula coefficients.  A JSON string is a rational, ``"n/m"``, held exactly.
        formula_coefficients = {
            name: parse_rational(value) if isinstance(value, str) else value
            for name, value in _load("formula_coefficients.json").items()
        }

        # Codelet types
        codelets_data = _load("codelet_types.json")
        codelet_specs = {
            c["name"]: CodeletSpec(
                name=c["name"],
                family=c["family"],
                phase=c["phase"],
                description=c.get("description", ""),
                source_file=c.get("source_file", ""),
                source_line=c.get("source_line", 0),
                execute_body=c.get("execute_body", ""),
            )
            for c in codelets_data
        }

        # Posting rules
        posting_data = _load("posting_rules.json")
        posting_rules = [
            PostingRuleSpec(
                codelet_type=pr["codelet_type"],
                direction=pr["direction"],
                urgency_level=pr.get("urgency_level"),
                urgency_formula=pr.get("urgency_formula"),
                posting_formula=pr["posting_formula"],
                count_formula=pr["count_formula"],
                count_values=pr.get("count_values"),
                condition=pr["condition"],
                triggering_slipnodes=pr.get("triggering_slipnodes"),
                rule_key=pr.get("rule_key", pr["codelet_type"]),
            )
            for pr in posting_data.get("posting_rules", [])
        ]

        # Compile every posting formula now, so a bad expression fails here rather
        # than the first time its rule is consulted.  Same contract as
        # ``compile_descriptor_predicate``.
        from server.engine.posting import validate_posting_formulas

        validate_posting_formulas(posting_rules)

        codelet_patterns = {
            name: [(entry[0], entry[1]) for entry in entries]
            for name, entries in posting_data.get("codelet_patterns", {}).items()
        }

        # Commentary templates
        commentary_templates = _load("commentary_templates.json")

        # Demo problems
        demos_data = _load("demo_problems.json")
        demo_problems = [
            DemoProblem(
                name=d["name"],
                section=d.get("section", ""),
                initial=d["initial"],
                modified=d["modified"],
                target=d["target"],
                answer=d.get("answer"),
                seed=d["seed"],
                description=d.get("description", ""),
            )
            for d in demos_data
        ]

        # Theme dimensions
        themes_data = _load("theme_dimensions.json")
        theme_dimensions = [
            ThemeDimensionSpec(
                slipnet_node=td["slipnet_node"],
                valid_relations=td["valid_relations"],
            )
            for td in themes_data.get("dimensions", [])
        ]

        # Slipnet layout
        layout_data = _load("slipnet_layout.json")
        slipnet_layout = {
            name: (pos[0], pos[1])
            for name, pos in layout_data.get("node_positions", {}).items()
        }

        # Roles and theme relations.  Ordered the way the database orders them
        # (``role`` by byte value, then ``ordinal``) so the two loaders agree.
        roles_data = _load("roles.json")
        node_roles = tuple(
            NodeRoleSpec(role=r["role"], ordinal=r["ordinal"], node_name=r["node_name"])
            for r in sorted(
                roles_data.get("node_roles", []),
                key=lambda r: (r["role"].encode(), r["ordinal"]),
            )
        )
        codelet_roles = tuple(
            CodeletRoleSpec(role=r["role"], ordinal=r["ordinal"], codelet_type=r["codelet_type"])
            for r in sorted(
                roles_data.get("codelet_roles", []),
                key=lambda r: (r["role"].encode(), r["ordinal"]),
            )
        )
        theme_relations = tuple(
            ThemeRelationSpec(
                name=r["name"],
                ordinal=r["ordinal"],
                node_name=r.get("node_name"),
                abstractness=r.get("abstractness"),
                description=r.get("description", ""),
                role=r.get("role"),
            )
            for r in sorted(_load("theme_relations.json"), key=lambda r: r["ordinal"])
        )

        # The enum tables: the rows the engine names (their ``role`` column) and the tables
        # that carry more than a name.
        enum_rows: dict[str, list[dict[str, Any]]] = {}
        enums_file = os.path.join(seed_dir, "enums.json")
        if os.path.exists(enums_file):
            enum_rows = {t: sorted(rows, key=lambda r: (r["sort_order"], r["name"].encode())) for t, rows in _load("enums.json").items()}
        enum_rows["theme_relations"] = [
            {"name": r.name, "role": r.role} for r in theme_relations
        ]
        link_types = tuple(
            LinkTypeSpec(name=r["name"], behaviour=r.get("behaviour"))
            for r in enum_rows.get("link_types", [])
        )
        clamp_types = tuple(
            ClampTypeSpec(
                name=r["name"],
                role=r.get("role"),
                codelet_background_level=r.get("codelet_background_level"),
                jootsing_factor=r.get("jootsing_factor"),
                jootsing_only_when_latest=bool(r.get("jootsing_only_when_latest", False)),
                progress_focus=r.get("progress_focus"),
                codelet_patterns=tuple(r.get("codelet_patterns") or ()),
            )
            for r in enum_rows.get("clamp_types", [])
        )
        progress_focuses = tuple(
            ProgressFocusSpec(name=r["name"], event_types=tuple(r["event_types"]))
            for r in enum_rows.get("progress_focuses", [])
        )
        serialised_families = tuple(
            r["name"] for r in enum_rows.get("codelet_families", []) if r.get("serialised")
        )

        return cls(
            slipnet_node_specs=node_specs,
            slipnet_link_specs=link_specs,
            codelet_specs=codelet_specs,
            posting_rules=posting_rules,
            params=params,
            urgency_levels=urgency_levels,
            formula_coefficients=formula_coefficients,
            commentary_templates=commentary_templates,
            demo_problems=demo_problems,
            theme_dimensions=theme_dimensions,
            slipnet_layout=slipnet_layout,
            codelet_patterns=codelet_patterns,
            node_roles=node_roles,
            codelet_roles=codelet_roles,
            theme_relations=theme_relations,
            vocabulary_bindings=vocabulary_bindings(enum_rows),
            link_types=link_types,
            clamp_types=clamp_types,
            progress_focuses=progress_focuses,
            serialised_families=serialised_families,
            param_refers_to=param_refers_to,
        )
