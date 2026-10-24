# Simulator / dataset card

Owner: Enamul Haque. Independent synthetic portfolio demonstration; no employer, OEM or customer source.
Four fictional models (Alder Compact, Birch Sedan, Cedar SUV, Elm Van), four countries, 200 named fictional
customers and consistent cities. Countries/weather are scenario context, not national statistics.

Simulator sim-1.0, seed 20251024; interval-support-r2 corrects counter support without changing public
app version 1.0.0. The manifest records prepared table counts and SHA-256 hashes. Complete 2025 daily
history (365,000 rows), twelve monthly summaries per vehicle, source ID mappings, inspections and parts
are bundled. All 1,000 detailed Oct–Dec partitions were generated and processed offline: 1,931,280
observations and 153,450.166667 supported operating hours. The complete detector result is 70 episodes.
This is the measured output, with no requested prevalence, sampling or row cap. Every fault has retrievable
actual supporting observations. Startup reads prepared data; it does not generate/train/detect the full fleet.

Raw full telemetry is partitioned per vehicle under ignored data/full. The offline pipeline processes
partitions with bounded windows and retains all Q4 support for vehicles with faults. Prepared data is
about 37 MB. Historical nine curated replays are archived under evaluation/historical; they are not the
operational queue or a prevalence estimate. Reproduction commands are in README.md.

Daily usage varies with zero-use days. Correlated heat/flow/electrical/vibration equations use load, RPM,
warm-up, ambient context, model effects, per-vehicle bias and noise. Hidden continuous capacity losses
change observations, not directly detector outputs. Detailed counters are rebased to daily usage and Q4
hours/distance are derived from consecutive supported intervals. Jan–Sep daily condition/usage summaries
remain independent approximations, not reconstructed five-minute data. Condition summaries must not be
used as equivalent diagnostic evidence. Weather uses the same seasonal formula across countries and is
not location-calibrated. Operational monotonic degradation produces Active/Unknown episodes in this run;
separate fixtures test actual recovery/end and recurrence. No ended rows are fabricated for variety.

Evaluation is distinct from this operational run: healthy development assets 1–80 and frozen baseline,
new reserved VEH-0401..0560 with seed 20261024, 61 explicitly bounded events including recurrence and
633.333333 supported operating hours. Co-fault iteration is sorted before random draws; different process
hash seeds reproduce the cohort. Historical evaluation evidence from bbcab56 is archived unchanged and
is not directly comparable after support/matching/cohort corrections. See MODEL_CARD and TESTING.

Customer free text never changes telemetry or repair efficacy. There is no claimed physical repair model
or calibrated repair probability. Conditional parts are not diagnoses. Intended use is software workflow,
evidence and integrity review, not actual workshop advice, risk scoring or production operations. Simple
physics, synthetic prevalence, short observation windows and small event counts limit generalization.
No open-source licence has been selected; publication alone is not a licence grant.
