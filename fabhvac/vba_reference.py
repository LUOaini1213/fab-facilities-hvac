"""Python reference for every VBA worksheet function in excel/FabHvac.bas, plus the
fixed parity grid. Used by scripts/vba_parity.py (with Excel) and by the CI test that
checks the committed VBA outputs (results/vba_parity.csv) against Python (no Excel).
"""

from __future__ import annotations

import psychrolib as _psy

from . import chiller, cleanroom, tower

_psy.SetUnitSystem(_psy.SI)

ERR = "ERR"


def _mees_check(eff, chws, cap, space=False):
    return chiller.mees_check(eff, chws, cap, space)["verdict"]


def _ct_eff(tin, tout, twb):
    return tower.scalar(tower.tower_effectiveness(tin, tout, twb))


def _heat_balance(qe, w, qc):
    if qc == 0:
        raise ValueError("zero heat rejection")
    return float(chiller.heat_balance_pct(qe, w, qc))


def _psy_w_twb(tdb, twb, p):
    return _psy.GetHumRatioFromTWetBulb(tdb, twb, p)


def _psy_h(t, w):
    return _psy.GetMoistAirEnthalpy(t, w)


FUNCTIONS = {
    "FH_ISO_CLASS_LIMIT": cleanroom.iso_class_limit,
    "FH_ISO_CLASS_FROM_CONC": cleanroom.iso_class_from_concentration,
    "FH_UD_AIRFLOW": cleanroom.unidirectional_airflow_m3s,
    "FH_FFU_COUNT": cleanroom.ffu_count,
    "FH_ACH": cleanroom.air_changes_per_hour,
    "FH_WM_CONC": cleanroom.well_mixed_concentration,
    "FH_WM_REQUIRED_Q": cleanroom.required_airflow_well_mixed,
    "FH_KWRT_TO_KWEKWC": chiller.kw_per_rt_to_kwe_per_kwc,
    "FH_KWEKWC_TO_KWRT": chiller.kwe_per_kwc_to_kw_per_rt,
    "FH_COP": chiller.cop_from_kwe_per_kwc,
    "FH_PLANT_EFF": chiller.plant_efficiency_kwe_per_kwc,
    "FH_MEES_LIMIT": chiller.mees_limit_kwe_per_kwc,
    "FH_MEES_CHECK": _mees_check,
    "FH_HEAT_BALANCE_PCT": _heat_balance,
    "FH_MV_UNCERTAINTY": chiller.mv_system_uncertainty_pct,
    "FH_CT_RANGE": lambda a, b: tower.scalar(tower.tower_range(a, b)),
    "FH_CT_APPROACH": lambda a, b: tower.scalar(tower.tower_approach(a, b)),
    "FH_CT_EFFECTIVENESS": _ct_eff,
    "FH_PSY_PWS": _psy.GetSatVapPres,
    "FH_PSY_W_RH": _psy.GetHumRatioFromRelHum,
    "FH_PSY_W_TWB": _psy_w_twb,
    "FH_PSY_W_TDP": _psy.GetHumRatioFromTDewPoint,
    "FH_PSY_H": _psy_h,
    "FH_PSY_TDP": _psy.GetTDewPointFromHumRatio,
    "FH_PSY_TWB": _psy.GetTWetBulbFromHumRatio,
}


def python_value(name, args):
    try:
        return FUNCTIONS[name](*args)
    except ValueError:
        return ERR


def grid():
    """Fixed, asymmetric parity inputs (including invalid ones that must be rejected)."""
    g = []
    for n in (1, 3.5, 5, 7, 9):
        for d in (0.1, 0.3, 0.5, 2.0, 5.0):
            g.append(("FH_ISO_CLASS_LIMIT", (n, d)))
    g += [("FH_ISO_CLASS_LIMIT", (0.5, 0.5)), ("FH_ISO_CLASS_LIMIT", (5, 0.05)), ("FH_ISO_CLASS_LIMIT", (5, 6.0))]
    for c, d in ((3520.0, 0.5), (29300.0, 5.0), (237.0, 0.2), (1.0e6, 0.1), (0.0, 0.5)):
        g.append(("FH_ISO_CLASS_FROM_CONC", (c, d)))
    g += [("FH_UD_AIRFLOW", (0.45, 123.4)), ("FH_UD_AIRFLOW", (0.3, 7.7)), ("FH_UD_AIRFLOW", (0.0, 10.0))]
    g += [("FH_FFU_COUNT", (600.0, 1.0, 0.72)), ("FH_FFU_COUNT", (250.0, 0.35, 0.72)),
          ("FH_FFU_COUNT", (72.0, 1.0, 0.72)), ("FH_FFU_COUNT", (100.0, 1.2, 0.72))]
    g += [("FH_ACH", (240.0, 2400.0)), ("FH_ACH", (1.37, 950.0)), ("FH_ACH", (1.0, 0.0))]
    g += [("FH_WM_CONC", (2.0e5, 3.1, 0.9997, 0.1, 3.0e7, 0.9)), ("FH_WM_CONC", (5.0e4, 0.8, 0.95, 0.0, 0.0, 0.0)),
          ("FH_WM_CONC", (1.0e5, 2.0, 0.995, 0.3, 1.0e8, 0.5)), ("FH_WM_CONC", (1.0e5, 2.0, 1.0, 0.3, 1.0e8, 0.5))]
    g += [("FH_WM_REQUIRED_Q", (2.0e5, 352000.0, 0.9997, 0.1, 3.0e7, 0.9)),
          ("FH_WM_REQUIRED_Q", (3.3e6, 35200.0, 0.995, 0.25, 2.0e7, 0.6)),
          ("FH_WM_REQUIRED_Q", (1.0e5, 100.0, 0.9, 1.0, 1.0e8, 0.0))]
    for x in (0.55, 0.68, 0.71, 0.913):
        g.append(("FH_KWRT_TO_KWEKWC", (x,)))
    for x in (0.152, 0.191, 0.203, 0.26):
        g.append(("FH_KWEKWC_TO_KWRT", (x,)))
    g += [("FH_COP", (0.18875,)), ("FH_COP", (0.0,))]
    g += [("FH_PLANT_EFF", (4000.0, 560.0, 70.0, 80.0, 45.0)), ("FH_PLANT_EFF", (1234.5, 201.0, 17.3, 22.9, 8.4)),
          ("FH_PLANT_EFF", (0.0, 1.0, 0.0, 0.0, 0.0))]
    for t in (2.9, 3.0, 3.2, 5.0, 6.01, 6.5, 9.0, 9.4, 10.0, 12.7):
        g.append(("FH_MEES_LIMIT", (t, False)))
    for t in (3.0, 4.5, 6.0, 6.2, 7.0, 11.0):
        g.append(("FH_MEES_LIMIT", (t, True)))
    g += [("FH_MEES_CHECK", (0.18875, 6.5, 7000.0, False)), ("FH_MEES_CHECK", (0.193, 6.5, 7000.0, False)),
          ("FH_MEES_CHECK", (0.193, 5.2, 7000.0, False)), ("FH_MEES_CHECK", (0.25, 6.5, 1000.0, False)),
          ("FH_MEES_CHECK", (0.181, 6.5, 2000.0, True)), ("FH_MEES_CHECK", (0.2, 2.5, 9000.0, False)),
          # invalid: negative efficiency / capacity are rejected before the scope test
          ("FH_MEES_CHECK", (-0.1, 7.0, 2000.0, False)), ("FH_MEES_CHECK", (0.19, 7.0, -5.0, False)),
          ("FH_MEES_CHECK", (-0.1, 6.5, 500.0, False))]
    g += [("FH_HEAT_BALANCE_PCT", (1000.0, 180.0, 1150.0)), ("FH_HEAT_BALANCE_PCT", (812.3, 160.4, 1003.9)),
          ("FH_HEAT_BALANCE_PCT", (1.0, 1.0, 0.0))]
    g += [("FH_MV_UNCERTAINTY", (0.05, 0.05, 5.5, 1.0, 2.0)), ("FH_MV_UNCERTAINTY", (0.03, 0.07, 3.1, 0.8, 1.5)),
          ("FH_MV_UNCERTAINTY", (0.05, 0.05, 0.0, 1.0, 2.0))]
    g += [("FH_CT_RANGE", (37.0, 31.5)), ("FH_CT_RANGE", (35.2, 29.9)),
          ("FH_CT_APPROACH", (31.5, 27.5)), ("FH_CT_APPROACH", (29.9, 26.1)),
          ("FH_CT_EFFECTIVENESS", (37.0, 31.5, 27.5)), ("FH_CT_EFFECTIVENESS", (35.2, 29.9, 26.1)),
          ("FH_CT_EFFECTIVENESS", (25.0, 24.0, 26.0))]
    for t in (-20.0, -0.5, 0.01, 0.02, 12.3, 25.0, 33.2, 47.9, 95.0, 250.0):
        g.append(("FH_PSY_PWS", (t,)))
    for t, rh, p in ((22.0, 0.45, 101325.0), (33.2, 0.584, 101240.0), (5.0, 0.95, 101325.0),
                     (40.0, 0.2, 90000.0), (-5.0, 0.6, 101325.0), (25.0, 1.1, 101325.0)):
        g.append(("FH_PSY_W_RH", (t, rh, p)))
    for tdb, twb, p in ((33.2, 26.3, 101240.0), (29.4, 27.6, 101240.0), (15.0, 9.0, 95000.0),
                        (2.0, -1.0, 101325.0), (20.0, 21.0, 101325.0)):
        g.append(("FH_PSY_W_TWB", (tdb, twb, p)))
    for tdp, p in ((27.1, 101240.0), (9.43, 101240.0), (-3.0, 101325.0), (14.2, 85000.0)):
        g.append(("FH_PSY_W_TDP", (tdp, p)))
    for t, w in ((33.2, 0.0188), (22.0, 0.0074), (-10.0, 0.0012), (45.0, 0.031), (20.0, -0.001)):
        g.append(("FH_PSY_H", (t, w)))
    for t, w, p in ((33.2, 0.0188, 101240.0), (22.0, 0.0074, 101325.0), (29.4, 0.02285, 101240.0),
                    (10.0, 0.002, 101325.0), (-5.0, 0.0015, 101325.0)):
        g.append(("FH_PSY_TDP", (t, w, p)))
        g.append(("FH_PSY_TWB", (t, w, p)))
    return g
