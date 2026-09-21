"""
Energy Accounting Service
=========================
Reads the five new energy-accounting CSVs and exposes aggregation /
drill-down functions consumed by the new /api/v1/energy-accounting/* routes.

Pattern: identical to app/services/mock_data.py — same DATA_DIR env override,
same csv.DictReader-based _read_csv helper, same lru_cache for loaded tables.

Columns NEVER returned to callers:
  - transformer_energy_daily.theft_event_flag
  - transformer_energy_daily.meters_flagged
"""

import csv
import os
from collections import defaultdict
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from statistics import mean
from typing import Optional

# ── Data-directory resolution (same mechanism as mock_data.py) ──────────────
DEFAULT_DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "bescom_dataset"
DATA_DIR = Path(os.environ.get("BESCOM_DATA_DIR", DEFAULT_DATA_DIR)).expanduser().resolve()

# Columns that must never appear in any API response.
_FORBIDDEN_COLUMNS = {"theft_event_flag", "meters_flagged"}


# ── Low-level CSV loader ─────────────────────────────────────────────────────

def _read_csv(name: str) -> list[dict]:
    path = DATA_DIR / name
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _date_str(value) -> str:
    """Return value as a date string YYYY-MM-DD, stripping any time component."""
    if not value:
        return ""
    return str(value)[:10]


# ── Cached table loaders ─────────────────────────────────────────────────────

@lru_cache(maxsize=None)
def _distribution_transformers() -> list[dict]:
    return _read_csv("distribution_transformers.csv")


@lru_cache(maxsize=None)
def _meter_transformer_map() -> list[dict]:
    return _read_csv("meter_transformer_map.csv")


@lru_cache(maxsize=None)
def _transformer_energy_daily() -> list[dict]:
    return _read_csv("transformer_energy_daily.csv")


@lru_cache(maxsize=None)
def _feeder_energy_daily() -> list[dict]:
    return _read_csv("feeder_energy_daily.csv")


@lru_cache(maxsize=None)
def _substation_energy_daily() -> list[dict]:
    return _read_csv("substation_energy_daily.csv")


@lru_cache(maxsize=None)
def _anomaly_alerts() -> list[dict]:
    return _read_csv("anomaly_alerts.csv")


# ── Index helpers ─────────────────────────────────────────────────────────────

@lru_cache(maxsize=None)
def _dt_meta_index() -> dict[str, dict]:
    """transformer_id → distribution_transformers row."""
    return {row["transformer_id"]: row for row in _distribution_transformers() if row.get("transformer_id")}


@lru_cache(maxsize=None)
def _meters_by_transformer() -> dict[str, list[str]]:
    """transformer_id → [meter_id, ...]"""
    index: dict[str, list[str]] = defaultdict(list)
    for row in _meter_transformer_map():
        tid = row.get("transformer_id", "")
        mid = row.get("meter_id", "")
        if tid and mid:
            index[tid].append(mid)
    return dict(index)


# ── Date-range filtering helper ───────────────────────────────────────────────

def _in_range(row_date: str, start_date: Optional[str], end_date: Optional[str]) -> bool:
    d = _date_str(row_date)
    if not d:
        return False
    if start_date and d < start_date:
        return False
    if end_date and d > end_date:
        return False
    return True


# ── Public API ────────────────────────────────────────────────────────────────

def ea_summary(
    zone: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> dict:
    """
    Aggregate energy-accounting totals across all DTs (optionally filtered by
    zone and/or date range).

    Returns: { total_input_kwh, total_metered_kwh, total_technical_loss_kwh,
               total_unexplained_kwh, unexplained_pct }
    """
    total_input = 0.0
    total_metered = 0.0
    total_tech_loss = 0.0
    total_unexplained = 0.0

    for row in _transformer_energy_daily():
        if zone and row.get("zone") != zone:
            continue
        if not _in_range(row.get("date", ""), start_date, end_date):
            continue
        total_input += _float(row.get("input_kwh"))
        total_metered += _float(row.get("metered_kwh"))
        total_tech_loss += _float(row.get("technical_loss_kwh"))
        total_unexplained += _float(row.get("unexplained_kwh"))

    unexplained_pct = round(total_unexplained / total_input * 100, 4) if total_input else 0.0

    return {
        "total_input_kwh": round(total_input, 2),
        "total_metered_kwh": round(total_metered, 2),
        "total_technical_loss_kwh": round(total_tech_loss, 2),
        "total_unexplained_kwh": round(total_unexplained, 2),
        "unexplained_pct": unexplained_pct,
        "note": (
            "Technical-loss figures are synthetic/parametric (not field-measured). "
            "See data/ENERGY_ACCOUNTING_DATA_README.md."
        ),
    }


def ea_transformers(
    zone: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 20,
) -> dict:
    """
    Return DTs ranked by unexplained_pct descending.

    Each item: { transformer_id, feeder_id, zone, rated_kva, location_type,
                 total_input_kwh, total_metered_kwh, total_technical_loss_kwh,
                 total_unexplained_kwh, unexplained_pct, days_in_range }
    """
    dt_meta = _dt_meta_index()
    # Accumulate per-DT totals over the date range.
    acc: dict[str, dict] = {}

    for row in _transformer_energy_daily():
        if zone and row.get("zone") != zone:
            continue
        if not _in_range(row.get("date", ""), start_date, end_date):
            continue
        tid = row.get("transformer_id", "")
        if not tid:
            continue
        if tid not in acc:
            meta = dt_meta.get(tid, {})
            acc[tid] = {
                "transformer_id": tid,
                "feeder_id": row.get("feeder_id", meta.get("feeder_id", "")),
                "zone": row.get("zone", meta.get("zone", "")),
                "rated_kva": _float(meta.get("rated_kva")),
                "location_type": meta.get("location_type", ""),
                "total_input_kwh": 0.0,
                "total_metered_kwh": 0.0,
                "total_technical_loss_kwh": 0.0,
                "total_unexplained_kwh": 0.0,
                "days_in_range": 0,
            }
        acc[tid]["total_input_kwh"] += _float(row.get("input_kwh"))
        acc[tid]["total_metered_kwh"] += _float(row.get("metered_kwh"))
        acc[tid]["total_technical_loss_kwh"] += _float(row.get("technical_loss_kwh"))
        acc[tid]["total_unexplained_kwh"] += _float(row.get("unexplained_kwh"))
        acc[tid]["days_in_range"] += 1

    items = []
    for item in acc.values():
        inp = item["total_input_kwh"]
        item["total_input_kwh"] = round(inp, 2)
        item["total_metered_kwh"] = round(item["total_metered_kwh"], 2)
        item["total_technical_loss_kwh"] = round(item["total_technical_loss_kwh"], 2)
        item["total_unexplained_kwh"] = round(item["total_unexplained_kwh"], 2)
        item["unexplained_pct"] = round(item["total_unexplained_kwh"] / inp * 100, 4) if inp else 0.0
        items.append(item)

    items.sort(key=lambda x: x["unexplained_pct"], reverse=True)
    return {"items": items[:limit], "total_transformers": len(acc)}


def ea_transformer_detail(
    transformer_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Optional[dict]:
    """
    Drill-down for a single DT:
    - transformer metadata
    - daily energy-accounting time series (sorted by date)
    - list of meters mapped to this DT
    - anomaly alerts (from anomaly_alerts.csv) for those meters
      whose alert_timestamp falls within [start_date, end_date]

    Returns None if transformer_id is not found.
    """
    dt_meta = _dt_meta_index()
    if transformer_id not in dt_meta:
        return None

    meta = dt_meta[transformer_id]

    # ── Daily series ─────────────────────────────────────────────────────────
    daily_rows = []
    for row in _transformer_energy_daily():
        if row.get("transformer_id") != transformer_id:
            continue
        if not _in_range(row.get("date", ""), start_date, end_date):
            continue
        # Strip forbidden columns before returning.
        daily_rows.append({
            "date": row.get("date"),
            "input_kwh": round(_float(row.get("input_kwh")), 2),
            "metered_kwh": round(_float(row.get("metered_kwh")), 2),
            "technical_loss_kwh": round(_float(row.get("technical_loss_kwh")), 2),
            "unexplained_kwh": round(_float(row.get("unexplained_kwh")), 2),
            "unexplained_pct": round(_float(row.get("unexplained_pct")), 4),
        })
    daily_rows.sort(key=lambda r: r["date"])

    # ── Meters mapped to this DT ─────────────────────────────────────────────
    meters_for_dt = _meters_by_transformer().get(transformer_id, [])
    meter_rows_detail = []
    for row in _meter_transformer_map():
        if row.get("transformer_id") == transformer_id:
            meter_rows_detail.append({
                "meter_id": row.get("meter_id"),
                "feeder_id": row.get("feeder_id"),
                "substation_id": row.get("substation_id"),
                "zone": row.get("zone"),
            })

    # ── Related anomaly alerts (cross-reference, read-only) ──────────────────
    meter_id_set = set(meters_for_dt)
    related_alerts = []
    for alert in _anomaly_alerts():
        if alert.get("meter_id") not in meter_id_set:
            continue
        alert_date = _date_str(alert.get("alert_timestamp", ""))
        if not _in_range(alert_date, start_date, end_date):
            continue
        related_alerts.append({
            "alert_id": alert.get("alert_id"),
            "meter_id": alert.get("meter_id"),
            "alert_timestamp": alert.get("alert_timestamp"),
            "severity": alert.get("severity"),
            "status": alert.get("status"),
            "anomaly_type": alert.get("anomaly_type"),
            "anomaly_score": _float(alert.get("anomaly_score")),
            "consumption_drop_pct": _float(alert.get("consumption_drop_pct")),
            "estimated_daily_loss_inr": _float(alert.get("estimated_daily_loss_inr")),
        })

    # Sort alerts newest first.
    related_alerts.sort(key=lambda a: a["alert_timestamp"] or "", reverse=True)

    return {
        "transformer": {
            "transformer_id": transformer_id,
            "feeder_id": meta.get("feeder_id"),
            "substation_id": meta.get("substation_id"),
            "zone": meta.get("zone"),
            "rated_kva": _float(meta.get("rated_kva")),
            "connected_load_kw": _float(meta.get("connected_load_kw")),
            "install_year": meta.get("install_year"),
            "location_type": meta.get("location_type"),
            # dt_technical_loss_pct_model is a generation parameter; not exposed.
        },
        "daily_series": daily_rows,
        "meters": meter_rows_detail,
        "related_alerts": related_alerts[:50],
    }


def ea_feeders(
    zone: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> dict:
    """
    Feeder-level rollup view, aggregated over the date range.

    Each item: { feeder_id, substation_id, zone,
                 total_input_kwh, total_sum_dt_input_kwh,
                 total_feeder_technical_loss_kwh, days_in_range }
    """
    acc: dict[str, dict] = {}

    for row in _feeder_energy_daily():
        if zone and row.get("zone") != zone:
            continue
        if not _in_range(row.get("date", ""), start_date, end_date):
            continue
        fid = row.get("feeder_id", "")
        if not fid:
            continue
        if fid not in acc:
            acc[fid] = {
                "feeder_id": fid,
                "substation_id": row.get("substation_id", ""),
                "zone": row.get("zone", ""),
                "total_input_kwh": 0.0,
                "total_sum_dt_input_kwh": 0.0,
                "total_feeder_technical_loss_kwh": 0.0,
                "days_in_range": 0,
            }
        acc[fid]["total_input_kwh"] += _float(row.get("input_kwh"))
        acc[fid]["total_sum_dt_input_kwh"] += _float(row.get("sum_dt_input_kwh"))
        acc[fid]["total_feeder_technical_loss_kwh"] += _float(row.get("feeder_technical_loss_kwh"))
        acc[fid]["days_in_range"] += 1

    items = sorted(
        [
            {**item,
             "total_input_kwh": round(item["total_input_kwh"], 2),
             "total_sum_dt_input_kwh": round(item["total_sum_dt_input_kwh"], 2),
             "total_feeder_technical_loss_kwh": round(item["total_feeder_technical_loss_kwh"], 2),
             }
            for item in acc.values()
        ],
        key=lambda x: x["total_input_kwh"],
        reverse=True,
    )
    return {"items": items, "total_feeders": len(acc)}


def ea_substations(
    zone: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> dict:
    """
    Substation-level rollup view, aggregated over the date range.

    Each item: { substation_id, zone, total_input_kwh, days_in_range }
    """
    acc: dict[str, dict] = {}

    for row in _substation_energy_daily():
        if zone and row.get("zone") != zone:
            continue
        if not _in_range(row.get("date", ""), start_date, end_date):
            continue
        sid = row.get("substation_id", "")
        if not sid:
            continue
        if sid not in acc:
            acc[sid] = {
                "substation_id": sid,
                "zone": row.get("zone", ""),
                "num_feeders": int(_float(row.get("num_feeders"))),
                "total_input_kwh": 0.0,
                "days_in_range": 0,
            }
        acc[sid]["total_input_kwh"] += _float(row.get("input_kwh"))
        acc[sid]["days_in_range"] += 1

    items = sorted(
        [
            {**item, "total_input_kwh": round(item["total_input_kwh"], 2)}
            for item in acc.values()
        ],
        key=lambda x: x["total_input_kwh"],
        reverse=True,
    )
    return {"items": items, "total_substations": len(acc)}
