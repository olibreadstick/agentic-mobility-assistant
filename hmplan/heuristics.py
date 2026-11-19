"""Rule-based and non-agentic baseline planners.

Both baselines are greedy, non-backtracking rollouts on the same state machine
as the exact planner, so that differences in outcomes come from decision
logic rather than from modelling differences.

``rules``   -- reimplementation of the deployed workflow's deterministic logic
               and of the planning agent's prompt rules: chronological sweep,
               active user as designated escort, the caregiver-medical
               reschedule rule (earliest time after the final protected pickup
               + 30 min + buffer, rounded up to 15 min), first-fit charging in
               the first idle gap >= 45 min using the deployed haversine
               estimator (1.25 x great-circle distance at 20 km/h + 5 min) at
               the charger nearest home within 3 km, and construction-aware
               rerouting with the deployed acceptance rule.
``context`` -- as ``rules`` but without calendar changes (context-aware only).
``replay``  -- non-agentic calendar replay: serves trips in calendar order,
               no escort/supervision reasoning, no calendar changes, no
               proactive charging, no construction or traffic information.
"""
from __future__ import annotations

import math
import time as _time
from typing import Dict, List, Optional, Tuple

from .mission import Mission
from .model import CAREGIVER, DEPENDENT, Instance
from .solver import INF, _Search, build_mission
from .travel import TravelModel, haversine_km
from .verify import verify

LEVELS = {
    "replay": dict(router="nominal", social=False, reschedule=False, charging="emergency"),
    "context": dict(router="aware", social=True, reschedule=False, charging="first_fit"),
    "rules": dict(router="aware", social=True, reschedule=True, charging="first_fit"),
}


def _ceil15(x: float) -> float:
    """Round up to the *next* 15-minute mark (deployed prompt rule; 17:30 -> 17:45)."""
    return (math.floor(x / 15.0 + 1e-9) + 1) * 15.0


def designated_escort(inst: Instance, escorts: Tuple[str, ...]) -> Optional[str]:
    cgs = inst.caregivers
    if not cgs:
        return None
    pool = [c for c in cgs if not escorts or c in escorts]
    if not pool:
        return None
    return inst.active_user if inst.active_user in pool else pool[0]


def deployed_reschedule(inst: Instance) -> Dict[str, float]:
    """Caregiver-conflict rule of the deployed planning agent."""
    starts: Dict[str, float] = {}
    deps = set(inst.dependents)
    pickups = [a for a in inst.activities if a.person in deps and a.sem.protected]
    by_escort: Dict[str, List] = {}
    for d in pickups:
        c = designated_escort(inst, d.escorts)
        if c:
            by_escort.setdefault(c, []).append(d)
    for c, plist in by_escort.items():
        final_pick = max(d.end for d in plist)
        for a in inst.activities_of(c):
            if a.sem.protected:
                continue
            conflict = any(a.start < d.end + 15 and a.end > d.end - 30 for d in plist) or \
                any(a.start < d.start and a.end > d.start - 30 for d in plist if d.start >= inst.day_start)
            if not conflict or not a.sem.reschedulable:
                continue
            target = _ceil15(final_pick + 30 + a.buffer)
            if a.slots:
                ok = [x for x in a.slots if x >= target - 1e-9]
                if not ok:
                    continue
                target = min(ok)
            starts[a.id] = target
    return starts


def _deployed_estimate(inst: Instance, o: str, d: str) -> float:
    km = haversine_km(inst.locations[o], inst.locations[d])
    if km < 0.1:
        return 0.0
    return max(5.0, math.ceil(km * 1.25 / 20.0 * 60.0) + 5.0)


def _deployed_charger(inst: Instance) -> Optional[str]:
    if not inst.chargers:
        return None
    home = inst.locations[inst.home]
    ds = sorted((haversine_km(home, inst.locations[c.loc]), c.loc) for c in inst.chargers)
    within = [x for x in ds if x[0] <= 3.0]
    return (within or ds)[0][1]


class _Greedy:
    def __init__(self, inst: Instance, tm: TravelModel, level: str, starts: Dict[str, float]):
        cfg = LEVELS[level]
        self.cfg = cfg
        self.inst = inst
        self.S = _Search(inst, tm, starts, len(starts), None, 10 ** 9, _time.time() + 3600,
                         router=cfg["router"], social=cfg["social"])
        self.charger = _deployed_charger(inst)
        self.charged = False

    def _due(self, act, ps, onboard, t, loc):
        S = self.S
        items = S.items
        if act[0] != "visit":
            return INF
        L, opt = act[1], act[2]
        if opt is None:
            ds = [items[i][ps[i][2]] for i in onboard if items[i][ps[i][2]].loc == L]
            vals = [it.start - it.buffer for it in ds if not it.is_home]
            return min(vals) if vals else INF - 1
        i = opt[1]
        cur = items[i][ps[i][1]]
        tgt = items[i][ps[i][2]]
        if cur.is_home and ps[i][0] == self.inst.home:
            est = S.tm.time(L, tgt.loc, t, S.router) if not tgt.is_home else 0.0
            return tgt.start - tgt.buffer - est - 5.0
        return cur.end

    def _prot(self, act, ps, onboard) -> bool:
        """Deployed priority rule: protected (dependent) services first among near-simultaneous ones."""
        S = self.S
        if act[2] is None:
            return any(S.items[i][ps[i][2]].protected for i in onboard if S.items[i][ps[i][2]].loc == act[1])
        i = act[2][1]
        return S.is_dep[i]

    def _escort_substitute(self, act, ps, onboard):
        """If the next action collects a dependent and no authorised caregiver is aboard, collect the escort first."""
        S = self.S
        if not S.social or act[0] != "visit" or act[2] is None:
            return act
        i = act[2][1]
        if not S.is_dep[i]:
            return act
        cur = S.items[i][ps[i][1]]
        auth = set(cur.escorts) if cur.escorts else {k for k in range(S.n) if S.is_cg[k]}
        if onboard & auth:
            return act
        esc_id = designated_escort(self.inst, tuple(S.pids[k] for k in cur.escorts))
        if esc_id is None:
            return act
        e = S.pids.index(esc_id)
        if ps[e][0] is None:
            return act
        if ps[e][0] == act[1]:
            return ("visit", act[1], ("esc", i, e))
        if ps[e][2] >= len(S.items[e]) or S.items[e][ps[e][1]].is_home:
            return ("visit", ps[e][0], ("esc", e, e))
        ce = S.items[e][ps[e][1]]
        jit = cur.end - cur.buffer - S.tm.time(ps[e][0], cur.loc, cur.end - 30, S.router)
        if ce.end > jit + 1e-9 and not ce.protected and ce.loc == ps[e][0]:
            # deployed rule: protect the dependent pickup -- the caregiver leaves the conflicting event early
            return ("visit", ps[e][0], ("early", e, jit))
        return ("visit", ps[e][0], ("one", e))

    def run(self):
        S = self.S
        inst = self.inst
        v = inst.vehicle
        loc, t, soc = inst.home, inst.day_start, v.soc0
        ps = []
        for i in range(S.n):
            sloc = S.items[i][0].loc
            cur, tgt = S._norm(i, sloc, 0, 1)
            ps.append((sloc, cur, tgt, None, False))
        ps = tuple(ps)
        onboard = frozenset()
        vp = ops = wm = nch = 0
        J = S.J0
        path = []
        for _ in range(400):
            if S._done(ps):
                break
            S._last_was_charge = False
            acts = [a for a in S._actions(loc, t, soc, ps, onboard, nch) if a[0] == "visit"]
            # deployed convention: household members leaving home together board together
            acts2 = []
            for a in acts:
                if a[2] is not None and a[1] == inst.home and ps[a[2][1]][0] == inst.home:
                    acts2.append(("visit", a[1], ("all", a[2][1])))
                acts2.append(a)
            ranked = sorted(acts2, key=lambda a: (self._due(a, ps, onboard, t, loc) - (20.0 if self._prot(a, ps, onboard) else 0.0),
                                                  0 if a[2] is None else 1))
            res = None
            for a in ranked:
                a2 = self._escort_substitute(a, ps, onboard)
                res = S._apply(a2, loc, t, soc, ps, onboard, vp, ops, wm, nch, J)
                if res is None and a2 is not a:
                    res = S._apply(a, loc, t, soc, ps, onboard, vp, ops, wm, nch, J)
                if res is not None:
                    break
            if res is None:
                break
            loc, t, soc, ps, onboard, vp, ops, wm, nch, J, stop = res
            path.extend(stop)
            # ---- charging
            ch = self._maybe_charge(loc, t, soc, ps, onboard, nch)
            if ch is not None:
                r2 = S._apply(ch, loc, t, soc, ps, onboard, vp, ops, wm, nch, J)
                if r2 is not None:
                    loc, t, soc, ps, onboard, vp, ops, wm, nch, J, stop = r2
                    path.extend(stop)
                    self.charged = True
        if loc != inst.home and S._done(ps):
            leg = S.tm.leg(loc, inst.home, t, S.router)
            path.append(("visit", inst.home, t + leg.time_min, t + leg.time_min, (), (), 0.0, None, "return home", ()))
        return path

    def _maybe_charge(self, loc, t, soc, ps, onboard, nch):
        S, inst, v = self.S, self.inst, self.inst.vehicle
        if self.charged or nch >= v.max_charges or self.charger is None:
            return None
        if any(S.is_dep[i] for i in onboard):
            return None
        mode = self.cfg["charging"]
        nearest = S.near_ch[loc][0] if S.near_ch.get(loc) else self.charger
        if mode == "emergency" or soc < v.soc_crit + 0.03:
            if soc < v.soc_crit + 0.03:
                return ("charge", nearest, 30.0)
            return None
        if mode != "first_fit" or v.soc0 >= v.soc_pref:
            return None
        if onboard and not (v.autonomy == "HV" and all(S.is_cg[i] for i in onboard)):
            return None
        # next due time among pending services
        dues = []
        for i, (ploc, cur, tgt, acc, flag) in enumerate(ps):
            if tgt >= len(S.items[i]):
                continue
            it = S.items[i][tgt]
            if ploc is None and not it.is_home:
                dues.append((it.start - it.buffer, it.loc))
            elif ploc is not None and acc is None and it.loc != ploc:
                dues.append((S.items[i][cur].end, ploc))
        if not dues:
            return None
        nxt_t, nxt_loc = min(dues)
        if nxt_t - t < 45:
            return None
        to_c = _deployed_estimate(inst, loc, self.charger)
        from_c = _deployed_estimate(inst, self.charger, nxt_loc)
        avail = math.floor((nxt_t - 10) - (t + to_c + 10) - from_c)
        dur = min(30.0, float(avail))
        if dur < 20:
            return None
        return ("charge", self.charger, dur)


def plan(inst: Instance, tm: TravelModel, level: str = "rules") -> Mission:
    cfg = LEVELS[level]
    starts = deployed_reschedule(inst) if cfg["reschedule"] else {}
    g = _Greedy(inst, tm, level, starts)
    path = g.run()
    m = build_mission(inst, path, starts, planner=level)
    m.router = cfg["router"]
    return m
