import math

import psychrolib as psy
import pytest

from fabhvac import loads, psychro
from fabhvac.design_data import CHANGI_2021
from fabhvac.units import RT_TO_KW

psy.SetUnitSystem(psy.SI)
P_SG = CHANGI_2021["std_pressure_kpa"] * 1000


# ---------------------------------------------------------------- psychrolib vs CoolProp
GRID = [(t, rh, p) for p in (101325.0, 95000.0) for t in (5.0, 18.0, 27.5, 42.5) for rh in (0.15, 0.55, 0.95)]


@pytest.mark.parametrize("t,rh,p", GRID)
def test_against_coolprop(t, rh, p):
    """PsychroLib (ideal-gas ASHRAE eqs) vs CoolProp (real-gas with enhancement factor).

    Tolerances: humidity ratio 0.6 % (CoolProp includes the water-vapour enhancement
    factor, ~0.4-0.5 % near 1 atm), dew point 0.02 K, wet bulb 0.03 K, enthalpy 0.4 %.
    """
    s = psychro.state_tdb_rh(t, rh, p)
    hap = pytest.importorskip("CoolProp.HumidAirProp").HAPropsSI
    tk = t + 273.15
    assert s.w == pytest.approx(hap("W", "T", tk, "R", rh, "P", p), rel=6e-3)
    assert s.tdp_c == pytest.approx(hap("Tdp", "T", tk, "R", rh, "P", p) - 273.15, abs=0.02)
    assert s.twb_c == pytest.approx(hap("Twb", "T", tk, "R", rh, "P", p) - 273.15, abs=0.03)
    assert s.h_j_kg == pytest.approx(hap("H", "T", tk, "R", rh, "P", p), rel=4e-3)


# ---------------------------------------------------------------- ASHRAE 2021 Changi table
PAIRS = [("dehum_0p4_dp_c", "dehum_0p4_hr_g_kg"), ("dehum_1p0_dp_c", "dehum_1p0_hr_g_kg"),
         ("dehum_2p0_dp_c", "dehum_2p0_hr_g_kg"), ("humid_99p6_dp_c", "humid_99p6_hr_g_kg"),
         ("humid_99p0_dp_c", "humid_99p0_hr_g_kg")]


@pytest.mark.parametrize("dp_key,hr_key", PAIRS)
def test_published_humidity_ratio_consistent_with_published_dew_point(dp_key, hr_key):
    """Both published values are rounded to 0.1; the intervals they stand for must overlap."""
    dp, hr = CHANGI_2021[dp_key], CHANGI_2021[hr_key]
    lo = psychro.hum_ratio_from_tdp(dp - 0.05, P_SG) * 1000
    hi = psychro.hum_ratio_from_tdp(dp + 0.05, P_SG) * 1000
    assert lo <= hr + 0.05 and hi >= hr - 0.05


def test_state_from_enthalpy_design_point():
    """ASHRAE enthalpy design point: h = 88.8 kJ/kg at MCDB 31.0 degC. Independent check with
    the ASHRAE enthalpy equation h = 1.006 t + W (2501 + 1.86 t) (kJ/kg)."""
    s = psychro.state_tdb_h(31.0, 88800.0, P_SG)
    assert s.tdb_c == 31.0
    assert s.h_j_kg == pytest.approx(88800.0, rel=1e-12)
    assert s.w == pytest.approx((88.8 - 1.006 * 31.0) / (2501 + 1.86 * 31.0), rel=1e-12)
    assert s.w * 1000 == pytest.approx(22.517, abs=1e-3)
    with pytest.raises(ValueError):
        psychro.state_tdb_h(31.0, 120000.0, P_SG)      # above saturation at 31 degC


def test_state_constructors_roundtrip():
    s = psychro.state_tdb_twb(33.2, 26.3, P_SG)
    assert s.twb_c == pytest.approx(26.3, abs=2e-3)
    assert s.w * 1000 == pytest.approx(18.822, abs=1e-3)
    d = psychro.state_tdb_tdp(29.4, 27.1, P_SG)
    assert d.tdp_c == pytest.approx(27.1, abs=2e-3)
    r = psychro.state_tdb_rh(22.0, 0.45, 101325.0)
    assert r.rh == pytest.approx(0.45, abs=1e-12)
    assert r.v_m3_kg == pytest.approx(psy.GetMoistAirVolume(22.0, r.w, 101325.0))
    assert psychro.dew_point_from_rh(22.0, 0.45) == pytest.approx(r.tdp_c, abs=2e-3)
    assert psychro.wet_bulb_from_rh(22.0, 0.45, 101325.0) == pytest.approx(r.twb_c, abs=2e-3)
    assert psychro.sat_vap_pres(25.0) == pytest.approx(3169.9, abs=1.0)
    with pytest.raises(ValueError):
        psychro.state_tdb_tdp(20.0, 21.0, P_SG)


# ---------------------------------------------------------------- MAU and recirculation loads
def _independent_mau(oa_t, oa_w, coil_t, coil_w, q):
    v = psy.GetMoistAirVolume(coil_t, coil_w, P_SG)
    m = q / v
    total = m * (psy.GetMoistAirEnthalpy(oa_t, oa_w) - psy.GetMoistAirEnthalpy(coil_t, coil_w)) / 1000
    return m, total


def test_mau_load_against_independent_calc():
    oa = psychro.state_tdb_twb(33.2, 26.3, P_SG)
    r = loads.mau_coil_load(oa, 11.0, 0.0078, 17.5, 2.0)
    m, total = _independent_mau(33.2, oa.w, 11.0, 0.0078, 2.0)
    assert r.m_da_kg_s == pytest.approx(m, rel=1e-12)
    assert r.total_kw == pytest.approx(total, rel=1e-12)
    assert r.sensible_kw + r.latent_kw == pytest.approx(r.total_kw, rel=1e-12)
    assert r.total_rt == pytest.approx(r.total_kw / RT_TO_KW)
    # latent part: m * W-change * (2501 + 1.86*T_out) kJ/kg in the ASHRAE enthalpy equation
    assert r.latent_kw == pytest.approx(m * (oa.w - 0.0078) * (2501 + 1.86 * 33.2), rel=1e-9)
    assert r.reheat_kw == pytest.approx(m * (17.5 - 11.0) * (1.006 + 1.86 * 0.0078), rel=1e-9)
    assert r.latent_kw > r.sensible_kw * 0.5  # Singapore air: latent is a large share


def test_mau_sensible_only_when_no_dehumidification():
    oa = psychro.state_tdb_rh(30.0, 0.30, P_SG)
    r = loads.mau_coil_load(oa, 20.0, oa.w, 20.0, 1.0)
    assert r.latent_kw == pytest.approx(0.0, abs=1e-12)
    assert r.reheat_kw == 0.0
    assert r.sensible_kw > 0


def test_mau_rejects_impossible_states():
    oa = psychro.state_tdb_twb(33.2, 26.3, P_SG)
    with pytest.raises(ValueError):
        loads.mau_coil_load(oa, 12.0, oa.w + 0.001, 18.0, 1.0)   # humidifying
    with pytest.raises(ValueError):
        loads.mau_coil_load(oa, 10.0, 0.0100, 18.0, 1.0)         # supersaturated at 10 degC
    with pytest.raises(ValueError):
        loads.mau_coil_load(oa, 34.0, 0.0100, 18.0, 1.0)         # warmer than outdoor


def test_required_supply_hum_ratio():
    w_room = psy.GetHumRatioFromRelHum(22.0, 0.45, P_SG)
    assert loads.required_supply_hum_ratio(22.0, 0.45, P_SG, 0.0003, 2.5) == pytest.approx(w_room - 0.00012)
    with pytest.raises(ValueError):
        loads.required_supply_hum_ratio(22.0, 0.45, P_SG, 0.0003, 0.0)


def test_coil_leaving_state_is_a_fixed_point():
    st = loads.mau_coil_leaving_state(22.0, 0.45, P_SG, 0.0002, 3.0, 1.0)
    m = 3.0 / psy.GetMoistAirVolume(st["tdb_c"], st["w"], P_SG)
    assert st["w"] == pytest.approx(st["w_room"] - 0.0002 / m, rel=1e-10)
    assert st["tdb_c"] - st["tdp_c"] == pytest.approx(1.0)
    assert st["tdp_c"] == pytest.approx(psy.GetTDewPointFromHumRatio(22.0, st["w"], P_SG), abs=1e-9)
    with pytest.raises(ValueError):
        loads.mau_coil_leaving_state(22.0, 0.45, P_SG, 0.1, 0.5, 1.0)
    with pytest.raises(ValueError):
        loads.mau_coil_leaving_state(22.0, 0.45, P_SG, 0.0002, 3.0, -0.5)


def test_recirculation_load():
    w = 0.0073
    r = loads.recirculation_sensible_load_kw(150.0, 834, 150.0, 15.0, 600.0, 3.6, 18.0, w, 22.0)
    assert r["ffu_fan_kw"] == pytest.approx(125.1)
    assert r["lighting_kw"] == pytest.approx(9.0)
    credit = 3.6 * (22.0 - 18.0) * (1.006 + 1.86 * w)
    assert r["mau_supply_credit_kw"] == pytest.approx(credit, rel=1e-9)
    assert r["dcc_kw"] == pytest.approx(284.1 - credit)
    assert r["dcc_rt"] == pytest.approx(r["dcc_kw"] / RT_TO_KW)
    with pytest.raises(ValueError):
        loads.recirculation_sensible_load_kw(-1.0, 1, 1.0, 1.0, 1.0, 1.0, 18.0, w, 22.0)
    assert math.isfinite(r["internal_sensible_kw"])
