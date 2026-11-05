"""The Metacat Standard Configuration as a ``MetadataProvider``, loaded once, for test doubles.

An engine object reads every number it uses from the configuration it was built with, so a test
double that stands in for a Themespace or a Slipnet carries one (``.meta``, ``.activation_params``)
instead of the engine holding a code default for it.
"""

from __future__ import annotations

import functools
from pathlib import Path

from server.engine.metadata import MetadataProvider
from server.engine.numeric.layout import ActivationParams

SEED_DIR = Path(__file__).resolve().parents[2] / "seed_data"


@functools.lru_cache(maxsize=1)
def standard_meta() -> MetadataProvider:
    return MetadataProvider.from_standard_configuration(str(SEED_DIR))


@functools.lru_cache(maxsize=1)
def standard_activation() -> ActivationParams:
    return ActivationParams.from_metadata(standard_meta())


def make_node(name: str, short_name: str, conceptual_depth: int, activation_params: ActivationParams | None = None):
    """A ``SlipnetNode`` built the way ``Slipnet.from_metadata`` builds one: with the activation
    constants of a configuration (the Metacat Standard Configuration unless one is given)."""
    from server.engine.slipnet import SlipnetNode

    return SlipnetNode(name, short_name, conceptual_depth, activation_params or standard_activation())


def bare_slipnet(meta: MetadataProvider | None = None):
    """A ``Slipnet`` with no nodes, carrying a configuration's activation constants and cycle length."""
    from server.engine.slipnet import Slipnet

    meta = meta or standard_meta()
    return Slipnet(ActivationParams.from_metadata(meta), int(meta.get_param("update_cycle_length")))


def synthetic(n_nodes: int, seed: int = 0, **kwargs):
    """``synthetic_topology`` under the Metacat Standard Configuration's activation constants."""
    from server.engine.numeric.synthetic import synthetic_topology

    return synthetic_topology(
        n_nodes, standard_activation(), int(standard_meta().get_param("update_cycle_length")),
        seed=seed, **kwargs,
    )
