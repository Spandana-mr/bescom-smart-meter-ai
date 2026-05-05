"""
ml/anomaly_detection/eif_detector.py  (also contains BOCPD + MetaClassifier)

Detector 2: Extended Isolation Forest (EIF) — P4 (Hariri et al., IEEE TKDE 2019)
Detector 3: Bayesian Online Changepoint Detection — P5 (Adams & MacKay, 2007)
Meta-Classifier: Calibrated logistic regression combining all detector scores
"""

import os
import json
import pickle
import hashlib
from functools import partial
from typing import Optional
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.calibration import CalibratedClassifierCV
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import f1_score, roc_auc_score, precision_score, recall_score
import mlflow
from loguru import logger

# EIF — pip install eif
try:
    import eif as iso
    EIF_AVAILABLE = True
except ImportError:
    logger.warning("eif package not found. Run: pip install eif")
    EIF_AVAILABLE = False

# BOCPD — pip install bayesian-changepoint-detection
try:
    from bayesian_changepoint_detection.online_changepoint_detection import online_changepoint_detection
    import bayesian_changepoint_detection.hazard_functions as hf
    from scipy.stats import t as student_t
    BOCPD_AVAILABLE = True
except ImportError:
    logger.warning("bayesian_changepoint_detection not found.")
    BOCPD_AVAILABLE = False


# ─── EIF Detector ──────────────────────────────────────────────────────────────

# Feature columns for EIF daily feature vector (29-dim)
EIF_FEATURE_COLS = [
    # 24 hourly mean kWh values (0..23)
    *[f"hour_{h:02d}_mean_kwh" for h in range(24)],
    # 5 derived daily features
    "load_factor_day", "night_ratio", "z_vs_peer", "kwh_delta_1d", "is_flatline",
]


def build_daily_features(df: pd.DataFrame) -> np.ndarray:
    """
    Build daily feature vector per meter.
    df: readings for ONE meter, multi-day.
    Returns: (n_days, 29) array.
    """
    df = df.copy()
    df["hour"] = pd.to_datetime(df["timestamp"]).dt.hour
    df["date"] = pd.to_datetime(df["timestamp"]).dt.date

    # Hourly means per day
    hourly = (
        df.groupby(["date", "hour"])["kwh"]
        .mean()
        .unstack("hour")
        .fillna(0)
        .reindex(columns=range(24), fill_value=0)
    )
    hourly.columns = [f"hour_{h:02d}_mean_kwh" for h in hourly.columns]

    # Daily derived features (take last value per day as proxy)
    daily_feats = df.groupby("date").agg(
        load_factor_day=("load_factor_day", "mean"),
        night_ratio=("night_ratio", "mean"),
        z_vs_peer=("z_vs_peer", "mean"),
        kwh_delta_1d=("kwh_delta_1d", "last"),
        is_flatline=("is_flatline", "max"),
    )

    combined = hourly.join(daily_feats, how="left").fillna(0)
    return combined.values.astype(np.float32), combined.index.tolist()


class EIFDetector:
    """
    Extended Isolation Forest anomaly detector.
    Trains on normal meter daily feature vectors. Scores new days.
    """

    def __init__(self, ntrees: int = 200, sample_size: int = 256, extension_level: int = 1):
        self.ntrees          = ntrees
        self.sample_size     = sample_size
        self.extension_level = extension_level
        self.model_          = None
        self.calibrator_     = None   # isotonic regression for probability calibration
        self.threshold_      = None

    def fit(self, X_normal: np.ndarray, X_labeled: Optional[np.ndarray] = None,
            y_labeled: Optional[np.ndarray] = None):
        """
        X_normal: normal daily feature vectors (n_days, 29) — no labels needed.
        X_labeled, y_labeled: optional labeled data for calibration.
        """
        if not EIF_AVAILABLE:
            raise ImportError("pip install eif")

        logger.info(f"Training EIF on {len(X_normal):,} normal days...")
        self.model_ = iso.iForest(
            X_normal,
            ntrees=self.ntrees,
            sample_size=self.sample_size,
            ExtensionLevel=self.extension_level,
        )

        # Compute threshold at 99th percentile of normal scores
        normal_scores = self.model_.compute_paths(X_normal)
        self.threshold_ = float(np.percentile(normal_scores, 99))
        logger.info(f"EIF threshold (p99): {self.threshold_:.4f}")

        # Calibrate to probabilities if labeled data available
        if X_labeled is not None and y_labeled is not None:
            raw_scores = self.model_.compute_paths(X_labeled).reshape(-1, 1)
            scaler = StandardScaler()
            raw_scaled = scaler.fit_transform(raw_scores)
            self.calibrator_ = CalibratedClassifierCV(
                LogisticRegression(C=1.0), cv=5, method="isotonic"
            )
            self.calibrator_.fit(raw_scaled, y_labeled)
            y_pred = self.calibrator_.predict_proba(raw_scaled)[:, 1] > 0.5
            logger.info(f"EIF calibrated F1: {f1_score(y_labeled, y_pred):.3f}")

    def score(self, X: np.ndarray) -> np.ndarray:
        """Raw EIF path scores (higher = more anomalous)."""
        return self.model_.compute_paths(X)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Calibrated probability of anomaly in [0,1]."""
        raw = self.model_.compute_paths(X)
        if self.calibrator_ is not None:
            scaler = StandardScaler()
            raw_scaled = scaler.fit_transform(raw.reshape(-1, 1))
            return self.calibrator_.predict_proba(raw_scaled)[:, 1]
        else:
            # Sigmoid-based fallback
            centered = raw - self.threshold_
            return 1 / (1 + np.exp(-centered * 5))

    def save(self, path: str):
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(path, "eif.pkl"), "wb") as f:
            pickle.dump(self, f)

    @classmethod
    def load(cls, path: str) -> "EIFDetector":
        with open(os.path.join(path, "eif.pkl"), "rb") as f:
            return pickle.load(f)


# ─── BOCPD Detector ──────────────────────────────────────────────────────────

class BOCPDDetector:
    """
    Bayesian Online Changepoint Detection (P5 — Adams & MacKay, 2007).
    Detects the exact timestamp at which a meter's consumption distribution
    structurally shifts — without needing labeled examples.
    Runs online (O(1) per new data point).
    """

    def __init__(self, lambda_param: float = 250, prob_threshold: float = 0.5):
        """
        lambda_param: expected run length between changepoints.
            250 ≈ expect structural break every ~2.5 days at 15-min intervals.
        prob_threshold: posterior probability threshold to declare a changepoint.
        """
        self.lambda_param   = lambda_param
        self.prob_threshold = prob_threshold

    def detect(self, series: np.ndarray, timestamps: list) -> list[dict]:
        """
        Detect changepoints in a 1D time series.
        Returns list of {timestamp, probability, index} for detected changepoints.
        """
        if not BOCPD_AVAILABLE:
            raise ImportError("pip install bayesian-changepoint-detection")

        # Student-T hazard model (conjugate prior for unknown mean & variance)
        R, maxes = online_changepoint_detection(
            series,
            partial(hf.constant_hazard, self.lambda_param),
            self._student_t_model(),
        )

        changepoint_indices = np.where(maxes > self.prob_threshold)[0]

        results = []
        for idx in changepoint_indices:
            if idx < len(timestamps):
                results.append({
                    "index":       int(idx),
                    "timestamp":   timestamps[idx],
                    "probability": float(maxes[idx]),
                })

        return results

    def _student_t_model(self):
        """Student-T conjugate prior for online Bayesian updating."""
        class StudentT:
            def __init__(self):
                self.alpha  = 0.1
                self.beta   = 0.01
                self.kappa  = 1.0
                self.mu     = 0.0

            def pdf(self, data, r, t):
                # Predictive distribution: t-distribution with 2*alpha DOF
                from scipy.stats import t as scipy_t
                df    = 2 * self.alpha
                loc   = self.mu
                scale = np.sqrt(self.beta * (self.kappa + 1) / (self.alpha * self.kappa))
                return scipy_t.pdf(data, df, loc=loc, scale=scale)

            def update_params(self, data):
                self.kappa += 1
                self.mu = (self.kappa * self.mu + data) / (self.kappa + 1)
                self.alpha += 0.5
                self.beta += 0.5 * self.kappa / (self.kappa + 1) * (data - self.mu) ** 2

        return StudentT()

    def has_recent_changepoint(self, series: np.ndarray, timestamps: list,
                                lookback_steps: int = 672) -> bool:
        """Check if there's a changepoint in the last `lookback_steps` intervals (default 1 week)."""
        recent = series[-lookback_steps:] if len(series) > lookback_steps else series
        recent_ts = timestamps[-lookback_steps:] if len(timestamps) > lookback_steps else timestamps
        changepoints = self.detect(recent, recent_ts)
        return len(changepoints) > 0

    def annotate_with_calendar(self, changepoints: list[dict],
                                calendar_events: pd.DataFrame) -> list[dict]:
        """
        Check if each changepoint is explained by a known calendar event.
        Returns changepoints with has_calendar_explanation flag.
        """
        if calendar_events is None or len(calendar_events) == 0:
            for cp in changepoints:
                cp["has_calendar_explanation"] = False
            return changepoints

        event_dates = set(pd.to_datetime(calendar_events["date"]).dt.date.tolist())

        for cp in changepoints:
            cp_date = pd.to_datetime(cp["timestamp"]).date()
            # Check ±2 days for calendar events
            nearby_dates = {
                cp_date + pd.Timedelta(days=d)
                for d in range(-2, 3)
            }
            cp["has_calendar_explanation"] = bool(nearby_dates & event_dates)

        return changepoints


# ─── Meta-Classifier ──────────────────────────────────────────────────────────

class MetaClassifier:
    """
    Calibrated logistic regression that combines outputs from all 4 detectors
    into a single theft_probability score.

    Features:
        vae_score, eif_score, bocpd_detected, gnn_node_score, gnn_balance_score,
        peer_z_score, load_factor, night_ratio, is_flatline

    Trained on confirmed inspection_records (ground truth labels).
    """

    META_FEATURES = [
        "vae_score",
        "eif_score",
        "bocpd_detected",
        "gnn_node_score",
        "gnn_balance_score",
        "peer_z_score",
        "load_factor_day",
        "night_ratio",
        "is_flatline",
    ]

    def __init__(self, C: float = 0.1, cv: int = 5):
        self.C  = C
        self.cv = cv
        self.model_     : Optional[CalibratedClassifierCV] = None
        self.feature_names = self.META_FEATURES

    def fit(self, df: pd.DataFrame, y: np.ndarray):
        """
        df: DataFrame with meta_features columns.
        y: binary array (1 = theft, 0 = normal).
        """
        X = df[self.META_FEATURES].fillna(0).values

        base_clf = LogisticRegression(C=self.C, max_iter=1000, random_state=42)
        self.model_ = CalibratedClassifierCV(base_clf, cv=self.cv, method="isotonic")
        self.model_.fit(X, y)

        # Log performance
        y_pred_proba = self.model_.predict_proba(X)[:, 1]
        y_pred       = (y_pred_proba > 0.5).astype(int)

        with mlflow.start_run(run_name="meta_classifier", nested=True):
            mlflow.log_metric("train_f1",        f1_score(y, y_pred))
            mlflow.log_metric("train_auc_pr",    roc_auc_score(y, y_pred_proba))
            mlflow.log_metric("train_precision",  precision_score(y, y_pred))
            mlflow.log_metric("train_recall",     recall_score(y, y_pred))
            mlflow.log_param("C", self.C)

        logger.info(
            f"MetaClassifier trained | "
            f"F1={f1_score(y, y_pred):.3f} | "
            f"AUC-PR={roc_auc_score(y, y_pred_proba):.3f} | "
            f"n_samples={len(y)} (theft={y.sum()}, normal={(1-y).sum()})"
        )

    def predict_proba(self, df: pd.DataFrame) -> np.ndarray:
        """Returns theft_probability in [0,1] per row."""
        X = df[self.META_FEATURES].fillna(0).values
        return self.model_.predict_proba(X)[:, 1]

    def compute_urgency_score(self, df: pd.DataFrame,
                               tariff_rate_inr_per_kwh: float = 6.5) -> pd.DataFrame:
        """
        Composite alert urgency = theft_probability × estimated_revenue_loss × recency_weight.
        Drives the alert queue ranking.
        """
        theft_proba = self.predict_proba(df)

        # Estimate daily kWh stolen = peer_group_mean - actual reading
        peer_mean = df.get("peer_group_mean_kwh", pd.Series(np.zeros(len(df))))
        actual    = df.get("kwh", pd.Series(np.zeros(len(df))))
        daily_kwh_stolen = (peer_mean - actual).clip(lower=0) * 96  # 96 intervals/day

        # Estimate days since suspected onset (from BOCPD changepoint or alert creation)
        days_since_onset = df.get("days_since_changepoint", pd.Series(np.ones(len(df)) * 30))

        est_revenue_loss = daily_kwh_stolen * days_since_onset * tariff_rate_inr_per_kwh

        # Recency weight: alerts detected more recently get a slight boost
        recency_weight = 1.0  # can adjust based on detection age

        urgency = theft_proba * np.log1p(est_revenue_loss) * recency_weight

        result = df[["meter_id"]].copy() if "meter_id" in df.columns else pd.DataFrame()
        result["theft_probability"]              = theft_proba
        result["estimated_revenue_loss_inr"]     = est_revenue_loss
        result["urgency_score"]                  = urgency
        return result

    def save(self, path: str):
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(path, "meta_clf.pkl"), "wb") as f:
            pickle.dump(self.model_, f)
        with open(os.path.join(path, "meta_config.json"), "w") as f:
            json.dump({"C": self.C, "features": self.META_FEATURES}, f)

    @classmethod
    def load(cls, path: str) -> "MetaClassifier":
        with open(os.path.join(path, "meta_config.json")) as f:
            cfg = json.load(f)
        instance = cls(C=cfg["C"])
        with open(os.path.join(path, "meta_clf.pkl"), "rb") as f:
            instance.model_ = pickle.load(f)
        return instance
