"""Montreal field case (Runs 1 and 2) re-encoded from the deployed prototype.

Times, activities, battery levels and the eight TomTom-routed legs of Run 2
are taken from the deployed system's outputs (demonstration paper, video and
repository figures). Coordinates are approximate geocodes used only for legs
that were not routed in the field run; the observed legs are injected as
travel-time overrides so the case study reproduces field conditions.
"""
from __future__ import annotations

from typing import Dict, Tuple

from .model import (CAREGIVER, DEPENDENT, Activity, Charger, Instance, Location, Person, Semantics, Vehicle,
                    Zone)
from .travel import TravelParams, calibrate_from_legs

H = lambda h, m=0: h * 60.0 + m  # noqa: E731

LOCS = {
    "home": Location("home", "1380 Sherbrooke St W (home)", 45.4986, -73.5794, "home"),
    "p1_work": Location("p1_work", "Macdonald Engineering Building, 817 Sherbrooke St W", 45.5049, -73.5761, "work"),
    "p2_work": Location("p2_work", "1 Place Ville Marie", 45.5016, -73.5690, "work"),
    "charger": Location("charger", "900 Rene-Levesque Blvd W (charging)", 45.4994, -73.5683, "charger"),
    "school1": Location("school1", "4350 Sainte-Catherine St W (Child1 school)", 45.4910, -73.5840, "school"),
    "school2": Location("school2", "11 Chemin de la Cote-Saint-Antoine (Child2 school)", 45.4905, -73.5898, "school"),
    "dentist": Location("dentist", "1194 Rue Mackay (dentist)", 45.4975, -73.5755, "poi"),
}

# Field-routed legs of Run 2 (TomTom): (origin, destination, km, minutes, departure)
FIELD_LEGS = [
    ("home", "p1_work", 3.6, 12, H(10, 38)),
    ("p1_work", "p2_work", 2.0, 11, H(11, 0)),
    ("p2_work", "charger", 0.6, 3, H(12, 0)),
    ("charger", "p2_work", 0.8, 5, H(13, 27)),
    ("p2_work", "p1_work", 1.2, 6, H(14, 30)),
    ("p1_work", "school1", 4.3, 13, H(15, 0)),
    ("school1", "school2", 4.8, 12, H(16, 0)),
    ("school2", "home", 3.4, 12, H(16, 45)),
]

MANSFIELD = Zone("mansfield", 45.5030, -73.5733, 140.0, delay=0.9, detour=0.15, street="Rue Mansfield")


def _sem(priority: int, protected: bool, reschedulable: bool) -> Semantics:
    return Semantics(priority=priority, protected=protected, reschedulable=reschedulable)


def calibrated_params() -> Tuple[TravelParams, float]:
    base = TravelParams()
    a, b, rmse = calibrate_from_legs([(km, mins, dep) for _, _, km, mins, dep in FIELD_LEGS], base)
    return TravelParams(a_min=a, b_min_per_km=b), rmse


def _overrides() -> Dict[Tuple[str, str], Tuple[float, float]]:
    return {(o, d): (km, float(m)) for o, d, km, m, _ in FIELD_LEGS}


def _persons():
    return [Person("Parent1", CAREGIVER), Person("Parent2", CAREGIVER),
            Person("Child1", DEPENDENT, False), Person("Child2", DEPENDENT, False)]


def run2(soc0: float = 0.35, with_construction: bool = True, escorts: Tuple[str, ...] = ("Parent1",)) -> Instance:
    """Constrained case: low battery, dentist conflicting with protected pickups, construction."""
    slots = tuple(H(16, 30) + 15 * k for k in range(9))  # provider availability 16:30-18:30 (assumed)
    acts = [
        Activity("p1_research", "Parent1", "Research meeting", "work", "p1_work", H(11), H(15), 5,
                 _sem(3, False, False)),
        Activity("p1_dentist", "Parent1", "Dentist appointment", "caregiver_medical", "dentist", H(16), H(16, 45),
                 15, _sem(2, False, True), slots=slots),
        Activity("p2_work", "Parent2", "Work meeting", "work", "p2_work", H(12), H(14, 30), 5,
                 _sem(3, False, False)),
        Activity("c1_school", "Child1", "School (pickup 4:00 PM)", "school", "school1", H(8, 30), H(16), 10,
                 _sem(1, True, False), escorts=escorts),
        Activity("c2_school", "Child2", "School (pickup 4:45 PM)", "school", "school2", H(8, 30), H(16, 45), 10,
                 _sem(1, True, False), escorts=escorts),
    ]
    return Instance(
        id="montreal_run2", locations=dict(LOCS), persons=_persons(), activities=acts,
        chargers=[Charger("ce_900rl", "charger", 40.0)],
        vehicle=Vehicle(soc0=soc0, soc_pref=0.65, soc_crit=0.20, autonomy="AV", escort_required=True),
        zones=[MANSFIELD] if with_construction else [], day_start=H(10, 30), active_user="Parent1",
        person_start={"Child1": "school1", "Child2": "school2"},
        meta={"leg_overrides": _overrides(), "source": "field case, Run 2"},
    )


def run1(escorts: Tuple[str, ...] = ("Parent1",)) -> Instance:
    """Feasible case: 80% battery, sequential caregiver drop-offs, two protected pickups."""
    acts = [
        Activity("p2_work", "Parent2", "Work meeting", "work", "p2_work", H(9), H(13, 30), 5, _sem(3, False, False)),
        Activity("p1_research", "Parent1", "Research meeting", "work", "p1_work", H(10), H(13, 15), 5,
                 _sem(3, False, False)),
        Activity("c1_school", "Child1", "School (pickup 3:30 PM)", "school", "school1", H(8, 30), H(15, 30), 10,
                 _sem(1, True, False), escorts=escorts),
        Activity("c2_school", "Child2", "School (pickup 4:15 PM)", "school", "school2", H(8, 30), H(16, 15), 10,
                 _sem(1, True, False), escorts=escorts),
    ]
    return Instance(
        id="montreal_run1", locations=dict(LOCS), persons=_persons(), activities=acts,
        chargers=[Charger("ce_900rl", "charger", 40.0)],
        vehicle=Vehicle(soc0=0.80, soc_pref=0.65, soc_crit=0.20, autonomy="AV", escort_required=True),
        zones=[], day_start=H(8, 15), active_user="Parent1",
        person_start={"Child1": "school1", "Child2": "school2"},
        meta={"leg_overrides": _overrides(), "source": "field case, Run 1"},
    )
