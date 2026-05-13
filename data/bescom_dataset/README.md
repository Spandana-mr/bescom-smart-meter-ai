# BESCOM Full Dashboard Dataset

Synthetic/enhanced CSV dataset generated from the existing BESCOM smart meter seed data. It implements the 9-dataset specification for the 14 dashboard features: enhanced meter registry, readings, forecasts, alerts, topology, audit events, data quality, analyst feedback, and model performance history.

## Files

- `alert_feedback.csv`: 650 rows, 12 columns
- `anomaly_alerts.csv`: 3500 rows, 30 columns
- `audit_events.csv`: 5000 rows, 11 columns
- `data_quality.csv`: 15000 rows, 14 columns
- `demand_forecasts.csv`: 7310 rows, 20 columns
- `grid_topology.csv`: 30 rows, 18 columns
- `meter_readings.csv`: 100000 rows, 24 columns
- `meters.csv`: 500 rows, 17 columns
- `model_performance_history.csv`: 2340 rows, 11 columns

## Notes

- `meters.csv` normalizes the legacy `substation` column to `substation_id`.
- `meter_readings.csv` includes heatmap, peer comparison, load factor, night-ratio, and day-over-day trend fields.
- `anomaly_alerts.csv` includes detector scores, SHAP-style feature contribution fields, loss estimates, reason codes, and recommended actions.
- `grid_topology.csv` includes compact GeoJSON LineStrings for feeder display.
- `alert_feedback.csv` and `model_performance_history.csv` are newly generated tables for feedback and drift monitoring.
