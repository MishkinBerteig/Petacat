"""Display names come from the node columns, never from the node's name (EN5a).

Two tests:

* **The rename test.**  Every node of a Slipnet built from the Metacat Standard Configuration
  is renamed to an opaque name while its display columns (``plain_name``, ``full_name``,
  ``cm_short_name``, ``article_an``, ``numeric_value``) and its roles stay; the English that
  ``trace_display``, ``verbose``, ``snag_explanation``, ``rule_english`` (its name and
  article helpers) and ``concept_mappings`` produce must be byte-identical.  The functions are
  called directly, on small stand-in structures: a whole-run comparison is blocked by node
  literals in files EN5a does not own (``bonds.py``, ``groups.py``, ``images.py``, ... and the
  grammar of ``rule_english.py`` itself, which EN8 converts).
* **The fallback test.**  A node whose display columns are all NULL and whose name has no
  ``plato-`` prefix prints through every display path with the fallbacks of
  ``ABSENCE-BEHAVIOUR.md`` 2.6, without an error.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from server.engine import trace as T
from server.engine import trace_display as D
from server.engine import verbose as V
from server.engine.concept_mappings import slippage_english_name
from server.engine.metadata import MetadataProvider
from server.engine.rule_english import _lc as rule_lc
from server.engine.slipnet import (
    Slipnet,
    SlipnetNode,
    article_of,
    cm_short_name_of,
    full_name_of,
    plain_name_of,
)
from server.engine.snag_explanation import explain_failure, snag_object_phrase
from server.engine.workspace import WorkspaceString
from tests.support.standard_configuration import make_node

SEED_DIR = Path(__file__).resolve().parents[2] / "seed_data"


_META = MetadataProvider.from_standard_configuration(str(SEED_DIR))
_TEMPLATES = _META.commentary_templates


def _slipnet(rename: bool) -> Slipnet:
    slipnet = Slipnet.from_metadata(_META)
    if rename:
        nodes = list(slipnet.nodes.values())
        slipnet.nodes.clear()
        for i, node in enumerate(nodes):
            node.name = f"opaque-{i:03d}"
            slipnet.nodes[node.name] = node
    return slipnet


def _glyph(slipnet: Slipnet, ch: str) -> SlipnetNode:
    return next(n for n in slipnet.nodes.values() if n.glyph == ch)


def _number(slipnet: Slipnet, value: int) -> SlipnetNode:
    return next(n for n in slipnet.nodes.values() if n.numeric_value == value)


def _string(text: str) -> WorkspaceString:
    s = WorkspaceString.__new__(WorkspaceString)
    s.text = text
    return s


def _letter(node: SlipnetNode, pos: int) -> SimpleNamespace:
    return SimpleNamespace(
        letter_category=node, left_string_pos=pos, right_string_pos=pos,
        get_descriptor_for=lambda facet, n=node: n,
    )


def _group(roles, *descriptors, category, direction=None, facet=None, nested=False):
    objects = [
        SimpleNamespace(objects=[1], get_descriptor_for=lambda f, d=d: d) if nested
        else SimpleNamespace(get_descriptor_for=lambda f, d=d: d)
        for d in descriptors
    ]
    return SimpleNamespace(
        objects=objects, group_category=category, direction=direction,
        bond_facet=facet if facet is not None else roles.dimension_letter_category,
        right_string_pos=len(objects) - 1, left_string_pos=0,
        string=SimpleNamespace(length=len(objects) + 1, string_type="initial", translated=False),
        _get_initial_letter_category=lambda: descriptors[0] if descriptors else None,
    )


def _english(slipnet: Slipnet) -> list[str]:
    """Every display path of EN5a's files, over fixed inputs, as a list of strings."""
    out: list[str] = []
    roles = slipnet.roles
    nodes = list(slipnet.nodes.values())

    # Name helpers, for every node.
    for n in nodes:
        out += [
            D.lowercase_name(n), D.uppercase_name(n), D.full_slipnode_name(n),
            D.cm_short_name(n), rule_lc(n), article_of(n), plain_name_of(n),
            full_name_of(n), cm_short_name_of(n), V.label_name(n),
        ]
        out.append(D.header(T.TraceEvent(standard_names.CONCEPT_ACTIVATION, 5, 50.0, slipnode=n)))
        out.append(D.print_name(T.TraceEvent(standard_names.CONCEPT_ACTIVATION, 5, 50.0, slipnode=n)))

    a, b, c = (_glyph(slipnet, ch) for ch in "abc")
    two, three = _number(slipnet, 2), _number(slipnet, 3)

    # Group names, headers and Trace print names.
    for direction in (roles.direction_left, roles.direction_right, None):
        letters = _group(roles, a, b, c, category=roles.group_category_successor, direction=direction)
        out.append(D.group_event_text(letters))
        out.append(D.print_name(T.TraceEvent(standard_names.GROUP_BUILT, 5, 50.0, group=letters)))
        out.append(V.ascii_name(letters))
    numbers = _group(roles, two, three, category=roles.group_category_successor, nested=True)
    out.append(D.group_event_text(numbers))
    for category in (
        roles.group_category_successor, roles.group_category_predecessor, roles.group_category_sameness,
    ):
        group = _group(roles, a, a, category=category, direction=None)
        out.append(D.header(T.TraceEvent(standard_names.GROUP_BUILT, 5, 50.0, group=group)))
        out.append(D.header(T.TraceEvent(standard_names.GROUP_BUILT, 5, 50.0, group=group, flipped=True)))
        out.append(V.ascii_name(group))
        out.append(V.full_object_name(group))
    out.append(V.full_object_name(SimpleNamespace()))

    # Concept mappings.
    identity, opposite = slipnet.relation("identity"), slipnet.relation("opposite")
    left, right = roles.direction_left, roles.direction_right
    pairs = [
        (roles.dimension_letter_category, a, b, None),
        (roles.dimension_direction, left, right, opposite),
        (roles.dimension_string_position, roles.position_leftmost, roles.position_rightmost, opposite),
        (roles.dimension_string_position, roles.position_whole, roles.position_single, None),
        (roles.dimension_bond_category, roles.bond_category_sameness, roles.bond_category_sameness, identity),
    ]
    for dimension, d1, d2, label in pairs:
        cm = SimpleNamespace(
            description_type1=dimension, descriptor1=d1, description_type2=dimension, descriptor2=d2,
            label=label, is_identity=label is identity, object1=None,
        )
        out += [
            D.concept_mapping_print_name(cm), slippage_english_name(cm),
            slippage_english_name({"descriptor1": d1, "descriptor2": d2}),
            V.concept_mapping_long_name(cm), str(D.cm_ref(cm)),
        ]
        out.append(D.header(T.TraceEvent(
            standard_names.CONCEPT_MAPPING_BUILT, 5, 50.0, concept_mapping=cm,
            bridge=SimpleNamespace(bridge_type="top"))))

    # Theme-supporting concept mappings (the whole/single exclusion; bond-category vs group).
    group_dim, bond_dim = roles.dimension_group_category, roles.dimension_bond_category
    succ_relation = slipnet.relation("successor")
    cms = [
        SimpleNamespace(description_type1=roles.dimension_string_position,
                        descriptor1=roles.position_whole, descriptor2=roles.position_single,
                        label=None),
        SimpleNamespace(description_type1=bond_dim, descriptor1=roles.bond_category_sameness,
                        descriptor2=roles.bond_category_sameness, label=succ_relation),
        SimpleNamespace(description_type1=group_dim, descriptor1=a, descriptor2=b, label=opposite),
    ]
    bridge = SimpleNamespace(get_all_concept_mappings=lambda: cms)
    pattern = {group_dim.name: "successor", roles.dimension_string_position.name: "diff"}
    out.append(str([cms.index(cm) for _, cm in D._theme_supporting(pattern, [bridge], slipnet)]))

    # Bonds.
    for category in (roles.bond_category_sameness, slipnet.relation("successor"),
                     slipnet.relation("predecessor")):
        for direction in (left, right, None):
            bond = SimpleNamespace(
                bond_category=category, direction=direction,
                left_object=_letter(a, 0), right_object=_letter(b, 1),
                string=SimpleNamespace(string_type="initial", translated=False),
                proposal_level="built",
            )
            out.append(V._bond_text(bond, None))
    out.append(V.ascii_name(_letter(c, 2)))

    # Themes.
    for dimension, relation in ((roles.dimension_letter_category, "identity"),
                                (roles.dimension_direction, "opposite"),
                                (roles.dimension_bond_category, "successor"),
                                (roles.dimension_length, "diff")):
        theme = SimpleNamespace(dimension=dimension.name, relation=relation)
        out.append(V.theme_ascii_name(theme, slipnet))
    log = V.VerboseLog()
    log.slipnet = slipnet
    for dimension, relation in ((roles.dimension_letter_category, "identity"),
                                (roles.dimension_direction, "opposite"),
                                (roles.dimension_length, "diff")):
        out.append(str(log.reveal({"dimension": dimension.name, "relation": relation})))

    # Snag explanations.
    st = _string("abc")
    out.append(snag_object_phrase(st, _TEMPLATES))
    for failure in (
        ("SWAP", [st], roles.dimension_letter_category),
        ("CONFLICT", st, roles.dimension_length, st, roles.dimension_direction),
        ("CHANGE", st, (roles.dimension_group_category, None, roles.dimension_length)),
        ("CHANGE", st, (roles.dimension_group_category, None, roles.dimension_letter_category)),
    ):
        out.append(str(explain_failure(failure, _TEMPLATES)))
    return out


def test_renaming_the_nodes_does_not_change_the_display_english():
    plain = _english(_slipnet(rename=False))
    renamed = _english(_slipnet(rename=True))
    assert len(plain) > 250
    assert plain == renamed
    # And the renaming took: no opaque name leaked into any text.
    assert not any("opaque-" in line for line in renamed)


def test_a_node_with_every_display_column_null_prints_with_the_fallbacks():
    # A learned node: no ``plato-`` prefix, no plain/full/cm name, no article, no short name.
    bare = make_node("L1-3", "", 50)
    assert bare.plain_name is None and bare.full_name is None
    assert bare.cm_short_name is None and bare.article_an is None
    assert plain_name_of(bare) == "L1-3"
    assert D.lowercase_name(bare) == "l1-3" and D.uppercase_name(bare) == "L1-3"
    assert D.full_slipnode_name(bare) == "L1-3"
    assert D.cm_short_name(bare) == "L1-3"
    assert article_of(bare) == "a" and rule_lc(bare) == "l1-3"
    assert V.label_name(bare) == "l1-3"

    # With a short name the chain goes plain_name -> short_name, cm_short_name -> short_name,
    # full_name -> plain_name.
    short = make_node("odd", "Odd", 50)
    assert plain_name_of(short) == "Odd" and D.cm_short_name(short) == "Odd"
    assert D.full_slipnode_name(short) == "Odd"
    short.plain_name = "plain"
    assert D.full_slipnode_name(short) == "plain" and D.cm_short_name(short) == "Odd"

    # Every display path of the files.
    for event in (
        T.TraceEvent(standard_names.CONCEPT_ACTIVATION, 5, 50.0, slipnode=bare),
        T.TraceEvent(standard_names.GROUP_BUILT, 5, 50.0,
                     group=SimpleNamespace(group_category=bare, objects=[], bond_facet=None,
                                           direction=None)),
        T.TraceEvent(standard_names.GROUP_BUILT, 5, 50.0, flipped=True,
                     group=SimpleNamespace(group_category=bare, objects=[], bond_facet=None,
                                           direction=None)),
    ):
        assert isinstance(D.header(event), str) and isinstance(D.print_name(event), str)
    assert D.header(T.TraceEvent(standard_names.GROUP_BUILT, 5, 50.0, group=SimpleNamespace(
        group_category=bare, objects=[], bond_facet=None, direction=None))) == "Built L1-3"
    group = SimpleNamespace(
        objects=[SimpleNamespace(get_descriptor_for=lambda f: bare)],
        bond_facet=None, direction=None, group_category=bare,
    )
    assert D.group_event_text(group) == "l1-3"
    cm = SimpleNamespace(description_type1=bare, descriptor1=bare, description_type2=bare,
                         descriptor2=short, label=bare, is_identity=False, object1=None)
    assert D.concept_mapping_print_name(cm) == "L1-3=>Odd"
    assert slippage_english_name(cm) == "l1-3 <=> plain"
    assert V.concept_mapping_long_name(cm).startswith("SLIPPAGE")
    assert isinstance(D.cm_ref(cm), dict)
    bond = SimpleNamespace(
        bond_category=bare, direction=None, left_object=_letter(bare, 0),
        right_object=_letter(short, 1),
        string=SimpleNamespace(string_type="initial", translated=False), proposal_level="built",
    )
    assert "l1-3:0" in V._bond_text(bond, None)
    assert V.ascii_name(_letter(bare, 0)) == "l1-3:0"
    st = _string("abc")
    assert snag_object_phrase(st, _TEMPLATES)
    assert explain_failure(("SWAP", [st], bare), _TEMPLATES) is not None
    assert explain_failure(("CHANGE", st, (bare, None, short)), _TEMPLATES) is not None
    assert isinstance(V.theme_ascii_name(
        SimpleNamespace(dimension="L1-3", relation="identity"), SimpleNamespace(nodes={"L1-3": bare})), str)


# --- G9: the roles EN5a's files read, unbound or with the node removed --------------------

import pytest  # noqa: E402

from tests.support import golden_baseline as gb  # noqa: E402
from tests.support import reduced_configurations as rc  # noqa: E402
from tests.support.role_table import SINGLE_ROLES  # noqa: E402

from server.engine.numeric.backend import use_backend  # noqa: E402
from server.engine.rng import RNG  # noqa: E402
from server.engine.runner import EngineRunner  # noqa: E402
from tests.support import standard_names

pytestmark = pytest.mark.numeric_matrix

DISPLAY_ROLES = (
    "direction.left", "direction.right", "dimension.letter_category",
    "dimension.bond_category", "dimension.group_category", "group_category.sameness",
    "bond_category.sameness", "position.whole", "position.single",
)


def _run_and_display(provider, problem, steps=400, seed=1):
    runner = EngineRunner(provider)
    with use_backend(gb.BACKEND):
        runner.init_mcat(*problem, seed=seed, rng=RNG(seed))
        for _ in range(steps):
            if runner.step_mcat().codelet_type is None:
                break
    workspace = runner.ctx.workspace
    for event in runner.ctx.trace.events:
        D.print_name(event)
        D.header(event)
    for string in (workspace.initial_string, workspace.modified_string, workspace.target_string):
        if string is None:
            continue
        for obj in list(string.objects) + list(string.groups):
            V.print_text(obj)
            D.group_print_name(obj) if hasattr(obj, "objects") and hasattr(obj, "bond_facet") else None
        for bond in string.bonds:
            V.print_text(bond)
    for bridge in workspace.vertical_bridges:
        V.print_text(bridge)
        D._theme_supporting({}, [bridge], runner.ctx.slipnet)


@pytest.mark.slow
@pytest.mark.parametrize("role", DISPLAY_ROLES)
def test_g9_display_roles_unbound_run_and_display_on_demo_problems(role) -> None:
    provider = rc.provider(rc.role_unbound(role))
    triples, _ = gb.demo_problems()
    for problem in triples:
        _run_and_display(provider, problem)


@pytest.mark.slow
@pytest.mark.parametrize("role", DISPLAY_ROLES)
def test_g9_display_roles_node_removed_run_and_display(role) -> None:
    provider = rc.provider(rc.node_removed(SINGLE_ROLES[role]))
    triples, _ = gb.demo_problems()
    for problem in triples[:4]:
        _run_and_display(provider, problem)
