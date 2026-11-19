"""Controlled fault injection for interpretation and numeric errors.

These utilities emulate the *kinds* of errors a language-model component can
introduce, at controlled rates, so that the architectures can be compared on
how they propagate or contain them. They do not model any particular LLM.

Semantic errors (labels):  unprotect, overprotect, priority, resched
Record errors (facts):     omit, time, place  -- only possible when the LLM
                           transcribes calendar records itself
Numeric errors:            travel times guessed without routing tools
"""
from __future__ import annotations

import math
import random
import zlib
from dataclasses import replace
from typing import Dict, List, Tuple

from .model import Instance, Semantics
from .travel import Leg, TravelModel, TravelParams

SEMANTIC = ("unprotect", "overprotect", "priority", "resched")
RECORD = ("omit", "time", "place")


def corrupt(inst: Instance, eps: float, rng: random.Random, record_errors: bool) -> Tuple[Instance, List[Tuple[str, str]]]:
    """Return the instance as perceived by the reasoning component, plus an error log."""
    types = SEMANTIC + (RECORD if record_errors else ())
    acts = []
    log: List[Tuple[str, str]] = []
    other_locs = [l for l, L in inst.locations.items() if L.kind in ("poi", "work", "school")]
    for a in inst.activities:
        if rng.random() >= eps:
            acts.append(a)
            continue
        kind = rng.choice(types)
        sem = a.sem
        if kind == "unprotect" and not sem.protected:
            kind = "priority"
        if kind == "overprotect" and sem.protected:
            kind = "priority"
        if kind == "unprotect":
            a = replace(a, sem=Semantics(priority=3, protected=False, reschedulable=True))
        elif kind == "overprotect":
            a = replace(a, sem=Semantics(priority=1, protected=True, reschedulable=False))
        elif kind == "priority":
            p = min(5, max(1, sem.priority + rng.choice((-2, -1, 1, 2))))
            a = replace(a, sem=replace(sem, priority=p))
        elif kind == "resched":
            a = replace(a, sem=replace(sem, reschedulable=not sem.reschedulable))
        elif kind == "omit":
            log.append((kind, a.id))
            continue
        elif kind == "time":
            d = rng.choice((-60, -30, -15, 15, 30, 60))
            a = replace(a, start=a.start + d, end=a.end + d)
        elif kind == "place":
            choices = [l for l in other_locs if l != a.loc]
            if choices:
                a = replace(a, loc=rng.choice(choices))
        log.append((kind, a.id))
        acts.append(a)
    return replace(inst, activities=acts), log


class NoisyTravelModel(TravelModel):
    """Travel times as guessed without routing tools: no construction or
    congestion information and a persistent multiplicative error per OD pair."""

    def __init__(self, inst: Instance, params: TravelParams, sigma: float = 0.35, seed: int = 0):
        super().__init__(inst, params)
        self.sigma = sigma
        self.seed = seed
        self._f: Dict[Tuple[str, str], float] = {}

    def _factor(self, o: str, d: str) -> float:
        key = (o, d)
        if key not in self._f:
            r = random.Random(zlib.crc32(f"{self.seed}|{o}|{d}".encode()))
            self._f[key] = math.exp(r.gauss(-0.5 * self.sigma ** 2, self.sigma))
        return self._f[key]

    def leg(self, o: str, d: str, t: float, mode: str = "aware") -> Leg:
        base = super().leg(o, d, 12 * 60.0, "nominal")
        if base.dist_km == 0:
            return base
        return Leg(base.dist_km, base.time_min * self._factor(o, d), "guess", ())
