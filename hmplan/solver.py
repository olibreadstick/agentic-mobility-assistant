"""Exact lexicographic mission planner for the HSVMP.

The planner enumerates calendar-change configurations (keep or move each
reschedulable activity to an admissible slot) and, for each, runs a
depth-first branch-and-bound over vehicle actions with label dominance:

  Visit(L, opt)    drive to L, drop every passenger whose next commitment is
                   at L, then board persons according to ``opt``;
  Charge(s, dur)   drive to charger s and charge for ``dur`` minutes;
  Skip(p)          decline person p's next non-protected activity.

Hard constraints that cannot be "paid for" (escort, driver, supervision,
capacity) are enforced during search; lateness, misses and energy are counted
so that a best-effort mission always exists. The returned mission is re-scored
by the independent verifier, which is the source of truth for Phi.

Modelling conventions (also stated in the paper):
  * persons leave home no earlier than READY_BEFORE minutes before their first
    commitment (household convention, avoids hours of idle riding);
  * dependents may be left at their own activity up to 30 min before start;
  * the vehicle departs as soon as boarding is complete (earliest departure),
    which is optimal under FIFO travel times; user-facing "leave by" times are
    derived afterwards (``views.py``).
"""
from __future__ import annotations

import itertools
import math
import time as _time
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from .mission import Mission, Stop
from .model import CAREGIVER, DEPENDENT, Activity, Instance, priority_weight
from .travel import TravelModel
from .verify import EARLY_DROP, EROSION_WEIGHT, RIDE_WEIGHT, SHIFT_WEIGHT, WAIT_WEIGHT, Report, verify

READY_BEFORE = 90.0
INF = float("inf")
CHARGE_DURATIONS = (20.0, 40.0, 60.0)
N_NEAREST_CHARGERS = 3
CHARGE_MARGIN = 0.25   # charging is never useful above soc_pref + 25% (> 89 km of urban driving)


@dataclass(frozen=True)
class Item:
    loc: str
    start: float
    end: float
    buffer: float
    protected: bool
    weight: int
    act: Optional[str]
    grace: float
    is_home: bool
    escorts: Tuple[int, ...] = ()


@dataclass
class SolveResult:
    mission: Optional[Mission]
    report: Optional[Report]
    phi: Optional[Tuple]
    nodes: int
    configs_evaluated: int
    seconds: float
    timed_out: bool


def _lex_ge(a: Sequence[float], b: Sequence[float]) -> bool:
    """a >= b lexicographically (with a small tolerance on floats)."""
    for x, y in zip(a, b):
        if x > y + 1e-9:
            return True
        if x < y - 1e-9:
            return False
    return True


class _Search:
    def __init__(self, inst: Instance, tm: TravelModel, starts: Dict[str, float], n_int: int,
                 incumbent: Optional[Tuple], node_limit: int, deadline: float,
                 router: str = "aware", social: bool = True):
        self.inst, self.tm = inst, tm
        self.router = router          # travel information the planner uses
        self.social = social          # enforce escort / supervision / authorisation reasoning
        self.v = inst.vehicle
        self.n_int = n_int
        self.best_phi = incumbent
        self.best_path = None
        self.nodes = 0
        self.node_limit = node_limit
        self.deadline = deadline
        self.timed_out = False
        self.pids = [p.id for p in inst.persons]
        self.n = len(self.pids)
        self.is_dep = [inst.person(p).role == DEPENDENT for p in self.pids]
        self.is_cg = [inst.person(p).role == CAREGIVER for p in self.pids]
        self.can_drive = [inst.person(p).role == CAREGIVER and inst.person(p).can_drive for p in self.pids]
        acts = [a.shifted(starts[a.id]) if a.id in starts else a for a in inst.activities]
        self.J0 = SHIFT_WEIGHT * sum(abs(starts[a.id] - a.start) for a in inst.activities if a.id in starts)
        self.items: List[List[Item]] = []
        for pid in self.pids:
            mine = sorted((a for a in acts if a.person == pid and a.sem.needs_vehicle and a.end > inst.day_start),
                          key=lambda a: a.start)
            first = mine[0].start - mine[0].buffer - READY_BEFORE if mine else INF
            sloc = inst.start_of(pid)
            seq = [Item(sloc, inst.day_start, max(inst.day_start, first) if sloc == inst.home else inst.day_start,
                        0, False, 0, None, 0, sloc == inst.home)]
            for a in mine:
                esc = tuple(self.pids.index(e) for e in a.escorts if e in self.pids)
                seq.append(Item(a.loc, a.start, a.end, a.buffer, a.sem.protected,
                                priority_weight(a.sem.priority), a.id, a.grace, False, esc))
            seq.append(Item(inst.home, INF, INF, 0, False, 0, None, 0, True))
            self.items.append(seq)
        self.chargers = list(inst.chargers)
        self.ch_power = {c.loc: c.power_kw for c in inst.chargers}
        self.memo: Dict[tuple, List[tuple]] = {}
        locs = list(inst.locations)
        # nominal off-peak times are valid lower bounds on grounded times
        self.lb = {(o, d): tm.base_time(tm._base(o, d)[0], 12 * 60.0) for o in locs for d in locs}
        for (o, d), (km, mins) in tm.overrides.items():
            if (o, d) in self.lb:
                self.lb[(o, d)] = min(self.lb[(o, d)], mins)
        self.near_ch = {}
        for o in locs:
            cs = sorted(self.chargers, key=lambda c: self.lb[(o, c.loc)])
            fast = [c for c in cs if c.power_kw >= 20.0]
            pick = []
            for c in fast[:2] + cs[:1]:
                if c.loc not in pick:
                    pick.append(c.loc)
            self.near_ch[o] = pick[:N_NEAREST_CHARGERS]

    # --------------------------------------------------------------- utilities
    def _norm(self, i: int, ploc: str, cur: int, tgt: int) -> Tuple[int, int]:
        """Advance through consecutive commitments at the same location."""
        seq = self.items[i]
        while tgt < len(seq) and seq[tgt].loc == ploc and not seq[tgt].is_home:
            cur, tgt = tgt, tgt + 1
        if tgt < len(seq) and seq[tgt].is_home and ploc == self.inst.home and tgt == len(seq) - 1:
            cur, tgt = tgt, tgt + 1
        return cur, tgt

    def _done(self, ps) -> bool:
        return all(st[2] >= len(self.items[i]) for i, st in enumerate(ps))

    def _bound(self, loc, t, soc, ps, vp, ops, wm, ncharge, J) -> Tuple:
        """Optimistic completion value (valid lexicographic lower bound)."""
        extra_p = 0
        extra_w = 0
        jrem = 0.0
        lb = self.lb
        for i, (ploc, cur, tgt, acc, flag) in enumerate(ps):
            seq = self.items[i]
            if tgt >= len(seq):
                continue
            it = seq[tgt]
            if ploc is None:
                arr = t + lb[(loc, it.loc)]
                rem = lb[(loc, it.loc)]
                frm = it.loc
            else:
                c = seq[cur]
                reach = t + lb[(loc, ploc)]
                if acc is None and self.is_dep[i] and not flag and c.protected and not c.is_home \
                        and ploc == c.loc and max(reach, c.end) > c.end + c.grace + 1e-9:
                    extra_p += 1
                arr = max(reach, c.end if acc is None else reach) + lb[(ploc, it.loc)]
                rem = lb[(loc, ploc)] + lb[(ploc, it.loc)]
                frm = it.loc
            if not it.is_home and arr > it.start + 1e-9:
                if it.protected:
                    extra_p += 1
                else:
                    extra_w += it.weight
            for k in range(tgt + 1, len(seq)):
                rem += lb[(frm, seq[k].loc)]
                frm = seq[k].loc
            jrem = max(jrem, rem)
        e_lb = max(0.0, self.v.soc_pref - soc) * 100.0 if ncharge >= self.v.max_charges else 0.0
        return (ops, vp + extra_p, wm + extra_w, self.n_int, round(e_lb, 1), round(J + jrem, 1))

    def _dominated(self, key, label) -> bool:
        lst = self.memo.get(key)
        if lst is None:
            self.memo[key] = [label]
            return False
        for o in lst:
            if all(o[k] <= label[k] + 1e-9 for k in range(len(label))):
                return True
        lst[:] = [o for o in lst if not all(label[k] <= o[k] + 1e-9 for k in range(len(label)))]
        lst.append(label)
        return False

    # --------------------------------------------------------------- search
    def run(self):
        ps0 = []
        for i in range(self.n):
            sloc = self.items[i][0].loc
            cur, tgt = self._norm(i, sloc, 0, 1)
            ps0.append((sloc, cur, tgt, None, False))
        self._dfs(self.inst.home, self.inst.day_start, self.v.soc0, tuple(ps0), frozenset(),
                  0, 0, 0, 0, self.J0, [])

    def _dfs(self, loc, t, soc, ps, onboard, vp, ops, wm, ncharge, J, path):
        self.nodes += 1
        if self.nodes > self.node_limit or (self.nodes & 1023) == 0 and _time.time() > self.deadline:
            self.timed_out = True
        if self.timed_out:
            return
        if t > self.inst.day_end_hard:
            return
        if self.best_phi is not None and _lex_ge(self._bound(loc, t, soc, ps, vp, ops, wm, ncharge, J), self.best_phi):
            return
        key = (loc, onboard, ps, ncharge)
        if self._dominated(key, (vp, ops, wm, t, -soc, J)):
            return
        if self._done(ps):
            self._finish(loc, t, soc, vp, ops, wm, J, path)
            return
        last = next((r for r in reversed(path) if r[0] == "visit"), None)
        self._last_was_charge = last is not None and last[6] > 0
        for act in self._actions(loc, t, soc, ps, onboard, ncharge):
            res = self._apply(act, loc, t, soc, ps, onboard, vp, ops, wm, ncharge, J)
            if res is None:
                continue
            nloc, nt, nsoc, nps, nob, nvp, nops, nwm, nnc, nJ, stops = res
            path.extend(stops)
            self._dfs(nloc, nt, nsoc, nps, nob, nvp, nops, nwm, nnc, nJ, path)
            del path[len(path) - len(stops):]
            if self.timed_out:
                return

    def _finish(self, loc, t, soc, vp, ops, wm, J, path):
        stops = list(path)
        if loc != self.inst.home:
            if self.v.autonomy == "HV":
                pass  # everyone is home; the vehicle is wherever the last driver left it
            leg = self.tm.leg(loc, self.inst.home, t, self.router)
            soc -= leg.dist_km * self.v.kwh_per_km / self.v.battery_kwh
            if soc < self.v.soc_crit - 1e-9:
                ops = max(ops, 1)
            J += leg.time_min
            stops.append(("visit", self.inst.home, t + leg.time_min, t + leg.time_min, (), (), 0.0, None, "return home", ()))
        e_short = max(0.0, self.v.soc_pref - soc) * 100.0
        phi = (ops, vp, wm, self.n_int, round(e_short, 1), round(J, 1))
        if self.best_phi is None or not _lex_ge(phi, self.best_phi):
            self.best_phi = phi
            self.best_path = stops

    # --------------------------------------------------------------- actions
    def _actions(self, loc, t, soc, ps, onboard, ncharge):
        seq_items = self.items
        hv = self.v.autonomy == "HV"
        has_driver = any(self.can_drive[i] for i in onboard)
        acts = []
        # where onboard persons must go
        drop_locs = {}
        for i in onboard:
            ploc, cur, tgt, acc, flag = ps[i]
            it = seq_items[i][tgt]
            drop_locs.setdefault(it.loc, []).append(it.start if not it.is_home else INF)
        # persons waiting for pickup
        pick = {}
        for i, (ploc, cur, tgt, acc, flag) in enumerate(ps):
            if ploc is None or acc is not None or tgt >= len(seq_items[i]):
                continue
            if seq_items[i][tgt].loc == ploc:
                continue
            pick.setdefault(ploc, []).append(i)
        cand = []
        for L, starts in drop_locs.items():
            cand.append((min(starts), ("visit", L, None)))
        for L, plist in pick.items():
            for i in plist:
                rel = seq_items[i][ps[i][1]].end
                urg = seq_items[i][ps[i][2]].start
                key = min(urg, rel + 600)
                cand.append((key, ("visit", L, ("one", i))))
                if len(plist) > 1:
                    cand.append((key + 0.5, ("visit", L, ("all", i))))
                # a dependent collected without a caregiver aboard: choose who escorts
                if self.social and self.is_dep[i] and not any(self.is_cg[k] for k in onboard):
                    for e, st in enumerate(ps):
                        if self.is_cg[e] and st[0] == L and st[3] is None and e != i:
                            cand.append((key + 0.25, ("visit", L, ("esc", i, e))))
        # a caregiver may leave a non-protected commitment early to escort a pending protected pickup
        if self.social and not any(self.is_cg[k] for k in onboard):
            pending = [(seq_items[d][ps[d][1]].end - seq_items[d][ps[d][1]].buffer, seq_items[d][ps[d][1]].loc)
                       for d in range(self.n)
                       if self.is_dep[d] and ps[d][0] is not None and ps[d][3] is None
                       and seq_items[d][ps[d][1]].protected and not seq_items[d][ps[d][1]].is_home]
            if pending:
                due, dloc = min(pending)
                for e, st in enumerate(ps):
                    if self.is_cg[e] and st[0] is not None and st[3] is None:
                        ce = seq_items[e][st[1]]
                        jit = due - self.tm.time(st[0], dloc, due - 30, self.router)
                        if not ce.is_home and not ce.protected and ce.loc == st[0] and ce.end > max(t, jit) + 1e-9:
                            cand.append((due - 1.0, ("visit", st[0], ("early", e, jit))))
        # movement restrictions
        out = []
        for _, a in sorted(cand, key=lambda x: x[0]):
            L = a[1]
            if L != loc and hv and not has_driver:
                continue
            out.append(a)
        # charging (no dependents aboard)
        if ncharge < self.v.max_charges and soc < min(0.999, self.v.soc_pref + CHARGE_MARGIN) \
                and not any(self.is_dep[i] for i in onboard) \
                and (not hv or has_driver):
            for c in self.near_ch[loc]:
                if c == loc and self._last_was_charge:
                    continue
                for dur in CHARGE_DURATIONS:
                    out.append(("charge", c, dur))
        # skipping non-protected commitments
        for i, (ploc, cur, tgt, acc, flag) in enumerate(ps):
            if tgt < len(seq_items[i]):
                it = seq_items[i][tgt]
                if not it.is_home and not it.protected:
                    out.append(("skip", i))
        return out

    def _move(self, loc, L, t, soc, onboard):
        """Drive from loc to L with the current passengers; returns (arrival, soc, dJ, legtime) or None."""
        if L == loc:
            return t, soc, 0.0, 0.0
        if self.social and self.v.escort_required and any(self.is_dep[i] for i in onboard) \
                and not any(self.is_cg[i] for i in onboard):
            return None
        if self.v.autonomy == "HV" and not any(self.can_drive[i] for i in onboard):
            return None
        if len(onboard) > self.v.capacity:
            return None
        leg = self.tm.leg(loc, L, t, self.router)
        nsoc = soc - leg.dist_km * self.v.kwh_per_km / self.v.battery_kwh
        dJ = leg.time_min * (1.0 + RIDE_WEIGHT * len(onboard))
        return t + leg.time_min, nsoc, dJ, leg.time_min

    def _expire(self, ps, t, vp, wm):
        """Drop targets that have already ended: they can no longer be attended."""
        recs = []
        nps = list(ps)
        for i, (ploc, cur, tgt, acc, flag) in enumerate(ps):
            seq = self.items[i]
            changed = False
            while tgt < len(seq) and not seq[tgt].is_home and seq[tgt].end <= t + 1e-9:
                it = seq[tgt]
                if it.protected:
                    vp += 1
                else:
                    wm += it.weight
                recs.append(("skip", it.act))
                tgt += 1
                changed = True
            if changed:
                if ploc is not None:
                    cur, tgt = self._norm(i, ploc, cur, tgt)
                nps[i] = (ploc, cur, tgt, acc, flag)
        return tuple(nps), vp, wm, recs

    def _apply(self, act, loc, t, soc, ps, onboard, vp, ops, wm, ncharge, J):
        res = self._apply_raw(act, loc, t, soc, ps, onboard, vp, ops, wm, ncharge, J)
        if res is None:
            return None
        nloc, nt, nsoc, nps, nob, nvp, nops, nwm, nnc, nJ, stops = res
        nps, nvp, nwm, recs = self._expire(nps, nt, nvp, nwm)
        return nloc, nt, nsoc, nps, nob, nvp, nops, nwm, nnc, nJ, stops + recs

    def _apply_raw(self, act, loc, t, soc, ps, onboard, vp, ops, wm, ncharge, J):
        items = self.items
        home = self.inst.home
        if act[0] == "skip":
            i = act[1]
            ploc, cur, tgt, acc, flag = ps[i]
            it = items[i][tgt]
            nps = list(ps)
            ntgt = tgt + 1
            ncur = cur
            if ploc is not None:
                ncur, ntgt = self._norm(i, ploc, cur, ntgt)
            nps[i] = (ploc, ncur, ntgt, acc, flag)
            stop = ("skip", it.act)
            return loc, t, soc, tuple(nps), onboard, vp, ops, wm + it.weight, ncharge, J, [stop]

        if act[0] == "charge":
            c, dur = act[1], act[2]
            mv = self._move(loc, c, t, soc, onboard)
            if mv is None:
                return None
            ta, nsoc, dJ, _ = mv
            nops = ops
            if nsoc < self.v.soc_crit - 1e-9:
                nops = max(ops, 1)
            gain = self.ch_power[c] * dur / 60.0 / self.v.battery_kwh
            if nsoc + gain > 1.0 + 1e-9 and dur > CHARGE_DURATIONS[0]:
                return None  # a shorter session reaches full
            nsoc = min(1.0, nsoc + gain)
            dep = ta + dur
            dJ += RIDE_WEIGHT * len(onboard) * dur
            stop = ("visit", c, ta, dep, (), (), dur, c, "self-charging", ())
            return c, dep, nsoc, ps, onboard, vp, nops, wm, ncharge + 1, J + dJ, [stop]

        # ------------------------------------------------------------- visit
        _, L, opt = act
        mv = self._move(loc, L, t, soc, onboard)
        if mv is None:
            return None
        ta, nsoc, dJ, _ = mv
        nops = ops
        if nsoc < self.v.soc_crit - 1e-9:
            nops = max(ops, 1)
        nps = list(ps)
        ob = set(onboard)
        nvp, nwm, nJ = vp, wm, J + dJ
        ready = ta
        alighted = []
        expired = []
        # who is present at L (not aboard) after alighting, for supervision
        present_cg = {i for i, st in enumerate(ps) if st[0] == L and self.is_cg[i]}
        al_cg = [i for i in onboard if self.is_cg[i] and items[i][ps[i][2]].loc == L]
        # 1) alight
        for i in sorted(onboard, key=lambda k: (self.is_dep[k], k)):
            ploc, cur, tgt, acc, flag = ps[i]
            it = items[i][tgt]
            if it.loc != L:
                continue
            t_al = ta
            if not it.is_home and t_al >= it.end - 1e-9:
                if it.protected:
                    nvp += 1
                else:
                    nwm += it.weight
                expired.append(("skip", it.act))
                nps[i] = (None, cur, tgt + 1, None, flag)
                continue
            if self.is_dep[i]:
                if it.is_home and self.social:
                    if not (present_cg or al_cg):
                        continue  # cannot be left home alone; stays aboard
                else:
                    gap = it.start - EARLY_DROP - ta
                    if gap > 120 and self.social:
                        continue  # too early to leave a child at the activity; stays aboard
                    if 0 < gap <= 120:
                        t_al = it.start - EARLY_DROP
            nflag = False
            if not it.is_home:
                if t_al > it.start + 1e-9:
                    if it.protected:
                        nvp += 1
                        nflag = True
                    else:
                        nwm += it.weight
                        nflag = True
                else:
                    nJ += EROSION_WEIGHT * min(it.buffer, max(0.0, t_al - (it.start - it.buffer)))
            ready = max(ready, t_al + self.inst.dwell)
            ob.discard(i)
            ncur, ntgt = tgt, tgt + 1
            # consecutive commitments at the same location
            while ntgt < len(items[i]) and items[i][ntgt].loc == L and not items[i][ntgt].is_home:
                nx = items[i][ntgt]
                if t_al > nx.start + 1e-9:
                    if nx.protected:
                        nvp += 1
                    else:
                        nwm += nx.weight
                ncur, ntgt = ntgt, ntgt + 1
            if items[i][ncur].is_home and ncur == len(items[i]) - 1:
                ntgt = len(items[i])
            nps[i] = (L, ncur, ntgt, None, nflag)
            alighted.append(i)
        # 2) accompaniment: dependents left aboard without any caregiver
        if any(self.is_dep[i] for i in ob) and not any(self.is_cg[i] for i in ob) and \
                ((self.social and self.v.escort_required) or self.v.autonomy == "HV"):
            hosts = [i for i in alighted if self.is_cg[i]]
            if True:
                if not hosts:
                    return None
                for i in [k for k in ob if self.is_dep[k]]:
                    ploc, cur, tgt, acc, flag = nps[i]
                    nps[i] = (L, cur, tgt, hosts[0], flag)
                    ob.discard(i)
                    alighted.append(i)
                    ready = max(ready, ta + self.inst.dwell)
        # 3) board
        board: List[int] = []
        early: List[int] = []
        dep = ready if alighted else ta
        if opt is not None and opt[0] == "early":
            mode, j = opt[0], opt[1]
            if nps[j][0] != L:
                return None
            cj = items[j][nps[j][1]]
            if cj.is_home or cj.protected or nps[j][3] is not None:
                return None
            dep = max(ready, ta + self.inst.dwell, opt[2] if len(opt) > 2 else ta)
            if dep >= cj.end - 1e-9:
                return None   # not actually early
            if not nps[j][4]:
                nwm += cj.weight
            early.append(j)
            board.append(j)
            opt = None
        if opt is not None:
            mode, j = opt[0], opt[1]
            if nps[j][0] != L:
                return None

            cj = items[j][nps[j][1]]
            rel_j = self.inst.day_start if (cj.is_home and (cj.end == INF or mode == "esc")) else cj.end
            dep = max(ready, rel_j)
            if mode == "esc":
                e = opt[2]
                if nps[e][0] != L or nps[e][3] is not None:
                    return None
                ce = items[e][nps[e][1]]
                rel_e = ce.end if not (ce.is_home and ce.loc == L) else self.inst.day_start
                dep = max(dep, rel_e)
            if dep > ta and not alighted:
                pass
            if not alighted:
                dep = max(dep, ta + self.inst.dwell)
            tgt_loc_j = items[j][nps[j][2]].loc if nps[j][2] < len(items[j]) else None
            for i, (ploc, cur, tgt, acc, flag) in enumerate(nps):
                if ploc != L or acc is not None or i in ob or tgt >= len(items[i]):
                    continue
                if items[i][tgt].loc == L:
                    continue
                rel = items[i][cur].end
                if rel > dep + 1e-9:
                    continue
                if i == j or mode == "all" or (tgt_loc_j is not None and items[i][tgt].loc == tgt_loc_j):
                    board.append(i)
            if mode == "esc" and opt[2] not in board:
                board.append(opt[2])
        # forced boarding: accompanied dependents and dependents who would be unsupervised
        if board and self.social:
            leaving_cg = {i for i in board if self.is_cg[i]}
            for i, (ploc, cur, tgt, acc, flag) in enumerate(nps):
                if i in board or ploc != L or not self.is_dep[i]:
                    continue
                if acc is not None and acc in leaving_cg:
                    board.append(i)
                    continue
                c_it = items[i][cur]
                institutional = (not c_it.is_home) and c_it.loc == L and acc is None
                if institutional:
                    continue
                remaining_cg = [k for k, st in enumerate(nps) if st[0] == L and self.is_cg[k] and k not in leaving_cg]
                if not remaining_cg:
                    board.append(i)
        nJ += RIDE_WEIGHT * len(ob) * (dep - ta)      # persons staying aboard while the vehicle waits
        for i in board:
            if self.is_cg[i] and L != home:
                nJ += WAIT_WEIGHT * max(0.0, dep - items[i][nps[i][1]].end)
        for i in board:
            ploc, cur, tgt, acc, flag = nps[i]
            if tgt >= len(items[i]):          # ride-along after the day is done: back home later
                cur = tgt = len(items[i]) - 1
            c_it = items[i][cur]
            if self.is_dep[i] and c_it.protected and not c_it.is_home and ploc == c_it.loc and acc is None:
                nJ += EROSION_WEIGHT * min(c_it.buffer, max(0.0, ta - (c_it.end - c_it.buffer)))
                if not flag and dep > c_it.end + c_it.grace + 1e-9:
                    nvp += 1
            nps[i] = (None, cur, tgt, None, False)
            ob.add(i)
        if not alighted and not board:
            return None
        if len(ob) > self.v.capacity:
            return None
        for i in board if self.social else ():
            if self.is_dep[i]:
                c_it = items[i][nps[i][1]]
                if c_it.escorts and not c_it.is_home and c_it.loc == L and not (ob & set(c_it.escorts)):
                    return None
        # a dependent can never be aboard without a caregiver once the vehicle must move
        stop = ("visit", L, ta, dep, tuple(self.pids[i] for i in alighted),
                tuple(self.pids[i] for i in board), 0.0, None, "", tuple(self.pids[i] for i in early))
        return L, dep, nsoc, tuple(nps), frozenset(ob), nvp, nops, nwm, ncharge, nJ, [stop] + expired


def _configs(inst: Instance) -> List[Dict[str, float]]:
    options = []
    for a in inst.activities:
        if a.sem.reschedulable and not a.sem.protected and a.slots:
            options.append([(a.id, None)] + [(a.id, s) for s in a.slots if abs(s - a.start) > 0.5])
    combos = []
    for pick in itertools.product(*options) if options else [()]:
        combos.append({aid: s for aid, s in pick if s is not None})
    combos.sort(key=len)
    return combos


def build_mission(inst: Instance, path, starts: Dict[str, float], planner: str) -> Mission:
    stops: List[Stop] = [Stop(inst.vehicle.start_loc, inst.day_start, inst.day_start, purpose="start")]
    skipped = []
    for rec in path:
        if rec[0] == "skip":
            skipped.append(rec[1])
            continue
        _, L, ta, dep, al, bd, ch, chg, purpose, early = rec
        s = Stop(L, ta, dep, tuple(al), tuple(bd), ch, chg, purpose, tuple(early))
        if len(stops) == 1 and L == stops[0].loc and not stops[0].alight and not stops[0].board:
            s.arrive = inst.day_start if ta <= inst.day_start + 1e-9 else ta
            stops[0] = s
        else:
            stops.append(s)
    return Mission(stops=stops, starts=dict(starts), skipped=tuple(skipped), router="aware", planner=planner)


def _lex_lt(a, b) -> bool:
    return not _lex_ge(a, b)


def solve(inst: Instance, tm: Optional[TravelModel] = None, time_limit: float = 20.0,
          node_limit: int = 3_000_000, planner: str = "exact", seed_heuristics: bool = True) -> SolveResult:
    """Lexicographically optimal mission (within limits), re-scored by the verifier.

    The search is warm-started with the rule-based plans, so the result is never
    worse than the deployed logic and the incumbent tightens pruning.
    """
    tm = tm or TravelModel(inst)
    t0 = _time.time()
    deadline = t0 + time_limit
    best_mission, best_rep = None, None
    if seed_heuristics:
        from .heuristics import plan as _plan
        for lvl in ("rules", "context"):
            try:
                m = _plan(inst, tm, lvl)
                rep = verify(inst, m, tm)
            except Exception:  # pragma: no cover - heuristics are best effort
                continue
            if best_rep is None or _lex_lt(rep.phi, best_rep.phi):
                best_mission, best_rep = m, rep
    best_phi = best_rep.phi if best_rep else None
    nodes = evaluated = 0
    timed_out = False
    improved = False
    for starts in _configs(inst):
        n_int = len(starts)
        if best_phi is not None and _lex_ge((0, 0, 0, n_int, 0.0, 0.0), best_phi):
            continue
        s = _Search(inst, tm, starts, n_int, best_phi, node_limit, deadline)
        s.run()
        nodes += s.nodes
        evaluated += 1
        timed_out = timed_out or s.timed_out
        if s.best_path is not None:
            m = build_mission(inst, s.best_path, starts, planner)
            rep = verify(inst, m, tm)
            if best_rep is None or _lex_lt(rep.phi, best_rep.phi):
                best_mission, best_rep, best_phi = m, rep, rep.phi
                improved = True
        if _time.time() > deadline:
            timed_out = True
            break
    if best_mission is None:
        return SolveResult(None, None, None, nodes, evaluated, _time.time() - t0, timed_out)
    if not improved:
        best_mission.planner = planner + "(seed)"
    return SolveResult(best_mission, best_rep, best_rep.phi, nodes, evaluated, _time.time() - t0, timed_out)
