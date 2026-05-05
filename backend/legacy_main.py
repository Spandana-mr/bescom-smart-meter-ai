"""
backend/main.py

BESCOM Smart Meter AI — FastAPI Application Entry Point.
Async REST API. All endpoints require JWT auth (Keycloak).
"""

import os
from contextlib import asynccontextmanager
from loguru import logger
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from routers import alerts, meters, zones, feeders, scenario, reports, health
from models.schemas import ErrorResponse
from services.model_registry import ModelRegistry


# ─── Lifespan (startup / shutdown) ────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("BESCOM API starting up...")

    # Load ML models into memory at startup
    app.state.model_registry = ModelRegistry()
    await app.state.model_registry.load_all()
    logger.info("✓ ML models loaded")

    yield  # Application runs here

    logger.info("BESCOM API shutting down...")
    await app.state.model_registry.unload_all()


# ─── App Initialization ───────────────────────────────────────────────────────

app = FastAPI(
    title="BESCOM Smart Meter AI API",
    description=(
        "Electricity theft detection and demand forecasting API. "
        "Covers 2M+ smart meters at 15-minute granularity across Bangalore."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ─── Middleware ───────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)

# ─── Exception Handlers ───────────────────────────────────────────────────────

@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})

# ─── Routers ──────────────────────────────────────────────────────────────────

app.include_router(alerts.router,   prefix="/api/v1/alerts",   tags=["Alerts"])
app.include_router(meters.router,   prefix="/api/v1/meters",   tags=["Meters"])
app.include_router(zones.router,    prefix="/api/v1/zones",    tags=["Zones"])
app.include_router(feeders.router,  prefix="/api/v1/feeders",  tags=["Feeders"])
app.include_router(scenario.router, prefix="/api/v1/scenario", tags=["Scenario"])
app.include_router(reports.router,  prefix="/api/v1/reports",  tags=["Reports"])
app.include_router(health.router,   prefix="/api/v1/health",   tags=["Health"])

# ─── Root ─────────────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
async def root():
    return {
        "service": "BESCOM Smart Meter AI API",
        "version": "1.0.0",
        "status":  "operational",
        "docs":    "/docs",
    }

@app.get("/api/v1/kpis", tags=["Dashboard"])
async def get_kpis(request: Request):
    """Summary KPI endpoint for dashboard header cards."""
    from services.alert_service import AlertService
    svc = AlertService(request.app.state.model_registry)
    return await svc.get_kpi_summary()
