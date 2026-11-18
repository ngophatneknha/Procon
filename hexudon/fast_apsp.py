"""ctypes wrapper for the C++20 Spot-Aware APSP accelerator (`hexudon_fast.dll`)."""

from __future__ import annotations
import ctypes
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .models import MapConfig, RoadState, TerrainType

_DLL_PATH = Path(__file__).resolve().parent / "hexudon_fast.dll"
_LIB: Optional[ctypes.CDLL] = None

try:
    if _DLL_PATH.exists():
        _LIB = ctypes.CDLL(str(_DLL_PATH))
        _LIB.compute_apsp_cpp.argtypes = [
            ctypes.c_int32,
            ctypes.c_int32,
            ctypes.POINTER(ctypes.c_int32),
            ctypes.POINTER(ctypes.c_int32),
            ctypes.POINTER(ctypes.c_int32),
            ctypes.c_int32,
            ctypes.POINTER(ctypes.c_int32),
            ctypes.POINTER(ctypes.c_int32),
            ctypes.POINTER(ctypes.c_int32),
        ]
        _LIB.compute_apsp_cpp.restype = None
except Exception:
    _LIB = None

_TERRAIN_TO_INT = {
    TerrainType.PLAIN: 0,
    TerrainType.MOUNTAIN: 1,
    TerrainType.POND: 2,
    TerrainType.ROAD: 3,
}

_MODE_TO_INT = {
    "steps": 0,
    "fuel": 1,
    "balanced": 2,
    "fuel_heavy": 3,
}

_GLOBAL_APSP_CACHE: Dict[Tuple, Tuple[List[List[int]], List[List[int]], List[List[int]]]] = {}


def has_cpp_accelerator() -> bool:
    return _LIB is not None


def compute_apsp_fast(
    config: MapConfig,
    road_states: Dict[int, RoadState],
    mode: str = "steps",
) -> Optional[Tuple[List[List[int]], List[List[int]], List[List[int]]]]:
    """
    Call the native C++20 Spot-Aware APSP engine if available; returns None if DLL is not loaded.
    Automatically breaks shortest-path ties in favor of paths passing through the most Udon Spots!
    """
    if _LIB is None:
        return None

    cache_key = (
        config.width,
        config.height,
        id(config.terrains),
        tuple(sorted(road_states.items())),
        mode,
    )
    if cache_key in _GLOBAL_APSP_CACHE:
        return _GLOBAL_APSP_CACHE[cache_key]

    n = config.num_cells
    n2 = n * n

    IntArrayN = ctypes.c_int32 * n
    IntArrayN2 = ctypes.c_int32 * n2

    c_terrains = IntArrayN(*(_TERRAIN_TO_INT[t] for t in config.terrains))
    c_road_states = IntArrayN(*(int(road_states.get(u, RoadState.SMOOTH)) for u in range(n)))
    c_is_spot = IntArrayN(*(1 if u in config.spots else 0 for u in range(n)))
    c_mode = ctypes.c_int32(_MODE_TO_INT.get(mode, 0))

    out_steps = IntArrayN2()
    out_fuel = IntArrayN2()
    out_parent = IntArrayN2()

    _LIB.compute_apsp_cpp(
        ctypes.c_int32(config.width),
        ctypes.c_int32(config.height),
        c_terrains,
        c_road_states,
        c_is_spot,
        c_mode,
        out_steps,
        out_fuel,
        out_parent,
    )

    # Slice directly from ctypes buffer into row lists (avoids intermediate 1M-element list copy)
    mat_s = [out_steps[i * n : (i + 1) * n] for i in range(n)]
    mat_f = [out_fuel[i * n : (i + 1) * n] for i in range(n)]
    mat_p = [out_parent[i * n : (i + 1) * n] for i in range(n)]

    res = (mat_s, mat_f, mat_p)
    if len(_GLOBAL_APSP_CACHE) > 64:
        _GLOBAL_APSP_CACHE.clear()
    _GLOBAL_APSP_CACHE[cache_key] = res
    return res
