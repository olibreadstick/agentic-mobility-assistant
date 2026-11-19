"""Timeline figure for the Montreal field case (Run 2): deployed rules vs ISV exact planner."""
from __future__ import annotations

import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from hmplan.casestudy import calibrated_params, run2  # noqa: E402
from hmplan.heuristics import plan  # noqa: E402
from hmplan.solver import solve  # noqa: E402
from hmplan.travel import TravelModel  # noqa: E402
from hmplan.verify import effective_activities, verify  # noqa: E402

SLOT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]
INK2, GRID = "#52514e", "#e4e3df"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 8, "axes.spines.top": False,
                     "axes.spines.right": False, "savefig.bbox": "tight"})


def draw(ax, inst, mission, rep, title):
    rows = ["Parent1", "Parent2", "Child1", "Child2", "Vehicle"]
    y = {r: len(rows) - 1 - k for k, r in enumerate(rows)}
    acts = effective_activities(inst, mission.starts)
    for a in acts.values():
        lo = max(a.start, inst.day_start - 60)
        moved = a.id in mission.starts
        ax.barh(y[a.person], a.end - lo, left=lo, height=0.42, color="#d9d8d3" if not a.sem.protected else "#bcd5f5",
                edgecolor=SLOT[1] if moved else "none", linewidth=1.4 if moved else 0, hatch="//" if moved else "")
        if moved:
            orig = inst.activity(a.id)
            ax.barh(y[a.person], orig.end - orig.start, left=orig.start, height=0.42, color="none",
                    edgecolor=INK2, linestyle=(0, (2, 2)), linewidth=0.8)
    # vehicle segments from the verified timeline
    act = rep.actual
    for k in range(len(mission.stops) - 1):
        s, nx = mission.stops[k], mission.stops[k + 1]
        dep, arr = act[k][1], act[k + 1][0]
        if nx.loc != s.loc and arr > dep:
            aboard = set()
            for j in range(k + 1):
                aboard -= set(mission.stops[j].alight)
                aboard |= set(mission.stops[j].board)
            col = SLOT[0] if aboard else SLOT[3]
            ax.barh(y["Vehicle"], arr - dep, left=dep, height=0.42, color=col)
        if nx.charge_min > 0:
            a0 = act[k + 1][0]
            ax.barh(y["Vehicle"], nx.charge_min, left=a0, height=0.42, color=SLOT[2], hatch="..")
    ax.set_yticks([y[r] for r in rows], rows)
    ticks = list(range(10 * 60 + 30, 19 * 60 + 31, 60))
    ax.set_xticks(ticks, [f"{t // 60}:{t % 60:02d}" for t in ticks])
    ax.set_xlim(10 * 60 + 15, 19 * 60 + 15)
    ax.grid(axis="x", color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    ax.set_title(title, loc="left", fontsize=8.5, color="#0b0b0b")


def main():
    prm, _ = calibrated_params()
    inst = run2()
    tm = TravelModel(inst, prm)
    m_rules = plan(inst, tm, "rules")
    r_rules = verify(inst, m_rules, tm)
    res = solve(inst, tm, time_limit=60)
    fig, axs = plt.subplots(2, 1, figsize=(7.0, 3.9), sharex=True)
    draw(axs[0], inst, m_rules, r_rules,
         f"(a) Deployed rules: {r_rules.vkt:.1f} km, SoC at end {100 * r_rules.soc_end:.0f}% (preferred 65%)")
    draw(axs[1], inst, res.mission, res.report,
         f"(b) ISV exact planner: {res.report.vkt:.1f} km, SoC at end {100 * res.report.soc_end:.0f}%")
    handles = [Patch(color="#bcd5f5", label="Protected commitment"), Patch(color="#d9d8d3", label="Other commitment"),
               Patch(facecolor="white", edgecolor=SLOT[1], hatch="//", label="Proposed new time (original dashed)"),
               Patch(color=SLOT[0], label="Driving with passengers"), Patch(color=SLOT[3], label="Driving empty"),
               Patch(facecolor=SLOT[2], hatch="..", label="Charging")]
    fig.legend(handles=handles, loc="upper center", ncol=3, fontsize=7, frameon=False, bbox_to_anchor=(0.5, 1.07))
    fig.tight_layout()
    out = os.path.join(ROOT, "results", "figures")
    os.makedirs(out, exist_ok=True)
    fig.savefig(os.path.join(out, "fig_case_timeline.pdf"))
    fig.savefig(os.path.join(out, "fig_case_timeline.png"), dpi=300)
    print("saved", r_rules.phi, res.phi)


if __name__ == "__main__":
    main()
