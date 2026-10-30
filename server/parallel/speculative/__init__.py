"""Within-run parallelism that is exact: a speculative executor (WP3).

``run_stream_serial`` is the reference: the faithful loop with keyed random streams
and an exponential-race coderack.  ``SpeculativeEngine`` runs the *same* run across
threads and is bit-identical to it for every worker count.  See the module docstrings
of :mod:`.streams`, :mod:`.clock_rack`, :mod:`.reference` and :mod:`.engine`.
"""
