-- BESCOM Smart Meter AI — TimescaleDB Schema Initialization
-- Run: psql -U bescom -d bescom_meters -f init_db.sql

-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ─── METER REGISTRY ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS meter_registry (
    meter_id            VARCHAR(30) PRIMARY KEY,
    consumer_id         VARCHAR(30) NOT NULL,
    consumer_type       VARCHAR(20) NOT NULL CHECK (consumer_type IN ('residential','commercial','industrial','agricultural','government')),
    tariff_category     VARCHAR(20) NOT NULL,
    contract_demand_kva FLOAT,
    meter_type          VARCHAR(20) CHECK (meter_type IN ('single_phase','three_phase','ct_metered')),
    meter_age_years     FLOAT DEFAULT 0,
    installation_date   DATE,
    zone                VARCHAR(50),
    ward_id             VARCHAR(20),
    feeder_id           VARCHAR(30),
    transformer_id      VARCHAR(30),
    substation_id       VARCHAR(30),
    latitude            FLOAT,
    longitude           FLOAT,
    address             TEXT,
    floor_area_sqft     FLOAT,
    peer_cluster_id     INT,
    is_active           BOOLEAN DEFAULT TRUE,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_meter_registry_feeder ON meter_registry(feeder_id);
CREATE INDEX IF NOT EXISTS idx_meter_registry_zone ON meter_registry(zone);
CREATE INDEX IF NOT EXISTS idx_meter_registry_cluster ON meter_registry(peer_cluster_id);

-- ─── SMART METER READINGS (Main hypertable) ───────────────────────────────────
CREATE TABLE IF NOT EXISTS smart_meter_readings (
    meter_id                VARCHAR(30) NOT NULL,
    timestamp               TIMESTAMPTZ NOT NULL,
    kwh                     FLOAT,
    kvah                    FLOAT,
    voltage_r               FLOAT,
    voltage_y               FLOAT,
    voltage_b               FLOAT,
    current_r               FLOAT,
    power_factor            FLOAT,
    cumulative_kwh          FLOAT,
    tamper_flag             BOOLEAN DEFAULT FALSE,
    communication_status    SMALLINT DEFAULT 0,  -- 0=OK, 1=partial, 2=failed
    read_source             VARCHAR(15) DEFAULT 'ami',
    is_imputed              BOOLEAN DEFAULT FALSE,
    created_at              TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (meter_id, timestamp)
);

-- Convert to TimescaleDB hypertable (partitioned by time, 1-week chunks)
SELECT create_hypertable(
    'smart_meter_readings',
    'timestamp',
    chunk_time_interval => INTERVAL '1 week',
    if_not_exists => TRUE
);

-- Enable columnar compression (critical for 192M rows/day)
ALTER TABLE smart_meter_readings SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'meter_id',
    timescaledb.compress_orderby = 'timestamp DESC'
);

-- Compress chunks older than 7 days
SELECT add_compression_policy('smart_meter_readings', INTERVAL '7 days', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_smr_meter_time ON smart_meter_readings(meter_id, timestamp DESC);

-- ─── FEEDER READINGS ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS feeder_readings (
    feeder_id           VARCHAR(30) NOT NULL,
    transformer_id      VARCHAR(30),
    timestamp           TIMESTAMPTZ NOT NULL,
    feeder_input_kwh    FLOAT,
    feeder_input_kvah   FLOAT,
    dt_input_kwh        FLOAT,
    PRIMARY KEY (feeder_id, timestamp)
);

SELECT create_hypertable('feeder_readings', 'timestamp',
    chunk_time_interval => INTERVAL '1 week', if_not_exists => TRUE);

-- ─── GRID TOPOLOGY ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS grid_topology (
    topology_id             SERIAL PRIMARY KEY,
    meter_id                VARCHAR(30) REFERENCES meter_registry(meter_id),
    transformer_id          VARCHAR(30) NOT NULL,
    feeder_id               VARCHAR(30) NOT NULL,
    substation_id           VARCHAR(30),
    transformer_rated_kva   FLOAT,
    feeder_length_km        FLOAT,
    connection_type         VARCHAR(15) CHECK (connection_type IN ('overhead','underground')),
    num_consumers_on_dt     INT,
    topology_valid_from     DATE NOT NULL DEFAULT CURRENT_DATE,
    topology_valid_to       DATE,
    is_verified             BOOLEAN DEFAULT FALSE
);

-- ─── WEATHER DATA ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS weather_data (
    zone_id             VARCHAR(50) NOT NULL,
    timestamp           TIMESTAMPTZ NOT NULL,
    temp_c              FLOAT,
    humidity_pct        FLOAT,
    temp_forecast_c     FLOAT,
    rainfall_mm         FLOAT DEFAULT 0,
    PRIMARY KEY (zone_id, timestamp)
);

SELECT create_hypertable('weather_data', 'timestamp',
    chunk_time_interval => INTERVAL '1 month', if_not_exists => TRUE);

-- ─── CALENDAR EVENTS ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS calendar_events (
    event_id                SERIAL PRIMARY KEY,
    date                    DATE NOT NULL,
    event_type              VARCHAR(30) CHECK (event_type IN ('national_holiday','state_holiday','festival','ipl_match','industrial_shutdown')),
    event_name              VARCHAR(100),
    expected_demand_impact  FLOAT,           -- signed %, e.g. -0.30 = -30% demand
    affected_zones          TEXT[],          -- NULL = all zones
    source                  VARCHAR(50) DEFAULT 'manual'
);

-- ─── INSPECTION RECORDS (Ground Truth) ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS inspection_records (
    inspection_id       SERIAL PRIMARY KEY,
    meter_id            VARCHAR(30) REFERENCES meter_registry(meter_id),
    inspection_date     DATE NOT NULL,
    outcome             VARCHAR(30) CHECK (outcome IN ('theft_confirmed','tamper_confirmed','meter_fault','no_issue','pending')),
    theft_type          VARCHAR(30) CHECK (theft_type IN ('bypass','slowdown','phase_reversal','flatline','illegal_extension','clock_fraud', NULL)),
    estimated_loss_kwh  FLOAT,
    inspector_id        VARCHAR(30),
    analyst_alert_id    VARCHAR(50),
    notes               TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- ─── ALERTS (Output of ML pipeline) ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS alerts (
    alert_id            VARCHAR(50) PRIMARY KEY DEFAULT gen_random_uuid()::text,
    meter_id            VARCHAR(30) REFERENCES meter_registry(meter_id),
    detected_at         TIMESTAMPTZ DEFAULT NOW(),
    risk_level          VARCHAR(15) CHECK (risk_level IN ('Critical','High','Medium','Low')),
    anomaly_type        VARCHAR(30) CHECK (anomaly_type IN ('bypass','slowdown','phase_reversal','flatline','illegal_extension','clock_fraud','unknown')),
    theft_probability   FLOAT NOT NULL,
    urgency_score       FLOAT NOT NULL,
    estimated_revenue_impact_inr FLOAT,
    vae_score           FLOAT,
    eif_score           FLOAT,
    bocpd_detected      BOOLEAN DEFAULT FALSE,
    gnn_node_score      FLOAT,
    gnn_balance_score   FLOAT,
    peer_z_score        FLOAT,
    shap_summary        JSONB,
    nl_summary          TEXT,
    status              VARCHAR(20) DEFAULT 'open' CHECK (status IN ('open','snoozed','dispatched','resolved')),
    snoozed_until       TIMESTAMPTZ,
    snooze_reason       TEXT,
    analyst_outcome     VARCHAR(30),
    analyst_reason_code VARCHAR(50),
    analyst_id          VARCHAR(30),
    resolved_at         TIMESTAMPTZ,
    model_version       VARCHAR(20)
);

CREATE INDEX IF NOT EXISTS idx_alerts_meter ON alerts(meter_id);
CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status);
CREATE INDEX IF NOT EXISTS idx_alerts_detected ON alerts(detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_urgency ON alerts(urgency_score DESC);

-- ─── AUDIT LOG (Immutable, hash-chained) ──────────────────────────────────────
CREATE TABLE IF NOT EXISTS audit_log (
    log_id              BIGSERIAL PRIMARY KEY,
    timestamp           TIMESTAMPTZ DEFAULT NOW(),
    event_type          VARCHAR(50) NOT NULL,  -- inference|alert|analyst_action|retrain
    meter_id            VARCHAR(30),
    alert_id            VARCHAR(50),
    actor_id            VARCHAR(30),
    payload             JSONB NOT NULL,
    model_version       VARCHAR(20),
    entry_hash          VARCHAR(64),           -- SHA-256(prev_hash || payload)
    prev_hash           VARCHAR(64)
);

CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_meter ON audit_log(meter_id);

-- ─── FORECAST OUTPUTS ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS demand_forecasts (
    meter_id            VARCHAR(30) NOT NULL,
    forecast_generated_at TIMESTAMPTZ NOT NULL,
    target_timestamp    TIMESTAMPTZ NOT NULL,
    forecast_kwh        FLOAT NOT NULL,
    lower_bound_90      FLOAT,
    upper_bound_90      FLOAT,
    lower_bound_99      FLOAT,
    upper_bound_99      FLOAT,
    model_name          VARCHAR(30),
    model_version       VARCHAR(20),
    PRIMARY KEY (meter_id, target_timestamp, model_name)
);

SELECT create_hypertable('demand_forecasts', 'target_timestamp',
    chunk_time_interval => INTERVAL '1 month', if_not_exists => TRUE);

-- ─── CONTINUOUS AGGREGATES (for dashboard performance) ──────────────────────
CREATE MATERIALIZED VIEW IF NOT EXISTS hourly_meter_stats
WITH (timescaledb.continuous) AS
SELECT
    meter_id,
    time_bucket('1 hour', timestamp) AS hour,
    AVG(kwh)    AS avg_kwh,
    SUM(kwh)    AS total_kwh,
    MAX(kwh)    AS peak_kwh,
    MIN(kwh)    AS min_kwh,
    STDDEV(kwh) AS std_kwh,
    COUNT(*)    AS reading_count,
    SUM(CASE WHEN is_imputed THEN 1 ELSE 0 END) AS imputed_count
FROM smart_meter_readings
GROUP BY meter_id, time_bucket('1 hour', timestamp)
WITH NO DATA;

-- Refresh policy: update every hour, covering last 3 days
SELECT add_continuous_aggregate_policy('hourly_meter_stats',
    start_offset => INTERVAL '3 days',
    end_offset   => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists => TRUE);

COMMIT;
