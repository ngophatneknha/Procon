"""Benchmark runner, 4-Team Adversarial Tournament, and Replay Generator for Procon 2026 HEXUDON."""

from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict, List

from hexudon.arena import MultiTeamArena
from hexudon.client import MatchRunner
from hexudon.generator import generate_map_config


def run_all_benchmarks() -> List[Dict[str, Any]]:
    scenarios = [
        {
            "name": "Scenario 1: Standard 10x10 (Figure 1 Scale)",
            "width": 10,
            "height": 10,
            "num_agents": 4,
            "num_spots": 14,
            "num_chains": 8,
            "num_days": 5,
            "max_fuel": 14,
            "seed": 101,
        },
        {
            "name": "Scenario 2: Medium 16x14 (High Traffic & Multi-Chain)",
            "width": 16,
            "height": 14,
            "num_agents": 6,
            "num_spots": 24,
            "num_chains": 14,
            "num_days": 6,
            "max_fuel": 18,
            "seed": 2026,
        },
        {
            "name": "Scenario 3: Large 22x18 (Tight Fuel / Active Tanker Rendezvous)",
            "width": 22,
            "height": 18,
            "num_agents": 8,
            "num_spots": 32,
            "num_chains": 18,
            "num_days": 7,
            "max_fuel": 16,
            "seed": 777,
        },
        {
            "name": "Scenario 4: Extreme 32x32 Max-Scale Stress-Test (1024 Cells, 24 Chains)",
            "width": 32,
            "height": 32,
            "num_agents": 8,
            "num_spots": 45,
            "num_chains": 24,
            "num_days": 8,
            "max_fuel": 18,
            "seed": 9999,
        },
    ]

    replays: List[Dict[str, Any]] = []
    print("=" * 94)
    print(" PART 1: PROCON VIETNAM 2026 - HEXUDON SINGLE-TEAM OPTIMIZATION & REPLAY BENCHMARK")
    print("=" * 94)

    for sc in scenarios:
        cfg = generate_map_config(
            width=sc["width"],
            height=sc["height"],
            num_agents=sc["num_agents"],
            num_spots=sc["num_spots"],
            num_chains=sc["num_chains"],
            num_days=sc["num_days"],
            max_fuel=sc["max_fuel"],
            seed=sc["seed"],
        )
        runner = MatchRunner(cfg)
        replay = runner.run_match(time_budget_ms_per_day=120.0)
        replay["scenario_name"] = sc["name"]
        replays.append(replay)

        score = replay["score"]
        roles_list = replay["roles"]
        n_patrol = sum(1 for r in roles_list if r == "PATROL")
        n_refuel = sum(1 for r in roles_list if r == "REFUEL")

        print(f"\n[{sc['name']}]")
        print(
            f"  Map Size: {cfg.width}x{cfg.height} ({cfg.num_cells} cells) | "
            f"Spots: {len(cfg.spots)} | Chains: {replay['total_chains_available']} | "
            f"Days: {cfg.num_days} | Max Fuel: {cfg.max_fuel}"
        )
        print(f"  Roles Selected: {n_patrol} PATROL + {n_refuel} REFUEL ({', '.join(roles_list)})")
        print(
            f"  -> Priority 1 (Unique Udon Types Overall) : "
            f"{score['priority_1_unique_chains_total']} / {replay['total_chains_available']} "
            f"({100.0 * score['priority_1_unique_chains_total'] / max(1, replay['total_chains_available']):.1f}%)"
        )
        print(
            f"  -> Priority 2 (Sum of Daily Unique Types) : "
            f"{score['priority_2_cumulative_daily_unique_chains']}"
        )
        print(
            f"  -> Priority 3 (Total Udon Portions)       : "
            f"{score['priority_3_total_portions']}"
        )
        print(
            f"  -> Priority 4 (Total Response Time)       : "
            f"{score['priority_4_total_response_time_ms']:.2f} ms "
            f"({score['priority_4_total_response_time_ms'] / cfg.num_days:.2f} ms/day)"
        )

    print("\n" + "=" * 94)
    print(" PART 2: 4-TEAM SIMULTANEOUS ADVERSARIAL TOURNAMENT (SHARED ROAD TRAFFIC)")
    print("=" * 94)

    for sc in scenarios:
        cfg = generate_map_config(
            width=sc["width"],
            height=sc["height"],
            num_agents=sc["num_agents"],
            num_spots=sc["num_spots"],
            num_chains=sc["num_chains"],
            num_days=sc["num_days"],
            max_fuel=sc["max_fuel"],
            seed=sc["seed"],
        )
        arena = MultiTeamArena(cfg)
        result = arena.run_tournament()
        print(f"\nTournament on [{sc['name']}] (Total Chains = {result['total_chains']}):")
        for rank, entry in enumerate(result["standings"], start=1):
            ms = entry["score"]
            medal = "🏆 #1" if rank == 1 else f"   #{rank}"
            print(
                f"  {medal} | {entry['team_name']:<56} | "
                f"P1={ms.unique_chains_total:>2}/{result['total_chains']:<2} | "
                f"P2={ms.cumulative_daily_unique_chains:>3} | "
                f"P3={ms.total_portions:>3} | "
                f"P4={ms.total_response_time_ms:>6.1f}ms"
            )

    out_dir = Path(__file__).resolve().parent
    replay_path = out_dir / "sample_replays.json"
    replay_path.write_text(json.dumps(replays, indent=2), encoding="utf-8")
    print("\n" + "=" * 94)
    print(f"Saved {len(replays)} full match replays to: {replay_path}")
    print("=" * 94)
    return replays


if __name__ == "__main__":
    run_all_benchmarks()
