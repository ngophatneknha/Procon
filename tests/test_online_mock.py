"""End-to-end run_online.py against a local mock of the official server (no real credentials)."""
import json, os, subprocess, sys, threading, unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from hexudon.engine import HexudonEngine
from hexudon.generator import generate_map_config
from hexudon.models import Action, AgentRole, DayInput, TerrainType
from hexudon.protocol import actions_from_official, roles_from_official

CODE = {TerrainType.PLAIN: 0, TerrainType.ROAD: 1, TerrainType.MOUNTAIN: 2, TerrainType.POND: 3}


class Mock:
    def __init__(self):
        self.cfg = generate_map_config(width=10, height=10, num_agents=4, num_spots=12, num_chains=6,
                                       num_days=4, seed=5, steps_range=(50, 80))
        self.eng = HexudonEngine(self.cfg)
        self.roles = None
        self.agents = None
        self.day = 0
        self.hist = []
        self.log = []
        self.pending = None
        self.deadline = None
        c = self.cfg
        self.raw_cfg = {
            "startsAt": 0, "daySeconds": [4] * c.num_days, "daySteps": c.steps_per_day,
            "map": {"height": c.height, "width": c.width,
                    "cells": [[CODE[c.terrains[r * c.width + k]] for k in range(c.width)] for r in range(c.height)]},
            "spots": [{"brand": s.chain_id, "pos": s.cell_id, "stocks": s.max_stock} for s in c.spots.values()],
            "agents": c.initial_agent_cells, "fuelLimits": c.max_fuel, "players": 1,
            "busyThreshold": 3, "jammedThreshold": 6,
        }

    def advance_if_due(self):
        import time
        if self.deadline is not None and time.time() >= self.deadline and self.day < self.cfg.num_days:
            di = self._di()
            plan = self.pending or [[Action.wait(di.max_steps)] for _ in self.agents]
            res = self.eng.simulate_day(di, plan, record_frames=False)
            self.agents, self.day = res.agents_end, self.day + 1
            self.hist.append(res.road_stay_steps)
            self.pending, self.deadline = None, time.time() + 3

    def _di(self):
        return DayInput(day=self.day + 1, max_steps=self.cfg.steps_per_day[self.day],
                        agents=[a.clone() for a in self.agents],
                        road_states=self.eng.compute_road_states(self.hist, self.day + 1),
                        spot_stocks={c: s.max_stock for c, s in self.cfg.spots.items()})

    def day_json(self):
        import time
        self.advance_if_due()
        if self.deadline is None:
            self.deadline = time.time() + 3
        rs = self.eng.compute_road_states(self.hist, self.day + 1)
        return {"endsAt": self.deadline, "day": self.day, "others": [],
                "agents": [{"kind": 0 if a.role == AgentRole.PATROL else 1, "pos": a.cell_id, "fuel": a.fuel}
                           for a in self.agents],
                "traffics": [{"pos": u, "status": int(s)} for u, s in rs.items()]}


def make_handler(m):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass

        def _send(self, code, obj):
            b = json.dumps(obj).encode()
            self.send_response(code); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

        def do_GET(self):
            p = urlparse(self.path).path
            if p == "/api/game/config": return self._send(200, m.raw_cfg)
            if p == "/api/game/day":
                if m.agents is None:
                    m.agents = m.eng.create_initial_agents([AgentRole.PATROL] * m.cfg.num_agents)
                return self._send(200, m.day_json())
            self._send(404, {})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            p = urlparse(self.path).path
            if p == "/api/game/agent-types":
                m.roles = roles_from_official(body["types"])
                m.agents = m.eng.create_initial_agents(m.roles)
                return self._send(200, {"ok": True})
            if p == "/api/game/practice/actions":
                if body["day"] != m.day + 1:                      # mock expects 1-indexed day
                    return self._send(400, {"detail": "bad day"})
                m.log.append(body["day"])
                di = m._di()
                plan = actions_from_official(m.cfg, [a.cell_id for a in m.agents], body["actions"])
                res = m.eng.simulate_day(di, plan, record_frames=False)
                if not res.valid:
                    return self._send(400, {"detail": res.error_message})
                m.pending = plan            # last valid submission counts; day advances at the deadline
                return self._send(200, {"ok": True})
            self._send(404, {})
    return H


class TestOnlineMock(unittest.TestCase):
    def test_full_match_against_mock(self):
        m = Mock()
        srv = HTTPServer(("127.0.0.1", 0), make_handler(m))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        env = dict(os.environ, HEXUDON_TOKEN="test-token", PYTHONIOENCODING="utf-8")
        out = subprocess.run(
            [sys.executable, "run_online.py", "--base-url", f"http://127.0.0.1:{srv.server_port}",
             "--game-id", "g", "--practice", "--select-seconds", "3"],
            capture_output=True, text=True, env=env, timeout=240,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        srv.shutdown()
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertEqual(m.day, 4, out.stdout)
        self.assertGreaterEqual(len(m.log), 4)
        self.assertIn("match finished", out.stdout)
        self.assertTrue(set(m.log) <= {1, 2, 3, 4})


if __name__ == "__main__":
    unittest.main()
