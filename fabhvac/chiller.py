"""Chiller-plant efficiency, Singapore NEA MEES check, and M&V heat-balance test.

MEES values and the M&V rules are transcribed from NEA pages retrieved 2026-10-02
(see docs/sources.md). NEA marks its table as indicative; the legal values are in the
Fifth Schedule of the Energy Conservation (Energy Management Practices) Regulations.
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np

from .units import NEA_CP_CDW_KJ_KGK, NEA_CP_CHW_KJ_KGK, RT_TO_KW

# ------------------------------------------------------------------ conversions

def kw_per_rt_to_kwe_per_kwc(kw_per_rt: float) -> float:
    return kw_per_rt / RT_TO_KW


def kwe_per_kwc_to_kw_per_rt(kwe_per_kwc: float) -> float:
    return kwe_per_kwc * RT_TO_KW


def cop_from_kwe_per_kwc(kwe_per_kwc: float) -> float:
    if kwe_per_kwc <= 0:
        raise ValueError("efficiency must be positive")
    return 1.0 / kwe_per_kwc


def plant_efficiency_kwe_per_kwc(cooling_kw: float, chiller_kw: float, chw_pump_kw: float = 0.0,
                                 cdw_pump_kw: float = 0.0, tower_kw: float = 0.0) -> float:
    """System efficiency = (chillers + chilled-water pumps + condenser pumps + towers) / cooling."""
    if cooling_kw <= 0:
        raise ValueError("cooling load must be positive")
    parts = (chiller_kw, chw_pump_kw, cdw_pump_kw, tower_kw)
    if any(x < 0 for x in parts):
        raise ValueError("powers must be >= 0")
    return sum(parts) / cooling_kw


# ------------------------------------------------------------------ NEA MEES

MEES_SCOPE_MIN_CAPACITY_KW = 1055.0  # "1055 kW (300 RT) or more", operating + standby chillers
MEES_SCOPE_MIN_CHWS_C = 3.0          # "produces chilled water at a temperature of 3 degC or higher"

# Table 1, general industrial WCCWS: CHWS temperature (rounded up) -> kWe/kWc
MEES_GENERAL = {3: 0.203, 4: 0.200, 5: 0.197, 6: 0.194, 7: 0.191, 8: 0.188, 9: 0.185}
MEES_GENERAL_STEP_ABOVE_9 = 0.003   # improve by 0.003 kWe/kWc per 1 degC above 9 degC

# Table 1, second row (with effect from 1 Apr 2026): new buildings, WCCWS solely for space cooling
MEES_SPACE_COOLING_NEW_BLDG = {3: 0.191, 4: 0.188, 5: 0.185, 6: 0.182}
MEES_SPACE_COOLING_NEW_BLDG_7_PLUS = 0.179


def mees_rounded_chws(chws_c: float) -> int:
    """NEA footnote: chilled water supply temperature 'to be rounded up to the nearest whole number'."""
    # round to 1e-9 first so 7.0000000001 from float noise does not jump to 8
    return int(math.ceil(round(chws_c, 9)))


def mees_limit_kwe_per_kwc(chws_c: float, space_cooling_new_building: bool = False) -> float:
    """Maximum allowed system efficiency (kWe/kWc) at the given chilled-water supply temperature."""
    if chws_c < MEES_SCOPE_MIN_CHWS_C:
        raise ValueError("chilled water below 3 degC is outside MEES scope")
    t = mees_rounded_chws(chws_c)
    if space_cooling_new_building:
        return MEES_SPACE_COOLING_NEW_BLDG.get(t, MEES_SPACE_COOLING_NEW_BLDG_7_PLUS)
    if t <= 9:
        return MEES_GENERAL[t]
    return round(MEES_GENERAL[9] - MEES_GENERAL_STEP_ABOVE_9 * (t - 9), 6)


def mees_in_scope(installed_capacity_kw: float, chws_c: float,
                  brine_or_glycol_only: bool = False) -> bool:
    return (installed_capacity_kw >= MEES_SCOPE_MIN_CAPACITY_KW
            and chws_c >= MEES_SCOPE_MIN_CHWS_C and not brine_or_glycol_only)


def mees_check(kwe_per_kwc: float, chws_c: float, installed_capacity_kw: float,
               space_cooling_new_building: bool = False) -> dict:
    """Return limit, margin and verdict ('PASS', 'FAIL' or 'OUT_OF_SCOPE')."""
    if not mees_in_scope(installed_capacity_kw, chws_c):
        return {"verdict": "OUT_OF_SCOPE", "limit_kwe_per_kwc": None, "margin_kwe_per_kwc": None}
    lim = mees_limit_kwe_per_kwc(chws_c, space_cooling_new_building)
    margin = lim - kwe_per_kwc
    return {"verdict": "PASS" if kwe_per_kwc <= lim else "FAIL",
            "limit_kwe_per_kwc": lim, "margin_kwe_per_kwc": margin}


# ------------------------------------------------------------------ M&V

def water_heat_rate_kw(flow_kg_s, delta_t_k, cp_kj_kgk):
    """Q = m * cp * dT  (NEA reference formula; 1 L/s ~ 1 kg/s)."""
    return np.asarray(flow_kg_s) * cp_kj_kgk * np.asarray(delta_t_k)


def cooling_load_kw(chw_flow_kg_s, chw_return_c, chw_supply_c):
    return water_heat_rate_kw(chw_flow_kg_s, np.asarray(chw_return_c) - np.asarray(chw_supply_c),
                              NEA_CP_CHW_KJ_KGK)


def heat_rejection_kw(cdw_flow_kg_s, cdw_leaving_chiller_c, cdw_entering_chiller_c):
    return water_heat_rate_kw(cdw_flow_kg_s,
                              np.asarray(cdw_leaving_chiller_c) - np.asarray(cdw_entering_chiller_c),
                              NEA_CP_CDW_KJ_KGK)


def heat_balance_pct(cooling_kw, work_input_kw, heat_rejection_kw_):
    """NEA system heat balance = (cooling load + work input - heat rejection) / heat rejection x 100."""
    q_c = np.asarray(heat_rejection_kw_, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):  # q_c == 0 -> inf/nan, filtered by callers
        return (np.asarray(cooling_kw, dtype=float) + np.asarray(work_input_kw, dtype=float) - q_c) / q_c * 100.0


def compressor_work_input_kw(measured_kw, vsd_eff: float = 1.0, motor_eff: float = 1.0):
    """Hermetic: measured x VSD eff; open-type: measured x motor eff x VSD eff (NEA M&V guide)."""
    for e in (vsd_eff, motor_eff):
        if not (0 < e <= 1):
            raise ValueError("efficiencies must be in (0, 1]")
    return np.asarray(measured_kw, dtype=float) * motor_eff * vsd_eff


def heat_balance_test(cooling_kw, work_input_kw, heat_rejection_kw_, tol_pct: float = 5.0,
                      required_fraction: float = 0.80) -> dict:
    """Heat balance within +/-tol_pct for >= required_fraction of operating points."""
    hb = heat_balance_pct(cooling_kw, work_input_kw, heat_rejection_kw_)
    hb = hb[np.isfinite(hb)]
    if hb.size == 0:
        raise ValueError("no valid operating points")
    frac = float(np.mean(np.abs(hb) <= tol_pct))
    return {"n_points": int(hb.size), "fraction_within": frac,
            "passes": frac >= required_fraction,
            "median_pct": float(np.median(hb))}


def mv_system_uncertainty_pct(u_t_supply_k: float, u_t_return_k: float, delta_t_chw_k: float,
                              u_flow_pct: float, u_power_pct: float) -> float:
    """Overall M&V uncertainty sqrt(dUT^2 + UF^2 + UP^2), dUT = sqrt(UTs^2+UTr^2)/dT_chw (in %)."""
    if delta_t_chw_k <= 0:
        raise ValueError("chilled-water delta T must be positive")
    d_ut = math.sqrt(u_t_supply_k ** 2 + u_t_return_k ** 2) / delta_t_chw_k * 100.0
    return math.sqrt(d_ut ** 2 + u_flow_pct ** 2 + u_power_pct ** 2)


MV_MAX_UNCERTAINTY_PCT = 5.0
MV_SENSOR_LIMITS = {"temperature_k": 0.05, "flow_pct": 1.0, "power_pct": 2.0}


def min_chw_delta_t_for_uncertainty(u_t_k: float = 0.05, u_flow_pct: float = 1.0,
                                    u_power_pct: float = 2.0,
                                    max_pct: float = MV_MAX_UNCERTAINTY_PCT) -> Optional[float]:
    """Smallest chilled-water delta T (K) at which the overall uncertainty stays <= max_pct."""
    rest = max_pct ** 2 - u_flow_pct ** 2 - u_power_pct ** 2
    if rest <= 0:
        return None
    return math.sqrt(2.0) * u_t_k * 100.0 / math.sqrt(rest)
