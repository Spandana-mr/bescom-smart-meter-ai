# Antigravity Prompt — Pass 1 Follow-up: Date-Range Selector + Git Checkpoint

Run this after Pass 1 (Energy Accounting Layer) and before Pass 2 (Risk
Pipeline Integration). This is a small, additive tweak to what Pass 1 built
— not a new architectural pass.

---

## CONTEXT

Pass 1 added `backend/app/services/energy_accounting.py`, the
`/api/v1/energy-accounting/*` routes, and the "Energy Accounting" tab in
`frontend/src/main.tsx` (`EnergyAccountingPage` component). All five
endpoints already accept optional `zone`, `start_date`, `end_date` query
params — the backend supports arbitrary date ranges. The problem is the
frontend: it currently has no UI control for the analyst to change the date
range, so the DT ranking table is defaulting to (or effectively showing) the
full 2023–2024 window. Averaged over two years, every DT's `unexplained_pct`
clusters near 1–2% — the short, spiky periods that make individual DTs stand
out as "investigate this" candidates get diluted into a long-run average and
disappear.

## TASK

### 1. Add a date-range selector to `EnergyAccountingPage`

Add a dropdown/selector control at the top of the Energy Accounting tab,
above the summary panel, with these options:

```
Date range:
[ Last 30 days ▼ ]

Options:
- Last 7 days
- Last 30 days
- Last 90 days
- Last 1 year
- All time
- Custom range (analyst enters start and end date manually)
```

Requirements:

- Default selection: **Last 30 days** (not "All time" — the whole point of
  this change is that a short window is what surfaces useful signal).
- Anchor "Last N days" relative to the latest date actually present in
  `transformer_energy_daily.csv` (the dataset ends 2024-12-31 and is not
  live data), not relative to today's real-world date — otherwise "Last 7
  days" would return an empty range.
- "Custom range" reveals two date inputs (start date, end date) that the
  analyst fills in directly and applies — this must be freely settable by
  the analyst to any range, not restricted to the four presets.
- Changing the selector (or applying a custom range) must re-fetch and
  re-render: the summary panel, the ranked DT table, and — if a DT is
  currently drilled into — the drill-down view, all scoped to the newly
  selected range.
- Match the existing visual style and component patterns already used
  elsewhere in `main.tsx` (reuse existing dropdown/select and date-input
  components/styling if the codebase already has them; do not introduce a
  new UI library for this).
- Keep the selected range in React state (e.g. `useState`) scoped to the
  Energy Accounting page — it does not need to persist across page
  navigation or reloads.

### 2. No backend changes should be required

The backend already accepts `start_date`/`end_date` on every
`/api/v1/energy-accounting/*` route from Pass 1. Do not modify
`energy_accounting.py` or the route handlers in `main.py` unless you find an
actual bug in how they handle a date range (e.g. an off-by-one, or a range
that returns an error instead of an empty result) — if so, fix only that
bug and note it explicitly in your summary, since it wasn't part of Pass 1's
scope. Confirm this by testing the existing endpoints directly with a few
of the ranges above before touching frontend code.

## CONSTRAINTS

- Strictly additive to the frontend — do not remove or restructure anything
  else on the Energy Accounting tab or any other tab.
- Do not touch `backend/app/services/ml_runtime.py`,
  `backend/artifacts/synthetic_ml/`, or anything related to the existing
  anomaly/risk pipeline — that is Pass 2's scope, not this task's.

## VERIFICATION

- Confirm the frontend builds cleanly (`npm run build`), no TypeScript
  errors.
- Manually confirm: selecting "Last 30 days" produces a DT ranking with
  clearly differentiated `unexplained_pct` values across DTs (not all
  clustered near 1–2%), consistent with the per-DT-day spikes described in
  `data/ENERGY_ACCOUNTING_DATA_README.md`'s validation section.
- Confirm "Last 7 days" / "Last 90 days" / "Last 1 year" / "All time" all
  return valid, differently-scoped results.
- Confirm "Custom range" lets you freely enter any start/end date and
  updates the summary, table, and drill-down accordingly.
- Confirm every existing tab and every existing route (the ones checked in
  Pass 1's verification) still works.

---

## GIT OPERATIONS — do this after the above is verified working

This is a checkpoint before Pass 2 touches shared, higher-risk code
(`ml_runtime.py`). Do the following in the project's git repository:

1. Run `git status` and `git diff --stat` and show me the output before
   committing anything — confirm the changed-files list matches what's
   expected (only `frontend/src/main.tsx` should have changed for this
   follow-up task; `backend/main.py` and `energy_accounting.py` should
   only appear here if you found and fixed a genuine date-range bug per
   the constraint above).
2. Stage and commit all of Pass 1's changes plus this follow-up as a single
   clean checkpoint commit (or two commits — one for Pass 1, one for this
   follow-up — either is fine, your choice, as long as the history is
   readable) with a clear commit message describing what was added:
   the new energy-accounting service, routes, dashboard tab, docs updates,
   and the date-range selector.
3. Do **not** touch any file related to Pass 2's scope
   (`ml_runtime.py`, `backend/artifacts/`) in this commit — this checkpoint
   should represent "Pass 1 complete, nothing from Pass 2 started."
4. After committing, run `git log --oneline -5` and show me the result so
   there's a clear rollback point on record before Pass 2 begins.
5. Do not push, force-push, or rewrite any existing history — only add new
   commit(s) on top of the current branch.
