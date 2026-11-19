"""Procedural generator for HouseholdMissionBench instances.

Instances are synthetic household days on a Montreal-like plane: homes in a
residential ring, employment concentrated downtown, schools near home, public
chargers (Level 2 and DC fast), and construction zones concentrated in the
core. Travel uses the calibrated surface in ``travel.py``. Every random draw is
seeded, so ``generate(seed)`` is reproducible across machines.
"""
from __future__ import annotations

import math
import random
from dataclasses import replace
from typing import Dict, List, Optional, Tuple

from .model import (CAREGIVER, DEPENDENT, Activity, Charger, Instance, Location, Person, Vehicle, Zone)
from .semantics import label_from_category

CENTER = (45.5017, -73.5673)   # downtown Montreal

TITLES = {
    "work": ["Team meeting", "Research meeting", "Client meeting", "Work (office)", "Project review",
             "Lab work", "Board meeting"],
    "caregiver_medical": ["Dentist appointment", "Doctor appointment", "Physiotherapy", "Eye exam",
                          "Blood test"],
    "errand": ["Accountant", "Bank appointment", "Notary", "Passport office", "Car insurance meeting"],
    "personal": ["Gym", "Yoga class", "Coffee with a friend", "Haircut", "Book club"],
    "child_activity": ["soccer practice", "piano lesson", "swimming lesson", "dance class", "hockey practice"],
    "child_medical": ["pediatrician", "orthodontist"],
}


def _offset(lat: float, lng: float, r_km: float, theta: float) -> Tuple[float, float]:
    dlat = (r_km / 111.2) * math.sin(theta)
    dlng = (r_km / (111.2 * math.cos(math.radians(lat)))) * math.cos(theta)
    return lat + dlat, lng + dlng


def _place(rng: random.Random, around: Tuple[float, float], rmin: float, rmax: float) -> Tuple[float, float]:
    r = math.sqrt(rng.uniform(rmin ** 2, rmax ** 2))
    return _offset(around[0], around[1], r, rng.uniform(0, 2 * math.pi))


def _slots(rng: random.Random, start: float, dur: float, lo: float = 8 * 60, hi: float = 20 * 60) -> Tuple[float, ...]:
    cands = [start + d for d in (-180, -120, -90, -60, 60, 90, 120, 180)]
    cands = [c for c in cands if lo <= c and c + dur <= hi]
    rng.shuffle(cands)
    return tuple(sorted(cands[: rng.randint(2, 4)]))


def _free(acts: List[Activity], person: str, s: float, e: float, gap: float = 20.0) -> bool:
    return all(not (s < a.end + gap and e > a.start - gap) for a in acts if a.person == person)


def generate(seed: int, n_caregivers: Optional[int] = None, n_dependents: Optional[int] = None,
             autonomy: str = "AV", soc0: Optional[float] = None, n_zones: Optional[int] = None,
             authorised_prob: float = 0.2) -> Instance:
    rng = random.Random(seed)
    nc = n_caregivers if n_caregivers is not None else rng.choices([1, 2], [0.25, 0.75])[0]
    nd = n_dependents if n_dependents is not None else rng.choices([0, 1, 2, 3], [0.15, 0.35, 0.35, 0.15])[0]

    locs: Dict[str, Location] = {}

    def add(lid: str, name: str, ll: Tuple[float, float], kind: str) -> str:
        locs[lid] = Location(lid, name, ll[0], ll[1], kind)
        return lid

    home_ll = _place(rng, CENTER, 2.0, 7.0)
    add("home", "Home", home_ll, "home")
    persons = [Person(f"Parent{k + 1}", CAREGIVER) for k in range(nc)] + \
              [Person(f"Child{k + 1}", DEPENDENT, False) for k in range(nd)]
    acts: List[Activity] = []
    aid = 0

    def new_act(person, category, title, loc, s, e, buffer, slots=(), escorts=()):
        nonlocal aid
        aid += 1
        acts.append(Activity(f"a{aid:02d}", person, title, category, loc, s, e, buffer,
                             label_from_category(category), tuple(slots), 5.0, tuple(escorts)))

    # ---------------------------------------------------------------- dependents
    shared_school = None
    for k in range(nd):
        child = f"Child{k + 1}"
        if shared_school and rng.random() < 0.4:
            sloc = shared_school
        else:
            sloc = add(f"school{k + 1}", f"{child}'s school", _place(rng, home_ll, 0.4, 2.5), "school")
            shared_school = shared_school or sloc
        s = rng.choice([8 * 60, 8 * 60 + 15, 8 * 60 + 30])
        e = rng.choice([15 * 60, 15 * 60 + 15, 15 * 60 + 30, 15 * 60 + 45, 16 * 60])
        escorts = ()
        if nc == 2 and rng.random() < authorised_prob:
            escorts = (rng.choice(["Parent1", "Parent2"]),)
        new_act(child, "school", f"{child} school (pickup {e // 60 - 12}:{e % 60:02d} PM)", sloc, s, e, 10,
                escorts=escorts)
        u = rng.random()
        if u < 0.30:
            st = rng.choice([16 * 60 + 30 + 15 * j for j in range(9)])
            du = rng.choice([45, 60, 75, 90])
            if _free(acts, child, st, st + du, 30):
                lloc = add(f"act{k + 1}", f"{child} activity", _place(rng, home_ll, 0.5, 3.0), "poi")
                new_act(child, "child_activity", f"{child} {rng.choice(TITLES['child_activity'])}", lloc,
                        st, st + du, 10)
        elif u < 0.36:
            st = rng.choice([16 * 60 + 30 + 15 * j for j in range(5)])
            if _free(acts, child, st, st + 45, 30):
                lloc = add(f"ped{k + 1}", f"{child} clinic", _place(rng, CENTER, 0.5, 5.0), "poi")
                new_act(child, "child_medical", f"{child} {rng.choice(TITLES['child_medical'])}", lloc,
                        st, st + 45, 15)

    # ---------------------------------------------------------------- caregivers
    for k in range(nc):
        cg = f"Parent{k + 1}"
        p_work = 0.9 if k == 0 else 0.75
        if rng.random() < p_work:
            downtown = rng.random() < 0.55
            wll = _place(rng, CENTER, 0.0, 1.5) if downtown else _place(rng, CENTER, 2.0, 8.0)
            wloc = add(f"work{k + 1}", f"{cg} workplace", wll, "work")
            if nd > 0 and rng.random() < 0.7:   # households with children adapt start times to school runs
                s = rng.choice([8 * 60 + 30 + 15 * j for j in range(7)])
            else:
                s = rng.choice([7 * 60 + 30 + 15 * j for j in range(11)])
            dur = rng.choice([180, 240, 300, 360, 420, 480, 510])
            e = min(s + dur, 18 * 60)
            if rng.random() < 0.2 and e - s >= 300:
                mid = s + (e - s) // 2
                mloc = add(f"meet{k + 1}", f"{cg} offsite meeting", _place(rng, CENTER, 0.3, 3.0), "work")
                new_act(cg, "work", rng.choice(TITLES["work"]), wloc, s, mid - 30, 5)
                new_act(cg, "work", rng.choice(TITLES["work"]), mloc, mid, e, 5)
            else:
                new_act(cg, "work", rng.choice(TITLES["work"]), wloc, s, e, 5)
        for cat, prob, durs, window, buf in (
                ("caregiver_medical", 0.35, (30, 45, 60), (9 * 60, 17 * 60 + 30), 15),
                ("errand", 0.20, (30, 45), (10 * 60, 18 * 60), 5),
                ("personal", 0.25, (60,), None, 5)):
            if rng.random() >= prob:
                continue
            for _ in range(10):
                du = rng.choice(durs)
                if window is None:
                    st = rng.choice([7 * 60, 7 * 60 + 30, 18 * 60, 18 * 60 + 30, 19 * 60])
                else:
                    st = rng.choice(range(int(window[0]), int(window[1]) + 1, 15))
                if _free(acts, cg, st, st + du, 30):
                    around = CENTER if rng.random() < 0.5 else home_ll
                    ploc = add(f"{cat[:3]}{k + 1}", f"{cg} {cat}", _place(rng, around, 0.5, 3.0), "poi")
                    new_act(cg, cat, rng.choice(TITLES[cat]), ploc, st, st + du, buf, slots=_slots(rng, st, du))
                    break

    # ---------------------------------------------------------------- chargers and zones
    chargers = []
    for j in range(14):
        ll = _place(rng, CENTER, 0.0, 2.5) if j < 6 else _place(rng, CENTER, 2.0, 8.0)
        cid = add(f"ch{j + 1:02d}", f"Public charger {j + 1}", ll, "charger")
        chargers.append(Charger(f"ch{j + 1:02d}", cid, 40.0 if rng.random() < 0.4 else 7.0))
    zones = []
    nz = n_zones if n_zones is not None else min(4, _poisson(rng, 2.0))
    for j in range(nz):
        zl = _place(rng, CENTER, 0.0, 4.0)
        zones.append(Zone(f"z{j + 1}", zl[0], zl[1], rng.uniform(150, 450), rng.uniform(0.5, 1.5),
                          rng.uniform(0.08, 0.30)))

    veh = Vehicle(soc0=soc0 if soc0 is not None else round(rng.uniform(0.25, 0.90), 2),
                  autonomy=autonomy, escort_required=True)
    return Instance(id=f"hmb_{seed:05d}", locations=locs, persons=persons, activities=acts, chargers=chargers,
                    vehicle=veh, zones=zones, day_start=7 * 60.0, active_user="Parent1",
                    meta={"seed": seed, "nc": nc, "nd": nd})


def _poisson(rng: random.Random, lam: float) -> int:
    L, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= L:
            return k
        k += 1
