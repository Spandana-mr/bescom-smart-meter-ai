"""
ml/training/walk_forward_cv.py

Walk-forward (time-series) cross-validation.
CRITICAL: Never use random splits for time-series. Always walk forward.
"""

import numpy as np
import pandas as pd
from typing import Type, Any
from sklearn.metrics import mean_absolute_percentage_error
from loguru import logger


def walk_forward_cv(
    model_class,
    params: dict,
    X: pd.DataFrame,
    y: pd.Series,
    n_splits: int = 3,
    train_days: int = 30,
    val_days: int = 7,
    ts_col: str = "timestamp",
    freq: str = "15T",
) -> list[float]:
    """
    Walk-forward cross-validation for time-series models.
    Splits data into n_splits folds, each with train_days training + val_days validation.
    Returns list of MAPE values per fold.

    Example for 3 splits, 30 train + 7 val:
        Fold 1: train [day 1–30], val [day 31–37]
        Fold 2: train [day 1–37], val [day 38–44]  ← expanding window
        Fold 3: train [day 1–44], val [day 45–51]
    """
    # Convert timestamps to indices
    if ts_col in X.columns:
        timestamps = pd.to_datetime(X[ts_col])
    elif hasattr(X.index, "freq") or hasattr(X.index, "to_pydatetime"):
        timestamps = pd.to_datetime(X.index)
    else:
        # Assume uniform 15-min intervals
        timestamps = pd.date_range(
            end=pd.Timestamp.now(), periods=len(X), freq=freq
        )

    unique_dates = pd.Series(timestamps.date).unique()
    unique_dates = sorted(unique_dates)
    total_days = len(unique_dates)

    mapes = []

    for fold in range(n_splits):
        val_end_idx   = total_days - (n_splits - fold - 1) * val_days
        val_start_idx = val_end_idx - val_days
        train_end_idx = val_start_idx

        if train_end_idx < train_days:
            logger.warning(f"Fold {fold+1}: not enough data. Skipping.")
            continue

        train_dates = unique_dates[:train_end_idx]
        val_dates   = unique_dates[val_start_idx:val_end_idx]

        train_mask = pd.Series(timestamps.date).isin(set(train_dates)).values
        val_mask   = pd.Series(timestamps.date).isin(set(val_dates)).values

        X_train, y_train = X[train_mask], y[train_mask]
        X_val,   y_val   = X[val_mask],   y[val_mask]

        # Drop timestamp col if present (not a feature)
        feat_cols = [c for c in X_train.columns if c != ts_col]
        X_train_f = X_train[feat_cols].fillna(0)
        X_val_f   = X_val[feat_cols].fillna(0)

        model = model_class(**params)
        model.fit(X_train_f, y_train)
        preds = model.predict(X_val_f)

        mape = mean_absolute_percentage_error(
            y_val.values.clip(min=1e-5), np.maximum(preds, 0)
        )
        mapes.append(mape)
        logger.info(
            f"  Fold {fold+1}/{n_splits}: "
            f"train={len(X_train):,} val={len(X_val):,} | MAPE={mape:.4f}"
        )

    logger.info(f"Walk-forward CV: mean MAPE={np.mean(mapes):.4f} ± {np.std(mapes):.4f}")
    return mapes
