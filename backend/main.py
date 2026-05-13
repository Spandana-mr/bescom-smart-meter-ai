from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.services.mock_data import (
    alerts,
    alert_detail,
    audit_events,
    data_quality,
    data_quality_trend,
    detector_health,
    drift_history,
    feeder_balance,
    forecast_points,
    kpis,
    meter_list,
    meter_profile,
    model_health,
    pipeline_layers,
    revenue_trend,
    scenario_points,
    topology_graph,
    topology_nodes,
    update_alert_status,
    zone_map,
    zones,
)
from app.services.ml_runtime import (
    anomaly_rankings,
    anomaly_scores_for_meter,
    forecast_preview,
    runtime_status,
)

app = FastAPI(
    title="BESCOM Smart Meter AI API",
    description="Operational API for demand forecasting, theft alerts, model health, and grid monitoring.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {
        "service": "BESCOM Smart Meter AI API",
        "status": "operational",
        "docs": "/docs",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/v1/health")
async def health():
    return {
        "status": "healthy",
        "api": "online",
        "database": "sample-data",
        "model_registry": "mock-loaded",
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/v1/dashboard/kpis")
async def get_kpis():
    return kpis()


@app.get("/api/v1/dashboard/overview")
async def get_overview():
    return {
        "kpis": kpis(),
        "zones": zones(),
        "alerts": alerts()[:6],
        "forecast": forecast_points(),
        "detectors": detector_health(),
        "pipeline": pipeline_layers(),
        "data_quality": data_quality(),
    }


@app.get("/api/v1/alerts")
async def list_alerts(
    risk: Literal["all", "critical", "high", "medium", "low"] = "all",
    status: Literal["all", "open", "assigned", "suppressed", "closed"] = "all",
):
    items = alerts()
    if risk != "all":
        items = [item for item in items if item["risk"].lower() == risk]
    if status != "all":
        items = [item for item in items if item["status"].lower() == status]
    return {"total": len(items), "items": items}


@app.get("/api/v1/alerts/{alert_id}")
async def get_alert(alert_id: str):
    item = alert_detail(alert_id)
    if item:
        return item
    raise HTTPException(status_code=404, detail="Alert not found")


@app.post("/api/v1/alerts/{alert_id}/feedback")
async def submit_alert_feedback(alert_id: str, payload: dict = Body(...)):
    item = alert_detail(alert_id)
    if not item:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {
        "saved": True,
        "feedbackId": f"FBK-UI-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
        "alertId": alert_id,
        "payload": payload,
        "message": "Feedback captured for the next model retraining batch.",
    }


@app.post("/api/v1/alerts/{alert_id}/action")
async def update_alert_action(alert_id: str, payload: dict = Body(...)):
    item = update_alert_status(alert_id, str(payload.get("action", "")).lower())
    if not item:
        raise HTTPException(status_code=404, detail="Alert action not available")
    return {"saved": True, "item": item}


@app.get("/api/v1/zones")
async def list_zones():
    return zones()


@app.get("/api/v1/zones/map")
async def get_zone_map():
    return zone_map()


@app.get("/api/v1/forecast")
async def get_forecast(horizon: Literal["24h", "7d"] = "24h"):
    points = forecast_points()
    if horizon == "7d":
        base = points[-1]["timestamp"]
        expanded = []
        for day in range(7):
            for point in points[::4]:
                expanded.append(
                    {
                        **point,
                        "timestamp": (
                            datetime.fromisoformat(base.replace("Z", "+00:00"))
                            + timedelta(days=day, hours=len(expanded) % 24)
                        ).isoformat(),
                    }
                )
        return expanded
    return points


@app.get("/api/v1/feeders/balance")
async def get_feeder_balance():
    return feeder_balance()


@app.get("/api/v1/feeders/topology")
async def get_topology():
    return topology_nodes()


@app.get("/api/v1/feeders/graph")
async def get_topology_graph():
    return topology_graph()


@app.get("/api/v1/models/health")
async def get_model_health():
    return model_health()


@app.get("/api/v1/ml/status")
async def get_ml_runtime_status():
    return runtime_status()


@app.get("/api/v1/ml/forecast-preview")
async def get_ml_forecast_preview(limit: int = 48):
    return {"items": forecast_preview(limit)}


@app.get("/api/v1/ml/anomaly-rankings")
async def get_ml_anomaly_rankings(limit: int = 50):
    return {"items": anomaly_rankings(limit)}


@app.get("/api/v1/ml/meters/{meter_id}/anomaly-scores")
async def get_ml_meter_anomaly_scores(meter_id: str):
    return {"items": anomaly_scores_for_meter(meter_id)}


@app.get("/api/v1/models/drift-history")
async def get_model_drift_history():
    return drift_history()


@app.get("/api/v1/data-quality")
async def get_data_quality():
    return data_quality()


@app.get("/api/v1/data-quality/trend")
async def get_data_quality_trend():
    return data_quality_trend()


@app.get("/api/v1/pipeline")
async def get_pipeline():
    return pipeline_layers()


@app.get("/api/v1/audit")
async def get_audit():
    return audit_events()


@app.get("/api/v1/revenue/trend")
async def get_revenue_trend():
    return revenue_trend()


@app.get("/api/v1/meters")
async def get_meters(limit: int = 50):
    return {"items": meter_list(limit)}


@app.get("/api/v1/meters/{meter_id}/detail")
async def get_meter_detail(meter_id: str):
    item = meter_profile(meter_id)
    if item:
        return item
    raise HTTPException(status_code=404, detail="Meter not found")


@app.get("/api/v1/scenario")
async def get_scenario(
    temperature_delta: float = 0,
    industrial_multiplier: float = 1,
    holiday: bool = False,
):
    return scenario_points(temperature_delta, industrial_multiplier, holiday)
