"""Benchmark real language models inside the architecture (run with your own API keys).

Examples
--------
    export OPENAI_API_KEY=...   GEMINI_API_KEY=...   ANTHROPIC_API_KEY=...
    python experiments/run_llm_benchmark.py --models openai:gpt-5.2 gemini:gemini-3.1-pro-preview \
        --n 60 --repeats 3
    python experiments/run_llm_benchmark.py --mock --n 20      # offline dry run

For every instance and model it records:
  * interpretation accuracy of the bounded LLM role (category, protection, priority, reschedulability);
  * the ISV outcome (LLM labels -> floor -> exact solver -> verifier), evaluated against ground truth;
  * an LLM-only planner baseline (the LLM writes the whole mission), verified against ground truth.
Results go to results/raw/llm_benchmark.jsonl; summarise with experiments/make_figures.py --llm.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from hmplan.generator import generate  # noqa: E402
from hmplan.llm.pipeline import isv_pipeline, llm_only_pipeline  # noqa: E402
from hmplan.llm.providers import MockProvider, make_provider  # noqa: E402
from hmplan.runner import report_row, tm_for  # noqa: E402
from hmplan.semantics import POLICY  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="*", default=[])
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--first-seed", type=int, default=5000, help="held-out seeds, disjoint from the main benchmark")
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--temperature", type=float, default=None)
    ap.add_argument("--skip-llm-only", action="store_true")
    ap.add_argument("--mock", action="store_true")
    a = ap.parse_args()
    out_path = os.path.join(ROOT, "results", "raw", "llm_benchmark.jsonl")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    specs = ["mock:mock"] if a.mock else a.models
    if not specs:
        ap.error("give --models or --mock")
    with open(out_path, "a") as out:
        for seed in range(a.first_seed, a.first_seed + a.n):
            inst = generate(seed)
            tm = tm_for(inst)
            for spec in specs:
                for rep in range(a.repeats):
                    if spec.startswith("mock"):
                        truth = {x.id: {"category": x.category, "priority": POLICY[x.category].priority,
                                        "protected": POLICY[x.category].protected,
                                        "reschedulable": POLICY[x.category].reschedulable} for x in inst.activities}
                        prov = MockProvider(truth, eps=0.1, seed=seed * 10 + rep)
                    else:
                        prov = make_provider(spec, a.temperature)
                    row = {"seed": seed, "model": spec, "repeat": rep, "time": time.time()}
                    try:
                        r = isv_pipeline(inst, prov, tm)
                        row.update({k: r[k] for k in ("acc_category", "acc_protected", "acc_priority",
                                                      "acc_resched", "false_unprotect", "flagged",
                                                      "llm_latency_s", "solver_s")})
                        row.update(report_row(r["true_report"], "isv"))
                        row["isv_usage"] = r["meta"].get("usage")
                        row["isv_invalid"] = len(r["meta"].get("invalid_entries", []))
                    except Exception as e:
                        row["isv_error"] = repr(e)
                    if not a.skip_llm_only and not spec.startswith("mock"):
                        try:
                            r2 = llm_only_pipeline(inst, prov, tm)
                            row.update(report_row(r2["true_report"], "llmonly"))
                            row["llmonly_latency_s"] = r2["llm_latency_s"]
                            row["llmonly_usage"] = r2["meta"].get("usage")
                        except Exception as e:
                            row["llmonly_error"] = repr(e)
                    out.write(json.dumps(row, default=str) + "\n")
                    out.flush()
                    print(seed, spec, rep, {k: row.get(k) for k in ("acc_category", "isv_feasible", "llmonly_feasible")},
                          flush=True)


if __name__ == "__main__":
    main()
