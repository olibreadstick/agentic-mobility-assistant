"""Run all computational experiments of the paper.

Usage:
    python experiments/run_experiments.py case
    python experiments/run_experiments.py bench     --n 1000
    python experiments/run_experiments.py autonomy  --n 300
    python experiments/run_experiments.py errors    --n 150
    python experiments/run_experiments.py sensitivity --n 100
    python experiments/run_experiments.py all

Raw results are appended to results/raw/<experiment>.jsonl (one JSON object
per line), so interrupted runs can be resumed; ``--fresh`` starts over.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from multiprocessing import Pool

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from hmplan.casestudy import FIELD_LEGS, calibrated_params, run1, run2  # noqa: E402
from hmplan.generator import generate  # noqa: E402
from hmplan.heuristics import plan  # noqa: E402
from hmplan.runner import ARCHS, instance_row, report_row, run_arch, run_method, tm_for  # noqa: E402
from hmplan.solver import solve  # noqa: E402
from hmplan.verify import verify  # noqa: E402

RAW = os.path.join(ROOT, "results", "raw")
TIME_LIMIT = 20.0


def _done_keys(path, keyf):
    if not os.path.exists(path):
        return set()
    keys = set()
    with open(path) as f:
        for line in f:
            try:
                keys.add(keyf(json.loads(line)))
            except Exception:
                pass
    return keys


def _run_pool(name, jobs, worker, keyf, fresh, procs):
    os.makedirs(RAW, exist_ok=True)
    path = os.path.join(RAW, f"{name}.jsonl")
    if fresh and os.path.exists(path):
        os.remove(path)
    done = _done_keys(path, keyf)
    todo = [j for j in jobs if keyf(j) not in done]
    print(f"[{name}] {len(todo)} jobs ({len(done)} already done)", flush=True)
    t0 = time.time()
    with open(path, "a") as out, Pool(procs) as pool:
        for k, row in enumerate(pool.imap_unordered(worker, todo, chunksize=1), 1):
            out.write(json.dumps(row) + "\n")
            out.flush()
            if k % 25 == 0:
                print(f"[{name}] {k}/{len(todo)}  {time.time() - t0:.0f}s", flush=True)
    print(f"[{name}] finished in {time.time() - t0:.0f}s", flush=True)


# ----------------------------------------------------------------------------- workers
def w_bench(job):
    inst = generate(job["seed"])
    row = instance_row(inst)
    row["seed"] = job["seed"]
    for m in ("exact", "rules", "context", "replay"):
        row.update(run_method(inst, m, TIME_LIMIT))
    return row


def w_autonomy(job):
    seed, variant = job["seed"], job["variant"]
    if variant == "HV":
        inst = generate(seed, autonomy="HV")
    elif variant == "AV_unaccompanied":
        inst = generate(seed).with_vehicle(escort_required=False)
    else:
        inst = generate(seed)
    row = instance_row(inst)
    row.update({"seed": seed, "variant": variant})
    for m in ("exact", "rules", "replay"):
        row.update(run_method(inst, m, TIME_LIMIT))
    return row


def w_errors(job):
    inst = generate(job["seed"])
    row = run_arch(inst, job["arch"], job["eps"], job["seed"] * 1000 + int(round(job["eps"] * 100)), TIME_LIMIT)
    row.update({"seed": job["seed"], "nd": len(inst.dependents), "nc": len(inst.caregivers),
                "n_acts": len(inst.activities)})
    return row


def w_sens(job):
    seed, factor, level = job["seed"], job["factor"], job["level"]
    if factor == "soc0":
        inst = generate(seed, soc0=level)
    elif factor == "zones":
        inst = generate(seed, n_zones=int(level))
    elif factor == "authorised":
        inst = generate(seed, authorised_prob=level)
    else:
        raise ValueError(factor)
    row = instance_row(inst)
    row.update({"seed": seed, "factor": factor, "level": level})
    for m in ("exact", "rules", "replay"):
        row.update(run_method(inst, m, TIME_LIMIT))
    return row


# ----------------------------------------------------------------------------- case study
def case():
    from hmplan.travel import TravelModel
    prm, rmse = calibrated_params()
    out = {"calibration": {"a_min": prm.a_min, "b_min_per_km": prm.b_min_per_km, "rmse_min": rmse,
                           "legs": [list(l) for l in FIELD_LEGS],
                           "observed_total_km": sum(l[2] for l in FIELD_LEGS),
                           "observed_total_min": sum(l[3] for l in FIELD_LEGS)}}
    scenarios = {
        "run1": run1(),
        "run2": run2(),
        "run2_any_escort": run2(escorts=()),
        "run2_no_construction": run2(with_construction=False),
        "run2_HV": run2().with_vehicle(autonomy="HV"),
        "run2_soc80": run2(soc0=0.80),
    }
    lines = []
    for name, inst in scenarios.items():
        tm = TravelModel(inst, prm)
        res = {}
        for m in ("exact", "rules", "context", "replay"):
            if m == "exact":
                r = solve(inst, tm, time_limit=120)
                mission, rep = r.mission, r.report
                extra = {"sec": r.seconds, "timeout": r.timed_out}
            else:
                mission = plan(inst, tm, m)
                rep = verify(inst, mission, tm)
                extra = {}
            row = report_row(rep, "m")
            row.update(extra)
            row["legs"] = mission.n_legs
            row["starts"] = {k: v for k, v in mission.starts.items()}
            row["violations"] = [(v.code, v.ref, v.detail) for v in rep.violations]
            res[m] = row
            lines.append(f"=== {name} / {m}  Phi={rep.phi}  legs={mission.n_legs}  vkt={rep.vkt:.1f}  "
                         f"vht={rep.vht:.1f}  soc_end={rep.soc_end:.2f}")
            lines.append(mission.describe())
            lines.append("violations: " + str([(v.code, v.ref) for v in rep.violations]))
        out[name] = res
    os.makedirs(RAW, exist_ok=True)
    with open(os.path.join(RAW, "case.json"), "w") as f:
        json.dump(out, f, indent=1)
    with open(os.path.join(ROOT, "results", "case_missions.txt"), "w") as f:
        f.write("\n".join(lines))
    print("\n".join(lines))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["case", "bench", "autonomy", "errors", "sensitivity", "all"])
    ap.add_argument("--n", type=int, default=None)
    ap.add_argument("--procs", type=int, default=max(1, (os.cpu_count() or 2)))
    ap.add_argument("--fresh", action="store_true")
    a = ap.parse_args()
    if a.what in ("case", "all"):
        case()
    if a.what in ("bench", "all"):
        n = a.n or 1000
        _run_pool("bench", [{"seed": s} for s in range(n)], w_bench, lambda j: j["seed"], a.fresh, a.procs)
    if a.what in ("autonomy", "all"):
        n = a.n or 300
        jobs = [{"seed": s, "variant": v} for s in range(n) for v in ("HV", "AV_unaccompanied")]
        _run_pool("autonomy", jobs, w_autonomy, lambda j: (j["seed"], j["variant"]), a.fresh, a.procs)
    if a.what in ("errors", "all"):
        n = a.n or 150
        jobs = [{"seed": s, "eps": e, "arch": ar} for s in range(n) for e in (0.0, 0.1, 0.2, 0.3) for ar in ARCHS]
        _run_pool("errors", jobs, w_errors, lambda j: (j["seed"], j["eps"], j["arch"]), a.fresh, a.procs)
    if a.what in ("sensitivity", "all"):
        n = a.n or 100
        jobs = [{"seed": s, "factor": "soc0", "level": l} for s in range(n) for l in (0.25, 0.40, 0.55, 0.70, 0.85)]
        jobs += [{"seed": s, "factor": "zones", "level": l} for s in range(n) for l in (0, 2, 4)]
        jobs += [{"seed": s, "factor": "authorised", "level": l} for s in range(n) for l in (0.0, 0.5, 1.0)]
        _run_pool("sensitivity", jobs, w_sens, lambda j: (j["seed"], j["factor"], j["level"]), a.fresh, a.procs)


if __name__ == "__main__":
    main()
