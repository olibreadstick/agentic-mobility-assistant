"""End-to-end pipelines with a real (or mock) language model.

``isv_pipeline``      Interpret (LLM) -> semantic floor -> Solve (exact) -> Verify
``llm_only_pipeline`` the LLM writes the whole mission; it is verified only for evaluation
"""
from __future__ import annotations

import time
from typing import Dict, List, Optional, Tuple

from ..mission import Mission, Stop
from ..model import Instance, Semantics
from ..semantics import POLICY, calendar_text, household_text, semantic_floor
from ..solver import solve
from ..travel import TravelModel
from ..verify import Report, verify
from .prompts import interpretation_prompt, llm_only_planning_prompt
from .providers import Provider


def parse_hhmm(s: str) -> float:
    h, m = s.strip().split(":")[:2]
    return int(h) * 60.0 + int(m)


def interpret(inst: Instance, provider: Provider) -> Tuple[Dict[str, Semantics], Dict[str, str], Dict]:
    """Ask the LLM for categories/labels. Invalid or missing entries fall back to
    the most conservative label (protected, not reschedulable) and are reported."""
    prompt = interpretation_prompt(household_text(inst), calendar_text(inst))
    out, meta = provider.complete_json(prompt)
    labels: Dict[str, Semantics] = {}
    cats: Dict[str, str] = {}
    issues: List[str] = []
    rows = {r.get("event_id"): r for r in (out.get("events", []) if isinstance(out, dict) else [])}
    for a in inst.activities:
        r = rows.get(a.id)
        try:
            labels[a.id] = Semantics(priority=int(r["priority"]), protected=bool(r["protected"]),
                                     reschedulable=bool(r["reschedulable"]))
            cats[a.id] = str(r.get("category", ""))
        except Exception:
            labels[a.id] = Semantics(priority=1, protected=True, reschedulable=False)
            cats[a.id] = "invalid"
            issues.append(a.id)
    extra = [k for k in rows if k not in {a.id for a in inst.activities}]
    meta.update({"invalid_entries": issues, "invented_event_ids": extra})
    return labels, cats, meta


def label_accuracy(inst: Instance, labels: Dict[str, Semantics], cats: Dict[str, str]) -> Dict[str, float]:
    n = len(inst.activities) or 1
    truth = {a.id: POLICY[a.category] for a in inst.activities}
    return {
        "acc_category": sum(cats.get(a.id) == a.category for a in inst.activities) / n,
        "acc_protected": sum(labels[a.id].protected == truth[a.id].protected for a in inst.activities) / n,
        "acc_priority": sum(labels[a.id].priority == truth[a.id].priority for a in inst.activities) / n,
        "acc_resched": sum(labels[a.id].reschedulable == truth[a.id].reschedulable for a in inst.activities) / n,
        "false_unprotect": sum(truth[a.id].protected and not labels[a.id].protected for a in inst.activities),
    }


def isv_pipeline(inst: Instance, provider: Provider, tm: TravelModel, use_floor: bool = True,
                 time_limit: float = 20.0) -> Dict:
    t0 = time.time()
    labels, cats, meta = interpret(inst, provider)
    t_llm = time.time() - t0
    if use_floor:
        labels = semantic_floor(inst, labels)
    perceived = inst.with_semantics(labels)
    r = solve(perceived, tm, time_limit=time_limit)
    true_rep = verify(inst, r.mission, tm)
    return {"labels": labels, "cats": cats, "meta": meta, "mission": r.mission, "system_report": r.report,
            "true_report": true_rep, "flagged": int(not r.report.feasible), "llm_latency_s": t_llm,
            "solver_s": r.seconds, **label_accuracy(inst, labels, cats)}


def llm_only_pipeline(inst: Instance, provider: Provider, tm: TravelModel) -> Dict:
    locs = [{"id": k, "name": v.name} for k, v in inst.locations.items() if v.kind != "charger"] + \
           [{"id": c.loc, "name": inst.locations[c.loc].name, "charger_kw": c.power_kw} for c in inst.chargers]
    vehicle = {"battery_percent": round(inst.vehicle.soc0 * 100), "preferred_min_percent": round(inst.vehicle.soc_pref * 100),
               "critical_percent": round(inst.vehicle.soc_crit * 100), "self_driving": inst.vehicle.autonomy == "AV"}
    prompt = llm_only_planning_prompt(household_text(inst), calendar_text(inst), vehicle, locs)
    t0 = time.time()
    out, meta = provider.complete_json(prompt)
    lat = time.time() - t0
    stops: List[Stop] = []
    for s in out.get("stops", []):
        loc = str(s.get("location", ""))
        if loc not in inst.locations:
            match = [k for k, v in inst.locations.items() if v.name.lower() == loc.lower()]
            loc = match[0] if match else f"UNKNOWN:{loc}"
        try:
            arr, dep = parse_hhmm(s.get("arrive", "00:00")), parse_hhmm(s.get("depart", s.get("arrive", "00:00")))
        except Exception:
            arr = dep = 0.0
        charger = loc if any(c.loc == loc for c in inst.chargers) else None
        stops.append(Stop(loc, arr, dep, tuple(s.get("drop", []) or []), tuple(s.get("pick", []) or []),
                          float(s.get("charge_min", 0) or 0), charger))
    if not stops:
        stops = [Stop(inst.home, inst.day_start, inst.day_start)]
    starts = {}
    for r in out.get("reschedule", []) or []:
        try:
            starts[r["event_id"]] = parse_hhmm(r["new_start"])
        except Exception:
            pass
    starts = {k: v for k, v in starts.items() if k in {a.id for a in inst.activities}}
    m = Mission(stops=stops, starts=starts, router="nominal", planner=f"llm_only:{provider.model}")
    rep = verify(inst, m, tm, exec_router="aware")
    return {"mission": m, "true_report": rep, "meta": meta, "llm_latency_s": lat}
