# BESCOM Smart Meter AI System — Master Builder Agent Prompt

---

## HOW TO USE THIS DOCUMENT
Copy the entire contents of the **"BUILDER AGENT PROMPT"** section below and paste it directly to your builder agent (e.g., Claude Code, GPT-4o with Code Interpreter, or any agentic coding framework). It is self-contained and fully specifies the system to be built.

---

---

# ═══════════════════════════════════════════════════════════
# BUILDER AGENT PROMPT — START
# ═══════════════════════════════════════════════════════════

You are a senior full-stack ML engineer and systems architect. Your task is to build the **BESCOM Smart Meter AI Platform** — a production-grade electricity theft detection and demand forecasting system for India's Bangalore Electricity Supply Company (BESCOM). This document is your complete specification. Build exactly what is described here, in the order described, without deviation unless technically blocked (in which case document the deviation clearly).

---

## 0. SYSTEM OVERVIEW

**What you are building:** A multi-layer AI platform that ingests 15-minute smart meter telemetry from ~2 million meters, predicts demand at meter/feeder/zone level, detects electricity theft and anomalies, and surfaces actionable alerts to BESCOM analysts via a web dashboard. The system combines results from 10 research papers (P1–P10 listed below) into a single coherent pipeline.

**Scale:** 2M meters × 96 readings/day = 192M rows/day  
**Granularity:** 15-minute intervals  
**Sensitivity:** No external LLM on meter data. All NL generation is template-based.  
**Deployment:** Docker + Kubernetes. On-premise preferred; cloud GPU for training only.

---

## 1. COMPLETE TECHNOLOGY STACK

### 1.1 Data Infrastructure
| Layer | Technology | Purpose |
|---|---|---|
| Streaming Ingestion | Apache Kafka + Kafka Connect | Real-time meter read ingestion at 15-min cadence |
| Raw Storage (Bronze) | Delta Lake on S3/HDFS | Immutable append-only raw meter reads |
| Processed Storage (Silver/Gold) | Delta Lake (medallion architecture) | Cleaned, featured, labeled data |
| Time-Series DB | TimescaleDB (PostgreSQL extension) | Fast range queries and hypertables for meter data |
| Feature Store | Feast (offline + online) | Consistent feature serving for training and inference |
| Batch Processing | PySpark 3.4 on YARN (20-node cluster) | Feature engineering, peer clustering, bulk inference |
| Orchestration | Apache Airflow 2.x | DAG-based pipeline scheduling |

### 1.2 ML Frameworks
| Purpose | Framework | Paper Reference |
|---|---|---|
| Demand Forecast (tabular) | LightGBM 4.x | Baseline |
| Demand Forecast (sequence) | PyTorch 2.x LSTM with Bahdanau Attention | Architecture design |
| Demand Forecast (multi-horizon) | pytorch-forecasting → TemporalFusionTransformer | P1 (Lim et al., NeurIPS 2021) |
| Demand Forecast (decomposition) | pytorch-forecasting → N-BEATS interpretable | P2 (Oreshkin et al., ICLR 2020) |
| Uncertainty Quantification | MAPIE (conformal prediction) | P6 (Cordier et al., JMLR 2023) |
| Anomaly Detection (probabilistic) | PyTorch VAE (custom MeterVAE) | Variational autoencoder architecture |
| Anomaly Detection (tree-based) | eif (Extended Isolation Forest) | P4 (Hariri et al., IEEE TKDE 2019) |
| Anomaly Detection (changepoint) | bayesian_changepoint_detection (BOCPD) | P5 (Adams & MacKay, arXiv 2007) |
| Anomaly Detection (graph-based) | PyTorch Geometric — EnergyGNN (GAT) | P3 (Pereira et al., IEEE Trans Smart Grid 2022) |
| Meta-Classifier | scikit-learn CalibratedClassifierCV | Combines all detector outputs |
| Contrastive Fingerprinting | SimCLR-style encoder (PyTorch) | Novel contribution |
| Causal Inference | DoWhy (Microsoft Research) | P10 (Sharma & Kiciman, arXiv 2020) |
| Federated Learning | Flower (flwr) framework | P8 (Taïk & Cherkaoui, IEEE Syst. J. 2020) |
| Explainability | shap (TreeSHAP + DeepExplainer) | P9 (Lundberg & Lee, NeurIPS 2017) |
| Peer Clustering | scikit-learn SpectralClustering + DTW | Novel contribution |

### 1.3 MLOps
| Purpose | Technology |
|---|---|
| Experiment tracking | MLflow |
| HPO | Optuna (TPE sampler, walk-forward CV) |
| Model registry | MLflow Model Registry |
| Drift monitoring | Evidently AI |
| CI/CD | GitHub Actions + DVC |

### 1.4 Backend API
| Purpose | Technology |
|---|---|
| REST API | FastAPI (async) |
| Task queue | Celery + Redis |
| Caching | Redis |
| Auth / RBAC | Keycloak (SSO) |
| Containerization | Docker + Kubernetes |
| Audit logging | Append-only Delta Lake tables (hash-chained) |

### 1.5 Frontend Dashboard
| Purpose | Technology |
|---|---|
| Framework | React 18 + TypeScript |
| Maps | Mapbox GL JS + DeckGL |
| Charts | Apache ECharts |
| UI Library | Ant Design Pro |
| State management | Zustand + React Query |

---

## 2. DATASET SPECIFICATION

### 2.1 Primary Table: `smart_meter_readings`
This is the core time-series fact table. **Minimum 24 months of history per meter for model training.**

| Column | Type | Description | Required? |
|---|---|---|---|
| `meter_id` | STRING | Unique meter identifier (e.g., "BES-4872193") | MUST |
| `timestamp` | TIMESTAMP | UTC timestamp of reading (15-min aligned) | MUST |
| `kwh` | FLOAT | Active energy consumed in this 15-min interval (kWh) | MUST |
| `kvah` | FLOAT | Apparent energy in this interval (kVAh) | MUST |
| `voltage_r` | FLOAT | R-phase voltage (V) — for phase reversal detection | SHOULD |
| `voltage_y` | FLOAT | Y-phase voltage (V) | SHOULD |
| `voltage_b` | FLOAT | B-phase voltage (V) | SHOULD |
| `current_r` | FLOAT | R-phase current (A) | SHOULD |
| `power_factor` | FLOAT | Computed power factor = kwh / kvah | SHOULD |
| `cumulative_kwh` | FLOAT | Odometer-style cumulative reading — rollback detection | MUST |
| `tamper_flag` | BOOLEAN | Hardware tamper event flag from meter firmware | SHOULD |
| `communication_status` | INT | 0=OK, 1=partial, 2=failed — imputation flag | MUST |
| `read_source` | ENUM | 'ami', 'manual', 'estimated' | MUST |

**Row count target:** 2M meters × 96 intervals/day × 730 days = ~140 billion rows (store in TimescaleDB with columnar compression; query recent 90 days for most inference tasks)

### 2.2 Meter Metadata Table: `meter_registry`
One row per meter. Static or slowly-changing.

| Column | Type | Description |
|---|---|---|
| `meter_id` | STRING | Primary key |
| `consumer_id` | STRING | BESCOM consumer account number |
| `consumer_type` | ENUM | 'residential', 'commercial', 'industrial', 'agricultural', 'government' |
| `tariff_category` | STRING | BESCOM tariff code (LT-1, LT-2, HT-1, etc.) |
| `contract_demand_kva` | FLOAT | Sanctioned demand (kVA) |
| `meter_type` | ENUM | 'single_phase', 'three_phase', 'ct_metered' |
| `meter_age_years` | FLOAT | Age of installed meter in years |
| `installation_date` | DATE | Meter installation date |
| `zone` | STRING | Administrative zone (e.g., "Rajajinagar", "Indiranagar") |
| `ward_id` | STRING | BBMP ward identifier |
| `feeder_id` | STRING | Electrical feeder ID |
| `transformer_id` | STRING | Distribution transformer ID |
| `substation_id` | STRING | 11kV substation ID |
| `latitude` | FLOAT | GPS latitude of meter location |
| `longitude` | FLOAT | GPS longitude of meter location |
| `address` | STRING | Physical address |
| `floor_area_sqft` | FLOAT | Property floor area (proxy for expected demand) — nice to have |

### 2.3 Network Topology Table: `grid_topology`
Encodes the physical electrical hierarchy. Essential for GNN.

| Column | Type | Description |
|---|---|---|
| `meter_id` | STRING | Child node |
| `transformer_id` | STRING | Parent transformer |
| `feeder_id` | STRING | Parent feeder |
| `substation_id` | STRING | Parent substation |
| `transformer_rated_kva` | FLOAT | Transformer rating (kVA) |
| `feeder_length_km` | FLOAT | Feeder length in km |
| `connection_type` | ENUM | 'overhead', 'underground' |
| `num_consumers_on_dt` | INT | Count of meters on this distribution transformer |
| `topology_valid_from` | DATE | For handling topology changes over time |

### 2.4 Feeder Telemetry Table: `feeder_readings`
Aggregated feeder-level readings from SCADA — critical for energy balance checks.

| Column | Type | Description |
|---|---|---|
| `feeder_id` | STRING | Feeder identifier |
| `timestamp` | TIMESTAMP | 15-min aligned timestamp |
| `feeder_input_kwh` | FLOAT | Energy entering feeder from substation |
| `feeder_input_kvah` | FLOAT | Apparent energy entering feeder |
| `transformer_id` | STRING | If available, per-DT submetering |
| `dt_input_kwh` | FLOAT | Energy at distribution transformer level |

### 2.5 External Reference Tables

**`weather_data`** (join on date + weather_station_id near meter zone)
| Column | Description |
|---|---|
| `date`, `hour` | Temporal key |
| `zone_id` | Spatial key |
| `temp_c` | Temperature °C |
| `humidity_pct` | Relative humidity % |
| `temp_forecast_c` | Next-24hr forecast temperature |
| `rainfall_mm` | Precipitation |

**`calendar_events`** (Indian holidays, local festivals, industrial shutdowns)
| Column | Description |
|---|---|
| `date` | Calendar date |
| `event_type` | 'national_holiday', 'state_holiday', 'festival', 'ipl_match', 'industrial_shutdown' |
| `event_name` | Human-readable name (e.g., "Ugadi", "Deepawali", "Ramadan") |
| `expected_demand_impact` | Signed float — expected % change vs normal day |
| `affected_zones` | Array of zone_ids or NULL for all-zones |

**`inspection_records`** (ground truth for model training — collect from field teams)
| Column | Description |
|---|---|
| `meter_id` | Inspected meter |
| `inspection_date` | Date of physical inspection |
| `outcome` | ENUM: 'theft_confirmed', 'tamper_confirmed', 'meter_fault', 'no_issue', 'pending' |
| `theft_type` | ENUM: 'bypass', 'slowdown', 'phase_reversal', 'flatline', 'illegal_extension', 'clock_fraud' |
| `estimated_loss_kwh` | Estimated energy stolen |
| `inspector_id` | Field team member ID |
| `analyst_alert_id` | FK to the alert that triggered dispatch |

### 2.6 Minimum Dataset Size for Good Model Performance

| Metric | Minimum | Ideal |
|---|---|---|
| History per meter (training) | 12 months | 24 months |
| Confirmed theft labels for meta-classifier | 500 positive cases | 2,000+ |
| Meters with labeled inspection outcomes | 5,000 | 20,000+ |
| Weather data coverage | All zones, daily | All zones, hourly |
| Feeder topology completeness | 80% of feeders mapped | 100% |
| Missing read rate (after imputation) | < 5% | < 2% |

---

## 3. COMPLETE SOLUTION PIPELINE

### LAYER 0 — DATA INGESTION
**Input:** Raw meter telemetry from AMI Head-End (SFTP/REST), SCADA feeds (OPC-UA), Weather API (REST)  
**Output:** Bronze Delta Lake tables (raw, immutable)  
**Tech:** Kafka + Kafka Connect, Bronze Delta Lake  
**SLA:** Meter reads available within 5 minutes of collection

Build these Kafka topics:
- `meter.raw` — all meter reads, schema: (meter_id, timestamp, kwh, kvah, cumulative_kwh, tamper_flag, communication_status)
- `feeder.telemetry` — feeder SCADA readings
- `weather.events` — OpenWeatherMap or IMD API data

---

### LAYER 1 — PREPROCESSING (PySpark)
**Input:** Bronze Delta Lake  
**Output:** Silver Delta Lake (cleaned features), Feast feature store  
**SLA:** Runs every 30 minutes on streaming micro-batches

**Step 1.1 — Missing Value Imputation (Priority: CRITICAL)**
Three-stage imputation cascade:
1. Mean of ±15-min neighbors (for isolated gaps)
2. Same-hour, same-day, previous-week value (for multi-hour gaps)
3. Peer group median for that hour/day-type (for multi-day gaps)
Flag all imputed values with `is_imputed=True`. Train models with augmentation that randomly drops 5–15% of values to make them imputation-robust.

**Step 1.2 — Feature Engineering**
Generate ALL of the following feature columns per meter per 15-min interval:

*Temporal encoding (cyclic — avoid ordinal pitfalls):*
- `hour_sin`, `hour_cos` = sin/cos of (2π × hour / 24)
- `dow_sin`, `dow_cos` = sin/cos of (2π × dayofweek / 7)
- `month_sin`, `month_cos` = sin/cos of (2π × month / 12)
- `is_holiday`, `is_ugadi`, `is_deepawali`, `is_ramadan_fasting`, `is_ipl_evening` (Karnataka + India holiday calendar)
- `time_of_use_period` = ENUM('off_peak', 'normal', 'peak', 'critical') mapped to BESCOM ToU tariff slots
- `minutes_since_midnight` (continuous, for fine-grained ToU effects)

*Lag features (multi-scale memory):*
- `kwh_lag_4` (1hr ago), `kwh_lag_8` (2hr ago), `kwh_lag_96` (1 day ago), `kwh_lag_672` (1 week ago), `kwh_lag_4032` (1 month ago)

*Rolling statistics (per meter, per window):*
- `roll_mean_4`, `roll_mean_96`, `roll_mean_672`
- `roll_std_4`, `roll_std_96`, `roll_std_672`
- `roll_max_96`, `roll_max_672`

*Physical / derived features:*
- `load_factor_day` = daily_mean_kwh / daily_max_kwh (low = suspicious)
- `kwh_delta_1d` = % change vs same 15-min slot yesterday
- `is_flatline` = True if rolling(8 periods).std < 0.01
- `night_ratio` = night_kwh / (day_kwh + 1e-5)
- `power_factor` = active_kwh / (apparent_kvah + 1e-5)
- `cumulative_rollback` = True if cumulative_kwh today < yesterday (tampering signal)

*Peer group features (recomputed monthly via Spectral Clustering):*
- `peer_cluster_id` = cluster assignment from DTW-distance spectral clustering on 30-day profiles
- `peer_group_mean_kwh` = mean kwh of peer cluster at this timestamp
- `peer_group_std_kwh` = std of peer cluster
- `peer_dev_ratio` = kwh / peer_group_mean_kwh
- `z_vs_peer` = (kwh - peer_group_mean_kwh) / peer_group_std_kwh

*Graph / topology features:*
- `feeder_load_share` = kwh / feeder_total_kwh
- `upstream_loss_ratio` = (feeder_input_kwh - feeder_billed_kwh) / feeder_input_kwh
- `transformer_loading` = transformer_demand_kva / transformer_rated_kva

**Step 1.3 — Dynamic Peer Grouping with Spectral Clustering** (Paper: novel contribution)
Monthly batch job:
1. Compute DTW distance matrix between all meters' 30-day consumption profiles (sample 10k meters per tariff class; scale with mini-batch DTW)
2. Apply SpectralClustering(n_clusters=auto via eigengap heuristic, affinity='precomputed')
3. Assign `peer_cluster_id` to meter_registry
4. Log cluster composition to MLflow for drift tracking

---

### LAYER 2A — DEMAND FORECASTING

**Goal:** Predict kWh demand at meter, feeder, and zone level for horizons: next 15 min, next 1 hr, next 24 hr, next 7 days.  
**Target metric:** MAPE < 5% hourly, MAPE < 3% day-ahead

#### Model 2A-1: LSTM with Bahdanau Attention (Enhanced Baseline)
**Input:** Sequence of 336 timesteps (3.5 days) of engineered features per meter  
**Output:** Next 96 timesteps (24hr ahead), scalar kWh per timestep  
**Architecture:**
```
Input: (batch, 336, input_dim=64 features)
→ LSTM(hidden=256, num_layers=3, dropout=0.2)
→ Bahdanau Additive Attention (query=last hidden, keys=all hidden states)
→ Context vector (weighted sum of encoder outputs)
→ Linear decoder → (batch, 96) forecast
```
Return attention weights for explainability (which historical timesteps were most influential).

#### Model 2A-2: LightGBM (Tabular Champion)
**Input:** Tabular feature vector per meter per target timestep (lag features + rolling stats + calendar + weather + static metadata)  
**Output:** Point forecast (median) + quantile forecasts (10th, 90th percentile)  
Train 3 separate models: alpha=0.1 (lower bound), alpha=0.5 (median), alpha=0.9 (upper bound).  
Use SHAP TreeExplainer for feature importance. This is the primary explainability mechanism.

**LightGBM config:**
- objective: 'quantile'
- num_leaves: 63 (tuned via Optuna)
- n_estimators: 2000, learning_rate: 0.03
- subsample: 0.8, colsample_bytree: 0.8
- reg_alpha: 0.1, reg_lambda: 0.1
- Trained on LSTM residuals (stacking — LightGBM corrects systematic LSTM errors)

#### Model 2A-3: Temporal Fusion Transformer (TFT) — Research Paper P1
**Input:** TimeSeriesDataSet with:
- `time_varying_known_reals`: ['temp_forecast_c', 'hour_sin', 'hour_cos', 'is_holiday', 'transformer_loading']
- `time_varying_unknown_reals`: ['kwh', 'peer_group_mean_kwh', 'feeder_load']
- `static_categoricals`: ['tariff_category', 'zone', 'consumer_type']
- `static_reals`: ['contract_demand_kva', 'meter_age_years']
- `max_encoder_length`: 336 (3.5 days context)
- `max_prediction_length`: 96 (1 day ahead)

**Output:** 7 quantile forecasts (0.02, 0.1, 0.25, 0.5, 0.75, 0.9, 0.98) per timestep  
**Architecture:** TFT with hidden_size=64, attention_head_size=4, output_size=7, loss=QuantileLoss  
**Key advantage:** Variable Selection Network provides built-in feature importance per timestep — use in dashboard.

#### Model 2A-4: N-BEATS (Seasonal Decomposition) — Research Paper P2
Deploy the **interpretable variant** with trend + seasonality stacks.  
**Input:** Univariate kWh series (meter or feeder level), lookback=5× forecast horizon  
**Output:** Forecast decomposed into trend_component, seasonality_component, residual  
**Use case:** Populate the "Causal Timeline Viewer" dashboard feature — analysts see what fraction of a consumption change is seasonal vs anomalous residual.

#### Ensemble + Conformal Prediction — Research Paper P6 (MAPIE)
Combine LSTM, LightGBM, TFT outputs via weighted averaging (weights tuned on validation set).  
Apply MAPIE conformal prediction wrapper to produce **distribution-free coverage-guaranteed intervals**:
- Fit MapieRegressor(estimator=ensemble, method='plus', cv=5)
- Produce 90% and 99% prediction intervals
- Dashboard shows: "90% of historical actuals fell within this band"
- Anomaly alert triggers when actual reading falls outside **99% conformal band** — statistically principled threshold

**Zone-level Risk Classification** (output of forecasting layer):
| Risk | Criterion | Action |
|---|---|---|
| Critical | Forecasted demand > 95% transformer capacity within 4hr | Immediate alert |
| High | Forecasted peak > 80% capacity OR >15% surge vs 7-day mean | Alert to field team |
| Medium | Uncertainty interval > 20% of mean + upward trend | Escalated monitoring |
| Normal | All clear | Logged only |

---

### LAYER 2B — ANOMALY & THEFT DETECTION

**Goal:** Detect 6 theft patterns across 2M meters daily. Surface top-50 alerts ranked by composite urgency.  
**Target metrics:** Precision@50 > 0.75, F1 > 0.70, FDR < 25%, Mean Time to Detect < 14 days

Run 4 detectors in parallel, combine via meta-classifier.

#### Detector B-1: Variational Autoencoder (VAE) — Enhanced
**Architecture (MeterVAE):**
```
Input: 96-dim vector (1 day of 15-min readings, normalized)
Encoder: Linear(96→64)→ReLU→Linear(64→32)→ReLU → [fc_mu(32→latent_dim), fc_logvar(32→latent_dim)]
Reparameterization: z = mu + eps * exp(0.5 * logvar)
Decoder: Linear(latent→32)→ReLU→Linear(32→64)→ReLU→Linear(64→96)
```
- `latent_dim` = 16 (tuned via Optuna, search space: 4–64)
- `kl_weight` (β-VAE) tuned via Optuna, search: 0.001–1.0
- Reconstruction loss: MSE or Huber (tuned)
- **Anomaly score:** Monte Carlo average of (recon_loss + β × KL_divergence) over 50 samples
- Train on 12 months of normal meter data (no labels needed)
- Anomaly threshold: 99th percentile of training reconstruction losses per peer cluster

#### Detector B-2: Extended Isolation Forest (EIF) — Research Paper P4
**Input:** Daily feature vector per meter: (24 hourly means + load_factor + night_ratio + kwh_delta_1d + z_vs_peer + is_flatline) = 29-dim  
**Config:** ntrees=200, sample_size=256, ExtensionLevel=1  
**Calibration:** Map raw path-length scores to probabilities via isotonic regression trained on labeled inspection records  
**Key advantage vs standard IF:** Eliminates axis-aligned bias; ~8% higher AUC on electricity theft datasets (per P4)

#### Detector B-3: Bayesian Online Changepoint Detection (BOCPD) — Research Paper P5
**Input:** Streaming 15-min kWh time series per meter  
**Algorithm:** Adams & MacKay 2007 — Student-T hazard model, lambda_param=250 (expected ~2.5 days between true changepoints at 15-min resolution)  
**Output:** Probability > 0.5 = structural break detected; return timestamp of break  
**Post-processing:** For each detected changepoint, check calendar_events table. If no known cause (holiday, industrial shutdown, temperature spike) → escalate as potential theft. This reduces false positives by 20–35% (per P10 DoWhy implementation below).

#### Detector B-4: Graph Neural Network (EnergyGNN) — Research Paper P3
**Architecture (Graph Attention Network):**
```
Node features: 32-dim meter embedding (from VAE encoder or SimCLR fingerprint)
Edge: physical connection in grid_topology (meter→transformer→feeder)
GATConv(32→64, heads=4, concat=True) → ReLU
GATConv(256→64, heads=1, concat=False) → ReLU
anomaly_head: Linear(64→1) per node  ← is this specific meter anomalous?
balance_head: Linear(64→1) per graph ← does the feeder energy balance hold?
```
**Training signal (self-supervised, no labels needed initially):**
- If upstream_loss_ratio > 0.08 (>8% feeder loss) → feeder-level positive label
- Node-level labels: propagate feeder label to meters with highest load share deviation
**What it detects:** Illegal tap extensions (feeder reads higher than sum of downstream meters) — the hardest theft type to catch individually

**Implement physics constraint loss:**
```python
physics_loss = max(0, sum(meter_kwh) - feeder_input_kwh)  # meters can't consume more than feeder input
total_loss = bce_loss + lambda_physics * physics_loss
```

**Note on GNN timing:** Start GNN only after a 3-month topology data audit. Cross-validate topology against substation aggregate reads. Use soft constraints — penalize but don't require perfect balance.

#### Meta-Classifier: Combining All 4 Detectors
```python
meta_features = {
    'vae_score':      vae_anomaly_score,        # 0–1 continuous
    'eif_score':      eif_calibrated_prob,       # 0–1 probability
    'bocpd_detected': bocpd_flag_last_7_days,    # binary
    'gnn_node_score': gnn_node_anomaly_score,    # 0–1
    'gnn_balance':    gnn_feeder_balance_score,  # 0–1
    'peer_z_score':   z_vs_peer,                 # z-score (continuous)
    'load_factor':    load_factor_day,
    'night_ratio':    night_ratio,
    'is_flatline':    is_flatline,
}
model = CalibratedClassifierCV(LogisticRegression(C=0.1), cv=5, method='isotonic')
```
Train on confirmed inspection_records. Output: `theft_probability` (0–1).

**Composite Alert Urgency Score (drives ranking in analyst queue):**
```
urgency_score = theft_probability × estimated_revenue_loss_inr × recency_weight
estimated_revenue_loss_inr = days_since_suspected_onset × daily_kwh_stolen × applicable_tariff_rate
```

#### Theft Pattern Coverage Matrix
| Pattern | Primary Detector | Signal |
|---|---|---|
| Bypass tampering | VAE + EIF | Sudden step-down, low load factor, normal peers |
| Phase reversal | VAE + Physics | Negative apparent energy, power_factor > 1 |
| Meter slowdown | Peer deviation + EIF | Consistent under-reading vs cluster over 30+ days |
| Clock fraud | BOCPD + temporal | Consumption shifts suddenly to off-peak hours |
| Illegal tap extension | GNN balance | Feeder reads > sum of downstream meters |
| Short-circuit injection | VAE + BOCPD | Flatline then sudden return to normal |

---

### LAYER 2C — NOVEL AI CONTRIBUTIONS

#### Novel 1: Contrastive Self-Supervised Meter Fingerprinting (SimCLR-style)
Train a contrastive encoder that learns a unique "consumption fingerprint" for each meter without labels:
- Augmentation A: Add Gaussian noise (σ=0.05) to 7-day profile
- Augmentation B: Random time shift (±2 hours) of 7-day profile
- Two augmentations of the SAME meter should be similar; different meters should be far apart
- NT-Xent loss (SimCLR) over meter-level batches
- After pre-training: anomaly score = cosine distance between current week's embedding and meter's historical fingerprint centroid
- Achieves anomaly detection without any labeled data; improves cold-start for new meters

#### Novel 2: Multi-Task Learning (Forecast + Detect Jointly)
Shared LSTM encoder trained simultaneously:
- Task A head: demand forecast (next 96 timesteps)
- Task B head: anomaly probability (binary)
- Total loss = λ₁ × ForecastLoss + λ₂ × AnomalyLoss
- λ₁, λ₂ tuned via Optuna on validation Pareto front
- Benefit: shared representations improve both tasks — normal pattern understanding aids anomaly detection

#### Novel 3: Causal Inference for False Positive Reduction (DoWhy) — Research Paper P10
When a meter shows a significant consumption drop (> 20% vs 7-day rolling mean), before escalating as theft:
1. Build causal DAG: {temperature, holiday, business_closure, industrial_shutdown} → consumption_drop
2. Use DoWhy to estimate backdoor adjustment: "What is the consumption drop unexplained by known causes?"
3. If residual unexplained variance > 15% → escalate. If explained by known cause → suppress for 7 days.
Implementation: Load calendar_events and weather_data as exogenous variables in DoWhy CausalModel.
Expected impact: 20–35% reduction in false positives from legitimate behavioral changes.

#### Novel 4: Federated Learning Across Substations (Phase 3) — Research Paper P8
Architecture (Flower framework):
- Central server: maintains global model, aggregates via FedAvg
- Substation edge nodes: train local VAE + EIF on local meter data
- Only gradient updates transmitted — never raw meter data
- Round frequency: daily (model updates once per day per substation)
- Privacy analysis: Gradient inversion attack resistance tested as per P8 methodology
- Deploy in Phase 3 (months 8–12) after substation compute infra is provisioned

---

### LAYER 3 — EXPLAINABILITY & AUDITABILITY

#### SHAP for Every Alert — Research Paper P9
```python
# LightGBM: TreeSHAP (O(n_features × n_trees) — fast for 2M daily inferences)
lgb_explainer = shap.TreeExplainer(lgb_model)
shap_values = lgb_explainer.shap_values(X_meter)  # per-feature attribution

# VAE: DeepExplainer (DeepLIFT-based approximation)
vae_explainer = shap.DeepExplainer(vae_model, background_data)
vae_shap_vals = vae_explainer.shap_values(anomalous_readings)
```

Generate **template-based NL alert summaries** from SHAP waterfall (NO external LLM):
```
"Meter {meter_id} ({zone}, {consumer_type}) flagged with {theft_probability:.0%} theft probability.
Top contributors: {top_feature_1} (↑{shap_1:.2f}), {top_feature_2} (↓{shap_2:.2f}).
Peer group behavior: Normal. No calendar event detected.
Recommended action: Physical inspection within 7 days. Estimated revenue at risk: ₹{revenue_impact:,.0f}/month."
```

#### Immutable Audit Trail
Store in append-only Delta Lake table `audit_log`:
- Every model inference: (timestamp, meter_id, model_version, raw_scores, shap_values, feature_snapshot)
- Every alert: (alert_id, urgency_score, threshold_used, shap_summary)
- Every analyst action: (analyst_id, action_type, reason_code, timestamp)
- Every model retraining event: (trigger_reason, training_data_range, performance_delta)
Hash-chain entries (SHA-256 of previous entry hash + current entry) to detect tampering.

---

## 4. BACKEND API SPECIFICATION (FastAPI)

Build the following REST endpoints:

### Alert Management
- `GET /api/v1/alerts` — paginated alert queue sorted by urgency_score (supports filters: risk_level, anomaly_type, zone, date_range)
- `GET /api/v1/alerts/{alert_id}` — full alert detail including SHAP values and NL summary
- `PATCH /api/v1/alerts/{alert_id}/feedback` — analyst feedback (outcome, reason_code)
- `POST /api/v1/alerts/dispatch-route` — accepts list of alert_ids, returns optimized field inspection route (use Google Maps Directions API or OSRM)

### Meter Inspector
- `GET /api/v1/meters/{meter_id}/profile` — 90-day consumption heatmap data, peer comparison, static metadata
- `GET /api/v1/meters/{meter_id}/forecast` — next 24hr demand forecast with confidence intervals
- `GET /api/v1/meters/{meter_id}/shap` — SHAP waterfall data for current alert
- `GET /api/v1/meters/{meter_id}/anomaly-timeline` — BOCPD changepoint history

### Zone & Feeder Views
- `GET /api/v1/zones` — all zone risk levels + demand forecasts (GeoJSON compatible)
- `GET /api/v1/feeders/{feeder_id}/balance` — energy balance: input vs metered vs billed
- `GET /api/v1/feeders/{feeder_id}/topology` — graph data for topology inspector

### Scenario Simulator
- `POST /api/v1/scenario/simulate` — body: {zone_id, temperature_override, holiday_flag, date}; returns modified forecast

### System Health
- `GET /api/v1/health/models` — current model performance metrics, drift scores, last retrain date
- `GET /api/v1/health/data` — data quality metrics (% missing per feeder, ingestion lag)

### Reports
- `POST /api/v1/reports/monthly-audit` — generate monthly PDF: detections, confirmed thefts, revenue recovered
- `GET /api/v1/kpis` — dashboard KPI summary: alerts today, precision this week, revenue recovered MTD

---

## 5. FRONTEND DASHBOARD SPECIFICATION (React 18 + TypeScript)

Build a single-page application with the following views, navigable from a left sidebar:

### 5.1 Analyst Alert Console (Primary View — Home Page)
This is the most critical screen. Build it as the default landing page.

**Layout:** Sidebar filters + main content area

**Top control bar filters:**
- Risk Level dropdown: All / Critical / High / Medium
- Anomaly Type dropdown: All / Bypass / Slowdown / Phase Reversal / Flatline / Illegal Extension / Clock Fraud
- Zone multiselect: All zones or specific zones
- Date range picker (default: last 7 days)
- Precision/Recall mode toggle: "High Precision" / "High Recall" (adjusts threshold displayed)

**Feeder Energy Balance Chart** (top of main area):
- Line chart (Apache ECharts) showing last 24hr: Input Energy vs Aggregated Metered Energy vs Billed Energy
- Color bands showing loss threshold breaches
- Zone selector to switch feeder

**Alert Table** (main area below chart):
Dynamic table updated by filters. Columns:
- Meter ID (clickable → opens Meter Deep Dive)
- Zone
- Risk Level (colored badge: Critical=red, High=orange, Medium=yellow)
- Anomaly Type
- Theft Probability (% with mini bar)
- Est. Revenue Impact (₹/month)
- Detectors Triggered (e.g., "VAE + EIF + GNN")
- Time Since Detection
- Actions: [View Details] [Dispatch] [Snooze 7d]

**Generate Dispatch Route button**: Select multiple rows → generates optimized route for field team (calls `/api/v1/alerts/dispatch-route`) → displays on map popup.

**"Send Soft Warning" button** per alert: Generates template-based SMS/email draft to consumer about unusual consumption.

### 5.2 Meter Deep Dive
Opened by clicking any meter in the alert table or searching by meter ID.

**Sections:**
1. **Header:** Meter ID, zone, consumer type, tariff, contract demand, GPS coordinates + Google Maps link
2. **90-Day Consumption Heatmap:** Apache ECharts calendar heatmap (rows=hours, cols=days, color=kWh)
3. **Peer Group Comparison:** Line chart showing this meter vs peer cluster mean ± 1σ band (last 30 days)
4. **SHAP Waterfall:** Bar chart showing top-10 features driving current anomaly score (positive=pushes toward theft, negative=normal signal)
5. **N-BEATS Decomposition View (Causal Timeline):** Stacked area chart: trend + seasonality + residual components over last 30 days. Annotate known events (holidays, temperature spikes) on the timeline.
6. **BOCPD Changepoint History:** Timeline showing detected structural breaks with probability indicators
7. **Historical Inspection Records:** Table of past inspections for this meter
8. **Natural Language Alert Summary:** Template-generated paragraph (from SHAP values) ready to copy for dispatch order

### 5.3 Interactive Zone Risk Map
- Mapbox GL JS choropleth layer over BBMP ward boundaries (GeoJSON)
- Color coding by risk tier (critical=red, high=orange, medium=yellow, normal=green)
- Time slider: slide through next 24 hours to see forecasted risk progression
- Click zone → drill down popup with: transformer list, top 5 alerts in zone, feeder load chart
- Layer toggles: Demand Risk / Theft Risk / Data Quality

### 5.4 Dynamic Peer Group Explorer
- Scatter plot (Apache ECharts) of meters in 2D PCA/t-SNE space (recomputed monthly)
- Points colored by cluster
- Click a meter → highlights it and shows its drift from cluster centroid over time
- "Straying meters" highlighted — those whose current week's position is >2σ from historical cluster center

### 5.5 Scenario Simulator
Form inputs:
- Zone selector
- Temperature slider (15°C – 45°C)
- Holiday toggle
- Industrial load multiplier slider (0.5× – 2.0×)
- Date picker

Submit → calls `/api/v1/scenario/simulate` → overlays modified forecast on baseline chart with confidence interval. Shows: "Peak demand shifts by +X kWh. Transformer loading reaches Y%."

### 5.6 Revenue Impact Dashboard
- KPI cards: Alerts Today / Precision This Week / Revenue Recovered MTD / Revenue Recovered YTD
- Cumulative revenue recovery line chart (monthly, 12 months rolling)
- Confirmed theft breakdown by anomaly type (donut chart)
- Feeder-level loss leaderboard: Top 10 feeders by upstream loss ratio

### 5.7 Intervention Tracker (One-Click Workflow)
When analyst dispatches a field team via the alert queue:
1. System creates an inspection ticket (status: Pending)
2. Field team updates outcome (mobile-friendly form or API)
3. Dashboard shows ticket lifecycle: Pending → In Progress → Resolved
4. On resolution: system automatically links outcome to original alert_id, triggers feedback loop, updates model labels

### 5.8 System Health Dashboard (Drift Monitor)
- Model performance trend charts: MAPE (forecasting) and F1/Precision/Recall (anomaly detection) over time
- Data quality heatmap: % missing reads per feeder per day (last 30 days)
- Feature drift chart (Evidently AI PSI scores for top features)
- Auto-retrain trigger indicator: "Model will auto-retrain when PSI > 0.2 on kwh_lag_96 — currently at 0.12"

---

## 6. HPO STRATEGY (Optuna — All Models)

Use walk-forward cross-validation for all time-series models (3 folds: 30 days train + 7 days validation). Never use random splits.

**LightGBM search space:** num_leaves [20–150], lr [0.005–0.1], n_estimators [500–5000], min_child_samples [5–100], subsample [0.5–1.0], colsample_bytree [0.5–1.0], reg_alpha [1e-8–10], reg_lambda [1e-8–10]

**VAE search space:** latent_dim [4–64], encoder_layers [1–4], kl_weight [0.001–1.0], reconstruction ['mse','mae','huber'], threshold_pct [90–99.9]

**LSTM search space:** hidden_dim [64,128,256,512], num_layers [1–4], dropout [0–0.5], lr [1e-4–1e-2], batch_size [32,64,128,256], seq_len [96–672 step 96]

All studies: TPESampler(multivariate=True), n_trials=200, log to MLflow.

---

## 7. EVALUATION FRAMEWORK

### Demand Forecasting
| Metric | Target | Notes |
|---|---|---|
| MAPE | < 5% hourly, < 3% day-ahead | Primary operational metric |
| RMSE | < 10 kWh at meter level | Penalizes large errors |
| PICP | > 90% for 90% prediction interval | Calibration check |
| PINAW | < 0.2 | Interval sharpness |
| Skill Score vs naive | > 0.25 | Beats "same hour last week" baseline by 25% |

### Anomaly Detection
| Metric | Target | Notes |
|---|---|---|
| Precision@50 alerts/day | > 0.75 | 75% of dispatched teams find confirmed issues |
| Recall | > 0.65 | 65% of known theft cases caught |
| F1 Score | > 0.70 | Balanced |
| AUC-PR | > 0.75 | Better than ROC for imbalanced data |
| False Discovery Rate | < 25% | Max 1-in-4 false alarms |
| Mean Time to Detect | < 14 days | From theft onset to alert |

### Baselines to Beat
Demand: Naive (same-hour-last-week), SARIMA(7,1,1)(1,1,1)[96], Prophet, MLP  
Anomaly: 3-σ rule, Tukey IQR, standard Isolation Forest, simple AE

---

## 8. USER-FACING FEATURES — DETAILED SPECIFICATIONS

### Feature 1: Smart Dispatch Router
After the analyst reviews the alert queue (sorted by composite urgency), they select multiple alerts and click "Generate Dispatch Route." The system calls a routing API (Google Maps Directions API or open-source OSRM) to compute an optimized route for the field team visiting all selected meter locations. Display route on Mapbox map with estimated travel time per leg. Export as PDF or share link. **Feasibility: HIGH** — standard routing API integration, no ML required, builds on existing alert queue.

### Feature 2: One-Click Intervention Tracker
Every dispatched alert creates a ticket. The ticket flows through states: `Pending → Dispatched → In Progress → Resolved`. On resolution, the field team records outcome (theft confirmed / meter fault / no issue) via a mobile-responsive form or voice call follow-up. The system links this outcome back to the original alert, updates the meta-classifier training labels automatically, and shows precision trend to the analyst. **Feasibility: HIGH** — standard CRUD workflow + feedback loop already in audit log architecture.

### Feature 3: Pre-Inspection Consumer Nudge (Soft Warning)
Before dispatching a costly field team, the analyst can send an automated message to the consumer: "We've noticed unusual consumption patterns at your premises. If this is due to a known change (renovation, new appliances), please call our helpline. Otherwise, we may schedule an inspection." This resolves accidental tampers or simple meter faults without truck roll. The message is generated from the NL alert summary template. **Feasibility: HIGH** — requires BESCOM's SMS/email gateway integration. Consumer contact database needed.

### Feature 4: Dynamic Peer Group Explorer
Interactive scatter plot (2D projection via PCA of peer cluster embeddings) showing all meters in a selected cluster. Animated "drift path" shows how a meter's position has evolved week-over-week. If a meter's current week is >2σ from its historical cluster centroid, it appears as a flashing red dot. Clicking any dot opens Meter Deep Dive. **Feasibility: MEDIUM** — requires monthly PCA recomputation and storage of weekly embeddings. Front-end render of 2k+ dots needs WebGL (DeckGL ScatterplotLayer). Doable in Phase 2.

### Feature 5: Feeder-Level Topology Inspector
Hierarchical tree visualization (D3.js or ECharts TreeGraph): Substation → Feeders → Distribution Transformers → Meters. Each node colored by loss ratio. Clicking a feeder shows the energy balance chart (input vs billed). "Kirchhoff violation" nodes flash red when balance deficit > 8%. Analysts drill top-down to isolate NTL source. **Feasibility: MEDIUM** — depends on topology data quality (GIS system access). Implement with soft constraints: if topology has gaps, show "unverified topology" badge. Phase 2.

### Feature 6: Causal Timeline Viewer
On the Meter Deep Dive screen, the N-BEATS decomposition chart is annotated with causal events from calendar_events and weather_data. Visual callouts: "↓ Temperature drop (11°C) — explains 35% of consumption reduction" or "Holiday: Ugadi — explains 28%". The remaining unexplained fraction is computed via DoWhy and highlighted in red as "Unexplained variance — theft probability elevated." Makes the "why did consumption drop?" question immediately visual. **Feasibility: HIGH** — N-BEATS + DoWhy already in pipeline; just a UI annotation layer over existing data.

### Feature 7: Automated Audit & Recovery Report Generator
Monthly Airflow DAG generates a formatted PDF report: total alerts raised, confirmed thefts, false discovery rate, estimated revenue recovered, top 10 theft zones, model performance summary. Auto-emails to BESCOM management. Uses Python `reportlab` or `weasyprint` with a branded HTML template. **Feasibility: HIGH** — all data already in audit_log and inspection_records; pure reporting task.

### Feature 8: Precision/Recall Mode Toggle
Dashboard toggle in alert console: "High Precision" mode (fewer false alarms — good for routine dispatch) vs "High Recall" mode (catch everything — good for audit campaigns). Dynamically adjusts the theft_probability threshold used to filter the alert queue. Backend endpoint accepts `operating_mode` param. Shows live preview of "X alerts at this threshold, estimated precision Y%." **Feasibility: HIGH** — threshold is a runtime parameter, no model retraining needed. Calibration curves precomputed and stored.

---

## 9. FEASIBILITY ANALYSIS — ALL COMPONENTS

| Component | Technical Feasibility | Operational Feasibility | Timeline | Risk | Mitigation |
|---|---|---|---|---|---|
| LSTM + LightGBM Demand Forecast | **Very High** (90%) — proven in 30+ utility deployments | High — standard MLOps | 3–4 months | Low | Walk-forward CV prevents leakage |
| Temporal Fusion Transformer (P1) | **High** (80%) — pytorch-forecasting is production-ready | Medium — needs GPU infra + MLflow | 4–5 months | Low-Medium | Use pytorch-forecasting's built-in trainer; cloud GPU for training only |
| N-BEATS Decomposition (P2) | **High** (80%) — ICLR 2020, open-source implementation | Medium — needs seasonal tuning for Indian calendar | 3–4 months | Low | Use interpretable variant; validate decomposition against known festivals |
| Conformal Prediction / MAPIE (P6) | **Very High** (95%) — pip-installable, 2-min integration | High — replaces fixed thresholds with statistical guarantees | 1–2 weeks | Very Low | Drop-in over any sklearn-compatible model |
| VAE Anomaly Detector | **High** (78%) — needs labeled theft cases for calibration | Medium — 3–6 months to collect labels from field teams | 3–4 months | Medium | Launch with EIF first; add VAE after 3 months of labels |
| Extended Isolation Forest (P4) | **Very High** (88%) — eif library is pip-installable | High — no labels needed initially | 2–3 months | Low | Direct upgrade from standard IF; validate AUC improvement |
| BOCPD Changepoint Detection (P5) | **High** (82%) — bayesian_changepoint_detection library | High — online algorithm, no retraining needed | 2–3 months | Low | Set lambda_param empirically; validate on known tamper timestamps |
| Graph Neural Network (P3) | **Medium-High** (65%) — topology data quality is the bottleneck | **Medium** — requires GIS system access + 3-month topology audit | 5–7 months | **High** | Start after topology audit; use soft physics constraints; cross-validate against substation reads |
| SHAP Explainability (P9) | **Very High** (95%) — TreeSHAP is battle-tested at scale | Very High — directly satisfies regulatory explainability requirements | 1–2 weeks | Very Low | TreeSHAP is O(polynomial) for LightGBM; fast enough for 2M daily inferences |
| Causal Inference / DoWhy (P10) | **Medium** (60%) — DAG design requires domain expertise | **Medium** — needs BESCOM domain experts to validate causal assumptions | 4–5 months | Medium | Build causal DAG with BESCOM engineers; validate on 6-month holdout; use as FP filter only |
| Contrastive Fingerprinting (Novel) | **Medium** (50%) — needs 12+ months stable data per meter | Medium — cold-start problem for new meters | 6–8 months | Medium | Pre-train on meters with 24+ months history; interpolate for newer meters |
| Dynamic Spectral Peer Clustering (Novel) | **High** (75%) — scikit-learn SpectralClustering + DTW | High — monthly batch job, well-contained | 2–3 months | Low | Mini-batch DTW for scale; fall back to K-Means if DTW too slow |
| Multi-Task Learning (Novel) | **Medium** (60%) — shared encoder architecture complexity | Medium — λ tuning via Optuna adds training complexity | 4–6 months | Medium | Phase 2; validate that shared encoder improves both tasks before deploying |
| Federated Learning (P8) | **Medium** (55%) — Flower is mature but substations need compute | **Low** — major organizational + infrastructure change | 8–10 months | **High** | Phase 3 only; pilot with 3 substations first; validate FedAvg achieves ≤3% MAPE penalty vs centralized |
| Smart Dispatch Router (UI) | **Very High** (95%) | Very High — standard Maps API | 2–4 weeks | Very Low | Use Google Maps Directions API or open-source OSRM |
| Consumer Nudge / SMS Gateway | **High** (85%) | **Medium** — requires BESCOM's telecom/SMS gateway approval | 4–6 weeks | Medium | Start with email-only; upgrade to SMS after gateway integration |
| Automated PDF Report Generator | **Very High** (95%) | Very High — management needs this immediately | 1–2 weeks | Very Low | reportlab or weasyprint; branded HTML template |
| Federated Privacy Guarantee | **Medium** (55%) | Low — gradient inversion protection needs audit | 10–12 months | High | Privacy analysis as per P8; third-party security audit before full rollout |

**Overall Feasibility Summary:**
- **Go live in 3 months:** LSTM+LightGBM demand forecast, EIF + BOCPD anomaly detection, Alert Console UI, Zone Map, SHAP explainability, Audit trail, Dispatch Router, PDF reports
- **Go live in 7 months:** TFT, N-BEATS, VAE, Meta-classifier, Spectral Peer Clustering, DoWhy FP filter, all UX features
- **Go live in 12 months:** GNN, Contrastive Fingerprinting, Multi-task Learning, Federated pilot
- **Technology is NOT the bottleneck — data quality, topology access, and labeled inspection records are.**

---

## 10. IMPLEMENTATION ROADMAP

### Phase 1 (Months 1–3): Foundation
1. Stand up Kafka + Delta Lake + TimescaleDB + Feast infrastructure (read-only from BESCOM)
2. Implement full PySpark preprocessing pipeline: imputation, all feature columns, peer clustering
3. Deploy LightGBM demand forecast with SHAP
4. Deploy Extended Isolation Forest with BOCPD + calibrated thresholds
5. Build MVP React dashboard: Alert Console, Zone Map, Meter Deep Dive
6. Establish audit logging + analyst feedback form
7. **Go-live milestone:** First real alerts dispatched to field teams

### Phase 2 (Months 4–7): Enhancement
1. Deploy TFT + N-BEATS forecasting with conformal prediction intervals
2. Deploy VAE anomaly detector — upgrade from initial EIF
3. Introduce meta-classifier combining all detectors
4. Add DoWhy causal FP filter
5. Deploy Evidently AI drift monitoring + automated retraining Airflow DAG
6. Add all UX features: Dispatch Router, Intervention Tracker, Consumer Nudge, Scenario Simulator, Revenue Dashboard, Dynamic Peer Explorer, Topology Inspector, Causal Timeline
7. **Target:** F1 > 0.70, MAPE < 5%

### Phase 3 (Months 8–12): Novel Tech
1. Deploy GNN (after topology audit completion)
2. Pilot Federated Learning at 3 test substations (Flower framework)
3. Train SimCLR contrastive meter fingerprints
4. Multi-task learning joint model
5. Full N-BEATS seasonal decomposition views
6. **Target:** FDR < 25% for top-50 daily alerts, feeder loss visibility for all DTs

### Phase 4 (Month 12+): Scale
1. Federated learning rollout to all substation edge nodes
2. Online learning for BOCPD at edge
3. Integrate with BESCOM's field dispatch system for one-click work-order
4. Expand to 2M+ meters with horizontal scaling

---

## 11. PROJECT STRUCTURE

Build the following monorepo structure:

```
bescom-smart-meter-ai/
├── infrastructure/
│   ├── docker-compose.yml          # Local dev: Kafka, TimescaleDB, Redis
│   ├── k8s/                        # Kubernetes manifests
│   └── terraform/                  # Cloud infra (optional)
│
├── data-pipeline/
│   ├── ingestion/
│   │   ├── kafka_producers/        # AMI, SCADA, Weather connectors
│   │   └── kafka_consumers/        # Bronze Delta Lake writers
│   ├── preprocessing/
│   │   ├── spark_pipeline.py       # Main PySpark feature engineering job
│   │   ├── imputation.py           # Multi-stage missing value imputation
│   │   └── peer_clustering.py      # Spectral clustering monthly job
│   └── feature_store/
│       └── feast_definitions.py    # Feast feature view definitions
│
├── ml/
│   ├── demand_forecasting/
│   │   ├── lstm_attention.py       # Model 2A-1
│   │   ├── lightgbm_forecaster.py  # Model 2A-2
│   │   ├── tft_forecaster.py       # Model 2A-3 (pytorch-forecasting)
│   │   ├── nbeats_forecaster.py    # Model 2A-4
│   │   └── ensemble_conformal.py   # MAPIE conformal ensemble
│   ├── anomaly_detection/
│   │   ├── vae_detector.py         # MeterVAE + anomaly scoring
│   │   ├── eif_detector.py         # Extended Isolation Forest
│   │   ├── bocpd_detector.py       # BOCPD streaming changepoint
│   │   ├── gnn_detector.py         # EnergyGNN (PyTorch Geometric)
│   │   └── meta_classifier.py      # Calibrated logistic regression ensemble
│   ├── novel/
│   │   ├── simclr_fingerprint.py   # Contrastive meter fingerprinting
│   │   ├── multitask_model.py      # Joint forecast+detect LSTM
│   │   └── causal_filter.py        # DoWhy FP reduction
│   ├── explainability/
│   │   ├── shap_explainer.py       # TreeSHAP + DeepExplainer wrappers
│   │   └── alert_nlg.py            # Template-based NL alert generation
│   ├── training/
│   │   ├── hpo_optuna.py           # Unified Optuna HPO configs
│   │   └── walk_forward_cv.py      # Time-series cross-validation
│   └── federated/
│       └── flower_server.py        # FedAvg server (Phase 3)
│
├── backend/
│   ├── main.py                     # FastAPI app entry point
│   ├── routers/
│   │   ├── alerts.py
│   │   ├── meters.py
│   │   ├── zones.py
│   │   ├── scenario.py
│   │   ├── reports.py
│   │   └── health.py
│   ├── services/
│   │   ├── alert_service.py        # Urgency scoring, queue management
│   │   ├── dispatch_service.py     # Route optimization API calls
│   │   └── report_service.py       # PDF generation
│   └── models/
│       └── schemas.py              # Pydantic response models
│
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── AlertConsole.tsx    # 5.1 — primary view
│   │   │   ├── MeterDeepDive.tsx   # 5.2
│   │   │   ├── ZoneRiskMap.tsx     # 5.3
│   │   │   ├── PeerGroupExplorer.tsx # 5.4
│   │   │   ├── ScenarioSimulator.tsx # 5.5
│   │   │   ├── RevenueDashboard.tsx  # 5.6
│   │   │   ├── InterventionTracker.tsx # 5.7
│   │   │   └── SystemHealth.tsx    # 5.8
│   │   ├── components/             # Reusable ECharts, Mapbox wrappers
│   │   └── store/                  # Zustand stores
│   └── package.json
│
├── airflow/
│   └── dags/
│       ├── daily_inference_dag.py  # Runs all models daily
│       ├── monthly_training_dag.py # Model retraining pipeline
│       ├── peer_clustering_dag.py  # Monthly spectral clustering
│       └── monthly_report_dag.py   # PDF report generation
│
└── tests/
    ├── unit/
    ├── integration/
    └── evaluation/
        └── run_baselines.py        # Automated baseline comparison
```

---

## 12. CRITICAL CONSTRAINTS & NON-NEGOTIABLES

1. **No external LLM on meter data.** All natural language generation is template-based using SHAP values + rule substitution. Zero data leakage.
2. **All audit logs are append-only and hash-chained.** Analysts can never delete historical alerts.
3. **Walk-forward cross-validation only.** Never random-split time-series data.
4. **Always use EIF (Extended IF) over standard Isolation Forest** — as shown in P4, 8% higher AUC.
5. **Always use MAPIE conformal prediction** over fixed thresholds for anomaly alerting — statistically principled.
6. **GNN deployment is blocked until topology audit completes.** Do not deploy GNN with unverified topology data.
7. **Federated learning is Phase 3 only.** Do not attempt early without substation compute provisioning.
8. **Precision@50 > 0.75 is a hard KPI.** If precision falls below 0.60, field teams will lose trust. Monitor weekly and retrain.
9. **Imputed readings must be flagged.** Models must know which values were estimated.
10. **Consumer data privacy:** Aggregate meter reads at feeder level for federated nodes — never expose individual consumption to cross-substation models.

---

## 13. GLOSSARY OF KEY TERMS

- **AMI:** Advanced Metering Infrastructure — the network of smart meters and communication backhaul
- **DT:** Distribution Transformer — the step-down transformer serving a cluster of ~10–50 meters
- **NTL:** Non-Technical Loss — electricity consumed but not billed (theft, metering errors)
- **BOCPD:** Bayesian Online Changepoint Detection — real-time structural break detection algorithm
- **EIF:** Extended Isolation Forest — anomaly detection algorithm with proper hyperplane cuts
- **TFT:** Temporal Fusion Transformer — multi-horizon forecasting model (P1)
- **VAE:** Variational Autoencoder — probabilistic reconstruction model for anomaly scoring
- **GNN:** Graph Neural Network — topology-aware theft detection using feeder graph
- **SHAP:** SHapley Additive exPlanations — model-agnostic feature attribution
- **FDR:** False Discovery Rate — fraction of dispatched alerts that are not real theft cases
- **MAPE:** Mean Absolute Percentage Error — demand forecast accuracy metric
- **ToU:** Time of Use — tariff pricing that varies by time of day
- **DTW:** Dynamic Time Warping — distance measure between time series for clustering

# ═══════════════════════════════════════════════════════════
# BUILDER AGENT PROMPT — END
# ═══════════════════════════════════════════════════════════

---

*Document compiled from: BESCOM_SmartMeter_AI_Blueprint.html (10 research papers, 14 blueprint sections) + User-facing feature specifications. Version 1.0.*
