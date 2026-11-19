"""Versioned persistent route memory.

The deployed prototype keys the stored daily mission by (user, local date).
Follow-up questions are then answered from memory, which is fast but can be
stale if the calendar, vehicle state or settings changed after planning. Here
each record also stores a *context digest* -- a hash of every input the
mission depends on. A follow-up is served from memory only if the digest of
the current inputs matches; otherwise the caller is told to replan
(Remark 1 in the paper).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional, Tuple

from .mission import Mission
from .model import Instance


def context_digest(inst: Instance) -> str:
    """Stable digest of all mission inputs (records, labels, vehicle state, zones)."""
    payload = {
        "acts": sorted([(a.id, a.person, a.loc, a.start, a.end, a.buffer, a.sem.priority, a.sem.protected,
                         a.sem.reschedulable, a.slots, a.escorts) for a in inst.activities]),
        "vehicle": asdict(inst.vehicle),
        "zones": sorted([(z.id, z.lat, z.lng, z.radius_m, z.delay, z.detour) for z in inst.zones]),
        "chargers": sorted([(c.id, c.loc, c.power_kw) for c in inst.chargers]),
        "start": inst.person_start, "day_start": inst.day_start,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:16]


@dataclass
class MemoryRecord:
    mission: Mission
    digest: str
    created: float
    meta: Dict[str, Any] = field(default_factory=dict)


class RouteMemory:
    def __init__(self):
        self._store: Dict[Tuple[str, str], MemoryRecord] = {}

    def save(self, user: str, date: str, mission: Mission, inst: Instance, created: float, **meta) -> str:
        d = context_digest(inst)
        self._store[(user, date)] = MemoryRecord(mission, d, created, dict(meta))
        return d

    def lookup(self, user: str, date: str, current: Optional[Instance] = None) -> Tuple[Optional[MemoryRecord], str]:
        """Return (record, status) with status in {'hit', 'stale', 'miss'}."""
        rec = self._store.get((user, date))
        if rec is None:
            return None, "miss"
        if current is not None and context_digest(current) != rec.digest:
            return rec, "stale"
        return rec, "hit"
