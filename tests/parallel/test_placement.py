"""Defends the WP6 placement policy: executors get a CPU backend, never the engine's
``auto`` (which means the GPU at every size and ran 4.9x slower than ``off`` when measured)."""
from __future__ import annotations

import pytest

from server.parallel import placement as p

ENVS = (
    p.ENV_SWARM_BACKEND, p.ENV_SPECULATIVE_BACKEND, p.ENV_GPU_PLACEMENT,
    p.ENV_GPU_MIN_NODES, p.ENV_GPU_DISPATCH_US, p.ENV_NUMERIC_BACKEND,
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ENVS:
        monkeypatch.delenv(name, raising=False)


def test_today_slipnet_gets_off_in_swarm_and_speculative():
    assert p.swarm_backend(59) == "off"
    assert p.speculative_backend(59, workers=16) == "off"
    assert p.swarm_backend() == "off"


def test_larger_slipnet_vectorises_on_the_cpu_but_never_picks_the_gpu():
    assert p.swarm_backend(p.VECTORISE_MIN_NODES) == "numpy"
    assert p.swarm_backend(1_000_000) == "numpy"
    assert p.speculative_backend(1_000_000) == "numpy"


def test_explicit_env_overrides(monkeypatch):
    monkeypatch.setenv(p.ENV_SWARM_BACKEND, "MLX")
    assert p.swarm_backend(59) == "mlx"
    monkeypatch.setenv(p.ENV_SPECULATIVE_BACKEND, "python")
    assert p.speculative_backend(59) == "python"


def test_garbage_override_is_ignored(monkeypatch):
    monkeypatch.setenv(p.ENV_SWARM_BACKEND, "cuda")
    assert p.swarm_backend(59) == "off"


def test_pinned_engine_backend_is_honoured_but_mlx_is_demoted_for_threads(monkeypatch):
    monkeypatch.setenv(p.ENV_NUMERIC_BACKEND, "mlx")
    assert p.swarm_backend(59) == "mlx"
    assert p.speculative_backend(59) == "numpy"
    monkeypatch.setenv(p.ENV_NUMERIC_BACKEND, "auto")  # auto is not a pin
    assert p.swarm_backend(59) == "off"


def test_thread_safety_flags_mlx_only():
    assert p.thread_safe("numpy") and p.thread_safe("off") and p.thread_safe("python")
    assert not p.thread_safe("mlx") and not p.thread_safe("mlx-cpu")


def test_gpu_not_worthwhile_at_59_nodes_even_batched(monkeypatch):
    monkeypatch.setattr(p, "_mlx_installed", lambda: True)
    assert not p.gpu_worthwhile(59)
    assert not p.gpu_worthwhile(59, batch=1024)  # no batched executor exists


def test_gpu_worthwhile_at_scale_single_user_only(monkeypatch):
    monkeypatch.setattr(p, "_mlx_installed", lambda: True)
    assert p.gpu_worthwhile(300_000)
    assert not p.gpu_worthwhile(300_000, threaded=True)
    # Many processes queueing on the one device erode the win.
    assert not p.gpu_worthwhile(40_000, concurrent_gpu_users=16)


def test_batching_counts_once_a_batched_executor_exists(monkeypatch):
    monkeypatch.setattr(p, "_mlx_installed", lambda: True)
    monkeypatch.setattr(p, "_batching_implemented", lambda: True)
    assert p.gpu_worthwhile(59, batch=4096)
    assert not p.gpu_worthwhile(59, batch=8)


def test_gpu_placement_switch_and_missing_mlx(monkeypatch):
    monkeypatch.setattr(p, "_mlx_installed", lambda: False)
    assert not p.gpu_worthwhile(1_000_000)
    monkeypatch.setenv(p.ENV_GPU_PLACEMENT, "on")
    assert p.gpu_worthwhile(1)
    monkeypatch.setenv(p.ENV_GPU_PLACEMENT, "off")
    monkeypatch.setattr(p, "_mlx_installed", lambda: True)
    assert not p.gpu_worthwhile(1_000_000)


def test_min_nodes_env_moves_the_threshold(monkeypatch):
    monkeypatch.setattr(p, "_mlx_installed", lambda: True)
    monkeypatch.setenv(p.ENV_GPU_MIN_NODES, "1000000")
    assert not p.gpu_worthwhile(300_000)


def test_worker_environment_is_explicit_and_validated():
    assert p.worker_environment("off") == {p.ENV_NUMERIC_BACKEND: "off"}
    with pytest.raises(ValueError):
        p.worker_environment("auto")


def test_start_method_never_fork_and_describe_is_plain():
    assert p.start_method("off") in {"forkserver", "spawn"}
    d = p.describe(59)
    assert d["swarm_backend"] == "off" and d["start_method"] != "fork"
