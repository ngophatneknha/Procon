"""Official HEXUDON JSON formats (KOSEN schema.pdf) <-> internal models.

Terrain codes: 0 Plain, 1 Road, 2 Mountain, 3 Pond. Agent kind: 0 Patrol, 1 Refuel.
Road status: 0 Smooth, 1 Congested, 2 Jam. Actions per agent: ints, 0..5 = move direction
(0 upper-left, 1 upper-right, then clockwise: 2 right, 3 lower-right, 4 lower-left, 5 left),
<= -1 = wait that many steps.
"""

from __future__ import annotations
from typing import Dict, List, Optional, Set, Tuple

from .models import (
    Action, ActionType, AgentRole, AgentState, DayInput, MapConfig, RoadState, Spot, TerrainType,
)

_TERRAIN = {0: TerrainType.PLAIN, 1: TerrainType.ROAD, 2: TerrainType.MOUNTAIN, 3: TerrainType.POND}

# (dr, dc) for directions 0..5 on even-r layout (even rows are shifted right by half a cell)
_DIRS_EVEN = [(-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (0, -1)]
_DIRS_ODD = [(-1, -1), (-1, 0), (0, 1), (1, 0), (1, -1), (0, -1)]


def neighbor(width: int, height: int, cell: int, direction: int) -> Optional[int]:
    r, c = divmod(cell, width)
    dr, dc = (_DIRS_EVEN if r % 2 == 0 else _DIRS_ODD)[direction]
    nr, nc = r + dr, c + dc
    if 0 <= nr < height and 0 <= nc < width:
        return nr * width + nc
    return None


def direction_of(width: int, height: int, u: int, v: int) -> int:
    for d in range(6):
        if neighbor(width, height, u, d) == v:
            return d
    raise ValueError(f"cells {u} and {v} are not adjacent")


def config_from_official(raw: dict) -> Tuple[MapConfig, List[float]]:
    """Map configuration JSON -> (MapConfig, daySeconds)."""
    h, w = int(raw["map"]["height"]), int(raw["map"]["width"])
    terrains = [_TERRAIN[int(code)] for row in raw["map"]["cells"] for code in row]
    if len(terrains) != h * w:
        raise ValueError("cells do not match height*width")
    spots = {
        int(s["pos"]): Spot(cell_id=int(s["pos"]), chain_id=int(s["brand"]), max_stock=int(s["stocks"]))
        for s in raw.get("spots", [])
    }
    cfg = MapConfig(
        width=w, height=h, terrains=terrains, spots=spots,
        initial_agent_cells=[int(p) for p in raw["agents"]],
        max_fuel=int(raw["fuelLimits"]),
        num_days=len(raw["daySteps"]),
        steps_per_day=[int(s) for s in raw["daySteps"]],
        congested_threshold=float(raw["busyThreshold"]),
        jam_threshold=float(raw["jammedThreshold"]),
        num_teams=int(raw["players"]),
    )
    return cfg, [float(x) for x in raw["daySeconds"]]


def types_to_official(roles: List[AgentRole]) -> List[int]:
    return [0 if r == AgentRole.PATROL else 1 for r in roles]


def roles_from_official(types: List[int]) -> List[AgentRole]:
    return [AgentRole.PATROL if t == 0 else AgentRole.REFUEL for t in types]


def day_from_official(raw: dict, cfg: MapConfig, collected_chains_overall: Set[int]) -> DayInput:
    """Start-of-day JSON -> DayInput. `raw["day"]` counts finished days (0 on the first day)."""
    day = int(raw["day"]) + 1
    agents = [
        AgentState(
            agent_id=i,
            role=AgentRole.PATROL if a["kind"] == 0 else AgentRole.REFUEL,
            cell_id=int(a["pos"]),
            fuel=int(a["fuel"]),
        )
        for i, a in enumerate(raw["agents"])
    ]
    road_states = {
        u: RoadState.SMOOTH for u in range(cfg.num_cells) if cfg.terrains[u] == TerrainType.ROAD
    }
    for t in raw.get("traffics", []):
        road_states[int(t["pos"])] = RoadState(int(t["status"]))
    return DayInput(
        day=day,
        max_steps=cfg.steps_per_day[day - 1],
        agents=agents,
        road_states=road_states,
        spot_stocks={c: sp.max_stock for c, sp in cfg.spots.items()},
        collected_chains_overall=set(collected_chains_overall),
    )


def actions_to_official(cfg: MapConfig, start_cells: List[int], actions: List[List[Action]]) -> List[List[int]]:
    """Internal actions -> official int lists (follows each agent's cell along its own moves)."""
    out: List[List[int]] = []
    for u0, acts in zip(start_cells, actions):
        u, seq = u0, []
        for a in acts:
            if a.action_type == ActionType.WAIT:
                seq.append(-int(a.wait_steps))
            else:
                seq.append(direction_of(cfg.width, cfg.height, u, a.target_cell))
                u = a.target_cell
        out.append(seq)
    return out


def actions_from_official(cfg: MapConfig, start_cells: List[int], plan: List[List[int]]) -> List[List[Action]]:
    """Official int lists -> internal actions (inverse of actions_to_official)."""
    out: List[List[Action]] = []
    for u0, seq in zip(start_cells, plan):
        u, acts = u0, []
        for x in seq:
            if x <= -1:
                acts.append(Action.wait(-x))
            else:
                v = neighbor(cfg.width, cfg.height, u, x)
                if v is None:
                    raise ValueError("move outside the map")
                acts.append(Action.move(v))
                u = v
        out.append(acts)
    return out
