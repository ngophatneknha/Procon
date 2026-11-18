"""
Championship Multi-Agent Route & Refueling Optimizer for Procon 2026 HEXUDON.
Includes fixes from Technical Audit:
  1. Exact Step-1 Spot Collection when starting Day d >= 2 on a Spot cell (Fixes Issue 1).
  2. Time-Synchronized End-of-Day Refuel Car Intercept (Fixes Issue 2).
  3. True Combinatorial Local Search on Agent Tours (`_run_tour_local_search`):
     - Operator 1: Intra-Agent 2-Opt Tour Compression + Slack Spot Extension
     - Operator 2: Inter-Agent Spot Swap
     - Operator 3: Inter-Agent Spot Relocate
     - Operator 4: Missing-Chain Targeted Injection (Repairs any missed chain for Priority 1 & 2)
  4. Domain Heuristics (H1-H7) + Spot-Aware C++20 APSP + 1-Day Lookahead Rollout.
"""

from __future__ import annotations
import os
import random
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from .engine import HexGrid, HexudonEngine
from .fast_apsp import compute_apsp_fast
from .heuristics import HexudonHeuristics, optimize_spot_sequence_2opt
from .models import (
    Action,
    ActionType,
    AgentRole,
    AgentState,
    DayInput,
    MapConfig,
    RoadState,
    Spot,
    TerrainType,
    get_terrain_fuel_cost,
    get_terrain_step_cost,
)


class _AgentPlanBuilder:
    """Tracks an agent's step-by-step planned trajectory within a day."""

    def __init__(
        self,
        agent_id: int,
        role: AgentRole,
        start_cell: int,
        start_fuel: int,
        max_steps: int,
        max_fuel: int,
    ):
        self.agent_id = agent_id
        self.role = role
        self.cell = start_cell
        self.fuel = start_fuel
        self.max_steps = max_steps
        self.max_fuel = max_fuel
        self.step = 0
        self.actions: List[Action] = []
        self.visited_spots: Set[int] = set()
        self.ordered_spots: List[int] = []
        self.finished_active_tour: bool = False

    @property
    def remaining_steps(self) -> int:
        return self.max_steps - self.step

    def add_wait(self, steps: int) -> None:
        if steps <= 0:
            return
        steps = min(steps, self.remaining_steps)
        if steps <= 0:
            return
        if self.actions and self.actions[-1].action_type == ActionType.WAIT:
            self.actions[-1].wait_steps += steps
        else:
            self.actions.append(Action.wait(steps))
        self.step += steps

    def add_move(self, target_cell: int, terrain_u: TerrainType, road_state_u: RoadState) -> bool:
        req_s = get_terrain_step_cost(terrain_u, road_state_u)
        req_f = get_terrain_fuel_cost(terrain_u)
        if req_s > self.remaining_steps:
            return False
        if self.role == AgentRole.PATROL and self.fuel < req_f:
            return False

        self.actions.append(Action.move(target_cell))
        self.step += req_s
        if self.role == AgentRole.PATROL:
            self.fuel -= req_f
        self.cell = target_cell
        return True

    def pad_to_end_of_day(self) -> None:
        if self.remaining_steps > 0:
            self.add_wait(self.remaining_steps)


class HexudonSolver:
    """
    Audited Championship Solver for Procon 2026 HEXUDON.
    """

    def __init__(self, config: MapConfig, seed: int = 42):
        self.config = config
        self.engine = HexudonEngine(config)
        self.grid = self.engine.grid
        self.heuristics = HexudonHeuristics(config, self.grid)
        self.seed = seed
        self.rng = random.Random(seed)
        self.plan_budget_ms = 120.0
        self.spot_bias: Dict[Tuple[int, int], float] = {}  # (day, spot cell) -> score multiplier, tuned pre-match
        self._apsp_cache: Dict[Tuple[int, str], Tuple[List[List[int]], List[List[int]], List[List[int]]]] = {}

    def select_roles(self, use_simulation_rollout: bool = True) -> List[AgentRole]:
        """
        Pre-Match Role Selection via Full-Match Simulation Rollout.
        """
        n = self.config.num_agents
        spot_cells = list(self.config.spots.keys())

        centrality: List[Tuple[float, int]] = []
        for idx, start_cell in enumerate(self.config.initial_agent_cells):
            avg_d = (
                sum(self.grid.hex_distance(start_cell, sc) for sc in spot_cells) / len(spot_cells)
                if spot_cells
                else 0.0
            )
            centrality.append((avg_d, idx))
        centrality.sort()
        sorted_indices = [idx for _, idx in centrality]

        candidates: List[List[AgentRole]] = []
        total_steps = sum(self.config.steps_per_day)
        need_two_refuel = n >= 6 and self.config.max_fuel < total_steps * 0.22

        if not need_two_refuel:
            c1 = [AgentRole.PATROL] * n
            c1[sorted_indices[0]] = AgentRole.REFUEL
            candidates.append(c1)

            if n >= 3:
                c1b = [AgentRole.PATROL] * n
                c1b[sorted_indices[1]] = AgentRole.REFUEL
                if c1b not in candidates:
                    candidates.append(c1b)

        if n >= 5:
            c2_central = [AgentRole.PATROL] * n
            c2_central[sorted_indices[0]] = AgentRole.REFUEL
            c2_central[sorted_indices[1]] = AgentRole.REFUEL
            if c2_central not in candidates:
                candidates.append(c2_central)

            first_ref = sorted_indices[0]
            first_cell = self.config.initial_agent_cells[first_ref]
            best_second = sorted_indices[1]
            best_sep_score = -1e9
            for _, cand_idx in centrality[1 : min(n, 6)]:
                cand_cell = self.config.initial_agent_cells[cand_idx]
                sep = self.grid.hex_distance(first_cell, cand_cell)
                avg_d = sum(self.grid.hex_distance(cand_cell, sc) for sc in spot_cells) / max(1, len(spot_cells))
                sc_val = sep * 1.2 - avg_d
                if sc_val > best_sep_score:
                    best_sep_score = sc_val
                    best_second = cand_idx

            c2 = [AgentRole.PATROL] * n
            c2[first_ref] = AgentRole.REFUEL
            c2[best_second] = AgentRole.REFUEL
            if c2 not in candidates:
                candidates.append(c2)

        if self.config.max_fuel >= total_steps // 2:
            c0 = [AgentRole.PATROL] * n
            candidates.append(c0)

        if use_simulation_rollout and os.environ.get("HEX_OLD_ROLES") != "1":
            # Role choice is the biggest lever (exp_roles.py: F1 9->11, 14->17, 17->19 on hard maps):
            # roll out every refuel-subset up to kmax instead of a hand-picked few.
            import itertools
            kmax = min(3 if n >= 7 else 2, n - 1)
            candidates = [
                [AgentRole.REFUEL if k in refs else AgentRole.PATROL for k in range(n)]
                for kk in range(0, kmax + 1)
                for refs in itertools.combinations(range(n), kk)
            ]

        if not use_simulation_rollout or len(candidates) == 1:
            return candidates[0]

        best_roles = candidates[0]
        best_score_tuple = (-1, -1, -1)

        if len(candidates) > 12:
            # Stage 1: cheap 1-config rollout on all subsets, time-capped; stage 2: full rollout on top 8 (HEX_OLD_ROLES=1 restores the old hand-picked candidates for A/B).
            t0 = time.perf_counter()
            cheap = []
            for roles in candidates:
                if time.perf_counter() - t0 > getattr(self, "role_time_s", 8.0):
                    break
                cheap.append((self._quick_rollout_roles(roles, n_cfg=1), roles))
            cheap.sort(key=lambda x: x[0], reverse=True)
            candidates = [r for _, r in cheap[:5]]

        scored = sorted(((self._quick_rollout_roles(r), r) for r in candidates), key=lambda x: x[0], reverse=True)
        best_roles = scored[0][1]
        if os.environ.get("HEX_OLD_ROLES") == "1" or os.environ.get("HEX_PLAYSEL") == "0" or len(scored) == 1:
            return best_roles
        # Stage 3: the quick rollout mis-ranks some maps (maps 39, 105) and play-through varies by seed.
        # Plan is deterministic per seed, so pick the best (roles, seed) by actually playing, then reuse the seed.
        t0 = time.perf_counter()
        best_play = None
        for _, roles in scored[:3]:
            for sd in (self.seed, 7, 99):
                if best_play is not None and time.perf_counter() - t0 > getattr(self, "role_time_s", 8.0):
                    break
                self.seed = sd
                sc = self._play_rollout_roles(roles, self.plan_budget_ms)
                if best_play is None or sc > best_play[0]:
                    best_play = (sc, roles, sd)
        self.seed = best_play[2]
        if os.environ.get("HEX_ES") != "0":
            self.spot_bias = self._evolve_bias(best_play[1], float(os.environ.get("HEX_ES_TIME", getattr(self, "evolve_time_s", 15.0))))
        return best_play[1]

    def _evolve_bias(self, roles: List[AgentRole], time_s: float) -> Dict[Tuple[int, int], float]:
        """(1+1)-ES over per-(day, spot) priority multipliers for the greedy builder. Whole-match play-through
        is the fitness (F1,F2,F3 lexicographic): it learns WHICH day should take WHICH spot, which the
        day-greedy planner cannot see. Tune with a cheap budget, then verify at the real budget (planner is
        deterministic, so the verification is exactly what the match will replay in the 1-team case)."""
        rng = random.Random(self.seed + 1)
        spots = list(self.config.spots)
        D = self.config.num_days
        self.spot_bias = {}
        best = self._play_rollout_roles(roles, self.plan_budget_ms)
        best_bias: Dict[Tuple[int, int], float] = {}
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < time_s:
            cand = dict(best_bias)
            for _ in range(rng.choice([1, 2, 3])):
                key = (rng.randint(1, D), rng.choice(spots))
                cand[key] = min(10.0, max(0.1, cand.get(key, 1.0) * rng.choice([0.25, 0.5, 2.0, 4.0])))
            self.spot_bias = cand
            sc = self._play_rollout_roles(roles, self.plan_budget_ms)
            if sc >= best:
                best, best_bias = sc, cand
        self.spot_bias = {}
        base_real = self._play_rollout_roles(roles, self.plan_budget_ms)
        self.spot_bias = best_bias
        tuned_real = self._play_rollout_roles(roles, self.plan_budget_ms)
        return best_bias if tuned_real > base_real else {}

    def _play_rollout_roles(self, roles: List[AgentRole], budget_ms: float) -> Tuple[int, int, int]:
        agents = self.engine.create_initial_agents(roles)
        overall: Set[int] = set()
        daily = portions = 0
        hist: List[Dict[int, int]] = []
        for day in range(1, self.config.num_days + 1):
            di = DayInput(
                day=day, max_steps=self.config.steps_per_day[day - 1], agents=[a.clone() for a in agents],
                road_states=self.engine.compute_road_states(hist, day),
                spot_stocks={c: sp.max_stock for c, sp in self.config.spots.items()},
                collected_chains_overall=set(overall),
            )
            res = self.engine.simulate_day(di, self.plan_day(di, time_budget_ms=budget_ms), record_frames=False)
            if not res.valid:
                return (-1, -1, -1)
            hist.append(res.road_stay_steps)
            agents = res.agents_end
            overall |= res.chains_collected_today
            daily += len(res.chains_collected_today)
            portions += res.portions_collected_today
        return (len(overall), daily, portions)

    def _get_deterministic_portfolio(self) -> List[Dict[str, Any]]:
        return [
            {
                "mode": "steps",
                "refuel_threshold": 0.35,
                "noise": 0.0,
                "cluster_bias": 0.15,
                "lookahead": 0.30,
                "scarcity_w": 0.0,
                "gravity_w": 0.0,
                "use_2opt": False,
            },
            {
                "mode": "balanced",
                "refuel_threshold": 0.40,
                "noise": 0.0,
                "cluster_bias": 0.25,
                "lookahead": 0.25,
                "scarcity_w": 0.0,
                "gravity_w": 0.0,
                "use_2opt": False,
            },
            {
                "mode": "fuel",
                "refuel_threshold": 0.30,
                "noise": 0.0,
                "cluster_bias": 0.10,
                "lookahead": 0.35,
                "scarcity_w": 0.0,
                "gravity_w": 0.0,
                "use_2opt": False,
            },
            {
                "mode": "steps",
                "refuel_threshold": 0.50,
                "noise": 0.0,
                "cluster_bias": 0.35,
                "lookahead": 0.20,
                "scarcity_w": 0.0,
                "gravity_w": 0.0,
                "use_2opt": False,
            },
            {
                "mode": "balanced",
                "refuel_threshold": 0.25,
                "noise": 0.0,
                "cluster_bias": 0.05,
                "lookahead": 0.40,
                "scarcity_w": 0.0,
                "gravity_w": 0.0,
                "use_2opt": False,
            },
            {
                "mode": "steps",
                "refuel_threshold": 0.35,
                "noise": 0.0,
                "cluster_bias": 0.00,
                "lookahead": 0.00,
                "scarcity_w": 0.00,
                "gravity_w": 0.0,
                "use_2opt": False,
            },
        ]

    def _get_heuristic_portfolio(self) -> List[Dict[str, Any]]:
        return [
            {
                "mode": "steps",
                "refuel_threshold": 0.35,
                "noise": 0.0,
                "cluster_bias": 0.15,
                "lookahead": 0.30,
                "scarcity_w": 0.35,
                "gravity_w": 18.0,
                "use_2opt": True,
            },
            {
                "mode": "balanced",
                "refuel_threshold": 0.40,
                "noise": 0.0,
                "cluster_bias": 0.25,
                "lookahead": 0.25,
                "scarcity_w": 0.45,
                "gravity_w": 25.0,
                "use_2opt": True,
            },
            {
                "mode": "fuel",
                "refuel_threshold": 0.30,
                "noise": 0.0,
                "cluster_bias": 0.10,
                "lookahead": 0.35,
                "scarcity_w": 0.30,
                "gravity_w": 15.0,
                "use_2opt": True,
            },
        ]

    def _quick_rollout_roles(self, roles: List[AgentRole], n_cfg: int = 99) -> Tuple[int, int, int]:
        agents = self.engine.create_initial_agents(roles)
        collected_overall: Set[int] = set()
        daily_unique_sum = 0
        total_portions = 0
        history_road_stays: List[Dict[int, int]] = []
        portfolio = self._get_deterministic_portfolio()[:n_cfg]

        for day in range(1, self.config.num_days + 1):
            max_steps = self.config.steps_per_day[day - 1]
            road_states = self.engine.compute_road_states(history_road_stays, day)
            spot_stocks = {cid: sp.max_stock for cid, sp in self.config.spots.items()}
            day_input = DayInput(
                day=day,
                max_steps=max_steps,
                agents=[a.clone() for a in agents],
                road_states=road_states,
                spot_stocks=spot_stocks,
                collected_chains_overall=set(collected_overall),
                daily_unique_chains_sum=daily_unique_sum,
                total_portions=total_portions,
            )
            apsp_steps = self._compute_apsp(road_states, mode="steps")
            apsp_fuel = self._compute_apsp(road_states, mode="fuel")
            apsp_balanced = self._compute_apsp(road_states, mode="balanced")

            best_res = None
            best_key = (-1, -1, -1, -1, -1, -1.0)
            for cfg in portfolio:
                apsp = (
                    apsp_steps
                    if cfg["mode"] == "steps"
                    else (apsp_fuel if cfg["mode"] == "fuel" else apsp_balanced)
                )
                actions, _ = self._build_schedule(
                    day_input=day_input,
                    apsp=apsp,
                    apsp_fuel=apsp_fuel,
                    refuel_threshold=cfg["refuel_threshold"],
                    noise=cfg["noise"],
                    cluster_bias=cfg["cluster_bias"],
                    lookahead_weight=cfg["lookahead"],
                    apsp_refuel=apsp_steps,
                    scarcity_weight=cfg["scarcity_w"],
                    gravity_weight=cfg["gravity_w"],
                    use_2opt=cfg["use_2opt"],
                )
                cand_res = self.engine.simulate_day(day_input, actions, record_frames=False)
                if cand_res.valid:
                    ek = self._evaluate_day_result(day_input, cand_res, apsp_steps)
                    if ek > best_key:
                        best_key = ek
                        best_res = cand_res
            if best_res is None:
                return (-1, -1, -1)
            res = best_res
            history_road_stays.append(res.road_stay_steps)
            agents = res.agents_end
            collected_overall |= res.chains_collected_today
            daily_unique_sum += len(res.chains_collected_today)
            total_portions += res.portions_collected_today

        return (len(collected_overall), daily_unique_sum, total_portions)

    def plan_day(
        self,
        day_input: DayInput,
        time_budget_ms: float = 120.0,
    ) -> List[List[Action]]:
        """
        Plan optimal, 100% valid actions for all agents on `day_input.day`:
          - Phase 1: Deterministic & Heuristic Portfolio
          - Phase 2: Stochastic Rollouts
          - Phase 3: True Combinatorial Tour Local Search (2-Opt, Inter-Agent Swap,
            Inter-Agent Relocate, Missing-Chain Injection)
          - Phase 4: True 1-Day Lookahead Rollout (Day d -> Day d+1)
        """
        t_start = time.perf_counter()
        # Deterministic per (seed, day): iteration counts instead of wall-clock cutoffs, so a play-through
        # in select_roles is reproduced exactly in the real match (own traffic only).
        self.rng = random.Random(self.seed * 1000 + day_input.day)

        apsp_steps = self._compute_apsp(day_input.road_states, mode="steps")
        apsp_fuel = self._compute_apsp(day_input.road_states, mode="fuel")
        apsp_balanced = self._compute_apsp(day_input.road_states, mode="balanced")

        # Tuple: (eval_key, res, cand_actions, agent_tours)
        candidates_today: List[Tuple[Tuple, Any, List[List[Action]], Dict[int, List[int]]]] = []

        # Phase 1: Deterministic Portfolio
        for cfg in self._get_deterministic_portfolio():
            apsp = (
                apsp_steps
                if cfg["mode"] == "steps"
                else (apsp_fuel if cfg["mode"] == "fuel" else apsp_balanced)
            )
            cand_actions, tours = self._build_schedule(
                day_input=day_input,
                apsp=apsp,
                apsp_fuel=apsp_fuel,
                refuel_threshold=cfg["refuel_threshold"],
                noise=cfg["noise"],
                cluster_bias=cfg["cluster_bias"],
                lookahead_weight=cfg["lookahead"],
                apsp_refuel=apsp_steps,
                scarcity_weight=cfg["scarcity_w"],
                gravity_weight=cfg["gravity_w"],
                use_2opt=cfg["use_2opt"],
            )
            res = self.engine.simulate_day(day_input, cand_actions, record_frames=False)
            if res.valid:
                eval_key = self._evaluate_day_result(day_input, res, apsp_steps)
                candidates_today.append((eval_key, res, cand_actions, tours))

        # Phase 2: High-throughput stochastic rollouts
        rollout_idx = 0
        while rollout_idx < min(600, int(time_budget_ms / 15)):
            rollout_idx += 1
            mode = self.rng.choice(["steps", "balanced", "fuel"])
            apsp = apsp_steps if mode == "steps" else (apsp_fuel if mode == "fuel" else apsp_balanced)
            refuel_thresh = self.rng.uniform(0.20, 0.60)
            noise = self.rng.uniform(0.02, 0.20)
            cluster_bias = self.rng.uniform(0.0, 0.50)
            lookahead = self.rng.uniform(0.0, 0.45)

            cand_actions, tours = self._build_schedule(
                day_input=day_input,
                apsp=apsp,
                apsp_fuel=apsp_fuel,
                refuel_threshold=refuel_thresh,
                noise=noise,
                cluster_bias=cluster_bias,
                lookahead_weight=lookahead,
                apsp_refuel=apsp_steps,
                scarcity_weight=0.0,
                gravity_weight=0.0,
                use_2opt=False,
            )
            res = self.engine.simulate_day(day_input, cand_actions, record_frames=False)
            if res.valid:
                eval_key = self._evaluate_day_result(day_input, res, apsp_steps)
                candidates_today.append((eval_key, res, cand_actions, tours))

        # Phase 2b: Domain Heuristics (H1-H7) Portfolio
        for h_cfg in self._get_heuristic_portfolio():
            apsp = (
                apsp_steps
                if h_cfg["mode"] == "steps"
                else (apsp_fuel if h_cfg["mode"] == "fuel" else apsp_balanced)
            )
            cand_actions, tours = self._build_schedule(
                day_input=day_input,
                apsp=apsp,
                apsp_fuel=apsp_fuel,
                refuel_threshold=h_cfg["refuel_threshold"],
                noise=h_cfg["noise"],
                cluster_bias=h_cfg["cluster_bias"],
                lookahead_weight=h_cfg["lookahead"],
                apsp_refuel=apsp_steps,
                scarcity_weight=h_cfg["scarcity_w"],
                gravity_weight=h_cfg["gravity_w"],
                use_2opt=h_cfg["use_2opt"],
            )
            res = self.engine.simulate_day(day_input, cand_actions, record_frames=False)
            if res.valid:
                eval_key = self._evaluate_day_result(day_input, res, apsp_steps)
                candidates_today.append((eval_key, res, cand_actions, tours))

        if not candidates_today:
            return [[Action.wait(day_input.max_steps)] for _ in range(len(day_input.agents))]

        candidates_today.sort(key=lambda item: item[0], reverse=True)

        # Phase 3: True Combinatorial Tour Local Search on Top 2 Schedules
        # (2-Opt Tour Compression, Inter-Agent Swap, Inter-Agent Relocate, Missing-Chain Injection)
        if time_budget_ms >= 60.0:
            ls_candidates = self._run_tour_local_search(
                day_input=day_input,
                base_Eval=candidates_today[0][0],
                base_res=candidates_today[0][1],
                base_tours=candidates_today[0][3],
                apsp_steps=apsp_steps,
                apsp_fuel=apsp_fuel,
            )
            candidates_today.extend(ls_candidates)
            candidates_today.sort(key=lambda item: item[0], reverse=True)
            if os.environ.get("HEX_BEAM") != "0" and time_budget_ms >= 60.0:
                candidates_today.extend(self._beam_tours(day_input, candidates_today[0], apsp_steps, apsp_fuel))
                candidates_today.sort(key=lambda item: item[0], reverse=True)
            if os.environ.get("HEX_ILS") != "0":
                candidates_today.extend(
                    self._ils_tours(day_input, candidates_today[0], apsp_steps, apsp_fuel, min(200, int(time_budget_ms / 5)))
                )
                candidates_today.sort(key=lambda item: item[0], reverse=True)

        if day_input.day >= self.config.num_days:
            return candidates_today[0][2]

        # Phase 4: full-horizon lookahead. Score each distinct end-of-day state by greedily playing the
        # REST of the match (own traffic only), so day d accounts for F1/F2/F3 on days d+1..D.
        # Old 1-day lookahead is used when HEX_HORIZON=0 or budget < 1500 ms (horizon costs 3-5x time for a small, noisy gain).
        f1_open = len(day_input.collected_chains_overall | candidates_today[0][1].chains_collected_today) < len(self.config.all_chain_ids)
        if os.environ.get("HEX_HORIZON") == "0" or not (f1_open or time_budget_ms >= 1500.0):
            best_two_day_key: Tuple = (-1, -1, -1, -1, -1, -1, -1)
            best_actions = candidates_today[0][2]
            seen_signatures: Set[Tuple] = set()
            evaluated_count = 0

            for eval_key, res, cand_actions, _ in candidates_today:
                sig = (
                    eval_key[0],
                    eval_key[1],
                    eval_key[2],
                    tuple((a.cell_id, a.fuel) for a in res.agents_end),
                )
                if sig in seen_signatures:
                    continue
                seen_signatures.add(sig)
                evaluated_count += 1

                next_day_num = day_input.day + 1
                next_max_steps = self.config.steps_per_day[next_day_num - 1]
                next_road_states = dict(day_input.road_states)
                next_day_input = DayInput(
                    day=next_day_num,
                    max_steps=next_max_steps,
                    agents=[a.clone() for a in res.agents_end],
                    road_states=next_road_states,
                    spot_stocks={cid: sp.max_stock for cid, sp in self.config.spots.items()},
                    collected_chains_overall=day_input.collected_chains_overall | res.chains_collected_today,
                )
                best_next_res = None
                best_next_key = (-1, -1, -1)
                for n_cfg in self._get_deterministic_portfolio()[:3]:
                    n_apsp = (
                        apsp_steps
                        if n_cfg["mode"] == "steps"
                        else (apsp_fuel if n_cfg["mode"] == "fuel" else apsp_balanced)
                    )
                    n_actions, _ = self._build_schedule(
                        day_input=next_day_input,
                        apsp=n_apsp,
                        apsp_fuel=apsp_fuel,
                        refuel_threshold=n_cfg["refuel_threshold"],
                        noise=0.0,
                        cluster_bias=n_cfg["cluster_bias"],
                        lookahead_weight=n_cfg["lookahead"],
                        apsp_refuel=apsp_steps,
                        scarcity_weight=n_cfg["scarcity_w"],
                        gravity_weight=n_cfg["gravity_w"],
                        use_2opt=n_cfg["use_2opt"],
                    )
                    cand_next_res = self.engine.simulate_day(next_day_input, n_actions, record_frames=False)
                    if cand_next_res.valid:
                        nk = (
                            len(cand_next_res.chains_collected_today),
                            cand_next_res.portions_collected_today,
                            sum(a.fuel for a in cand_next_res.agents_end if a.role == AgentRole.PATROL),
                        )
                        if nk > best_next_key:
                            best_next_key = nk
                            best_next_res = cand_next_res

                if best_next_res is not None:
                    next_res = best_next_res
                    combined_chains = (
                        day_input.collected_chains_overall
                        | res.chains_collected_today
                        | next_res.chains_collected_today
                    )
                    two_day_daily_chains = len(res.chains_collected_today) + len(next_res.chains_collected_today)
                    two_day_portions = res.portions_collected_today + next_res.portions_collected_today
                    next_end_fuel = sum(a.fuel for a in next_res.agents_end if a.role == AgentRole.PATROL)
                    two_day_key = (
                        eval_key[0],
                        eval_key[1],
                        len(combined_chains),
                        two_day_daily_chains,
                        two_day_portions + (next_end_fuel // 3),
                        res.portions_collected_today,
                        eval_key[3],
                    )
                    if two_day_key > best_two_day_key:
                        best_two_day_key = two_day_key
                        best_actions = cand_actions

                if evaluated_count >= 4:
                    break

            return best_actions
        best_actions = candidates_today[0][2]
        best_key = None
        seen: Set[Tuple] = set()
        n_eval = 0
        port = self._get_deterministic_portfolio()[:2]
        for eval_key, res, cand_actions, _ in candidates_today:
            sig = (eval_key[0], eval_key[1], eval_key[2], tuple((a.cell_id, a.fuel) for a in res.agents_end))
            if sig in seen:
                continue
            seen.add(sig)
            if n_eval >= max(2, int(time_budget_ms / 100)):
                break
            n_eval += 1
            agents = [a.clone() for a in res.agents_end]
            overall = day_input.collected_chains_overall | res.chains_collected_today
            daily_sum = len(res.chains_collected_today)
            portions = res.portions_collected_today
            hist = [res.road_stay_steps]
            for nd in range(day_input.day + 1, self.config.num_days + 1):
                rs = self.engine.compute_road_states(hist, 2)
                a_s = self._compute_apsp(rs, mode="steps")
                a_f = self._compute_apsp(rs, mode="fuel")
                a_b = self._compute_apsp(rs, mode="balanced")
                di = DayInput(
                    day=nd, max_steps=self.config.steps_per_day[nd - 1], agents=[a.clone() for a in agents],
                    road_states=rs, spot_stocks={c: sp.max_stock for c, sp in self.config.spots.items()},
                    collected_chains_overall=set(overall),
                )
                best_r, best_k = None, None
                for cfg in port:
                    ap = a_s if cfg["mode"] == "steps" else (a_f if cfg["mode"] == "fuel" else a_b)
                    acts, _ = self._build_schedule(
                        day_input=di, apsp=ap, apsp_fuel=a_f, refuel_threshold=cfg["refuel_threshold"],
                        noise=0.0, cluster_bias=cfg["cluster_bias"], lookahead_weight=cfg["lookahead"],
                        apsp_refuel=a_s, scarcity_weight=cfg["scarcity_w"], gravity_weight=cfg["gravity_w"],
                        use_2opt=cfg["use_2opt"],
                    )
                    r2 = self.engine.simulate_day(di, acts, record_frames=False)
                    if r2.valid:
                        k = (len(r2.chains_collected_today - overall), len(r2.chains_collected_today),
                             r2.portions_collected_today)
                        if best_k is None or k > best_k:
                            best_k, best_r = k, r2
                if best_r is None:
                    break
                agents = [a.clone() for a in best_r.agents_end]
                overall |= best_r.chains_collected_today
                daily_sum += len(best_r.chains_collected_today)
                portions += best_r.portions_collected_today
                hist = [best_r.road_stay_steps]
            key = (len(overall), daily_sum, portions, eval_key[3], eval_key[4], eval_key[5])
            if best_key is None or key > best_key:
                best_key, best_actions = key, cand_actions
        return best_actions

    def _run_tour_local_search(
        self,
        day_input: DayInput,
        base_Eval: Tuple,
        base_res: Any,
        base_tours: Dict[int, List[int]],
        apsp_steps: Tuple[List[List[int]], List[List[int]], List[List[int]]],
        apsp_fuel: Tuple[List[List[int]], List[List[int]], List[List[int]]],
    ) -> List[Tuple[Tuple, Any, List[List[Action]], Dict[int, List[int]]]]:
        """
        True Combinatorial Local Search on the extracted agent spot sequences `base_tours`:
          1. Intra-Agent 2-Opt Reordering on every Patrol Car's tour
          2. Missing-Chain Targeted Injection (if any chain was missed today)
          3. Inter-Agent Spot Swap & Relocate between Patrol Cars
        """
        dist_steps, dist_fuel, _ = apsp_steps
        start_cells = {ag.agent_id: ag.cell_id for ag in day_input.agents if ag.role == AgentRole.PATROL}
        patrol_ids = sorted(start_cells.keys())
        results: List[Tuple[Tuple, Any, List[List[Action]], Dict[int, List[int]]]] = []

        def _try_Forced_tours(forced_map: Dict[int, List[int]]) -> None:
            for ref_th in (0.35, 0.45):
                acts, new_tours = self._build_schedule(
                    day_input=day_input,
                    apsp=apsp_steps,
                    apsp_fuel=apsp_fuel,
                    refuel_threshold=ref_th,
                    noise=0.0,
                    cluster_bias=0.10,
                    lookahead_weight=0.25,
                    apsp_refuel=apsp_steps,
                    scarcity_weight=0.25,
                    gravity_weight=15.0,
                    use_2opt=True,
                    forced_tours=forced_map,
                )
                res = self.engine.simulate_day(day_input, acts, record_frames=False)
                if res.valid:
                    ek = self._evaluate_day_result(day_input, res, apsp_steps)
                    results.append((ek, res, acts, new_tours))

        # Operator 1: Intra-Agent 2-Opt on all Patrol Car tours
        opt2_tours: Dict[int, List[int]] = {}
        changed_2opt = False
        for pid in patrol_ids:
            seq = base_tours.get(pid, [])
            if len(seq) >= 2:
                opt_seq = optimize_spot_sequence_2opt(
                    start_cell=start_cells[pid],
                    spot_seq=seq,
                    dist_steps=dist_steps,
                    dist_fuel=dist_fuel,
                    max_fuel_budget=self.config.max_fuel * 3,
                )
                opt2_tours[pid] = opt_seq
                if opt_seq != seq:
                    changed_2opt = True
            else:
                opt2_tours[pid] = list(seq)

        if changed_2opt:
            _try_Forced_tours(opt2_tours)

        # Operator 2: Missing-Chain Targeted Injection!
        # If any chain was NOT collected in `base_res.chains_collected_today`, find the closest
        # patrol car and inject that missing chain's spot into position 0 or 1 of its tour!
        all_chains = self.config.all_chain_ids
        missing_chains = all_chains - base_res.chains_collected_today
        if missing_chains:
            # Prioritize globally unvisited missing chains first
            sorted_missing = sorted(
                missing_chains,
                key=lambda cid: (0 if cid not in day_input.collected_chains_overall else 1, cid),
            )
            for m_cid in sorted_missing[:2]:
                cand_spots = [sc for sc, sp in self.config.spots.items() if sp.chain_id == m_cid]
                if not cand_spots:
                    continue
                # Find (patrol_id, spot_cell, insert_pos) with minimum detour steps
                best_inj = None
                best_detour = 10**9
                for sc in cand_spots:
                    for pid in patrol_ids:
                        seq = list(opt2_tours.get(pid, []))
                        if sc in seq:
                            continue
                        # Try inserting at position 0 (start of day) or position 1
                        for pos in range(min(3, len(seq) + 1)):
                            prev_c = start_cells[pid] if pos == 0 else seq[pos - 1]
                            if pos < len(seq):
                                next_c = seq[pos]
                                detour = dist_steps[prev_c][sc] + dist_steps[sc][next_c] - dist_steps[prev_c][next_c]
                            else:
                                detour = dist_steps[prev_c][sc]
                            if detour < best_detour:
                                best_detour = detour
                                best_inj = (pid, sc, pos)

                if best_inj is not None:
                    pid, sc, pos = best_inj
                    inj_tours = {k: list(v) for k, v in opt2_tours.items()}
                    inj_tours[pid].insert(pos, sc)
                    # Optimize the modified tour with 2-Opt
                    inj_tours[pid] = optimize_spot_sequence_2opt(
                        start_cell=start_cells[pid],
                        spot_seq=inj_tours[pid],
                        dist_steps=dist_steps,
                        dist_fuel=dist_fuel,
                        max_fuel_budget=self.config.max_fuel * 3,
                    )
                    _try_Forced_tours(inj_tours)

        # Operator 3: Inter-Agent Swap / Relocate between pairs of Patrol Cars
        if len(patrol_ids) >= 2:
            best_swap_tours = None
            best_saving = 0
            for idx_a in range(len(patrol_ids)):
                for idx_b in range(idx_a + 1, len(patrol_ids)):
                    pa = patrol_ids[idx_a]
                    pb_id = patrol_ids[idx_b]
                    seq_a = list(opt2_tours.get(pa, []))
                    seq_b = list(opt2_tours.get(pb_id, []))
                    if not seq_a or not seq_b:
                        continue
                    for i, sa in enumerate(seq_a[:3]):
                        for j, sb in enumerate(seq_b[:3]):
                            if sa == sb:
                                continue
                            prev_a = start_cells[pa] if i == 0 else seq_a[i - 1]
                            prev_b = start_cells[pb_id] if j == 0 else seq_b[j - 1]
                            old_cost = dist_steps[prev_a][sa] + dist_steps[prev_b][sb]
                            new_cost = dist_steps[prev_a][sb] + dist_steps[prev_b][sa]
                            saving = old_cost - new_cost
                            if saving > best_saving:
                                best_saving = saving
                                new_map = {k: list(v) for k, v in opt2_tours.items()}
                                new_map[pa][i] = sb
                                new_map[pb_id][j] = sa
                                best_swap_tours = new_map
            if best_swap_tours is not None:
                _try_Forced_tours(best_swap_tours)

        return results

    def _beam_tour(self, start, spots, stocks, steps_left, fuel_left, dist_steps, dist_fuel,
                   chains_overall, others_chains, width):
        """Beam-search orienteering for ONE patrol. State = (last spot, visited set); value follows the
        reward ladder 1e6 (new chain overall) > 1e4 (new chain vs. other patrols today) > 100 (portion)."""
        cfg = self.config
        def val(sp_cell, have):
            ch = cfg.spots[sp_cell].chain_id
            v = 100.0
            if ch not in have:
                v += 10_000.0
                if ch not in chains_overall:
                    v += 1_000_000.0
            return v
        # state: (value, -steps, fuel_left, last, seq(tuple), chains(frozenset))
        beam = [(0.0, 0, fuel_left, start, (), frozenset(others_chains))]
        best = beam[0]
        for _ in range(len(spots)):
            nxt = {}
            for v0, nst, fl, last, seq, have in beam:
                used = -nst
                for sc in spots:
                    if sc in seq or sc == last:
                        continue
                    ds = dist_steps[last][sc]
                    df = dist_fuel[last][sc]
                    if used + ds > steps_left or df > fl:
                        continue
                    ch = cfg.spots[sc].chain_id
                    st = (v0 + val(sc, have), -(used + ds), fl - df, sc, seq + (sc,), have | {ch})
                    key = (sc, frozenset(seq) | {sc})
                    old = nxt.get(key)
                    if old is None or (st[0], st[1]) > (old[0], old[1]):
                        nxt[key] = st
            if not nxt:
                break
            beam = sorted(nxt.values(), key=lambda t: (t[0], t[1]), reverse=True)[:width]
            if (beam[0][0], beam[0][1]) > (best[0], best[1]):
                best = beam[0]
        return list(best[4])

    def _beam_tours(self, day_input, start, apsp_steps, apsp_fuel):
        """Coordinate descent over patrols: re-optimise one patrol's tour with beam search while the other
        patrols' spots are fixed (their chains are not worth again today), rebuild with forced tours, keep if
        the day key does not get worse. Fills the ~5% single-agent routing gap measured by exp_gap.py."""
        dist_steps, dist_fuel, _ = apsp_steps
        start_cells = {ag.agent_id: ag.cell_id for ag in day_input.agents if ag.role == AgentRole.PATROL}
        fuels = {ag.agent_id: ag.fuel for ag in day_input.agents if ag.role == AgentRole.PATROL}
        pids = sorted(start_cells)
        if not pids:
            return []
        cfg = self.config
        cur_key, _, _, cur_tours = start
        tours = {pid: list(cur_tours.get(pid, [])) for pid in pids}
        spots = [sc for sc, sp in cfg.spots.items() if sp.max_stock > 0]
        width = 24
        out = []
        for _round in range(2):
            changed = False
            for pid in self.rng.sample(pids, len(pids)):
                others = [sc for q in pids if q != pid for sc in tours[q]]
                cap = {}
                for sc in others:
                    cap[sc] = cap.get(sc, 0) + 1
                avail = [sc for sc in spots if cfg.spots[sc].max_stock - cap.get(sc, 0) > 0]
                others_chains = {cfg.spots[sc].chain_id for sc in others}
                new = self._beam_tour(start_cells[pid], avail, None, day_input.max_steps, fuels[pid],
                                      dist_steps, dist_fuel, day_input.collected_chains_overall, others_chains, width)
                if not new or new == tours[pid]:
                    continue
                trial = dict(tours)
                trial[pid] = new
                acts, new_tours = self._build_schedule(
                    day_input=day_input, apsp=apsp_steps, apsp_fuel=apsp_fuel, refuel_threshold=0.4, noise=0.0,
                    cluster_bias=0.10, lookahead_weight=0.25, apsp_refuel=apsp_steps, scarcity_weight=0.25,
                    gravity_weight=15.0, use_2opt=True, forced_tours=trial)
                res = self.engine.simulate_day(day_input, acts, record_frames=False)
                if not res.valid:
                    continue
                ek = self._evaluate_day_result(day_input, res, apsp_steps)
                if ek >= cur_key:
                    if ek > cur_key:
                        out.append((ek, res, acts, new_tours))
                        changed = True
                    cur_key = ek
                    tours = {q: list(new_tours.get(q, [])) for q in pids}
            if not changed:
                break
        return out

    def _ils_tours(self, day_input, start, apsp_steps, apsp_fuel, n_iter):
        """Iterated local search on per-patrol spot sequences (ruin & recreate): perturb the tours, rebuild the
        day with the greedy builder forced onto them, keep the change if the day key does not get worse.
        Extends the old single-pass Phase 3 into a real search; returns the improved candidates."""
        dist_steps, dist_fuel, _ = apsp_steps
        start_cells = {ag.agent_id: ag.cell_id for ag in day_input.agents if ag.role == AgentRole.PATROL}
        pids = sorted(start_cells)
        if not pids:
            return []
        rng = self.rng
        all_spots = list(self.config.spots)
        cur_key, cur_res, cur_acts, cur_tours = start
        cur_tours = {pid: list(cur_tours.get(pid, [])) for pid in pids}
        out = []

        def best_pos(pid, sc):
            seq = cur_tours_try[pid]
            best = (10**9, 0)
            for pos in range(len(seq) + 1):
                prev_c = start_cells[pid] if pos == 0 else seq[pos - 1]
                d = dist_steps[prev_c][sc] + (dist_steps[sc][seq[pos]] - dist_steps[prev_c][seq[pos]] if pos < len(seq) else 0)
                if d < best[0]:
                    best = (d, pos)
            return best[1]

        for _ in range(n_iter):
            cur_tours_try = {pid: list(v) for pid, v in cur_tours.items()}
            op = rng.randrange(4)
            pid = rng.choice(pids)
            if op == 0 and cur_tours_try[pid]:  # drop a spot
                cur_tours_try[pid].pop(rng.randrange(len(cur_tours_try[pid])))
            elif op == 1:  # insert any spot at cheapest position (steals it from another tour)
                sc = rng.choice(all_spots)
                for q in pids:
                    if sc in cur_tours_try[q]:
                        cur_tours_try[q].remove(sc)
                cur_tours_try[pid].insert(best_pos(pid, sc), sc)
            elif op == 2 and cur_tours_try[pid]:  # relocate a spot to another patrol
                sc = cur_tours_try[pid].pop(rng.randrange(len(cur_tours_try[pid])))
                q = rng.choice(pids)
                cur_tours_try[q].insert(best_pos(q, sc), sc)
            elif op == 3:  # swap two spots across tours
                q = rng.choice(pids)
                if cur_tours_try[pid] and cur_tours_try[q] and q != pid:
                    i, j = rng.randrange(len(cur_tours_try[pid])), rng.randrange(len(cur_tours_try[q]))
                    cur_tours_try[pid][i], cur_tours_try[q][j] = cur_tours_try[q][j], cur_tours_try[pid][i]
            for q in (pid,):
                if len(cur_tours_try[q]) >= 2:
                    cur_tours_try[q] = optimize_spot_sequence_2opt(
                        start_cell=start_cells[q], spot_seq=cur_tours_try[q], dist_steps=dist_steps,
                        dist_fuel=dist_fuel, max_fuel_budget=self.config.max_fuel * 3)
            acts, new_tours = self._build_schedule(
                day_input=day_input, apsp=apsp_steps, apsp_fuel=apsp_fuel, refuel_threshold=0.4, noise=0.0,
                cluster_bias=0.10, lookahead_weight=0.25, apsp_refuel=apsp_steps, scarcity_weight=0.25,
                gravity_weight=15.0, use_2opt=True, forced_tours=cur_tours_try)
            res = self.engine.simulate_day(day_input, acts, record_frames=False)
            if not res.valid:
                continue
            ek = self._evaluate_day_result(day_input, res, apsp_steps)
            if ek >= cur_key:
                if ek > cur_key:
                    out.append((ek, res, acts, new_tours))
                cur_key = ek
                cur_tours = {pid2: list(new_tours.get(pid2, [])) for pid2 in pids}
        return out

    def _compute_apsp(
        self,
        road_states: Dict[int, RoadState],
        mode: str = "steps",
    ) -> Tuple[List[List[int]], List[List[int]], List[List[int]]]:
        state_hash = hash((tuple(sorted(road_states.items())), mode))
        if len(self._apsp_cache) > 24:  # bound RAM on 32x32 maps
            self._apsp_cache.clear()
        if state_hash in self._apsp_cache:
            return self._apsp_cache[state_hash]

        fast_res = compute_apsp_fast(self.config, road_states, mode=mode)
        if fast_res is not None:
            self._apsp_cache[state_hash] = fast_res
            return fast_res

        n_cells = self.config.num_cells
        all_steps: List[List[int]] = []
        all_fuel: List[List[int]] = []
        all_parent: List[List[int]] = []
        for u in range(n_cells):
            ds, df, par = self.grid.shortest_paths_from(u, road_states, optimize_for=mode)
            all_steps.append(ds)
            all_fuel.append(df)
            all_parent.append(par)

        res = (all_steps, all_fuel, all_parent)
        self._apsp_cache[state_hash] = res
        return res

    def _evaluate_day_result(
        self,
        day_input: DayInput,
        res,
        apsp_steps: Tuple[List[List[int]], List[List[int]], List[List[int]]],
    ) -> Tuple[int, int, int, int, int, float]:
        new_global_chains = len(res.chains_collected_today - day_input.collected_chains_overall)
        daily_unique_chains = len(res.chains_collected_today)
        portions = res.portions_collected_today

        is_last_day = day_input.day >= self.config.num_days
        parked_on_spots = 0
        end_fuel = 0
        for ag in res.agents_end:
            if ag.role == AgentRole.PATROL:
                end_fuel += ag.fuel
                if not is_last_day and ag.cell_id in self.config.spots and ag.fuel >= 1:
                    parked_on_spots += 1

        covered_after = day_input.collected_chains_overall | res.chains_collected_today
        unvisited_spots = [
            s.cell_id for s in self.config.spots.values() if s.chain_id not in covered_after
        ]
        if not unvisited_spots:
            unvisited_spots = list(self.config.spots.keys())

        dist_steps_mat = apsp_steps[0]
        prox_bonus = 0.0
        for ag in res.agents_end:
            if ag.role == AgentRole.PATROL and unvisited_spots:
                min_d = min(dist_steps_mat[ag.cell_id][sc] for sc in unvisited_spots)
                prox_bonus -= float(min_d) * 0.15

        total_road_stays = sum(res.road_stay_steps.values())
        prox_bonus -= total_road_stays * 0.02

        return (
            new_global_chains,
            daily_unique_chains,
            portions,
            end_fuel,
            parked_on_spots,
            prox_bonus,
        )

    def _build_schedule(
        self,
        day_input: DayInput,
        apsp: Tuple[List[List[int]], List[List[int]], List[List[int]]],
        apsp_fuel: Tuple[List[List[int]], List[List[int]], List[List[int]]],
        refuel_threshold: float,
        noise: float,
        cluster_bias: float,
        lookahead_weight: float = 0.25,
        apsp_refuel: Optional[Tuple[List[List[int]], List[List[int]], List[List[int]]]] = None,
        scarcity_weight: float = 0.0,
        gravity_weight: float = 0.0,
        use_2opt: bool = False,
        forced_tours: Optional[Dict[int, List[int]]] = None,
    ) -> Tuple[List[List[Action]], Dict[int, List[int]]]:
        dist_steps, dist_fuel, parents = apsp
        f_dist_steps, f_dist_fuel, f_parents = apsp_fuel
        r_dist_steps, _, r_parents = apsp_refuel if apsp_refuel is not None else apsp

        builders: List[_AgentPlanBuilder] = [
            _AgentPlanBuilder(
                agent_id=ag.agent_id,
                role=ag.role,
                start_cell=ag.cell_id,
                start_fuel=ag.fuel,
                max_steps=day_input.max_steps,
                max_fuel=self.config.max_fuel,
            )
            for ag in day_input.agents
        ]

        patrol_builders = [b for b in builders if b.role == AgentRole.PATROL]
        refuel_builders = [b for b in builders if b.role == AgentRole.REFUEL]

        spot_stocks = dict(day_input.spot_stocks)
        chains_overall = set(day_input.collected_chains_overall)
        chains_today: Set[int] = set()

        # Fix for Audit Issue 1:
        # If a Patrol Car starts the day (step = 0) already standing on a Spot cell `s` (which is always PLAIN,
        # taking 2 steps to move out of, or waiting at `s`), then at the end of Step 1 in `engine.py` it is STILL
        # on cell `s` and automatically collects 1 Udon at `s`!
        # Only record this when `use_2opt` or `forced_tours` is active (or when `pb` takes its first action on `s`).
        patrol_anchors = {pb.agent_id: pb.cell for pb in patrol_builders}

        forced_queues: Dict[int, List[int]] = {
            pid: list(seq) for pid, seq in (forced_tours or {}).items()
        }

        gravity_potentials = (
            self.heuristics.compute_gravity_potential(
                dist_steps, spot_stocks, chains_today, chains_overall
            )
            if gravity_weight > 0.0
            else {}
        )

        max_iters = day_input.max_steps * len(builders) * 2
        iters = 0

        while iters < max_iters:
            iters += 1
            active_patrols = [
                pb for pb in patrol_builders if pb.remaining_steps > 0 and not pb.finished_active_tour
            ]
            if not active_patrols:
                break

            active_patrols.sort(key=lambda b: (b.step, b.agent_id))
            pb = active_patrols[0]

            if scarcity_weight > 0.0 or gravity_weight > 0.0:
                refuel_cells = [rb.cell for rb in refuel_builders]
                fuel_shadow_price = self.heuristics.compute_dynamic_fuel_shadow_price(
                    pb.cell, pb.fuel, refuel_cells, r_dist_steps
                )
            else:
                fuel_shadow_price = 0.32

            best_spot_target: Optional[int] = None
            best_spot_partner: Optional[int] = None
            best_spot_score = -1e18
            best_use_fuel_path = False

            # Check if this Patrol Car has a forced target spot from `forced_tours` Local Search
            fq = forced_queues.get(pb.agent_id, [])
            while fq and (fq[0] in pb.visited_spots or spot_stocks.get(fq[0], 0) <= 0):
                fq.pop(0)

            if fq:
                cand_sc = fq[0]
                s_cost = dist_steps[pb.cell][cand_sc]
                f_cost = dist_fuel[pb.cell][cand_sc]
                if f_cost <= pb.fuel and max(1, s_cost) <= pb.remaining_steps:
                    best_spot_target = cand_sc
                    best_use_fuel_path = False
                    fq.pop(0)
                elif f_dist_fuel[pb.cell][cand_sc] <= pb.fuel and max(1, f_dist_steps[pb.cell][cand_sc]) <= pb.remaining_steps:
                    best_spot_target = cand_sc
                    best_use_fuel_path = True
                    fq.pop(0)

            if best_spot_target is None:
                for sc, spot in self.config.spots.items():
                    if spot_stocks.get(sc, 0) <= 0:
                        continue
                    if sc in pb.visited_spots:
                        continue

                    s_cost = dist_steps[pb.cell][sc]
                    f_cost = dist_fuel[pb.cell][sc]
                    use_fuel_map = False

                    if f_cost > pb.fuel or s_cost > pb.remaining_steps:
                        s_cost2 = f_dist_steps[pb.cell][sc]
                        f_cost2 = f_dist_fuel[pb.cell][sc]
                        if f_cost2 <= pb.fuel and s_cost2 <= pb.remaining_steps:
                            s_cost = s_cost2
                            f_cost = f_cost2
                            use_fuel_map = True
                        else:
                            continue

                    eff_steps = max(1, s_cost)
                    if eff_steps > pb.remaining_steps:
                        continue

                    is_new_global = (spot.chain_id not in chains_overall) and (spot.chain_id not in chains_today)
                    is_new_daily = spot.chain_id not in chains_today

                    reward = 100.0
                    if is_new_global:
                        reward += 1_000_000.0
                    if is_new_daily:
                        reward += 15_000.0

                    if scarcity_weight > 0.0 and is_new_daily:
                        scarcity = self.heuristics.chain_scarcity.get(spot.chain_id, 0.5)
                        isolation = self.heuristics.spot_isolation.get(sc, 0.5)
                        reward *= 1.0 + scarcity_weight * (0.7 * scarcity + 0.3 * isolation)

                    if is_new_daily and len(patrol_builders) > 1:
                        other_min_steps = 10**9
                        for other_pb in patrol_builders:
                            if other_pb.agent_id == pb.agent_id or other_pb.remaining_steps <= 0:
                                continue
                            d_other = dist_steps[other_pb.cell][sc]
                            f_other = dist_fuel[other_pb.cell][sc]
                            if d_other <= other_pb.remaining_steps and f_other <= other_pb.fuel:
                                other_arrival = other_pb.step + d_other
                                if other_arrival < other_min_steps:
                                    other_min_steps = other_arrival
                        my_arrival = pb.step + eff_steps
                        if other_min_steps + 2 < my_arrival:
                            reward *= 0.80
                        elif use_2opt and other_min_steps < 10**8 and other_min_steps > my_arrival + 2:
                            regret_gap = min(12, other_min_steps - my_arrival)
                            reward *= 1.0 + 0.025 * regret_gap

                    rem_after = pb.remaining_steps - eff_steps
                    fuel_after = pb.fuel - f_cost
                    lookahead_bonus = 0.0
                    best_next_spot_for_sc: Optional[int] = None
                    if lookahead_weight > 0.0 and rem_after >= 2 and fuel_after >= 1:
                        best_next_val = 0.0
                        for sc2, spot2 in self.config.spots.items():
                            if sc2 == sc or sc2 in pb.visited_spots or spot_stocks.get(sc2, 0) <= 0:
                                continue
                            d2 = dist_steps[sc][sc2]
                            f2 = dist_fuel[sc][sc2]
                            if d2 <= rem_after and f2 <= fuel_after:
                                r2 = 100.0
                                if spot2.chain_id != spot.chain_id:
                                    if (spot2.chain_id not in chains_overall) and (spot2.chain_id not in chains_today):
                                        r2 += 500_000.0
                                    elif spot2.chain_id not in chains_today:
                                        r2 += 8_000.0
                                val2 = r2 / (d2 + fuel_shadow_price * f2 + 1.0)
                                if val2 > best_next_val:
                                    best_next_val = val2
                                    best_next_spot_for_sc = sc2
                        lookahead_bonus = lookahead_weight * best_next_val

                    grav_bonus = gravity_weight * gravity_potentials.get(sc, 0.0)
                    score = (reward / (eff_steps + fuel_shadow_price * f_cost + 1.0)) + lookahead_bonus + grav_bonus

                    if cluster_bias > 0.0:
                        anchor_d = dist_steps[patrol_anchors[pb.agent_id]][sc]
                        score -= cluster_bias * anchor_d

                    if noise > 0.0:
                        score *= 1.0 + self.rng.uniform(-noise, noise)
                    score *= self.spot_bias.get((day_input.day, sc), 1.0)

                    if score > best_spot_score:
                        best_spot_score = score
                        best_spot_target = sc
                        best_spot_partner = best_next_spot_for_sc
                        best_use_fuel_path = use_fuel_map

            needs_refuel = (
                best_spot_target is None
                or (
                    pb.fuel <= int(self.config.max_fuel * refuel_threshold)
                    and len(refuel_builders) > 0
                    and pb.remaining_steps >= 3
                )
            )

            if needs_refuel and refuel_builders:
                if self._try_schedule_rendezvous(
                    pb=pb,
                    refuel_builders=refuel_builders,
                    day_input=day_input,
                    apsp=apsp,
                    apsp_fuel=apsp_fuel,
                    apsp_refuel=apsp_refuel if apsp_refuel is not None else apsp,
                    spot_stocks=spot_stocks,
                    chains_today=chains_today,
                ):
                    continue

            if best_spot_target is not None:
                if (
                    use_2opt
                    and not best_use_fuel_path
                    and best_spot_partner is not None
                    and best_spot_partner != pb.cell
                ):
                    s1 = best_spot_target
                    s2 = best_spot_partner
                    c1 = self.config.spots[s1].chain_id
                    c2 = self.config.spots[s2].chain_id
                    tier1 = (2 if (c1 not in chains_overall and c1 not in chains_today) else (1 if c1 not in chains_today else 0))
                    tier2 = (2 if (c2 not in chains_overall and c2 not in chains_today) else (1 if c2 not in chains_today else 0))
                    if tier2 >= tier1:
                        d_12 = dist_steps[pb.cell][s1] + dist_steps[s1][s2]
                        d_21 = dist_steps[pb.cell][s2] + dist_steps[s2][s1]
                        f_21 = dist_fuel[pb.cell][s2] + dist_fuel[s2][s1]
                        if d_21 < d_12 and d_21 <= pb.remaining_steps and f_21 <= pb.fuel:
                            best_spot_target = s2

                if use_2opt and not best_use_fuel_path and pb.cell != best_spot_target:
                    via_w = self.heuristics.find_best_via_spot(
                        u=pb.cell,
                        target_v=best_spot_target,
                        visited_spots=pb.visited_spots,
                        spot_stocks=spot_stocks,
                        chains_today=chains_today,
                        chains_overall=chains_overall,
                        remaining_steps=pb.remaining_steps,
                        remaining_fuel=pb.fuel,
                        dist_steps=dist_steps,
                        dist_fuel=dist_fuel,
                    )
                    if via_w is not None:
                        best_spot_target = via_w

                par_mat = f_parents if best_use_fuel_path else parents
                if pb.cell == best_spot_target:
                    pb.add_wait(1)
                    self._record_spot_collection(pb, best_spot_target, spot_stocks, chains_today)
                else:
                    # Audit Fix 1: If starting Step 1 from a Spot cell `pb.cell` (which is PLAIN, 2 steps),
                    # moving out of `pb.cell` leaves `pb` on `pb.cell` at the end of Step 1, collecting it!
                    if use_2opt and pb.step == 0 and pb.cell in self.config.spots:
                        self._record_spot_collection(pb, pb.cell, spot_stocks, chains_today)

                    path = self.grid.reconstruct_path(par_mat[pb.cell], pb.cell, best_spot_target)
                    moved_ok = True
                    for next_c in path:
                        t_u = self.config.terrains[pb.cell]
                        rs_u = day_input.road_states.get(pb.cell, RoadState.SMOOTH)
                        if not pb.add_move(next_c, t_u, rs_u):
                            moved_ok = False
                            break
                        if pb.cell in self.config.spots:
                            self._record_spot_collection(pb, pb.cell, spot_stocks, chains_today)
                    if not moved_ok:
                        pb.finished_active_tour = True
                continue

            if refuel_builders and pb.fuel < self.config.max_fuel:
                if self._try_schedule_rendezvous(
                    pb=pb,
                    refuel_builders=refuel_builders,
                    day_input=day_input,
                    apsp=apsp,
                    apsp_fuel=apsp_fuel,
                    apsp_refuel=apsp_refuel if apsp_refuel is not None else apsp,
                    spot_stocks=spot_stocks,
                    chains_today=chains_today,
                ):
                    continue

            pb.finished_active_tour = True

        # Step Patrol Cars off ROAD cells before end-of-day waiting (preserving `pb.step` arrival time!)
        for pb in patrol_builders:
            self._step_off_road_if_needed(pb, day_input)

        # Audit Fix 2: Time-Synchronized End-of-Day Refuel Car Intercept!
        # `pb.step` is the EXACT step when `pb` arrives at its final cell `pb.cell` and starts waiting!
        # When `rb` moves to `pb.cell` (arriving at `t_rb_arr`), `rb` MUST wait until `t_meet = max(rb.step, pb.step)`
        # plus 1 full overlap step (`t_meet + 1 <= max_steps`) before moving on to another car!
        for rb in refuel_builders:
            while rb.remaining_steps > 0:
                target_pb = None
                best_finish_step = 10**9
                for pb in patrol_builders:
                    if pb.fuel < self.config.max_fuel:
                        d_s = r_dist_steps[rb.cell][pb.cell]
                        t_rb_arr = rb.step + d_s
                        t_meet = max(t_rb_arr, pb.step)
                        if t_meet + 1 <= day_input.max_steps and t_meet + 1 < best_finish_step:
                            best_finish_step = t_meet + 1
                            target_pb = pb

                if target_pb is not None:
                    path = self.grid.reconstruct_path(r_parents[rb.cell], rb.cell, target_pb.cell)
                    moved = True
                    for next_c in path:
                        t_u = self.config.terrains[rb.cell]
                        rs_u = day_input.road_states.get(rb.cell, RoadState.SMOOTH)
                        if not rb.add_move(next_c, t_u, rs_u):
                            moved = False
                            break
                    if moved and rb.cell == target_pb.cell:
                        # Wait until `target_pb` actually arrives at `target_pb.cell`!
                        if rb.step < target_pb.step:
                            rb.add_wait(target_pb.step - rb.step)
                        if rb.remaining_steps >= 1:
                            rb.add_wait(1)
                            target_pb.fuel = self.config.max_fuel
                            continue
                break

            self._step_off_road_if_needed(rb, day_input)
            rb.pad_to_end_of_day()

        # Finally pad all Patrol Cars to `max_steps`
        for pb in patrol_builders:
            pb.pad_to_end_of_day()

        tours_map = {pb.agent_id: list(pb.ordered_spots) for pb in patrol_builders}
        return [b.actions for b in builders], tours_map

    def _step_off_road_if_needed(self, b: _AgentPlanBuilder, day_input: DayInput) -> None:
        if self.config.terrains[b.cell] != TerrainType.ROAD:
            return
        rs_u = day_input.road_states.get(b.cell, RoadState.SMOOTH)
        req_s = get_terrain_step_cost(TerrainType.ROAD, rs_u)
        req_f = get_terrain_fuel_cost(TerrainType.ROAD)
        if b.remaining_steps < req_s:
            return
        if b.role == AgentRole.PATROL and b.fuel < req_f + 2:
            return

        plain_nbrs = [
            v for v in self.grid.passable_neighbors[b.cell]
            if self.config.terrains[v] == TerrainType.PLAIN
        ]
        if plain_nbrs:
            plain_nbrs.sort(key=lambda v: (0 if v in self.config.spots else 1, v))
            b.add_move(plain_nbrs[0], TerrainType.ROAD, rs_u)

    def _record_spot_collection(
        self,
        pb: _AgentPlanBuilder,
        cell_id: int,
        spot_stocks: Dict[int, int],
        chains_today: Set[int],
    ) -> None:
        if cell_id in self.config.spots and cell_id not in pb.visited_spots:
            if spot_stocks.get(cell_id, 0) > 0:
                pb.visited_spots.add(cell_id)
                pb.ordered_spots.append(cell_id)
                spot_stocks[cell_id] -= 1
                chains_today.add(self.config.spots[cell_id].chain_id)

    def _try_schedule_rendezvous(
        self,
        pb: _AgentPlanBuilder,
        refuel_builders: List[_AgentPlanBuilder],
        day_input: DayInput,
        apsp: Tuple[List[List[int]], List[List[int]], List[List[int]]],
        apsp_fuel: Tuple[List[List[int]], List[List[int]], List[List[int]]],
        spot_stocks: Dict[int, int],
        chains_today: Set[int],
        apsp_refuel: Optional[Tuple[List[List[int]], List[List[int]], List[List[int]]]] = None,
    ) -> bool:
        dist_steps, dist_fuel, parents = apsp
        f_dist_steps, f_dist_fuel, f_parents = apsp_fuel
        r_dist_steps, _, r_parents = apsp_refuel if apsp_refuel is not None else apsp

        best_choice: Optional[Tuple[float, _AgentPlanBuilder, int, int]] = None

        for rb in refuel_builders:
            if rb.remaining_steps <= 0:
                continue

            if self.config.num_cells <= 256:
                candidate_cells = range(self.config.num_cells)
            else:
                # On large maps (e.g. 32x32 = 1024 cells), candidate meeting cells are:
                # 1. pb.cell, rb.cell, and passable neighbors of pb.cell
                # 2. All Spot cells (for In-Route Spot Tankering)
                # 3. All cells along the shortest path between rb.cell and pb.cell (meeting halfway)
                c_set = {pb.cell, rb.cell}
                c_set.update(self.grid.passable_neighbors[pb.cell])
                c_set.update(self.config.spots.keys())
                cur = pb.cell
                par_rb = r_parents[rb.cell]
                while cur != -1 and cur != rb.cell:
                    c_set.add(cur)
                    cur = par_rb[cur]
                candidate_cells = c_set

            for m in candidate_cells:
                if not self.grid.is_passable(m):
                    continue

                path_type = 1
                pb_s = dist_steps[pb.cell][m]
                pb_f = dist_fuel[pb.cell][m]
                if pb_f > pb.fuel:
                    path_type = 2
                    pb_s = f_dist_steps[pb.cell][m]
                    pb_f = f_dist_fuel[pb.cell][m]
                    if pb_f > pb.fuel:
                        continue

                rb_s = r_dist_steps[rb.cell][m]
                t_pb_arr = pb.step + pb_s
                t_rb_arr = rb.step + rb_s
                t_meet = max(t_pb_arr, t_rb_arr)

                t_done = t_meet + 1
                if t_done > day_input.max_steps:
                    continue

                spot_bonus = 0.0
                if m in self.config.spots and m not in pb.visited_spots and spot_stocks.get(m, 0) > 0:
                    sp = self.config.spots[m]
                    if sp.chain_id not in day_input.collected_chains_overall and sp.chain_id not in chains_today:
                        spot_bonus = 3.0
                    elif sp.chain_id not in chains_today:
                        spot_bonus = 2.0
                    else:
                        spot_bonus = 1.5

                effective_cost = float(t_done) - spot_bonus
                if best_choice is None or effective_cost < best_choice[0]:
                    best_choice = (effective_cost, rb, m, path_type)

        if best_choice is None:
            return False

        _, rb, m, path_type = best_choice
        pb_par = parents[pb.cell] if path_type == 1 else f_parents[pb.cell]
        rb_par = r_parents[rb.cell]

        pb_path = self.grid.reconstruct_path(pb_par, pb.cell, m)
        rb_path = self.grid.reconstruct_path(rb_par, rb.cell, m)

        for next_c in pb_path:
            t_u = self.config.terrains[pb.cell]
            rs_u = day_input.road_states.get(pb.cell, RoadState.SMOOTH)
            if not pb.add_move(next_c, t_u, rs_u):
                return False
            if pb.cell in self.config.spots:
                self._record_spot_collection(pb, pb.cell, spot_stocks, chains_today)

        for next_c in rb_path:
            t_u = self.config.terrains[rb.cell]
            rs_u = day_input.road_states.get(rb.cell, RoadState.SMOOTH)
            if not rb.add_move(next_c, t_u, rs_u):
                return False

        t_meet = max(pb.step, rb.step)
        if pb.step < t_meet:
            pb.add_wait(t_meet - pb.step)
        if rb.step < t_meet:
            rb.add_wait(t_meet - rb.step)

        if pb.remaining_steps >= 1 and rb.remaining_steps >= 1:
            pb.add_wait(1)
            rb.add_wait(1)
            pb.fuel = self.config.max_fuel
            if m in self.config.spots:
                self._record_spot_collection(pb, m, spot_stocks, chains_today)
            return True

        return False
