"""Map and match configuration generator for Procon 2026 HEXUDON."""

from __future__ import annotations
from collections import deque
import random
from typing import Dict, List, Set

from .engine import HexGrid
from .models import MapConfig, Spot, TerrainType


def _is_connected(width: int, height: int, terrains: List[TerrainType]) -> bool:
    """Verify that all non-POND cells form a single connected component."""
    grid = HexGrid(width, height, terrains)
    passable = [u for u in range(grid.num_cells) if terrains[u] != TerrainType.POND]
    if not passable:
        return False

    visited: Set[int] = {passable[0]}
    q: deque[int] = deque([passable[0]])
    while q:
        u = q.popleft()
        for v in grid.passable_neighbors[u]:
            if v not in visited:
                visited.add(v)
                q.append(v)

    return len(visited) == len(passable)


def generate_map_config(
    width: int = 12,
    height: int = 12,
    num_agents: int = 5,
    num_spots: int = 18,
    num_chains: int = 10,
    num_days: int = 6,
    max_fuel: int = 18,
    seed: int = 2026,
) -> MapConfig:
    """
    Generate a valid, connected HEXUDON map configuration matching all official constraints:
    - 8 <= width, height <= 32
    - All non-POND cells connected
    - Spots placed on PLAIN cells
    - Initial agent positions placed on PLAIN cells without spots
    - 3 <= num_agents <= 8
    - 4 <= num_days <= 10
    """
    rng = random.Random(seed)
    width = max(8, min(32, width))
    height = max(8, min(32, height))
    num_agents = max(3, min(8, num_agents))
    num_days = max(4, min(10, num_days))
    num_cells = width * height

    # Generate connected terrain layout
    for _attempt in range(100):
        terrains = [TerrainType.PLAIN] * num_cells

        # Create a highway network of ROAD cells
        temp_grid = HexGrid(width, height, terrains)
        num_roads = max(2, (width + height) // 5)
        for _ in range(num_roads):
            cur = rng.randrange(num_cells)
            target = rng.randrange(num_cells)
            for _step in range(width + height):
                if cur == target:
                    break
                terrains[cur] = TerrainType.ROAD
                nbrs = temp_grid.all_neighbors[cur]
                cur = min(nbrs, key=lambda v: temp_grid.hex_distance(v, target) + rng.random() * 0.5)
                terrains[cur] = TerrainType.ROAD

        # Sprinkle MOUNTAIN and POND cells while preserving connectivity
        for u in range(num_cells):
            if terrains[u] == TerrainType.ROAD:
                continue
            r, c = divmod(u, width)
            is_border = r == 0 or r == height - 1 or c == 0 or c == width - 1
            roll = rng.random()
            if is_border and roll < 0.45:
                terrains[u] = TerrainType.POND
            elif roll < 0.14:
                terrains[u] = TerrainType.POND
            elif roll < 0.28:
                terrains[u] = TerrainType.MOUNTAIN

        if not _is_connected(width, height, terrains):
            # Repair connectivity by turning isolated POND barriers into PLAIN
            for u in range(num_cells):
                if terrains[u] == TerrainType.POND and rng.random() < 0.5:
                    terrains[u] = TerrainType.PLAIN
            if not _is_connected(width, height, terrains):
                continue

        plain_cells = [u for u in range(num_cells) if terrains[u] == TerrainType.PLAIN]
        if len(plain_cells) >= num_spots + num_agents + 4:
            break
    else:
        terrains = [TerrainType.PLAIN] * num_cells
        plain_cells = list(range(num_cells))

    rng.shuffle(plain_cells)
    actual_num_spots = min(num_spots, len(plain_cells) - num_agents)
    actual_num_chains = max(1, min(num_chains, actual_num_spots))

    spot_cells = plain_cells[:actual_num_spots]
    agent_cells = plain_cells[actual_num_spots : actual_num_spots + num_agents]

    # Ensure every chain from 1..actual_num_chains appears at least once
    chain_assignments = list(range(1, actual_num_chains + 1))
    while len(chain_assignments) < actual_num_spots:
        chain_assignments.append(rng.randint(1, actual_num_chains))
    rng.shuffle(chain_assignments)

    spots: Dict[int, Spot] = {}
    for cell_id, chain_id in zip(spot_cells, chain_assignments):
        max_stock = rng.randint(1, min(3, num_agents))
        spots[cell_id] = Spot(cell_id=cell_id, chain_id=chain_id, max_stock=max_stock)

    steps_per_day = [rng.randint(24, 42) for _ in range(num_days)]

    return MapConfig(
        width=width,
        height=height,
        terrains=terrains,
        spots=spots,
        initial_agent_cells=agent_cells,
        max_fuel=max_fuel,
        num_days=num_days,
        steps_per_day=steps_per_day,
        congested_threshold=3.0,
        jam_threshold=6.0,
        num_teams=2,
    )
