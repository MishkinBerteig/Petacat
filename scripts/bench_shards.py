#!/usr/bin/env python3
"""Compare the three candidate sharded coderacks (WP4.3).

The Coderack is the hardest single problem in Phase 0: it is at once the largest serial
fraction of the runtime and the most contended structure in the engine.  The plan lists
three candidate decompositions and does not choose between them, so this measures them
on the two axes that actually decide it.

**Fidelity.** Selection is a two-stage urgency-weighted draw, and that distribution is
how temperature regulates exploration — nearly random when hot, greedy when cold.  A
decomposition that distorts it does not make the engine faster, it makes it a different
engine.  So the first measurement is the selection distribution against the unsharded
rack: same codelets posted, same temperature, same number of draws, compared as a
frequency distribution over codelet types and over urgency bins.

**Contention.** The second is what it costs under threads: contended lock acquisitions,
steals, throughput, and how evenly the shards fill.

Neither axis decides alone.  Perfect fidelity with heavy contention is the locked rack,
which is the control; low contention with a distorted distribution is not worth having at
any speed.

    python3 scripts/bench_shards.py [--shards N] [--workers N] [--draws N] [--json PATH]
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import threading
import time
from collections import Counter

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from server.engine.coderack import Codelet, Coderack  # noqa: E402
from server.engine.coderack_shards import build_candidate  # noqa: E402
from server.engine.metadata import MetadataProvider  # noqa: E402
from server.engine.rng import RNG  # noqa: E402

SEED_DIR = os.path.join(REPO, "seed_data")

#: A codelet mix resembling a real rack: the urgency levels the engine actually posts at,
#: and the type spread a mid-run rack carries.  Taken from the posting passes in
#: ``runner.py`` rather than invented, because the fidelity question is entirely about how
#: a real mix distributes.
MIX = [
    ("bottom-up-bond-scout", 20),
    ("bottom-up-bridge-scout", 20),
    ("bottom-up-description-scout", 20),
    ("group-scout:whole-string", 20),
    ("important-object-bridge-scout", 20),
    ("rule-scout", 20),
    ("bond-evaluator", 45),
    ("bridge-evaluator", 45),
    ("group-evaluator", 45),
    ("rule-evaluator", 60),
    ("thematic-bridge-scout", 60),
    ("progress-watcher", 35),
    ("jootser", 35),
    ("breaker", 5),
    ("answer-finder", 85),
]

TEMPERATURES = (100.0, 70.0, 40.0, 10.0)


def _fill(rack, count: int, rng: RNG, current_time: int = 500) -> None:
    """Post a realistic mix, without eviction skewing the comparison.

    ``max_size`` is raised for the duration: eviction is itself stochastic, and letting it
    fire would mix its distribution into the selection distribution being measured. What
    is under test here is *selection*.
    """
    for index in range(count):
        codelet_type, urgency = MIX[index % len(MIX)]
        rack.post(
            Codelet(codelet_type, urgency, time_stamp=index % current_time),
            current_time,
            rng,
        )


def _spread_fill(rack, count: int, rng: RNG, current_time: int = 500) -> None:
    """Populate a sharded rack as several workers would have, then draw serially.

    Needed because the worker-sharded candidate is *deliberately* thread-affine: a single
    thread posts everything to its own shard, so a single-threaded fidelity measurement
    degenerates to one rack and scores a perfect 0.000 while testing nothing.  That
    degeneration is the right behaviour — serially it should be the unsharded rack — but
    the fidelity question only arises once shards are genuinely populated.

    So posting is done directly into shards, round-robin, reproducing the steady state
    under free-running, and the draw is then measured against the unsharded rack.
    """
    shards = getattr(rack, "num_shards", 1)
    if shards <= 1:
        _fill(rack, count, rng, current_time)
        return

    # Filled by real threads, through the candidate's own ``post``.
    #
    # An earlier version placed codelets into shards round-robin directly, and that was
    # wrong in a way that flattered one candidate: it bypassed each candidate's *own*
    # placement, so family sharding was measured on round-robin placement — erasing the
    # very property that defines it — and duly scored the same as worker sharding.  Using
    # real threads lets each candidate place codelets the way it actually would: family by
    # codelet type regardless of thread, worker by the posting thread.
    per_thread = max(1, count // shards)

    def poster(offset: int) -> None:
        local = RNG(7000 + offset)
        for step in range(per_thread):
            index = offset * per_thread + step
            codelet_type, urgency = MIX[index % len(MIX)]
            rack.post(
                Codelet(codelet_type, urgency, time_stamp=index % current_time),
                current_time,
                local,
            )

    threads = [threading.Thread(target=poster, args=(i,)) for i in range(shards)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


def _raise_capacity(rack) -> None:
    for attr in ("_racks",):
        for inner in getattr(rack, attr, []) or []:
            inner.max_size = 10_000
    inner = getattr(rack, "_rack", None)
    if inner is not None:
        inner.max_size = 10_000


def measure_fidelity(meta, name: str, shards: int, draws: int) -> dict:
    """Selection frequencies against the unsharded rack, per temperature.

    Total-variation distance is the summary: half the sum of absolute differences between
    the two frequency distributions, so 0.0 is identical and 1.0 is disjoint. It is the
    right summary here because it is bounded and interpretable — a TV distance of 0.02
    means the two racks disagree about where 2% of draws go.
    """
    # Draw only a *fraction* of a full rack, and never refill mid-trial.
    #
    # The first version of this drained the rack and topped it up, and every candidate
    # scored a perfect 0.000 — which was the measurement being wrong, not the candidates
    # being right.  Draining a rack means eventually drawing *everything* in it, so the
    # observed frequencies converge on the posted mix no matter what order selection
    # chose.  Selection preference is only visible while there is something left
    # unchosen, so each trial fills a realistic rack and takes the first 10% of it.
    population, take = 400, 40
    trials = max(1, draws // take)
    binner = Coderack(meta)._urgency_to_bin

    per_temperature = {}
    for temperature in TEMPERATURES:
        reference, reference_bins = Counter(), Counter()
        observed, observed_bins = Counter(), Counter()

        for trial in range(trials):
            rack = Coderack(meta)
            rack.max_size = 10_000
            rng = RNG(1234 + trial)
            rack.rng = rng
            _fill(rack, population, rng)
            for _ in range(take):
                codelet = rack.choose_and_remove(temperature, rng)
                if codelet is None:
                    break
                reference[codelet.codelet_type] += 1
                reference_bins[binner(codelet.urgency)] += 1

            candidate = build_candidate(name, meta, shards)
            _raise_capacity(candidate)
            rng2 = RNG(1234 + trial)
            candidate.rng = rng2
            _spread_fill(candidate, population, rng2)
            # Drawn from the main thread, which has posted nothing, so the
            # occupancy-weighted path is used rather than one shard's affinity — the
            # arrangement a serial reader of a rack filled by workers actually sees.
            for _ in range(take):
                codelet = candidate.choose_and_remove(temperature, rng2)
                if codelet is None:
                    break
                observed[codelet.codelet_type] += 1
                observed_bins[binner(codelet.urgency)] += 1

        per_temperature[temperature] = {
            "type_tv_distance": _tv(reference, observed),
            "bin_tv_distance": _tv(reference_bins, observed_bins),
        }
    return per_temperature


def _tv(a: Counter, b: Counter) -> float:
    total_a, total_b = sum(a.values()), sum(b.values())
    if not total_a or not total_b:
        return 1.0
    keys = set(a) | set(b)
    return round(
        0.5 * sum(abs(a[k] / total_a - b[k] / total_b) for k in keys), 5
    )


def measure_contention(meta, name: str, shards: int, workers: int, draws: int) -> dict:
    """Throughput and contention with ``workers`` threads posting and drawing."""
    candidate = build_candidate(name, meta, shards)
    _raise_capacity(candidate)
    rng = RNG(99)
    candidate.rng = rng
    _fill(candidate, 200 * workers, rng)

    per_worker = max(1, draws // workers)
    drawn = [0] * workers
    barrier = threading.Barrier(workers)

    def worker(index: int) -> None:
        local = RNG(1000 + index)
        barrier.wait()
        for step in range(per_worker):
            codelet = candidate.choose_and_remove(50.0, local)
            if codelet is None:
                candidate.post(Codelet("bottom-up-bond-scout", 20, time_stamp=step), 500, local)
                continue
            drawn[index] += 1
            # Post as codelets do, so the measurement includes both directions of
            # contention rather than only selection.
            if step % 3 == 0:
                candidate.post(
                    Codelet("bond-evaluator", 45, time_stamp=step), 500, local
                )

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(workers)]
    started = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.perf_counter() - started

    total = sum(drawn)
    occupancy = candidate.occupancy() if hasattr(candidate, "occupancy") else [candidate.total_count]
    return {
        "workers": workers,
        "draws": total,
        "seconds": round(elapsed, 4),
        "draws_per_second": round(total / elapsed) if elapsed else 0,
        "contended_acquisitions": candidate.contended_acquisitions,
        "contention_rate": round(candidate.contended_acquisitions / max(1, total), 4),
        "steals": candidate.steals,
        "shard_occupancy": occupancy,
        # Coefficient of variation across shards: 0 is perfectly balanced. A candidate
        # that keeps one shard hot has not really decomposed anything.
        "occupancy_cv": round(
            statistics.pstdev(occupancy) / statistics.mean(occupancy), 4
        ) if len(occupancy) > 1 and statistics.mean(occupancy) else 0.0,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--shards", type=int, default=4)
    ap.add_argument("--workers", default="1,2,4,8")
    ap.add_argument("--draws", type=int, default=20000)
    ap.add_argument("--json", dest="json_path", default=None)
    args = ap.parse_args()

    worker_counts = [int(w) for w in args.workers.split(",")]
    meta = MetadataProvider.from_seed_data(SEED_DIR)
    names = ["locked", "family", "worker"]

    print(
        f"Coderack sharding comparison — {args.shards} shards, "
        f"{args.draws:,} draws, workers {worker_counts}\n"
    )

    results: dict = {"shards": args.shards, "draws": args.draws, "candidates": {}}

    print("1. Selection fidelity — total-variation distance from the unsharded rack")
    print("   (0.000 = identical distribution; by codelet type / by urgency bin)\n")
    header = "   candidate    " + "".join(f"{f'T={t:g}':>18}" for t in TEMPERATURES)
    print(header)
    for name in names:
        fidelity = measure_fidelity(meta, name, args.shards, min(args.draws, 20000))
        results["candidates"].setdefault(name, {})["fidelity"] = {
            str(k): v for k, v in fidelity.items()
        }
        cells = "".join(
            f"{fidelity[t]['type_tv_distance']:>8.3f}/{fidelity[t]['bin_tv_distance']:<9.3f}"
            for t in TEMPERATURES
        )
        print(f"   {name:<13}{cells}")

    print("\n2. Contention and throughput under threads\n")
    print("   candidate    workers    draws/s   contention   steals   occupancy CV")
    for name in names:
        results["candidates"][name]["contention"] = []
        for workers in worker_counts:
            row = measure_contention(meta, name, args.shards, workers, args.draws)
            results["candidates"][name]["contention"].append(row)
            print(
                f"   {name:<13}{row['workers']:>7}{row['draws_per_second']:>11,}"
                f"{row['contention_rate']:>13.4f}{row['steals']:>9}"
                f"{row['occupancy_cv']:>15.3f}"
            )

    print(
        "\n   Fidelity is the veto: a candidate that distorts the selection distribution\n"
        "   is not a faster engine, it is a different one. Contention decides between\n"
        "   the candidates that pass."
    )

    if args.json_path:
        os.makedirs(os.path.dirname(os.path.abspath(args.json_path)), exist_ok=True)
        with open(args.json_path, "w") as fh:
            json.dump(results, fh, indent=2)
            fh.write("\n")
        print(f"\n   Wrote {args.json_path}")


if __name__ == "__main__":
    main()
