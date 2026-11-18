"""Data models and constants for the Procon 2026 HEXUDON problem."""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Dict, List, Optional, Set, Tuple


class TerrainType(str, Enum):
    PLAIN = "PLAIN"         # Đồng bằng: 2 steps, 1 fuel
    MOUNTAIN = "MOUNTAIN"   # Núi: 3 steps, 2 fuel
    POND = "POND"           # Ao: Cannot enter
    ROAD = "ROAD"           # Đường bộ: 1/2/4 steps (by traffic), 2 fuel


class RoadState(IntEnum):
    SMOOTH = 0      # Thông thoáng: 1 step
    CONGESTED = 1   # Đông đúc: 2 steps
    JAM = 2         # Ùn tắc: 4 steps


class AgentRole(str, Enum):
    PATROL = "PATROL"   # Xe tuần tra (thu thập udon, tốn nhiên liệu)
    REFUEL = "REFUEL"   # Xe tiếp nhiên liệu (tiếp xăng, không tốn nhiên liệu)


class ActionType(str, Enum):
    MOVE = "MOVE"   # Di chuyển sang ô liền kề
    WAIT = "WAIT"   # Đợi tại ô hiện tại trong N bước


def get_terrain_step_cost(terrain: TerrainType, road_state: RoadState = RoadState.SMOOTH) -> int:
    """Return the number of steps required to move OUT of a cell with the given terrain."""
    if terrain == TerrainType.PLAIN:
        return 2
    if terrain == TerrainType.MOUNTAIN:
        return 3
    if terrain == TerrainType.ROAD:
        if road_state == RoadState.SMOOTH:
            return 1
        if road_state == RoadState.CONGESTED:
            return 2
        if road_state == RoadState.JAM:
            return 4
    raise ValueError(f"Cannot move from/into terrain {terrain}")


def get_terrain_fuel_cost(terrain: TerrainType) -> int:
    """Return the fuel consumed by a Patrol Car when moving OUT of a cell with the given terrain."""
    if terrain == TerrainType.PLAIN:
        return 1
    if terrain == TerrainType.MOUNTAIN:
        return 2
    if terrain == TerrainType.ROAD:
        return 2
    raise ValueError(f"Cannot move from terrain {terrain}")


@dataclass(frozen=True)
class Spot:
    """A destination (điểm đến) where Patrol Cars can collect Udon."""
    cell_id: int
    chain_id: int       # Chuỗi nhượng quyền (loại Udon)
    max_stock: int      # Kho dự trữ tối đa mỗi ngày (1 .. num_agents)

    def to_dict(self) -> dict:
        return {
            "cell_id": self.cell_id,
            "chain_id": self.chain_id,
            "max_stock": self.max_stock,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Spot:
        return cls(
            cell_id=int(d["cell_id"]),
            chain_id=int(d["chain_id"]),
            max_stock=int(d["max_stock"]),
        )


@dataclass
class Action:
    """An instruction issued to an agent."""
    action_type: ActionType
    target_cell: Optional[int] = None   # Required for MOVE
    wait_steps: int = 0                 # Required for WAIT (>= 1)

    @classmethod
    def move(cls, target_cell: int) -> Action:
        return cls(action_type=ActionType.MOVE, target_cell=target_cell, wait_steps=0)

    @classmethod
    def wait(cls, steps: int) -> Action:
        if steps <= 0:
            raise ValueError(f"Wait steps must be >= 1, got {steps}")
        return cls(action_type=ActionType.WAIT, target_cell=None, wait_steps=steps)

    def to_dict(self) -> dict:
        if self.action_type == ActionType.MOVE:
            return {"type": "MOVE", "target": self.target_cell}
        return {"type": "WAIT", "steps": self.wait_steps}

    @classmethod
    def from_dict(cls, d: dict) -> Action:
        t = ActionType(d["type"].upper())
        if t == ActionType.MOVE:
            return cls.move(int(d["target"]))
        return cls.wait(int(d["steps"]))


@dataclass
class AgentState:
    """Runtime state of a single agent."""
    agent_id: int
    role: AgentRole
    cell_id: int
    fuel: int                   # For PATROL: 0..max_fuel; for REFUEL: ignored/infinite
    visited_spots_today: Set[int] = field(default_factory=set)

    def clone(self) -> AgentState:
        return AgentState(
            agent_id=self.agent_id,
            role=self.role,
            cell_id=self.cell_id,
            fuel=self.fuel,
            visited_spots_today=set(self.visited_spots_today),
        )

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "role": self.role.value,
            "cell_id": self.cell_id,
            "fuel": self.fuel,
        }


@dataclass
class MapConfig:
    """Static match configuration provided before Day 1."""
    width: int                          # 8 .. 32
    height: int                         # 8 .. 32
    terrains: List[TerrainType]         # Length = width * height
    spots: Dict[int, Spot]              # cell_id -> Spot
    initial_agent_cells: List[int]      # Length = num_agents (3 .. 8), all PLAIN without spots
    max_fuel: int                       # Max fuel capacity for each Patrol Car
    num_days: int                       # 4 .. 10
    steps_per_day: List[int]            # Length = num_days (1-indexed via steps_per_day[day-1])
    congested_threshold: float          # Ngưỡng đông đúc
    jam_threshold: float                # Ngưỡng ùn tắc
    num_teams: int = 1                  # Số lượng đội cùng thi đấu trên bản đồ

    @property
    def num_cells(self) -> int:
        return self.width * self.height

    @property
    def num_agents(self) -> int:
        return len(self.initial_agent_cells)

    @property
    def all_chain_ids(self) -> Set[int]:
        return {spot.chain_id for spot in self.spots.values()}

    def to_dict(self) -> dict:
        return {
            "width": self.width,
            "height": self.height,
            "terrains": [t.value for t in self.terrains],
            "spots": [s.to_dict() for s in self.spots.values()],
            "initial_agent_cells": list(self.initial_agent_cells),
            "max_fuel": self.max_fuel,
            "num_days": self.num_days,
            "steps_per_day": list(self.steps_per_day),
            "congested_threshold": self.congested_threshold,
            "jam_threshold": self.jam_threshold,
            "num_teams": self.num_teams,
        }

    @classmethod
    def from_dict(cls, d: dict) -> MapConfig:
        spots_list = [Spot.from_dict(s) for s in d["spots"]]
        return cls(
            width=int(d["width"]),
            height=int(d["height"]),
            terrains=[TerrainType(t) for t in d["terrains"]],
            spots={s.cell_id: s for s in spots_list},
            initial_agent_cells=[int(c) for c in d["initial_agent_cells"]],
            max_fuel=int(d["max_fuel"]),
            num_days=int(d["num_days"]),
            steps_per_day=[int(s) for s in d["steps_per_day"]],
            congested_threshold=float(d.get("congested_threshold", 4.0)),
            jam_threshold=float(d.get("jam_threshold", 8.0)),
            num_teams=int(d.get("num_teams", 1)),
        )


@dataclass
class DayInput:
    """State provided at the start of Day `day` (1-indexed)."""
    day: int                                # 1 .. num_days
    max_steps: int                          # Steps available on this day
    agents: List[AgentState]                # Current positions and fuel of our agents
    road_states: Dict[int, RoadState]       # cell_id -> RoadState for all ROAD cells
    spot_stocks: Dict[int, int]             # cell_id -> current remaining stock (replenished to max)
    collected_chains_overall: Set[int] = field(default_factory=set)
    daily_unique_chains_sum: int = 0
    total_portions: int = 0


@dataclass
class StepFrame:
    """Snapshot of a single step within a day for replay & visualization."""
    day: int
    step: int                               # 0 .. max_steps
    agent_cells: List[int]
    agent_fuels: List[int]
    spot_stocks: Dict[int, int]
    collected_chains_today: List[int]
    refueled_agents: List[int]              # agent_ids refueled at this step
    collected_events: List[Tuple[int, int, int]]  # (agent_id, cell_id, chain_id)


@dataclass
class DayResult:
    """Outcome of simulating a single day."""
    day: int
    valid: bool
    error_message: Optional[str]
    agents_end: List[AgentState]
    chains_collected_today: Set[int]
    portions_collected_today: int
    road_stay_steps: Dict[int, int]         # cell_id -> total agent-steps spent on road cell today
    frames: List[StepFrame] = field(default_factory=list)


@dataclass
class MatchScore:
    """The 4-tier lexicographic score of a team in HEXUDON."""
    unique_chains_total: int                # Priority 1: Distinct udon types across match
    cumulative_daily_unique_chains: int     # Priority 2: Sum of distinct udon types per day
    total_portions: int                     # Priority 3: Total udon portions collected
    total_response_time_ms: float = 0.0     # Priority 4: Lower is better

    def comparison_key(self) -> Tuple[int, int, int, float]:
        """Return tuple for max comparison (negating response time)."""
        return (
            self.unique_chains_total,
            self.cumulative_daily_unique_chains,
            self.total_portions,
            -self.total_response_time_ms,
        )

    def to_dict(self) -> dict:
        return {
            "priority_1_unique_chains_total": self.unique_chains_total,
            "priority_2_cumulative_daily_unique_chains": self.cumulative_daily_unique_chains,
            "priority_3_total_portions": self.total_portions,
            "priority_4_total_response_time_ms": round(self.total_response_time_ms, 2),
        }
