"""
Domain-specific Heuristics (H1-H7) and Metaheuristic Local Search (2-Opt, Regret-2 Auction,
Via-Spot Detour Augmentation) for Procon 2026 HEXUDON.
"""

from __future__ import annotations
from typing import Dict, List, Optional, Set, Tuple

from .engine import HexGrid
from .models import MapConfig, Spot, TerrainType


class HexudonHeuristics:
    """
    Precomputes and evaluates the 7 domain-specific HEXUDON heuristics:
      H1: Chain Scarcity & Boundary Isolation
      H2: Hex Gravity Potential Field (Spot Cluster Density)
      H3: Zero-Leftover Refuel Sprint
      H4: Road Betweenness Centrality (Traffic Congestion Predictor)
      H5: Dynamic Fuel Shadow Price (Opportunity cost of fuel by tanker distance)
      H6: Regret-2 Multi-Agent Auction Bonus (VRP Regret Heuristic)
      H7: Via-Spot Detour Augmentation (Opportunistic intermediate spot collection)
    """

    def __init__(self, config: MapConfig, grid: HexGrid):
        self.config = config
        self.grid = grid
        self.map_diameter = max(1, config.width + config.height)

        # H1a: Chain Scarcity (1 / count^0.65)
        chain_counts: Dict[int, int] = {}
        for sp in config.spots.values():
            chain_counts[sp.chain_id] = chain_counts.get(sp.chain_id, 0) + 1

        self.chain_counts = chain_counts
        self.chain_scarcity: Dict[int, float] = {
            cid: (1.0 / max(1, cnt)) ** 0.65 for cid, cnt in chain_counts.items()
        }

        # H1b: Spot Boundary Isolation (normalized average hex distance to all other spots)
        spot_cells = list(config.spots.keys())
        raw_iso: Dict[int, float] = {}
        for sc in spot_cells:
            if len(spot_cells) > 1:
                avg_d = sum(grid.hex_distance(sc, other) for other in spot_cells if other != sc) / (
                    len(spot_cells) - 1
                )
            else:
                avg_d = 1.0
            raw_iso[sc] = avg_d

        max_iso = max(raw_iso.values()) if raw_iso else 1.0
        self.spot_isolation: Dict[int, float] = {
            sc: val / max(1e-6, max_iso) for sc, val in raw_iso.items()
        }

        # H4: Road Betweenness Centrality (identifies bottleneck roads likely to jam)
        self.road_betweenness: Dict[int, float] = self._compute_road_betweenness()

    def _compute_road_betweenness(self) -> Dict[int, float]:
        road_pass_counts: Dict[int, int] = {
            u: 0 for u in range(self.config.num_cells) if self.config.terrains[u] == TerrainType.ROAD
        }
        if not road_pass_counts:
            return {}

        spot_cells = list(self.config.spots.keys())
        for sc in spot_cells:
            _, _, par = self.grid.shortest_paths_from(sc, {}, optimize_for="steps")
            for dst in spot_cells:
                if sc == dst:
                    continue
                cur = dst
                while cur != -1 and cur != sc:
                    if cur in road_pass_counts:
                        road_pass_counts[cur] += 1
                    cur = par[cur]

        max_cnt = max(road_pass_counts.values()) if road_pass_counts else 1
        return {
            u: cnt / max(1, max_cnt) for u, cnt in road_pass_counts.items()
        }

    def compute_gravity_potential(
        self,
        dist_steps: List[List[int]],
        spot_stocks: Dict[int, int],
        chains_today: Set[int],
        chains_overall: Set[int],
    ) -> Dict[int, float]:
        """
        H2: Compute the Hex Gravity Potential Field for every active Spot cell.
        Spots embedded inside dense clusters of unvisited chains get a strong positive potential.
        """
        potentials: Dict[int, float] = {}
        active_spots = [sc for sc, st in spot_stocks.items() if st > 0]

        for sc in active_spots:
            sp_i = self.config.spots[sc]
            pot = 0.0
            for sc2 in active_spots:
                if sc == sc2:
                    continue
                d = dist_steps[sc][sc2]
                if d > 10:
                    continue
                sp_j = self.config.spots[sc2]
                stock_j = spot_stocks.get(sc2, 0)
                chain_mult = 1.0
                if sp_j.chain_id != sp_i.chain_id:
                    if sp_j.chain_id not in chains_overall and sp_j.chain_id not in chains_today:
                        chain_mult = 3.5
                    elif sp_j.chain_id not in chains_today:
                        chain_mult = 2.2
                    else:
                        chain_mult = 1.2
                pot += (stock_j * chain_mult) / ((d + 1.0) ** 1.4)
            potentials[sc] = pot

        return potentials

    def compute_dynamic_fuel_shadow_price(
        self,
        pb_cell: int,
        pb_fuel: int,
        refuel_cells: List[int],
        dist_steps: List[List[int]],
    ) -> float:
        """
        H5: Compute the dynamic opportunity cost of 1 unit of fuel relative to 1 step.
        """
        fuel_ratio = self.config.max_fuel / max(1.0, float(pb_fuel))
        if refuel_cells:
            min_tanker_dist = min(dist_steps[pb_cell][rc] for rc in refuel_cells)
            dist_factor = max(0.25, min(1.5, min_tanker_dist / max(4.0, self.map_diameter * 0.4)))
        else:
            dist_factor = 1.5

        return min(1.2, 0.18 * fuel_ratio * dist_factor)

    def find_best_via_spot(
        self,
        u: int,
        target_v: int,
        visited_spots: Set[int],
        spot_stocks: Dict[int, int],
        chains_today: Set[int],
        chains_overall: Set[int],
        remaining_steps: int,
        remaining_fuel: int,
        dist_steps: List[List[int]],
        dist_fuel: List[List[int]],
    ) -> Optional[int]:
        """
        H7: Via-Spot Detour Augmentation.
        Checks if there is an unvisited intermediate Spot `w` along the corridor `u -> target_v`
        that can be visited with 0 extra steps (or <= 2 extra steps if `w` covers a new Chain!)
        while keeping enough steps and fuel to still reach `target_v`.
        """
        base_s = dist_steps[u][target_v]
        if base_s <= 2:
            return None

        best_w: Optional[int] = None
        best_val = -1.0

        for w, sp_w in self.config.spots.items():
            if w == u or w == target_v or w in visited_spots or spot_stocks.get(w, 0) <= 0:
                continue

            s_uw = dist_steps[u][w]
            s_wv = dist_steps[w][target_v]
            if s_uw == 0 or s_wv == 0:
                continue

            tot_s = s_uw + s_wv
            tot_f = dist_fuel[u][w] + dist_fuel[w][target_v]
            if tot_s > remaining_steps or tot_f > remaining_fuel:
                continue

            extra_steps = tot_s - base_s
            is_new_global = (sp_w.chain_id not in chains_overall) and (sp_w.chain_id not in chains_today)
            is_new_daily = sp_w.chain_id not in chains_today

            max_allowed_detour = 2 if is_new_daily else 0
            if extra_steps <= max_allowed_detour:
                val = (1000.0 if is_new_global else (200.0 if is_new_daily else 50.0)) - extra_steps * 15.0 - s_uw * 0.1
                if val > best_val:
                    best_val = val
                    best_w = w

        return best_w


def optimize_spot_sequence_2opt(
    start_cell: int,
    spot_seq: List[int],
    dist_steps: List[List[int]],
    dist_fuel: List[List[int]],
    max_fuel_budget: int,
) -> List[int]:
    """
    Metaheuristic Intra-Route 2-Opt Local Search.
    """
    n = len(spot_seq)
    if n < 2:
        return list(spot_seq)

    seq = list(spot_seq)

    def _eval_seq(cand: List[int]) -> Tuple[int, int]:
        cur = start_cell
        tot_s = 0
        tot_f = 0
        for sc in cand:
            tot_s += dist_steps[cur][sc]
            tot_f += dist_fuel[cur][sc]
            cur = sc
        return tot_s, tot_f

    cur_s, cur_f = _eval_seq(seq)
    improved = True
    iters = 0

    while improved and iters < 20:
        improved = False
        iters += 1
        for i in range(n - 1):
            for j in range(i + 1, n):
                cand = seq[:i] + list(reversed(seq[i : j + 1])) + seq[j + 1 :]
                ns, nf = _eval_seq(cand)
                if nf <= max_fuel_budget and (ns < cur_s or (ns == cur_s and nf < cur_f)):
                    seq = cand
                    cur_s, cur_f = ns, nf
                    improved = True
                    break
            if improved:
                break

    return seq
