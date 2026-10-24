# Data dictionary

All records are fictional. Events use UTC. IDs remain stable under the seed/config version.

| Table / record | Keys and values | Provenance / coverage |
|---|---|---|
| assets | vehicle_id, crm_asset_id, customer_id, model_id, country, age_years, initial_odometer_km, initial_engine_hours, usage_profile; customer contact at `customer.example` | Mock CRM; 1,000 vehicles |
| id_map | crm_asset_id → vehicle_id / telemetry_asset_id, one-to-one | Canonical mock source mapping |
| daily | vehicle_id + date; operating_hours, distance_km, mean_oil_temperature_c, condition_coverage, odometer_km, lifetime_engine_hours | 365 days × 1,000; 2025 UTC; Q4 detail takes precedence where supplied |
| monthly | vehicle_id + month; summed hours/distance; last counters; mean daily coverage | 12,000 records derived from daily; coverage is daily mean, not sensor-weighted confidence |
| replays | vehicle_id + timestamp; scenario, sensor/context columns below | Nine explicitly curated windows, 43 samples each; 15 Dec 2025; 5-minute cadence |
| full telemetry | same observation schema, partitioned per vehicle | Full generator only, variable operating usage Oct–Dec |
| service_history | service_id, vehicle_id, package_id, completed_at, completed_hours/km | One synthetic inspection per vehicle; counters match the recorded September day; not a scheduled-engine result |
| ERP adapter | sku, erp_part_id, model_id, fault_code, component_type, family, quantity, stock, unit_price_eur, currency, supplier, playbook_version | 16 families × 4 model variants = 64 fictional SKUs |
| Incident | id, vehicle/fault/component, severity/state, onset/last evidence, recurrence, measurements, versions, notification | SQLite; derived only from valid measured evidence |
| WorkOrder / Line | incident key, lifecycle/operational status; candidate, reserved, consumed, returned, unavailable quantities | Mock local service receiver; no purchase order |
| Feedback | idempotency key, role, finding, confirmed cause, action, actual parts/quantities, completion UTC, reported outcome, notes, synthetic effect | Customer report cannot consume parts or complete workshop work |
| Component | stable family instance ID, installed/replaced timestamps | Only replaced family's age resets |
| AuditEvent | monotonic ID, at, kind, entity ID, JSON detail | Source/derived action history |

| Sensor / observed context | Unit / meaning |
|---|---|
| engine_rpm | rpm |
| vehicle_speed_kmh | km/h |
| engine_load_pct | percent |
| coolant_temperature_c / oil_temperature_c / ambient_temperature_c | °C |
| oil_pressure_bar | bar |
| charging_voltage_v | V |
| engine_vibration_rms | fictional relative units, uncalibrated |
| fuel_rate_lph | L/h |
| engine_on | boolean; operating telemetry mostly engine on |
| operating_mode | startup / idle / cruise / high_load / off |
| charging_expected | boolean eligibility |
| warmup | observable elapsed-trip decay proxy, calculated from operating clock |
| model_index | encoded observed model, 0–3 |
| quality_status | valid / missing / sensor_error |
| odometer_km / lifetime_engine_hours | monotonic operating counters including periods with missing sensors |
| source / simulation_version | mock lineage, simulator version |

Hidden capacity losses, injected labels, future failure onset and repair effects are not detector features.
Scenario names label curated replay navigation; detector inference does not consume them. Offline truth is
in `evaluation/truth.json`, predictions in `evaluation/predictions.json`. The app reads only aggregate report.

Future schemas: `config/shared-contracts.json`, generated from validated Pydantic contracts. ServicePlan
must use unique milestone keys, retain late service, model intervals, last counters, overlapping-package
rules and derived next-due values. FleetPulse must keep score, peer percentile and confidence distinct;
leave unsupported scores null. Same-model, weather/context-aware peer cohorts require documented
minimum size/fallbacks and leave-one-out reference contributions. Freeze versioned historical references;
explicitly version revisions. Selected month + prior three chart gaps remain gaps. No scores, peer engine
or scheduler are implemented or fabricated in this project.
