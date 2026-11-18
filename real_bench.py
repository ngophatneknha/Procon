"""Benchmark on the REAL practice boards saved in ref/board{1..5}.json (agents are synthesized: board has none).
Usage: python real_bench.py <question 1..5> <budget_ms> [n_agents]"""
import json, random, sys, time
from hexudon.client import MatchRunner
from hexudon.models import TerrainType
from hexudon.protocol import config_from_official
from hexudon.solver import HexudonSolver


def load(q, n_agents=8):
    import os
    cfgf = f"ref/config{q}.json"
    if os.path.exists(cfgf) and n_agents == 0:          # n_agents=0: use the real initial agents
        return config_from_official(json.load(open(cfgf, encoding="utf-8")))
    raw = json.load(open(f"ref/board{q}.json", encoding="utf-8"))
    r = random.Random(q)
    occupied = {int(s["pos"]) for s in raw["spots"]}
    plains = [i for i, c in enumerate(c for row in raw["map"]["cells"] for c in row) if c == 0 and i not in occupied]
    raw["agents"] = r.sample(plains, n_agents)
    return config_from_official(raw)


if __name__ == "__main__":
    q, budget = int(sys.argv[1]), float(sys.argv[2])
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    cfg, secs = load(q, n)
    s = HexudonSolver(cfg, seed=42)
    s.role_time_s, s.evolve_time_s = 6.0, 5.0
    t = time.time()
    rep = MatchRunner(cfg, s).run_match(time_budget_ms_per_day=budget)
    sc = rep["score"]
    print(f"Q{q} n={n} budget={budget:.0f}ms wall={time.time()-t:.0f}s roles={''.join(r[0] for r in rep['roles'])} "
          f"F1={sc['priority_1_unique_chains_total']}/{len(cfg.all_chain_ids)} F2={sc['priority_2_cumulative_daily_unique_chains']} "
          f"F3={sc['priority_3_total_portions']} resp={sc['priority_4_total_response_time_ms']:.0f}ms")
    print("per-day chains/portions:", [(len(d['chains_collected_today']), d['portions_collected_today']) for d in rep['days']],
          "ms:", [round(d['response_time_ms']) for d in rep['days']])
