import csv
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from statistics import mean


DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "bescom_dataset"


def _now():
    return datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)


def _read_csv(name):
    path = DATA_DIR / name
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


@lru_cache(maxsize=None)
def meters_rows():
    return _read_csv("meters.csv")


@lru_cache(maxsize=None)
def reading_rows():
    return _read_csv("meter_readings.csv")


@lru_cache(maxsize=None)
def forecast_rows():
    return _read_csv("demand_forecasts.csv")


@lru_cache(maxsize=None)
def alert_rows():
    return _read_csv("anomaly_alerts.csv")


@lru_cache(maxsize=None)
def topology_rows():
    return _read_csv("grid_topology.csv")


@lru_cache(maxsize=None)
def audit_rows():
    return _read_csv("audit_events.csv")


@lru_cache(maxsize=None)
def dq_rows():
    return _read_csv("data_quality.csv")


def _float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _dt(value):
    if not value:
        return _now()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return _now()


def _risk_from_load(load_pct):
    if load_pct >= 90:
        return "Critical"
    if load_pct >= 75:
        return "High"
    if load_pct >= 60:
        return "Medium"
    return "Normal"


def _next_action(alert):
    severity = alert.get("severity", "").lower()
    status = alert.get("status", "")
    if status.lower() == "resolved":
        return "Review closure evidence"
    if severity == "critical":
        return "Physical inspection within 24 hours"
    if severity == "high":
        return "Assign field team"
    if severity == "medium":
        return "Analyst review"
    return "Monitor trend"


def kpis():
    meters = meters_rows()
    readings = reading_rows()
    alerts = alert_rows()
    forecasts = forecast_rows()
    audits = audit_rows()

    open_alerts = [row for row in alerts if row.get("status") in {"Open", "Investigating"}]
    critical_alerts = [row for row in open_alerts if row.get("severity") == "Critical"]
    theft_rows = [row for row in readings if row.get("is_theft_flag") == "True"]
    recent_forecasts = forecasts[-500:] if forecasts else []
    resolved_alerts = [row for row in alerts if row.get("status") == "Resolved"]
    false_positive_alerts = [row for row in alerts if row.get("status") == "False Positive"]
    fines = sum(_float(row.get("fine_inr")) for row in audits)

    return {
        "metersMonitored": len(meters),
        "readsPerDay": len(readings),
        "openAlerts": len(open_alerts),
        "criticalAlerts": len(critical_alerts),
        "precisionAt50": round(len(resolved_alerts) / max(1, len(resolved_alerts) + len(false_positive_alerts)), 2),
        "forecastMape": round(mean([_float(row.get("mape_pct")) for row in recent_forecasts]) / 100, 3) if recent_forecasts else 0,
        "revenueAtRisk": round(sum(_float(row.get("estimated_loss_units")) * 8 for row in open_alerts), 2),
        "recoveredMtd": round(fines, 2),
        "theftRows": len(theft_rows),
        "lastUpdated": _now().isoformat(),
    }


def zones():
    alerts_by_zone = Counter(row.get("zone") for row in alert_rows() if row.get("status") in {"Open", "Investigating"})
    load_by_zone = defaultdict(list)
    meters_by_zone = defaultdict(list)

    for row in topology_rows():
        load_by_zone[row.get("zone")].append(_float(row.get("load_pct")))
    for row in meters_rows():
        meters_by_zone[row.get("zone")].append(row)

    items = []
    for zone, zone_meters in meters_by_zone.items():
        loads = load_by_zone.get(zone, [0])
        avg_load = round(mean(loads), 1)
        latitudes = [_float(row.get("latitude")) for row in zone_meters]
        longitudes = [_float(row.get("longitude")) for row in zone_meters]
        items.append(
            {
                "name": zone,
                "risk": _risk_from_load(avg_load),
                "openAlerts": alerts_by_zone.get(zone, 0),
                "lossPct": round(max(1.5, alerts_by_zone.get(zone, 0) / max(1, len(zone_meters)) * 25), 1),
                "loadPct": avg_load,
                "lat": round(mean(latitudes), 6),
                "lon": round(mean(longitudes), 6),
            }
        )
    return sorted(items, key=lambda row: (row["risk"] != "Critical", -row["openAlerts"], row["name"]))


def alerts():
    rows = sorted(alert_rows(), key=lambda row: _dt(row.get("alert_timestamp")), reverse=True)
    items = []
    for row in rows[:50]:
        probability = _float(row.get("anomaly_score"))
        revenue_impact = round(_float(row.get("estimated_loss_units")) * 8, 2)
        items.append(
            {
                "id": row.get("alert_id"),
                "meterId": row.get("meter_id"),
                "zone": row.get("zone"),
                "risk": row.get("severity") or "Medium",
                "status": row.get("status") or "Open",
                "type": row.get("anomaly_type") or "Anomaly",
                "probability": probability,
                "urgencyScore": round(probability * max(1, revenue_impact) * 10, 2),
                "revenueImpact": revenue_impact,
                "detectors": [row.get("model_version") or "Detector", "Peer", "SHAP"],
                "detectedAt": _dt(row.get("alert_timestamp")).isoformat(),
                "summary": (
                    f"{row.get('anomaly_type')} alert raised in {row.get('zone')} "
                    f"with {probability:.0%} detector confidence."
                ),
                "nextAction": _next_action(row),
            }
        )
    return items


def forecast_points():
    rows = sorted(forecast_rows(), key=lambda row: (row.get("forecast_date"), row.get("zone")))[-24:]
    points = []
    for row in rows:
        timestamp = _dt(row.get("forecast_date"))
        points.append(
            {
                "timestamp": timestamp.isoformat(),
                "actual": round(_float(row.get("actual_mw")), 2),
                "forecast": round(_float(row.get("forecast_mw")), 2),
                "lower90": round(_float(row.get("p10_mw")), 2),
                "upper90": round(_float(row.get("p90_mw")), 2),
                "lower99": round(_float(row.get("p10_mw")) * 0.94, 2),
                "upper99": round(_float(row.get("p90_mw")) * 1.06, 2),
            }
        )
    return points


def detector_health():
    forecasts = forecast_rows()
    alerts_by_model = Counter(row.get("model_version") or "Detector" for row in alert_rows())
    forecast_mape = mean([_float(row.get("mape_pct")) for row in forecasts[-500:]]) if forecasts else 0
    return [
        {"name": "Forecast models", "purpose": "Zone demand prediction", "status": "Healthy", "metric": f"MAPE {forecast_mape:.1f}%", "coverage": 100},
        {"name": "TheftDetect-v2.1", "purpose": "Theft and tamper alerts", "status": "Healthy", "metric": f"{alerts_by_model.get('TheftDetect-v2.1', 0)} alerts", "coverage": 94},
        {"name": "TheftDetect-v3.0", "purpose": "High-confidence anomalies", "status": "Healthy", "metric": f"{alerts_by_model.get('TheftDetect-v3.0', 0)} alerts", "coverage": 91},
        {"name": "Ensemble-v1", "purpose": "Combined detector score", "status": "Healthy", "metric": f"{alerts_by_model.get('Ensemble-v1', 0)} alerts", "coverage": 97},
        {"name": "Data quality scorer", "purpose": "Completeness and latency checks", "status": "Healthy", "metric": f"{len(dq_rows())} checks", "coverage": 100},
        {"name": "Topology monitor", "purpose": "Feeder load and outage risk", "status": "Watch", "metric": f"{len(topology_rows())} feeders", "coverage": 86},
    ]


def model_health():
    mape_by_model = defaultdict(list)
    for row in forecast_rows():
        mape_by_model[row.get("model_name")].append(_float(row.get("mape_pct")))

    items = []
    for model_name, values in sorted(mape_by_model.items()):
        drift = round(min(0.35, mean(values) / 35), 2)
        items.append(
            {
                "model": model_name,
                "version": "synthetic-dataset",
                "drift": drift,
                "status": "Watch" if drift > 0.18 else "Healthy",
                "lastTrained": "2024-12-31",
            }
        )
    items.append({"model": "Theft detector ensemble", "version": "dataset-v1", "drift": 0.14, "status": "Healthy", "lastTrained": "2024-12-31"})
    return items


def data_quality():
    by_zone = defaultdict(list)
    latest = {}
    for row in dq_rows():
        zone = row.get("zone")
        by_zone[zone].append(row)
        if zone not in latest or row.get("date", "") > latest[zone].get("date", ""):
            latest[zone] = row

    items = []
    for zone, rows in sorted(by_zone.items()):
        missing = mean([_float(row.get("missing_readings")) for row in rows])
        quality = mean([_float(row.get("quality_score")) for row in rows])
        items.append(
            {
                "source": zone,
                "freshness": latest[zone].get("date"),
                "missingPct": round(missing / 24 * 100, 1),
                "status": "OK" if quality >= 0.85 else "Audit",
            }
        )
    return items[:10]


def pipeline_layers():
    return [
        {"layer": "0", "name": "Dataset", "items": ["meters", "meter_readings", "grid_topology"], "status": f"{len(meters_rows())} meters"},
        {"layer": "1", "name": "Data Quality", "items": ["completeness", "latency", "duplicates"], "status": f"{len(dq_rows())} checks"},
        {"layer": "2A", "name": "Demand Forecast", "items": ["LSTM-v2", "XGBoost-v3", "Prophet-v1", "Ensemble-v4"], "status": f"{len(forecast_rows())} rows"},
        {"layer": "2B", "name": "Anomaly Detection", "items": ["TheftDetect-v2.1", "TheftDetect-v3.0", "Ensemble-v1"], "status": f"{len(alert_rows())} alerts"},
        {"layer": "3", "name": "Field Workflow", "items": ["audit_events", "inspector actions", "fines"], "status": f"{len(audit_rows())} events"},
    ]


def feeder_balance():
    points = []
    for row in sorted(topology_rows(), key=lambda item: _float(item.get("load_pct")), reverse=True)[:16]:
        capacity = _float(row.get("capacity_mva"))
        current = _float(row.get("current_load_mva"))
        loss_pct = max(0, 100 - (current / max(capacity, 1) * 100))
        points.append(
            {
                "timestamp": row.get("feeder_id"),
                "inputKwh": round(capacity * 1000, 2),
                "meteredKwh": round(current * 1000, 2),
                "lossPct": round(loss_pct, 2),
            }
        )
    return points


def topology_nodes():
    nodes = []
    for row in topology_rows()[:30]:
        substation_id = row.get("substation_id")
        feeder_id = row.get("feeder_id")
        risk = _risk_from_load(_float(row.get("load_pct")))
        if not any(node["id"] == substation_id for node in nodes):
            nodes.append({"id": substation_id, "label": substation_id, "type": "Substation", "parent": None, "risk": risk})
        nodes.append({"id": feeder_id, "label": feeder_id, "type": "Feeder", "parent": substation_id, "risk": risk})
    return nodes


def audit_events():
    rows = sorted(audit_rows(), key=lambda row: _dt(row.get("action_timestamp")), reverse=True)[:25]
    return [
        {
            "time": _dt(row.get("action_timestamp")).isoformat(),
            "event": row.get("action_type"),
            "actor": row.get("inspector_id"),
            "hash": row.get("audit_id"),
            "meterId": row.get("meter_id"),
            "outcome": row.get("outcome"),
        }
        for row in rows
    ]


def scenario_points(temperature_delta, industrial_multiplier, holiday):
    modifier = 1 + temperature_delta * 0.012 + (industrial_multiplier - 1) * 0.35 - (0.08 if holiday else 0)
    return [
        {
            **point,
            "scenario": round(point["forecast"] * modifier, 2),
            "deltaPct": round((modifier - 1) * 100, 1),
        }
        for point in forecast_points()
    ]
