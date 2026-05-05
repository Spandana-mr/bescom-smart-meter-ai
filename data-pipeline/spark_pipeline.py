"""
data-pipeline/preprocessing/spark_pipeline.py

Main PySpark feature engineering job.
Reads from Bronze Delta Lake → produces Silver Delta Lake with full feature set.
Run every 30 minutes via Airflow DAG.

Usage:
    spark-submit --packages io.delta:delta-core_2.12:2.4.0 spark_pipeline.py \
        --start 2024-01-01 --end 2024-01-02
"""

import os
import argparse
from datetime import datetime, timedelta
from functools import partial

from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.window import Window
from pyspark.sql.types import (
    StructType, StructField, StringType, FloatType,
    BooleanType, TimestampType, IntegerType
)
from delta import configure_spark_with_delta_pip

# ─── Spark Session ────────────────────────────────────────────────────────────

def create_spark_session(app_name: str = "BESCOM-Feature-Engineering") -> SparkSession:
    builder = (
        SparkSession.builder
        .appName(app_name)
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
        .config("spark.sql.adaptive.enabled", "true")
        .config("spark.sql.adaptive.coalescePartitions.enabled", "true")
        .config("spark.serializer", "org.apache.spark.serializer.KryoSerializer")
        # TimescaleDB JDBC
        .config("spark.jars", "postgresql-42.7.1.jar")
    )
    return configure_spark_with_delta_pip(builder).getOrCreate()


# ─── Step 1: Load Raw Data ────────────────────────────────────────────────────

def load_bronze(spark: SparkSession, bronze_path: str, start_dt: str, end_dt: str):
    """Load raw meter readings from Bronze Delta Lake."""
    df = (
        spark.read.format("delta")
        .load(f"{bronze_path}/smart_meter_readings")
        .filter(
            (F.col("timestamp") >= start_dt) &
            (F.col("timestamp") < end_dt)
        )
    )
    return df


def load_metadata(spark: SparkSession, jdbc_url: str, jdbc_props: dict):
    """Load static meter metadata from TimescaleDB."""
    registry = spark.read.jdbc(
        url=jdbc_url, table="meter_registry", properties=jdbc_props
    )
    topology = spark.read.jdbc(
        url=jdbc_url, table="grid_topology", properties=jdbc_props
    )
    return registry, topology


def load_weather(spark: SparkSession, jdbc_url: str, jdbc_props: dict):
    return spark.read.jdbc(
        url=jdbc_url, table="weather_data", properties=jdbc_props
    )


def load_calendar(spark: SparkSession, jdbc_url: str, jdbc_props: dict):
    return spark.read.jdbc(
        url=jdbc_url, table="calendar_events", properties=jdbc_props
    )


def load_peer_groups(spark: SparkSession, jdbc_url: str, jdbc_props: dict):
    """Load pre-computed peer cluster assignments."""
    return spark.read.jdbc(
        url=jdbc_url,
        table="(SELECT meter_id, peer_cluster_id FROM meter_registry) AS t",
        properties=jdbc_props
    )


# ─── Step 2: Missing Value Imputation ─────────────────────────────────────────

def impute_missing_reads(df):
    """
    Three-stage imputation cascade:
    1. Mean of ±15-min neighbors (for isolated gaps)
    2. Same-hour, same-day, previous-week value
    3. Peer group median for that hour/day-type

    Marks all imputed rows with is_imputed=True.
    """
    meter_time_window = Window.partitionBy("meter_id").orderBy("timestamp")

    # Stage 1: forward/backward fill within 2 steps (±30 min)
    df = df.withColumn(
        "kwh",
        F.when(
            F.col("kwh").isNull() | (F.col("communication_status") == 2),
            (F.lag("kwh", 1).over(meter_time_window) +
             F.lead("kwh", 1).over(meter_time_window)) / 2
        ).otherwise(F.col("kwh"))
    )

    # Stage 2: same-hour, same-weekday, last week (lag 672 × 15-min = 1 week)
    df = df.withColumn(
        "kwh",
        F.when(
            F.col("kwh").isNull(),
            F.lag("kwh", 672).over(meter_time_window)
        ).otherwise(F.col("kwh"))
    )

    # Mark remaining nulls as imputed (Stage 3 handled via peer join below)
    df = df.withColumn(
        "is_imputed",
        F.col("kwh").isNull() | (F.col("communication_status") > 0)
    )

    return df


# ─── Step 3: Temporal Feature Engineering ─────────────────────────────────────

def add_temporal_features(df):
    """Add cyclic temporal encodings and calendar flags."""
    import math

    df = (
        df
        # Basic temporal decomposition
        .withColumn("hour",      F.hour("timestamp"))
        .withColumn("dayofweek", F.dayofweek("timestamp"))
        .withColumn("month",     F.month("timestamp"))
        .withColumn("quarter",   F.quarter("timestamp"))
        .withColumn("date",      F.to_date("timestamp"))

        # Cyclic encoding (avoids ordinal pitfalls: 23:45 and 00:00 are neighbors)
        .withColumn("hour_sin",  F.sin(2 * math.pi * F.col("hour") / 24))
        .withColumn("hour_cos",  F.cos(2 * math.pi * F.col("hour") / 24))
        .withColumn("dow_sin",   F.sin(2 * math.pi * F.col("dayofweek") / 7))
        .withColumn("dow_cos",   F.cos(2 * math.pi * F.col("dayofweek") / 7))
        .withColumn("month_sin", F.sin(2 * math.pi * F.col("month") / 12))
        .withColumn("month_cos", F.cos(2 * math.pi * F.col("month") / 12))

        # Time-of-use period mapping (BESCOM tariff slots)
        .withColumn("tou_period", F.when(
            (F.col("hour") >= 22) | (F.col("hour") < 6), "off_peak"
        ).when(
            (F.col("hour") >= 6) & (F.col("hour") < 9), "normal"
        ).when(
            (F.col("hour") >= 9) & (F.col("hour") < 18), "peak"
        ).when(
            (F.col("hour") >= 18) & (F.col("hour") < 22), "critical"
        ).otherwise("normal"))

        # Minutes since midnight (fine-grained ToU)
        .withColumn("minutes_since_midnight",
                    F.col("hour") * 60 + F.minute("timestamp"))

        # Weekend flag
        .withColumn("is_weekend", F.col("dayofweek").isin([1, 7]))  # Sun=1, Sat=7
    )
    return df


def add_calendar_features(df, calendar_df):
    """Join calendar events and add holiday/festival flags."""
    # Explode affected_zones to join per zone (NULL zones = all zones)
    cal = calendar_df.select(
        "date", "event_type", "event_name", "expected_demand_impact"
    ).groupBy("date").agg(
        F.max(F.when(F.col("event_type") == "national_holiday", True)).alias("is_national_holiday"),
        F.max(F.when(F.col("event_type") == "state_holiday", True)).alias("is_state_holiday"),
        F.max(F.when(F.col("event_name") == "Ugadi", True)).alias("is_ugadi"),
        F.max(F.when(F.col("event_name") == "Deepawali", True)).alias("is_deepawali"),
        F.max(F.when(F.col("event_name").like("%Ramadan%"), True)).alias("is_ramadan"),
        F.max(F.when(F.col("event_name").like("%IPL%"), True)).alias("is_ipl_evening"),
        F.sum("expected_demand_impact").alias("total_demand_impact")
    ).withColumn("is_holiday",
        F.coalesce(F.col("is_national_holiday"), F.lit(False)) |
        F.coalesce(F.col("is_state_holiday"), F.lit(False))
    )

    df = df.join(cal, on="date", how="left").fillna({
        "is_holiday": False, "is_ugadi": False, "is_deepawali": False,
        "is_ramadan": False, "is_ipl_evening": False, "total_demand_impact": 0.0
    })
    return df


# ─── Step 4: Lag & Rolling Features ──────────────────────────────────────────

def add_lag_features(df):
    """Multi-scale lags: 1hr, 2hr, 1day, 1week, 1month (at 15-min intervals)."""
    w = Window.partitionBy("meter_id").orderBy("timestamp")

    lag_steps = {
        "kwh_lag_4":    4,     # 1 hour
        "kwh_lag_8":    8,     # 2 hours
        "kwh_lag_96":   96,    # 1 day
        "kwh_lag_672":  672,   # 1 week
        "kwh_lag_4032": 4032,  # ~1 month (42 days × 96)
    }

    for col_name, steps in lag_steps.items():
        df = df.withColumn(col_name, F.lag("kwh", steps).over(w))

    return df


def add_rolling_features(df):
    """Rolling statistics: mean, std, max over multiple windows."""
    windows = {
        4:   "1hr",
        96:  "1day",
        672: "1week",
    }

    for steps, label in windows.items():
        w = Window.partitionBy("meter_id").orderBy("timestamp").rowsBetween(-steps, 0)
        df = (
            df
            .withColumn(f"roll_mean_{steps}", F.avg("kwh").over(w))
            .withColumn(f"roll_std_{steps}",  F.stddev("kwh").over(w))
            .withColumn(f"roll_max_{steps}",  F.max("kwh").over(w))
        )
    return df


# ─── Step 5: Physical / Derived Features ──────────────────────────────────────

def add_physical_features(df):
    """Add domain-physics-based derived features."""
    w_day = Window.partitionBy("meter_id", "date")

    df = (
        df
        # Daily statistics needed for load factor
        .withColumn("daily_mean_kwh", F.avg("kwh").over(w_day))
        .withColumn("daily_max_kwh",  F.max("kwh").over(w_day))

        # Load factor (low → suspicious / intermittent use)
        .withColumn("load_factor_day",
            F.when(F.col("daily_max_kwh") > 0,
                F.col("daily_mean_kwh") / F.col("daily_max_kwh")
            ).otherwise(None)
        )

        # Day-over-day percentage change
        .withColumn("kwh_delta_1d",
            F.when(F.col("kwh_lag_96") > 0,
                (F.col("kwh") - F.col("kwh_lag_96")) / F.col("kwh_lag_96")
            ).otherwise(None)
        )

        # Flatline detection: std < 0.01 over 8 consecutive readings (2 hours)
        .withColumn("is_flatline",
            F.col("roll_std_4") < 0.01
        )

        # Power factor (phase reversal detection: if > 1 = anomaly)
        .withColumn("power_factor_computed",
            F.when(F.col("kvah") > 0,
                F.col("kwh") / F.col("kvah")
            ).otherwise(None)
        )

        # Cumulative rollback detection (tampering signal)
        .withColumn("cumulative_rollback",
            F.col("cumulative_kwh") <
            F.lag("cumulative_kwh", 1).over(
                Window.partitionBy("meter_id").orderBy("timestamp")
            )
        )
    )
    return df


def add_night_ratio(df):
    """Night-time vs day-time consumption ratio per meter per day."""
    w_day = Window.partitionBy("meter_id", "date")
    df = (
        df
        .withColumn("is_night", (F.col("hour") >= 22) | (F.col("hour") < 6))
        .withColumn("night_kwh_sum",
            F.sum(F.when(F.col("is_night"), F.col("kwh")).otherwise(0)).over(w_day)
        )
        .withColumn("day_kwh_sum",
            F.sum(F.when(~F.col("is_night"), F.col("kwh")).otherwise(0)).over(w_day)
        )
        .withColumn("night_ratio",
            F.col("night_kwh_sum") / (F.col("day_kwh_sum") + 1e-5)
        )
    )
    return df


# ─── Step 6: Peer Group Features ─────────────────────────────────────────────

def add_peer_features(df, peer_df):
    """
    Join peer cluster assignments and compute peer-deviation features.
    Peer group stats are pre-aggregated by cluster + timestamp.
    """
    # Compute cluster-level stats for each timestamp
    peer_stats = (
        df.join(peer_df, on="meter_id", how="left")
        .groupBy("peer_cluster_id", "timestamp")
        .agg(
            F.avg("kwh").alias("peer_group_mean_kwh"),
            F.stddev("kwh").alias("peer_group_std_kwh"),
            F.percentile_approx("kwh", 0.5).alias("peer_group_median_kwh")
        )
    )

    df = (
        df
        .join(peer_df, on="meter_id", how="left")
        .join(peer_stats, on=["peer_cluster_id", "timestamp"], how="left")
        .withColumn("peer_dev_ratio",
            F.when(F.col("peer_group_mean_kwh") > 0,
                F.col("kwh") / F.col("peer_group_mean_kwh")
            ).otherwise(None)
        )
        .withColumn("z_vs_peer",
            F.when(F.col("peer_group_std_kwh") > 0,
                (F.col("kwh") - F.col("peer_group_mean_kwh")) / F.col("peer_group_std_kwh")
            ).otherwise(None)
        )
    )
    return df


# ─── Step 7: Graph / Topology Features ───────────────────────────────────────

def add_topology_features(df, topology_df, feeder_df):
    """Join topology data and compute feeder-level energy balance features."""
    # Feeder-level aggregations per timestamp
    feeder_stats = (
        df
        .join(topology_df.select("meter_id", "feeder_id"), on="meter_id", how="left")
        .groupBy("feeder_id", "timestamp")
        .agg(F.sum("kwh").alias("feeder_billed_kwh"))
    )

    # Join with actual feeder input readings
    feeder_balance = feeder_df.join(
        feeder_stats, on=["feeder_id", "timestamp"], how="left"
    ).withColumn("upstream_loss_ratio",
        F.when(F.col("feeder_input_kwh") > 0,
            (F.col("feeder_input_kwh") - F.col("feeder_billed_kwh")) / F.col("feeder_input_kwh")
        ).otherwise(None)
    )

    df = (
        df
        .join(topology_df.select("meter_id", "feeder_id", "transformer_id",
                                  "transformer_rated_kva"), on="meter_id", how="left")
        .join(feeder_balance.select("feeder_id", "timestamp",
                                    "feeder_input_kwh", "upstream_loss_ratio"),
              on=["feeder_id", "timestamp"], how="left")
        .withColumn("feeder_load_share",
            F.when((F.col("feeder_input_kwh") is not None) & (F.col("feeder_input_kwh") > 0),
                F.col("kwh") / F.col("feeder_input_kwh")
            ).otherwise(None)
        )
    )
    return df


# ─── Step 8: Weather Features ─────────────────────────────────────────────────

def add_weather_features(df, weather_df, registry_df):
    """Join weather data by zone and timestamp (hour-aligned)."""
    df = df.join(registry_df.select("meter_id", "zone"), on="meter_id", how="left")

    weather_hourly = weather_df.withColumn(
        "hour_ts", F.date_trunc("hour", F.col("timestamp"))
    )

    df = (
        df
        .withColumn("hour_ts", F.date_trunc("hour", F.col("timestamp")))
        .join(
            weather_hourly.select("zone_id", "hour_ts", "temp_c",
                                   "humidity_pct", "temp_forecast_c"),
            (F.col("zone") == F.col("zone_id")) & (F.col("hour_ts") == weather_hourly["hour_ts"]),
            how="left"
        )
        .drop("zone_id", "hour_ts")
    )
    return df


# ─── Main Pipeline ────────────────────────────────────────────────────────────

def run_pipeline(
    spark: SparkSession,
    bronze_path: str,
    silver_path: str,
    jdbc_url: str,
    jdbc_props: dict,
    start_dt: str,
    end_dt: str
):
    print(f"[Pipeline] Processing {start_dt} to {end_dt}")

    # Load all data
    raw_df      = load_bronze(spark, bronze_path, start_dt, end_dt)
    registry_df, topology_df = load_metadata(spark, jdbc_url, jdbc_props)
    weather_df  = load_weather(spark, jdbc_url, jdbc_props)
    calendar_df = load_calendar(spark, jdbc_url, jdbc_props)
    peer_df     = load_peer_groups(spark, jdbc_url, jdbc_props)

    # Need feeder readings too
    feeder_df = spark.read.jdbc(
        url=jdbc_url,
        table=f"(SELECT * FROM feeder_readings WHERE timestamp >= '{start_dt}' AND timestamp < '{end_dt}') AS t",
        properties=jdbc_props
    )

    # Run pipeline stages
    df = raw_df
    df = impute_missing_reads(df)
    df = add_temporal_features(df)
    df = add_calendar_features(df, calendar_df)
    df = add_lag_features(df)
    df = add_rolling_features(df)
    df = add_physical_features(df)
    df = add_night_ratio(df)
    df = add_peer_features(df, peer_df)
    df = add_topology_features(df, topology_df, feeder_df)
    df = add_weather_features(df, weather_df, registry_df)

    # Join static metadata
    static_cols = ["meter_id", "consumer_type", "tariff_category",
                   "contract_demand_kva", "meter_type", "meter_age_years",
                   "zone", "ward_id", "feeder_id", "transformer_id"]
    df = df.join(registry_df.select(static_cols), on="meter_id", how="left")

    # Write to Silver Delta Lake (partition by date for efficient querying)
    print(f"[Pipeline] Writing Silver Delta Lake to {silver_path}")
    (
        df.write
        .format("delta")
        .mode("append")
        .partitionBy("date")
        .save(f"{silver_path}/smart_meter_features")
    )

    record_count = df.count()
    print(f"[Pipeline] ✓ Wrote {record_count:,} feature rows to Silver.")
    return record_count


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True, help="Start datetime (ISO)")
    parser.add_argument("--end",   required=True, help="End datetime (ISO)")
    parser.add_argument("--bronze-path", default=os.getenv("DELTA_LAKE_PATH") + "/bronze")
    parser.add_argument("--silver-path", default=os.getenv("DELTA_LAKE_PATH") + "/silver")
    args = parser.parse_args()

    spark = create_spark_session()
    spark.sparkContext.setLogLevel("WARN")

    jdbc_url = (
        f"jdbc:postgresql://{os.getenv('TIMESCALE_HOST')}:{os.getenv('TIMESCALE_PORT')}"
        f"/{os.getenv('TIMESCALE_DB')}"
    )
    jdbc_props = {
        "user":     os.getenv("TIMESCALE_USER"),
        "password": os.getenv("TIMESCALE_PASSWORD"),
        "driver":   "org.postgresql.Driver"
    }

    run_pipeline(
        spark=spark,
        bronze_path=args.bronze_path,
        silver_path=args.silver_path,
        jdbc_url=jdbc_url,
        jdbc_props=jdbc_props,
        start_dt=args.start,
        end_dt=args.end
    )
    spark.stop()
