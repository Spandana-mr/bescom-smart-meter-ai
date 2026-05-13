# BESCOM Reviewer Demo Edge Cases

This drop-in dataset mirrors the full dashboard schema and adds curated reviewer scenarios:

- `ALT-DEMO001`: critical bypass theft with 4/4 detector consensus and a newly installed meter.
- `ALT-DEMO002`: false positive candidate caused by legitimate occupancy change, with analyst feedback and audit closure.
- `ALT-DEMO003`: confirmed tamper case with field escalation and FIR workflow.
- Severe communication/data-quality degradation for one meter.
- High feeder loss and non-technical-loss scenarios for grid views.
- Drift-monitoring rows where PSI exceeds 0.25 and performance softens.
- Forecast degradation row for reviewer discussion around retraining triggers.

Launch the backend with `BESCOM_DATA_DIR` pointing at this folder to use these cases in the UI.
