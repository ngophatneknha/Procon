"""Play a real/practice HEXUDON match against the official server.

  set HEXUDON_TOKEN=<JWT from the website 🔑>        (never written to disk or printed)
  python run_online.py --base-url https://hexudon.hairbui76.id.vn --game-id <id> [--practice] [--dry]

--dry plans and validates locally but sends nothing.
Per day: submit a quick valid plan at once, then a deeper plan; resubmit only if (F1,F2,F3) is strictly
better and there is time left (the last valid submission counts, F4 uses it).
"""
import argparse, os, sys, time, urllib.error

from hexudon.client import ContestApiClient
from hexudon.engine import HexudonEngine
from hexudon.models import Action
from hexudon.protocol import (actions_to_official, config_from_official, day_from_official, roles_from_official,
                              types_to_official)
from hexudon.solver import HexudonSolver


def f123(day_input, res):
    return (len(day_input.collected_chains_overall | res.chains_collected_today),
            len(res.chains_collected_today), res.portions_collected_today)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--game-id", required=True)
    ap.add_argument("--practice", action="store_true")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--select-seconds", type=float, default=25.0, help="time for the pre-match role search")
    ap.add_argument("--es-seconds", type=float, default=8.0)
    a = ap.parse_args()
    token = os.environ.get("HEXUDON_TOKEN")
    if not token:
        sys.exit("set HEXUDON_TOKEN first")
    cl = ContestApiClient(a.base_url, token, a.game_id, practice=a.practice)

    cfg, day_secs = config_from_official(cl.get_config())
    eng = HexudonEngine(cfg)
    solver = HexudonSolver(cfg, seed=42)
    solver.plan_budget_ms = max(120.0, min(2000.0, 0.35 * min(day_secs) * 1000.0))
    solver.role_time_s = a.select_seconds / 3.0
    solver.evolve_time_s = a.es_seconds
    t0 = time.time()
    roles = solver.select_roles()
    print(f"roles chosen in {time.time()-t0:.1f}s: {[r.value[0] for r in roles]} budget={solver.plan_budget_ms:.0f}ms")
    if not a.dry:
        print("agent-types:", cl.select_types(types_to_official(roles)))

    collected, handled, day_off = set(), -1, None
    while True:
        raw = cl.get_day()
        d = int(raw["day"])
        if d >= cfg.num_days:
            print("match finished"); break
        if d == handled:
            time.sleep(0.4); continue
        di = day_from_official(raw, cfg, collected)
        starts = [ag.cell_id for ag in di.agents]
        ends_at = float(raw.get("endsAt", time.time() + 5))
        quick = solver.plan_day(di, time_budget_ms=60.0)
        qres = eng.simulate_day(di, quick, record_frames=False)
        if not qres.valid:
            quick = [[Action.wait(di.max_steps)] for _ in di.agents]
            qres = eng.simulate_day(di, quick, record_frames=False)
        best, best_res = quick, qres

        def send(acts):
            plan = actions_to_official(cfg, starts, acts)
            if a.dry:
                return
            nonlocal day_off
            for off in ([day_off] if day_off is not None else [1, 0]):   # body day = server day + off
                try:
                    cl.submit_actions(d + off, plan); day_off = off; return
                except urllib.error.HTTPError as e:
                    print("submit rejected", e.code, "with day =", d + off, e.read()[:300])
            raise RuntimeError("submission rejected")

        send(best)
        remaining = ends_at - time.time()
        if remaining > 1.5:
            deep = solver.plan_day(di, time_budget_ms=solver.plan_budget_ms)
            dres = eng.simulate_day(di, deep, record_frames=False)
            if dres.valid and f123(di, dres) > f123(di, qres) and ends_at - time.time() > 0.4:
                send(deep); best, best_res = deep, dres
        collected |= best_res.chains_collected_today
        handled = d
        print(f"day {d+1}: F1-F3 so far {f123(di, best_res)} total chains {len(collected)}")
        if a.dry:
            break


if __name__ == "__main__":
    main()
