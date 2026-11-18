import os, sys; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sys, itertools
from multiprocessing import Pool
from bench_wide import make
from hexudon.client import MatchRunner
from hexudon.solver import HexudonSolver
from hexudon.models import AgentRole

def job(a):
    i, refs = a
    cfg = make(i); n = cfg.num_agents
    roles = [AgentRole.REFUEL if k in refs else AgentRole.PATROL for k in range(n)]
    s = HexudonSolver(cfg); s.select_roles = lambda *x, **k: roles
    rep = MatchRunner(cfg, s).run_match(time_budget_ms_per_day=120)
    sc = rep["score"]
    return i, refs, (sc["priority_1_unique_chains_total"], sc["priority_2_cumulative_daily_unique_chains"], sc["priority_3_total_portions"]), rep["roles"].count("REFUEL")

if __name__ == "__main__":
    ids = [int(x) for x in sys.argv[1:]]
    jobs = []
    for i in ids:
        n = make(i).num_agents
        for k in range(0, 3):
            for refs in itertools.combinations(range(n), k): jobs.append((i, refs))
    with Pool(2, maxtasksperchild=1) as p: out = p.map(job, jobs)
    for i in ids:
        rows = sorted([o for o in out if o[0] == i], key=lambda o: o[2], reverse=True)
        print(i, "C=", len(make(i).all_chain_ids), "best:", [(r[1], r[2]) for r in rows[:3]], "worst:", rows[-1][2])
        print("   by #refuel best:", {k: max(r[2] for r in rows if len(r[1]) == k) for k in range(3)})
