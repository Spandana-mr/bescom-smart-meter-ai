# Antigravity Prompt — Pass 1: Energy Accounting Layer (Backend + API + Dashboard)

Run this pass first. Pass 2 (risk-pipeline integration) depends on this one
being complete and reviewed.

---

## CONTEXT

This is the BESCOM Smart Meter AI project — a FastAPI + React dashboard for
electricity theft detection and demand forecasting for BESCOM (Bangalore's
electricity distribution utility). Full architecture is documented in
`BESCOM_Master_Builder_Prompt.md` and `README.md`.

Five new CSV files already exist in `data/bescom_dataset/`:
`distribution_transformers.csv`, `meter_transformer_map.csv`,
`transformer_energy_daily.csv`, `feeder_energy_daily.csv`, and
`substation_energy_daily.csv`. Read `data/ENERGY_ACCOUNTING_DATA_README.md`
first — it documents every column and how these tables were generated
consistently with the existing `meter_readings.csv`, `anomaly_alerts.csv`,
and `demand_forecasts.csv`. Do not regenerate or modify these CSVs.
`transformer_energy_daily.csv` has `theft_event_flag` / `meters_flagged`
columns that exist for generation-validation only — never expose those two
columns through any API response or UI.

Do not modify or remove any existing file, model, table, or endpoint. This
must be a strictly additive change — every existing route in
`backend/main.py` must keep returning exactly what it returns today.

## THE ARCHITECTURAL PROBLEM BEING FIXED

The current theft-detection logic asks "did this meter's consumption look
unusual?" — which is not sufficient, because legitimate consumption drops
(vacation, weather, seasonal closure) look identical to theft-driven drops
to a naive detector. The correct approach, used by real distribution
utilities, is hierarchical:

1. **Energy accounting (network level)**: does energy delivered into a
   distribution transformer (DT) reconcile with what its downstream meters
   report, after expected technical loss? If yes — no escalation,
   regardless of any individual meter's consumption movement. If there's a
   meaningful UNEXPLAINED gap, that DT is a candidate for investigation.
2. **Meter-level investigation** (secondary, only within a flagged DT): use
   existing anomaly signals to identify which specific meters are most
   likely responsible.

**Scope constraint**: analysis starts at the BESCOM substation's outgoing
(secondary) side and goes downstream only (substation → feeder → DT →
meter). Nothing upstream of the substation is modeled.

## TASK FOR THIS PASS

Self-contained — do **not** touch the existing anomaly/risk pipeline yet,
that is a separate follow-up task (Pass 2).

### 1. New backend service: `backend/app/services/energy_accounting.py`

- Load the 5 new CSVs from the existing `DATA_DIR` mechanism already used
  by `app/services/mock_data.py` (same pattern: env-overridable directory
  via `BESCOM_DATA_DIR`, pandas-based reads).
- Expose functions to compute, per DT / feeder / substation / zone and over
  a given date range: total `input_kwh`, total `metered_kwh`, total
  `technical_loss_kwh`, total `unexplained_kwh`, and `unexplained_pct`.
- Expose a ranking function: given a date range and optional zone filter,
  return DTs sorted by `unexplained_kwh` or `unexplained_pct` descending.
- Expose a drill-down function: given a `transformer_id`, return its daily
  energy-accounting time series for a date range, the meters mapped to it
  (via `meter_transformer_map.csv`), and — for each of those meters — any
  existing `anomaly_alerts.csv` entries whose `alert_timestamp` falls in
  that date range (this is the cross-reference between the two evidence
  types, read-only, no modification to `anomaly_alerts.csv`).

### 2. New API routes in `backend/main.py`

Follow the existing route style (see the `/api/v1/ml/*` and
`/api/v1/zones/*` routes as the pattern to match) — add these exact paths:

- `GET /api/v1/energy-accounting/summary`
  query params: `zone` (optional), `start_date`, `end_date`
  → `{ total_input_kwh, total_metered_kwh, total_technical_loss_kwh, total_unexplained_kwh, unexplained_pct }`
- `GET /api/v1/energy-accounting/transformers`
  query params: `zone` (optional), `start_date`, `end_date`, `limit` (default 20)
  → `{ items: [ { transformer_id, feeder_id, zone, unexplained_kwh, unexplained_pct, ... } ] }`
  ranked descending by `unexplained_pct`
- `GET /api/v1/energy-accounting/transformers/{transformer_id}`
  → `{ transformer: {...}, daily_series: [...], meters: [...], related_alerts: [...] }`
- `GET /api/v1/energy-accounting/feeders` and
  `GET /api/v1/energy-accounting/substations` — analogous rollup views

### 3. Frontend: new "Energy Accounting" tab in `frontend/src/main.tsx`

- Match the existing visual style and data-fetching pattern already used
  for the other tabs (Alerts, Zones, Grid, Model Health, Data Quality).
- Include: a summary panel (the 5 totals + unexplained %), a ranked table
  of DTs ("top areas requiring review"), and a drill-down view for a
  selected DT showing its daily unexplained-energy trend plus its mapped
  meters and any related existing alerts.
- Wire it to the new `/api/v1/energy-accounting/*` endpoints.

### 4. Documentation

Briefly update `README.md` and `BESCOM_Master_Builder_Prompt.md` to
describe the new energy-accounting layer's place in the architecture
(DT-level energy balance as the network-level view; meter-level ML as a
separate, still-independent layer for now — this pass does not connect
them, that's the next task). Note the scope boundary (starts at substation
output) and that technical-loss figures are synthetic/parametric, per
`data/ENERGY_ACCOUNTING_DATA_README.md`.

## CONSTRAINTS

- Never present a meter-level consumption drop, by itself, as evidence of
  theft anywhere in new UI copy or docs.
- Never claim technical-loss figures are measured/real.
- Match existing code conventions exactly (FastAPI route style in
  `backend/main.py`, pandas-based loading pattern in `mock_data.py`,
  TypeScript/React patterns already in `main.tsx`) — do not introduce a new
  stack or pattern for this feature alone.

## VERIFICATION BEFORE FINISHING THIS PASS

- Start the backend and confirm every existing route still returns a
  response (spot-check `/api/v1/kpis`, `/api/v1/alerts`,
  `/api/v1/ml/anomaly-rankings`, `/api/v1/zones` — pick a handful across
  the file).
- Confirm each new `/api/v1/energy-accounting/*` route returns valid JSON
  with the DT-level `unexplained_pct` values roughly matching what's
  described in `data/ENERGY_ACCOUNTING_DATA_README.md`'s validation section
  (clean periods near 0%, flagged periods clearly higher).
- Confirm the frontend builds and the new tab renders without breaking any
  existing tab.
