"""Mission representation shared by planners, the verifier and the user/vehicle views."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .model import fmt_time


@dataclass
class Stop:
    loc: str
    arrive: float                 # planned arrival time
    depart: float                 # planned departure time
    alight: Tuple[str, ...] = ()
    board: Tuple[str, ...] = ()
    charge_min: float = 0.0
    charger: Optional[str] = None
    purpose: str = ""
    early: Tuple[str, ...] = ()      # persons collected before their commitment ends (declared)


@dataclass
class Mission:
    """An ordered vehicle mission M = <m_1..m_K> plus calendar decisions.

    ``stops[0]`` is the vehicle's start location. Leg k goes from stops[k] to
    stops[k+1]. ``starts`` holds rescheduled start times (activity id -> new
    start) and ``skipped`` the activities the plan deliberately does not serve.
    ``router`` records which travel information the planner relied on:
    ``aware`` (grounded traffic + construction) or ``nominal`` (no grounding).
    """
    stops: List[Stop]
    starts: Dict[str, float] = field(default_factory=dict)
    skipped: Tuple[str, ...] = ()
    router: str = "aware"
    planner: str = ""
    notes: List[str] = field(default_factory=list)

    @property
    def n_legs(self) -> int:
        return sum(1 for a, b in zip(self.stops, self.stops[1:]) if a.loc != b.loc)

    def describe(self) -> str:
        rows = []
        for i, s in enumerate(self.stops):
            act = []
            if s.alight:
                act.append("drop " + ",".join(s.alight))
            if s.board:
                act.append("pick " + ",".join(s.board) + (" (early: " + ",".join(s.early) + ")" if s.early else ""))
            if s.charge_min:
                act.append(f"charge {s.charge_min:.0f} min")
            rows.append(f"{i:2d} {fmt_time(s.arrive)}-{fmt_time(s.depart)} {s.loc:<14s} {'; '.join(act)} {s.purpose}")
        if self.starts:
            rows.append("reschedule: " + ", ".join(f"{k}->{fmt_time(v)}" for k, v in self.starts.items()))
        if self.skipped:
            rows.append("not served: " + ", ".join(self.skipped))
        return "\n".join(rows)
