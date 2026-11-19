# Field evaluation logs (deployed n8n prototype)

This folder holds the logs of the field evaluation reported in Section 6.1 of the paper
(Montreal Run 2; three runs per condition; GPT-5.2 for the architecture ablation; eight
GPT/Gemini models inside the prototype).

**To be added by the authors before publication**

- `ablation_scores.csv` – one row per run x condition x rubric criterion (IR-01..IR-06, 0-2)
- `model_comparison.csv` – one row per model x run: rubric scores, wall time (s), tokens
- `followup_scores.csv` – route-memory follow-up questions: factual and memory accuracy per model
- `rubric.md` – the scoring guide used by the evaluators
- raw n8n execution exports (JSON) with credentials and personal data removed

Summary values already reported in the paper (criterion means over three runs):

| Criterion | Proposed | LLM-only | Calendar-tool agent |
|---|---|---|---|
| IR-01 Event coverage | 2.00 | 2.00 | 2.00 |
| IR-02 Conflict detection | 2.00 | 2.00 | 2.00 |
| IR-03 Priority reasoning | 2.00 | 2.00 | 2.00 |
| IR-04 Alternative recommendation | 1.33 | 1.00 | 1.00 |
| IR-05 Active-user filtering | 2.00 | 1.00 | 1.00 |
| IR-06 Schedule feasibility | 2.00 | 1.00 | 0.67 |
| Mean route accuracy | 94.44% | 75.00% | 72.22% |
