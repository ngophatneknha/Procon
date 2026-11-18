import os, sys; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""Wide random benchmark: solver score vs. simple upper bounds, for several time budgets.
Usage: python bench_wide.py [n_instances] [budget_ms,...]"""
import sys, json, random
from multiprocessing import Pool
from hexudon.client import MatchRunner
from hexudon.generator import generate_map_config


def make(i):
    r = random.Random(1000 + i)
    cfg = generate_map_config(
        width=r.randint(8, 32), height=r.randint(8, 32), num_agents=r.randint(3, 8),
        num_spots=r.randint(8, 45), num_chains=r.randint(3, 24), num_days=r.randint(4, 10),
        max_fuel=r.randint(10, 24), seed=5000 + i,
        steps_range=tuple(int(x) for x in __import__('os').environ.get('HEX_STEPS', '24,42').split(',')))
    return cfg


def run(args):
    i, budget = args
    cfg = make(i)
    rep = MatchRunner(cfg).run_match(time_budget_ms_per_day=budget)
    s = rep["score"]
    C = len(cfg.all_chain_ids)
    n_pat = sum(1 for r in rep["roles"] if r == "PATROL")
    ub2 = cfg.num_days * C
    ub3 = cfg.num_days * sum(min(sp.max_stock, n_pat) for sp in cfg.spots.values())
    return dict(i=i, budget=budget, W=cfg.width, H=cfg.height, N=cfg.num_agents, D=cfg.num_days,
                C=C, S=len(cfg.spots), fuel=cfg.max_fuel, steps=sum(cfg.steps_per_day) // cfg.num_days,
                pat=n_pat, F1=s["priority_1_unique_chains_total"], F2=s["priority_2_cumulative_daily_unique_chains"],
                F3=s["priority_3_total_portions"], ub2=ub2, ub3=ub3, ms=s["priority_4_total_response_time_ms"])


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 16
    budgets = [float(x) for x in (sys.argv[2] if len(sys.argv) > 2 else "120").split(",")]
    ids = [int(x) for x in sys.argv[3].split(',')] if len(sys.argv) > 3 else range(n)
    jobs = [(i, b) for b in budgets for i in ids]
    with Pool(2, maxtasksperchild=1) as p:
        out = p.map(run, jobs)
    for b in budgets:
        rows = [o for o in out if o["budget"] == b]
        print(f"budget {b} ms: F1 full {sum(r['F1']==r['C'] for r in rows)}/{len(rows)}"
              f" | F2 {sum(r['F2'] for r in rows)}/{sum(r['ub2'] for r in rows)}"
              f" | F3 {sum(r['F3'] for r in rows)}/{sum(r['ub3'] for r in rows)}")
    json.dump(out, open("bench_wide_out.json", "w"))
