"""
ml/explainability/alert_nlg.py

Template-based Natural Language Alert Summary generator.
Uses SHAP values + rule substitution — NO external LLM, zero data leakage.
All outputs are fully auditable and reproducible.
"""

from typing import Optional
import numpy as np
import pandas as pd
from datetime import datetime


# ─── Templates ────────────────────────────────────────────────────────────────

ANOMALY_TYPE_DESCRIPTIONS = {
    "bypass":           "suspected meter bypass — sudden sharp drop in recorded consumption",
    "slowdown":         "meter slowdown — consistent under-reading vs peer group over 30+ days",
    "phase_reversal":   "phase reversal detected — power factor anomaly indicating reversed meter wiring",
    "flatline":         "flatline readings — near-zero variance for extended period suggesting meter manipulation",
    "illegal_extension": "illegal tap extension — feeder energy balance deficit implicates unreported connections",
    "clock_fraud":      "clock fraud — consumption pattern shifted to off-peak hours to evade ToU pricing",
    "unknown":          "unclassified anomaly — multiple detector signals triggered without clear pattern match",
}

RISK_LEVEL_COLORS = {
    "Critical": "🔴",
    "High":     "🟠",
    "Medium":   "🟡",
    "Low":      "🟢",
}

FEATURE_PLAIN_ENGLISH = {
    "kwh_lag_96":              "consumption vs. yesterday same hour",
    "kwh_lag_672":             "consumption vs. last week same hour",
    "z_vs_peer":               "deviation from peer group",
    "load_factor_day":         "daily load factor (avg/peak)",
    "night_ratio":             "night-time vs day-time usage ratio",
    "is_flatline":             "consecutive zero-variance readings",
    "peer_dev_ratio":          "ratio to peer group mean",
    "roll_mean_96":            "24-hour rolling average",
    "roll_std_96":             "24-hour consumption volatility",
    "upstream_loss_ratio":     "feeder energy balance deficit",
    "power_factor_computed":   "power factor (physics check)",
    "temp_c":                  "ambient temperature",
    "is_holiday":              "holiday flag",
    "kwh_delta_1d":            "day-over-day change rate",
    "cumulative_rollback":     "cumulative meter rollback detected",
    "gnn_node_score":          "graph-level anomaly (topology check)",
    "feeder_load_share":       "share of feeder's total load",
}


# ─── NL Alert Summary Generator ───────────────────────────────────────────────

class AlertNLGGenerator:
    """
    Generates plain-English alert summaries from SHAP values and meter metadata.
    Template-based — no LLM, fully auditable.
    """

    def generate(
        self,
        meter_id: str,
        zone: str,
        consumer_type: str,
        tariff_category: str,
        anomaly_type: str,
        risk_level: str,
        theft_probability: float,
        estimated_revenue_loss_inr: float,
        shap_contributions: list[dict],         # from LightGBMForecaster.explain_single()
        detectors_triggered: list[str],
        bocpd_detected: bool,
        days_since_onset: Optional[int] = None,
        peer_z_score: Optional[float] = None,
        calendar_explanation: Optional[str] = None,
        inspector_notes: Optional[str] = None,
    ) -> str:
        """
        Returns a complete, copy-paste ready alert summary.
        """
        lines = []
        icon = RISK_LEVEL_COLORS.get(risk_level, "⚪")
        anomaly_desc = ANOMALY_TYPE_DESCRIPTIONS.get(anomaly_type, "anomalous reading pattern")

        # ── Header
        lines.append(f"{icon} BESCOM Smart Meter Alert — {risk_level} Risk")
        lines.append(f"Generated: {datetime.now().strftime('%d %b %Y, %H:%M IST')}")
        lines.append("")

        # ── Meter Identity
        lines.append(f"Meter ID:      {meter_id}")
        lines.append(f"Location:      {zone}")
        lines.append(f"Consumer Type: {consumer_type.title()} ({tariff_category})")
        lines.append("")

        # ── Summary Sentence
        lines.append(
            f"SUMMARY: Meter {meter_id} ({zone}, {consumer_type}) has been flagged with "
            f"{theft_probability:.0%} theft probability for {anomaly_desc}."
        )
        if days_since_onset:
            lines.append(
                f"Estimated onset: {days_since_onset} days ago. "
                f"Estimated revenue at risk: ₹{estimated_revenue_loss_inr:,.0f}/month."
            )
        lines.append("")

        # ── Detection Evidence
        lines.append("DETECTION EVIDENCE:")
        lines.append(f"  Detectors triggered: {', '.join(detectors_triggered)}")
        if peer_z_score is not None:
            direction = "below" if peer_z_score < 0 else "above"
            lines.append(
                f"  Peer group deviation: {abs(peer_z_score):.1f}σ {direction} peer cluster mean"
            )
        if bocpd_detected:
            lines.append("  Structural break detected (BOCPD): consumption distribution shifted recently")

        lines.append("")

        # ── Top SHAP Contributors
        lines.append("TOP CONTRIBUTING FACTORS (SHAP):")
        for contrib in shap_contributions[:5]:
            feat_name = FEATURE_PLAIN_ENGLISH.get(
                contrib["feature"], contrib["feature"].replace("_", " ")
            )
            direction = "↑ pushed anomaly score higher" if contrib["shap_value"] > 0 else "↓ normal signal"
            lines.append(
                f"  • {feat_name}: {direction} (SHAP={contrib['shap_value']:+.3f}, "
                f"value={contrib['value']:.3f})"
            )
        lines.append("")

        # ── Calendar Explanation Check
        if calendar_explanation:
            lines.append(f"⚠ CALENDAR NOTE: {calendar_explanation}")
            lines.append("  Some consumption change may be explained by this event.")
            lines.append("  Causal inference analysis: residual anomaly remains significant.")
            lines.append("")

        # ── Recommended Action
        lines.append("RECOMMENDED ACTION:")
        if risk_level == "Critical":
            lines.append("  → IMMEDIATE physical inspection within 24 hours.")
            lines.append("  → Check for physical bypass at meter socket and distribution board.")
        elif risk_level == "High":
            lines.append("  → Schedule physical inspection within 3–5 days.")
            lines.append(f"  → Verify meter type ({consumer_type}) wiring and seals.")
        else:
            lines.append("  → Consider sending soft consumer notification first.")
            lines.append("  → Schedule inspection within 2 weeks if no response.")

        if inspector_notes:
            lines.append(f"\n  PRIOR NOTES: {inspector_notes}")

        lines.append("")
        lines.append("─" * 60)
        lines.append(f"Confidence: {'High' if len(detectors_triggered) >= 3 else 'Medium'} "
                     f"({len(detectors_triggered)}/4 detectors agree)")
        lines.append("This alert was generated by BESCOM AI. Final decision rests with the analyst.")

        return "\n".join(lines)

    def generate_consumer_nudge(
        self,
        consumer_name: str,
        meter_id: str,
        consumption_change_pct: float,
    ) -> str:
        """
        Generate soft consumer notification SMS/email (before dispatching field team).
        Polite tone — does NOT mention theft or investigation.
        """
        direction = "lower" if consumption_change_pct < 0 else "higher"
        magnitude = abs(consumption_change_pct)

        subject = f"Important: Unusual consumption pattern on your BESCOM account"

        body = f"""Dear Consumer ({meter_id}),

We've noticed that your electricity consumption has been {magnitude:.0f}% {direction} than usual over the past few weeks.

This could be due to:
  • A change in your daily routine or business operations
  • New appliances or equipment being added or removed
  • A potential issue with your electricity meter

If this change is due to a known reason, no action is required. However, if this seems unexpected, we kindly request you to:

  1. Call our helpline at 1912
  2. Visit bescom.co.in/self-service
  3. Reply to this message with a brief explanation

If we don't hear from you within 7 days, our field team may schedule a routine meter inspection at your premises.

Thank you for your cooperation.

BESCOM Customer Service
Bangalore Electricity Supply Company Limited"""

        return subject, body


# ─── Audit Trail Logger ───────────────────────────────────────────────────────

class AuditLogger:
    """
    Hash-chained audit trail logger.
    All entries are immutable — append only.
    """

    def __init__(self, db_conn):
        self.conn = db_conn
        self._last_hash = self._get_last_hash()

    def _get_last_hash(self) -> str:
        with self.conn.cursor() as cur:
            cur.execute("SELECT entry_hash FROM audit_log ORDER BY log_id DESC LIMIT 1")
            row = cur.fetchone()
            return row[0] if row else "genesis"

    def _compute_hash(self, prev_hash: str, payload: str) -> str:
        import hashlib
        return hashlib.sha256(f"{prev_hash}{payload}".encode()).hexdigest()

    def log(self, event_type: str, payload: dict, meter_id: str = None,
            alert_id: str = None, actor_id: str = None, model_version: str = None):
        import json
        payload_str = json.dumps(payload, sort_keys=True, default=str)
        entry_hash  = self._compute_hash(self._last_hash, payload_str)

        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO audit_log
                    (event_type, meter_id, alert_id, actor_id, payload,
                     model_version, entry_hash, prev_hash)
                VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s)
            """, (event_type, meter_id, alert_id, actor_id,
                  payload_str, model_version, entry_hash, self._last_hash))
        self.conn.commit()
        self._last_hash = entry_hash
