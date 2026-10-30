"""macOS quality-of-service classes, and a description of the core tiers.

Apple silicon has no thread affinity: a thread cannot be pinned to a core.  What the
kernel does offer is a *quality-of-service class* per thread, and the scheduler maps
the class onto the core clusters.  ``BACKGROUND`` work is confined to the efficiency
cores; ``USER_INITIATED`` and ``USER_INTERACTIVE`` are free to run on the performance
cores (on an M5 Max, both the 6 "Super" and the 12 "Performance" cores).  That is the
only placement lever the plugin has, so it lives in one small module.

Everything here is **best effort and harmless**.  On a platform without libSystem's
``pthread_set_qos_class_self_np`` the calls are no-ops, a failing call is swallowed,
and every function says what happened (a :class:`QosResult`) rather than raising, so a
worker that cannot be placed still runs, merely unplaced.  QoS changes where and when a
thread runs, never what it computes: the swarm's runs are byte-identical with or
without it (``tests/parallel/test_swarm.py`` holds that).
"""

from __future__ import annotations

import ctypes
import ctypes.util
import sys
from dataclasses import dataclass, field
from typing import Any

#: ``qos_class_t`` values from ``<sys/qos.h>``.
USER_INTERACTIVE = 0x21
USER_INITIATED = 0x19
UTILITY = 0x11
BACKGROUND = 0x09

QOS_NAMES = {
    USER_INTERACTIVE: "USER_INTERACTIVE",
    USER_INITIATED: "USER_INITIATED",
    UTILITY: "UTILITY",
    BACKGROUND: "BACKGROUND",
}


@dataclass(frozen=True)
class QosResult:
    """What a QoS call did.  ``applied`` is False on non-macOS or on failure."""

    applied: bool
    qos: int
    name: str
    detail: str = ""


_LIB: Any = None
_LIB_TRIED = False


def _libsystem() -> Any:
    """libSystem, or ``None`` off macOS / when it cannot be opened."""
    global _LIB, _LIB_TRIED
    if _LIB_TRIED:
        return _LIB
    _LIB_TRIED = True
    if sys.platform != "darwin":
        return None
    try:
        lib = ctypes.CDLL(ctypes.util.find_library("System") or "libSystem.dylib")
        lib.pthread_set_qos_class_self_np.argtypes = [ctypes.c_uint, ctypes.c_int]
        lib.pthread_set_qos_class_self_np.restype = ctypes.c_int
        _LIB = lib
    except (OSError, AttributeError):
        _LIB = None
    return _LIB


def available() -> bool:
    """Whether QoS classes can be set in this process."""
    return _libsystem() is not None


def set_thread_qos(qos: int = USER_INITIATED, relative_priority: int = 0) -> QosResult:
    """Set the calling thread's QoS class.  Never raises."""
    name = QOS_NAMES.get(qos, hex(qos))
    lib = _libsystem()
    if lib is None:
        return QosResult(False, qos, name, f"no QoS on {sys.platform}")
    try:
        rc = int(lib.pthread_set_qos_class_self_np(qos, relative_priority))
    except Exception as exc:  # noqa: BLE001 - a placement hint must never break a run
        return QosResult(False, qos, name, f"{type(exc).__name__}: {exc}")
    if rc != 0:
        return QosResult(False, qos, name, f"pthread_set_qos_class_self_np returned {rc}")
    return QosResult(True, qos, name)


def current_thread_qos() -> int | None:
    """The calling thread's QoS class, or ``None`` when it cannot be read."""
    lib = _libsystem()
    if lib is None:
        return None
    try:
        qos = ctypes.c_uint(0)
        prio = ctypes.c_int(0)
        lib.pthread_get_qos_class_np.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_int)
        ]
        lib.pthread_get_qos_class_np.restype = ctypes.c_int
        lib.pthread_self.restype = ctypes.c_void_p
        if lib.pthread_get_qos_class_np(lib.pthread_self(), ctypes.byref(qos), ctypes.byref(prio)) != 0:
            return None
        return int(qos.value)
    except Exception:  # noqa: BLE001
        return None


def set_worker_qos() -> QosResult:
    """The swarm worker's placement: ``USER_INITIATED``, off the efficiency-only tier."""
    return set_thread_qos(USER_INITIATED)


@dataclass
class CoreTier:
    """One ``hw.perflevelN`` cluster."""

    level: int
    name: str
    logical_cpus: int


@dataclass
class CoreTiers:
    tiers: list[CoreTier] = field(default_factory=list)
    logical_cores: int = 0
    probe: str = ""

    def as_dict(self) -> dict:
        return {
            "logical_cores": self.logical_cores,
            "probe": self.probe,
            "tiers": [
                {"level": t.level, "name": t.name, "logical_cpus": t.logical_cpus}
                for t in self.tiers
            ],
        }


def describe_core_tiers() -> CoreTiers:
    """The machine's core tiers by ``hw.perflevelN`` (level 0 is the fastest).

    An M5 Max reports ``Super`` (6) and ``Performance`` (12); an M1 Ultra ``Performance``
    (16) and ``Efficiency`` (4).  A host that reports no levels yields one anonymous
    tier covering every logical core, so callers never branch on ``None``.
    """
    from server.engine import hardware

    cpu = hardware.cpu_info()
    values = hardware._sysctl("hw.nperflevels")  # noqa: SLF001 - the one sysctl reader
    levels = hardware._as_int(values.get("hw.nperflevels")) or 0  # noqa: SLF001
    if levels < 1:
        return CoreTiers(
            [CoreTier(0, "all", cpu.logical_cores)], cpu.logical_cores, "single tier"
        )
    keys: list[str] = []
    for level in range(levels):
        keys += [f"hw.perflevel{level}.name", f"hw.perflevel{level}.logicalcpu"]
    got = hardware._sysctl(*keys)  # noqa: SLF001
    tiers = [
        CoreTier(
            level,
            got.get(f"hw.perflevel{level}.name", f"level{level}"),
            hardware._as_int(got.get(f"hw.perflevel{level}.logicalcpu")) or 0,  # noqa: SLF001
        )
        for level in range(levels)
    ]
    return CoreTiers(tiers, cpu.logical_cores, "sysctl hw.perflevel")
