# Antigravity Prompt — Pass 2: Connect Energy Accounting into the Existing Risk Pipeline

Run this pass only after Pass 1 (Energy Accounting Layer) is complete,
reviewed, and confirmed working.

---

## CONTEXT

Pass 1 added `backend/app/services/energy_accounting.py` and the
`/api/v1/energy-accounting/*` endpoints (see that code for the exact schema
of `unexplained_pct` per transformer/day). This pass connects that signal
into the existing per-meter risk score.

The existing per-meter risk score lives in
`backend/artifacts/synthetic_ml/anomaly_scores.csv` (regenerated offline by
`scripts/train_synthetic_models.py`) and is served, unmodified, by
`backend/app/services/ml_runtime.py`'s `anomaly_rankings()` and
`anomaly_scores_for_meter()` functions, via `GET /api/v1/ml/anomaly-rankings`
and `GET /api/v1/ml/meters/{meter_id}/anomaly-scores`. Its key field is
`blended_probability` (0–1), one row per meter.

Do not modify or remove any existing file, model, table, or endpoint. This
must be a strictly additive change.

## TASK

Do this at **READ time** in `ml_runtime.py`, not by retraining the models in
`scripts/train_synthetic_models.py`:

1. In `ml_runtime.py`, for each row returned by `anomaly_rankings()` and
   `anomaly_scores_for_meter()`, look up that meter's `transformer_id` via
   `data/bescom_dataset/meter_transformer_map.csv`, then look up that
   transformer's most recent `unexplained_pct` from
   `data/bescom_dataset/transformer_energy_daily.csv` (or use the summary
   function added in `energy_accounting.py` in Pass 1 — reuse it rather
   than re-implementing the lookup).
2. Add two new fields to each returned row, additive only — do not remove
   or rename `blended_probability` or any existing field:
   - `dt_unexplained_pct`: the parent DT's current `unexplained_pct`
   - `combined_risk_score`: a simple, clearly-documented blend of
     `blended_probability` and `dt_unexplained_pct` (e.g. a weighted
     average after normalizing `dt_unexplained_pct` to a 0–1 scale with a
     reasonable cap — choose and clearly comment the formula; this does
     not need to be a trained/calibrated model, a documented heuristic
     blend is acceptable for this prototype)
3. Sort `anomaly_rankings()` by `combined_risk_score` instead of
   `blended_probability` when both are available, falling back to
   `blended_probability` alone for meters with no DT mapping.
4. On the frontend, where the existing Alerts view shows a meter's
   risk/score, add the DT's `unexplained_pct` as corroborating context
   (e.g. a small inline note: "Parent transformer DT-XXX: unexplained loss
   X.X% this period") — do not remove or restyle anything else in that
   view.

## CONSTRAINTS

- Do not modify `anomaly_scores.csv`, `training_summary.json`, or any file
  under `backend/artifacts/`. This is a read-time blend only.
- Do not change the response shape of any existing field — only add new
  fields.
- Clearly comment the `combined_risk_score` formula in code so it reads as
  an explicit, documented heuristic, not a black box.
- Never present a meter-level consumption drop, by itself, as evidence of
  theft anywhere in new UI copy or docs — the blended score exists to
  *prioritize* investigation, not to accuse a meter.

## VERIFICATION

- Confirm `/api/v1/ml/anomaly-rankings` and
  `/api/v1/ml/meters/{meter_id}/anomaly-scores` still return every field
  they returned before this pass, plus the two new fields.
- Spot-check a handful of meters: one under a DT with near-zero
  `unexplained_pct` (`combined_risk_score` should stay close to
  `blended_probability`) and one under a DT with high `unexplained_pct`
  (`combined_risk_score` should be meaningfully higher than
  `blended_probability` alone).
- Confirm the frontend Alerts view still renders correctly with the new
  corroborating-context note added.
