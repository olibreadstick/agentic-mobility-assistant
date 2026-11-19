"""Shared evaluation helpers used by the experiment scripts."""
from __future__ import annotations

import random
import time
from typing import Dict, Optional

from .casestudy import calibrated_params
from .errors import NoisyTravelModel, corrupt
from .heuristics import plan
from .model import Instance
from .semantics import ground_truth_labels, semantic_floor
from .solver import solve
from .travel import TravelModel
from .verify import Report, verify

PARAMS, CAL_RMSE = calibrated_params()


def tm_for(inst: Instance) -> TravelModel:
    return TravelModel(inst, PARAMS)


def report_row(rep: Report, prefix: str) -> Dict[str, float]:
    codes = rep.codes()
    return {
        f"{prefix}_ops": rep.v_ops, f"{prefix}_prot": rep.v_prot, f"{prefix}_wmiss": rep.w_miss,
        f"{prefix}_nint": rep.n_int, f"{prefix}_eshort": round(rep.e_short, 2), f"{prefix}_J": round(rep.J, 2),
        f"{prefix}_feasible": int(rep.feasible), f"{prefix}_vkt": round(rep.vkt, 2),
        f"{prefix}_empty_vkt": round(rep.empty_vkt, 2), f"{prefix}_vht": round(rep.vht, 2),
        f"{prefix}_soc_end": round(rep.soc_end, 3), f"{prefix}_soc_min": round(rep.soc_min, 3),
        f"{prefix}_charges": rep.charges, f"{prefix}_charge_min": rep.charge_min,
        f"{prefix}_cg_onboard": round(rep.caregiver_onboard_min, 1), f"{prefix}_wait": round(rep.wait_min, 1),
        f"{prefix}_erosion": round(rep.buffer_erosion, 1), f"{prefix}_prot_total": rep.protected_total,
        f"{prefix}_prot_ok": rep.protected_ok, f"{prefix}_incons": rep.n_time_inconsistent,
        f"{prefix}_codes": "|".join(sorted(set(codes))),
        f"{prefix}_n_escort": codes.count("ESCORT"), f"{prefix}_n_superv": codes.count("SUPERVISION"),
        f"{prefix}_n_driver": codes.count("DRIVER"), f"{prefix}_n_energy": codes.count("ENERGY"),
        f"{prefix}_n_unauth": codes.count("UNAUTHORIZED_PICKUP"),
    }


def run_method(inst: Instance, method: str, time_limit: float = 20.0) -> Dict[str, float]:
    tm = tm_for(inst)
    t0 = time.time()
    if method == "exact":
        r = solve(inst, tm, time_limit=time_limit)
        row = report_row(r.report, method)
        row.update({f"{method}_sec": round(r.seconds, 3), f"{method}_timeout": int(r.timed_out),
                    f"{method}_nodes": r.nodes, f"{method}_configs": r.configs_evaluated,
                    f"{method}_from_seed": int(r.mission.planner.endswith("(seed)"))})
        return row
    m = plan(inst, tm, method)
    rep = verify(inst, m, tm)
    row = report_row(rep, method)
    row[f"{method}_sec"] = round(time.time() - t0, 3)
    return row


def instance_row(inst: Instance) -> Dict[str, float]:
    return {
        "id": inst.id, "seed": inst.meta.get("seed"), "nc": len(inst.caregivers), "nd": len(inst.dependents),
        "n_acts": len(inst.activities), "n_prot": sum(a.sem.protected for a in inst.activities),
        "n_resched": sum(a.sem.reschedulable for a in inst.activities), "n_zones": len(inst.zones),
        "soc0": inst.vehicle.soc0, "autonomy": inst.vehicle.autonomy,
        "escort_required": int(inst.vehicle.escort_required),
        "n_authorised": sum(1 for a in inst.activities if a.escorts),
    }


# --------------------------------------------------------------------------- error study
ARCHS = ("llm_only", "tool_agent", "isv_rules", "isv_exact", "isv_exact_nofloor")


def run_arch(true_inst: Instance, arch: str, eps: float, rep_seed: int, time_limit: float = 20.0) -> Dict:
    rng = random.Random(rep_seed)
    record_errors = arch in ("llm_only", "tool_agent")
    perceived, log = corrupt(true_inst, eps, rng, record_errors)
    if arch.startswith("isv") and arch != "isv_exact_nofloor":
        perceived = perceived.with_semantics(semantic_floor(perceived, {a.id: a.sem for a in perceived.activities}))
    true_tm = tm_for(true_inst)
    flagged = 0
    t0 = time.time()
    if arch == "llm_only":
        ptm = NoisyTravelModel(perceived, PARAMS, sigma=0.35, seed=rep_seed)
        m = plan(perceived, ptm, "rules")
        m.router = "nominal"
    elif arch == "tool_agent":
        m = plan(perceived, tm_for(perceived), "rules")
    elif arch == "isv_rules":
        ptm = tm_for(perceived)
        m = plan(perceived, ptm, "rules")
        flagged = int(not verify(perceived, m, ptm).feasible)
    else:
        ptm = tm_for(perceived)
        r = solve(perceived, ptm, time_limit=time_limit)
        m = r.mission
        flagged = int(not r.report.feasible)
    sec = time.time() - t0
    rep = verify(true_inst, m, true_tm)
    row = report_row(rep, "t")
    row.update({"arch": arch, "eps": eps, "rep_seed": rep_seed, "flagged": flagged, "sec": round(sec, 3),
                "n_errors": len(log), "error_types": "|".join(k for k, _ in log)})
    return row
