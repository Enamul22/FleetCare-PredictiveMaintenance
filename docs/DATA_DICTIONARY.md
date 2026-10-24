# Data dictionary

All vehicles, customers, measurements, procedures and parts are fictional. Timestamps are UTC.
Public application version remains 1.0.0; internal detection revision is independent.

| Record | Keys and contents | Coverage / authority |
|---|---|---|
| assets | vehicle_id, crm_asset_id, customer_id/name, model_id, country, city, initial counters, usage profile | 1,000 vehicles; 200 fictional customers |
| id_map | CRM, canonical vehicle and telemetry IDs | One-to-one source mapping |
| daily | vehicle_id/date, hours, distance, end counters, approximate condition summaries | 365,000 rows; Q4 hours/distance derived from detailed intervals |
| monthly | vehicle_id/month, summed usage, end counters, average daily coverage | 12,000 rows; condition coverage is not diagnostic confidence |
| service_history | service_id, vehicle_id, package, completion time/counters | 1,000 synthetic inspections; no scheduling engine |
| raw telemetry | vehicle/timestamp, observed sensor/context columns | All 1,000 Q4 partitions in offline full generation; not committed |
| faults.parquet | stable episode ID, vehicle/code, severity, supporting start, confirmation, observed end, recovery confirmation, last detection/observation, status, versions, evidence, support file | Complete materialized output: 70 episodes, all five families; no cap |
| support/*.parquet | actual Q4 observed rows for every vehicle with a detected fault | Complete chart support; never generic scenario substitutions |
| parts | SKU, ERP ID, model, fault, family, proposed quantity, fictional price/stock | 64 model-compatible fictional SKUs; customer reports do not change stock |
| customers / vehicles | stable customer ownership and location | Shared SQLite reference tables |
| users / sessions | mapped role/customer, salted password hash, enabled flag; hashed opaque token and expiry | Server-side sign-in; role is not an editable reporting field |
| faults | imported episode evidence and optional legacy_state | Sensor-derived authority; response never establishes recovery |
| export_requests | unique fault ID, state, attempts, error, immutable requested snapshot, actor/time | Explicit admin Create only; failed attempt remains retryable |
| work_orders | unique order ID and fault ID, assigned customer, Open/Completed/Rejected, saved snapshot, actor/time, legacy_state | At most one order per episode; no silent reissue after rejection |
| work_order_responses | unique order, decision, finding/cause/action, actual parts/quantities, reported resolution, nullable rating, notes/reason, response/submission timestamps, normalized payload | One atomic final customer response; identical retry is idempotent; conflicting retry rejected |
| fault_reporting | faults LEFT JOIN vehicles/customers/export/work_orders/responses | Exactly one row per fault, including uncreated faults; filtered download includes joined response fields |
| audit | monotonic ID, UTC, kind, entity, detail, actor | Append action evidence; old audit rows retained |
| legacy tables | original incidents, orders, feedback, observations and related tables where present | Additive migration retains originals; old feedback remains separate, never invented as a new final response |

Creation status is Not created / Pending / Created / Failed; order status is null before creation.
Feedback/rating is null until submitted. Rejected responses have no invented performed work. Fault status
is Active / Ended / Unknown. Sensor verification is independent of Completed/Rejected and of reported
Resolved / Not resolved / Not sure. Missing future readings do not establish an end.

| Observation | Unit / meaning |
|---|---|
| oil_temperature_c, coolant_temperature_c, ambient_temperature_c | °C |
| oil_pressure_bar | bar |
| charging_voltage_v | V |
| engine_vibration_rms | Uncalibrated fictional relative units |
| engine_rpm, vehicle_speed_kmh, engine_load_pct, fuel_rate_lph | rpm, km/h, %, L/h |
| engine_on, operating_mode, charging_expected, warmup | Observed eligibility/context, elapsed-trip warm-up proxy |
| quality_status | valid / missing / sensor_error |
| odometer_km, lifetime_engine_hours | Monotonic supported usage counters |

A supported operating interval requires consecutive engine-on endpoints, positive separation ≤10 minutes.
There is no extra final-sample slot: 49 five-minute samples span 48 intervals. Sensor missingness retains
known engine context; overnight gaps and engine-off periods do not add supported exposure. Hidden losses,
labels, future failure times and hypothetical repair effects are never inference features.

`config/shared-contracts.json` retains future ServicePlan/FleetPulse interfaces only. No service scheduler,
monthly peer reference, health score or portfolio site is implemented here.
