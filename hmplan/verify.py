"""Deterministic mission verifier (the "shield").

``verify`` re-simulates a mission with grounded travel times and checks every
hard constraint of the HSVMP. It is independent of how the mission was
produced (exact solver, rule-based pipeline, or a language model), which is
what allows the architecture to certify outputs regardless of the reasoning
component (Proposition 2 in the paper).

Violation classes map to the lexicographic objective
    Phi = (V_ops, V_prot, W_miss, N_int, E_short, J)
  * prot : a protected activity is missed, late, moved, or a dependent is
           collected after the pickup grace period;
  * ops  : operational infeasibility -- escort, driver, supervision, passenger
           continuity, capacity, location, energy, day closure, invalid
           calendar change;
  * miss : a non-protected activity is missed or late (priority weighted).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .mission import Mission
from .model import CAREGIVER, DEPENDENT, Activity, Instance, priority_weight
from .travel import TravelModel

EARLY_DROP = 30.0     # dependents may be left at their own activity up to 30 min before start
EPS = 1e-6
# Weights of the service-disutility term J (last lexicographic level)
EROSION_WEIGHT = 2.0  # per minute of arrival-buffer erosion
RIDE_WEIGHT = 0.1     # per person-minute spent in the vehicle (moving, waiting or charging)
WAIT_WEIGHT = 0.05    # per caregiver-minute waiting to be collected after a commitment ends
SHIFT_WEIGHT = 0.05   # per minute an activity is moved from its original time


@dataclass
class Violation:
    cls: str          # prot | ops | miss
    code: str
    ref: str
    detail: str = ""


@dataclass
class Report:
    violations: List[Violation]
    v_prot: int
    v_ops: int
    w_miss: int
    n_int: int
    e_short: float
    J: float
    vkt: float
    empty_vkt: float
    vht: float
    soc_end: float
    soc_min: float
    charges: int
    charge_min: float
    caregiver_onboard_min: float
    buffer_erosion: float
    pax_min: float
    wait_min: float
    n_time_inconsistent: int
    protected_total: int
    protected_ok: int
    actual: List[Tuple[float, float]] = field(default_factory=list)   # (arrive, depart) per stop
    missed: List[str] = field(default_factory=list)

    @property
    def phi(self) -> Tuple[float, ...]:
        return (self.v_ops, self.v_prot, self.w_miss, self.n_int, round(self.e_short, 1), round(self.J, 1))

    @property
    def feasible(self) -> bool:
        return self.v_prot == 0 and self.v_ops == 0

    def codes(self) -> List[str]:
        return [v.code for v in self.violations]


def effective_activities(inst: Instance, starts: Dict[str, float]) -> Dict[str, Activity]:
    return {a.id: (a.shifted(starts[a.id]) if a.id in starts else a) for a in inst.activities}


def _subtract(intervals: List[Tuple[float, float]], cover: List[Tuple[float, float]]) -> float:
    """Total length of ``intervals`` not covered by the union of ``cover``."""
    total = 0.0
    cover = sorted(c for c in cover if c[1] > c[0])
    for lo, hi in intervals:
        cur = lo
        for c0, c1 in cover:
            if c1 <= cur:
                continue
            if c0 >= hi:
                break
            if c0 > cur:
                total += min(c0, hi) - cur
            cur = max(cur, c1)
            if cur >= hi:
                break
        if cur < hi:
            total += hi - cur
    return total


def _release(seq: List[Activity], loc: str, stay_from: float, day_start: float) -> float:
    """Time at which a person staying at ``loc`` since ``stay_from`` is free to leave.

    The person stays through the contiguous run of own activities at ``loc``
    that follows ``stay_from``; if the next own activity is elsewhere they can
    leave immediately.
    """
    i = next((k for k, a in enumerate(seq) if a.end > stay_from + EPS), None)
    if i is None or seq[i].loc != loc:
        return max(stay_from, day_start)
    j = i
    while j + 1 < len(seq) and seq[j + 1].loc == loc:
        j += 1
    return seq[j].end


def verify(inst: Instance, mission: Mission, tm: TravelModel, exec_router: Optional[str] = None,
           check_consistency: bool = True) -> Report:
    v = inst.vehicle
    V: List[Violation] = []
    acts = effective_activities(inst, mission.starts)
    role = {p.id: p.role for p in inst.persons}
    drivers = {p.id for p in inst.persons if p.role == CAREGIVER and p.can_drive}
    own_at: Dict[Tuple[str, str], List[Activity]] = {}
    seq: Dict[str, List[Activity]] = {p.id: [] for p in inst.persons}
    for a in acts.values():
        own_at.setdefault((a.person, a.loc), []).append(a)
        seq[a.person].append(a)
    for p in seq:
        seq[p].sort(key=lambda a: a.start)
    if exec_router is None:
        exec_router = "aware" if mission.router == "aware" else "through"

    stops = mission.stops
    if not stops:
        raise ValueError("empty mission")
    if stops[0].loc != v.start_loc:
        V.append(Violation("ops", "VEH_START", stops[0].loc, "mission does not start at the vehicle location"))
    for s in stops:
        if s.loc not in inst.locations:
            V.append(Violation("ops", "LOC_UNKNOWN", s.loc, "stop location is not a validated location"))

    # person state: current location (None = aboard) and segments [loc, t0, t1]
    where: Dict[str, Optional[str]] = {p.id: inst.start_of(p.id) for p in inst.persons}
    segs: Dict[str, List[List]] = {}
    for p in inst.persons:
        sl = inst.start_of(p.id)
        t0 = inst.day_start
        if sl != inst.home:   # already at an activity in progress when the plan starts
            cur = [a for a in seq[p.id] if a.loc == sl and a.end > inst.day_start]
            if cur:
                t0 = min(t0, cur[0].start - cur[0].buffer)
        segs[p.id] = [[sl, t0, None]]
    onboard: set = set()
    soc = v.soc0
    soc_min = soc
    vkt = empty = vht = cg_on = pax_min = wait_min = 0.0
    charges, charge_min = 0, 0.0
    n_incons = 0
    energy_flag = False
    actual: List[Tuple[float, float]] = []
    erosion = 0.0
    prev_loc, dep_prev = None, None

    for k, s in enumerate(stops):
        if s.loc not in inst.locations:
            # an unvalidated stop cannot be driven to; skip it in the simulation
            actual.append((float("nan"), float("nan")))
            continue
        if prev_loc is None:
            arr = max(s.arrive, inst.day_start)
        else:
            leg = tm.leg(prev_loc, s.loc, dep_prev, exec_router)
            if leg.dist_km > 0:
                if len(onboard) > v.capacity:
                    V.append(Violation("ops", "CAPACITY", f"leg{k}", f"{len(onboard)} aboard"))
                deps = [p for p in onboard if role[p] == DEPENDENT]
                cgs = [p for p in onboard if role[p] == CAREGIVER]
                if v.escort_required and deps and not cgs:
                    V.append(Violation("ops", "ESCORT", f"leg{k}", f"{','.join(deps)} without caregiver"))
                if v.autonomy == "HV" and not (onboard & drivers):
                    V.append(Violation("ops", "DRIVER", f"leg{k}", "vehicle moves without a driver"))
                vkt += leg.dist_km
                vht += leg.time_min
                if not onboard:
                    empty += leg.dist_km
                cg_on += leg.time_min * len(cgs)
                pax_min += leg.time_min * len(onboard)
                soc -= leg.dist_km * v.kwh_per_km / v.battery_kwh
                soc_min = min(soc_min, soc)
                if soc < v.soc_crit - EPS:
                    energy_flag = True
            arr = dep_prev + leg.time_min
            if check_consistency and abs(arr - s.arrive) > 1.0 + EPS:
                n_incons += 1
        ready = arr + (inst.dwell if (s.alight or s.board) else 0.0)

        # --- alight
        for p in s.alight:
            if p not in onboard:
                V.append(Violation("ops", "PASSENGER", p, f"alights at {s.loc} but is not aboard"))
                continue
            t_al = arr
            if role[p] == DEPENDENT:
                nxt = next((a for a in seq[p] if a.end > arr + EPS), None)
                if nxt is not None and nxt.loc == s.loc and 0 < nxt.start - EARLY_DROP - arr <= 120:
                    t_al = nxt.start - EARLY_DROP
            ready = max(ready, t_al + inst.dwell)
            onboard.discard(p)
            segs[p][-1][2] = t_al
            segs[p].append([s.loc, t_al, None])
            where[p] = s.loc

        # --- charge
        if s.charge_min > 0:
            ch = [c for c in inst.chargers if c.loc == s.loc]
            if not ch:
                V.append(Violation("ops", "CHARGER", s.loc, "charging at a location without a charger"))
            else:
                if any(role[p] == DEPENDENT for p in onboard):
                    V.append(Violation("ops", "CHARGE_WITH_CHILD", s.loc, "dependents aboard while charging"))
                ready = max(ready, arr) + s.charge_min
                soc = min(1.0, soc + ch[0].power_kw * s.charge_min / 60.0 / v.battery_kwh)
                charges += 1
                charge_min += s.charge_min
                cg_on += s.charge_min * sum(1 for p in onboard if role[p] == CAREGIVER)

        # --- board (the vehicle waits for boarding persons to be released)
        valid_board = []
        for p in s.board:
            if p in onboard or where[p] != s.loc:
                V.append(Violation("ops", "PASSENGER", p, f"boards at {s.loc} but is not there"))
                continue
            release = arr if p in s.early else _release(seq[p], s.loc, segs[p][-1][1], inst.day_start)
            ready = max(ready, release)
            valid_board.append(p)
        dep = max(s.depart, ready)
        pax_min += (dep - arr) * len(onboard)
        for p in valid_board:
            if role[p] == CAREGIVER and s.loc != inst.home and p not in s.early:
                wait_min += max(0.0, dep - _release(seq[p], s.loc, segs[p][-1][1], inst.day_start))
        aboard_after = onboard | set(valid_board)
        for p in valid_board:
            if role[p] != DEPENDENT:
                continue
            for a in own_at.get((p, s.loc), []):
                if a.sem.protected and abs(a.end - _release(seq[p], s.loc, segs[p][-1][1], inst.day_start)) < EPS:
                    erosion += min(a.buffer, max(0.0, arr - (a.end - a.buffer)))
                if a.escorts and abs(a.end - _release(seq[p], s.loc, segs[p][-1][1], inst.day_start)) < EPS \
                        and not (aboard_after & set(a.escorts)):
                    V.append(Violation("ops", "UNAUTHORIZED_PICKUP", a.id,
                                       f"{p} collected without an authorised caregiver ({','.join(a.escorts)})"))
        for p in valid_board:
            segs[p][-1][2] = dep
            segs[p].append(["V", dep, None])
            where[p] = None
            onboard.add(p)
        actual.append((arr, dep))
        prev_loc, dep_prev = s.loc, dep

    horizon = max(dep_prev or inst.day_start, 23 * 60.0) + 60.0
    for p in segs:
        if segs[p][-1][2] is None:
            segs[p][-1][2] = horizon

    # --- day closure
    if stops[-1].loc != inst.home:
        V.append(Violation("ops", "VEH_NOT_HOME", stops[-1].loc, "vehicle does not return home"))
    for p in segs:
        last = segs[p][-1]
        if last[0] != inst.home:
            V.append(Violation("ops", "STRANDED", p, f"ends the day at {last[0]}"))

    # --- calendar changes
    for aid, ns in mission.starts.items():
        a = inst.activity(aid)
        if a.sem.protected:
            V.append(Violation("prot", "MOVED_PROTECTED", aid, "protected activity rescheduled"))
        elif not a.slots or min(abs(ns - x) for x in a.slots) > 0.5:
            # admissibility is a record (provider availability), not an interpretation
            V.append(Violation("ops", "INVALID_SLOT", aid, "proposed time is not an admissible slot"))

    # --- activity attendance
    prot_total = prot_ok = 0
    w_miss = 0
    missed: List[str] = []
    for a in acts.values():
        p = a.person
        cand = [sg for sg in segs[p] if sg[0] == a.loc and sg[1] < a.end - EPS and sg[2] > a.start + EPS]
        stay = [sg for sg in cand if sg[2] >= a.end - EPS]
        bad, code = False, ""
        if not stay:
            bad, code = True, ("LEFT_EARLY" if any(sg[1] <= a.start + EPS for sg in cand) else "MISSED")
        else:
            sg = min(stay, key=lambda x: x[1])
            if sg[1] > a.start + EPS:
                bad, code = True, "LATE"
            else:
                erosion += min(a.buffer, max(0.0, sg[1] - (a.start - a.buffer)))
            if role[p] == DEPENDENT and a.sem.protected and sg[2] > a.end + a.grace + EPS:
                bad, code = True, (code + "+" if code else "") + "LATE_PICKUP"
        if a.sem.protected:
            prot_total += 1
            if bad or a.id in mission.starts:
                if bad:
                    V.append(Violation("prot", "PROT_" + code, a.id, a.title))
            else:
                prot_ok += 1
        elif bad:
            w = priority_weight(a.sem.priority)
            w_miss += w
            missed.append(a.id)
            V.append(Violation("miss", code, a.id, f"{a.title} (w={w})"))

    # --- dependent supervision
    cg_ids = [p for p in segs if role[p] == CAREGIVER]
    for d in [p for p in segs if role[p] == DEPENDENT]:
        for loc, t0, t1 in segs[d]:
            if loc == "V" or t1 - t0 <= EPS:
                continue
            cover = []
            for a in own_at.get((d, loc), []):
                if a.loc != inst.home and t0 < a.end - EPS and t1 > a.start - EARLY_DROP + EPS:
                    cover.append((a.start - EARLY_DROP, t1))
            for c in cg_ids:
                for cl, c0, c1 in segs[c]:
                    if cl == loc:
                        cover.append((c0, c1))
            gap = _subtract([(t0, t1)], cover)
            if gap > 1.0:
                V.append(Violation("ops", "SUPERVISION", d, f"unsupervised {gap:.0f} min at {loc}"))

    if energy_flag:
        V.append(Violation("ops", "ENERGY", "vehicle", f"SoC fell to {soc_min:.2f} < {v.soc_crit:.2f}"))

    shift = sum(abs(ns - inst.activity(aid).start) for aid, ns in mission.starts.items())
    v_prot = sum(1 for x in V if x.cls == "prot")
    v_ops = sum(1 for x in V if x.cls == "ops")
    e_short = max(0.0, v.soc_pref - soc) * 100.0
    return Report(violations=V, v_prot=v_prot, v_ops=v_ops, w_miss=w_miss, n_int=len(mission.starts),
                  e_short=e_short,
                  J=vht + EROSION_WEIGHT * erosion + RIDE_WEIGHT * pax_min + WAIT_WEIGHT * wait_min + SHIFT_WEIGHT * shift, vkt=vkt, empty_vkt=empty, vht=vht, soc_end=soc,
                  soc_min=soc_min, charges=charges, charge_min=charge_min, caregiver_onboard_min=cg_on,
                  buffer_erosion=erosion, pax_min=pax_min, wait_min=wait_min, n_time_inconsistent=n_incons, protected_total=prot_total,
                  protected_ok=prot_ok, actual=actual, missed=missed)
