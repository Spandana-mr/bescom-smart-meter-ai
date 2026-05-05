"""
backend/models/schemas.py

Pydantic v2 response models for all API endpoints.
"""

from typing import Any, Optional
from datetime import datetime
from pydantic import BaseModel, Field


# ─── Common ───────────────────────────────────────────────────────────────────

class ErrorResponse(BaseModel):
    detail: str

class PaginatedResponse(BaseModel):
    total:   int
    page:    int
    size:    int
    items:   list[Any]


# ─── Alerts ───────────────────────────────────────────────────────────────────

class SHAPContribution(BaseModel):
    feature:    str
    value:      float
    shap_value: float
    direction:  str   # "increased" | "decreased"

class AlertSummary(BaseModel):
    alert_id:                    str
    meter_id:                    str
    zone:                        str
    risk_level:                  str
    anomaly_type:                str
    theft_probability:           float
    urgency_score:               float
    estimated_revenue_impact_inr: float
    detectors_triggered:         list[str]
    detected_at:                 datetime
    status:                      str
    nl_summary:                  Optional[str] = None

class AlertDetail(AlertSummary):
    consumer_type:               str
    tariff_category:             str
    latitude:                    Optional[float]
    longitude:                   Optional[float]
    vae_score:                   Optional[float]
    eif_score:                   Optional[float]
    bocpd_detected:              bool
    gnn_node_score:              Optional[float]
    peer_z_score:                Optional[float]
    shap_contributions:          list[SHAPContribution]
    model_version:               str

class AlertFeedbackRequest(BaseModel):
    outcome:     str = Field(..., description="theft_confirmed|meter_fault|no_issue|pending")
    reason_code: Optional[str] = None
    notes:       Optional[str] = None

class DispatchRouteRequest(BaseModel):
    alert_ids: list[str] = Field(..., min_length=1, max_length=50)

class DispatchRouteStop(BaseModel):
    alert_id:      str
    meter_id:      str
    zone:          str
    latitude:      float
    longitude:     float
    risk_level:    str
    address:       str
    urgency_score: float

class DispatchRouteResponse(BaseModel):
    stops:                list[DispatchRouteStop]
    total_distance_km:    float
    estimated_duration_min: int
    route_polyline:       Optional[str] = None  # Google Maps encoded polyline

class SoftWarningResponse(BaseModel):
    meter_id: str
    subject:  str
    body:     str


# ─── Meters ───────────────────────────────────────────────────────────────────

class MeterProfile(BaseModel):
    meter_id:            str
    consumer_id:         str
    consumer_type:       str
    tariff_category:     str
    contract_demand_kva: Optional[float]
    meter_type:          str
    zone:                str
    feeder_id:           str
    transformer_id:      str
    latitude:            Optional[float]
    longitude:           Optional[float]
    address:             Optional[str]
    peer_cluster_id:     Optional[int]
    is_active:           bool

class HeatmapDataPoint(BaseModel):
    date:  str   # YYYY-MM-DD
    hour:  int   # 0-23
    value: float # kWh

class PeerComparisonPoint(BaseModel):
    timestamp:    datetime
    meter_kwh:    float
    peer_mean:    float
    peer_upper:   float   # mean + 1σ
    peer_lower:   float   # mean - 1σ

class MeterForecast(BaseModel):
    timestamp:      datetime
    forecast_kwh:   float
    lower_bound_90: float
    upper_bound_90: float
    lower_bound_99: float
    upper_bound_99: float
    model_name:     str

class ChangePoint(BaseModel):
    timestamp:   datetime
    probability: float
    has_calendar_explanation: bool
    calendar_note: Optional[str]

class NBEATSDecomposition(BaseModel):
    timestamp:   datetime
    actual_kwh:  Optional[float]
    trend:       float
    seasonality: float
    residual:    float
    event_label: Optional[str]   # "Ugadi", "Temperature spike", etc.


# ─── Zones ────────────────────────────────────────────────────────────────────

class ZoneRiskSummary(BaseModel):
    zone:              str
    risk_level:        str
    open_alerts:       int
    critical_alerts:   int
    high_alerts:       int
    transformer_load_pct: float
    forecast_peak_kwh: float
    upstream_loss_pct: float
    centroid_lat:      float
    centroid_lon:      float


# ─── Feeders ──────────────────────────────────────────────────────────────────

class FeederBalancePoint(BaseModel):
    timestamp:       datetime
    input_kwh:       float
    metered_kwh:     float
    billed_kwh:      Optional[float]
    loss_kwh:        float
    loss_pct:        float
    kirchhoff_ok:    bool   # False if input < sum(metered)

class FeederTopologyNode(BaseModel):
    id:           str
    type:         str  # "substation" | "feeder" | "transformer" | "meter"
    label:        str
    loss_pct:     Optional[float]
    risk_level:   Optional[str]
    parent_id:    Optional[str]
    lat:          Optional[float]
    lon:          Optional[float]


# ─── Scenario ────────────────────────────────────────────────────────────────

class ScenarioRequest(BaseModel):
    zone_id:                  str
    temperature_override_c:   Optional[float] = None
    is_holiday:               bool = False
    industrial_load_multiplier: float = Field(default=1.0, ge=0.1, le=5.0)
    target_date:              Optional[str] = None  # YYYY-MM-DD

class ScenarioPoint(BaseModel):
    timestamp:        datetime
    baseline_kwh:     float
    scenario_kwh:     float
    lower_bound:      float
    upper_bound:      float
    delta_pct:        float
    transformer_loading_pct: float

class ScenarioResponse(BaseModel):
    zone_id:        str
    scenario_label: str
    points:         list[ScenarioPoint]
    peak_delta_pct: float
    max_transformer_loading_pct: float
    risk_assessment: str


# ─── Reports ──────────────────────────────────────────────────────────────────

class MonthlyReportRequest(BaseModel):
    year:  int
    month: int   # 1-12
    zones: Optional[list[str]] = None  # None = all zones


# ─── Health ───────────────────────────────────────────────────────────────────

class ModelHealthItem(BaseModel):
    model_name:      str
    version:         str
    last_trained:    datetime
    mape_current:    Optional[float]
    f1_current:      Optional[float]
    drift_psi_score: float
    needs_retrain:   bool
    status:          str  # "healthy" | "degraded" | "critical"

class DataQualityItem(BaseModel):
    feeder_id:        str
    zone:             str
    missing_pct_7d:   float
    missing_pct_30d:  float
    last_reading_at:  datetime
    status:           str  # "ok" | "warning" | "error"


# ─── KPIs ─────────────────────────────────────────────────────────────────────

class KPISummary(BaseModel):
    alerts_today:            int
    alerts_open:             int
    precision_7d:            Optional[float]
    f1_score_30d:            Optional[float]
    revenue_recovered_mtd:   float
    revenue_recovered_ytd:   float
    false_discovery_rate_7d: Optional[float]
    meters_monitored:        int
    last_updated:            datetime
