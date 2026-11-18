"""Match runner and contest server HTTP/JSON client for Procon 2026 HEXUDON."""

from __future__ import annotations
import json
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Set

from .engine import HexudonEngine
from .models import (
    Action,
    AgentRole,
    AgentState,
    DayInput,
    DayResult,
    MapConfig,
    MatchScore,
    RoadState,
)
from .solver import HexudonSolver


class MatchRunner:
    """
    Runs a complete multi-day HEXUDON match using `HexudonEngine` and `HexudonSolver`,
    recording full replay data for analysis and visualization.
    """

    def __init__(self, config: MapConfig, solver: Optional[HexudonSolver] = None):
        self.config = config
        self.engine = HexudonEngine(config)
        self.solver = solver or HexudonSolver(config)

    def run_match(self, time_budget_ms_per_day: float = 150.0) -> Dict[str, Any]:
        # Step 1: Pre-match role assignment
        self.solver.plan_budget_ms = time_budget_ms_per_day
        roles = self.solver.select_roles()
        agents = self.engine.create_initial_agents(roles)

        collected_chains_overall: Set[int] = set()
        cumulative_daily_unique_chains = 0
        total_portions = 0
        total_response_time_ms = 0.0
        history_road_stays: List[Dict[int, int]] = []
        day_results: List[DayResult] = []
        daily_logs: List[Dict[str, Any]] = []

        for day in range(1, self.config.num_days + 1):
            max_steps = self.config.steps_per_day[day - 1]
            road_states = self.engine.compute_road_states(history_road_stays, day)
            spot_stocks = {
                cell_id: spot.max_stock for cell_id, spot in self.config.spots.items()
            }

            day_input = DayInput(
                day=day,
                max_steps=max_steps,
                agents=[a.clone() for a in agents],
                road_states=road_states,
                spot_stocks=spot_stocks,
                collected_chains_overall=set(collected_chains_overall),
                daily_unique_chains_sum=cumulative_daily_unique_chains,
                total_portions=total_portions,
            )

            t0 = time.perf_counter()
            actions = self.solver.plan_day(day_input, time_budget_ms=time_budget_ms_per_day)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            total_response_time_ms += elapsed_ms

            res = self.engine.simulate_day(day_input, actions, record_frames=True)
            if not res.valid:
                raise RuntimeError(f"Day {day} produced invalid actions: {res.error_message}")

            day_results.append(res)
            history_road_stays.append(res.road_stay_steps)
            agents = [a.clone() for a in res.agents_end]

            collected_chains_overall |= res.chains_collected_today
            cumulative_daily_unique_chains += len(res.chains_collected_today)
            total_portions += res.portions_collected_today

            daily_logs.append(
                {
                    "day": day,
                    "max_steps": max_steps,
                    "response_time_ms": round(elapsed_ms, 2),
                    "road_states": {str(k): int(v) for k, v in road_states.items()},
                    "actions": [[a.to_dict() for a in ag_acts] for ag_acts in actions],
                    "chains_collected_today": sorted(res.chains_collected_today),
                    "portions_collected_today": res.portions_collected_today,
                    "cumulative_unique_chains": len(collected_chains_overall),
                    "frames": [
                        {
                            "step": f.step,
                            "agent_cells": f.agent_cells,
                            "agent_fuels": f.agent_fuels,
                            "spot_stocks": {str(k): v for k, v in f.spot_stocks.items()},
                            "collected_chains_today": f.collected_chains_today,
                            "refueled_agents": f.refueled_agents,
                            "collected_events": f.collected_events,
                        }
                        for f in res.frames
                    ],
                }
            )

        score = MatchScore(
            unique_chains_total=len(collected_chains_overall),
            cumulative_daily_unique_chains=cumulative_daily_unique_chains,
            total_portions=total_portions,
            total_response_time_ms=total_response_time_ms,
        )

        return {
            "config": self.config.to_dict(),
            "roles": [r.value for r in roles],
            "score": score.to_dict(),
            "total_chains_available": len(self.config.all_chain_ids),
            "days": daily_logs,
        }


class ContestApiClient:
    """
    HTTP/JSON client adapter for communicating with the Procon Contest Server.
    Follows the 6-step match progression defined in the specification:
      1. Fetch initial MapConfig & submit AgentRoles.
      2. For each day d = 1..num_days:
         - Fetch DayInput (agent positions, fuel, road traffic states).
         - Compute & validate actions via HexudonSolver.
         - Submit actions before the day's response deadline.
    """

    def __init__(self, base_url: str, token: str, timeout_sec: float = 5.0):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout_sec = timeout_sec

    def _request(self, method: str, path: str, payload: Optional[dict] = None) -> dict:
        url = f"{self.base_url}/{path.lstrip('/')}"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}",
            "X-API-Token": self.token,
        }
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def get_map_config(self, match_id: str) -> MapConfig:
        raw = self._request("GET", f"/matches/{match_id}/config")
        return MapConfig.from_dict(raw)

    def submit_roles(self, match_id: str, roles: List[AgentRole]) -> dict:
        payload = {"roles": [r.value for r in roles]}
        return self._request("POST", f"/matches/{match_id}/roles", payload)

    def submit_day_actions(
        self, match_id: str, day: int, actions: List[List[Action]]
    ) -> dict:
        payload = {
            "day": day,
            "actions": [[a.to_dict() for a in ag_acts] for ag_acts in actions],
        }
        return self._request("POST", f"/matches/{match_id}/days/{day}/actions", payload)

    def plan_and_submit_dual_commit(
        self,
        match_id: str,
        day_input: DayInput,
        solver: HexudonSolver,
        deep_budget_ms: float = 500.0,
    ) -> List[List[Action]]:
        """
        Championship Dual-Commit Strategy for Priority 4 + Note 5 & 6:
          1. Ultra-Fast Commit (~15-30ms): Immediately compute & submit a valid high-quality plan
             to lock in an ultra-low response timestamp on the contest server.
          2. Conditional Deep Upgrade: Run deeper rollout search; ONLY resubmit if the new plan
             achieves a STRICTLY HIGHER (F1, F2, F3) tuple (never resubmit on ties, preserving
             the fast response timestamp from Commit 1!).
        """
        # Commit 1: Fast deterministic pass
        fast_actions = solver.plan_day(day_input, time_budget_ms=15.0)
        fast_res = solver.engine.simulate_day(day_input, fast_actions, record_frames=False)
        self.submit_day_actions(match_id, day_input.day, fast_actions)

        fast_f123 = (
            len(day_input.collected_chains_overall | fast_res.chains_collected_today),
            len(fast_res.chains_collected_today),
            fast_res.portions_collected_today,
        )

        # Commit 2: Deep lookahead search
        deep_actions = solver.plan_day(day_input, time_budget_ms=deep_budget_ms)
        deep_res = solver.engine.simulate_day(day_input, deep_actions, record_frames=False)
        if deep_res.valid:
            deep_f123 = (
                len(day_input.collected_chains_overall | deep_res.chains_collected_today),
                len(deep_res.chains_collected_today),
                deep_res.portions_collected_today,
            )
            if deep_f123 > fast_f123:
                self.submit_day_actions(match_id, day_input.day, deep_actions)
                return deep_actions

        return fast_actions
