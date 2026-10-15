"""Part D, 8D example: numbers behind docs/8D_chiller_example.md (cooling-tower fouling).

Uses the hourly LBNL cache written by scripts/fdd_prepare.py (LBNL_FDD_CACHE) and the
committed Part C results (results/fdd_detection.csv, results/fdd_detection_daily.csv,
results/fdd_energy.csv). Every scenario file is the same simulated year with the same
weather and building model, so a faulted hour can be compared with the same hour of the
fault-free file ("paired" differences): the difference is caused by the fault and its
effect on the plant's control (simulation-level evidence).

Outputs
  results/maintenance_8d_tower_fouling.json   paired effects, existing FDD detection, new indicator
  results/maintenance_8d_indicator.csv        daily alarm rate of the new indicator for every scenario
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fabhvac.fdd.data import NORMAL  # noqa: E402
from fabhvac.fdd.models import month_split  # noqa: E402
from fabhvac.maintenance.condition import ResidualIndicator, daily_mean  # noqa: E402
from fabhvac.results_io import write_csv, write_json  # noqa: E402
from fabhvac.units import f_to_c  # noqa: E402

RES = Path(os.environ.get("FABHVAC_RESULTS_DIR", ROOT / "results"))
FAULT = "coolingtower_fouling"
SEVERITIES = ["095", "080", "065"]
# Indicator design, fixed before it was evaluated on test months: target = tower-1 leaving
# water; inputs = weather, load, set points, staging, and tower-1 fan speed and water flow.
TARGET = "ct1_sw_c"
INPUTS = ["t_wb_c", "t_db_c", "sec_load_kw", "chw_spt_c", "ct_spt_c", "n_chillers_on",
          "CT_FAN_SPD_1", "CT_FLOW_1", "CT_STA_2", "CT_STA_3"]
SIGNATURE_FILES = ["ChillerPlant_coolingtower_fouling_065", "ChillerPlant_coolingtower_bias_2",
                   "ChillerPlant_coolingtower_bias_-2", "ChillerPlant_bypass_leakage_025", "ChillerPlant_coolingtower_PI"]
ENERGY_PARTS = ["chiller_kw", "chw_pump_kw", "cdw_pump_kw", "tower_kw", "plant_kw"]


def cache_dir() -> Path:
    c = os.environ.get("LBNL_FDD_CACHE")
    if not c:
        sys.exit("set LBNL_FDD_CACHE to the hourly cache written by scripts/fdd_prepare.py")
    return Path(c)


def load(name: str) -> pd.DataFrame:
    df = pd.read_parquet(cache_dir() / f"{name}.parquet")
    df["ct1_sw_c"] = f_to_c(df["CT_SW_TEMP_1"])
    df["ct2_sw_c"] = f_to_c(df["CT_SW_TEMP_2"])
    df["cdw_sw_c"] = f_to_c(df["CDWL_SW_TEMP"])
    return df


def kwh(df, col):
    return float((df[col] * df["n_minutes"] / 60.0).sum())


def paired_effects(n: pd.DataFrame, f: pd.DataFrame) -> dict:
    if not (f.index.equals(n.index)):
        raise ValueError("scenario files are not hour-aligned")
    d_ct1 = (f["ct1_sw_c"] - n["ct1_sw_c"]).to_numpy()
    d_ct2 = (f["ct2_sw_c"] - n["ct2_sw_c"]).to_numpy()
    tower2_on = ((n["CT_STA_2"] > 0.99) & (f["CT_STA_2"] > 0.99)).to_numpy()
    out = {"hours": int(len(n)),
           "kwh_delta": {c: kwh(f, c) - kwh(n, c) for c in ENERGY_PARTS},
           "plant_kwh_delta_pct": (kwh(f, "plant_kw") / kwh(n, "plant_kw") - 1) * 100,
           "tower1_leaving_water_delta_k": {"mean": float(np.mean(d_ct1)), "median": float(np.median(d_ct1)),
                                             "p95": float(np.percentile(d_ct1, 95)), "max": float(np.max(d_ct1))},
           "tower2_leaving_water_delta_k_when_on": {
               "hours_on": int(tower2_on.sum()),
               "median": float(np.median(d_ct2[tower2_on])) if tower2_on.any() else None},
           "tower1_fan_speed_delta_mean": float((f["CT_FAN_SPD_1"] - n["CT_FAN_SPD_1"]).mean()),
           "tower1_fan_at_full_speed_hours_frac": {"fault": float((f["CT_FAN_SPD_1"] > 0.99).mean()),
                                                   "fault_free": float((n["CT_FAN_SPD_1"] > 0.99).mean())},
           "tower1_above_setpoint_0p5k_hours_frac": {"fault": float((f["ct1_minus_spt_k"] > 0.5).mean()),
                                                     "fault_free": float((n["ct1_minus_spt_k"] > 0.5).mean())},
           "chiller1_lift_delta_k_mean": float((f["chl1_lift_k"] - n["chl1_lift_k"]).mean()),
           "condenser_supply_minus_tower1_delta_k_median": float(
               np.median((f["cdw_sw_c"] - f["ct1_sw_c"]) - (n["cdw_sw_c"] - n["ct1_sw_c"]))),
           # measured chiller evaporator heat (chiller-side sensors), not primary-loop delivered cooling
           "evaporator_heat_kwh_delta": kwh(f, "q_evap_kw") - kwh(n, "q_evap_kw"),
           "tower2_on_hours_frac": {"fault": float(f["CT_STA_2"].mean()), "fault_free": float(n["CT_STA_2"].mean())},
           "tower1_water_flow_delta_gpm_mean": float((f["CT_FLOW_1"] - n["CT_FLOW_1"]).mean()),
           "condenser_bypass_valve_delta_mean": float((f["TWV_CTRL"] - n["TWV_CTRL"]).mean())}
    return out


def signature(n: pd.DataFrame, f: pd.DataFrame) -> dict:
    """Median paired changes that separate a real loss of tower capacity from a biased
    tower-1 temperature sensor or a leaking condenser valve (D4 differential check)."""
    return {"tower1_leaving_water_k": float(np.median(f["ct1_sw_c"] - n["ct1_sw_c"])),
            "condenser_supply_k": float(np.median(f["cdw_sw_c"] - n["cdw_sw_c"])),
            "chiller1_lift_k_mean": float((f["chl1_lift_k"] - n["chl1_lift_k"]).mean()),
            "tower1_fan_speed_mean": float((f["CT_FAN_SPD_1"] - n["CT_FAN_SPD_1"]).mean()),
            "tower_kwh_pct": (kwh(f, "tower_kw") / kwh(n, "tower_kw") - 1) * 100,
            "chiller_kwh_pct": (kwh(f, "chiller_kw") / kwh(n, "chiller_kw") - 1) * 100}


def main() -> int:
    files = sorted(p.stem for p in cache_dir().glob("ChillerPlant*.parquet"))
    normal = load("ChillerPlant")
    tr, te = month_split(normal.index)
    ntr = normal[tr]
    ind = ResidualIndicator(TARGET, INPUTS).fit(ntr, ntr.index.month.to_numpy())

    # existing Part C detection for this fault (committed results)
    det = pd.read_csv(ROOT / "results" / "fdd_detection.csv", dtype={"severity": str})
    day = pd.read_csv(ROOT / "results" / "fdd_detection_daily.csv", dtype={"severity": str})
    en = pd.read_csv(ROOT / "results" / "fdd_energy.csv", dtype={"severity": str})

    rows, per_sev, sigs, scores = [], {}, {}, {}
    for name in files:
        df = load(name)
        _, te_f = month_split(df.index)
        scores[name] = (df["fault_type"].iloc[0], df["severity"].iloc[0], ind.daily_score(df[te_f]))
        if name in SIGNATURE_FILES:
            sigs[name + ".csv"] = signature(normal, df)
        if df["fault_type"].iloc[0] == FAULT:
            per_sev[df["severity"].iloc[0]] = paired_effects(normal, df)
    s_ff = scores["ChillerPlant"][2]
    ff_quant = {"p50": float(s_ff.quantile(0.5)), "p99": float(s_ff.quantile(0.99)), "max": float(s_ff.max())}
    # two operating points, as in Part C: "deployable" (threshold from training months only) and
    # "zero_fa_test" (threshold = largest fault-free TEST-day score: 0 false-alarm days by construction,
    # an ROC point for comparison, not a deployable setting)
    thr = {"deployable": ind.threshold_, "zero_fa_test": float(s_ff.max())}
    for name, (ft, sev, s) in scores.items():
        rows.append([name + ".csv", ft, sev, int(s.size)]
                    + [int((s > thr[k]).sum()) for k in thr] + [float((s > thr[k]).mean()) for k in thr])
        if ft == FAULT:
            d = det[det["file"] == name + ".csv"].iloc[0]
            dy = day[day["file"] == name + ".csv"].iloc[0]
            g = en[en["file"] == name + ".csv"].iloc[0]
            per_sev[sev].update({
                "kw_per_rt_delivered_delta_pct": float(g["kw_per_rt_delivered_delta_pct"]),
                "part_c_detection_hourly": {k: float(d[k]) for k in
                                            ("baseline_deployable_alarm_rate", "ml_deployable_alarm_rate",
                                             "baseline_far1_alarm_rate", "ml_far1_alarm_rate")},
                "part_c_detection_daily_any_hour": {k: float(dy[k]) for k in
                                                    ("baseline_deployable_daily_alarm_rate", "ml_deployable_daily_alarm_rate",
                                                     "baseline_zero_fa_test_daily_alarm_rate",
                                                     "ml_zero_fa_test_daily_alarm_rate")},
                "new_indicator_test_days": int(s.size),
                "new_indicator_median_daily_score_k": float(s.median()),
                "new_indicator_daily_alarm_rate": {k: float((s > thr[k]).mean()) for k in thr}})
    write_csv(RES / "maintenance_8d_indicator.csv",
              ["file", "fault_type", "severity", "test_days", "alarm_days_deployable", "alarm_days_zero_fa_test",
               "daily_alarm_rate_deployable", "daily_alarm_rate_zero_fa_test"], rows)
    nf = [r for r in rows if r[1] == NORMAL][0]
    dff = day[day["fault_type"] == NORMAL].iloc[0]
    summary = {
        "fault_free_operation": {
            "tower2_on_hours_frac": float(normal["CT_STA_2"].mean()),
            "tower3_on_hours_frac": float(normal["CT_STA_3"].mean()),
            "tower2_status_equals_chiller2_status_hours_frac": float(
                ((normal["CT_STA_2"] - normal["CHL_STA_2"]).abs() < 1e-9).mean()),
            "tower1_fan_speed_median": float(normal["CT_FAN_SPD_1"].median()),
            "tower1_fan_off_hours_frac": float((normal["CT_FAN_SPD_1"] <= 0.0).mean()),
            "tower1_leaving_water_below_setpoint_hours_frac": float((normal["ct1_minus_spt_k"] < 0.0).mean())},
        "part_c_fault_free_test_days_alarming_any_hour": {
            "test_days": int(dff["test_days"]),
            "baseline_deployable": int(dff["baseline_deployable_alarm_days"]),
            "ml_deployable": int(dff["ml_deployable_alarm_days"]),
            "baseline_zero_fa_test": int(dff["baseline_zero_fa_test_alarm_days"]),
            "ml_zero_fa_test": int(dff["ml_zero_fa_test_alarm_days"])},
        "fault": FAULT, "documented_fault": "tower 1 heat-transfer coefficient multiplied by 0.95 / 0.80 / 0.65 (LBNL documentation, Table 3)",
        "paired_effects_by_severity": per_sev,
        "differential_signatures": sigs,
        "fault_free_reference": {"plant_kwh": kwh(normal, "plant_kw"),
                                 "tower1_fan_full_speed_hours_frac": float((normal["CT_FAN_SPD_1"] > 0.99).mean())},
        "indicator": {"target": "tower-1 leaving water temperature (degC)", "inputs": INPUTS,
                      "model": "ridge, degree-2 polynomial, standardised inputs, alpha 1",
                      "aggregation": "daily mean of hourly residuals (>= 12 hours)",
                      "threshold_k": thr,
                      "threshold_rule": {"deployable": "99th percentile of out-of-fold daily scores on fault-free training months",
                                         "zero_fa_test": "largest daily score on fault-free test days (comparison only)"},
                      "fault_free_test_days": nf[3], "fault_free_test_alarm_days_deployable": nf[4],
                      "fault_free_test_daily_score_k": ff_quant,
                      "split": "train odd months (fault-free only), test even months, 24 h boundary buffer"},
    }
    write_json(RES / "maintenance_8d_tower_fouling.json", summary)
    for r in rows:
        print(f"{r[0]:62s} {r[4]:4d} {r[5]:4d} /{r[3]:4d}")
    print("thresholds K", thr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
