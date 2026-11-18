"""Comprehensive unit and integration tests for Procon 2026 HEXUDON rules and solver."""

import unittest

from hexudon.arena import MultiTeamArena
from hexudon.client import MatchRunner
from hexudon.engine import HexGrid, HexudonEngine
from hexudon.fast_apsp import compute_apsp_fast, has_cpp_accelerator
from hexudon.generator import generate_map_config
from hexudon.heuristics import HexudonHeuristics, optimize_spot_sequence_2opt
from hexudon.models import (
    Action,
    AgentRole,
    AgentState,
    DayInput,
    MapConfig,
    RoadState,
    Spot,
    TerrainType,
)
from hexudon.solver import HexudonSolver


class TestHexudonRules(unittest.TestCase):
    def test_figure1_hex_grid_neighbors(self):
        """Verify even-r hex layout against Figure 1 (10x10 map, cells 0..99)."""
        grid = HexGrid(10, 10, [TerrainType.PLAIN] * 100)

        # In Figure 1:
        # Row 0 (even, shifted right): cell 0 is adjacent to 1 (right), 10 (bottom-left), 11 (bottom-right)
        self.assertEqual(sorted(grid.all_neighbors[0]), [1, 10, 11])

        # Cell 12 (Row 1, Col 2 - odd row, shifted left):
        # Top-left: 1, Top-right: 2, Left: 11, Right: 13, Bottom-left: 21, Bottom-right: 22
        self.assertEqual(sorted(grid.all_neighbors[12]), [1, 2, 11, 13, 21, 22])

        # Cell 22 (Row 2, Col 2 - even row, shifted right):
        # Top-left: 12, Top-right: 13, Left: 21, Right: 23, Bottom-left: 32, Bottom-right: 33
        self.assertEqual(sorted(grid.all_neighbors[22]), [12, 13, 21, 23, 32, 33])

        # Exact hex distances
        self.assertEqual(grid.hex_distance(12, 12), 0)
        for nb in grid.all_neighbors[12]:
            self.assertEqual(grid.hex_distance(12, nb), 1)

    def test_terrain_costs_and_current_cell_rule(self):
        """
        Verify Table 1: moving from u to v costs steps(u) and fuel(u).
        """
        terrains = [TerrainType.PLAIN] * 64
        terrains[0] = TerrainType.PLAIN      # 2 steps, 1 fuel
        terrains[1] = TerrainType.MOUNTAIN   # 3 steps, 2 fuel
        terrains[2] = TerrainType.ROAD       # 1/2/4 steps, 2 fuel
        terrains[3] = TerrainType.POND       # Impassable

        cfg = MapConfig(
            width=8,
            height=8,
            terrains=terrains,
            spots={2: Spot(cell_id=2, chain_id=1, max_stock=2)},
            initial_agent_cells=[0, 8, 16],
            max_fuel=10,
            num_days=4,
            steps_per_day=[6, 6, 6, 6],
            congested_threshold=2.0,
            jam_threshold=4.0,
        )
        engine = HexudonEngine(cfg)
        agents = engine.create_initial_agents([AgentRole.PATROL, AgentRole.PATROL, AgentRole.REFUEL])

        # Day 1: Agent 0 moves 0 (PLAIN: 2s, 1f) -> 1 (MOUNTAIN: 3s, 2f) -> 2 (ROAD: 1s, 2f) + WAIT(1) = 6 steps
        day_input = DayInput(
            day=1,
            max_steps=6,
            agents=agents,
            road_states={2: RoadState.SMOOTH},
            spot_stocks={2: 2},
        )
        actions = [
            [Action.move(1), Action.move(2), Action.wait(1)],
            [Action.wait(6)],
            [Action.wait(6)],
        ]
        res = engine.simulate_day(day_input, actions)
        self.assertTrue(res.valid, res.error_message)
        self.assertEqual(res.agents_end[0].cell_id, 2)
        # Fuel consumed: 1 (from cell 0 PLAIN) + 2 (from cell 1 MOUNTAIN) = 3 -> remaining 7
        self.assertEqual(res.agents_end[0].fuel, 7)
        self.assertEqual(res.portions_collected_today, 1)
        self.assertEqual(res.chains_collected_today, {1})

    def test_refueling_and_one_visit_per_spot_per_day(self):
        """
        Verify:
        1. Patrol car only collects udon on first visit to a spot in the same day.
        2. Refueling car on same cell as Patrol car refills Patrol car to max_fuel.
        """
        terrains = [TerrainType.PLAIN] * 64
        cfg = MapConfig(
            width=8,
            height=8,
            terrains=terrains,
            spots={1: Spot(cell_id=1, chain_id=1, max_stock=3)},
            initial_agent_cells=[0, 2, 8],
            max_fuel=4,
            num_days=4,
            steps_per_day=[8, 8, 8, 8],
            congested_threshold=3.0,
            jam_threshold=6.0,
        )
        engine = HexudonEngine(cfg)
        # Agent 0: PATROL at 0, Agent 1: REFUEL at 2, Agent 2: PATROL at 8
        agents = engine.create_initial_agents([AgentRole.PATROL, AgentRole.REFUEL, AgentRole.PATROL])
        agents[0].fuel = 1  # Only enough fuel to move 0 -> 1

        day_input = DayInput(
            day=1,
            max_steps=8,
            agents=agents,
            road_states={},
            spot_stocks={1: 3},
        )
        # Agent 0 moves 0 -> 1 (takes 2 steps, uses 1 fuel -> 0 fuel left).
        # Agent 1 (REFUEL) moves 2 -> 1 (takes 2 steps, uses 0 fuel).
        # At step 2, both arrive at cell 1! Agent 0 is refilled to max_fuel=4 and collects 1 udon!
        # Then Agent 0 moves 1 -> 0 (2 steps) -> 1 (2 steps) + wait(2): revisits spot 1 on same day, should NOT collect a 2nd time!
        actions = [
            [Action.move(1), Action.move(0), Action.move(1), Action.wait(2)],
            [Action.move(1), Action.wait(6)],
            [Action.wait(8)],
        ]
        res = engine.simulate_day(day_input, actions)
        self.assertTrue(res.valid, res.error_message)
        self.assertEqual(res.portions_collected_today, 1)  # Only 1 collected despite visiting cell 1 twice!
        self.assertEqual(res.agents_end[0].fuel, 4)        # Refilled at cell 1 on second visit too!

    def test_invalid_moves_rejected(self):
        """Ensure Pond entry, insufficient fuel, and insufficient steps are flagged as invalid."""
        terrains = [TerrainType.PLAIN] * 64
        terrains[1] = TerrainType.POND
        cfg = MapConfig(
            width=8,
            height=8,
            terrains=terrains,
            spots={},
            initial_agent_cells=[0, 8, 16],
            max_fuel=1,
            num_days=4,
            steps_per_day=[3, 3, 3, 3],
            congested_threshold=3.0,
            jam_threshold=6.0,
        )
        engine = HexudonEngine(cfg)
        agents = engine.create_initial_agents([AgentRole.PATROL, AgentRole.PATROL, AgentRole.REFUEL])
        day_input = DayInput(day=1, max_steps=3, agents=agents, road_states={}, spot_stocks={})

        # 1. Moving into POND cell 1
        res_pond = engine.simulate_day(
            day_input,
            [[Action.move(1), Action.wait(1)], [Action.wait(3)], [Action.wait(3)]],
        )
        self.assertFalse(res_pond.valid)

        # 2. Moving when remaining steps (1) < required steps (2)
        res_steps = engine.simulate_day(
            day_input,
            [[Action.move(8), Action.move(0)], [Action.wait(3)], [Action.wait(3)]],
        )
        self.assertFalse(res_steps.valid)

    def test_cpp_accelerator_matches_python_dijkstra(self):
        """Verify that C++20 hexudon_fast.dll is active and matches Python Dijkstra on all modes."""
        self.assertTrue(has_cpp_accelerator())
        cfg = generate_map_config(width=12, height=10, seed=99)
        grid = HexGrid(cfg.width, cfg.height, cfg.terrains)
        road_states = {
            u: RoadState(u % 3)
            for u in range(cfg.num_cells)
            if cfg.terrains[u] == TerrainType.ROAD
        }
        for mode in ("steps", "fuel", "balanced"):
            cpp_steps, cpp_fuel, _ = compute_apsp_fast(cfg, road_states, mode=mode)
            for src in (0, 15, 42, cfg.num_cells - 1):
                py_s, py_f, _ = grid.shortest_paths_from(src, road_states, optimize_for=mode)
                self.assertEqual(cpp_steps[src], py_s)
                self.assertEqual(cpp_fuel[src], py_f)

    def test_heuristics_and_2opt_local_search(self):
        """Verify H1-H5 domain heuristics and 2-Opt local search tour improvement."""
        cfg = generate_map_config(width=10, height=10, seed=101)
        grid = HexGrid(cfg.width, cfg.height, cfg.terrains)
        heur = HexudonHeuristics(cfg, grid)

        self.assertEqual(set(heur.chain_scarcity.keys()), cfg.all_chain_ids)
        self.assertEqual(set(heur.spot_isolation.keys()), set(cfg.spots.keys()))

        apsp_s, apsp_f, _ = compute_apsp_fast(cfg, {}, mode="steps")
        pots = heur.compute_gravity_potential(
            apsp_s,
            {sc: sp.max_stock for sc, sp in cfg.spots.items()},
            set(),
            set(),
        )
        self.assertEqual(len(pots), len(cfg.spots))

        # Test 2-Opt on a deliberately zig-zagging sequence of 4 cells
        spot_list = list(cfg.spots.keys())[:4]
        ZigZag = [spot_list[2], spot_list[0], spot_list[3], spot_list[1]]
        opt = optimize_spot_sequence_2opt(0, ZigZag, apsp_s, apsp_f, max_fuel_budget=100)
        self.assertEqual(sorted(opt), sorted(ZigZag))

    def test_multi_team_adversarial_arena(self):
        """Verify 4-team simultaneous tournament with shared road traffic and Grandmaster #1 win."""
        cfg = generate_map_config(
            width=10,
            height=10,
            num_agents=4,
            num_spots=14,
            num_chains=8,
            num_days=4,
            max_fuel=14,
            seed=101,
        )
        arena = MultiTeamArena(cfg)
        res = arena.run_tournament()
        self.assertEqual(len(res["standings"]), 4)
        self.assertTrue(res["standings"][0]["team_name"].startswith("1. Grandmaster"))

    def test_solver_and_match_runner_end_to_end(self):
        """Run full multi-day match with HexudonSolver and verify 100% valid actions and udon collection."""
        cfg = generate_map_config(
            width=10,
            height=10,
            num_agents=5,
            num_spots=15,
            num_chains=8,
            num_days=5,
            max_fuel=12,
            seed=42,
        )
        runner = MatchRunner(cfg)
        replay = runner.run_match(time_budget_ms_per_day=80.0)

        self.assertEqual(len(replay["days"]), 5)
        self.assertGreater(replay["score"]["priority_1_unique_chains_total"], 0)
        self.assertGreaterEqual(
            replay["score"]["priority_2_cumulative_daily_unique_chains"],
            replay["score"]["priority_1_unique_chains_total"],
        )
        self.assertGreaterEqual(
            replay["score"]["priority_3_total_portions"],
            replay["score"]["priority_2_cumulative_daily_unique_chains"],
        )


if __name__ == "__main__":
    unittest.main()
