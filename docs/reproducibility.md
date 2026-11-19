# Reproducing the paper

All computational results are produced by the scripts below from integer seeds. Wall times are
for a 2-core virtual machine.

```bash
pip install -r requirements.txt
python -m pytest -q tests                                       # ~2 min
python experiments/run_experiments.py case                      # E1, <1 min
python experiments/run_experiments.py bench --n 1000            # E2, ~25 min
python experiments/run_experiments.py errors --n 150            # E4, ~35 min
python experiments/run_experiments.py autonomy --n 300          # E3, ~15 min
python experiments/run_experiments.py sensitivity --n 100       # E5, ~25 min
python experiments/plot_case.py                                 # Fig. case timeline
python experiments/make_figures.py                              # tables, figures, summary.json
python experiments/export_latex.py --out paper/                 # macros + tables for the manuscript
```

Raw results are written to `results/raw/*.jsonl` (one line per instance or run); runs resume
where they stopped. `--procs` sets the number of worker processes; `--fresh` restarts.

The exact planner has a 20 s limit per instance (`TIME_LIMIT` in `run_experiments.py`). Results
on instances that hit the limit are the best missions found and are reported as such.
