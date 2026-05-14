# BESCOM Smart Meter AI Platform

Minimal full-stack dashboard for BESCOM smart meter demand forecasting, theft detection, grid monitoring, and audit workflows.

## What Is Included

- FastAPI backend with operational dashboard endpoints under `/api/v1`.
- React + TypeScript + Vite dashboard with a compact navigation model.
- Dashboard coverage for ingestion health, demand forecasts, anomaly alerts, zone risk, detector/model health, data quality, topology, scenario analysis, and audit events.
- Render-ready `render.yaml` with separate API and static dashboard services.
- Docker Compose for local full-stack development.

## Project Structure

```text
smart_ai_meter/
  backend/                 FastAPI API and lightweight service layer
  frontend/                React dashboard
  ml/                      Foundational ML modules from the starter zip
  data-pipeline/           PySpark pipeline scaffold
  scripts/                 Database bootstrap SQL
  infrastructure/          Deployment expansion point
  docker-compose.yml       Local container workflow
  render.yaml              Render blueprint
```

## Run Locally Without Docker

1. Open a terminal in the project root:

```bash
cd D:\bescom-smart-meter-ai
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
cd D:\bescom-smart-meter-ai\frontend
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
cd C:\Users\Spandana\Documents\Codex\2026-05-05\files-mentioned-by-the-user-smart\smart_ai_meter\backend
.venv\Scripts\Activate.ps1
$env:BESCOM_DATA_DIR="C:\Users\Spandana\Documents\Codex\2026-05-05\files-mentioned-by-the-user-smart\smart_ai_meter\data\demo_edge_cases"
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
cd C:\Users\Spandana\Documents\Codex\2026-05-05\files-mentioned-by-the-user-smart\smart_ai_meter
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
