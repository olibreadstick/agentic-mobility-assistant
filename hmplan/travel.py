"""Grounded travel-time, distance, energy and construction model.

The benchmark uses a calibrated travel-time surface instead of live routing so
that experiments are reproducible offline. Road distance is a circuity factor
times the great-circle distance; travel time is an affine function of road
distance scaled by a time-of-day congestion multiplier. The affine parameters
are fitted to the eight TomTom-routed legs of the Montreal field case
(``calibrate_from_legs``). Construction zones modify legs whose straight-line
path crosses a work-zone disc: a leg either passes through (delayed) or takes a
detour (longer), using the deployed system's acceptance rule (extra time <= 15
min and ratio <= 1.25) when the planner is construction-aware.

Three query modes are exposed:
  * ``aware``   -- what a construction-aware, traffic-aware router returns;
  * ``nominal`` -- what a planner without construction/traffic data assumes;
  * ``through`` -- what actually happens if the vehicle ignores construction.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, Iterable, List, Sequence, Tuple

from .model import Instance, Location, Zone

EARTH_R_KM = 6371.0088


def haversine_km(a: Location, b: Location) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a.lat, a.lng, b.lat, b.lng))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * EARTH_R_KM * math.asin(min(1.0, math.sqrt(h)))


def _xy(lat: float, lng: float, lat0: float) -> Tuple[float, float]:
    """Equirectangular projection in metres (adequate at city scale)."""
    x = math.radians(lng) * EARTH_R_KM * 1000 * math.cos(math.radians(lat0))
    y = math.radians(lat) * EARTH_R_KM * 1000
    return x, y


def segment_hits_disc(a: Location, b: Location, z: Zone) -> bool:
    lat0 = (a.lat + b.lat + z.lat) / 3
    ax, ay = _xy(a.lat, a.lng, lat0)
    bx, by = _xy(b.lat, b.lng, lat0)
    cx, cy = _xy(z.lat, z.lng, lat0)
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 == 0:
        return math.hypot(cx - ax, cy - ay) <= z.radius_m
    t = max(0.0, min(1.0, ((cx - ax) * dx + (cy - ay) * dy) / L2))
    px, py = ax + t * dx, ay + t * dy
    return math.hypot(cx - px, cy - py) <= z.radius_m


@dataclass(frozen=True)
class TravelParams:
    circuity: float = 1.40          # road km per great-circle km (urban grid)
    a_min: float = 2.6              # fixed access/egress/parking time (min)
    b_min_per_km: float = 2.45      # marginal minutes per road km (off-peak)
    am_peak: Tuple[float, float, float] = (7 * 60, 9 * 60, 1.25)
    pm_peak: Tuple[float, float, float] = (15.5 * 60, 18.5 * 60, 1.30)
    max_extra_reroute_min: float = 15.0   # deployed acceptance rule
    max_extra_time_ratio: float = 1.25    # deployed acceptance rule


@dataclass(frozen=True)
class Leg:
    dist_km: float
    time_min: float
    mode: str              # base | detour | through
    zones: Tuple[str, ...]


class TravelModel:
    """Grounded oracle for leg times/distances on an instance."""

    def __init__(self, inst: Instance, params: TravelParams = TravelParams(),
                 overrides: Dict[Tuple[str, str], Tuple[float, float]] = None):
        self.inst = inst
        self.p = params
        # observed (km, minutes) for specific directed pairs, e.g. field-routed legs
        self.overrides = dict(overrides or inst.meta.get("leg_overrides", {}) or {})
        self.locs = inst.locations
        self._zones = list(inst.zones)
        self._cache: Dict[Tuple[str, str], Tuple[float, Tuple[Zone, ...]]] = {}

    # ------------------------------------------------------------------ basics
    def tod_mult(self, t: float) -> float:
        """Congestion multiplier with 20-minute linear ramps (keeps travel times FIFO)."""
        t = t % (24 * 60)
        ramp = 20.0
        best = 1.0
        for lo, hi, m in (self.p.am_peak, self.p.pm_peak):
            if lo <= t < hi:
                w = 1.0
            elif lo - ramp <= t < lo:
                w = (t - (lo - ramp)) / ramp
            elif hi <= t < hi + ramp:
                w = 1.0 - (t - hi) / ramp
            else:
                w = 0.0
            best = max(best, 1.0 + w * (m - 1.0))
        return best

    def _base(self, o: str, d: str) -> Tuple[float, Tuple[Zone, ...]]:
        key = (o, d)
        if key not in self._cache:
            if o == d:
                self._cache[key] = (0.0, ())
            else:
                a, b = self.locs[o], self.locs[d]
                km = self.p.circuity * haversine_km(a, b)
                hits = tuple(z for z in self._zones if segment_hits_disc(a, b, z))
                self._cache[key] = (km, hits)
        return self._cache[key]

    def base_time(self, km: float, t: float) -> float:
        if km <= 0:
            return 0.0
        return (self.p.a_min + self.p.b_min_per_km * km) * self.tod_mult(t)

    # ------------------------------------------------------------------ queries
    def leg(self, o: str, d: str, t: float, mode: str = "aware") -> Leg:
        km, hits = self._base(o, d)
        if km == 0:
            return Leg(0.0, 0.0, "base", ())
        if (o, d) in self.overrides:
            okm, omin = self.overrides[(o, d)]
            km, base = okm, omin
            if not hits or mode == "nominal":
                return Leg(km, base, "base", ())
        else:
            base = self.base_time(km, t)
        zids = tuple(z.id for z in hits)
        if mode == "nominal" or not hits:
            return Leg(km, base, "base", ())
        delay = sum(z.delay for z in hits)
        through = Leg(km, base * (1.0 + delay), "through", zids)
        if mode == "through":
            return through
        overhead = sum(z.detour for z in hits)
        detour = Leg(km * (1.0 + 0.8 * overhead), base * (1.0 + overhead), "detour", zids)
        acceptable = (detour.time_min - base <= self.p.max_extra_reroute_min and
                      detour.time_min <= base * self.p.max_extra_time_ratio)
        if acceptable and detour.time_min < through.time_min:
            return detour
        return through

    def time(self, o: str, d: str, t: float, mode: str = "aware") -> float:
        return self.leg(o, d, t, mode).time_min

    def km(self, o: str, d: str, t: float = 12 * 60, mode: str = "aware") -> float:
        return self.leg(o, d, t, mode).dist_km


def calibrate_from_legs(legs: Sequence[Tuple[float, float, float]], params: TravelParams = TravelParams()
                        ) -> Tuple[float, float, float]:
    """Fit (a, b) in t = m(t_dep) * (a + b * d) by least squares.

    ``legs`` holds (road_km, observed_minutes, departure_minute) tuples. Returns
    (a, b, rmse). The congestion multipliers are taken as given.
    """
    tm = TravelModel.__new__(TravelModel)
    tm.p = params
    xs, ys = [], []
    for km, mins, dep in legs:
        m = TravelModel.tod_mult(tm, dep)
        xs.append((m, m * km))
        ys.append(mins)
    # normal equations for two regressors without intercept
    s11 = sum(x[0] * x[0] for x in xs)
    s12 = sum(x[0] * x[1] for x in xs)
    s22 = sum(x[1] * x[1] for x in xs)
    t1 = sum(x[0] * y for x, y in zip(xs, ys))
    t2 = sum(x[1] * y for x, y in zip(xs, ys))
    det = s11 * s22 - s12 * s12
    a = (t1 * s22 - t2 * s12) / det
    b = (s11 * t2 - s12 * t1) / det
    rmse = math.sqrt(sum((a * x[0] + b * x[1] - y) ** 2 for x, y in zip(xs, ys)) / len(ys))
    return a, b, rmse
