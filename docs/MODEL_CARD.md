# Detector / model card

**Versions:** healthy-linear-1.0, policy-1.0, PB-1.0. All numerical boundaries are fictional.
Persisted coefficients in `data/demo/baseline.json` are fitted only on healthy development records.
Features: observed load, ambient temperature, RPM, speed, elapsed-trip warmup proxy and observed model.
LinearRegression predicts five sensor baselines. Positive floors protect ratio denominators.
No hidden expected-value simulator function is called during inference. Country is not a fault proxy.

| Code | Evidence | Warning | Critical | Recovery |
|---|---|---|---|---|
| FC-01 | observed − expected oil °C | ≥15 for 10 min | ≥25 for 5 min | <8 for 15 min |
| FC-02 | observed − expected coolant °C | ≥12 for 10 min | ≥20 for 5 min | <6 for 15 min |
| FC-03 | observed / expected oil pressure | ≤0.70 for 10 min | ≤0.50 for 5 min | >0.85 for 15 min |
| FC-04 | expected − observed voltage | ≥1.0 for 10 min | ≥2.0 for 5 min | <0.5 for 15 min |
| FC-05 | observed / expected vibration | ≥1.8 for 15 min | ≥2.5 for 5 min | <1.3 for 15 min |

Windows include both endpoints: two distinct samples spanning five minutes minimum. Required valid
coverage ≥80% of expected cadence slots; no observation/valid-data gap >10 minutes. Valid samples may
not contradict the comparison. Startup/off samples do not count. Charging also requires charging_expected;
vibration requires stable operating mode. At this cadence/these short windows, one missing reading often
prevents persistence entirely. Insufficient or invalid evidence is unknown, not healthy. Sampling cannot
localize onset more precisely than five minutes; no interpolation invents continuous evidence.

Warning/critical equality is inclusive; recovery equality does not qualify. Severity remains critical
once escalated until recovery. Recovery resolution is separate from technician-reported outcome.
Rule outputs identify suspected conditions and evidence, not unique mechanical causes.

Isolation Forest comparison uses only past/current rolling 4-sample median residual/ratio features,
100 trees, contamination .015, random state 431; healthy development training only. No future fill,
centred rolling windows, test preprocessing fit or test-driven policy adjustment. Consecutive anomaly
evidence must persist ten minutes under the same coverage rule. IF labels remain `unexplained`; no arbitrary
fault names are assigned. It is not promoted; the app runs rules. Raw fixed single-sample limits provide
a deliberately simple comparison baseline. It is not used operationally.

See `evaluation/report.json` and TESTING.md for measured numerators/denominators, confidence intervals,
false-alert exposure, misses and delay. No point-adjusted accuracy is reported. Only separately labelled
later capacity-failure onsets qualify for pre-failure lead time; alerts at/after that onset do not count.
Synthetic observations cannot validate a real vehicle detector or establish real maintenance effectiveness.
