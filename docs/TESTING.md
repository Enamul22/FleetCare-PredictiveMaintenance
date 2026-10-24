# Evaluation and verification report

Frozen synthetic holdout: 160 vehicles, 50 injected events, 653.333 operating hours.

| Method | Events recalled | False incidents / 100 h | Median delay (min) |
|---|---:|---:|---:|
| rules | 41/50 (82.0%) | 0/653.333 h = 0.00 | 10.0 |
| isolation_forest | 28/50 (56.0%) | 8/653.333 h = 1.22 | 62.5 |
| raw_limits | 39/50 (78.0%) | 9/653.333 h = 1.38 | 10.0 |

| Fault | Detected / events | Recall 95% Wilson interval |
|---|---:|---|
| FC-01 | 9/11 | [0.523, 0.949] |
| FC-02 | 9/11 | [0.523, 0.949] |
| FC-03 | 8/11 | [0.434, 0.903] |
| FC-04 | 4/5 | [0.376, 0.964] |
| FC-05 | 11/12 | [0.646, 0.985] |

Rules recall 95% Wilson interval: [0.692, 0.902]. Zero false incidents in this small exposure does not establish a zero population rate; a one-sided Poisson 95% upper bound is approximately 0.46 per 100 hours.

Pre-failure results: 0/4 eligible later failure events warned before failure. No positive lead-time claim. Most events have no separately defined later failure onset and are excluded from lead-time analysis.

First qualifying alert at/after injected onset within episode; exact family for rules/raw; any family for generic IF. Other alerts are false incidents. No point adjustment.

Uncertainty treats events as independent for Wilson intervals; multi-fault clustering can reduce effective support. IF generic alerts may match multiple simultaneous events, so its family recall does not measure diagnosis. Mild loss is intentionally missed by some policies. No thresholds or preprocessing are tuned on this report. Challenger stays offline.

## Executed checks

The final local/remote check counts and UI evidence are recorded in PROGRESS.md and evidence/. Tests exercise all five fault completions, missing/quality data, time-window equality, past-only features, source joins and checksums, monthly sums and counters, incompatibility/stockout, recurrence, escalation, outbox restart/retry, consumption idempotency, failed/successful repair branches, session isolation, immutable evaluation and Streamlit interactions.

Reproduce: `pytest -q`; `ruff check .`; `ruff format --check .`; `PYTHONPATH=src python -m fleetcare.evaluation`. Generation/evaluation run offline; bounded CI uses prepared data and does not retrain. Test output and screenshots are review evidence, not production certification.

Operational acceptance evidence: `evaluation/operational.json` records 5 verified fault cycles,
5 exported work orders, 0 duplicate orders (0/5), 5 consumed units despite repeated feedback calls,
and 10 transport attempts (failure + retry per order). Reproduce with
`PYTHONPATH=src python -m fleetcare.verify`. This is separate from detection-cohort evaluation.
