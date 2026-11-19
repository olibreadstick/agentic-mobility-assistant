"""Minimal HTTP service exposing the ISV planner and verifier to the n8n workflow.

    python service/server.py --port 8787

Endpoints (JSON in, JSON out):
  POST /plan    {"instance": {...}, "time_limit": 20}            -> mission + verified report
  POST /verify  {"instance": {...}, "mission": {...}}            -> report (the shield)
  POST /floor   {"instance": {...}}                              -> instance with floored labels
  GET  /health

In n8n, call these with an HTTP Request node: /plan replaces the planning
agent's ordering duties and the rule nodes, /verify sits in front of the final
response so that nothing reaches the user or the vehicle unverified.
Travel times use the calibrated surface; to use live TomTom legs, pass them as
"leg_overrides": [[origin, destination, km, minutes], ...] in the instance.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hmplan.io import instance_from_dict, instance_to_dict, mission_from_dict, mission_to_dict, report_to_dict  # noqa: E402
from hmplan.runner import PARAMS  # noqa: E402
from hmplan.semantics import semantic_floor  # noqa: E402
from hmplan.solver import solve  # noqa: E402
from hmplan.travel import TravelModel  # noqa: E402
from hmplan.verify import verify  # noqa: E402


def _tm(inst, body):
    ov = {(o, d): (float(km), float(mn)) for o, d, km, mn in body.get("instance", {}).get("leg_overrides", [])}
    return TravelModel(inst, PARAMS, overrides=ov)


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        data = json.dumps(obj, default=float).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            return self._send(200, {"status": "ok"})
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            inst = instance_from_dict(body["instance"])
            if self.path == "/floor":
                floored = inst.with_semantics(semantic_floor(inst, {a.id: a.sem for a in inst.activities}))
                return self._send(200, {"instance": instance_to_dict(floored)})
            inst = inst.with_semantics(semantic_floor(inst, {a.id: a.sem for a in inst.activities}))
            tm = _tm(inst, body)
            if self.path == "/plan":
                r = solve(inst, tm, time_limit=float(body.get("time_limit", 20)))
                return self._send(200, {"mission": mission_to_dict(r.mission), "report": report_to_dict(r.report),
                                        "verified": r.report.feasible, "seconds": r.seconds,
                                        "timed_out": r.timed_out})
            if self.path == "/verify":
                rep = verify(inst, mission_from_dict(body["mission"]), tm)
                return self._send(200, {"report": report_to_dict(rep), "verified": rep.feasible})
            return self._send(404, {"error": "not found"})
        except Exception as e:  # report errors as JSON so the workflow can branch on them
            return self._send(400, {"error": repr(e)})

    def log_message(self, fmt, *args):  # quieter logs
        sys.stderr.write("[ama-service] " + fmt % args + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8787)
    a = ap.parse_args()
    print(f"ISV service on http://{a.host}:{a.port}")
    ThreadingHTTPServer((a.host, a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
