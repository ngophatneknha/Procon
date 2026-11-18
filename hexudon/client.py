"""Match runner and contest server HTTP/JSON client for Procon 2026 HEXUDON."""

from __future__ import annotations
import json
import time
import urllib.error
import urllib.parse
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
    """HTTP client for the official HEXUDON server (endpoints from its OpenAPI; formats from schema.pdf).

    Flow: get_config -> select_types -> loop { get_day -> submit_actions }.
    `practice=True` posts to /api/game/practice/actions; use a game id of the form "<game_id>:<team_id>"
    for config/day in practice (see PLATFORM_NOTES.md). The bearer token is the JWT shown by the website.
    """

    def __init__(self, base_url: str, token: str, game_id: str, practice: bool = False, timeout_sec: float = 4.0):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.game_id = game_id
        self.practice = practice
        self.timeout_sec = timeout_sec

    def _request(self, method: str, path: str, payload: Optional[dict] = None, params: Optional[dict] = None) -> Any:
        url = f"{self.base_url}/{path.lstrip('/')}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}

    def get_config(self) -> dict:
        return self._request("GET", "/api/game/config", params={"game_id": self.game_id})

    def select_types(self, types: List[int]) -> Any:
        return self._request("POST", "/api/game/agent-types", {"game_id": self.game_id, "types": types})

    def get_day(self) -> dict:
        return self._request("GET", "/api/game/day", params={"game_id": self.game_id})

    def submit_actions(self, day: int, plan: List[List[int]]) -> Any:
        path = "/api/game/practice/actions" if self.practice else "/api/game/actions"
        return self._request("POST", path, {"game_id": self.game_id, "day": day, "actions": plan})
