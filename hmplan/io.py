"""JSON (de)serialisation of instances, missions and reports (used by the HTTP service)."""
from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict

from .mission import Mission, Stop
from .model import Activity, Charger, Instance, Location, Person, Semantics, Vehicle, Zone
from .verify import Report


def _hhmm(x: Any) -> float:
    if isinstance(x, (int, float)):
        return float(x)
    h, m = str(x).split(":")[:2]
    return int(h) * 60.0 + int(m)


def instance_from_dict(d: Dict[str, Any]) -> Instance:
    locs = {k: Location(k, v.get("name", k), float(v["lat"]), float(v["lng"]), v.get("kind", "poi"))
            for k, v in d["locations"].items()}
    persons = [Person(p["id"], p["role"], bool(p.get("can_drive", p["role"] == "caregiver"))) for p in d["persons"]]
    acts = []
    for a in d["activities"]:
        sem = a.get("semantics", {})
        acts.append(Activity(
            a["id"], a["person"], a.get("title", a["id"]), a.get("category", "work"), a["loc"],
            _hhmm(a["start"]), _hhmm(a["end"]), float(a.get("buffer", 5)),
            Semantics(int(sem.get("priority", 3)), bool(sem.get("protected", False)),
                      bool(sem.get("reschedulable", False))),
            tuple(_hhmm(x) for x in a.get("slots", [])), float(a.get("grace", 5)), tuple(a.get("escorts", []))))
    chargers = [Charger(c["id"], c["loc"], float(c["power_kw"])) for c in d.get("chargers", [])]
    vehicle = Vehicle(**d.get("vehicle", {}))
    zones = [Zone(**z) for z in d.get("zones", [])]
    return Instance(id=d.get("id", "request"), locations=locs, persons=persons, activities=acts, chargers=chargers,
                    vehicle=vehicle, zones=zones, home=d.get("home", "home"),
                    day_start=_hhmm(d.get("day_start", "07:00")), active_user=d.get("active_user", "Parent1"),
                    person_start=d.get("person_start", {}))


def instance_to_dict(inst: Instance) -> Dict[str, Any]:
    return {
        "id": inst.id, "home": inst.home, "day_start": inst.day_start, "active_user": inst.active_user,
        "person_start": inst.person_start,
        "locations": {k: {"name": v.name, "lat": v.lat, "lng": v.lng, "kind": v.kind} for k, v in inst.locations.items()},
        "persons": [{"id": p.id, "role": p.role, "can_drive": p.can_drive} for p in inst.persons],
        "activities": [{"id": a.id, "person": a.person, "title": a.title, "category": a.category, "loc": a.loc,
                        "start": a.start, "end": a.end, "buffer": a.buffer, "grace": a.grace, "slots": list(a.slots),
                        "escorts": list(a.escorts), "semantics": asdict(a.sem)} for a in inst.activities],
        "chargers": [asdict(c) for c in inst.chargers],
        "vehicle": asdict(inst.vehicle),
        "zones": [asdict(z) for z in inst.zones],
    }


def mission_from_dict(d: Dict[str, Any]) -> Mission:
    stops = [Stop(s["loc"], _hhmm(s.get("arrive", 0)), _hhmm(s.get("depart", s.get("arrive", 0))),
                  tuple(s.get("alight", [])), tuple(s.get("board", [])), float(s.get("charge_min", 0)),
                  s.get("charger"), s.get("purpose", ""), tuple(s.get("early", []))) for s in d["stops"]]
    return Mission(stops=stops, starts={k: _hhmm(v) for k, v in d.get("starts", {}).items()},
                   skipped=tuple(d.get("skipped", [])), router=d.get("router", "aware"), planner=d.get("planner", ""))


def mission_to_dict(m: Mission) -> Dict[str, Any]:
    return {"planner": m.planner, "router": m.router, "starts": m.starts, "skipped": list(m.skipped),
            "stops": [asdict(s) for s in m.stops]}


def report_to_dict(r: Report) -> Dict[str, Any]:
    return {"phi": list(r.phi), "feasible": r.feasible, "violations": [asdict(v) for v in r.violations],
            "vkt": r.vkt, "empty_vkt": r.empty_vkt, "vht": r.vht, "soc_end": r.soc_end, "soc_min": r.soc_min,
            "charges": r.charges, "n_time_inconsistent": r.n_time_inconsistent,
            "actual": [list(x) for x in r.actual]}
