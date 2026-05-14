from typing import Any

from app.services.mock_data import alerts, feeder_balance, forecast_points, zones


def fetch_forecast_summary() -> list[dict[str, Any]]:
    return forecast_points()[:24]


def fetch_anomaly_alerts(limit: int = 10) -> list[dict[str, Any]]:
    return alerts()[:limit]


def summarize_risk_zones(limit: int = 8) -> list[dict[str, Any]]:
    return zones()[:limit]


def fetch_feeder_risk(limit: int = 8) -> list[dict[str, Any]]:
    return feeder_balance()[:limit]
