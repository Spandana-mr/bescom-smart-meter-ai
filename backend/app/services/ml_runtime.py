import csv
import json
from functools import lru_cache
from pathlib import Path
from typing import Optional

from app.services.energy_accounting import _meter_transformer_map, _transformer_energy_daily

ARTIFACT_DIR = Path(__file__).resolve().parents[2] / "artifacts" / "synthetic_ml"


def _read_json(name, default):
    path = ARTIFACT_DIR / name
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _read_csv(name):
    path = ARTIFACT_DIR / name
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


@lru_cache(maxsize=1)
def training_summary():
    return _read_json(
        "training_summary.json",
        {
            "status": "not_trained",
            "forecasting": {"status": "not_trained"},
            "anomaly_detection": {"status": "not_trained"},
        },
    )


@lru_cache(maxsize=1)
def forecast_preview_rows():
    return _read_csv("forecast_preview.csv")


@lru_cache(maxsize=1)
def anomaly_score_rows():
    return _read_csv("anomaly_scores.csv")


# ── Energy Accounting parent DT integration (Pass 2) ─────────────────────────

@lru_cache(maxsize=1)
def _meter_to_transformer_map() -> dict[str, str]:
    """Returns meter_id -> transformer_id mapping from meter_transformer_map.csv."""
    mapping: dict[str, str] = {}
    for row in _meter_transformer_map():
        mid = row.get("meter_id")
        tid = row.get("transformer_id")
        if mid and tid:
            mapping[mid] = tid
    return mapping


@lru_cache(maxsize=1)
def _dt_recent_unexplained_map() -> dict[str, float]:
    """
    Returns transformer_id -> most recent unexplained_pct.
    Scans transformer_energy_daily rows and takes the latest daily record for each DT.
    """
    latest_by_dt: dict[str, dict] = {}
    for row in _transformer_energy_daily():
        tid = row.get("transformer_id")
        d = row.get("date", "")
        if not tid:
            continue
        if tid not in latest_by_dt or d > latest_by_dt[tid].get("date", ""):
            latest_by_dt[tid] = row

    res: dict[str, float] = {}
    for tid, row in latest_by_dt.items():
        try:
            res[tid] = float(row.get("unexplained_pct", 0.0))
        except (ValueError, TypeError):
            res[tid] = 0.0
    return res


def calculate_combined_risk_score(blended_prob: float, dt_unexplained_pct: Optional[float]) -> float:
    """
    Combines meter-level ML blended_probability (0-1) with parent DT unexplained loss.

    Formula rationale:
    - Normalizes dt_unexplained_pct with a 10.0% cap:
        norm_dt = min(max(dt_unexplained_pct, 0.0) / 10.0, 1.0)
    - If DT unexplained loss is near zero (or negative due to metering noise),
      norm_dt -> 0.0, and combined_risk_score stays close to blended_probability.
    - If DT unexplained loss is elevated (e.g. 5% to 10%+), it provides corroborating
      network-level evidence, boosting the prioritization score:
        combined = blended_prob + 0.30 * norm_dt * (1.0 - blended_prob)
    - If parent DT is not mapped or data is missing, falls back to blended_probability.
    - Bounded strictly to [0.0, 1.0].
    """
    if dt_unexplained_pct is None:
        return round(blended_prob, 5)

    norm_dt = min(max(dt_unexplained_pct, 0.0) / 10.0, 1.0)
    score = blended_prob + 0.30 * norm_dt * (1.0 - blended_prob)
    return round(min(1.0, max(0.0, score)), 5)


def _enrich_anomaly_row(row: dict) -> dict:
    """
    Enriches an anomaly score row with parent DT context at read time:
    - transformer_id: parent DT ID if mapped
    - dt_unexplained_pct: parent DT's current unexplained loss percentage
    - combined_risk_score: heuristic blend of blended_probability and dt_unexplained_pct
    Does not modify or remove any existing field.
    """
    m_map = _meter_to_transformer_map()
    dt_loss_map = _dt_recent_unexplained_map()

    meter_id = row.get("meter_id", "")
    tid = m_map.get(meter_id)

    try:
        blended_prob = float(row.get("blended_probability", 0.0))
    except (ValueError, TypeError):
        blended_prob = 0.0

    if tid and tid in dt_loss_map:
        dt_loss = dt_loss_map[tid]
        combined = calculate_combined_risk_score(blended_prob, dt_loss)
    else:
        dt_loss = None
        combined = round(blended_prob, 5)

    enriched = dict(row)
    enriched["transformer_id"] = tid
    enriched["dt_unexplained_pct"] = dt_loss
    enriched["combined_risk_score"] = combined
    return enriched


def runtime_status():
    summary = training_summary()
    return {
        "trained": summary.get("forecasting", {}).get("status") == "trained"
        and summary.get("anomaly_detection", {}).get("status") == "trained",
        "artifactDir": str(ARTIFACT_DIR),
        "generatedAt": summary.get("generated_at"),
        "forecasting": summary.get("forecasting", {}),
        "anomalyDetection": summary.get("anomaly_detection", {}),
    }


def forecast_preview(limit=48):
    rows = forecast_preview_rows()
    return rows[-max(1, min(limit, 240)) :]


def anomaly_rankings(limit=50):
    rows = anomaly_score_rows()
    enriched = [_enrich_anomaly_row(row) for row in rows]
    # Sort by combined_risk_score descending, falling back to blended_probability
    enriched.sort(
        key=lambda r: (
            float(r.get("combined_risk_score") or 0.0),
            float(r.get("blended_probability") or 0.0),
        ),
        reverse=True,
    )
    return enriched[: max(1, min(limit, 500))]


def anomaly_scores_for_meter(meter_id):
    rows = [row for row in anomaly_score_rows() if row.get("meter_id") == meter_id][:90]
    return [_enrich_anomaly_row(row) for row in rows]

