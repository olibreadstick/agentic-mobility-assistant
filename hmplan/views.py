"""User-facing and vehicle-facing projections of a verified mission.

The vehicle-facing plan keeps every movement (including passenger-free
repositioning and charging). The user-facing plan keeps only the legs that
involve the active user, and adds a just-in-time "leave by" time computed
from grounded travel times, so personalisation never removes operational
movements from the vehicle plan.
"""
from __future__ import annotations

from typing import Dict, List

from .mission import Mission
from .model import Instance, fmt_time
from .travel import TravelModel
from .verify import Report


def vehicle_view(inst: Instance, m: Mission, rep: Report) -> List[Dict]:
    rows = []
    aboard: set = set()
    for k, s in enumerate(m.stops):
        arr, dep = rep.actual[k] if k < len(rep.actual) else (s.arrive, s.depart)
        aboard -= set(s.alight)
        rows.append({"stop": k, "location": inst.locations[s.loc].name, "arrive": fmt_time(arr),
                     "depart": fmt_time(dep), "drop": list(s.alight), "pick": list(s.board),
                     "charge_min": s.charge_min, "aboard_after": sorted(aboard | set(s.board))})
        aboard |= set(s.board)
    return rows


def user_view(inst: Instance, m: Mission, rep: Report, tm: TravelModel, user: str) -> List[Dict]:
    """Trips of ``user`` with a latest departure that preserves the arrival target."""
    acts = {a.id: (a.shifted(m.starts[a.id]) if a.id in m.starts else a) for a in inst.activities}
    trips = []
    for k in range(len(m.stops) - 1):
        a, b = m.stops[k], m.stops[k + 1]
        if user not in b.alight or a.loc == b.loc:
            continue
        target = next((x for x in acts.values() if x.person == user and x.loc == b.loc and x.end > rep.actual[k][1]),
                      None)
        arrive = rep.actual[k + 1][0]
        leave = rep.actual[k][1]
        slack_leave = None
        if target is not None:
            latest_arrival = target.start - target.buffer
            slack_leave = latest_arrival - tm.time(a.loc, b.loc, latest_arrival - 30)
        trips.append({"from": inst.locations[a.loc].name, "to": inst.locations[b.loc].name,
                      "depart": fmt_time(leave), "latest_departure": fmt_time(slack_leave), "arrive": fmt_time(arrive),
                      "purpose": target.title if target else "return home"})
    return trips
