# Energy-Accounting Dataset Extension

Extends the existing BESCOM Smart Meter AI dataset (`data/bescom_dataset/`)
with an **upstream energy hierarchy**: Substation → Feeder → Distribution
Transformer (DT) → Meter. This lets the project compute unexplained energy
loss (input − metered − expected technical loss) instead of relying only on
per-meter consumption anomalies.

**Scope**: analysis starts at the BESCOM substation's outgoing (secondary)
side. Generation and transmission upstream of the substation are out of
scope and are not modeled.

**Nothing in the existing dataset was modified.** These are five new CSVs
plus this README; `meters.csv`, `meter_readings.csv`, `anomaly_alerts.csv`,
`grid_topology.csv`, `demand_forecasts.csv`, etc. are untouched and still
work exactly as before.

## New files

| File | Grain | Rows | Purpose |
|---|---|---|---|
| `distribution_transformers.csv` | 1 row / DT | 36 | New DT registry (feeder → DT level didn't exist before) |
| `meter_transformer_map.csv` | 1 row / meter | 500 | Which DT each of the 500 existing meters sits under |
| `transformer_energy_daily.csv` | DT × day | 26,316 | **Core table.** Daily input energy, metered energy, technical loss, unexplained energy per DT |
| `feeder_energy_daily.csv` | feeder × day | 21,930 | Daily feeder input energy (rollup of its DTs + feeder-conductor loss) |
| `substation_energy_daily.csv` | substation × day | 7,310 | Daily substation input energy (rollup of its feeders) |

All daily tables cover **2023-01-01 to 2024-12-31**, matching the date range
of the existing `meter_readings.csv` / `demand_forecasts.csv`.

### `distribution_transformers.csv`
`transformer_id, feeder_id, substation_id, zone, rated_kva, connected_load_kw, install_year, location_type, dt_technical_loss_pct_model`

- `rated_kva` is picked from a standard LT distribution-transformer catalog
  (100–3150 kVA) sized to give the DT's actual connected load (`connected_load_kw`,
  the sum of `contracted_kw` for meters assigned to it) roughly 40–80% headroom.
- `dt_technical_loss_pct_model` is the *generation-time* parameter used to
  synthesize technical loss (see Methodology). It is **not** what the
  accounting engine should read back as "the answer" — the engine derives
  loss from `transformer_energy_daily.csv`'s own `technical_loss_kwh`
  column, which is a separate, independently-computed figure.

### `meter_transformer_map.csv`
`meter_id, transformer_id, feeder_id, substation_id, zone`

One row per existing meter in `meters.csv`. Meters under a feeder are
distributed round-robin across that feeder's DTs (deterministic, seeded).

### `transformer_energy_daily.csv` — the table the new engine reads
`date, transformer_id, feeder_id, zone, input_kwh, metered_kwh, technical_loss_kwh, unexplained_kwh, unexplained_pct, theft_event_flag, meters_flagged`

- `input_kwh` — energy delivered into the DT that day (actual physical
  consumption of its meters + technical loss).
- `metered_kwh` — sum of what those meters' billing/AMI system actually
  *recorded* that day (this is lower than actual consumption on days a
  meter has an active tamper/theft event).
- `technical_loss_kwh` — expected/modeled technical loss for that DT-day.
- `unexplained_kwh = input_kwh − metered_kwh − technical_loss_kwh`. This is
  the energy-accounting engine's core output.
- `theft_event_flag` / `meters_flagged` — ground-truth marker (**for
  validation only** — a real engine wouldn't have this) showing whether
  ≥1 meter under this DT had an active `anomaly_alerts.csv` event that day.

### `feeder_energy_daily.csv`
`date, feeder_id, substation_id, zone, input_kwh, sum_dt_input_kwh, feeder_technical_loss_kwh`
`input_kwh = sum_dt_input_kwh + feeder_technical_loss_kwh` (conductor loss
between the feeder head and its DTs).

### `substation_energy_daily.csv`
`date, substation_id, zone, input_kwh, num_feeders`
`input_kwh = sum of that substation's feeders' input_kwh` for the day. No
extra loss is added at this level (out of scope, per the substation-start
constraint) — this is the top of the modeled hierarchy.

Top-to-bottom reconciliation is exact by construction: substation `input_kwh`
== sum of its feeders' `input_kwh` == sum of those feeders' DTs' `input_kwh`
+ modeled losses at each stage.

## Methodology (how these were generated, and why they're consistent)

The generator (`gen_energy_accounting_data.py`) builds the new tables
**bottom-up from data already in the project**, not independently — this is
the part that matters, since two separately-generated datasets would just
produce meaningless "unexplained energy" noise.

1. **DT registry**: one or more DTs created per feeder, using the existing
   `transformer_count` column in `grid_topology.csv`.
2. **Meter → DT assignment**: round-robin within each feeder (deterministic).
3. **Per-meter daily baseline (actual physical usage)**: for the 200 meters
   that have rows in `meter_readings.csv`, baseline = their average hourly
   `kwh` × 24. For the other 300 meters (which have no readings in the
   existing sparse sample), baseline = `contracted_kw` × a typical load
   factor by `consumer_type` (Residential 0.22, Commercial 0.35, Industrial
   0.55, Agricultural 0.30) × 24.
4. **Zone daily shape**: each meter's daily baseline is modulated by a
   per-zone, per-day index derived from the *existing*
   `demand_forecasts.csv` (`actual_mw`, normalized to mean = 1.0 per zone).
   This is what carries real seasonal/weekday/holiday shape into the new
   data — and it's applied identically to a DT's total input and to its
   meters' consumption, so a zone-wide demand dip (e.g. a holiday) reduces
   both sides equally and produces **no unexplained energy** — this is the
   fix for the "vacation problem."
5. **Theft/tamper suppression**: for each row in the *existing*
   `anomaly_alerts.csv`, the affected meter's *metered* (recorded) energy is
   suppressed by `consumption_drop_pct` for a short window around
   `alert_timestamp` (up to `resolution_timestamp`). Actual physical
   consumption is unaffected — only what the meter reports is reduced. This
   is the mechanism that creates real unexplained energy, and it's tied
   directly to alerts your existing ML pipeline already produces, so the two
   evidence streams corroborate each other for genuine cases.
6. **Technical loss**: modeled as a per-DT base loss fraction (seeded loosely
   from the existing `grid_topology.csv` → `feeder_loss_pct`, scaled down and
   randomized — used only as a generation parameter, not copied through as
   an output) plus day-to-day noise. Feeder-level conductor loss is modeled
   the same way, as an additional stage.
7. Small Gaussian noise is added to both consumption and metering to avoid
   perfectly clean zeros on non-flagged days (real meters have small,
   normal tolerance error).

## Validation (from the generation run)

- **Clean DT-days** (no active alert under that DT that day): mean
  `unexplained_pct` ≈ **0.006%** — essentially zero, as expected.
- **Flagged DT-days** (≥1 meter under that DT has an active alert): mean
  `unexplained_pct` ≈ **4.7%**, median 0.7%, right-skewed up to 70%+ on
  DT-days where a large flagged meter dominates a small transformer's load
  — i.e. plenty of borderline cases plus some clear "investigate this"
  cases, not just a binary signal.
- Reconciliation is exact: `sum(DT input_kwh)` under a feeder for a given
  day exactly equals `feeder_energy_daily.sum_dt_input_kwh` for that
  feeder/day, and `sum(feeder input_kwh)` under a substation exactly equals
  `substation_energy_daily.input_kwh`.

## Known limitations (be upfront about these if asked)

- This is **synthetic, parameterized data**, not measured technical loss —
  fine for an academic prototype, but should be labeled as such anywhere it
  appears in the dashboard or paper.
- `dt_technical_loss_pct_model` and the feeder loss-anchor are only
  generation-time parameters; don't present them as if the engine "looked
  them up" — the actual deliverable is that the engine recomputes
  `unexplained_kwh` from `input_kwh`, `metered_kwh`, and
  `technical_loss_kwh`, independently.
- The 300 meters without `meter_readings.csv` rows use a load-factor
  fallback for their baseline; this is coarser than the 200 meters with
  real hourly samples.
- DT sizing uses a standard kVA catalog and connected load only; it doesn't
  account for real-world diversity/coincidence factors.

## Suggested next step in the backend

Add `backend/app/services/energy_accounting.py` that reads
`transformer_energy_daily.csv` (joined to `distribution_transformers.csv`
and `meter_transformer_map.csv`) and exposes it via new `/api/v1/energy-accounting/*`
endpoints (zone/feeder/DT summaries, top-unexplained-loss ranking) for a new
"Energy Accounting" dashboard page — then feed `unexplained_pct` as an
additional feature into the existing meta-classifier / alert pipeline
alongside the VAE/EIF/BOCPD scores, as discussed.
