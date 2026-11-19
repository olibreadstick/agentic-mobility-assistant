# Running real language models inside the architecture

The computational study in the paper injects interpretation errors at controlled rates. To measure
what specific LLMs actually do, run the harness with your own API keys:

```bash
export OPENAI_API_KEY=...      # and/or GEMINI_API_KEY, ANTHROPIC_API_KEY
python experiments/run_llm_benchmark.py \
    --models openai:gpt-5.2 openai:gpt-5-mini gemini:gemini-3.1-pro-preview \
    --n 60 --repeats 3
```

For each held-out benchmark day (seeds 5000+) and model it records

* interpretation accuracy of the bounded role (category, protection, priority, reschedulability);
* the ISV outcome (LLM labels -> semantic floor -> exact planner -> verifier) against ground truth;
* an LLM-only planner baseline in which the model writes the whole mission (JSON), verified
  against ground truth, including invented locations and inconsistent times;
* latency and token usage as reported by the provider.

Use `--mock` for an offline dry run. Results are appended to `results/raw/llm_benchmark.jsonl`.
Suggested reporting: mean +/- s.d. over repeats, per model, for label accuracy, feasible-day rate
of ISV vs LLM-only, silent-failure rate of LLM-only (ISV discloses by construction), latency.
