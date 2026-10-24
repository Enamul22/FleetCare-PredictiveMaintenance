# Simulator / dataset card

**Owner:** Enamul Haque. Independent synthetic portfolio data; no employer, OEM, customer, MetroPT or
proprietary source. Countries and weather are fictional scenario contexts, not national statistics.
Four models (Alder Compact, Birch Sedan, Cedar SUV, Elm Van), four countries and overlapping usage profiles.

**Version/seed:** sim-1.0 / 20251024. Compact manifest contains per-table counts and SHA-256 hashes.
The complete 2025 daily history and derived twelve-month usage records are bundled (~15 MB total).
Only nine detailed operating replays are bundled; they are curated and cannot represent fleet prevalence.
The full generator emits Oct–Dec detail in per-vehicle Parquet partitions, then derives overlapping daily
statistics and rebases detailed counters onto the daily operating clock. Each vehicle's detail is processed
separately; no entire detailed fleet is retained in memory. A 1,000-vehicle daily result is small enough to
concatenate in memory. Stop generation without modifying committed demo assets by using `--output data/full`.

Daily usage comes first (variable operating hours, zero-use days, distance). Sensor observations use
correlated heat/flow/electrical/vibration equations with load, RPM, warm-up, ambient context, model effects,
per-vehicle bias and measurement noise. Hidden continuous component capacity losses change observations;
labels are injected onset/capacity events, not detector threshold crossings. Detailed missingness preserves
usage counters. Where detail is absent, daily condition values are summary-level synthetic approximations;
these are not reconstructed five-minute telemetry and are never passed to the detector.

The full generator includes calendar degradation in five independently overlapping families; detailed
representative evaluation separately includes abrupt, gradual, mild, severe and simultaneous losses,
healthy high load, isolated sensor spikes, flagged measurement errors and missingness. Repair replay
branches are interactive; no repair physics claims or empirically calibrated success probabilities.
Correct staged-family action produces full effect; a `partial` note selects 45% effect; unsupported actions
produce zero effect. This recorded setting is explicit and repeatable, not learned repair efficacy.

**Partitions:** development assets 1–80, development healthy observation seeds 100–179, fleet seed 321;
held-out assets 201–360 from independent seed 784, telemetry seeds 6000–6159; scenario seed 77881.
Curated scenarios use seed 44 and different event configurations. Split before feature construction.
Raw held-out frames are reproducible via `cohort()` and not bundled as operational features.

**Intended use:** demonstration of operational integration, evidence, state integrity, testing and
failure analysis. Not vehicle diagnosis, workshop advice, real risk scoring or production operations.
Synthetic prevalence is the Bernoulli scenario process (0.36 episode event probability, 0.18 optional
co-fault draw), chosen before evaluation, without target recall. Small denominators and simple physics
limit transfer. No licensing grant has been selected; repository publication is not an open-source licence.
