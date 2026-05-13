import csv
import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from statistics import mean


DEFAULT_DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "bescom_dataset"
DATA_DIR = Path(os.environ.get("BESCOM_DATA_DIR", DEFAULT_DATA_DIR)).expanduser().resolve()
ALERT_STATUS_OVERRIDES = {}


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


@lru_cache(maxsize=None)
def feedback_rows():
    return _read_csv("alert_feedback.csv")


@lru_cache(maxsize=None)
def model_performance_rows():
    return _read_csv("model_performance_history.csv")


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
    if alert.get("recommended_action"):
        return alert.get("recommended_action")
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


def _meter_index():
    return {row.get("meter_id"): row for row in meters_rows()}


def _alert_index():
    return {row.get("alert_id"): row for row in alert_rows()}


def _severity_rank(risk):
    return {"Critical": 4, "High": 3, "Medium": 2, "Low": 1, "Normal": 0}.get(risk, 0)


def _alert_summary(row, meter=None):
    probability = _float(row.get("anomaly_score"))
    revenue_impact = round(
        _float(row.get("estimated_daily_loss_inr"), _float(row.get("estimated_loss_units")) * 8),
        2,
    )
    detector_count = _int(row.get("num_detectors_agreeing"), 1)
    modality = row.get("suspected_theft_modality") or row.get("anomaly_type") or "anomaly"
    consumer_type = meter.get("consumer_type", "consumer") if meter else "consumer"
    drop = _float(row.get("consumption_drop_pct"))
    summary = (
        f"Meter {row.get('meter_id')} ({row.get('zone')}, {consumer_type}) shows "
        f"{modality.replace('_', ' ')} signature with {drop:.1f}% consumption shift. "
        f"Estimated loss is INR {revenue_impact:,.0f}/day; {detector_count}/4 detectors agree."
    )
    return {
        "id": row.get("alert_id"),
        "meterId": row.get("meter_id"),
        "zone": row.get("zone"),
        "risk": row.get("severity") or "Medium",
        "status": ALERT_STATUS_OVERRIDES.get(row.get("alert_id"), row.get("status") or "Open"),
        "type": row.get("anomaly_type") or "Anomaly",
        "probability": probability,
        "urgencyScore": round(probability * max(1, revenue_impact) * 10, 2),
        "revenueImpact": revenue_impact,
        "detectors": [row.get("model_version") or "Detector", "VAE", "EIF", "GNN"],
        "detectorsAgreeing": detector_count,
        "detectedAt": _dt(row.get("alert_timestamp")).isoformat(),
        "summary": summary,
        "nextAction": _next_action(row),
        "reasonCode": row.get("alert_reason_code") or "ANOMALY_SCORE",
        "modality": modality,
    }


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
    feedback = feedback_rows()
    true_positive = sum(1 for row in feedback if row.get("feedback_type") == "true_positive")
    false_positive = sum(1 for row in feedback if row.get("feedback_type") == "false_positive")

    return {
        "metersMonitored": len(meters),
        "readsPerDay": len(readings),
        "openAlerts": len(open_alerts),
        "criticalAlerts": len(critical_alerts),
        "precisionAt50": round(true_positive / max(1, true_positive + false_positive), 2),
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

    loss_by_zone = defaultdict(list)
    feeder_count = Counter()
    for row in topology_rows():
        load_by_zone[row.get("zone")].append(_float(row.get("load_pct")))
        loss_by_zone[row.get("zone")].append(_float(row.get("feeder_loss_pct")))
        feeder_count[row.get("zone")] += 1
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
                "feederLossPct": round(mean(loss_by_zone.get(zone, [0])), 1),
                "loadPct": avg_load,
                "meterCount": len(zone_meters),
                "feederCount": feeder_count.get(zone, 0),
                "lat": round(mean(latitudes), 6),
                "lon": round(mean(longitudes), 6),
                "wardName": zone_meters[0].get("ward_name") if zone_meters else zone,
            }
        )
    return sorted(items, key=lambda row: (-_severity_rank(row["risk"]), -row["openAlerts"], row["name"]))


def alerts():
    meter_by_id = _meter_index()
    rows = sorted(alert_rows(), key=lambda row: _dt(row.get("alert_timestamp")), reverse=True)
    return [_alert_summary(row, meter_by_id.get(row.get("meter_id"))) for row in rows[:75]]


def alert_detail(alert_id):
    row = _alert_index().get(alert_id)
    if not row:
        return None
    meter = _meter_index().get(row.get("meter_id"), {})
    base = _alert_summary(row, meter)
    return {
        **base,
        "meter": meter_profile(row.get("meter_id")),
        "confidence": {
            "totalDetectors": 4,
            "detectorsAgreeing": _int(row.get("num_detectors_agreeing"), 1),
            "consensusLabel": "High confidence" if _int(row.get("num_detectors_agreeing"), 1) >= 3 else "Needs analyst review",
            "breakdown": [
                {"detector": "VAE", "score": _float(row.get("detector_vae_score")), "status": "flagged" if _float(row.get("detector_vae_score")) >= 0.65 else "watch"},
                {"detector": "EIF", "score": _float(row.get("detector_eif_score")), "status": "flagged" if _float(row.get("detector_eif_score")) >= 0.65 else "watch"},
                {"detector": "BOCPD", "score": None, "status": "changepoint" if row.get("detector_bocpd_flag") == "True" else "no_changepoint"},
                {"detector": "GNN", "score": _float(row.get("detector_gnn_score")), "status": "flagged" if _float(row.get("detector_gnn_score")) >= 0.65 else "watch"},
            ],
        },
        "shap": [
            {"name": row.get("shap_feature_1_name"), "value": _float(row.get("shap_feature_1_value"))},
            {"name": row.get("shap_feature_2_name"), "value": _float(row.get("shap_feature_2_value"))},
            {"name": row.get("shap_feature_3_name"), "value": _float(row.get("shap_feature_3_value"))},
        ],
        "feedback": [item for item in feedback_rows() if item.get("alert_id") == alert_id],
    }


def update_alert_status(alert_id, action):
    row = _alert_index().get(alert_id)
    if not row:
        return None
    status_map = {
        "assign": "Assigned",
        "snooze": "Snoozed",
        "close": "Resolved",
        "reopen": "Open",
    }
    status = status_map.get(action)
    if not status:
        return None
    ALERT_STATUS_OVERRIDES[alert_id] = status
    meter = _meter_index().get(row.get("meter_id"), {})
    return _alert_summary(row, meter)


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
                "lower99": round(_float(row.get("p5_mw"), _float(row.get("p10_mw")) * 0.94), 2),
                "upper99": round(_float(row.get("p95_mw"), _float(row.get("p90_mw")) * 1.06), 2),
                "p50": round(_float(row.get("p50_mw"), _float(row.get("forecast_mw"))), 2),
                "model": row.get("model_name"),
                "confidence": _float(row.get("confidence_level"), 0.9),
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
    from app.services.ml_runtime import runtime_status

    latest = {}
    for row in model_performance_rows():
        key = (row.get("model_name"), row.get("metric_type"))
        if key not in latest or row.get("evaluation_date", "") > latest[key].get("evaluation_date", ""):
            latest[key] = row

    by_model = defaultdict(dict)
    for (model_name, metric_type), row in latest.items():
        by_model[model_name][metric_type] = row

    items = []
    for model_name, metrics in sorted(by_model.items()):
        representative = next(iter(metrics.values()))
        drift = _float(representative.get("feature_drift_psi"))
        items.append(
            {
                "model": model_name,
                "version": representative.get("model_version"),
                "drift": round(drift, 3),
                "status": "Critical" if drift > 0.25 else ("Watch" if drift > 0.15 else "Healthy"),
                "lastTrained": representative.get("training_date"),
                "mape": _float(metrics.get("mape_pct", {}).get("metric_value")),
                "precision": _float(metrics.get("precision", {}).get("metric_value")),
                "recall": _float(metrics.get("recall", {}).get("metric_value")),
                "f1": _float(metrics.get("f1_score", {}).get("metric_value")),
            }
        )
    runtime = runtime_status()
    forecasting = runtime.get("forecasting", {})
    anomaly = runtime.get("anomalyDetection", {})
    if forecasting.get("status") == "trained":
        items.insert(
            0,
            {
                "model": forecasting.get("model", "Synthetic forecaster"),
                "version": "trained-artifact",
                "drift": round(float(forecasting.get("mape", 0.0)), 3),
                "status": "Healthy" if float(forecasting.get("mape", 1.0)) <= 0.12 else "Watch",
                "lastTrained": runtime.get("generatedAt"),
                "mape": forecasting.get("mape", 0.0),
                "precision": 0.0,
                "recall": 0.0,
                "f1": 0.0,
            },
        )
    if anomaly.get("status") == "trained":
        blended = anomaly.get("blended", {})
        items.insert(
            0,
            {
                "model": anomaly.get("model", "Synthetic anomaly ensemble"),
                "version": "trained-artifact",
                "drift": 0.0,
                "status": "Healthy" if float(blended.get("f1", 0.0)) >= 0.7 else "Watch",
                "lastTrained": runtime.get("generatedAt"),
                "mape": 0.0,
                "precision": blended.get("precision", 0.0),
                "recall": blended.get("recall", 0.0),
                "f1": blended.get("f1", 0.0),
            },
        )
    return items


def drift_history():
    rows = sorted(model_performance_rows(), key=lambda row: (row.get("evaluation_date"), row.get("model_name")))
    return [
        {
            "date": row.get("evaluation_date"),
            "model": row.get("model_name"),
            "version": row.get("model_version"),
            "metric": row.get("metric_type"),
            "value": _float(row.get("metric_value")),
            "psi": _float(row.get("feature_drift_psi")),
            "shift": row.get("distribution_shift_detected") == "True",
            "notes": row.get("notes"),
        }
        for row in rows
        if row.get("metric_type") in {"mape_pct", "f1_score", "precision", "recall", "auc_roc"}
    ][-250:]


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
                "qualityScore": round(quality, 3),
                "status": "OK" if quality >= 0.85 else "Audit",
            }
        )
    return items[:10]


def data_quality_trend():
    by_date = defaultdict(list)
    drift_by_date = defaultdict(list)
    for row in dq_rows():
        by_date[row.get("date")].append(row)
    for row in model_performance_rows():
        if row.get("metric_type") == "mape_pct":
            drift_by_date[row.get("evaluation_date")].append(_float(row.get("feature_drift_psi")))
    trend = []
    for date, rows in sorted(by_date.items())[-90:]:
        psi = mean(drift_by_date.get(date, [0]))
        trend.append(
            {
                "date": date,
                "quality": round(mean([_float(row.get("quality_score")) for row in rows]), 3),
                "completeness": round(mean([_float(row.get("completeness_pct")) for row in rows]), 2),
                "missing": round(mean([_float(row.get("missing_readings")) for row in rows]), 2),
                "psi": round(psi, 3),
                "status": "DRIFT_RISK" if psi > 0.25 else "OK",
            }
        )
    return trend


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
                "feederId": row.get("feeder_id"),
                "zone": row.get("zone"),
                "inputKwh": round(capacity * 1000, 2),
                "meteredKwh": round(current * 1000, 2),
                "lossPct": round(_float(row.get("feeder_loss_pct"), loss_pct), 2),
                "nonTechnicalLossPct": _float(row.get("estimated_nontechnical_loss_pct")),
                "theftAlertsYtd": _int(row.get("num_theft_alerts_ytd")),
            }
        )
    return points


def topology_graph():
    nodes = []
    edges = []
    seen = set()
    for row in topology_rows()[:30]:
        substation_id = row.get("substation_id")
        feeder_id = row.get("feeder_id")
        risk = _risk_from_load(_float(row.get("load_pct")))
        if substation_id not in seen:
            nodes.append({"id": substation_id, "label": substation_id, "type": "Substation", "parent": None, "risk": risk, "loadPct": _float(row.get("load_pct"))})
            seen.add(substation_id)
        nodes.append({"id": feeder_id, "label": feeder_id, "type": "Feeder", "parent": substation_id, "risk": risk, "loadPct": _float(row.get("load_pct")), "lossPct": _float(row.get("feeder_loss_pct")), "meterCount": _int(row.get("meter_count"))})
        edges.append({"source": substation_id, "target": feeder_id, "weight": _int(row.get("meter_count"))})
    return {"nodes": nodes, "edges": edges}


def topology_nodes():
    return topology_graph()["nodes"]


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


def revenue_trend():
    daily = defaultdict(lambda: {"recovery": 0.0, "meters": set(), "actions": 0})
    by_zone = defaultdict(float)
    by_inspector = defaultdict(float)
    for row in audit_rows():
        date = _dt(row.get("action_timestamp")).date().isoformat()
        fine = _float(row.get("fine_inr"))
        daily[date]["recovery"] += fine
        daily[date]["meters"].add(row.get("meter_id"))
        daily[date]["actions"] += 1
        by_zone[row.get("zone")] += fine
        by_inspector[row.get("inspector_id")] += fine
    cumulative = 0.0
    trend = []
    for date, item in sorted(daily.items())[-120:]:
        cumulative += item["recovery"]
        trend.append({"date": date, "dailyRecovery": round(item["recovery"], 2), "cumulativeRecovery": round(cumulative, 2), "metersActioned": len(item["meters"]), "actions": item["actions"]})
    return {
        "trend": trend,
        "byZone": [{"name": zone, "value": round(value, 2)} for zone, value in sorted(by_zone.items(), key=lambda pair: pair[1], reverse=True)[:10]],
        "byInspector": [{"name": inspector, "value": round(value, 2)} for inspector, value in sorted(by_inspector.items(), key=lambda pair: pair[1], reverse=True)[:10]],
    }


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


def meter_profile(meter_id):
    meter = _meter_index().get(meter_id)
    if not meter:
        return None
    alerts_for_meter = [item for item in alerts() if item["meterId"] == meter_id][:8]
    audits_for_meter = [
        {
            "time": _dt(row.get("action_timestamp")).isoformat(),
            "action": row.get("action_type"),
            "inspector": row.get("inspector_id"),
            "outcome": row.get("outcome"),
            "remarks": row.get("remarks"),
        }
        for row in sorted(audit_rows(), key=lambda row: _dt(row.get("action_timestamp")), reverse=True)
        if row.get("meter_id") == meter_id
    ][:8]
    recent = [row for row in reading_rows() if row.get("meter_id") == meter_id][-240:]
    heatmap_cells = defaultdict(lambda: {"kwh": [], "z": []})
    for row in recent[-240:]:
        key = (
            _int(row.get("consumption_heatmap_day")),
            _int(row.get("consumption_heatmap_hour")),
        )
        heatmap_cells[key]["kwh"].append(_float(row.get("kwh")))
        heatmap_cells[key]["z"].append(_float(row.get("z_score_vs_peer")))
    heatmap = [
        {
            "day": day,
            "hour": hour,
            "kwh": round(mean(values["kwh"]), 3),
            "zScore": round(mean(values["z"]), 3),
        }
        for (day, hour), values in sorted(heatmap_cells.items())
    ]
    peer = [
        {
            "timestamp": _dt(row.get("timestamp")).isoformat(),
            "meterKwh": round(_float(row.get("kwh")), 3),
            "peerMean": round(_float(row.get("peer_group_mean_kwh")), 3),
            "peerUpper": round(_float(row.get("peer_group_mean_kwh")) + _float(row.get("peer_group_std_kwh")), 3),
            "peerLower": round(max(0, _float(row.get("peer_group_mean_kwh")) - _float(row.get("peer_group_std_kwh"))), 3),
        }
        for row in recent[-48:]
    ]
    return {
        "meterId": meter.get("meter_id"),
        "consumerType": meter.get("consumer_type"),
        "zone": meter.get("zone"),
        "substationId": meter.get("substation_id"),
        "feederId": meter.get("feeder_id"),
        "tariffCode": meter.get("tariff_code"),
        "phase": meter.get("phase"),
        "contractedKw": _float(meter.get("contracted_kw")),
        "installDate": meter.get("install_date"),
        "latitude": _float(meter.get("latitude")),
        "longitude": _float(meter.get("longitude")),
        "address": meter.get("meter_address"),
        "wardName": meter.get("ward_name"),
        "communicationProtocol": meter.get("communication_protocol"),
        "firmwareVersion": meter.get("firmware_version"),
        "meterMake": meter.get("meter_make"),
        "active": meter.get("active") == "True",
        "mapsUrl": f"https://www.google.com/maps/search/?api=1&query={meter.get('latitude')},{meter.get('longitude')}",
        "heatmap": heatmap,
        "peer": peer,
        "alerts": alerts_for_meter,
        "audit": audits_for_meter,
    }


def meter_list(limit=50):
    return [
        {
            "meterId": row.get("meter_id"),
            "consumerType": row.get("consumer_type"),
            "zone": row.get("zone"),
            "feederId": row.get("feeder_id"),
            "tariffCode": row.get("tariff_code"),
            "address": row.get("meter_address"),
            "active": row.get("active") == "True",
        }
        for row in meters_rows()[:limit]
    ]


def zone_map():
    features = []
    for zone in zones():
        lon = zone["lon"]
        lat = zone["lat"]
        size = 0.018
        features.append(
            {
                "type": "Feature",
                "id": zone["name"],
                "properties": {
                    "zone": zone["name"],
                    "risk_level": zone["risk"],
                    "load_pct": zone["loadPct"],
                    "open_alerts": zone["openAlerts"],
                    "loss_pct": zone["feederLossPct"],
                    "meter_count": zone["meterCount"],
                    "feeder_count": zone["feederCount"],
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[lon - size, lat - size], [lon + size, lat - size], [lon + size, lat + size], [lon - size, lat + size], [lon - size, lat - size]]],
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}
