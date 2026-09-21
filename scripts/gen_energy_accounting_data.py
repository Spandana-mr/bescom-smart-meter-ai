"""
Generate a synthetic, internally-consistent energy-accounting dataset for the
BESCOM Smart Meter AI project, extending the existing dataset with:

  1. distribution_transformers.csv   - DT registry (new hierarchy level)
  2. meter_transformer_map.csv       - meter -> DT assignment
  3. transformer_energy_daily.csv    - daily DT input energy vs metered energy
  4. feeder_energy_daily.csv         - daily feeder input energy (rollup of DTs)
  5. substation_energy_daily.csv     - daily substation input energy (rollup)

Scope note: analysis starts at the BESCOM substation (secondary side of the
grid) and goes downstream to feeders -> distribution transformers -> consumer
meters. Nothing upstream of the substation (transmission/generation) is
modeled.

Design goal: unexplained_kwh at the DT level should be ~0 (small metering
noise only) on ordinary days, and should spike specifically on
(meter, day) combinations that already have a genuine anomaly_alerts.csv
event for that meter - so the new energy-accounting evidence and the
existing ML alert evidence corroborate each other, exactly as intended by
the hierarchical design. Zone-wide demand dips (e.g. holidays) are shared by
both the meter baseline and the zone index, so they do NOT create unexplained
energy - this is what fixes the "vacation problem".
"""

import numpy as np
import pandas as pd
from pathlib import Path

SRC = Path("/home/claude/bescom_project/bescom-smart-meter-ai_newFeature/data/bescom_dataset")
OUT = Path("/home/claude/energy_accounting_dataset")
OUT.mkdir(parents=True, exist_ok=True)

rng = np.random.default_rng(42)

# ---------------------------------------------------------------- load ----
meters = pd.read_csv(SRC / "meters.csv")
topo = pd.read_csv(SRC / "grid_topology.csv")
readings = pd.read_csv(SRC / "meter_readings.csv", parse_dates=["timestamp"])
forecasts = pd.read_csv(SRC / "demand_forecasts.csv", parse_dates=["forecast_date"])
alerts = pd.read_csv(SRC / "anomaly_alerts.csv", parse_dates=["alert_timestamp", "resolution_timestamp"])

DATE_RANGE = pd.date_range("2023-01-01", "2024-12-31", freq="D")

# ============================================================== STEP 1 ====
# Distribution-transformer registry (new hierarchy level: feeder -> DT)
# ============================================================================
dt_rows = []
for _, f in topo.iterrows():
    n_dt = max(1, int(f["transformer_count"]))
    for i in range(1, n_dt + 1):
        dt_id = f"DT-{f['feeder_id'].split('-', 1)[1]}-{i:02d}"
        dt_rows.append({
            "transformer_id": dt_id,
            "feeder_id": f["feeder_id"],
            "substation_id": f["substation_id"],
            "zone": f["zone"],
            "install_year": int(rng.integers(2005, 2023)),
            "location_type": "Urban" if f["zone"] not in ("Yelahanka",) else rng.choice(["Urban", "Semi-Urban"]),
        })
dt_registry = pd.DataFrame(dt_rows)

# base technical-loss fraction per DT: anchored loosely to the feeder's
# existing feeder_loss_pct label (used only as a generation seed, ~55% of
# the feeder figure attributed to the DT stage), with random spread so the
# accounting engine has to *derive* the number rather than reproduce a label
feeder_loss_lookup = topo.set_index("feeder_id")["feeder_loss_pct"].to_dict()
dt_registry["_base_loss_frac"] = dt_registry["feeder_id"].map(feeder_loss_lookup) / 100 * 0.55
dt_registry["_base_loss_frac"] = (dt_registry["_base_loss_frac"] * rng.uniform(0.7, 1.3, len(dt_registry))).clip(0.015, 0.14)

print(f"[1/5] Distribution transformers generated: {len(dt_registry)} (across {topo.feeder_id.nunique()} feeders)")

# ============================================================== STEP 2 ====
# Assign every meter to a DT under its own feeder (round-robin, deterministic)
# ============================================================================
meter_dt_rows = []
for feeder_id, grp in meters.groupby("feeder_id"):
    dts = dt_registry.loc[dt_registry.feeder_id == feeder_id, "transformer_id"].tolist()
    if not dts:
        continue
    meter_ids_sorted = grp["meter_id"].sort_values().tolist()
    for idx, mid in enumerate(meter_ids_sorted):
        meter_dt_rows.append({"meter_id": mid, "transformer_id": dts[idx % len(dts)]})
meter_dt_map = pd.DataFrame(meter_dt_rows).merge(
    meters[["meter_id", "consumer_type", "zone", "feeder_id", "substation_id", "contracted_kw"]],
    on="meter_id", how="left"
)

print(f"[2/5] Meter -> transformer mapping built for {len(meter_dt_map)} meters")

# ============================================================== STEP 3 ====
# Per-meter daily baseline consumption (actual physical usage, kWh/day)
# ============================================================================
avg_kwh_per_reading = readings.groupby("meter_id")["kwh"].mean()
LOAD_FACTOR_BY_TYPE = {"Residential": 0.22, "Commercial": 0.35, "Industrial": 0.55, "Agricultural": 0.30}

def baseline_daily_kwh(row):
    if row["meter_id"] in avg_kwh_per_reading.index:
        return avg_kwh_per_reading[row["meter_id"]] * 24.0
    lf = LOAD_FACTOR_BY_TYPE.get(row["consumer_type"], 0.3)
    return row["contracted_kw"] * lf * 24.0

meter_dt_map["baseline_daily_kwh"] = meter_dt_map.apply(baseline_daily_kwh, axis=1)
n_from_readings = meter_dt_map["meter_id"].isin(avg_kwh_per_reading.index).sum()
print(f"[3/5] Baseline daily kWh set ({n_from_readings} meters from readings, "
      f"{len(meter_dt_map) - n_from_readings} from contracted_kw x load-factor fallback)")

# ============================================================== STEP 4 ====
# Zone daily demand index (captures weekday/weekend/seasonal/holiday shape
# from the EXISTING demand_forecasts.csv, normalised to mean=1.0 per zone)
# ============================================================================
forecasts["value_mw"] = forecasts["actual_mw"].fillna(forecasts["forecast_mw"])
zone_mean = forecasts.groupby("zone")["value_mw"].transform("mean")
forecasts["zone_idx"] = forecasts["value_mw"] / zone_mean
zone_idx = forecasts[["zone", "forecast_date", "zone_idx"]].rename(columns={"forecast_date": "date"})

# ============================================================== STEP 5 ====
# Suppression windows: on days close to a real anomaly_alerts.csv event for a
# meter, its METERED reading is suppressed relative to actual usage. This is
# the physical mechanism that produces "unexplained energy" upstream.
# ============================================================================
sup_rows = []
for _, a in alerts.iterrows():
    start = a["alert_timestamp"].normalize()
    end = start + pd.Timedelta(days=2)
    if pd.notna(a["resolution_timestamp"]):
        end = min(end, a["resolution_timestamp"].normalize())
    frac = min(max(a["consumption_drop_pct"] / 100.0, 0.0), 0.95)
    for d in pd.date_range(start, max(start, end)):
        sup_rows.append({"meter_id": a["meter_id"], "date": d, "suppression_frac": frac})
suppression = (pd.DataFrame(sup_rows)
               .groupby(["meter_id", "date"], as_index=False)["suppression_frac"].max())
print(f"[4/5] Suppression events (meter-days linked to existing alerts): {len(suppression)}")

# ============================================================== STEP 6 ====
# Meter x day actual & metered consumption (in-memory only; not exported at
# this grain to avoid duplicating meter_readings.csv / bloating file size)
# ============================================================================
cross = meter_dt_map.merge(pd.DataFrame({"date": DATE_RANGE, "_k": 1}),
                            meter_dt_map.assign(_k=1)[["_k"]].drop_duplicates(),
                            on="_k") if False else None
# simpler + memory-friendly cross join:
meter_dt_map["_k"] = 1
dates_df = pd.DataFrame({"date": DATE_RANGE, "_k": 1})
cross = meter_dt_map.merge(dates_df, on="_k").drop(columns="_k")

cross = cross.merge(zone_idx, on=["zone", "date"], how="left")
cross["zone_idx"] = cross["zone_idx"].fillna(1.0)

daily_noise = rng.normal(1.0, 0.03, len(cross)).clip(0.85, 1.15)
cross["actual_kwh"] = (cross["baseline_daily_kwh"] * cross["zone_idx"] * daily_noise).clip(lower=0)

cross = cross.merge(suppression, on=["meter_id", "date"], how="left")
cross["suppression_frac"] = cross["suppression_frac"].fillna(0.0)
meter_noise = rng.normal(1.0, 0.005, len(cross))
cross["metered_kwh"] = (cross["actual_kwh"] * (1 - cross["suppression_frac"]) * meter_noise).clip(lower=0)

# ============================================================== STEP 7 ====
# Aggregate to DT-day, apply technical loss, compute unexplained energy
# ============================================================================
dt_day = cross.groupby(["transformer_id", "date"], as_index=False).agg(
    actual_kwh=("actual_kwh", "sum"),
    metered_kwh=("metered_kwh", "sum"),
    meters_flagged=("suppression_frac", lambda s: int((s > 0.05).sum())),
)
dt_day = dt_day.merge(dt_registry[["transformer_id", "feeder_id", "zone", "_base_loss_frac"]],
                       on="transformer_id", how="left")
loss_noise = rng.normal(1.0, 0.08, len(dt_day)).clip(0.6, 1.5)
dt_day["loss_frac"] = (dt_day["_base_loss_frac"] * loss_noise).clip(0.01, 0.18)
dt_day["technical_loss_kwh"] = (dt_day["actual_kwh"] * dt_day["loss_frac"]).round(2)
dt_day["input_kwh"] = (dt_day["actual_kwh"] + dt_day["technical_loss_kwh"]).round(2)
dt_day["metered_kwh"] = dt_day["metered_kwh"].round(2)
dt_day["unexplained_kwh"] = (dt_day["input_kwh"] - dt_day["metered_kwh"] - dt_day["technical_loss_kwh"]).round(2)
dt_day["unexplained_pct"] = (dt_day["unexplained_kwh"] / dt_day["input_kwh"] * 100).round(3)
dt_day["theft_event_flag"] = dt_day["meters_flagged"] > 0

transformer_energy_daily = dt_day[[
    "date", "transformer_id", "feeder_id", "zone", "input_kwh", "metered_kwh",
    "technical_loss_kwh", "unexplained_kwh", "unexplained_pct",
    "theft_event_flag", "meters_flagged"
]].sort_values(["date", "transformer_id"]).reset_index(drop=True)

print(f"[5/5] Transformer-day rows: {len(transformer_energy_daily)}")

# ============================================================== STEP 8 ====
# Feeder-day rollup: sum of DT inputs + an additional feeder-conductor loss
# ============================================================================
feeder_loss_lookup2 = topo.set_index("feeder_id")["feeder_loss_pct"].to_dict()
feeder_base_extra = {fid: max(0.005, v / 100 * 0.45) for fid, v in feeder_loss_lookup2.items()}

fd = dt_day.groupby(["feeder_id", "date"], as_index=False).agg(sum_dt_input_kwh=("input_kwh", "sum"))
fd["substation_id"] = fd["feeder_id"].map(topo.set_index("feeder_id")["substation_id"])
fd["zone"] = fd["feeder_id"].map(topo.set_index("feeder_id")["zone"])
fd["_extra_base"] = fd["feeder_id"].map(feeder_base_extra)
extra_noise = rng.normal(1.0, 0.08, len(fd)).clip(0.6, 1.5)
fd["feeder_extra_loss_frac"] = (fd["_extra_base"] * extra_noise).clip(0.003, 0.10)
fd["feeder_technical_loss_kwh"] = (fd["sum_dt_input_kwh"] * fd["feeder_extra_loss_frac"]).round(2)
fd["input_kwh"] = (fd["sum_dt_input_kwh"] + fd["feeder_technical_loss_kwh"]).round(2)

feeder_energy_daily = fd[[
    "date", "feeder_id", "substation_id", "zone", "input_kwh",
    "sum_dt_input_kwh", "feeder_technical_loss_kwh"
]].sort_values(["date", "feeder_id"]).reset_index(drop=True)

# ============================================================== STEP 9 ====
# Substation-day rollup: sum of feeder inputs (starting point = substation
# secondary side; nothing upstream of this is modeled, per scope)
# ============================================================================
sd = feeder_energy_daily.groupby(["substation_id", "date"], as_index=False).agg(
    input_kwh=("input_kwh", "sum"),
    num_feeders=("feeder_id", "nunique"),
)
sd["zone"] = sd["substation_id"].map(topo.drop_duplicates("substation_id").set_index("substation_id")["zone"])
substation_energy_daily = sd[["date", "substation_id", "zone", "input_kwh", "num_feeders"]] \
    .sort_values(["date", "substation_id"]).reset_index(drop=True)

# ============================================================== WRITE =====
dt_registry_out = dt_registry.drop(columns=["_base_loss_frac"]).copy()
dt_registry_out["dt_technical_loss_pct_model"] = (dt_registry["_base_loss_frac"] * 100).round(2)
meter_dt_out = meter_dt_map[["meter_id", "transformer_id", "feeder_id", "substation_id", "zone"]]

# realistic LT-side DT sizing: pick the smallest standard rating that covers
# the connected load (sum of contracted_kw under that DT) with ~40-80% headroom,
# instead of an unrealistic multi-MVA figure derived from feeder capacity
STANDARD_KVA = [100, 160, 250, 315, 400, 500, 630, 1000, 1600, 2000, 2500, 3150]
connected_kw = meter_dt_map.groupby("transformer_id")["contracted_kw"].sum()
def pick_rating(kw):
    target = kw * rng.uniform(1.4, 1.8)  # headroom + power-factor allowance
    for s in STANDARD_KVA:
        if s >= target:
            return s
    return STANDARD_KVA[-1]
dt_registry_out["connected_load_kw"] = dt_registry_out["transformer_id"].map(connected_kw).fillna(0).round(1)
dt_registry_out["rated_kva"] = dt_registry_out["connected_load_kw"].apply(pick_rating)
dt_registry_out = dt_registry_out[["transformer_id", "feeder_id", "substation_id", "zone",
                                    "rated_kva", "connected_load_kw", "install_year",
                                    "location_type", "dt_technical_loss_pct_model"]]

dt_registry_out.to_csv(OUT / "distribution_transformers.csv", index=False)
meter_dt_out.to_csv(OUT / "meter_transformer_map.csv", index=False)
transformer_energy_daily.to_csv(OUT / "transformer_energy_daily.csv", index=False)
feeder_energy_daily.to_csv(OUT / "feeder_energy_daily.csv", index=False)
substation_energy_daily.to_csv(OUT / "substation_energy_daily.csv", index=False)

# ============================================================== SANITY ====
clean = transformer_energy_daily[~transformer_energy_daily.theft_event_flag]
flagged = transformer_energy_daily[transformer_energy_daily.theft_event_flag]
print("\n--- Sanity check ---")
print(f"Clean DT-days   : n={len(clean):6d}  mean unexplained_pct = {clean.unexplained_pct.mean():.3f}%  "
      f"(should be small / noise-level)")
print(f"Flagged DT-days : n={len(flagged):6d}  mean unexplained_pct = {flagged.unexplained_pct.mean():.3f}%  "
      f"(should be clearly higher)")
print(f"Overall feeder_loss_pct anchor vs realized (feeder level, mean %): "
      f"anchor={topo.feeder_loss_pct.mean():.2f}  realized={((feeder_energy_daily.feeder_technical_loss_kwh.sum()+dt_day.technical_loss_kwh.sum())/feeder_energy_daily.input_kwh.sum()*100):.2f}")
print("\nFiles written to:", OUT)
for p in sorted(OUT.glob("*.csv")):
    print(" -", p.name, f"({p.stat().st_size/1024:.1f} KB)")
