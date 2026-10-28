# Antigravity Prompt — Pass 2 Verification Checks

Run this after Pass 2 (Risk Pipeline Integration) implementation is
reported complete, before it's signed off as final. This is verification
only — do not change the design, the blend formula, or any file structure
unless you find an actual bug while checking. Do not run any git commands
or create any commits — that will be done separately.

---

## CONTEXT

Pass 2 modified `backend/app/services/ml_runtime.py` (combined risk score
blending `blended_probability` with `dt_unexplained_pct`),
`backend/app/services/mock_data.py` (attaching `transformerId` /
`dtUnexplainedPct` to alert responses), and `frontend/src/main.tsx`
(corroborating-context notes on alert cards/detail). The reported combined
score formula is:

```
norm_dt = min(max(dt_unexplained_pct, 0.0) / 10.0, 1.0)
combined = blended_prob + 0.30 * norm_dt * (1.0 - blended_prob)
```

## CHECKS TO RUN

### 1. `mock_data.py` — confirm existing alert fields are untouched

- Fetch a full alert object from `GET /api/v1/alerts` (and from the
  single-alert detail endpoint if one exists) and list every field it
  returns.
- Compare that field list against what `_alert_summary` (and the detail
  equivalent) returned **before** Pass 2's change — every field that
  existed before must still be present, with the same name and same
  value semantics. Only new fields (`transformerId`, `dtUnexplainedPct`)
  should have been added.
- Report the full before/after field list, not just a summary statement of
  "unchanged."

### 2. No-DT-mapping fallback — confirm it's actually handled, not assumed

- Check whether every meter in `meter_transformer_map.csv` has a
  `transformer_id` (i.e. whether an unmapped meter can even occur given
  the current dataset).
- Regardless of whether an unmapped meter currently exists in the data,
  trace through `_enrich_anomaly_row` / `calculate_combined_risk_score` in
  `ml_runtime.py` and confirm what happens if `_meter_to_transformer_map()`
  has no entry for a given `meter_id`: does it fall back cleanly to
  `combined_risk_score = blended_probability` (as required), or would it
  raise an error / silently produce a wrong value (e.g. treating a missing
  lookup as `dt_unexplained_pct = 0`, which is a different thing than "no
  DT signal available")?
- If the current dataset happens to have no unmapped meters, write a
  temporary/synthetic test case (in a scratch script or test file, not by
  editing the real dataset) that calls the enrichment function with a
  meter_id that has no transformer mapping, and confirm the actual
  behavior. Report exactly what happens.

### 3. `anomaly_rankings()` sort behavior — confirm the fallback sort works too

- Confirm that when `combined_risk_score` is unavailable for a given row
  (per the fallback case above), the sort still places that row sensibly
  by falling back to `blended_probability`, rather than sorting it as if
  its score were 0, None, or otherwise incorrectly.

### 4. Formula bounds sanity check

- Independently recompute `combined_risk_score` for at least 5 meters
  spanning a range of `blended_probability` and `dt_unexplained_pct`
  values (include: a low-blended-prob/high-unexplained-pct meter, a
  high-blended-prob/low-unexplained-pct meter, and one right at or near
  the 10% `dt_unexplained_pct` cap boundary) using the formula above, and
  confirm the API's returned `combined_risk_score` matches your
  independent calculation exactly (within floating-point rounding).
- Confirm `combined_risk_score` never exceeds 1.0 or drops below the
  original `blended_probability` for any row you check (the formula should
  only ever raise the score, never lower it).

### 5. Duplicated logic check (informational, not necessarily a fix)

- Confirm whether the meter → DT → `unexplained_pct` lookup logic in
  `ml_runtime.py` (`_meter_to_transformer_map`, `_dt_recent_unexplained_map`)
  duplicates logic already present in `energy_accounting.py`, or whether it
  reads the same underlying CSVs independently.
- Report which CSVs/columns each of the two implementations reads and
  whether they could ever disagree (e.g. one using "latest date in range"
  and the other using a different date-selection rule). You do not need to
  consolidate them in this task — just report clearly whether they're
  consistent, so a future maintainer knows if there's a risk of drift.

### 6. Full endpoint regression pass

- Call every existing endpoint that existed before Pass 1 (the same list
  used in Pass 1's verification: `/api/v1/health`, `/api/v1/kpis` or
  `/api/v1/dashboard/overview`, `/api/v1/alerts`, `/api/v1/zones`,
  `/api/v1/ml/anomaly-rankings`, `/api/v1/ml/meters/{meter_id}/anomaly-scores`,
  plus a couple more picked from `backend/main.py`) and confirm each
  returns HTTP 200 with its expected shape, unchanged from before Pass 2
  except for the documented additive fields.
- Call every `/api/v1/energy-accounting/*` endpoint from Pass 1 again and
  confirm they still work unmodified (Pass 2 should not have touched
  `energy_accounting.py`, but verify rather than assume).

### 7. Frontend check

- Confirm `npm run build` is still clean (zero TypeScript errors).
- Confirm the corroborating-context note on alert cards only appears when
  `dtUnexplainedPct` is actually present/meaningful for that alert, and
  degrades gracefully (no broken layout, no "undefined%" text) for any
  alert where it isn't available.

## OUTPUT

Report the results of all 7 checks clearly, one by one, with actual values/
evidence (not just pass/fail statements). Flag anything that didn't behave
as expected — do not silently fix it, describe what you found and propose
the fix so it can be reviewed before you apply it.
