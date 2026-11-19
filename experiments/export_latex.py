"""Export results/summary.json to LaTeX macros and tables used by the paper.

    python experiments/make_figures.py && python experiments/export_latex.py --out paper/
Every number quoted in the manuscript comes from these generated files.
"""
from __future__ import annotations

import argparse
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Field evaluation of the deployed prototype (three runs per condition, GPT-5.2; rubric in Appendix B)
FIELD = {
    "Proposed": [2.0, 2.0, 2.0, 4 / 3, 2.0, 2.0],
    "LLMOnly": [2.0, 2.0, 2.0, 1.0, 1.0, 1.0],
    "CalTool": [2.0, 2.0, 2.0, 1.0, 1.0, 2 / 3],
}


def f1(x):
    return f"{x:.1f}"


def f0(x):
    return f"{x:.0f}"


def f2(x):
    return f"{x:.2f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "results", "tables"))
    a = ap.parse_args()
    S = json.load(open(os.path.join(ROOT, "results", "summary.json")))
    M = {}

    def put(k, v):
        M[k] = v

    for k, v in FIELD.items():
        put(f"Field{k}", f2(100 * sum(v) / (2 * len(v))))
    case = S.get("case", {})
    cal = case.get("calibration", {})
    if cal:
        put("CalA", f2(cal["a_min"]))
        put("CalB", f2(cal["b_min_per_km"]))
        put("CalRMSE", f1(cal["rmse_min"]))
        put("FieldKm", f1(cal["observed_total_km"]))
        put("FieldMin", f0(cal["observed_total_min"]))

    # ---------------------------------------------------------------- benchmark
    b = S.get("bench")
    if b:
        tab = {r["method"]: r for r in b["table"]}
        key = {"Exact": "ISV exact (proposed)", "Rules": "Deployed rules",
               "Context": "Context-aware, no calendar changes", "Replay": "Calendar replay (non-agentic)"}
        put("NBench", f"{b['n']:,}")
        for k, name in key.items():
            r = tab[name]
            put(f"BenchFeas{k}", f1(r["feasible_pct"]))
            put(f"BenchProt{k}", f1(r["prot_service_pct"]))
            put(f"BenchOps{k}", f1(r["ops_viol_days_pct"]))
            put(f"BenchW{k}", f2(r["wmiss_per_day"]))
            put(f"BenchResched{k}", f2(r["resched_per_day"]))
            put(f"BenchCharges{k}", f2(r["charges_per_day"]))
            put(f"BenchEshort{k}", f1(r["eshort_days_pct"]))
            put(f"BenchVkt{k}", f1(r["vkt"]))
            put(f"BenchEmpty{k}", f1(r["empty_share_pct"]))
        put("BenchSecMedian", f2(b["sec_median"]))
        put("BenchSecMean", f1(b["sec_mean"]))
        put("BenchSecP", f1(b["sec_p95"]))
        put("BenchTimeout", f1(b["timeouts_pct"]))
        put("BenchFromSeed", f1(b["from_seed_pct"]))
        put("BenchDomRules", f1(b["dominance"]["rules"]["exact_better_pct"]))
        put("BenchTieRules", f1(b["dominance"]["rules"]["tie_pct"]))
        put("BenchWorseRules", f1(b["dominance"]["rules"]["exact_worse_pct"]))
        put("BenchDomReplay", f1(b["dominance"]["replay"]["exact_better_pct"]))
        put("BenchDomRulesTop", f1(b["dominance"]["rules"]["exact_better_top3_pct"]))
        put("BenchDomRulesFive", f1(b["dominance"]["rules"]["exact_better_top5_pct"]))
        put("BenchDomReplayTop", f1(b["dominance"]["replay"]["exact_better_top3_pct"]))
        put("BenchExcessRules", f1(b["rules_excess_resched_when_equal_service_pct"]))
        put("BenchFewerRules", f1(b["rules_fewer_resched_when_equal_service_pct"]))
        put("BenchEqualN", str(b["n_equal_service"]))
        put("BenchInfeasExact", f1(b["exact_infeasible_pct"]))
        put("BenchVktRed", f1(b["vkt_reduction_vs_rules_pct_feasible_both"]))
        put("BenchMeanActs", f1(b["mean_acts"]))
        put("BenchMaxVkt", f0(b["max_vkt_exact"]))
        codes = b["codes_pct_days"]
        put("BenchEscortReplay", f1(codes["replay"].get("ESCORT", 0)))
        put("BenchUnauthReplay", f1(codes["replay"].get("UNAUTHORIZED_PICKUP", 0)))
        put("BenchEnergyReplay", f1(codes["replay"].get("ENERGY", 0)))
        put("BenchEnergyRules", f1(codes["rules"].get("ENERGY", 0)))
        lp = lambda m: sum(v for c, v in codes[m].items() if "LATE_PICKUP" in c)  # noqa: E731
        put("BenchLatePickRules", f1(lp("rules")))
        put("BenchLatePickExact", f1(lp("exact")))
        by = {(r["nd"], r["method"]): r for r in b["by_nd"]}
        for nd in range(4):
            for m, k in (("exact", "Exact"), ("rules", "Rules"), ("replay", "Replay")):
                if (nd, m) in by:
                    put(f"BenchFeas{k}Nd{'ABCD'[nd]}", f1(by[(nd, m)]["feasible_pct"]))
        # table
        rows = []
        for k, name in key.items():
            r = tab[name]
            label = {"Exact": "L3 ISV exact", "Rules": "L2 deployed rules", "Context": "L1 context-aware",
                     "Replay": "L0 calendar replay"}[k]
            rows.append(f"{label} & {f1(r['feasible_pct'])} & {f1(r['ops_viol_days_pct'])} & {f1(r['prot_service_pct'])} & "
                        f"{f2(r['wmiss_per_day'])} & {f2(r['resched_per_day'])} & {f2(r['charges_per_day'])} & "
                        f"{f1(r['eshort_days_pct'])} & {f1(r['vkt'])} & {f1(r['empty_share_pct'])} \\\\")
        with open(os.path.join(a.out, "tab_bench.tex"), "w") as fh:
            fh.write("\n".join(rows) + "\n")

    # ---------------------------------------------------------------- autonomy
    au = S.get("autonomy")
    if au:
        d = {(r["autonomy"], r["agency"]): r for r in au}
        put("NAut", str(d[("HV", "exact")]["n"]))
        names = {"HV": "HV", "AV": "AV", "AV_unaccompanied": "Unacc"}
        ags = {"replay": "Replay", "rules": "Rules", "exact": "Exact"}
        rows = []
        for v, vn in names.items():
            for g, gn in ags.items():
                r = d[(v, g)]
                put(f"Aut{vn}{gn}", f1(r["feasible_pct"]))
                put(f"AutProt{vn}{gn}", f1(r["prot_service_pct"]))
                put(f"AutEmpty{vn}{gn}", f1(r["empty_vkt"]))
                put(f"AutVkt{vn}{gn}", f1(r["vkt"]))
                put(f"AutW{vn}{gn}", f2(r["wmiss"]))
                put(f"AutOps{vn}{gn}", f1(r["ops_days_pct"]))
                put(f"AutCg{vn}{gn}", f0(r["cg_onboard_min"]))
            lab = {"HV": "Human-driven", "AV": "Automated, escorted", "AV_unaccompanied": "Automated, unaccompanied allowed"}[v]
            cells = []
            for g in ags:
                r = d[(v, g)]
                cells += [f1(r["feasible_pct"]), f1(r["prot_service_pct"]), f2(r["wmiss"]), f1(r["vkt"])]
            rows.append(f"{lab} & " + " & ".join(cells) + " \\\\")
        with open(os.path.join(a.out, "tab_autonomy.tex"), "w") as fh:
            fh.write("\n".join(rows) + "\n")

    # ---------------------------------------------------------------- errors
    er = S.get("errors")
    if er:
        d = {(r["arch"], round(r["eps"], 2)): r for r in er}
        codes = {"llm_only": "LLM", "tool_agent": "Tool", "isv_rules": "ISVR", "isv_exact_nofloor": "NoFloor",
                 "isv_exact": "ISV"}
        epsn = {0.0: "Zero", 0.1: "Ten", 0.2: "Twenty", 0.3: "Thirty"}
        put("NErr", str(d[("isv_exact", 0.0)]["n"]))
        rows = []
        for arch, c in codes.items():
            cells = []
            for e, en in epsn.items():
                r = d.get((arch, e))
                if r is None:
                    continue
                put(f"ErrAvoid{c}{en}", f1(r.get("excess_unsafe_pct", r["violating_pct"])))
                put(f"ErrSilent{c}{en}", f1(r["silent_pct"]))
                put(f"ErrFlag{c}{en}", f1(r["flagged_pct"]))
                put(f"ErrW{c}{en}", f2(r.get("excess_w", r["wmiss"])))
                put(f"ErrResched{c}{en}", f2(r["resched"]))
                put(f"ErrIncons{c}{en}", f1(r["incons"]))
            label = {"llm_only": "LLM-only planner", "tool_agent": "Tool-using agent", "isv_rules": "ISV, rule planner",
                     "isv_exact_nofloor": "ISV exact, no floor", "isv_exact": "ISV exact"}[arch]
            av = [f1(d[(arch, e)].get("excess_unsafe_pct", d[(arch, e)]["violating_pct"])) for e in epsn]
            si = [f1(d[(arch, e)]["silent_pct"]) for e in epsn]
            ew = f2(d[(arch, 0.3)].get("excess_w", 0.0))
            rows.append(f"{label} & " + " & ".join(av) + " & " + " & ".join(si) + f" & {ew} \\\\")
        with open(os.path.join(a.out, "tab_errors.tex"), "w") as fh:
            fh.write("\n".join(rows) + "\n")

    # ---------------------------------------------------------------- sensitivity
    se = S.get("sensitivity")
    if se:
        d = {(r["factor"], round(r["level"], 2), r["method"]): r for r in se}
        put("NSens", str(max(r["n"] for r in se)))
        specs = [("SensEshortLow", ("soc0", 0.25), "eshort_days_pct", f1), ("SensEshortMid", ("soc0", 0.55), "eshort_days_pct", f1),
                 ("SensChargesLow", ("soc0", 0.25), "charges", f2), ("SensChargesHigh", ("soc0", 0.85), "charges", f2),
                 ("SensEnergyLow", ("soc0", 0.25), "energy_days_pct", f1),
                 ("SensFeasLow", ("soc0", 0.25), "feasible_pct", f1), ("SensFeasHigh", ("soc0", 0.85), "feasible_pct", f1),
                 ("SensEshortHigh", ("soc0", 0.85), "eshort_days_pct", f1),
                 ("SensChargeMinLow", ("soc0", 0.25), "charge_min", f0), ("SensChargeMinHigh", ("soc0", 0.85), "charge_min", f0),
                 ("SensFeasZoneZero", ("zones", 0.0), "feasible_pct", f1), ("SensFeasZoneFour", ("zones", 4.0), "feasible_pct", f1),
                 ("SensProtZoneZero", ("zones", 0.0), "prot_days_pct", f1), ("SensProtZoneFour", ("zones", 4.0), "prot_days_pct", f1),
                 ("SensInconsZoneFour", ("zones", 4.0), "incons", f1),
                 ("SensReschedAuthZero", ("authorised", 0.0), "resched", f2), ("SensReschedAuthOne", ("authorised", 1.0), "resched", f2),
                 ("SensFeasAuthZero", ("authorised", 0.0), "feasible_pct", f1), ("SensFeasAuthOne", ("authorised", 1.0), "feasible_pct", f1)]
        for m, k in (("exact", "Exact"), ("rules", "Rules"), ("replay", "Replay")):
            for name, (fac, lvl), col, fmt in specs:
                r = d.get((fac, lvl, m))
                if r is not None:
                    put(f"{name}{k}", fmt(r[col]))

    # ---------------------------------------------------------------- case study
    if case:
        sc = [("run1", "Run 1 (field)"), ("run2", "Run 2 (field)"), ("run2_any_escort", "Run 2: any escort"),
              ("run2_no_construction", "Run 2: no construction"), ("run2_HV", "Run 2: human-driven"),
              ("run2_soc80", "Run 2: 80\\% SoC")]
        pl = [("exact", "L3"), ("rules", "L2"), ("context", "L1"), ("replay", "L0")]
        rows = []
        for key_, lab in sc:
            if key_ not in case:
                continue
            first = True
            for m, ml in pl:
                if key_ not in ("run1", "run2") and m in ("context", "replay"):
                    continue
                r = case[key_][m]
                chg = ", ".join(f"{k.replace('_', ' ')} $\\to$ {int(v) // 60}:{int(v) % 60:02d}" for k, v in r["starts"].items()) or "--"
                chg = chg.replace("p1 dentist", "dentist")
                nrows = 4 if key_ in ("run1", "run2") else 2
                head = f"\\multirow{{{nrows}}}{{*}}{{\\parbox{{3.2cm}}{{\\raggedright {lab}}}}}" if first else ""
                first = False
                rows.append(f"{head} & {ml} & {r['m_ops']} & {r['m_prot']} & {r['m_wmiss']} & {r['m_nint']} & "
                            f"{f1(r['m_eshort'])} & {f1(r['m_vkt'])} & {r['legs']} & {chg} \\\\")
            rows.append("\\midrule")
        if rows and rows[-1] == "\\midrule":
            rows.pop()
        with open(os.path.join(a.out, "tab_case.tex"), "w") as fh:
            fh.write("\n".join(rows) + "\n")
        r2e, r2r = case["run2"]["exact"], case["run2"]["rules"]
        put("CaseExactKm", f1(r2e["m_vkt"]))
        put("CaseRulesKm", f1(r2r["m_vkt"]))
        put("CaseExactSoc", f0(100 * r2e["m_soc_end"]))
        put("CaseRulesSoc", f0(100 * r2r["m_soc_end"]))
        put("CaseExactCharge", f0(r2e["m_charge_min"]))
        put("CaseRulesCharge", f0(r2r["m_charge_min"]))
        put("CaseExactSec", f1(r2e.get("sec", 0)))

    with open(os.path.join(a.out, "numbers.tex"), "w") as fh:
        fh.write("% generated by experiments/export_latex.py -- do not edit by hand\n")
        for k, v in sorted(M.items()):
            fh.write(f"\\newcommand{{\\{k}}}{{{v}}}\n")
    print(f"wrote {len(M)} macros to {a.out}")


if __name__ == "__main__":
    main()
