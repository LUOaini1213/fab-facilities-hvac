"""LBNL FDD chiller-plant dataset: scenario parsing, unit conversion and derived signals.

Raw data (not in this repository): Granderson et al., LBNL Fault Detection and Diagnostics
Datasets, OEDI 2022, CC BY 4.0. 1-minute data, IP units (degF, GPM, kW; secondary-loop
load in W, differential pressure in inH2O).

Data-quality findings that this module encodes (evidence in results/fdd_data_checks.json):
  * OA_TEMP behaves as the outdoor WET bulb and OA_TEMP_WB as the DRY bulb: OA_TEMP_WB is
    never below OA_TEMP, and the cooling-tower set point equals max(OA_TEMP + 8 F, 60 F),
    which is the documented wet-bulb reset. We therefore map t_wb <- OA_TEMP and
    t_db <- OA_TEMP_WB.
  * The archive contains chiller_fouling_065/095 files that the documentation PDF does not
    list; they are kept and labelled from the file name.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..units import GPM_TO_M3_S, NEA_CP_CDW_KJ_KGK, NEA_CP_CHW_KJ_KGK, RT_TO_KW, f_to_c

GPM_TO_KG_S = GPM_TO_M3_S * 1000.0  # NEA M&V guide: 1 L/s of water ~ 1 kg/s
CHILLERS = (1, 2, 3)
TOWERS = (1, 2, 3)
DOCUMENTED_FAULTS = ("coolingtower_bias", "chiller_bias", "secondary_chilled_water_pressure_bias",
                     "bypass_leakage", "bypass_stuck", "coolingtower_fouling", "coolingtower_PI")
UNDOCUMENTED_FAULTS = ("chiller_fouling",)
FAULT_TYPES = DOCUMENTED_FAULTS + UNDOCUMENTED_FAULTS
NORMAL = "normal"


@dataclass(frozen=True)
class Scenario:
    file: str
    fault_type: str      # NORMAL or one of FAULT_TYPES
    severity: str        # e.g. "-1", "025", "PI", "" for normal
    severity_value: float  # numeric intensity in the documented unit (degC, %, ...); nan if n/a


_PAT = re.compile(r"^ChillerPlant(?:_(?P<body>.+))?\.csv$")


def parse_scenario(filename: str) -> Scenario:
    m = _PAT.match(filename)
    if not m:
        raise ValueError(f"not a chiller-plant file: {filename}")
    body = m.group("body")
    if body is None:
        return Scenario(filename, NORMAL, "", float("nan"))
    if body == "coolingtower_PI":
        return Scenario(filename, "coolingtower_PI", "PI", float("nan"))
    for ft in sorted(FAULT_TYPES, key=len, reverse=True):
        if body.startswith(ft + "_"):
            sev = body[len(ft) + 1:]
            # degC for the temperature-sensor biases, percent otherwise ("-010" -> -10.0, "065" -> 65.0)
            val = float(sev)
            return Scenario(filename, ft, sev, val)
    raise ValueError(f"unknown fault in file name: {filename}")


def derive_signals(df: pd.DataFrame) -> pd.DataFrame:
    """Per-row derived signals in SI units. Works on 1-minute or window-averaged rows."""
    out = pd.DataFrame(index=df.index)
    out["t_wb_c"] = f_to_c(df["OA_TEMP"])        # see module docstring: columns are swapped
    out["t_db_c"] = f_to_c(df["OA_TEMP_WB"])
    out["sec_load_kw"] = df["CWL_SEC_LOAD"] / 1000.0
    out["n_chillers_on"] = sum(df[f"CHL_STA_{i}"] for i in CHILLERS)
    out["chw_spt_c"] = f_to_c(df["CWL_PRI_SW_TEMPSPT"])
    out["ct_spt_c"] = f_to_c(df["CT_SW_TEMPSPT"])

    q_evap = 0.0
    q_cond = 0.0
    for i in CHILLERS:
        m_chw = df[f"CHL_CW_FLOW_{i}"] * GPM_TO_KG_S
        m_cdw = df[f"CHL_CD_FLOW_{i}"] * GPM_TO_KG_S
        dt_chw = (df[f"CHL_RW_TEMP_{i}"] - df[f"CHL_SW_TEMP_{i}"]) / 1.8
        dt_cdw = (df[f"CHL_SWCD_TEMP_{i}"] - df[f"CHL_RWCD_TEMP_{i}"]) / 1.8
        qe = m_chw * NEA_CP_CHW_KJ_KGK * dt_chw
        qc = m_cdw * NEA_CP_CDW_KJ_KGK * dt_cdw
        out[f"q_evap_{i}_kw"] = qe
        out[f"q_cond_{i}_kw"] = qc
        q_evap = q_evap + qe
        q_cond = q_cond + qc
    out["q_evap_kw"] = q_evap
    out["q_cond_kw"] = q_cond
    out["chiller_kw"] = sum(df[f"CHL_POW_{i}"] for i in CHILLERS)
    out["chw_pump_kw"] = (sum(df[f"CWL_PRI_PM_POW_{i}"] for i in CHILLERS)
                          + df["CWL_SEC_PM_POW_1"] + df["CWL_SEC_PM_POW_2"])
    out["cdw_pump_kw"] = sum(df[f"CDWL_PM_POW_{i}"] for i in CHILLERS)
    out["tower_kw"] = sum(df[f"CT_POW_{i}"] for i in TOWERS)
    out["plant_kw"] = out["chiller_kw"] + out["chw_pump_kw"] + out["cdw_pump_kw"] + out["tower_kw"]
    with np.errstate(divide="ignore", invalid="ignore"):
        out["plant_kw_per_rt"] = out["plant_kw"] / (out["q_evap_kw"] / RT_TO_KW)
        out["heat_balance_pct"] = (out["q_evap_kw"] + out["chiller_kw"] - out["q_cond_kw"]) / out["q_cond_kw"] * 100
        out["chiller1_cop"] = out["q_evap_1_kw"] / df["CHL_POW_1"]
    out["chw_supply_c"] = f_to_c(df["CWL_PRI_SW_TEMP"])
    out["chw_supply_err_k"] = (df["CWL_PRI_SW_TEMP"] - df["CWL_PRI_SW_TEMPSPT"]) / 1.8
    out["chl1_sw_minus_pri_sw_k"] = (df["CHL_SW_TEMP_1"] - df["CWL_PRI_SW_TEMP"]) / 1.8
    out["ct1_approach_k"] = f_to_c(df["CT_SW_TEMP_1"]) - out["t_wb_c"]
    out["ct1_range_k"] = (df["CT_RW_TEMP_1"] - df["CT_SW_TEMP_1"]) / 1.8
    out["ct1_minus_spt_k"] = (df["CT_SW_TEMP_1"] - df["CT_SW_TEMPSPT"]) / 1.8
    out["cdw_supply_minus_ct1_k"] = (df["CDWL_SW_TEMP"] - df["CT_SW_TEMP_1"]) / 1.8
    out["chl1_lift_k"] = (df["CHL_SWCD_TEMP_1"] - df["CHL_SW_TEMP_1"]) / 1.8
    out["sec_dp_err_pct"] = (df["CWL_SEC_DP"] - df["CWL_SEC_DPSPT"]) / df["CWL_SEC_DPSPT"] * 100
    out["twv_ctrl"] = df["TWV_CTRL"]
    out["ct1_fan_spd"] = df["CT_FAN_SPD_1"]
    out["sec_pump_spd"] = df["CWL_SEC_PM_SPD_1"]
    return out


STD_COLUMNS = ("CT_FAN_SPD_1", "TWV_CTRL", "CHL_SW_TEMP_1", "CT_SW_TEMP_1", "CWL_SEC_DP",
               "CHL_COMP_SPD_CTRL_1", "CWL_SEC_PM_SPD_1", "CDWL_SW_TEMP")


def window_aggregate(raw: pd.DataFrame, freq: str = "1h") -> pd.DataFrame:
    """Window means of every raw column, window std of selected columns, derived signals of
    the window means, and energy-based window ratios (kWh / RTh, heat balance of energies)."""
    df = raw.set_index("Datetime")
    num = df.select_dtypes("number")
    g = num.resample(freq, label="left", closed="left")
    mean = g.mean()
    std = g.std(ddof=0)[list(STD_COLUMNS)].add_suffix("__std")
    count = g.size().rename("n_minutes")
    der = derive_signals(mean)
    agg = pd.concat([mean, std, count, der], axis=1)
    return agg[agg["n_minutes"] > 0]


def heat_balance_fraction(raw: pd.DataFrame, tol_pct: float = 5.0, min_cond_kw: float = 1.0) -> dict:
    """NEA-style heat-balance test on 1-minute rows where the plant is rejecting heat."""
    d = derive_signals(raw)
    op = (d["q_cond_kw"] > min_cond_kw) & (d["chiller_kw"] > 0)
    hb = d.loc[op, "heat_balance_pct"].to_numpy()
    hb = hb[np.isfinite(hb)]
    return {"n_points": int(hb.size),
            "fraction_within": float(np.mean(np.abs(hb) <= tol_pct)) if hb.size else float("nan"),
            "median_pct": float(np.median(hb)) if hb.size else float("nan"),
            "p05_pct": float(np.percentile(hb, 5)) if hb.size else float("nan"),
            "p95_pct": float(np.percentile(hb, 95)) if hb.size else float("nan")}
