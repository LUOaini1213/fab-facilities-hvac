"""Part C step 1: reduce the raw LBNL chiller-plant CSVs (1-minute, ~10 GB) to hourly
windows and per-scenario annual summaries.

Raw data are NOT in this repository. Point LBNL_FDD_DIR at the folder holding the
extracted ChillerPlant*.csv files. The hourly cache goes to LBNL_FDD_CACHE (default:
<LBNL_FDD_DIR>/_cache). Committed outputs (small, derived):

  results/fdd_scenarios.csv      annual energy, kW/RT, heat-balance test per scenario
  results/fdd_data_checks.json   documentation-vs-data checks used by fabhvac.fdd.data
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fabhvac import chiller  # noqa: E402
from fabhvac.fdd.data import (DOCUMENTED_FAULTS, NORMAL, derive_signals,  # noqa: E402
                              heat_balance_fraction, parse_scenario, window_aggregate)
from fabhvac.results_io import write_csv, write_json  # noqa: E402
from fabhvac.fdd.data import GPM_TO_KG_S  # noqa: E402
from fabhvac.units import NEA_CP_CHW_KJ_KGK, RT_TO_KW, f_to_c  # noqa: E402

RES = Path(os.environ.get("FABHVAC_RESULTS_DIR", ROOT / "results"))
DOC_FILES = 22  # documentation Table 4 lists 21 faulted files + 1 fault-free


def raw_dir() -> Path:
    d = os.environ.get("LBNL_FDD_DIR")
    if not d:
        sys.exit("set LBNL_FDD_DIR to the folder with the extracted ChillerPlant*.csv files")
    return Path(d)


def cache_dir() -> Path:
    return Path(os.environ.get("LBNL_FDD_CACHE", raw_dir() / "_cache"))


def annual(raw: pd.DataFrame, d: pd.DataFrame) -> dict:
    kwh = d["plant_kw"].sum() / 60.0
    cool = d["q_evap_kw"].sum() / 60.0
    w = d["q_evap_kw"].clip(lower=0)
    chws = float((d["chw_supply_c"] * w).sum() / w.sum())
    summer = raw["Datetime"].dt.month.isin([6, 7, 8]).to_numpy()
    # cooling delivered by the primary loop, from primary-loop sensors (no fault is imposed on them)
    q_pri = (raw["CWL_PRI_CW_FLOW"] * GPM_TO_KG_S * NEA_CP_CHW_KJ_KGK
             * (raw["CWL_PRI_RW_TEMP"] - raw["CWL_PRI_SW_TEMP"]) / 1.8)
    hourly_err = (d["chw_supply_err_k"].groupby(raw["Datetime"].dt.floor("1h")).mean())
    return {"plant_kwh": kwh, "chiller_kwh": d["chiller_kw"].sum() / 60.0,
            "pump_kwh": (d["chw_pump_kw"] + d["cdw_pump_kw"]).sum() / 60.0,
            "tower_kwh": d["tower_kw"].sum() / 60.0,
            "cooling_kwh_measured": cool, "plant_kw_per_rt_measured": kwh / (cool / RT_TO_KW),
            "summer_plant_kwh": d.loc[summer, "plant_kw"].sum() / 60.0,
            "summer_cooling_kwh_measured": d.loc[summer, "q_evap_kw"].sum() / 60.0,
            "load_weighted_chws_c": chws,
            "delivered_cooling_kwh": q_pri.sum() / 60.0,
            "summer_delivered_cooling_kwh": q_pri[summer].sum() / 60.0,
            "hours_chws_above_spt_1k_frac": float((hourly_err > 1.0).mean()),
            }


def main() -> int:
    src = raw_dir()
    out = cache_dir()
    out.mkdir(parents=True, exist_ok=True)
    files = sorted(p.name for p in src.glob("ChillerPlant*.csv"))
    scen = [parse_scenario(f) for f in files]
    normal_file = [s.file for s in scen if s.fault_type == NORMAL]
    assert len(normal_file) == 1, normal_file
    order = normal_file + [s.file for s in scen if s.fault_type != NORMAL]

    checks = {"n_files": len(files), "n_files_in_documentation": DOC_FILES,
              "files_not_in_documentation": [s.file for s in scen if s.fault_type not in DOCUMENTED_FAULTS + (NORMAL,)],
              "per_file_rows": {}}
    ref = None
    rows = []
    for f in order:
        s = parse_scenario(f)
        raw = pd.read_csv(src / f, engine="pyarrow")
        checks["per_file_rows"][f] = int(len(raw))
        d = derive_signals(raw)
        if ref is None:
            ref = {"datetime": raw["Datetime"].to_numpy(), "cool": d["q_evap_kw"].to_numpy()}
            # documentation vs data checks on the fault-free file
            ct_db = (np.maximum(raw["OA_TEMP_WB"] + 8, 60) - raw["CT_SW_TEMPSPT"]).abs()
            ct_wb = (np.maximum(raw["OA_TEMP"] + 8, 60) - raw["CT_SW_TEMPSPT"]).abs()
            op = d["q_cond_kw"] > 1.0
            checks["outdoor_columns"] = {
                "fraction_OA_TEMP_WB_ge_OA_TEMP": float((raw["OA_TEMP_WB"] >= raw["OA_TEMP"]).mean()),
                "ct_setpoint_vs_max(col+8F,60F)_median_abs_err_F": {
                    "OA_TEMP": float(ct_wb.median()), "OA_TEMP_WB": float(ct_db.median())},
                "ct_setpoint_vs_max(col+8F,60F)_p90_abs_err_F": {
                    "OA_TEMP": float(ct_wb.quantile(0.9)), "OA_TEMP_WB": float(ct_db.quantile(0.9))},
                "conclusion": "OA_TEMP is used as wet bulb, OA_TEMP_WB as dry bulb"}
            checks["chw_setpoint_F"] = {"min": float(raw["CWL_PRI_SW_TEMPSPT"].min()),
                                        "max": float(raw["CWL_PRI_SW_TEMPSPT"].max()),
                                        "documented_range_F": [42, 52]}
            checks["energy_closure_fault_free_annual_MWh"] = {
                "chiller_evaporator_heat": float(d["q_evap_kw"].sum() / 60e3),
                "chiller_electric_input": float(d["chiller_kw"].sum() / 60e3),
                "chiller_condenser_heat": float(d["q_cond_kw"].sum() / 60e3),
                "secondary_loop_load_CWL_SEC_LOAD": float(d["sec_load_kw"].sum() / 60e3),
                "evap_plus_input_over_condenser": float((d["q_evap_kw"].sum() + d["chiller_kw"].sum()) / d["q_cond_kw"].sum()),
                "chiller1_cop_median_when_q_evap_gt_100kW": float(d.loc[d["q_evap_1_kw"] > 100, "chiller1_cop"].median()),
                "max_plant_cooling_kw": float(d.loc[op, "q_evap_kw"].max())}
        else:
            checks.setdefault("timestamps_identical_to_fault_free", {})[f] = bool(
                len(raw) == len(ref["datetime"]) and (raw["Datetime"].to_numpy() == ref["datetime"]).all())
        a = annual(raw, d)
        if s.fault_type == NORMAL:
            base = a
        hb = heat_balance_fraction(raw)
        chws_lim = chiller.mees_limit_kwe_per_kwc(a["load_weighted_chws_c"])
        kwrt_true_load = a["plant_kwh"] / (ref["cool"].sum() / 60.0 / RT_TO_KW)
        rows.append({"file": f, "fault_type": s.fault_type, "severity": s.severity,
                     "plant_kwh": a["plant_kwh"], "chiller_kwh": a["chiller_kwh"], "pump_kwh": a["pump_kwh"],
                     "tower_kwh": a["tower_kwh"],
                     "plant_kwh_delta_pct": (a["plant_kwh"] / base["plant_kwh"] - 1) * 100,
                     "summer_plant_kwh_delta_pct": (a["summer_plant_kwh"] / base["summer_plant_kwh"] - 1) * 100,
                     "cooling_kwh_measured": a["cooling_kwh_measured"],
                     "kw_per_rt_measured_load": a["plant_kw_per_rt_measured"],
                     "kw_per_rt_fault_free_load": kwrt_true_load,
                     "kwe_per_kwc_fault_free_load": kwrt_true_load / RT_TO_KW,
                     "delivered_cooling_kwh": a["delivered_cooling_kwh"],
                     "delivered_cooling_delta_pct": (a["delivered_cooling_kwh"] / base["delivered_cooling_kwh"] - 1) * 100,
                     "kw_per_rt_delivered": a["plant_kwh"] / (a["delivered_cooling_kwh"] / RT_TO_KW),
                     "kw_per_rt_delivered_delta_pct": (a["plant_kwh"] / a["delivered_cooling_kwh"]
                                                       / (base["plant_kwh"] / base["delivered_cooling_kwh"]) - 1) * 100,
                     "summer_kw_per_rt_delivered": a["summer_plant_kwh"] / (a["summer_delivered_cooling_kwh"] / RT_TO_KW),
                     "summer_kw_per_rt_delivered_delta_pct": (a["summer_plant_kwh"] / a["summer_delivered_cooling_kwh"]
                                                              / (base["summer_plant_kwh"] / base["summer_delivered_cooling_kwh"]) - 1) * 100,
                     "hours_chws_above_spt_1k_frac": a["hours_chws_above_spt_1k_frac"],
                     "load_weighted_chws_c": a["load_weighted_chws_c"],
                     "mees_limit_kwe_per_kwc_at_chws": chws_lim,
                     "hb_points": hb["n_points"], "hb_fraction_within_5pct": hb["fraction_within"],
                     "hb_median_pct": hb["median_pct"], "hb_passes_80pct_rule": hb["fraction_within"] >= 0.8})
        hourly = window_aggregate(raw, "1h")
        hourly["file"] = f
        hourly["fault_type"] = s.fault_type
        hourly["severity"] = s.severity
        hourly.to_parquet(out / (f[:-4] + ".parquet"))
        print(f"{f:62s} kWh {a['plant_kwh']:.0f}  hb_within {hb['fraction_within']:.3f}", flush=True)
        del raw, d, hourly

    header = list(rows[0].keys())
    write_csv(RES / "fdd_scenarios.csv", header, [[r[k] for k in header] for r in rows])
    checks["doc_chw_setpoint_F_documented"] = "42-52 F (documentation eq. 2)"
    checks["fahrenheit_to_celsius_example"] = f_to_c(44.0)
    write_json(RES / "fdd_data_checks.json", checks)
    return 0


if __name__ == "__main__":
    sys.exit(main())
