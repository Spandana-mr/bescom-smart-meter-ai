# BESCOM Smart Meter AI Platform

Minimal full-stack dashboard for BESCOM smart meter demand forecasting, theft detection, grid monitoring, and audit workflows.

## What Is Included

- FastAPI backend with operational dashboard endpoints under `/api/v1`.
- React + TypeScript + Vite dashboard with a compact navigation model.
- Dashboard coverage for ingestion health, demand forecasts, anomaly alerts, zone risk, detector/model health, data quality, topology, scenario analysis, audit events, and **energy accounting**.
- Render-ready `render.yaml` with separate API and static dashboard services.
- Docker Compose for local full-stack development.

## Project Architecture

```text
bescom-smart-meter-ai/
│
├── backend/                          # FastAPI API and service layer
│   ├── app/                          # Application package
│   │   ├── models/                   # Pydantic schemas & data models
│   │   │   ├── __init__.py
│   │   │   └── schemas.py
│   │   ├── services/                 # Business logic & data services
│   │   │   ├── ai_assistant/         # Copilot chat (Groq LLM integration)
│   │   │   │   ├── context_builder.py
│   │   │   │   ├── groq_client.py
│   │   │   │   ├── prompt_builder.py
│   │   │   │   ├── response_formatter.py
│   │   │   │   ├── routes.py
│   │   │   │   └── tools.py
│   │   │   ├── energy_accounting.py  # DT-level energy balance service
│   │   │   ├── ml_runtime.py         # Synthetic ML model runtime
│   │   │   └── mock_data.py          # Sample data generators
│   │   └── __init__.py
│   ├── artifacts/                    # Persisted ML artifacts
│   │   └── synthetic_ml/             # Trained model outputs
│   │       ├── anomaly_scores.csv
│   │       ├── forecast_preview.csv
│   │       └── training_summary.json
│   ├── main.py                       # FastAPI app entry point & route definitions
│   ├── legacy_main.py                # Legacy API (preserved for reference)
│   ├── Dockerfile                    # Backend container image
│   ├── requirements.txt              # Core Python dependencies
│   └── requirements-full.txt         # Extended dependencies (research stack)
│
├── frontend/                         # React + TypeScript dashboard
│   ├── src/                          # Source code
│   │   ├── styles/                   # CSS stylesheets
│   │   │   └── app.css               # Global dashboard styles
│   │   ├── main.tsx                  # Single-file React app (all pages & components)
│   │   └── vite-env.d.ts            # Vite type declarations
│   ├── dist/                         # Production build output
│   ├── index.html                    # HTML entry point
│   ├── package.json                  # NPM dependencies & scripts
│   ├── tsconfig.json                 # TypeScript configuration
│   ├── vite.config.js                # Vite config (JavaScript)
│   └── vite.config.ts                # Vite config (TypeScript)
│
├── ml/                               # Research ML modules
│   ├── anomaly_detection/            # Theft & anomaly detectors
│   │   ├── eif_bocpd_meta.py         # Extended Isolation Forest + BOCPD meta-classifier
│   │   ├── gnn_detector.py           # Graph Neural Network detector
│   │   └── vae_detector.py           # Variational Autoencoder detector
│   ├── demand_forecasting/           # Load forecasting models
│   │   └── lightgbm_forecaster.py    # LightGBM quantile forecaster
│   ├── explainability/               # Model interpretability
│   │   ├── alert_nlg.py              # Natural-language alert generation
│   │   └── causal_filter.py          # Causal inference filter
│   └── training/                     # Training utilities
│       ├── peer_clustering.py        # Meter peer-group clustering
│       └── walk_forward_cv.py        # Walk-forward cross-validation
│
├── data/                             # Datasets
│   ├── bescom_dataset/               # Primary BESCOM dataset (2023-2024)
│   │   ├── meter_readings.csv        # 500-meter daily readings
│   │   ├── meters.csv                # Meter registry
│   │   ├── demand_forecasts.csv      # Forecasted demand
│   │   ├── anomaly_alerts.csv        # Anomaly alert history
│   │   ├── alert_feedback.csv        # Field feedback on alerts
│   │   ├── data_quality.csv          # Data quality metrics
│   │   ├── grid_topology.csv         # Network topology
│   │   ├── audit_events.csv          # Audit trail
│   │   ├── model_performance_history.csv
│   │   ├── distribution_transformers.csv   # DT registry (36 transformers)
│   │   ├── meter_transformer_map.csv       # Meter → DT assignments
│   │   ├── transformer_energy_daily.csv    # DT daily energy balance
│   │   ├── feeder_energy_daily.csv         # Feeder daily rollup
│   │   ├── substation_energy_daily.csv     # Substation daily rollup
│   │   └── schema_manifest.json      # Dataset schema definitions
│   ├── demo_edge_cases/              # Reviewer demo dataset (edge cases)
│   ├── BESCOM_Dataset_README.md      # Dataset documentation
│   └── ENERGY_ACCOUNTING_DATA_README.md  # Energy accounting data methodology
│
├── data-pipeline/                    # PySpark ETL pipeline
│   └── spark_pipeline.py            # Spark ingestion & transformation job
│
├── scripts/                          # Utility scripts
│   ├── init_db.sql                   # Database bootstrap schema (TimescaleDB)
│   ├── gen_energy_accounting_data.py # Synthetic energy accounting data generator
│   └── train_synthetic_models.py     # Train lightweight ML models locally
│
├── prompts/                          # Antigravity / LLM prompt archive
│   ├── antigravity_prompt_pass1_energy_accounting.md
│   ├── antigravity_prompt_pass1_followup_date_range_and_checkpoint.md
│   ├── antigravity_prompt_pass2_risk_pipeline.md
│   └── antigravity_prompt_pass2_verification.md
│
├── BESCOM_Master_Builder_Prompt.md   # Master project specification
├── docker-compose.yml                # Local container orchestration
├── render.yaml                       # Render deployment blueprint
├── .env.example                      # Environment variable template
├── .gitignore                        # Git ignore rules
├── package.json                      # Root workspace config
└── package-lock.json                 # Root lockfile
```

## Energy Accounting Layer

The platform now includes a **distribution-transformer (DT) level energy-accounting layer** — a network-level view of unexplained energy loss that is independent of per-meter consumption signals.

### Why it exists

Naive theft detection asks: "did this meter's consumption look unusual?" — which misclassifies legitimate demand drops (vacations, seasonal closures, weather) as theft. Real distribution utilities use a hierarchical approach:

1. **Network level (energy accounting)**: does energy delivered into a DT reconcile with what its downstream meters report, after expected technical loss? An unexplained gap flags the DT for investigation, regardless of individual meter movements.
2. **Meter level (ML pipeline — separate layer)**: within a flagged DT, existing anomaly signals help identify which specific meters are most likely responsible.

These two evidence streams are deliberately kept separate in this pass. Pass 2 will integrate `unexplained_pct` as an additional feature in the meta-classifier.

### Scope

Analysis starts at the BESCOM substation's outgoing (secondary) side and goes downstream only: **substation → feeder → DT → meter**. Nothing upstream of the substation is modeled.

### Data sources

Five new CSVs in `data/bescom_dataset/` cover 2023-01-01 to 2024-12-31:

| File | Contents |
|---|---|
| `distribution_transformers.csv` | DT registry (36 transformers) |
| `meter_transformer_map.csv` | Meter → DT assignment for all 500 meters |
| `transformer_energy_daily.csv` | DT × day: input, metered, technical loss, unexplained energy |
| `feeder_energy_daily.csv` | Feeder × day rollup |
| `substation_energy_daily.csv` | Substation × day rollup |

> **Note**: Technical-loss figures are **synthetic/parametric** (not field-measured). They were derived from `grid_topology.csv` feeder-loss parameters during data generation. See `data/ENERGY_ACCOUNTING_DATA_README.md` for full methodology.

### New API endpoints

```
GET /api/v1/energy-accounting/summary            Aggregate KPIs (zone, date range)
GET /api/v1/energy-accounting/transformers       DTs ranked by unexplained_pct desc
GET /api/v1/energy-accounting/transformers/{id}  DT drill-down: daily series + meters + alerts
GET /api/v1/energy-accounting/feeders            Feeder rollup
GET /api/v1/energy-accounting/substations        Substation rollup
```

### Dashboard tab

A new **Energy** tab in the dashboard shows:
- Summary panel (5 KPIs: total input, metered, technical loss, unexplained kWh, unexplained %)
- Ranked DT table with zone-filter and unexplained-% colour coding
- Drill-down panel per DT: daily energy balance chart, unexplained-% trend, mapped meters, and cross-referenced anomaly alerts

## Run Locally Without Docker

1. Open a terminal in the project root:

```bash
cd D:\Projects\bescom-smart-meter-ai_newFeature
```

2. Add your Groq API key for the backend.

Create or edit `backend\.env` or set it in the backend terminal before starting the API:

```powershell
$env:GROQ_API_KEY="your_groq_api_key_here"
```

If you prefer a project-level dotenv file, copy `.env.example` to `.env` and set:

```text
GROQ_API_KEY=your_groq_api_key_here
```

The assistant route will still work without the key, but it returns a local fallback summary instead of a Groq-generated answer.

3. Start the backend in VS Code terminal 1:

```bash
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

4. In VS Code terminal 2, start the frontend:

```bash
cd frontend
npm install
$env:VITE_API_URL="http://127.0.0.1:8000"
npm run dev
```

5. Open:

- Dashboard: `http://127.0.0.1:3000`
- API docs: `http://127.0.0.1:8000/docs`

## AI Analyst Assistant

The dashboard includes a floating **BESCOM Copilot** panel. It sends compact dashboard context only: KPI summaries, forecast bands, priority alerts, zone risks, feeder summaries, and masked selected meter or alert details. Raw addresses and precise private identifiers are redacted before the prompt is sent.

Backend endpoint:

- `POST /api/v1/assistant/chat`

Groq model fallback order:

- `llama-3.3-70b-versatile`
- `mixtral-8x7b-32768`
- `llama3-8b-8192`

## Run With The Reviewer Demo Dataset

The backend supports a dataset override through `BESCOM_DATA_DIR`.

In backend terminal 1:

```powershell
cd backend
.venv\Scripts\Activate.ps1
$env:BESCOM_DATA_DIR="..\data\demo_edge_cases"
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

The frontend command stays the same. Restart the backend whenever you change `BESCOM_DATA_DIR`.

## Train The Runnable Synthetic ML Backend

The repo keeps the heavier research model scaffolds under `ml/`, and also ships a locally runnable synthetic-data training path that works with the current demo dataset:

- Quantile gradient-boosting forecaster with simple conformal-style interval padding
- Daily anomaly ensemble using supervised random forest + unsupervised isolation forest
- Persisted artifacts consumed by the FastAPI backend

Run from the project root:

```powershell
python scripts\train_synthetic_models.py
```

This writes artifacts under:

```text
backend/artifacts/synthetic_ml/
```

Useful backend endpoints after training:

- `GET /api/v1/ml/status`
- `GET /api/v1/ml/forecast-preview`
- `GET /api/v1/ml/anomaly-rankings`
- `GET /api/v1/ml/meters/{meter_id}/anomaly-scores`

The existing frontend is not changed by this training workflow, but the Models page reads refreshed backend model-health data after artifacts are available.

## Run Locally With Docker

```bash
docker compose up --build
```

Then open `http://localhost:3000`.

## Deploy On Render

1. Push this project to GitHub.
2. In Render, choose **New > Blueprint**.
3. Select the repository.
4. Render will read `render.yaml` and create:
   - `bescom-smart-meter-api`
   - `bescom-smart-meter-dashboard`
5. After deploy, set `VITE_API_URL` on the dashboard service to the public API URL if Render does not resolve it automatically.

## Notes

The backend currently serves realistic sample data so the UI is runnable immediately. The foundational ML files from the zip are preserved under `ml/` and `data-pipeline/`; production wiring can replace the mock service functions with TimescaleDB, MLflow, Kafka, and model registry calls.
