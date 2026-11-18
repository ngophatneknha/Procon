"""Official-format adapter tests (examples taken from KOSEN schema.pdf)."""
import unittest

from hexudon.engine import HexGrid, HexudonEngine
from hexudon.generator import generate_map_config
from hexudon.models import AgentRole, RoadState
from hexudon.protocol import (
    actions_from_official, actions_to_official, config_from_official, day_from_official,
    direction_of, neighbor, roles_from_official, types_to_official,
)
from hexudon.solver import HexudonSolver

EXAMPLE_CONFIG = {
    "startsAt": 1778227200, "daySeconds": [5, 5, 5, 10], "daySteps": [50, 100, 150, 200],
    "map": {"height": 8, "width": 8, "cells": [[3, 0, 1, 2, 0, 1, 2, 0]] * 8},
    "spots": [{"brand": 0, "pos": 1, "stocks": 4}, {"brand": 1, "pos": 9, "stocks": 1},
              {"brand": 0, "pos": 17, "stocks": 1}, {"brand": 1, "pos": 25, "stocks": 3}],
    "agents": [4, 12, 20, 28], "fuelLimits": 20, "players": 8, "busyThreshold": 2, "jammedThreshold": 4,
}
EXAMPLE_DAY = {
    "endsAt": 1778227205, "day": 1,
    "agents": [{"kind": 0, "pos": 1, "fuel": 20}, {"kind": 1, "pos": 1, "fuel": 20},
               {"kind": 0, "pos": 9, "fuel": 10}, {"kind": 0, "pos": 9, "fuel": 0}],
    "others": [], "traffics": [{"pos": 2, "status": 0}, {"pos": 5, "status": 1}, {"pos": 10, "status": 2}],
}


class TestProtocol(unittest.TestCase):
    def test_config_example(self):
        cfg, secs = config_from_official(EXAMPLE_CONFIG)
        self.assertEqual((cfg.width, cfg.height, cfg.num_days, cfg.max_fuel, cfg.num_teams), (8, 8, 4, 20, 8))
        self.assertEqual(cfg.steps_per_day, [50, 100, 150, 200])
        self.assertEqual(secs, [5, 5, 5, 10])
        self.assertEqual(cfg.terrains[0].value, "POND")
        self.assertEqual(cfg.terrains[2].value, "ROAD")
        self.assertEqual(cfg.terrains[3].value, "MOUNTAIN")
        self.assertEqual(cfg.spots[25].max_stock, 3)
        self.assertEqual(cfg.initial_agent_cells, [4, 12, 20, 28])

    def test_day_example(self):
        cfg, _ = config_from_official(EXAMPLE_CONFIG)
        di = day_from_official(EXAMPLE_DAY, cfg, set())
        self.assertEqual((di.day, di.max_steps), (2, 100))
        self.assertEqual([a.role for a in di.agents],
                         [AgentRole.PATROL, AgentRole.REFUEL, AgentRole.PATROL, AgentRole.PATROL])
        self.assertEqual(di.agents[2].fuel, 10)
        self.assertEqual(di.road_states[5], RoadState.CONGESTED)
        self.assertEqual(di.road_states[10], RoadState.JAM)

    def test_directions_match_grid(self):
        grid = HexGrid(10, 9, [__import__("hexudon.models", fromlist=["TerrainType"]).TerrainType.PLAIN] * 90)
        for u in range(90):
            got = {neighbor(10, 9, u, d) for d in range(6)} - {None}
            self.assertEqual(got, set(grid.all_neighbors[u]))
            for v in grid.all_neighbors[u]:
                self.assertEqual(neighbor(10, 9, u, direction_of(10, 9, u, v)), v)
        # direction 0 is upper-left, 1 upper-right, 2 right, 3 lower-right, 4 lower-left, 5 left
        self.assertEqual(neighbor(10, 9, 12, 0), 1)    # odd row, upper-left
        self.assertEqual(neighbor(10, 9, 12, 1), 2)
        self.assertEqual(neighbor(10, 9, 12, 2), 13)
        self.assertEqual(neighbor(10, 9, 22, 0), 12)   # even row, upper-left
        self.assertEqual(neighbor(10, 9, 22, 1), 13)

    def test_roles_and_plan_roundtrip_through_engine(self):
        cfg = generate_map_config(width=10, height=10, num_agents=4, num_spots=12, num_chains=6, num_days=4, seed=5)
        eng = HexudonEngine(cfg)
        roles = [AgentRole.PATROL, AgentRole.PATROL, AgentRole.REFUEL, AgentRole.PATROL]
        self.assertEqual(roles_from_official(types_to_official(roles)), roles)
        solver = HexudonSolver(cfg)
        agents = eng.create_initial_agents(roles)
        from hexudon.models import DayInput
        di = DayInput(day=1, max_steps=cfg.steps_per_day[0], agents=agents,
                      road_states=eng.compute_road_states([], 1),
                      spot_stocks={c: s.max_stock for c, s in cfg.spots.items()})
        acts = solver.plan_day(di, time_budget_ms=80.0)
        plan = actions_to_official(cfg, [a.cell_id for a in agents], acts)
        self.assertTrue(all(isinstance(x, int) for seq in plan for x in seq))
        back = actions_from_official(cfg, [a.cell_id for a in agents], plan)
        r1 = eng.simulate_day(di, acts, record_frames=False)
        r2 = eng.simulate_day(di, back, record_frames=False)
        self.assertTrue(r1.valid and r2.valid)
        self.assertEqual((r1.chains_collected_today, r1.portions_collected_today),
                         (r2.chains_collected_today, r2.portions_collected_today))


if __name__ == "__main__":
    unittest.main()
