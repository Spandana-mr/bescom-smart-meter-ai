# BESCOM Smart Meter — Synthetic Dataset
> 1,31,340 rows across 7 CSV files  
> Date range: 2023-01-01 to 2024-12-31  
> Geography: 10 Bangalore zones (Whitefield, Koramangala, Jayanagar, Rajajinagar, Hebbal, Electronic City, Marathahalli, Indiranagar, Yelahanka, BTM Layout)

---

## File Summary

| File | Rows | Grain |
|------|-----:|-------|
| `meters.csv` | 500 | One row per meter (master) |
| `meter_readings.csv` | 1,00,000 | Hourly reading per meter |
| `demand_forecasts.csv` | 7,310 | Daily zone-level forecast |
| `anomaly_alerts.csv` | 3,500 | Per-alert event |
| `grid_topology.csv` | 30 | Substation → Feeder |
| `audit_events.csv` | 5,000 | Inspector workflow event |
| `data_quality.csv` | 15,000 | Daily per-meter DQ metric |

---

## Column Descriptions

### meters.csv
| Column | Type | Description |
|--------|------|-------------|
| meter_id | string | Primary key `BSCM-XXXXXX` |
| consumer_type | string | Residential / Commercial / Industrial / Agricultural |
| zone | string | Bangalore supply zone |
| substation_id | string | Parent substation |
| feeder_id | string | Parent feeder |
| tariff_code | string | BESCOM tariff slab (LT-1, LT-2, HT-1 …) |
| phase | string | 1-Phase / 3-Phase |
| contracted_kw | float | Sanctioned load in kW |
| install_date | date | Meter installation date |
| latitude / longitude | float | GPS coordinates |
| communication_protocol | string | RF Mesh / GPRS / PLC / NB-IoT |
| firmware_version | string | Current firmware |
| meter_make | string | Manufacturer |
| active | bool | Whether meter is currently active |

### meter_readings.csv
| Column | Type | Description |
|--------|------|-------------|
| reading_id | string | PK `RDG-XXXXXXXX` |
| meter_id | string | FK → meters |
| zone | string | Denormalized zone |
| timestamp | datetime | Hourly reading timestamp |
| kwh | float | Active energy (kWh) |
| kvarh | float | Reactive energy (kVArh) |
| voltage_v | float | Measured voltage (V) |
| current_a | float | Measured current (A) |
| power_factor | float | Power factor 0–1 |
| demand_kw | float | Instantaneous demand (kW) |
| is_theft_flag | bool | ML-flagged theft indicator |
| tamper_detected | bool | Physical tamper flag |
| anomaly_type | string | bypass / meter_tamper / phase_cut / abnormal_low / abnormal_high |
| anomaly_score | float | Model confidence 0–1 |
| signal_rssi_dbm | int | Communication signal strength |
| communication_ok | bool | Whether packet was received cleanly |

> **Theft injection rate:** ~1.5% of rows carry a synthetic anomaly with depressed kWh or tamper flag.

### demand_forecasts.csv
| Column | Type | Description |
|--------|------|-------------|
| forecast_id | string | PK |
| zone | string | Zone name |
| forecast_date | date | Date of forecast horizon |
| model_name | string | LSTM-v2 / XGBoost-v3 / Prophet-v1 / Ensemble-v4 |
| forecast_mw | float | Predicted zone demand (MW) |
| actual_mw | float | Realised demand (MW) |
| p10_mw / p90_mw | float | 10th / 90th percentile bounds |
| mape_pct | float | Mean Absolute Percentage Error |
| peak_hour | int | Hour of projected peak (0–23) |
| peak_forecast_mw | float | Peak demand estimate |
| horizon_hours | int | Forecast horizon (24) |
| run_timestamp | datetime | When forecast was generated |

### anomaly_alerts.csv
| Column | Type | Description |
|--------|------|-------------|
| alert_id | string | PK `ALT-XXXXXX` |
| meter_id | string | FK → meters |
| zone | string | Zone |
| alert_timestamp | datetime | When alert was raised |
| anomaly_type | string | Energy Theft / Meter Tamper / Phase Imbalance / … |
| severity | string | Low / Medium / High / Critical |
| anomaly_score | float | Detector confidence |
| status | string | Open / Investigating / Resolved / False Positive |
| estimated_loss_units | float | kWh loss estimate (theft cases) |
| assigned_inspector | string | Inspector ID (if assigned) |
| resolution_timestamp | datetime | When resolved (nullable) |
| root_cause | string | Confirmed root cause (nullable) |
| model_version | string | Detector model version |

### grid_topology.csv
| Column | Type | Description |
|--------|------|-------------|
| zone | string | Zone name |
| substation_id | string | Substation identifier |
| substation_voltage_kv | int | Operating voltage kV |
| feeder_id | string | Feeder identifier |
| feeder_length_km | float | Feeder length |
| capacity_mva | float | Rated capacity |
| current_load_mva | float | Current loading |
| load_pct | float | Loading percentage |
| meter_count | int | Meters on feeder |
| outage_count_ytd | int | Outages year-to-date |
| last_maintenance | date | Last maintenance date |
| status | string | Normal / Alert / Critical |

### audit_events.csv
| Column | Type | Description |
|--------|------|-------------|
| audit_id | string | PK `AUD-XXXXXXX` |
| meter_id | string | FK → meters |
| zone | string | Zone |
| action_timestamp | datetime | When action was taken |
| action_type | string | Field Inspection / Meter Replacement / FIR Filed / … |
| inspector_id | string | Inspector performing the action |
| outcome | string | Pass / Fail / Pending / Escalated |
| remarks | string | Free-text notes |
| fine_inr | float | Penalty levied (₹) |
| follow_up_date | date | Next follow-up date (nullable) |
| related_alert_id | string | Linked anomaly alert (nullable) |

### data_quality.csv
| Column | Type | Description |
|--------|------|-------------|
| dq_id | string | PK |
| meter_id | string | FK → meters |
| zone | string | Zone |
| date | date | Reporting date |
| expected_readings | int | Expected hourly packets (24) |
| received_readings | int | Actually received |
| missing_readings | int | Gap count |
| completeness_pct | float | % completeness |
| null_values | int | Null/invalid field count |
| out_of_range_values | int | Values outside physical bounds |
| duplicate_readings | int | Duplicate packet count |
| avg_latency_ms | float | Average ingestion latency |
| comms_failures | int | Communication failure count |
| quality_score | float | Composite DQ score 0–1 |

---

## Relationships

```
meters (meter_id)
  ├── meter_readings (meter_id)
  ├── anomaly_alerts (meter_id)
  ├── audit_events   (meter_id)
  └── data_quality   (meter_id)

grid_topology (feeder_id) ← meters (feeder_id)

anomaly_alerts (alert_id) ← audit_events (related_alert_id)

demand_forecasts (zone) ← meters / readings (zone)  [aggregate level]
```

---

## Realistic Patterns Built In

- **Seasonal load variation** — 25% higher demand in Mar–Jun (Bangalore summer), lower in Oct–Feb
- **Hourly load profiles** — consumer-type-specific (residential evening peak, commercial business-hours, industrial flat, agricultural off-peak irrigation)
- **Theft signatures** — 1.5% injection rate with reduced kWh (bypass/phase-cut) or tamper flags
- **Forecast error** — MAPE typically 3–7%, stored for model evaluation
- **Data quality gaps** — 70% of days have complete 24/24 packets; ~5% have >4 missing readings
- **Multi-model forecasting** — 4 named models with independent error profiles
