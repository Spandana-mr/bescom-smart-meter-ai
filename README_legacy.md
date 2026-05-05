# BESCOM Smart Meter AI Platform

A production-grade electricity theft detection and demand forecasting system for Bangalore Electricity Supply Company (BESCOM). Built on 10 research papers, covering 2M+ smart meters at 15-minute granularity.

## Architecture

```
AMI Head-End / SCADA / Weather API
        ↓ (Kafka)
Bronze Delta Lake  →  PySpark Preprocessing  →  Silver/Gold Delta Lake
                                                        ↓
                              ┌─────────────────────────────────────────┐
                              │           AI MODEL LAYER                │
                              │  Part A: LSTM · LightGBM · TFT · NBEATS│
                              │  Part B: VAE · EIF · BOCPD · GNN        │
                              │  Novel:  SimCLR · MultiTask · DoWhy     │
                              └─────────────────────────────────────────┘
                                                        ↓
                              FastAPI Backend  →  React 18 Dashboard
```

## Quick Start

```bash
# 1. Clone and set up environment
cp .env.example .env
# Edit .env with your credentials

# 2. Start local infrastructure
docker-compose up -d

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Run database migrations
python scripts/init_db.py

# 5. Start the backend API
cd backend && uvicorn main:app --reload --port 8000

# 6. Start the frontend
cd frontend && npm install && npm run dev
```

## Research Papers Implemented

| ID  | Paper | Usage |
|-----|-------|-------|
| P1  | Temporal Fusion Transformers (Lim et al., NeurIPS 2021) | Multi-horizon demand forecasting |
| P2  | N-BEATS (Oreshkin et al., ICLR 2020) | Seasonal decomposition |
| P3  | NTL Detection via GNN (Pereira et al., IEEE TSG 2022) | Topology-aware theft detection |
| P4  | Extended Isolation Forest (Hariri et al., IEEE TKDE 2019) | Anomaly detection (EIF > IF) |
| P5  | BOCPD (Adams & MacKay, arXiv 2007) | Real-time changepoint detection |
| P6  | MAPIE Conformal Prediction (Cordier et al., JMLR 2023) | Calibrated uncertainty intervals |
| P7  | Theft Detection Survey (Zheng et al., IEEE TSG 2023) | Taxonomy & evaluation protocol |
| P8  | Federated Learning for Smart Grid (Taïk & Cherkaoui, IEEE SJ 2020) | Privacy-preserving federated training |
| P9  | SHAP (Lundberg & Lee, NeurIPS 2017) | Model explainability for every alert |
| P10 | DoWhy Causal Inference (Sharma & Kiciman, 2020) | False positive reduction |

## Target Performance

| Metric | Target |
|--------|--------|
| Demand MAPE (hourly) | < 5% |
| Demand MAPE (day-ahead) | < 3% |
| Theft Detection F1 | > 0.70 |
| Precision@50 alerts/day | > 0.75 |
| False Discovery Rate | < 25% |
| Mean Time to Detect | < 14 days |

## Project Structure

```
bescom-smart-meter-ai/
├── infrastructure/          # Docker, K8s, Terraform
├── data-pipeline/           # Kafka, PySpark, Feast
├── ml/                      # All ML models
│   ├── demand_forecasting/  # LSTM, LightGBM, TFT, N-BEATS
│   ├── anomaly_detection/   # VAE, EIF, BOCPD, GNN, meta-classifier
│   ├── novel/               # SimCLR, MultiTask, DoWhy
│   ├── explainability/      # SHAP, NL alert generation
│   └── training/            # HPO, walk-forward CV
├── backend/                 # FastAPI REST API
├── frontend/                # React 18 + TypeScript dashboard
├── airflow/                 # DAGs for orchestration
└── tests/                   # Unit, integration, evaluation
```

## Implementation Phases

- **Phase 1 (M1–3):** LSTM + LightGBM + EIF + BOCPD + MVP Dashboard → First real alerts
- **Phase 2 (M4–7):** TFT + N-BEATS + VAE + GNN + DoWhy + Full UX → F1 > 0.70
- **Phase 3 (M8–12):** Federated Learning + SimCLR + Multi-task → FDR < 25%
- **Phase 4 (M12+):** Full scale to 2M+ meters

## Tech Stack

**Data:** Kafka, Delta Lake, TimescaleDB, Feast, PySpark  
**ML:** PyTorch 2.x, LightGBM, pytorch-forecasting, PyTorch Geometric, SHAP, DoWhy, MAPIE, Flower  
**MLOps:** MLflow, Optuna, Evidently AI, Airflow, DVC, GitHub Actions  
**Backend:** FastAPI, Celery, Redis, Keycloak, Docker, Kubernetes  
**Frontend:** React 18, TypeScript, Mapbox GL JS, Apache ECharts, Ant Design Pro, Zustand
