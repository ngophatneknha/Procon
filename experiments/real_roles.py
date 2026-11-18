import os, sys; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""Force role sets on a real board. Usage: python real_roles.py <q> <budget_ms> <refuel sets e.g. 0 0,1 0,1,2>"""
import sys, time
from multiprocessing import Pool
from real_bench import load
from hexudon.client import MatchRunner
from hexudon.solver import HexudonSolver
from hexudon.models import AgentRole as R

def job(a):
    q, budget, refs = a
    cfg, _ = load(q, 0)
    roles = [R.REFUEL if i in refs else R.PATROL for i in range(cfg.num_agents)]
    s = HexudonSolver(cfg, seed=42); s.select_roles = lambda *x, **k: roles
    rep = MatchRunner(cfg, s).run_match(time_budget_ms_per_day=budget); sc = rep["score"]
    return refs, (sc["priority_1_unique_chains_total"], sc["priority_2_cumulative_daily_unique_chains"], sc["priority_3_total_portions"])

if __name__ == "__main__":
    q, b = int(sys.argv[1]), float(sys.argv[2])
    sets = [tuple(int(x) for x in a.split(",") if x != "") for a in sys.argv[3:]]
    with Pool(2, maxtasksperchild=1) as p:
        for refs, sc in p.imap(job, [(q, b, r) for r in sets]): print("refuel", refs, "->", sc, flush=True)
