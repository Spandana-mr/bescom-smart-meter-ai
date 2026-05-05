"""
ml/demand_forecasting/lightgbm_forecaster.py

LightGBM demand forecasting model — tabular champion for feeder/zone-level forecasting.
Trained on LSTM residuals (stacking). Produces 3 quantile forecasts: 10th, 50th, 90th.
SHAP TreeExplainer provides feature importance for every prediction.

Paper references:
- P6 (MAPIE): conformal prediction intervals
- P9 (SHAP): TreeSHAP explainability
"""

import os
import json
import pickle
from typing import Optional
import numpy as np
import pandas as pd
import lightgbm as lgb
import shap
from mapie.regression import MapieRegressor
from sklearn.model_selection import KFold
import mlflow
import mlflow.lightgbm
import optuna
from loguru import logger

from ml.training.walk_forward_cv import walk_forward_cv


# ─── Feature Columns (must match spark_pipeline output) ──────────────────────

TEMPORAL_FEATURES = [
    "hour_sin", "hour_cos", "dow_sin", "dow_cos", "month_sin", "month_cos",
    "minutes_since_midnight", "is_weekend", "is_holiday", "is_ugadi",
    "is_deepawali", "is_ramadan", "is_ipl_evening", "total_demand_impact",
    "tou_period",  # will be label-encoded
]

LAG_FEATURES = [
    "kwh_lag_4", "kwh_lag_8", "kwh_lag_96", "kwh_lag_672", "kwh_lag_4032",
]

ROLLING_FEATURES = [
    "roll_mean_4", "roll_mean_96", "roll_mean_672",
    "roll_std_4",  "roll_std_96",  "roll_std_672",
    "roll_max_96", "roll_max_672",
]

PHYSICAL_FEATURES = [
    "load_factor_day", "kwh_delta_1d", "is_flatline",
    "power_factor_computed", "night_ratio",
]

PEER_FEATURES = [
    "peer_group_mean_kwh", "peer_group_std_kwh", "peer_dev_ratio", "z_vs_peer",
]

TOPOLOGY_FEATURES = [
    "feeder_load_share", "upstream_loss_ratio",
]

WEATHER_FEATURES = [
    "temp_c", "humidity_pct", "temp_forecast_c",
]

STATIC_FEATURES = [
    "consumer_type", "tariff_category", "contract_demand_kva",
    "meter_age_years", "meter_type",
]

ALL_FEATURES = (
    TEMPORAL_FEATURES + LAG_FEATURES + ROLLING_FEATURES +
    PHYSICAL_FEATURES + PEER_FEATURES + TOPOLOGY_FEATURES +
    WEATHER_FEATURES + STATIC_FEATURES
)

TARGET_COL = "kwh"


# ─── Base LightGBM Config ────────────────────────────────────────────────────

BASE_LGB_PARAMS = {
    "objective":         "quantile",
    "alpha":             0.5,       # median; override per quantile model
    "num_leaves":        63,
    "learning_rate":     0.03,
    "n_estimators":      2000,
    "min_child_samples": 20,
    "subsample":         0.8,
    "colsample_bytree":  0.8,
    "reg_alpha":         0.1,
    "reg_lambda":        0.1,
    "verbose":           -1,
    "n_jobs":            -1,
}

QUANTILES = [0.1, 0.5, 0.9]   # lower, median, upper


# ─── Optuna HPO ──────────────────────────────────────────────────────────────

def build_optuna_objective(X_train: pd.DataFrame, y_train: pd.Series, quantile: float = 0.5):
    """Returns Optuna objective for LightGBM HPO."""
    def objective(trial: optuna.Trial) -> float:
        params = {
            "objective":         "quantile",
            "alpha":             quantile,
            "num_leaves":        trial.suggest_int("num_leaves", 20, 150),
            "learning_rate":     trial.suggest_float("learning_rate", 0.005, 0.1, log=True),
            "n_estimators":      trial.suggest_int("n_estimators", 500, 5000),
            "min_child_samples": trial.suggest_int("min_child_samples", 5, 100),
            "subsample":         trial.suggest_float("subsample", 0.5, 1.0),
            "colsample_bytree":  trial.suggest_float("colsample_bytree", 0.5, 1.0),
            "reg_alpha":         trial.suggest_float("reg_alpha", 1e-8, 10.0, log=True),
            "reg_lambda":        trial.suggest_float("reg_lambda", 1e-8, 10.0, log=True),
            "min_split_gain":    trial.suggest_float("min_split_gain", 0.0, 0.5),
            "verbose":           -1,
        }
        # Walk-forward CV: 3 folds, 30-day train + 7-day validation
        mapes = walk_forward_cv(
            model_class=lgb.LGBMRegressor,
            params=params,
            X=X_train, y=y_train,
            n_splits=3,
            train_days=30,
            val_days=7,
            ts_col="timestamp",  # or index
        )
        return float(np.mean(mapes))
    return objective


def run_hpo(X_train: pd.DataFrame, y_train: pd.Series,
            n_trials: int = 100, quantile: float = 0.5) -> dict:
    """Run Optuna HPO for LightGBM, return best params."""
    study = optuna.create_study(
        direction="minimize",
        study_name=f"lgbm_q{int(quantile*100)}",
        sampler=optuna.samplers.TPESampler(multivariate=True, seed=42),
    )
    study.optimize(
        build_optuna_objective(X_train, y_train, quantile),
        n_trials=n_trials,
        n_jobs=4,
        show_progress_bar=True,
    )
    best = {**BASE_LGB_PARAMS, **study.best_params, "alpha": quantile}
    logger.info(f"Best params (q={quantile}): {best}")
    return best


# ─── Training ────────────────────────────────────────────────────────────────

class LightGBMForecaster:
    """
    Three-quantile LightGBM demand forecaster.
    Produces: lower_bound (q10), forecast (q50), upper_bound (q90).
    Uses SHAP TreeExplainer for feature attribution.
    """

    def __init__(self, params_q10=None, params_q50=None, params_q90=None):
        self.params = {
            0.1: params_q10 or {**BASE_LGB_PARAMS, "alpha": 0.1},
            0.5: params_q50 or {**BASE_LGB_PARAMS, "alpha": 0.5},
            0.9: params_q90 or {**BASE_LGB_PARAMS, "alpha": 0.9},
        }
        self.models: dict[float, lgb.LGBMRegressor] = {}
        self.mapie_model: Optional[MapieRegressor] = None
        self.explainer: Optional[shap.TreeExplainer] = None
        self.feature_names: list[str] = []

    def _prepare_X(self, df: pd.DataFrame) -> pd.DataFrame:
        """Select and encode features."""
        available = [f for f in ALL_FEATURES if f in df.columns]
        X = df[available].copy()

        # Label encode categoricals
        for col in ["consumer_type", "tariff_category", "meter_type", "tou_period"]:
            if col in X.columns:
                X[col] = X[col].astype("category").cat.codes

        self.feature_names = list(X.columns)
        return X

    def fit(self, train_df: pd.DataFrame, run_hpo: bool = False, n_hpo_trials: int = 100):
        """Train 3 quantile models. Optionally run HPO first."""
        X_train = self._prepare_X(train_df)
        y_train = train_df[TARGET_COL].values

        with mlflow.start_run(run_name="lgbm_forecaster", nested=True):
            mlflow.log_param("n_features", len(self.feature_names))
            mlflow.log_param("n_train_samples", len(X_train))

            for q in QUANTILES:
                logger.info(f"Training LightGBM q={q}...")

                if run_hpo:
                    self.params[q] = run_hpo(X_train, pd.Series(y_train),
                                              n_trials=n_hpo_trials, quantile=q)

                model = lgb.LGBMRegressor(**self.params[q])
                model.fit(
                    X_train, y_train,
                    eval_set=[(X_train, y_train)],
                    callbacks=[lgb.early_stopping(50, verbose=False), lgb.log_evaluation(200)],
                )
                self.models[q] = model
                mlflow.lightgbm.log_model(model, f"lgbm_q{int(q*100)}")
                logger.info(f"✓ LightGBM q={q} trained. n_trees={model.n_estimators_}")

            # Fit MAPIE conformal wrapper on median model (P6)
            logger.info("Fitting MAPIE conformal prediction wrapper...")
            self.mapie_model = MapieRegressor(
                estimator=self.models[0.5],
                method="plus",
                cv=5,
            )
            self.mapie_model.fit(X_train, y_train)
            logger.info("✓ MAPIE fitted.")

            # Build SHAP explainer (TreeSHAP — fast, O(polynomial))
            self.explainer = shap.TreeExplainer(self.models[0.5])
            logger.info("✓ SHAP TreeExplainer ready.")

    def predict(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Returns DataFrame with columns:
        forecast_kwh, lower_bound_90, upper_bound_90, lower_bound_99, upper_bound_99
        """
        X = self._prepare_X(df)

        q10 = self.models[0.1].predict(X)
        q50 = self.models[0.5].predict(X)
        q90 = self.models[0.9].predict(X)

        # Conformal prediction intervals (P6 — distribution-free coverage guarantee)
        _, y_pis_90 = self.mapie_model.predict(X, alpha=[0.10])  # 90% coverage
        _, y_pis_99 = self.mapie_model.predict(X, alpha=[0.01])  # 99% coverage

        result = pd.DataFrame({
            "forecast_kwh":    np.maximum(q50, 0),
            "lower_bound_10":  np.maximum(q10, 0),
            "upper_bound_90":  np.maximum(q90, 0),
            "lower_bound_90":  np.maximum(y_pis_90[:, 0, 0], 0),
            "upper_bound_90_conformal": np.maximum(y_pis_90[:, 1, 0], 0),
            "lower_bound_99":  np.maximum(y_pis_99[:, 0, 0], 0),
            "upper_bound_99":  np.maximum(y_pis_99[:, 1, 0], 0),
        }, index=df.index)

        return result

    def explain(self, df: pd.DataFrame, max_samples: int = 500) -> dict:
        """
        Compute SHAP values for up to max_samples rows.
        Returns dict with shap_values array and feature names.
        """
        X = self._prepare_X(df.head(max_samples))
        shap_values = self.explainer.shap_values(X)

        return {
            "shap_values":   shap_values.tolist(),
            "feature_names": self.feature_names,
            "base_value":    float(self.explainer.expected_value),
        }

    def explain_single(self, row: pd.Series) -> list[dict]:
        """
        Explain a single meter reading. Returns sorted list of
        {feature, shap_value, direction} for NL summary generation.
        """
        X = self._prepare_X(pd.DataFrame([row]))
        shap_vals = self.explainer.shap_values(X)[0]

        contributions = sorted(
            [
                {
                    "feature":    feat,
                    "value":      float(X[feat].iloc[0]),
                    "shap_value": float(sv),
                    "direction":  "increased" if sv > 0 else "decreased",
                }
                for feat, sv in zip(self.feature_names, shap_vals)
            ],
            key=lambda x: abs(x["shap_value"]),
            reverse=True,
        )
        return contributions[:10]  # top 10 features

    def save(self, path: str):
        """Persist models to disk."""
        os.makedirs(path, exist_ok=True)
        for q, model in self.models.items():
            model.booster_.save_model(os.path.join(path, f"lgbm_q{int(q*100)}.txt"))
        with open(os.path.join(path, "mapie.pkl"), "wb") as f:
            pickle.dump(self.mapie_model, f)
        with open(os.path.join(path, "config.json"), "w") as f:
            json.dump({"feature_names": self.feature_names, "quantiles": QUANTILES}, f)
        logger.info(f"✓ Models saved to {path}")

    @classmethod
    def load(cls, path: str) -> "LightGBMForecaster":
        """Load models from disk."""
        instance = cls()
        for q in QUANTILES:
            booster = lgb.Booster(model_file=os.path.join(path, f"lgbm_q{int(q*100)}.txt"))
            model = lgb.LGBMRegressor()
            model._Booster = booster
            instance.models[q] = model
        with open(os.path.join(path, "mapie.pkl"), "rb") as f:
            instance.mapie_model = pickle.load(f)
        with open(os.path.join(path, "config.json")) as f:
            cfg = json.load(f)
            instance.feature_names = cfg["feature_names"]
        instance.explainer = shap.TreeExplainer(instance.models[0.5])
        logger.info(f"✓ LightGBMForecaster loaded from {path}")
        return instance
