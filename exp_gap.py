"""Gap of plan_day vs exact orienteering optimum (1 patrol, ample fuel, day 1). Usage: python exp_gap.py [n] [budget_ms]"""
import sys, random, itertools
from hexudon.generator import generate_map_config
from hexudon.solver import HexudonSolver
from hexudon.models import AgentRole as R, DayInput
from hexudon.engine import HexudonEngine

def opt(cfg, steps):
    eng = HexudonEngine(cfg); rs = eng.compute_road_states([], 1)
    s = HexudonSolver(cfg); d = s._compute_apsp(rs, "steps")[0]
    sp = list(cfg.spots); n = len(sp); st = cfg.initial_agent_cells[0]
    INF = 10**9; dp = [[INF]*n for _ in range(1 << n)]
    for i in range(n):
        if d[st][sp[i]] <= steps: dp[1 << i][i] = d[st][sp[i]]
    best = (0, 0)
    for m in range(1, 1 << n):
        for i in range(n):
            c = dp[m][i]
            if c >= INF: continue
            ch = {cfg.spots[sp[j]].chain_id for j in range(n) if m >> j & 1}
            best = max(best, (len(ch), bin(m).count("1")))
            for j in range(n):
                if m >> j & 1: continue
                nc = c + d[sp[i]][sp[j]]
                if nc <= steps and nc < dp[m | 1 << j][j]: dp[m | 1 << j][j] = nc
    return best

if __name__ == "__main__":
    n = int(sys.argv[1]); budget = float(sys.argv[2]); tot = [0, 0, 0, 0]
    for k in range(n):
        r = random.Random(77 + k)
        cfg = generate_map_config(width=r.randint(8, 12), height=r.randint(8, 12), num_agents=3,
                                  num_spots=r.randint(8, 11), num_chains=r.randint(4, 8), num_days=4,
                                  max_fuel=60, seed=300 + k)
        steps = cfg.steps_per_day[0]
        roles = [R.PATROL, R.REFUEL, R.REFUEL]
        eng = HexudonEngine(cfg); s = HexudonSolver(cfg)
        di = DayInput(day=1, max_steps=steps, agents=eng.create_initial_agents(roles), road_states=eng.compute_road_states([], 1),
                      spot_stocks={c: sp.max_stock for c, sp in cfg.spots.items()}, collected_chains_overall=set())
        res = eng.simulate_day(di, s.plan_day(di, time_budget_ms=budget), record_frames=False)
        o = opt(cfg, steps); got = (len(res.chains_collected_today), res.portions_collected_today)
        tot[0] += o[0]; tot[1] += got[0]; tot[2] += o[1]; tot[3] += got[1]
        print(k, "steps", steps, "opt", o, "got", got, "" if got == o else "<-- gap")
    print("chains opt/got", tot[0], tot[1], "| portions opt/got", tot[2], tot[3])
