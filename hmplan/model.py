"""Core data model for the Household Shared-Vehicle Mission Problem (HSVMP).

All times are minutes after midnight (floats). Distances are km, energy kWh,
state of charge (SoC) is a fraction in [0, 1].

The model separates three kinds of information, mirroring the architecture
in the paper:

* records   -- facts that come from calendars, settings and vehicle telemetry
               (who, where, when). These are never produced by a language model.
* semantics -- interpretive labels (priority, protection, reschedulability)
               that an LLM may propose and a deterministic floor may override.
* grounded  -- quantities computed by deterministic services (travel time,
               distance, energy, construction impact); see ``travel.py``.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional, Tuple

CAREGIVER = "caregiver"
DEPENDENT = "dependent"

# Activity categories used by the generator, the semantic layer and the LLM schema.
CATEGORIES = (
    "school",            # dependent school / daycare (drop-off + pickup)
    "child_activity",    # dependent extracurricular (piano, soccer, ...)
    "child_medical",     # dependent medical appointment
    "work",              # caregiver work / meeting / research
    "caregiver_medical", # caregiver medical / dentist
    "errand",            # administrative / accountant / bank
    "personal",          # gym, social, flexible
)


@dataclass(frozen=True)
class Location:
    id: str
    name: str
    lat: float
    lng: float
    kind: str = "poi"  # home | work | school | poi | charger


@dataclass(frozen=True)
class Person:
    id: str
    role: str                 # CAREGIVER | DEPENDENT
    can_drive: bool = True


@dataclass(frozen=True)
class Semantics:
    """Interpretive labels attached to an activity (proposed by the semantic layer)."""
    priority: int             # 1 (highest) .. 5 (lowest)
    protected: bool           # must not be missed, moved or delayed
    reschedulable: bool       # may be moved to one of the candidate slots
    needs_vehicle: bool = True


@dataclass(frozen=True)
class Activity:
    id: str
    person: str
    title: str
    category: str
    loc: str
    start: float
    end: float
    buffer: float             # required arrival buffer (min) before start
    sem: Semantics
    slots: Tuple[float, ...] = ()   # admissible alternative start times (records)
    grace: float = 5.0        # pickup tolerance after end for dependents (min)
    escorts: Tuple[str, ...] = ()   # caregivers authorised to collect a dependent (empty = any)

    @property
    def duration(self) -> float:
        return self.end - self.start

    def shifted(self, new_start: float) -> "Activity":
        return replace(self, start=new_start, end=new_start + self.duration)


@dataclass(frozen=True)
class Charger:
    id: str
    loc: str
    power_kw: float           # effective average power while charging


@dataclass(frozen=True)
class Zone:
    """A construction work zone (circle) with its traffic impact."""
    id: str
    lat: float
    lng: float
    radius_m: float
    delay: float              # multiplicative delay on legs passing through (0.5 = +50%)
    detour: float             # multiplicative overhead of the detour avoiding the zone
    street: str = ""


@dataclass(frozen=True)
class Vehicle:
    battery_kwh: float = 64.0
    soc0: float = 0.8
    soc_crit: float = 0.20
    soc_pref: float = 0.65
    kwh_per_km: float = 0.18
    capacity: int = 5
    start_loc: str = "home"
    autonomy: str = "AV"          # "AV": may drive empty; "HV": a caregiver must drive
    escort_required: bool = True  # dependents may not ride without a caregiver
    max_charges: int = 2


@dataclass
class Instance:
    id: str
    locations: Dict[str, Location]
    persons: List[Person]
    activities: List[Activity]
    chargers: List[Charger]
    vehicle: Vehicle
    zones: List[Zone] = field(default_factory=list)
    home: str = "home"
    day_start: float = 7 * 60.0
    day_end_hard: float = 26 * 60.0
    dwell: float = 1.0            # boarding/alighting time per stop (min)
    active_user: str = "Parent1"
    person_start: Dict[str, str] = field(default_factory=dict)   # initial location if not home
    meta: Dict[str, object] = field(default_factory=dict)

    def start_of(self, pid: str) -> str:
        return self.person_start.get(pid, self.home)

    # ------------------------------------------------------------------ helpers
    def person(self, pid: str) -> Person:
        for p in self.persons:
            if p.id == pid:
                return p
        raise KeyError(pid)

    @property
    def caregivers(self) -> List[str]:
        return [p.id for p in self.persons if p.role == CAREGIVER]

    @property
    def dependents(self) -> List[str]:
        return [p.id for p in self.persons if p.role == DEPENDENT]

    def activities_of(self, pid: str) -> List[Activity]:
        return sorted((a for a in self.activities if a.person == pid), key=lambda a: a.start)

    def activity(self, aid: str) -> Activity:
        for a in self.activities:
            if a.id == aid:
                return a
        raise KeyError(aid)

    def with_semantics(self, labels: Dict[str, Semantics]) -> "Instance":
        """Return a copy whose activities carry the given semantic labels."""
        acts = [replace(a, sem=labels.get(a.id, a.sem)) for a in self.activities]
        return replace(self, activities=acts)

    def with_vehicle(self, **kw) -> "Instance":
        return replace(self, vehicle=replace(self.vehicle, **kw))

    def with_times(self, starts: Dict[str, float]) -> "Instance":
        acts = [a.shifted(starts[a.id]) if a.id in starts else a for a in self.activities]
        return replace(self, activities=acts)


def priority_weight(priority: int) -> int:
    """Weight of missing a non-protected activity of a given priority (1 = highest)."""
    return max(1, 6 - int(priority))


def fmt_time(m: Optional[float]) -> str:
    if m is None:
        return "--:--"
    m = int(round(m))
    return f"{m // 60:02d}:{m % 60:02d}"
