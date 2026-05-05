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
cd C:\Users\Spandana\Documents\Codex\2026-05-05\files-mentioned-by-the-user-smart\smart_ai_meter
```

2. Start the backend:

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

3. In a second terminal, start the frontend:

```bash
cd C:\Users\Spandana\Documents\Codex\2026-05-05\files-mentioned-by-the-user-smart\smart_ai_meter\frontend
npm install
npm run dev
```

4. Open:

- Dashboard: `http://localhost:3000`
- API docs: `http://localhost:8000/docs`

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
