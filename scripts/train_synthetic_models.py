"""
Train runnable synthetic-data ML baselines for the BESCOM demo backend.

This script intentionally uses only pandas + scikit-learn so it can run in the
current local environment without the heavyweight research stack. It produces:

1. Zone demand forecasting with quantile gradient boosting regressors.
2. Daily anomaly scoring with:
   - supervised RandomForest classifier using synthetic theft labels
   - unsupervised IsolationForest for novelty detection
3. JSON/CSV artifacts consumed by the FastAPI backend.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import GradientBoostingRegressor, IsolationForest, RandomForestClassifier
from sklearn.metrics import (
    average_precision_score,
    f1_score,
    mean_absolute_percentage_error,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("BESCOM_DATA_DIR", ROOT / "data" / "bescom_dataset")).resolve()
ARTIFACT_DIR = ROOT / "backend" / "artifacts" / "synthetic_ml"
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)


def _safe_metric(fn, y_true, y_score, default=0.0):
    try:
        return float(fn(y_true, y_score))
    except Exception:
        return default


def _load() -> tuple[pd.DataFrame, pd.DataFrame]:
    forecasts = pd.read_csv(DATA_DIR / "demand_forecasts.csv")
    readings = pd.read_csv(DATA_DIR / "meter_readings.csv")
    return forecasts, readings


def _forecast_features(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    dates = pd.to_datetime(result["forecast_date"])
    result["month"] = dates.dt.month
    result["dayofweek"] = dates.dt.dayofweek
    result["day"] = dates.dt.day
    result["lag_actual"] = result.groupby("zone")["actual_mw"].shift(1)
    result["lag_forecast"] = result.groupby("zone")["forecast_mw"].shift(1)
    result["lag_actual"] = result["lag_actual"].fillna(result["actual_mw"].median())
    result["lag_forecast"] = result["lag_forecast"].fillna(result["forecast_mw"].median())
    result["error_gap"] = (result["forecast_mw"] - result["actual_mw"]).fillna(0)
    return result


def train_forecaster(forecasts: pd.DataFrame) -> dict:
    df = _forecast_features(forecasts).sort_values("forecast_date")
    target = df["actual_mw"].astype(float)
    features = [
        "zone",
        "model_name",
        "peak_hour",
        "forecast_mw",
        "p10_mw",
        "p50_mw",
        "p90_mw",
        "p5_mw",
        "p95_mw",
        "confidence_level",
        "training_data_size",
        "month",
        "dayofweek",
        "day",
        "lag_actual",
        "lag_forecast",
        "error_gap",
    ]
    features = [column for column in features if column in df.columns]
    X = df[features].copy()

    split = max(20, int(len(df) * 0.8))
    X_train, X_test = X.iloc[:split], X.iloc[split:]
    y_train, y_test = target.iloc[:split], target.iloc[split:]

    categorical = [column for column in ["zone", "model_name"] if column in X.columns]
    numeric = [column for column in X.columns if column not in categorical]
    prep = ColumnTransformer(
        transformers=[
            ("cat", OneHotEncoder(handle_unknown="ignore"), categorical),
            ("num", "passthrough", numeric),
        ]
    )

    models = {}
    predictions = {}
    for label, alpha in [("p10", 0.1), ("p50", 0.5), ("p90", 0.9)]:
        estimator = GradientBoostingRegressor(
            loss="quantile",
            alpha=alpha,
            n_estimators=180,
            learning_rate=0.04,
            max_depth=3,
            random_state=42,
        )
        model = Pipeline([("prep", prep), ("model", estimator)])
        model.fit(X_train, y_train)
        pred = np.maximum(model.predict(X_test), 0)
        models[label] = model
        predictions[label] = pred

    point = predictions["p50"]
    mape = mean_absolute_percentage_error(np.maximum(y_test, 1e-6), point)
    residual = np.abs(y_train.iloc[-len(y_test):].to_numpy() - df.iloc[split - len(y_test):split]["forecast_mw"].to_numpy())
    conformal_pad = float(np.quantile(residual, 0.9)) if len(residual) else 0.0

    preview = pd.DataFrame(
        {
            "forecast_date": df.iloc[split:]["forecast_date"].astype(str).tolist(),
            "zone": df.iloc[split:]["zone"].astype(str).tolist(),
            "actual_mw": y_test.round(3).tolist(),
            "p10_mw": np.maximum(predictions["p10"], 0).round(3).tolist(),
            "p50_mw": np.maximum(predictions["p50"], 0).round(3).tolist(),
            "p90_mw": np.maximum(predictions["p90"], 0).round(3).tolist(),
            "conformal_lower_mw": np.maximum(point - conformal_pad, 0).round(3).tolist(),
            "conformal_upper_mw": (point + conformal_pad).round(3).tolist(),
        }
    ).tail(120)
    preview.to_csv(ARTIFACT_DIR / "forecast_preview.csv", index=False)

    return {
        "model": "QuantileGradientBoostingForecaster",
        "status": "trained",
        "train_rows": int(len(X_train)),
        "test_rows": int(len(X_test)),
        "features": features,
        "mape": round(float(mape), 4),
        "conformal_pad_mw": round(conformal_pad, 4),
        "artifacts": ["forecast_preview.csv"],
    }


def _daily_anomaly_features(readings: pd.DataFrame) -> pd.DataFrame:
    df = readings.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["date"] = df["timestamp"].dt.date.astype(str)
    df["hour"] = df["timestamp"].dt.hour
    hourly = (
        df.pivot_table(index=["meter_id", "zone", "date"], columns="hour", values="kwh", aggfunc="mean", fill_value=0)
        .reindex(columns=range(24), fill_value=0)
    )
    hourly.columns = [f"hour_{hour:02d}_kwh" for hour in hourly.columns]
    hourly = hourly.reset_index()

    daily = df.groupby(["meter_id", "zone", "date"], as_index=False).agg(
        total_kwh=("kwh", "sum"),
        avg_kwh=("kwh", "mean"),
        max_kwh=("kwh", "max"),
        avg_power_factor=("power_factor", "mean"),
        avg_voltage=("voltage_v", "mean"),
        avg_existing_anomaly_score=("anomaly_score", "mean"),
        peer_mean=("peer_group_mean_kwh", "mean"),
        peer_std=("peer_group_std_kwh", "mean"),
        peer_z=("z_score_vs_peer", "mean"),
        load_factor_day=("load_factor_day", "mean"),
        night_ratio=("night_ratio", "mean"),
        pct_change_1d=("pct_change_1d", "mean"),
        comms_ok_ratio=("communication_ok", lambda s: np.mean(s.astype(str).str.lower().eq("true"))),
        tamper_any=("tamper_detected", lambda s: int(s.astype(str).str.lower().eq("true").any())),
        theft_label=("is_theft_flag", lambda s: int(s.astype(str).str.lower().eq("true").any())),
    )
    daily["flatline_score"] = (daily["max_kwh"] - daily["avg_kwh"]).abs()
    combined = daily.merge(hourly, on=["meter_id", "zone", "date"], how="left").fillna(0)
    return combined


def train_anomaly_models(readings: pd.DataFrame) -> dict:
    daily = _daily_anomaly_features(readings).sort_values("date")
    target = daily["theft_label"].astype(int)
    feature_cols = [
        column
        for column in daily.columns
        if column
        not in {
            "meter_id",
            "zone",
            "date",
            "theft_label",
        }
    ]
    X = daily[feature_cols].astype(float)
    split = max(20, int(len(daily) * 0.8))
    X_train, X_test = X.iloc[:split], X.iloc[split:]
    y_train, y_test = target.iloc[:split], target.iloc[split:]

    clf = RandomForestClassifier(
        n_estimators=220,
        max_depth=10,
        min_samples_leaf=2,
        class_weight="balanced",
        random_state=42,
        n_jobs=-1,
    )
    clf.fit(X_train, y_train)
    supervised_score = clf.predict_proba(X_test)[:, 1]
    supervised_pred = (supervised_score >= 0.5).astype(int)

    normal_train = X_train[y_train == 0]
    iso = IsolationForest(
        n_estimators=220,
        contamination=max(0.01, min(0.12, float(y_train.mean() or 0.02))),
        random_state=42,
        n_jobs=-1,
    )
    iso.fit(normal_train if len(normal_train) else X_train)
    raw_iso = -iso.score_samples(X_test)
    iso_score = (raw_iso - raw_iso.min()) / (raw_iso.max() - raw_iso.min() + 1e-9)
    blended = 0.7 * supervised_score + 0.3 * iso_score
    blended_pred = (blended >= 0.5).astype(int)

    feature_importance = sorted(
        [
            {"feature": name, "importance": round(float(value), 6)}
            for name, value in zip(feature_cols, clf.feature_importances_)
        ],
        key=lambda item: item["importance"],
        reverse=True,
    )[:12]

    scored = daily.iloc[split:][["meter_id", "zone", "date", "theft_label"]].copy()
    scored["supervised_probability"] = np.round(supervised_score, 5)
    scored["isolation_probability"] = np.round(iso_score, 5)
    scored["blended_probability"] = np.round(blended, 5)
    scored["predicted_theft"] = blended_pred
    scored = scored.sort_values("blended_probability", ascending=False)
    scored.head(500).to_csv(ARTIFACT_DIR / "anomaly_scores.csv", index=False)

    return {
        "model": "SyntheticAnomalyEnsemble",
        "status": "trained",
        "train_rows": int(len(X_train)),
        "test_rows": int(len(X_test)),
        "positive_rate_train": round(float(y_train.mean()), 4),
        "supervised": {
            "roc_auc": round(_safe_metric(roc_auc_score, y_test, supervised_score), 4),
            "average_precision": round(_safe_metric(average_precision_score, y_test, supervised_score), 4),
            "precision": round(precision_score(y_test, supervised_pred, zero_division=0), 4),
            "recall": round(recall_score(y_test, supervised_pred, zero_division=0), 4),
            "f1": round(f1_score(y_test, supervised_pred, zero_division=0), 4),
        },
        "blended": {
            "roc_auc": round(_safe_metric(roc_auc_score, y_test, blended), 4),
            "average_precision": round(_safe_metric(average_precision_score, y_test, blended), 4),
            "precision": round(precision_score(y_test, blended_pred, zero_division=0), 4),
            "recall": round(recall_score(y_test, blended_pred, zero_division=0), 4),
            "f1": round(f1_score(y_test, blended_pred, zero_division=0), 4),
        },
        "feature_importance": feature_importance,
        "artifacts": ["anomaly_scores.csv"],
    }


def main() -> None:
    forecasts, readings = _load()
    summary = {
        "dataset_dir": str(DATA_DIR),
        "artifact_dir": str(ARTIFACT_DIR),
        "generated_at": pd.Timestamp.now("UTC").isoformat(),
        "forecasting": train_forecaster(forecasts),
        "anomaly_detection": train_anomaly_models(readings),
    }
    (ARTIFACT_DIR / "training_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
