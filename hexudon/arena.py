"""
Multi-Team Simultaneous Adversarial Arena for Procon 2026 HEXUDON.
Pits our Audited Grandmaster Solver against genuinely distinct algorithmic bots
(Voronoi Cluster + 2-Opt TSP Bot, Global Chain-Auction Bot, and Fast Dijkstra Greedy Bot)
under simultaneous shared road traffic.
"""

from __future__ import annotations
from dataclasses import dataclass
import time
from typing import Any, Callable, Dict, List, Set

from .engine import HexudonEngine
from .heuristics import optimize_spot_sequence_2opt
from .models import (
    Action,
    AgentRole,
    AgentState,
    DayInput,
    MapConfig,
    MatchScore,
    RoadState,
)
from .solver import HexudonSolver


@dataclass
class BotCompetitor:
    name: str
    select_roles_fn: Callable[[], List[AgentRole]]
    plan_day_fn: Callable[[DayInput], List[List[Action]]]


class MultiTeamArena:
    """
    Simultaneous multi-team match simulator matching official Procon 2026 rules.
    """

    def __init__(self, config: MapConfig):
        self.config = config
        self.engine = HexudonEngine(config)

    def create_standard_competitors(self) -> List[BotCompetitor]:
        champ_solver = HexudonSolver(self.config, seed=42)
        cluster_solver = HexudonSolver(self.config, seed=101)
        auction_solver = HexudonSolver(self.config, seed=202)
        greedy_solver = HexudonSolver(self.config, seed=303)

        def _cluster_2opt_plan(day_input: DayInput) -> List[List[Action]]:
            """
            Independent Algorithm: Voronoi Territory Partitioning + TSP 2-Opt Tour per Patrol Car.
            Partitions spots among Patrol Cars by proximity, solves TSP 2-Opt on each car's cluster,
            and decodes into valid actions with refueling.
            """
            apsp_s = cluster_solver._compute_apsp(day_input.road_states, mode="steps")
            apsp_f = cluster_solver._compute_apsp(day_input.road_states, mode="fuel")
            dist_s, dist_f, _ = apsp_s

            patrol_agents = [ag for ag in day_input.agents if ag.role == AgentRole.PATROL]
            clusters: Dict[int, List[int]] = {ag.agent_id: [] for ag in patrol_agents}

            # Sort spots so unvisited chains are assigned first
            sorted_spots = sorted(
                self.config.spots.values(),
                key=lambda sp: (
                    0 if sp.chain_id not in day_input.collected_chains_overall else 1,
                    sp.cell_id,
                ),
            )
            for sp in sorted_spots:
                if not patrol_agents:
                    break
                best_ag = min(
                    patrol_agents,
                    key=lambda ag: dist_s[ag.cell_id][sp.cell_id] + len(clusters[ag.agent_id]) * 3,
                )
                clusters[best_ag.agent_id].append(sp.cell_id)

            forced_tours: Dict[int, List[int]] = {}
            for ag in patrol_agents:
                raw_seq = clusters[ag.agent_id]
                # Order by nearest neighbor from ag.cell_id, then refine with 2-Opt
                nn_seq: List[int] = []
                rem = list(raw_seq)
                cur = ag.cell_id
                while rem:
                    nxt = min(rem, key=lambda sc: dist_s[cur][sc])
                    nn_seq.append(nxt)
                    rem.remove(nxt)
                    cur = nxt
                forced_tours[ag.agent_id] = optimize_spot_sequence_2opt(
                    start_cell=ag.cell_id,
                    spot_seq=nn_seq,
                    dist_steps=dist_s,
                    dist_fuel=dist_f,
                    max_fuel_budget=self.config.max_fuel * 3,
                )

            acts, _ = cluster_solver._build_schedule(
                day_input=day_input,
                apsp=apsp_s,
                apsp_fuel=apsp_f,
                refuel_threshold=0.35,
                noise=0.0,
                cluster_bias=0.20,
                lookahead_weight=0.0,
                apsp_refuel=apsp_s,
                scarcity_weight=0.0,
                gravity_weight=0.0,
                use_2opt=True,
                forced_tours=forced_tours,
            )
            return acts

        def _auction_plan(day_input: DayInput) -> List[List[Action]]:
            """
            Independent Algorithm: Balanced-Cost Multi-Agent Chain Auction + Regret-2 + Gravity Field.
            """
            apsp_bal = auction_solver._compute_apsp(day_input.road_states, mode="balanced")
            apsp_s = auction_solver._compute_apsp(day_input.road_states, mode="steps")
            apsp_f = auction_solver._compute_apsp(day_input.road_states, mode="fuel")
            acts, _ = auction_solver._build_schedule(
                day_input=day_input,
                apsp=apsp_bal,
                apsp_fuel=apsp_f,
                refuel_threshold=0.40,
                noise=0.0,
                cluster_bias=0.25,
                lookahead_weight=0.25,
                apsp_refuel=apsp_s,
                scarcity_weight=0.40,
                gravity_weight=20.0,
                use_2opt=True,
            )
            return acts

        def _greedy_plan(day_input: DayInput) -> List[List[Action]]:
            apsp_s = greedy_solver._compute_apsp(day_input.road_states, mode="steps")
            apsp_f = greedy_solver._compute_apsp(day_input.road_states, mode="fuel")
            acts, _ = greedy_solver._build_schedule(
                day_input=day_input,
                apsp=apsp_s,
                apsp_fuel=apsp_f,
                refuel_threshold=0.30,
                noise=0.0,
                cluster_bias=0.0,
                lookahead_weight=0.0,
                apsp_refuel=apsp_s,
                scarcity_weight=0.0,
                gravity_weight=0.0,
                use_2opt=False,
            )
            return acts

        return [
            BotCompetitor(
                name="1. Grandmaster Solver (Audited Full Local Search + 1-Day Lookahead)",
                select_roles_fn=lambda: champ_solver.select_roles(use_simulation_rollout=True),
                plan_day_fn=lambda di: champ_solver.plan_day(di, time_budget_ms=110.0),
            ),
            BotCompetitor(
                name="2. Multi-Agent Chain-Auction + Gravity Field Bot",
                select_roles_fn=lambda: auction_solver.select_roles(use_simulation_rollout=False),
                plan_day_fn=_auction_plan,
            ),
            BotCompetitor(
                name="3. Voronoi Territory Partition + TSP 2-Opt Bot",
                select_roles_fn=lambda: cluster_solver.select_roles(use_simulation_rollout=False),
                plan_day_fn=_cluster_2opt_plan,
            ),
            BotCompetitor(
                name="4. Fast Dijkstra Greedy Orienteering Bot",
                select_roles_fn=lambda: greedy_solver.select_roles(use_simulation_rollout=False),
                plan_day_fn=_greedy_plan,
            ),
        ]

    def run_tournament(self, competitors: List[BotCompetitor] | None = None) -> Dict[str, Any]:
        if competitors is None:
            competitors = self.create_standard_competitors()

        num_teams = len(competitors)
        self.config.num_teams = num_teams

        team_agents: List[List[AgentState]] = []
        team_chains_overall: List[Set[int]] = [set() for _ in range(num_teams)]
        team_daily_unique_sum: List[int] = [0] * num_teams
        team_portions: List[int] = [0] * num_teams
        team_time_ms: List[float] = [0.0] * num_teams

        for comp in competitors:
            roles = comp.select_roles_fn()
            team_agents.append(self.engine.create_initial_agents(roles))

        combined_road_history: List[Dict[int, int]] = []
        congested_days_log: List[Dict[str, int]] = []

        for day in range(1, self.config.num_days + 1):
            max_steps = self.config.steps_per_day[day - 1]
            road_states = self.engine.compute_road_states(combined_road_history, day)

            n_smooth = sum(1 for s in road_states.values() if s == RoadState.SMOOTH)
            n_cong = sum(1 for s in road_states.values() if s == RoadState.CONGESTED)
            n_jam = sum(1 for s in road_states.values() if s == RoadState.JAM)
            congested_days_log.append({"day": day, "smooth": n_smooth, "congested": n_cong, "jam": n_jam})

            combined_stays_today: Dict[int, int] = {}

            for t_idx, comp in enumerate(competitors):
                day_input = DayInput(
                    day=day,
                    max_steps=max_steps,
                    agents=[a.clone() for a in team_agents[t_idx]],
                    road_states=dict(road_states),
                    spot_stocks={cid: sp.max_stock for cid, sp in self.config.spots.items()},
                    collected_chains_overall=set(team_chains_overall[t_idx]),
                    daily_unique_chains_sum=team_daily_unique_sum[t_idx],
                    total_portions=team_portions[t_idx],
                )

                t0 = time.perf_counter()
                actions = comp.plan_day_fn(day_input)
                elapsed = (time.perf_counter() - t0) * 1000.0
                team_time_ms[t_idx] += elapsed

                res = self.engine.simulate_day(day_input, actions, record_frames=False)
                if not res.valid:
                    raise RuntimeError(f"Bot {comp.name} invalid on Day {day}: {res.error_message}")

                team_agents[t_idx] = res.agents_end
                team_chains_overall[t_idx] |= res.chains_collected_today
                team_daily_unique_sum[t_idx] += len(res.chains_collected_today)
                team_portions[t_idx] += res.portions_collected_today

                for u, st in res.road_stay_steps.items():
                    combined_stays_today[u] = combined_stays_today.get(u, 0) + st

            combined_road_history.append(combined_stays_today)

        standings = []
        for t_idx, comp in enumerate(competitors):
            score = MatchScore(
                unique_chains_total=len(team_chains_overall[t_idx]),
                cumulative_daily_unique_chains=team_daily_unique_sum[t_idx],
                total_portions=team_portions[t_idx],
                total_response_time_ms=team_time_ms[t_idx],
            )
            standings.append(
                {
                    "team_name": comp.name,
                    "score": score,
                    "comparison_key": score.comparison_key(),
                }
            )

        standings.sort(key=lambda x: x["comparison_key"], reverse=True)
        return {
            "standings": standings,
            "road_traffic_summary": congested_days_log,
            "total_chains": len(self.config.all_chain_ids),
        }
