"""Hexagonal grid geometry and full match simulation engine for HEXUDON."""

from __future__ import annotations
import heapq
from typing import Dict, List, Optional, Set, Tuple

from .models import (
    Action,
    ActionType,
    AgentRole,
    AgentState,
    DayInput,
    DayResult,
    MapConfig,
    MatchScore,
    RoadState,
    Spot,
    StepFrame,
    TerrainType,
    get_terrain_fuel_cost,
    get_terrain_step_cost,
)


class HexGrid:
    """
    Pointy-top hexagonal grid using the `even-r` layout shown in Figure 1 of the problem statement.
    - Cell ID = r * width + c, where 0 <= r < height, 0 <= c < width.
    - Even rows (r % 2 == 0) are indented HALF A HEX TO THE RIGHT relative to odd rows (r % 2 == 1).
    """

    def __init__(self, width: int, height: int, terrains: List[TerrainType]):
        if not (8 <= width <= 32 and 8 <= height <= 32):
            raise ValueError(f"Map dimensions must be in [8, 32], got {width}x{height}")
        if len(terrains) != width * height:
            raise ValueError(f"Expected {width * height} terrain entries, got {len(terrains)}")

        self.width = width
        self.height = height
        self.num_cells = width * height
        self.terrains = list(terrains)

        # Precompute adjacency list (all 6 neighbors, and passable neighbors)
        self.all_neighbors: List[List[int]] = [[] for _ in range(self.num_cells)]
        self.passable_neighbors: List[List[int]] = [[] for _ in range(self.num_cells)]

        for u in range(self.num_cells):
            r, c = self.id_to_rc(u)
            if r % 2 == 0:
                # Even row (shifted right)
                deltas = [(0, -1), (0, 1), (-1, 0), (-1, 1), (1, 0), (1, 1)]
            else:
                # Odd row (shifted left)
                deltas = [(0, -1), (0, 1), (-1, -1), (-1, 0), (1, -1), (1, 0)]

            for dr, dc in deltas:
                nr, nc = r + dr, c + dc
                if 0 <= nr < self.height and 0 <= nc < self.width:
                    v = self.rc_to_id(nr, nc)
                    self.all_neighbors[u].append(v)
                    if self.terrains[v] != TerrainType.POND:
                        self.passable_neighbors[u].append(v)

    def id_to_rc(self, cell_id: int) -> Tuple[int, int]:
        return divmod(cell_id, self.width)

    def rc_to_id(self, r: int, c: int) -> int:
        return r * self.width + c

    def id_to_axial(self, cell_id: int) -> Tuple[int, int]:
        """Convert cell_id to axial coordinates (q, r) for exact hex distance calculation."""
        r, c = divmod(cell_id, self.width)
        q = c - ((r + (r & 1)) // 2)
        return q, r

    def hex_distance(self, u: int, v: int) -> int:
        """Exact minimum number of hex hops between u and v (ignoring obstacles)."""
        q1, r1 = self.id_to_axial(u)
        q2, r2 = self.id_to_axial(v)
        dq = q1 - q2
        dr = r1 - r2
        return (abs(dq) + abs(dr) + abs(dq + dr)) // 2

    def is_adjacent(self, u: int, v: int) -> bool:
        return v in self.all_neighbors[u]

    def is_passable(self, u: int) -> bool:
        return 0 <= u < self.num_cells and self.terrains[u] != TerrainType.POND

    def shortest_paths_from(
        self,
        source: int,
        road_states: Dict[int, RoadState],
        optimize_for: str = "steps",
    ) -> Tuple[List[int], List[int], List[int]]:
        """
        Compute single-source shortest paths from `source` to all cells.
        Remember: moving OUT of cell `u` into adjacent non-POND cell `v` costs
        the step_cost(u) and fuel_cost(u)!

        optimize_for:
          - "steps": primary = min steps, secondary = min fuel
          - "fuel":  primary = min fuel, secondary = min steps
          - "balanced": primary = steps * 2 + fuel

        Returns:
          (min_steps, min_fuel, parent_cell) arrays of length num_cells.
        """
        INF = 10**9
        dist_steps = [INF] * self.num_cells
        dist_fuel = [INF] * self.num_cells
        parent = [-1] * self.num_cells

        if not self.is_passable(source):
            return dist_steps, dist_fuel, parent

        dist_steps[source] = 0
        dist_fuel[source] = 0
        # Heap items: (primary_cost, secondary_cost, cell_id)
        pq: List[Tuple[int, int, int]] = [(0, 0, source)]

        while pq:
            p_cost, s_cost, u = heapq.heappop(pq)
            cur_s = dist_steps[u]
            cur_f = dist_fuel[u]

            if optimize_for == "steps":
                if (p_cost, s_cost) > (cur_s, cur_f):
                    continue
            elif optimize_for == "fuel":
                if (p_cost, s_cost) > (cur_f, cur_s):
                    continue
            else:
                if (p_cost, s_cost) > (cur_s * 2 + cur_f, cur_s):
                    continue

            t_u = self.terrains[u]
            rs_u = road_states.get(u, RoadState.SMOOTH)
            step_u = get_terrain_step_cost(t_u, rs_u)
            fuel_u = get_terrain_fuel_cost(t_u)

            ns = cur_s + step_u
            nf = cur_f + fuel_u

            for v in self.passable_neighbors[u]:
                if optimize_for == "steps":
                    new_key = (ns, nf)
                    old_key = (dist_steps[v], dist_fuel[v])
                elif optimize_for == "fuel":
                    new_key = (nf, ns)
                    old_key = (dist_fuel[v], dist_steps[v])
                else:
                    new_key = (ns * 2 + nf, ns)
                    old_key = (dist_steps[v] * 2 + dist_fuel[v], dist_steps[v])

                if new_key < old_key:
                    dist_steps[v] = ns
                    dist_fuel[v] = nf
                    parent[v] = u
                    heapq.heappush(pq, (new_key[0], new_key[1], v))

        return dist_steps, dist_fuel, parent

    @staticmethod
    def reconstruct_path(parent: List[int], source: int, target: int) -> List[int]:
        """Return list of cells [v_1, v_2, ..., target] to move from source to target."""
        if source == target:
            return []
        if parent[target] == -1:
            return []
        path = []
        cur = target
        while cur != source:
            path.append(cur)
            cur = parent[cur]
            if cur == -1:
                return []
        path.reverse()
        return path


class HexudonEngine:
    """
    Complete simulator and action validator for Procon 2026 HEXUDON.
    """

    def __init__(self, config: MapConfig):
        self.config = config
        self.grid = HexGrid(config.width, config.height, config.terrains)

    def create_initial_agents(self, roles: List[AgentRole]) -> List[AgentState]:
        if len(roles) != self.config.num_agents:
            raise ValueError(f"Expected {self.config.num_agents} roles, got {len(roles)}")
        agents = []
        for idx, (cell_id, role) in enumerate(zip(self.config.initial_agent_cells, roles)):
            fuel = self.config.max_fuel if role == AgentRole.PATROL else self.config.max_fuel
            agents.append(
                AgentState(
                    agent_id=idx,
                    role=role,
                    cell_id=cell_id,
                    fuel=fuel,
                    visited_spots_today=set(),
                )
            )
        return agents

    def compute_road_states(
        self,
        history_road_stays: List[Dict[int, int]],
        day: int,
    ) -> Dict[int, RoadState]:
        """
        Compute road state for every ROAD cell at the start of `day` (1-indexed).
        - Day 1: all SMOOTH.
        - Day 2: based on Day 1 traffic divided by num_teams.
        - Day d >= 3: based on sum of Day (d-1) and Day (d-2) traffic divided by num_teams.
        """
        road_states: Dict[int, RoadState] = {}
        for u in range(self.config.num_cells):
            if self.config.terrains[u] != TerrainType.ROAD:
                continue
            if day <= 1 or not history_road_stays:
                road_states[u] = RoadState.SMOOTH
                continue

            relevant_days = history_road_stays[-1:] if day == 2 else history_road_stays[-2:]
            total_stays = sum(d_map.get(u, 0) for d_map in relevant_days)
            traffic = total_stays / max(1, self.config.num_teams)

            if traffic >= self.config.jam_threshold:
                road_states[u] = RoadState.JAM
            elif traffic >= self.config.congested_threshold:
                road_states[u] = RoadState.CONGESTED
            else:
                road_states[u] = RoadState.SMOOTH

        return road_states

    def simulate_day(
        self,
        day_input: DayInput,
        agent_actions: List[List[Action]],
        record_frames: bool = True,
    ) -> DayResult:
        """
        Simulate one full day of HEXUDON and strictly validate every instruction.

        Rules enforced:
        1. `agent_actions` must provide an action list for each of the `num_agents` agents.
        2. Every MOVE must go to an adjacent non-POND cell.
        3. Moving out of `u` takes `step_cost(u)` steps and (for PATROL) `fuel_cost(u)` fuel.
        4. Fuel is checked and deducted at the moment the MOVE instruction begins.
           Wait! What if a Refueling Car is on the same cell at the start of the day (step 0)
           or during an overlap step?
           Rule: "Nếu một xe tiếp nhiên liệu ở cùng ô với một xe tuần tra trong một hoặc nhiều bước,
           nhiên liệu của xe tuần tra sẽ tự động được nạp đầy đến dung lượng tối đa."
        5. Total steps of actions for each agent must equal `day_input.max_steps`
           (if an agent cannot move due to fuel or insufficient remaining steps, it MUST issue WAIT).
        """
        num_agents = len(day_input.agents)
        if len(agent_actions) != num_agents:
            return DayResult(
                day=day_input.day,
                valid=False,
                error_message=f"Expected actions for {num_agents} agents, got {len(agent_actions)}",
                agents_end=[a.clone() for a in day_input.agents],
                chains_collected_today=set(),
                portions_collected_today=0,
                road_stay_steps={},
            )

        max_steps = day_input.max_steps
        agents = [a.clone() for a in day_input.agents]
        for a in agents:
            a.visited_spots_today.clear()

        spot_stocks = dict(day_input.spot_stocks)
        chains_today: Set[int] = set()
        portions_today = 0
        road_stay_steps: Dict[int, int] = {
            u: 0 for u in range(self.config.num_cells) if self.config.terrains[u] == TerrainType.ROAD
        }

        # Per-agent execution cursors
        action_idx = [0] * num_agents
        busy_remaining = [0] * num_agents
        pending_target: List[Optional[int]] = [None] * num_agents

        frames: List[StepFrame] = []

        # Initial frame (Step 0)
        if record_frames:
            frames.append(
                StepFrame(
                    day=day_input.day,
                    step=0,
                    agent_cells=[a.cell_id for a in agents],
                    agent_fuels=[a.fuel for a in agents],
                    spot_stocks=dict(spot_stocks),
                    collected_chains_today=sorted(chains_today),
                    refueled_agents=[],
                    collected_events=[],
                )
            )

        for step in range(1, max_steps + 1):
            remaining_in_day = max_steps - step + 1

            # 1. Start new actions for any agent whose previous action finished (busy_remaining == 0)
            for i, ag in enumerate(agents):
                if busy_remaining[i] == 0:
                    if action_idx[i] >= len(agent_actions[i]):
                        return DayResult(
                            day=day_input.day,
                            valid=False,
                            error_message=(
                                f"Agent {i} ran out of instructions at step {step}/{max_steps}. "
                                f"Must issue WAIT for remaining {remaining_in_day} steps."
                            ),
                            agents_end=agents,
                            chains_collected_today=chains_today,
                            portions_collected_today=portions_today,
                            road_stay_steps=road_stay_steps,
                            frames=frames,
                        )

                    act = agent_actions[i][action_idx[i]]
                    action_idx[i] += 1
                    u = ag.cell_id

                    if act.action_type == ActionType.WAIT:
                        if act.wait_steps <= 0:
                            return DayResult(
                                day=day_input.day,
                                valid=False,
                                error_message=f"Agent {i} issued WAIT with invalid steps={act.wait_steps}.",
                                agents_end=agents,
                                chains_collected_today=chains_today,
                                portions_collected_today=portions_today,
                                road_stay_steps=road_stay_steps,
                                frames=frames,
                            )
                        if act.wait_steps > remaining_in_day:
                            return DayResult(
                                day=day_input.day,
                                valid=False,
                                error_message=(
                                    f"Agent {i} issued WAIT({act.wait_steps}) at step {step}, "
                                    f"exceeding remaining steps ({remaining_in_day})."
                                ),
                                agents_end=agents,
                                chains_collected_today=chains_today,
                                portions_collected_today=portions_today,
                                road_stay_steps=road_stay_steps,
                                frames=frames,
                            )
                        busy_remaining[i] = act.wait_steps
                        pending_target[i] = None

                    elif act.action_type == ActionType.MOVE:
                        v = act.target_cell
                        if v is None or not self.grid.is_adjacent(u, v):
                            return DayResult(
                                day=day_input.day,
                                valid=False,
                                error_message=f"Agent {i} at cell {u} tried to MOVE to non-adjacent cell {v}.",
                                agents_end=agents,
                                chains_collected_today=chains_today,
                                portions_collected_today=portions_today,
                                road_stay_steps=road_stay_steps,
                                frames=frames,
                            )
                        if not self.grid.is_passable(v):
                            return DayResult(
                                day=day_input.day,
                                valid=False,
                                error_message=f"Agent {i} at cell {u} tried to MOVE into POND cell {v}.",
                                agents_end=agents,
                                chains_collected_today=chains_today,
                                portions_collected_today=portions_today,
                                road_stay_steps=road_stay_steps,
                                frames=frames,
                            )

                        t_u = self.config.terrains[u]
                        rs_u = day_input.road_states.get(u, RoadState.SMOOTH)
                        req_steps = get_terrain_step_cost(t_u, rs_u)
                        req_fuel = get_terrain_fuel_cost(t_u)

                        if req_steps > remaining_in_day:
                            return DayResult(
                                day=day_input.day,
                                valid=False,
                                error_message=(
                                    f"Agent {i} at cell {u} ({t_u.value}) tried to MOVE requiring "
                                    f"{req_steps} steps, but only {remaining_in_day} steps remain in day."
                                ),
                                agents_end=agents,
                                chains_collected_today=chains_today,
                                portions_collected_today=portions_today,
                                road_stay_steps=road_stay_steps,
                                frames=frames,
                            )

                        if ag.role == AgentRole.PATROL:
                            if ag.fuel < req_fuel:
                                return DayResult(
                                    day=day_input.day,
                                    valid=False,
                                    error_message=(
                                        f"Patrol Agent {i} at cell {u} tried to MOVE requiring "
                                        f"{req_fuel} fuel, but only has {ag.fuel} fuel."
                                    ),
                                    agents_end=agents,
                                    chains_collected_today=chains_today,
                                    portions_collected_today=portions_today,
                                    road_stay_steps=road_stay_steps,
                                    frames=frames,
                                )
                            ag.fuel -= req_fuel

                        busy_remaining[i] = req_steps
                        pending_target[i] = v
                    else:
                        return DayResult(
                            day=day_input.day,
                            valid=False,
                            error_message=f"Unknown action type {act.action_type}",
                            agents_end=agents,
                            chains_collected_today=chains_today,
                            portions_collected_today=portions_today,
                            road_stay_steps=road_stay_steps,
                            frames=frames,
                        )

            # 2. Advance 1 step for all agents
            for i, ag in enumerate(agents):
                # Record road stay during this step
                if self.config.terrains[ag.cell_id] == TerrainType.ROAD:
                    road_stay_steps[ag.cell_id] = road_stay_steps.get(ag.cell_id, 0) + 1

                busy_remaining[i] -= 1
                if busy_remaining[i] == 0 and pending_target[i] is not None:
                    ag.cell_id = pending_target[i]
                    pending_target[i] = None

            # 3. Check Refueling: any Patrol Car on the same cell as a Refueling Car for >= 1 step
            # Note: an agent that stays on cell `c` during this step or arrives at `c` at the end of this step
            refuel_cells = {
                ag.cell_id for ag in agents if ag.role == AgentRole.REFUEL
            }
            refueled_this_step: List[int] = []
            for ag in agents:
                if ag.role == AgentRole.PATROL and ag.cell_id in refuel_cells:
                    if ag.fuel < self.config.max_fuel:
                        refueled_this_step.append(ag.agent_id)
                    ag.fuel = self.config.max_fuel

            # 4. Check Udon Collection at destinations
            collected_events: List[Tuple[int, int, int]] = []
            for ag in agents:
                if ag.role == AgentRole.PATROL:
                    c = ag.cell_id
                    if c in self.config.spots and c not in ag.visited_spots_today:
                        if spot_stocks.get(c, 0) > 0:
                            spot = self.config.spots[c]
                            ag.visited_spots_today.add(c)
                            spot_stocks[c] -= 1
                            chains_today.add(spot.chain_id)
                            portions_today += 1
                            collected_events.append((ag.agent_id, c, spot.chain_id))

            if record_frames:
                frames.append(
                    StepFrame(
                        day=day_input.day,
                        step=step,
                        agent_cells=[a.cell_id for a in agents],
                        agent_fuels=[a.fuel for a in agents],
                        spot_stocks=dict(spot_stocks),
                        collected_chains_today=sorted(chains_today),
                        refueled_agents=refueled_this_step,
                        collected_events=collected_events,
                    )
                )

        # Ensure no extra unconsumed actions remain after max_steps
        for i in range(num_agents):
            if busy_remaining[i] != 0 or action_idx[i] != len(agent_actions[i]):
                return DayResult(
                    day=day_input.day,
                    valid=False,
                    error_message=(
                        f"Agent {i} has leftover actions after step {max_steps} "
                        f"(action_idx={action_idx[i]}/{len(agent_actions[i])})."
                    ),
                    agents_end=agents,
                    chains_collected_today=chains_today,
                    portions_collected_today=portions_today,
                    road_stay_steps=road_stay_steps,
                    frames=frames,
                )

        return DayResult(
            day=day_input.day,
            valid=True,
            error_message=None,
            agents_end=agents,
            chains_collected_today=chains_today,
            portions_collected_today=portions_today,
            road_stay_steps=road_stay_steps,
            frames=frames,
        )
