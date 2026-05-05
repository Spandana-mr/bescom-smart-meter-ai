from datetime import datetime, timedelta, timezone
from math import cos, sin, pi


def _now():
    return datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)


def kpis():
    return {
        "metersMonitored": 2_000_000,
        "readsPerDay": 192_000_000,
        "openAlerts": 148,
        "criticalAlerts": 12,
        "precisionAt50": 0.78,
        "forecastMape": 0.041,
        "revenueAtRisk": 18_750_000,
        "recoveredMtd": 6_420_000,
        "lastUpdated": _now().isoformat(),
    }


def zones():
    return [
        {"name": "Indiranagar", "risk": "Critical", "openAlerts": 31, "lossPct": 10.8, "loadPct": 93, "lat": 12.9784, "lon": 77.6408},
        {"name": "Rajajinagar", "risk": "High", "openAlerts": 24, "lossPct": 8.7, "loadPct": 86, "lat": 12.9915, "lon": 77.5568},
        {"name": "Jayanagar", "risk": "Medium", "openAlerts": 18, "lossPct": 5.9, "loadPct": 74, "lat": 12.9299, "lon": 77.5933},
        {"name": "Whitefield", "risk": "High", "openAlerts": 27, "lossPct": 7.6, "loadPct": 82, "lat": 12.9698, "lon": 77.7500},
        {"name": "Yelahanka", "risk": "Normal", "openAlerts": 8, "lossPct": 2.8, "loadPct": 61, "lat": 13.1007, "lon": 77.5963},
    ]


def alerts():
    base = _now()
    return [
        {
            "id": "ALT-24051",
            "meterId": "BES-4872193",
            "zone": "Indiranagar",
            "risk": "Critical",
            "status": "Open",
            "type": "Bypass tampering",
            "probability": 0.94,
            "urgencyScore": 94120,
            "revenueImpact": 382000,
            "detectors": ["VAE", "EIF", "BOCPD", "Peer"],
            "detectedAt": (base - timedelta(hours=2)).isoformat(),
            "summary": "Sharp step-down in recorded kWh with normal feeder input and strong peer deviation.",
            "nextAction": "Physical inspection within 24 hours",
        },
        {
            "id": "ALT-24052",
            "meterId": "BES-1189024",
            "zone": "Whitefield",
            "risk": "High",
            "status": "Assigned",
            "type": "Illegal extension",
            "probability": 0.87,
            "urgencyScore": 71240,
            "revenueImpact": 291000,
            "detectors": ["GNN", "Feeder balance", "Peer"],
            "detectedAt": (base - timedelta(hours=4)).isoformat(),
            "summary": "Feeder balance deficit concentrated around one transformer cluster.",
            "nextAction": "Route to field team",
        },
        {
            "id": "ALT-24053",
            "meterId": "BES-9301441",
            "zone": "Rajajinagar",
            "risk": "High",
            "status": "Open",
            "type": "Meter slowdown",
            "probability": 0.82,
            "urgencyScore": 58840,
            "revenueImpact": 196000,
            "detectors": ["EIF", "Peer", "SHAP"],
            "detectedAt": (base - timedelta(hours=7)).isoformat(),
            "summary": "Thirty-day under-reading against commercial peer group.",
            "nextAction": "Inspect seals and calibration",
        },
        {
            "id": "ALT-24054",
            "meterId": "BES-6657810",
            "zone": "Jayanagar",
            "risk": "Medium",
            "status": "Suppressed",
            "type": "Consumption drop",
            "probability": 0.61,
            "urgencyScore": 21410,
            "revenueImpact": 74000,
            "detectors": ["BOCPD", "DoWhy"],
            "detectedAt": (base - timedelta(hours=9)).isoformat(),
            "summary": "Drop partially explained by holiday and rainfall. Held for monitoring.",
            "nextAction": "Review after 7 days",
        },
        {
            "id": "ALT-24055",
            "meterId": "BES-5549012",
            "zone": "Indiranagar",
            "risk": "Critical",
            "status": "Open",
            "type": "Phase reversal",
            "probability": 0.91,
            "urgencyScore": 87300,
            "revenueImpact": 336000,
            "detectors": ["VAE", "Physics", "SHAP"],
            "detectedAt": (base - timedelta(hours=11)).isoformat(),
            "summary": "Power factor and phase telemetry violate physical expectation.",
            "nextAction": "Immediate wiring inspection",
        },
        {
            "id": "ALT-24056",
            "meterId": "BES-7734028",
            "zone": "Yelahanka",
            "risk": "Low",
            "status": "Open",
            "type": "Flatline",
            "probability": 0.43,
            "urgencyScore": 9040,
            "revenueImpact": 28000,
            "detectors": ["VAE"],
            "detectedAt": (base - timedelta(hours=14)).isoformat(),
            "summary": "Eight consecutive low-variance intervals; communication status remains OK.",
            "nextAction": "Send soft notification",
        },
    ]


def forecast_points():
    base = _now()
    points = []
    for i in range(24):
        demand = 42 + 7 * sin((i / 24) * 2 * pi - 0.7) + (4 if 18 <= i <= 21 else 0)
        points.append(
            {
                "timestamp": (base + timedelta(hours=i)).isoformat(),
                "actual": round(demand - 1.8 + cos(i), 2) if i < 8 else None,
                "forecast": round(demand, 2),
                "lower90": round(demand * 0.91, 2),
                "upper90": round(demand * 1.09, 2),
                "lower99": round(demand * 0.84, 2),
                "upper99": round(demand * 1.16, 2),
            }
        )
    return points


def detector_health():
    return [
        {"name": "LightGBM", "purpose": "Tabular demand forecast", "status": "Healthy", "metric": "MAPE 4.1%", "coverage": 98},
        {"name": "VAE", "purpose": "Probabilistic anomalies", "status": "Healthy", "metric": "AUC 0.84", "coverage": 91},
        {"name": "EIF", "purpose": "Daily theft vectors", "status": "Healthy", "metric": "F1 0.72", "coverage": 96},
        {"name": "BOCPD", "purpose": "Streaming changepoints", "status": "Watch", "metric": "FDR 24%", "coverage": 89},
        {"name": "GNN", "purpose": "Topology loss detection", "status": "Auditing", "metric": "Topology 83%", "coverage": 63},
        {"name": "DoWhy", "purpose": "False positive filter", "status": "Healthy", "metric": "FP -27%", "coverage": 76},
    ]


def model_health():
    return [
        {"model": "LSTM Attention", "version": "1.2.0", "drift": 0.11, "status": "Healthy", "lastTrained": "2026-04-28"},
        {"model": "LightGBM Quantile", "version": "2.0.3", "drift": 0.08, "status": "Healthy", "lastTrained": "2026-05-01"},
        {"model": "TFT", "version": "0.9.4", "drift": 0.19, "status": "Watch", "lastTrained": "2026-04-20"},
        {"model": "MeterVAE", "version": "1.4.1", "drift": 0.14, "status": "Healthy", "lastTrained": "2026-04-30"},
        {"model": "Meta-classifier", "version": "1.1.8", "drift": 0.22, "status": "Retrain queued", "lastTrained": "2026-04-18"},
    ]


def data_quality():
    return [
        {"source": "meter.raw", "freshness": "4 min", "missingPct": 1.8, "status": "OK"},
        {"source": "feeder.telemetry", "freshness": "6 min", "missingPct": 2.6, "status": "OK"},
        {"source": "weather.events", "freshness": "19 min", "missingPct": 0.4, "status": "OK"},
        {"source": "inspection_records", "freshness": "2 hr", "missingPct": 0.0, "status": "OK"},
        {"source": "grid_topology", "freshness": "1 day", "missingPct": 17.0, "status": "Audit"},
    ]


def pipeline_layers():
    return [
        {"layer": "0", "name": "Ingestion", "items": ["AMI Head-End", "SCADA", "Weather API"], "status": "Streaming"},
        {"layer": "1", "name": "Preprocessing", "items": ["Imputation", "Feature engineering", "Peer clusters"], "status": "30 min SLA"},
        {"layer": "2A", "name": "Demand Forecast", "items": ["LSTM", "LightGBM", "TFT", "N-BEATS", "MAPIE"], "status": "Online"},
        {"layer": "2B", "name": "Theft Detection", "items": ["VAE", "EIF", "BOCPD", "GNN", "Meta-classifier"], "status": "Online"},
        {"layer": "3", "name": "Explainability", "items": ["SHAP", "Template NLG", "Audit log"], "status": "Immutable"},
    ]


def feeder_balance():
    base = _now()
    return [
        {
            "timestamp": (base - timedelta(hours=i)).isoformat(),
            "inputKwh": 1880 - i * 12,
            "meteredKwh": 1710 - i * 11,
            "lossPct": round(7.4 + sin(i / 2) * 1.6, 2),
        }
        for i in reversed(range(16))
    ]


def topology_nodes():
    return [
        {"id": "SS-04", "label": "Indiranagar Substation", "type": "Substation", "parent": None, "risk": "High"},
        {"id": "FD-21", "label": "Feeder 21", "type": "Feeder", "parent": "SS-04", "risk": "Critical"},
        {"id": "DT-118", "label": "Transformer 118", "type": "Transformer", "parent": "FD-21", "risk": "Critical"},
        {"id": "BES-4872193", "label": "BES-4872193", "type": "Meter", "parent": "DT-118", "risk": "Critical"},
        {"id": "BES-5549012", "label": "BES-5549012", "type": "Meter", "parent": "DT-118", "risk": "Critical"},
    ]


def audit_events():
    base = _now()
    return [
        {"time": (base - timedelta(minutes=14)).isoformat(), "event": "alert_created", "actor": "meta-classifier", "hash": "7cc9a88f"},
        {"time": (base - timedelta(minutes=27)).isoformat(), "event": "shap_summary_written", "actor": "explainability", "hash": "a21f7d44"},
        {"time": (base - timedelta(minutes=42)).isoformat(), "event": "model_inference", "actor": "LightGBM v2.0.3", "hash": "11a90bc1"},
        {"time": (base - timedelta(minutes=66)).isoformat(), "event": "analyst_feedback", "actor": "analyst-104", "hash": "94eb3172"},
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
