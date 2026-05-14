from statistics import mean
from typing import Any

from app.services.mock_data import (
    alert_detail,
    alerts,
    data_quality,
    feeder_balance,
    forecast_points,
    kpis,
    meter_profile,
    zones,
)

from .response_formatter import sanitize_context


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _forecast_summary(points: list[dict[str, Any]]) -> dict[str, Any]:
    if not points:
        return {}
    peak = max(points, key=lambda point: _num(point.get("forecast")))
    avg_width = mean([_num(point.get("upper90")) - _num(point.get("lower90")) for point in points])
    avg_actual_gap = mean(
        [
            abs(_num(point.get("actual")) - _num(point.get("forecast")))
            for point in points
            if point.get("actual") is not None
        ]
        or [0]
    )
    return {
        "horizonHours": len(points),
        "peakForecastMw": round(_num(peak.get("forecast")), 2),
        "peakTime": peak.get("timestamp"),
        "average90BandWidthMw": round(avg_width, 2),
        "averageActualForecastGapMw": round(avg_actual_gap, 2),
        "points": points[:24],
    }


def _compact_meter(meter: dict[str, Any] | None) -> dict[str, Any] | None:
    if not meter:
        return None
    peer = meter.get("peer", [])[-24:]
    peer_gap = mean([_num(row.get("meterKwh")) - _num(row.get("peerMean")) for row in peer] or [0])
    return {
        "meterId": meter.get("meterId"),
        "consumerType": meter.get("consumerType"),
        "zone": meter.get("zone"),
        "feederId": meter.get("feederId"),
        "tariffCode": meter.get("tariffCode"),
        "contractedKw": meter.get("contractedKw"),
        "alerts": meter.get("alerts", [])[:5],
        "recentPeerGapKwh": round(peer_gap, 3),
        "recentAudit": meter.get("audit", [])[:4],
    }


def build_dashboard_context(frontend_context: dict[str, Any] | None = None) -> dict[str, Any]:
    frontend_context = frontend_context or {}
    selected_meter_id = frontend_context.get("selectedMeter")
    selected_alert_id = frontend_context.get("selectedAlert")

    selected_meter = _compact_meter(meter_profile(selected_meter_id)) if selected_meter_id else None
    selected_alert = alert_detail(selected_alert_id) if selected_alert_id else None
    if selected_alert and not selected_meter:
        selected_meter = _compact_meter(selected_alert.get("meter"))

    context = {
        "activePage": frontend_context.get("page"),
        "selectedZone": frontend_context.get("selectedZone"),
        "kpis": kpis(),
        "forecastSummary": _forecast_summary(forecast_points()),
        "zones": zones()[:8],
        "alerts": alerts()[:8],
        "feeders": feeder_balance()[:8],
        "dataQuality": data_quality()[:6],
        "selectedAlert": selected_alert,
        "selectedMeter": selected_meter,
        "frontendSnapshot": {
            "visibleZones": frontend_context.get("zones", [])[:6],
            "visibleAlerts": frontend_context.get("alerts", [])[:6],
            "visibleForecast": frontend_context.get("forecast", [])[:12],
        },
    }
    return sanitize_context(context)

