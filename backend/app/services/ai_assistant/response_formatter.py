import copy
import re
from typing import Any


MASKED_ID = "[masked-meter]"
METER_ID_PATTERN = re.compile(r"\b(?:MTR|SM|BESCOM)[-_]?[A-Z0-9-]{3,}\b", re.IGNORECASE)


def mask_meter_id(value: str | None) -> str | None:
    if not value:
        return value
    text = str(value)
    if len(text) <= 4:
        return MASKED_ID
    return f"{text[:3]}...{text[-2:]}"


def sanitize_text(value: str) -> str:
    return METER_ID_PATTERN.sub(lambda match: mask_meter_id(match.group(0)) or MASKED_ID, value)


def sanitize_context(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            lower = key.lower()
            if lower in {"meterid", "meter_id", "consumer_id", "consumerid", "address", "mapsurl", "latitude", "longitude", "lat", "lon"}:
                if "meter" in lower:
                    sanitized[key] = mask_meter_id(str(item))
                else:
                    sanitized[key] = "[redacted]"
            else:
                sanitized[key] = sanitize_context(item)
        return sanitized
    if isinstance(value, list):
        return [sanitize_context(item) for item in value[:80]]
    if isinstance(value, str):
        return sanitize_text(value)
    return copy.deepcopy(value)


def fallback_answer(message: str, context: dict[str, Any]) -> str:
    kpis = context.get("kpis", {})
    zones = context.get("zones", [])
    alerts = context.get("alerts", [])
    forecast = context.get("forecastSummary", {})
    top_zone = zones[0] if zones else {}
    peak = forecast.get("peakForecastMw")

    parts = [
        "Groq is not configured or temporarily unavailable, so this is a local dashboard summary.",
        f"Open alerts: {kpis.get('openAlerts', 'n/a')}; critical alerts: {kpis.get('criticalAlerts', 'n/a')}.",
    ]
    if peak:
        parts.append(f"Latest forecast peak is about {peak} MW during {forecast.get('peakTime', 'the forecast window')}.")
    if top_zone:
        parts.append(
            f"Highest visible zone risk is {top_zone.get('name')} with {top_zone.get('risk')} risk, "
            f"{top_zone.get('openAlerts')} open alerts, and {top_zone.get('loadPct')}% load."
        )
    if alerts:
        parts.append(
            "Priority alerts show potential irregularities only; they require analyst verification before field conclusions."
        )
    if "forecast" in message.lower() or "band" in message.lower():
        parts.append("The grey forecast band represents uncertainty: wider bands mean the model expects more variability.")
    return " ".join(parts)

