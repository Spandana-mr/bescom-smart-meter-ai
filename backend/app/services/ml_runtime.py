import csv
import json
from functools import lru_cache
from pathlib import Path


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
    return rows[: max(1, min(limit, 500))]


def anomaly_scores_for_meter(meter_id):
    return [row for row in anomaly_score_rows() if row.get("meter_id") == meter_id][:90]
