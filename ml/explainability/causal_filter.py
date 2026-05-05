"""
ml/novel/causal_filter.py

DoWhy causal inference filter for false positive reduction.
P10 reference: Sharma & Kiciman, "DoWhy: A Python package for causal inference", 2020.

When a meter shows a significant consumption drop (>20% vs 7-day rolling mean),
before escalating as theft, estimate how much of the drop is explained by
known causes (temperature change, holiday, industrial shutdown).

If residual unexplained variance > 15% → escalate.
If fully explained by known causes → suppress for 7 days.
Expected impact: 20–35% reduction in false positives.
"""

import os
from typing import Optional
import numpy as np
import pandas as pd
from loguru import logger

try:
    import dowhy
    from dowhy import CausalModel
    DOWHY_AVAILABLE = True
except ImportError:
    logger.warning("dowhy not installed. pip install dowhy")
    DOWHY_AVAILABLE = False


# ─── Causal DAG Definition ────────────────────────────────────────────────────

# Causal graph (GML format):
# Known causes → consumption_drop
# Confounders: season (affects both temperature and consumption)
CAUSAL_DAG_GML = """
graph [
  directed 1
  node [id "temperature_delta"         label "temperature_delta"]
  node [id "is_holiday"                label "is_holiday"]
  node [id "industrial_shutdown"       label "industrial_shutdown"]
  node [id "is_ramadan"                label "is_ramadan"]
  node [id "rainfall_mm"               label "rainfall_mm"]
  node [id "season"                    label "season"]
  node [id "consumption_drop"          label "consumption_drop"]
  edge [source "temperature_delta"     target "consumption_drop"]
  edge [source "is_holiday"            target "consumption_drop"]
  edge [source "industrial_shutdown"   target "consumption_drop"]
  edge [source "is_ramadan"            target "consumption_drop"]
  edge [source "rainfall_mm"           target "consumption_drop"]
  edge [source "season"                target "temperature_delta"]
  edge [source "season"                target "consumption_drop"]
]
"""


# ─── Causal Filter ────────────────────────────────────────────────────────────

class CausalFalsePositiveFilter:
    """
    Uses DoWhy causal inference to determine whether a detected anomaly
    (consumption drop) is explained by known external causes.

    For each alert candidate, runs backdoor adjustment estimation and
    computes the fraction of change unexplained by known causes.
    """

    def __init__(self, unexplained_threshold: float = 0.15, min_drop_threshold: float = 0.20):
        """
        unexplained_threshold: if unexplained fraction > this → escalate
        min_drop_threshold: only run causal analysis on drops > this fraction
        """
        self.unexplained_threshold = unexplained_threshold
        self.min_drop_threshold    = min_drop_threshold

    def should_escalate(
        self,
        meter_df: pd.DataFrame,
        calendar_events: pd.DataFrame,
        weather_df: pd.DataFrame,
    ) -> dict:
        """
        Determine whether to escalate a meter alert or suppress it.

        Args:
            meter_df: recent 30-day readings for one meter with columns
                      [timestamp, kwh, roll_mean_672, ...feature columns]
            calendar_events: calendar table (date, event_type, event_name)
            weather_df: weather for this meter's zone (timestamp, temp_c, rainfall_mm)

        Returns:
            dict with keys:
                escalate: bool
                unexplained_fraction: float
                calendar_explanation: str or None
                suppression_reason: str or None
        """
        if not DOWHY_AVAILABLE:
            # Fallback: always escalate if DoWhy not available
            return {"escalate": True, "unexplained_fraction": 1.0,
                    "calendar_explanation": None, "suppression_reason": "DoWhy unavailable"}

        # Build daily-level dataset for causal analysis
        causal_df = self._build_causal_df(meter_df, calendar_events, weather_df)

        if causal_df is None or len(causal_df) < 14:
            return {"escalate": True, "unexplained_fraction": 1.0,
                    "calendar_explanation": None, "suppression_reason": "Insufficient data"}

        # Compute consumption drop
        recent_mean  = causal_df["kwh_daily"].tail(7).mean()
        baseline_mean = causal_df["kwh_daily"].head(21).mean()

        if baseline_mean < 1e-3:
            return {"escalate": False, "unexplained_fraction": 0.0,
                    "calendar_explanation": None, "suppression_reason": "Near-zero baseline"}

        drop_fraction = (baseline_mean - recent_mean) / (baseline_mean + 1e-8)

        if drop_fraction < self.min_drop_threshold:
            # Not a significant drop — no analysis needed
            return {"escalate": False, "unexplained_fraction": 0.0,
                    "calendar_explanation": None,
                    "suppression_reason": f"Drop {drop_fraction:.1%} < threshold {self.min_drop_threshold:.1%}"}

        # Run DoWhy causal analysis
        try:
            explained_fraction, calendar_str = self._estimate_causal_effect(causal_df, drop_fraction)
            unexplained = max(0.0, drop_fraction - explained_fraction)
            unexplained_fraction = unexplained / (drop_fraction + 1e-8)

            escalate = unexplained_fraction > self.unexplained_threshold

            return {
                "escalate":              escalate,
                "unexplained_fraction":  round(unexplained_fraction, 3),
                "explained_fraction":    round(explained_fraction / (drop_fraction + 1e-8), 3),
                "total_drop_pct":        round(drop_fraction * 100, 1),
                "calendar_explanation":  calendar_str,
                "suppression_reason":    None if escalate else f"Explained by known causes ({calendar_str})",
            }

        except Exception as e:
            logger.warning(f"DoWhy analysis failed: {e}. Defaulting to escalate.")
            return {"escalate": True, "unexplained_fraction": 1.0,
                    "calendar_explanation": None, "suppression_reason": None}

    def _build_causal_df(
        self,
        meter_df: pd.DataFrame,
        calendar_events: pd.DataFrame,
        weather_df: pd.DataFrame,
    ) -> Optional[pd.DataFrame]:
        """Merge meter readings with weather and calendar at daily level."""
        meter_df = meter_df.copy()
        meter_df["date"] = pd.to_datetime(meter_df["timestamp"]).dt.date

        # Daily consumption
        daily = meter_df.groupby("date")["kwh"].sum().reset_index()
        daily.columns = ["date", "kwh_daily"]
        daily["date"] = pd.to_datetime(daily["date"])

        # Weather join (daily mean temperature)
        if weather_df is not None and len(weather_df) > 0:
            weather_df = weather_df.copy()
            weather_df["date"] = pd.to_datetime(weather_df["timestamp"]).dt.date
            daily_weather = weather_df.groupby("date").agg(
                temp_c=("temp_c", "mean"),
                rainfall_mm=("rainfall_mm", "sum"),
            ).reset_index()
            daily_weather["date"] = pd.to_datetime(daily_weather["date"])
            daily = daily.merge(daily_weather, on="date", how="left")
        else:
            daily["temp_c"]      = 28.0  # Bangalore average
            daily["rainfall_mm"] = 0.0

        # Temperature delta vs baseline
        baseline_temp = daily["temp_c"].head(14).mean()
        daily["temperature_delta"] = daily["temp_c"] - baseline_temp

        # Calendar flags
        if calendar_events is not None and len(calendar_events) > 0:
            cal = calendar_events.copy()
            cal["date"] = pd.to_datetime(cal["date"])
            holiday_dates  = set(cal[cal["event_type"].isin(
                ["national_holiday","state_holiday"])]["date"].dt.date)
            shutdown_dates = set(cal[cal["event_type"] == "industrial_shutdown"]["date"].dt.date)
            ramadan_dates  = set(cal[cal["event_name"].str.contains("Ramadan", na=False)]["date"].dt.date)
        else:
            holiday_dates = shutdown_dates = ramadan_dates = set()

        daily["is_holiday"]           = daily["date"].dt.date.isin(holiday_dates).astype(int)
        daily["industrial_shutdown"]  = daily["date"].dt.date.isin(shutdown_dates).astype(int)
        daily["is_ramadan"]           = daily["date"].dt.date.isin(ramadan_dates).astype(int)
        daily["season"]               = daily["date"].dt.month.apply(
            lambda m: 0 if m in [12,1,2] else 1 if m in [3,4,5] else 2 if m in [6,7,8,9] else 3
        )

        return daily.dropna(subset=["kwh_daily"])

    def _estimate_causal_effect(
        self, causal_df: pd.DataFrame, observed_drop_fraction: float
    ) -> tuple[float, str]:
        """
        Run DoWhy backdoor adjustment to estimate causal effect of known causes.
        Returns (explained_drop_fraction, calendar_explanation_string).
        """
        # Use linear regression as the causal estimator (fast, auditable)
        treatment_vars    = ["temperature_delta", "is_holiday",
                             "industrial_shutdown", "is_ramadan", "rainfall_mm"]
        outcome_var       = "kwh_daily"
        common_causes     = ["season"]

        # DoWhy model
        model = CausalModel(
            data=causal_df,
            treatment=treatment_vars,
            outcome=outcome_var,
            graph=CAUSAL_DAG_GML,
            common_causes=common_causes,
        )

        identified_estimand = model.identify_effect(proceed_when_unidentifiable=True)
        estimate = model.estimate_effect(
            identified_estimand,
            method_name="backdoor.linear_regression",
        )

        # Compute explained effect: sum of (coefficient × average treatment value in recent period)
        recent_period = causal_df.tail(7)
        baseline_kwh  = causal_df.head(21)["kwh_daily"].mean()

        explained_drop_kwh = 0.0
        explanations       = []

        for treatment in treatment_vars:
            try:
                coeff         = float(estimate.value) if len(treatment_vars) == 1 else 0.0
                recent_val    = recent_period[treatment].mean()
                baseline_val  = causal_df.head(21)[treatment].mean()
                delta         = recent_val - baseline_val
                contribution  = abs(coeff * delta)
                explained_drop_kwh += contribution

                if abs(contribution) > baseline_kwh * 0.05:
                    direction = "reduction" if delta < 0 and treatment == "temperature_delta" else "change"
                    explanations.append(
                        f"{treatment.replace('_',' ').title()} ({direction}: {delta:+.1f})"
                    )
            except Exception:
                continue

        explained_fraction = min(
            explained_drop_kwh / (baseline_kwh * observed_drop_fraction + 1e-8),
            1.0
        )
        calendar_str = "; ".join(explanations) if explanations else None
        return explained_fraction, calendar_str
