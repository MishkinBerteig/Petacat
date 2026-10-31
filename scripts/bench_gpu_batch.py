#!/usr/bin/env python3
"""Crossover for presenting K runs' Slipnet updates to the GPU as one dispatch (WP6).

At today's 59-node Slipnet a single numpy update costs about 7 microseconds and a
Metal dispatch about 200.  Batching K runs into one ``[K, N]`` dispatch amortises the
dispatch, so the question is the K at which one batched dispatch beats K separate
numpy updates, and then how much of a whole run that can ever be worth.  This script
measures the first; ``agents-workspace/wp6-gpu-ane/FINDINGS.md`` argues the second.

Rows, per K (milliseconds per *update cycle across all K runs*, best of --repeat):

``numpy_xK``      K separate ``NumpySlipnetSession.update`` calls (what a swarm worker
                  does today if it hosts K runs)
``numpy_batched`` one float64 ``[K, N]`` update on the CPU (a fairer CPU baseline)
``mlx_resident``  one float32 ``[K, N]`` update on the GPU, state already on device
``mlx_roundtrip`` the same plus uploading the K activation/buffer rows and reading the
                  K activation rows back, which is what an engine that keeps its
                  object graph as the authority must pay every cycle

``--json PATH`` writes the table.  Run it from a quiet machine for final numbers.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402


class BatchedSlipnet:
    """K runs sharing one topology, updated as one ``[K, N]`` pass (prototype).

    ``device="gpu"`` is float32 MLX on the default (Metal) stream; ``"numpy"`` is the
    same arithmetic in float64 on the CPU.  The Slipnet update per run is the one in
    ``NumpySlipnetSession.update``: decay, per-edge rounded contribution, destination
    sum, add, clip, clear.  The destination sum is a matmul against a dense 0/1
    ``[E, N]`` incidence matrix, which is exact because the addends are integers.
    """

    def __init__(self, topo, k, device):
        self.device, self.k, self.n = device, k, topo.n_nodes
        self.src = np.asarray(topo.in_source, dtype=np.int32)
        self.dst = np.asarray(topo.in_dest, dtype=np.int32)
        self.w = np.asarray(topo.in_weight, dtype=np.float64)
        self.decay = np.asarray(topo.decay_percent, dtype=np.float64)
        self.maxa = float(topo.activation.max_activation)
        inc = np.zeros((len(self.src), self.n))
        inc[np.arange(len(self.src)), self.dst] = 1.0
        self.inc = inc
        if device == "gpu":
            import mlx.core as mx
            self.mx = mx
            self.g_src, self.g_w = mx.array(self.src), mx.array(self.w.astype(np.float32))
            self.g_decay, self.g_inc = mx.array(self.decay.astype(np.float32)), mx.array(inc.astype(np.float32))
            self._step = mx.compile(self._gpu_step)

    def load(self, act, buf, frozen):
        if self.device == "gpu":
            mx = self.mx
            self.act, self.buf = mx.array(act.astype(np.float32)), mx.array(buf.astype(np.float32))
            self.frozen = mx.array(frozen)
        else:
            self.act, self.buf, self.frozen = act.copy(), buf.copy(), frozen.copy()

    def _gpu_step(self, act, buf, frozen, thr):
        mx = self.mx
        a = mx.take(act, self.g_src, axis=1)
        gate = (a > 0) & (a >= thr)
        contrib = mx.round(self.g_w * a / 100.0) * gate
        sums = contrib @ self.g_inc
        buf = buf - mx.where(frozen, 0.0, mx.round(self.g_decay * act / 100.0))
        buf = buf + mx.where(frozen, 0.0, sums)
        return mx.clip(act + buf, 0.0, self.maxa)

    def update(self, threshold, scale):
        if self.device == "gpu":
            self.act = self._step(self.act, self.buf, self.frozen, threshold)
            return
        a = self.act[:, self.src]
        gate = (a > 0) & (a >= threshold)
        contrib = np.rint(self.w * scale * a / 100.0) * gate
        sums = contrib @ self.inc
        self.buf -= np.where(self.frozen, 0.0, np.rint(self.decay * self.act / 100.0))
        self.buf += np.where(self.frozen, 0.0, sums)
        self.act = np.clip(self.act + self.buf, 0.0, self.maxa)
        self.buf = np.zeros_like(self.buf)

    def sync(self):
        if self.device == "gpu":
            self.mx.eval(self.act)

    def activation_numpy(self):
        if self.device == "gpu":
            return np.array(self.act, dtype=np.float64)
        return self.act


def real_topology():
    from server.engine.metadata import MetadataProvider
    from server.engine.runner import EngineRunner
    from server.engine.numeric.layout import SlipnetTopology

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    meta = MetadataProvider.from_standard_configuration(os.path.join(root, "seed_data"))
    runner = EngineRunner(meta)
    runner.init_mcat("abc", "abd", "mrrjjj", seed=1)
    return SlipnetTopology.from_slipnet(runner.ctx.slipnet)


def random_state(topology, k, rng):
    n = topology.n_nodes
    act = np.rint(rng.uniform(0, 100, (k, n)) * (rng.random((k, n)) < 0.4))
    buf = np.rint(rng.uniform(-5, 20, (k, n)))
    frozen = rng.random((k, n)) < 0.05
    return act, buf, frozen


def best(fn, repeat, inner=1):
    times = []
    for _ in range(repeat):
        t = time.perf_counter()
        for _ in range(inner):
            fn()
        times.append((time.perf_counter() - t) / inner)
    return min(times) * 1000.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ks", default="1,2,4,8,16,32,64,128,256,512,1024")
    ap.add_argument("--repeat", type=int, default=30)
    ap.add_argument("--json")
    args = ap.parse_args()

    import mlx.core as mx
    from server.engine.numeric.numpy_backend import NumpySlipnetSession

    topo = real_topology()
    n, e = topo.n_nodes, topo.n_edges
    rng = np.random.default_rng(7)
    rows = []
    for k in [int(x) for x in args.ks.split(",")]:
        act, buf, frozen = random_state(topo, k, rng)
        sessions = []
        for i in range(k):
            s = NumpySlipnetSession(topo)
            s.activation, s.buffer, s.frozen = act[i].copy(), buf[i].copy(), frozen[i].copy()
            sessions.append(s)

        def numpy_xk():
            for s in sessions:
                s.update(100.0, 1.0)

        batch_np = BatchedSlipnet(topo, k, device="numpy")
        batch_np.load(act, buf, frozen)
        batch_gpu = BatchedSlipnet(topo, k, device="gpu")
        batch_gpu.load(act, buf, frozen)

        def mlx_resident():
            batch_gpu.update(100.0, 1.0)
            batch_gpu.sync()

        def mlx_roundtrip():
            batch_gpu.load(act, buf, frozen)
            batch_gpu.update(100.0, 1.0)
            batch_gpu.activation_numpy()

        for f in (numpy_xk, lambda: batch_np.update(100.0, 1.0), mlx_resident, mlx_roundtrip):
            for _ in range(3):
                f()
        row = {
            "k": k, "nodes": n, "edges": e,
            "numpy_xK_ms": best(numpy_xk, args.repeat),
            "numpy_batched_ms": best(lambda: batch_np.update(100.0, 1.0), args.repeat),
            "mlx_resident_ms": best(mlx_resident, args.repeat),
            "mlx_roundtrip_ms": best(mlx_roundtrip, args.repeat),
        }
        # Equivalence: one float64 update vs the float32 GPU update, from the same state.
        batch_gpu.load(act, buf, frozen)
        batch_gpu.update(100.0, 1.0)
        got = batch_gpu.activation_numpy()
        ref_sessions = []
        for i in range(k):
            s = NumpySlipnetSession(topo)
            s.activation, s.buffer, s.frozen = act[i].copy(), buf[i].copy(), frozen[i].copy()
            s.update(100.0, 1.0)
            ref_sessions.append(s.activation)
        ref = np.stack(ref_sessions)
        row["max_abs_diff"] = float(np.abs(got - ref).max())
        row["mismatched_cells"] = int((got != ref).sum())
        rows.append(row)
        print(json.dumps({k_: (round(v, 4) if isinstance(v, float) else v) for k_, v in row.items()}), flush=True)
    if args.json:
        with open(args.json, "w") as fh:
            json.dump(rows, fh, indent=1)


if __name__ == "__main__":
    main()
