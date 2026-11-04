"""Hand-built Themespace fixtures.

A run's Themespace holds just the themes something has touched, so the engine never creates every
possible theme.  Tests that need the whole set build it here.
"""

from __future__ import annotations

from typing import TypeVar

from server.engine.themes import Themespace, ThemeCluster

T = TypeVar("T", ThemeCluster, Themespace)


def populate(target: T) -> T:
    """Create every possible theme of a cluster, or of every cluster of a Themespace, in ``valid_relations`` order."""
    if isinstance(target, ThemeCluster):
        for relation in reversed(target.valid_relations):
            target.add_theme(relation)
    else:
        for cluster in target.clusters:
            for relation in reversed(cluster.valid_relations):
                target.add_theme(cluster.theme_type, cluster.dimension, relation, False)
    return target
