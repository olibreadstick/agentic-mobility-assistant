"""Summarise raw experiment results into the tables and figures of the paper.

    python experiments/make_figures.py            # all available experiments
Outputs: results/tables/*.csv, results/tables/*.tex, results/figures/*.pdf|png, results/summary.json
"""
from __future__ import annotations

import json
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "results", "raw")
TAB = os.path.join(ROOT, "results", "tables")
FIG = os.path.join(ROOT, "results", "figures")
os.makedirs(TAB, exist_ok=True)
os.makedirs(FIG, exist_ok=True)

# Validated categorical palette (fixed order) + texture for print/CVD
SLOT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]
HATCH = ["", "//", "\\\\", "..", "xx", "--"]
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"
METHOD_LABEL = {"exact": "ISV exact (proposed)", "rules": "Deployed rules", "context": "Context-aware, no calendar changes",
                "replay": "Calendar replay (non-agentic)"}
ARCH_LABEL = {"isv_exact": "ISV exact", "isv_rules": "ISV with rule planner", "isv_exact_nofloor": "ISV exact, no floor",
              "tool_agent": "Tool-using agent", "llm_only": "LLM-only planner"}

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 8.5, "axes.edgecolor": INK2, "axes.labelcolor": INK,
    "xtick.color": INK2, "ytick.color": INK2, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "axes.axisbelow": True,
    "legend.frameon": False, "figure.dpi": 150, "savefig.bbox": "tight", "lines.linewidth": 2.0,
})


def load(name):
    p = os.path.join(RAW, f"{name}.jsonl")
    if not os.path.exists(p):
        return None
    return pd.DataFrame([json.loads(l) for l in open(p) if l.strip()])


def save(fig, name):
    fig.savefig(os.path.join(FIG, name + ".pdf"))
    fig.savefig(os.path.join(FIG, name + ".png"), dpi=300)
    plt.close(fig)


def pct(x):
    return 100.0 * float(np.mean(x))


def method_summary(df, methods, prefix_map=None):
    rows = []
    for m in methods:
        prot_rate = 100.0 * df[f"{m}_prot_ok"].sum() / max(1, df[f"{m}_prot_total"].sum())
        row = {
            "method": METHOD_LABEL.get(m, m),
            "feasible_pct": pct(df[f"{m}_feasible"]),
            "ops_viol_days_pct": pct(df[f"{m}_ops"] > 0),
            "prot_service_pct": prot_rate,
            "prot_viol_per_day": df[f"{m}_prot"].mean(),
            "wmiss_per_day": df[f"{m}_wmiss"].mean(),
            "resched_per_day": df[f"{m}_nint"].mean(),
            "charges_per_day": df[f"{m}_charges"].mean(),
            "eshort_days_pct": pct(df[f"{m}_eshort"] > 0.05),
            "vkt": df[f"{m}_vkt"].mean(),
            "empty_share_pct": 100.0 * df[f"{m}_empty_vkt"].sum() / max(1e-9, df[f"{m}_vkt"].sum()),
            "cg_onboard_min": df[f"{m}_cg_onboard"].mean(),
            "sec_mean": df[f"{m}_sec"].mean(),
            "sec_p95": df[f"{m}_sec"].quantile(0.95),
        }
        rows.append(row)
    return pd.DataFrame(rows)


def lexcmp(a, b):
    for x, y in zip(a, b):
        if x < y - 1e-9:
            return -1
        if x > y + 1e-9:
            return 1
    return 0


def phi(df, m):
    return list(zip(df[f"{m}_ops"], df[f"{m}_prot"], df[f"{m}_wmiss"], df[f"{m}_nint"], df[f"{m}_eshort"].round(1),
                    df[f"{m}_J"].round(1)))


# ============================================================================ benchmark
def bench(summary):
    df = load("bench")
    if df is None:
        return
    methods = ["exact", "rules", "context", "replay"]
    tab = method_summary(df, methods)
    tab.to_csv(os.path.join(TAB, "bench_summary.csv"), index=False)
    pe = phi(df, "exact")
    dom = {}
    for m in ["rules", "context", "replay"]:
        pm = phi(df, m)
        c = [lexcmp(a, b) for a, b in zip(pe, pm)]
        c3 = [lexcmp(a[:3], b[:3]) for a, b in zip(pe, pm)]
        c5 = [lexcmp(a[:5], b[:5]) for a, b in zip(pe, pm)]
        dom[m] = {"exact_better_pct": 100 * np.mean([x < 0 for x in c]), "tie_pct": 100 * np.mean([x == 0 for x in c]),
                  "exact_worse_pct": 100 * np.mean([x > 0 for x in c]),
                  "exact_better_top3_pct": 100 * np.mean([x < 0 for x in c3]),
                  "exact_better_top5_pct": 100 * np.mean([x < 0 for x in c5])}
    # excess interventions of the deployed rules relative to the optimum (same or better service)
    same = (df.rules_ops == df.exact_ops) & (df.rules_prot == df.exact_prot) & (df.rules_wmiss == df.exact_wmiss)
    excess = df.loc[same, "rules_nint"] - df.loc[same, "exact_nint"]
    feas_e = df.exact_feasible == 1
    summary["bench"] = {
        "n": int(len(df)), "timeouts_pct": pct(df.exact_timeout), "from_seed_pct": pct(df.exact_from_seed),
        "sec_median": float(df.exact_sec.median()), "sec_mean": float(df.exact_sec.mean()),
        "sec_p95": float(df.exact_sec.quantile(0.95)), "sec_max": float(df.exact_sec.max()),
        "dominance": dom, "table": tab.to_dict(orient="records"),
        "rules_excess_resched_when_equal_service_pct": float(100 * np.mean(excess > 0)) if len(excess) else 0.0,
        "rules_fewer_resched_when_equal_service_pct": float(100 * np.mean(excess < 0)) if len(excess) else 0.0,
        "n_equal_service": int(same.sum()),
        "exact_infeasible_pct": float(100 - pct(feas_e)),
        "vkt_reduction_vs_rules_pct_feasible_both": float(100 * (1 - df.loc[(df.exact_feasible == 1) & (df.rules_feasible == 1), "exact_vkt"].sum() /
                                                                  max(1e-9, df.loc[(df.exact_feasible == 1) & (df.rules_feasible == 1), "rules_vkt"].sum()))),
        "mean_acts": float(df.n_acts.mean()), "nd_dist": df.nd.value_counts().sort_index().to_dict(),
        "nc_dist": df.nc.value_counts().sort_index().to_dict(),
        "max_vkt_exact": float(df.exact_vkt.max()),
    }
    # violation-code frequencies
    codes = {}
    for m in methods:
        cnt = {}
        for s in df[f"{m}_codes"].fillna(""):
            for c in s.split("|"):
                if c:
                    cnt[c] = cnt.get(c, 0) + 1
        codes[m] = {k: 100.0 * v / len(df) for k, v in sorted(cnt.items(), key=lambda x: -x[1])}
    summary["bench"]["codes_pct_days"] = codes
    # by number of dependents
    by = []
    for nd, g in df.groupby("nd"):
        for m in methods:
            by.append({"nd": nd, "method": m, "feasible_pct": pct(g[f"{m}_feasible"]), "n": len(g),
                       "prot_service_pct": 100.0 * g[f"{m}_prot_ok"].sum() / max(1, g[f"{m}_prot_total"].sum())})
    by = pd.DataFrame(by)
    by.to_csv(os.path.join(TAB, "bench_by_nd.csv"), index=False)
    summary["bench"]["by_nd"] = by.to_dict(orient="records")

    # ---- Figure: feasibility by number of dependents
    fig, ax = plt.subplots(figsize=(6.6, 2.6))
    nds = sorted(df.nd.unique())
    w = 0.19
    for k, m in enumerate(methods):
        vals = [by[(by.nd == nd) & (by.method == m)].feasible_pct.values[0] for nd in nds]
        xs = np.arange(len(nds)) + (k - 1.5) * (w + 0.012)
        ax.bar(xs, vals, width=w, color=SLOT[k], hatch=HATCH[k], edgecolor="white", linewidth=0.0,
               label=METHOD_LABEL[m])
        for x, v in zip(xs, vals):
            ax.text(x, v + 1.5, f"{v:.0f}", ha="center", va="bottom", fontsize=6.5, color=INK2)
    ns = [int((df.nd == nd).sum()) for nd in nds]
    ax.set_xticks(range(len(nds)), [f"{nd} dependent{'s' if nd != 1 else ''}\n(n={n})" for nd, n in zip(nds, ns)])
    ax.set_ylabel("Feasible days (%)")
    ax.set_ylim(0, 108)
    ax.legend(ncol=2, loc="lower center", bbox_to_anchor=(0.5, 1.0), fontsize=7)
    ax.grid(axis="x", visible=False)
    save(fig, "fig_bench_feasibility")

    # ---- Figure: runtime ECDF
    fig, ax = plt.subplots(figsize=(3.3, 2.4))
    x = np.sort(df.exact_sec.values)
    ax.plot(x, np.arange(1, len(x) + 1) / len(x) * 100, color=SLOT[0])
    ax.set_xscale("log")
    ax.set_xlabel("Exact planner wall time (s, log scale)")
    ax.set_ylabel("Instances solved (%)")
    ax.set_ylim(0, 101)
    save(fig, "fig_runtime")


# ============================================================================ autonomy
def autonomy(summary):
    df = load("autonomy")
    base = load("bench")
    if df is None or base is None:
        return
    seeds = sorted(df.seed.unique())
    av = base[base.seed.isin(seeds)].copy()
    av["variant"] = "AV"
    df = pd.concat([df, av], ignore_index=True)
    rows = []
    for var in ["HV", "AV", "AV_unaccompanied"]:
        g = df[df.variant == var]
        for m in ["replay", "rules", "exact"]:
            rows.append({"autonomy": var, "agency": m, "n": len(g), "feasible_pct": pct(g[f"{m}_feasible"]),
                         "prot_service_pct": 100.0 * g[f"{m}_prot_ok"].sum() / max(1, g[f"{m}_prot_total"].sum()),
                         "wmiss": g[f"{m}_wmiss"].mean(), "resched": g[f"{m}_nint"].mean(),
                         "vkt": g[f"{m}_vkt"].mean(), "empty_vkt": g[f"{m}_empty_vkt"].mean(),
                         "cg_onboard_min": g[f"{m}_cg_onboard"].mean(),
                         "ops_days_pct": pct(g[f"{m}_ops"] > 0)})
    t = pd.DataFrame(rows)
    t.to_csv(os.path.join(TAB, "agency_autonomy.csv"), index=False)
    summary["autonomy"] = t.to_dict(orient="records")
    # figure: 2x3 grid of feasibility
    fig, ax = plt.subplots(figsize=(4.4, 2.5))
    ag = ["replay", "rules", "exact"]
    au = ["HV", "AV"]
    w = 0.34
    for k, a in enumerate(au):
        vals = [t[(t.autonomy == a) & (t.agency == g)].feasible_pct.values[0] for g in ag]
        xs = np.arange(len(ag)) + (k - 0.5) * (w + 0.02)
        ax.bar(xs, vals, width=w, color=SLOT[k], hatch=HATCH[k], edgecolor="white", linewidth=0,
               label={"HV": "Human-driven (driver aboard)", "AV": "Automated (empty repositioning)"}[a])
        for x, v in zip(xs, vals):
            ax.text(x, v + 1.5, f"{v:.0f}", ha="center", va="bottom", fontsize=7, color=INK2)
    ax.set_xticks(range(len(ag)), ["Low agency\n(calendar replay)", "Rule-based agency\n(deployed rules)",
                                   "High agency\n(ISV exact)"])
    ax.set_ylabel("Feasible days (%)")
    ax.set_ylim(0, 108)
    ax.legend(ncol=2, loc="lower center", bbox_to_anchor=(0.5, 1.0), fontsize=7)
    ax.grid(axis="x", visible=False)
    save(fig, "fig_agency_autonomy")


# ============================================================================ errors
def errors(summary):
    df = load("errors")
    base = load("bench")
    if df is None:
        return
    if base is not None:
        orc = base.set_index("seed")[["exact_ops", "exact_prot", "exact_wmiss", "exact_nint"]]
        df = df.join(orc, on="seed")
        df["excess_unsafe"] = ((df.t_ops + df.t_prot) > (df.exact_ops + df.exact_prot)).astype(int)
        df["excess_prot"] = (df.t_prot - df.exact_prot).clip(lower=0)
        df["excess_w"] = (df.t_wmiss - df.exact_wmiss)
    df["violating"] = ((df.t_ops + df.t_prot) > 0).astype(int)
    df["silent"] = ((df.violating == 1) & (df.flagged == 0)).astype(int)
    rows = []
    for (arch, eps), g in df.groupby(["arch", "eps"]):
        r = {"arch": arch, "eps": eps, "n": len(g), "violating_pct": pct(g.violating), "silent_pct": pct(g.silent),
             "flagged_pct": pct(g.flagged), "ops_days_pct": pct(g.t_ops > 0), "prot_days_pct": pct(g.t_prot > 0),
             "wmiss": g.t_wmiss.mean(), "resched": g.t_nint.mean(), "incons": g.t_incons.mean()}
        if "excess_unsafe" in g:
            r.update({"excess_unsafe_pct": pct(g.excess_unsafe), "excess_prot": g.excess_prot.mean(),
                      "excess_w": g.excess_w.mean()})
        rows.append(r)
    t = pd.DataFrame(rows)
    t.to_csv(os.path.join(TAB, "error_containment.csv"), index=False)
    summary["errors"] = t.to_dict(orient="records")
    order = ["llm_only", "tool_agent", "isv_rules", "isv_exact_nofloor", "isv_exact"]
    fig, axs = plt.subplots(1, 2, figsize=(6.8, 2.5))
    for k, arch in enumerate(order):
        g = t[t.arch == arch].sort_values("eps")
        if g.empty:
            continue
        ymet = "excess_unsafe_pct" if "excess_unsafe_pct" in g else "violating_pct"
        axs[0].plot(g.eps * 100, g[ymet], color=SLOT[k], marker="o", ms=4, mec="white", mew=1.0,
                    label=ARCH_LABEL[arch])
        axs[1].plot(g.eps * 100, g.silent_pct, color=SLOT[k], marker="o", ms=4, mec="white", mew=1.0)
    axs[0].set_ylabel("Days with avoidable safety or\nprotected violations (%)")
    axs[1].set_ylabel("Days with an undisclosed\nviolation (silent failure, %)")
    for a in axs:
        a.set_xlabel("Injected interpretation error rate (% of events)")
        a.set_xticks([0, 10, 20, 30])
        a.set_ylim(bottom=0)
    fig.legend(loc="upper center", ncol=3, fontsize=7, bbox_to_anchor=(0.5, 1.13))
    fig.tight_layout()
    save(fig, "fig_error_containment")


# ============================================================================ sensitivity
def sensitivity(summary):
    df = load("sensitivity")
    if df is None:
        return
    out = {}
    rows = []
    for (fac, lvl), g in df.groupby(["factor", "level"]):
        for m in ["exact", "rules", "replay"]:
            rows.append({"factor": fac, "level": lvl, "method": m, "n": len(g), "feasible_pct": pct(g[f"{m}_feasible"]),
                         "eshort_days_pct": pct(g[f"{m}_eshort"] > 0.05), "eshort": g[f"{m}_eshort"].mean(),
                         "charges": g[f"{m}_charges"].mean(), "charge_min": g[f"{m}_charge_min"].mean(),
                         "resched": g[f"{m}_nint"].mean(), "incons": g[f"{m}_incons"].mean(),
                         "energy_days_pct": pct(g[f"{m}_n_energy"] > 0), "vkt": g[f"{m}_vkt"].mean(),
                         "prot_days_pct": pct(g[f"{m}_prot"] > 0)})
    t = pd.DataFrame(rows)
    t.to_csv(os.path.join(TAB, "sensitivity.csv"), index=False)
    summary["sensitivity"] = t.to_dict(orient="records")
    fig, axs = plt.subplots(1, 3, figsize=(7.0, 2.3))
    panels = [("soc0", "eshort_days_pct", "Initial state of charge (%)", "Days ending below\npreferred SoC (%)", 100),
              ("zones", "incons", "Construction zones (count)", "Stops per day off the\ngrounded timetable", 1),
              ("authorised", "feasible_pct", "Share of pickups with a sole\nauthorised caregiver (%)", "Feasible days (%)", 100)]
    for ax, (fac, met, xl, yl, sc) in zip(axs, panels):
        for k, m in enumerate(["exact", "rules", "replay"]):
            g = t[(t.factor == fac) & (t.method == m)].sort_values("level")
            ax.plot(g.level * sc, g[met], color=SLOT[k], marker="o", ms=4, mec="white", mew=1.0,
                    label=METHOD_LABEL[m])
        ax.set_xlabel(xl)
        ax.set_ylabel(yl)
        ax.set_ylim(bottom=0)
    handles, labels = axs[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=3, fontsize=7, bbox_to_anchor=(0.5, 1.08))
    axs[1].set_xticks([0, 2, 4])
    axs[2].set_ylim(0, 100)
    fig.tight_layout()
    save(fig, "fig_sensitivity")


def main():
    summary = {}
    for f in (bench, autonomy, errors, sensitivity):
        try:
            f(summary)
        except Exception as e:  # keep going with partial results
            print(f"[{f.__name__}] skipped: {e!r}")
    case = os.path.join(RAW, "case.json")
    if os.path.exists(case):
        summary["case"] = json.load(open(case))
    with open(os.path.join(ROOT, "results", "summary.json"), "w") as fh:
        json.dump(summary, fh, indent=1, default=float)
    print(json.dumps({k: (v if k != "case" else "...") for k, v in summary.items()}, indent=1, default=float)[:6000])


if __name__ == "__main__":
    main()
