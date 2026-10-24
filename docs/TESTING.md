# Evaluation and verification report

Evaluation-r2: new reserved synthetic holdout VEH-0401..0560, seed 20261024; 160 vehicles,
61 bounded injected events, 633.333333 supported operating hours. Healthy baseline/policies remain frozen.

| Method | Recalled events | False incidents / 100 h | Duplicates | Median delay |
|---|---:|---:|---:|---:|
| Rules | 53/61 (86.9%) | 0 / 633.333333 h = 0.00 | 0 | 45 min |
| Isolation Forest | 27/61 (44.3%) | 6 / 633.333333 h = 0.95 | 3 | 45 min |
| Raw limits | 51/61 (83.6%) | 7 / 633.333333 h = 1.11 | 17 | 35 min |

| Rules fault | Recalled / events | Recall 95% Wilson interval |
|---|---:|---|
| FC-01 | 13/15 | [0.621, 0.963] |
| FC-02 | 6/8 | [0.409, 0.929] |
| FC-03 | 12/14 | [0.601, 0.960] |
| FC-04 | 12/13 | [0.667, 0.986] |
| FC-05 | 10/11 | [0.623, 0.984] |

Rules overall Wilson interval [0.762, 0.932]. Zero observed false incidents is not a zero population
rate: the approximate one-sided 95% Poisson upper bound is 0.47 per 100 hours. Events share vehicles;
independence-based intervals understate some clustering uncertainty. IF family attribution does not
measure diagnosis. No point adjustment or test-driven threshold tuning. IF stays an offline challenger.

Rules warned before separately labelled later failure in 3/3 eligible cases (median 45 min lead);
raw limits 3/3 (40 min), IF 0/3. Most events lack a distinct later failure label and are excluded.
Three synthetic cases do not establish real failure forecasting or useful repair effectiveness.

Matching requires inclusive onset ≤ alert ≤ event end in the same case/family (generic IF at most one
event per alert). Recurrence IDs are distinct. Further matching alerts are duplicates; early/late/no-event
alerts are false. Exposure sums consecutive engine-on intervals ≤10 minutes, without a final extrapolated
sample slot. The former 41/50 rules result is preserved in evaluation/historical, with its original
methodology; corrected support, matching and new cohort make direct numerical comparison inappropriate.

## Executed verification

36 meaningful tests cover prepared full-fleet hashes/counters/support, all five fault families, healthy
transients, missing/bad data, exact temporal windows, prefix/batch parity, actual recovery/recurrence,
past-only features, bounded event matching and separate-process hash-seed reproducibility. Small complete
generation/materialization runs reproduce identical output. Service tests cover additive legacy migration,
shared-store restart, authorization including direct foreign detail/evidence/submission attempts, explicit
single-order creation, recoverable export failure, stable snapshots, null feedback, transaction rollback,
concurrency, identical/conflicting retries, expiry/logout, rejection and completed-but-not-resolved.

Streamlit AppTest exercises admin creation and separate customer submission/writeback. Chrome review checks
native table selection, all nested tabs, separate signed-in sessions and refreshed saved responses; screenshot
details are in evidence/README.md. Operational verification uses an isolated store and records five explicit
orders/responses, zero duplicates and exactly 70 joined fault rows in evaluation/operational.json. Notes have
no simulation side effects. No test reports physical repair success.

Reproduce from repository root after locked install:

```bash
.venv/bin/python -m pytest -q --junitxml=docs/evidence/local-tests.xml
.venv/bin/ruff check .
.venv/bin/ruff format --check .
PYTHONPATH=src .venv/bin/python -m fleetcare.evaluation
PYTHONPATH=src .venv/bin/python -m fleetcare.verify
```

Full generation/detection is offline; bounded CI uses prepared data without full training/generation.
Clean environment and exact remote Actions result are recorded in PROGRESS.md. Review evidence is not
production certification. Hosted local SQLite durability and production identity management remain limitations.
