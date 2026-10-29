"""Seed data that exists only so a display can match Metacat's.

- every demo Metacat's ``demos.ss`` defines is in ``demo_problems.json``;
- the Themespace's dimension and relation names (``theme-graphics.ss:740-771``).
"""

import json
import os
import re

import pytest

from server.engine.metadata import MetadataProvider
from server.engine.serialization import theme_display_labels

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SEED_DIR = os.path.join(ROOT, "seed_data")
DEMOS_SS = os.path.join(ROOT, "Metacat", "build", "source", "demos.ss")


@pytest.fixture(scope="module")
def meta():
    return MetadataProvider.from_seed_data(SEED_DIR)


def _metacat_demos():
    """(name, initial, modified, target, answer-or-None, seed) for each live define."""
    text = open(DEMOS_SS).read()
    live = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith(";"))
    out = []
    for m in re.finditer(r"\(define ([\w.\-]+) '\(([^)]*)\)\)", live):
        parts = m.group(2).split()
        if len(parts) == 4:
            out.append((m.group(1), parts[0], parts[1], parts[2], None, int(parts[3])))
        elif len(parts) == 5:
            out.append((m.group(1), *parts[:4], int(parts[4])))
    return out


@pytest.mark.skipif(not os.path.exists(DEMOS_SS), reason="Metacat source not present")
def test_every_metacat_demo_is_in_the_seed_data():
    seeded = {d["name"]: d for d in json.load(open(os.path.join(SEED_DIR, "demo_problems.json")))}
    demos = _metacat_demos()
    assert len(demos) >= 35
    for name, initial, modified, target, answer, seed in demos:
        assert name in seeded, f"{name} is a Metacat demo but is not seeded"
        d = seeded[name]
        assert (d["initial"], d["modified"], d["target"], d["answer"], d["seed"]) == (
            initial, modified, target, answer, seed,
        ), name


def test_fig_5_5_top_shares_fig_5_4_tops_strings_and_seed(meta):
    by_name = {d.name: d for d in meta.demo_problems}
    a, b = by_name["fig5.4-top"], by_name["fig5.5-top"]
    assert (a.initial, a.modified, a.target, a.seed) == (b.initial, b.modified, b.target, b.seed)


def test_dimension_names_are_metacats(meta):
    labels = theme_display_labels(meta)["dimension_labels"]
    assert labels["plato-letter-category"] == {"name": "Letter Category", "abbreviation": "Letter Ctgy."}
    assert labels["plato-alphabetic-position-category"] == {
        "name": "Alphabetic Position", "abbreviation": "Alpha. Pos.",
    }
    assert labels["plato-string-position-category"] == {
        "name": "String Position", "abbreviation": "String Pos.",
    }
    assert labels["plato-direction-category"]["name"] == "Direction"
    assert labels["plato-object-category"]["name"] == "Object Type"
    assert labels["plato-group-category"]["name"] == "Group Type"
    assert labels["plato-bond-category"]["name"] == "Bond Type"
    assert labels["plato-bond-facet"]["name"] == "Bond Facet"


def test_a_dimension_without_a_name_falls_back_to_its_short_name(meta):
    labels = theme_display_labels(meta)["dimension_labels"]
    short = meta.slipnet_node_specs["plato-length"].short_name
    assert labels["plato-length"] == {"name": short, "abbreviation": short}


def test_relation_names_are_metacats(meta):
    assert theme_display_labels(meta)["relation_labels"] == {
        "identity": "iden", "opposite": "opp", "successor": "succ",
        "predecessor": "pred", "diff": "diff",
    }
