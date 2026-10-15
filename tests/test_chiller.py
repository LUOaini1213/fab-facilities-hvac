import numpy as np
import pytest

from fabhvac import chiller as ch
from fabhvac.units import RT_TO_KW

# NEA web table, kWe/kWc with the kW/RT shown in brackets (retrieved 2026-10-02)
NEA_GENERAL = {3: (0.203, 0.71), 4: (0.200, 0.70), 5: (0.197, 0.69), 6: (0.194, 0.68),
               7: (0.191, 0.67), 8: (0.188, 0.66), 9: (0.185, 0.65)}
NEA_SPACE = {3: (0.191, 0.67), 4: (0.188, 0.66), 5: (0.185, 0.65), 6: (0.182, 0.64), 7: (0.179, 0.63)}


@pytest.mark.parametrize("t,pair", list(NEA_GENERAL.items()))
def test_mees_general_table_and_bracketed_kw_per_rt(t, pair):
    kwe, kwrt = pair
    assert ch.mees_limit_kwe_per_kwc(t) == kwe
    assert round(ch.kwe_per_kwc_to_kw_per_rt(kwe), 2) == kwrt


@pytest.mark.parametrize("t,pair", list(NEA_SPACE.items()))
def test_mees_space_cooling_table(t, pair):
    kwe, kwrt = pair
    assert ch.mees_limit_kwe_per_kwc(t, space_cooling_new_building=True) == kwe
    assert round(ch.kwe_per_kwc_to_kw_per_rt(kwe), 2) == kwrt


@pytest.mark.parametrize("t,expected", [(6.0, 0.194), (6.01, 0.191), (3.2, 0.200), (9.4, 0.182),
                                        (10.0, 0.182), (11.0, 0.179), (12.7, 0.173), (3.0, 0.203)])
def test_mees_rounding_up_and_progressive_rule(t, expected):
    assert ch.mees_limit_kwe_per_kwc(t) == pytest.approx(expected, abs=1e-12)


@pytest.mark.parametrize("t,expected", [(6.2, 0.179), (4.5, 0.185), (11.0, 0.179), (3.0, 0.191)])
def test_mees_space_cooling_rounding(t, expected):
    assert ch.mees_limit_kwe_per_kwc(t, True) == expected


def test_mees_float_noise_does_not_round_up():
    assert ch.mees_rounded_chws(7.0 + 1e-12) == 7
    assert ch.mees_rounded_chws(7.000001) == 8


def test_mees_below_scope_raises():
    with pytest.raises(ValueError):
        ch.mees_limit_kwe_per_kwc(2.9)


def test_mees_check_verdicts_and_scope_boundaries():
    assert ch.mees_check(0.18875, 6.5, 7000.0)["verdict"] == "PASS"
    r = ch.mees_check(0.193, 6.5, 7000.0)
    assert r["verdict"] == "FAIL" and r["margin_kwe_per_kwc"] == pytest.approx(-0.002)
    assert ch.mees_check(0.193, 5.2, 7000.0)["verdict"] == "PASS"     # 6 degC limit 0.194
    assert ch.mees_check(0.191, 7.0, 7000.0)["verdict"] == "PASS"      # equal to limit passes
    assert ch.mees_check(0.25, 6.5, 1054.9)["verdict"] == "OUT_OF_SCOPE"
    assert ch.mees_check(0.25, 6.5, 1055.0)["verdict"] == "FAIL"
    assert ch.mees_check(0.181, 6.5, 2000.0, True)["verdict"] == "FAIL"  # space-cooling 0.179
    assert ch.mees_check(0.2, 2.5, 9000.0)["verdict"] == "OUT_OF_SCOPE"
    assert not ch.mees_in_scope(5000.0, 6.0, brine_or_glycol_only=True)


def test_conversions():
    assert ch.kw_per_rt_to_kwe_per_kwc(0.68) == pytest.approx(0.68 / 3.516853)
    assert ch.kwe_per_kwc_to_kw_per_rt(ch.kw_per_rt_to_kwe_per_kwc(0.913)) == pytest.approx(0.913)
    assert ch.cop_from_kwe_per_kwc(0.18875) == pytest.approx(5.298013245)
    with pytest.raises(ValueError):
        ch.cop_from_kwe_per_kwc(0.0)
    assert RT_TO_KW == 3.516853


def test_plant_efficiency():
    assert ch.plant_efficiency_kwe_per_kwc(4000, 560, 70, 80, 45) == pytest.approx(755 / 4000)
    assert ch.plant_efficiency_kwe_per_kwc(1234.5, 201.0, 17.3, 22.9, 8.4) == pytest.approx(249.6 / 1234.5)
    with pytest.raises(ValueError):
        ch.plant_efficiency_kwe_per_kwc(0.0, 1.0)
    with pytest.raises(ValueError):
        ch.plant_efficiency_kwe_per_kwc(100.0, 10.0, -1.0)


def test_heat_balance_pct_sign_and_value():
    assert ch.heat_balance_pct(1000.0, 180.0, 1150.0) == pytest.approx(30 / 1150 * 100)
    assert ch.heat_balance_pct(812.3, 160.4, 1003.9) == pytest.approx((812.3 + 160.4 - 1003.9) / 1003.9 * 100)
    assert ch.heat_balance_pct(800.0, 150.0, 1000.0) == pytest.approx(-5.0)


def test_heat_balance_test_80_percent_rule():
    q_c = np.full(10, 1000.0)
    w = np.full(10, 200.0)
    # heat balance values: 8 within +/-5 %, 2 outside -> exactly 80 % -> pass
    hb = np.array([0.0, 1.0, -2.0, 4.9, -4.9, 5.0, -5.0, 3.0, 6.0, -7.5])
    q_e = q_c * (1 + hb / 100) - w
    r = ch.heat_balance_test(q_e, w, q_c)
    assert r["fraction_within"] == pytest.approx(0.8) and r["passes"]
    hb2 = hb.copy()
    hb2[0] = 5.01
    r2 = ch.heat_balance_test(q_c * (1 + hb2 / 100) - w, w, q_c)
    assert r2["fraction_within"] == pytest.approx(0.7) and not r2["passes"]
    assert r["n_points"] == 10


def test_heat_balance_test_ignores_nonfinite_and_rejects_empty():
    r = ch.heat_balance_test([1000.0, np.nan, 800.0], [200.0, 200.0, 200.0], [1200.0, 1000.0, 0.0])
    assert r["n_points"] == 1 and r["passes"]
    with pytest.raises(ValueError):
        ch.heat_balance_test([np.nan], [1.0], [1.0])


def test_water_heat_rates_use_nea_cp():
    assert float(ch.cooling_load_kw(50.0, 12.5, 7.0)) == pytest.approx(50 * 4.19 * 5.5)
    assert float(ch.heat_rejection_kw(60.0, 35.5, 30.0)) == pytest.approx(60 * 4.18 * 5.5)


def test_compressor_work_input():
    assert float(ch.compressor_work_input_kw(200.0, vsd_eff=0.97)) == pytest.approx(194.0)
    assert float(ch.compressor_work_input_kw(200.0, vsd_eff=0.97, motor_eff=0.95)) == pytest.approx(184.3)
    with pytest.raises(ValueError):
        ch.compressor_work_input_kw(200.0, vsd_eff=1.2)


def test_mv_uncertainty():
    u = ch.mv_system_uncertainty_pct(0.03, 0.07, 3.1, 0.8, 1.5)
    d_ut = (0.03 ** 2 + 0.07 ** 2) ** 0.5 / 3.1 * 100
    assert u == pytest.approx((d_ut ** 2 + 0.8 ** 2 + 1.5 ** 2) ** 0.5)
    dt_min = ch.min_chw_delta_t_for_uncertainty()
    assert dt_min == pytest.approx(1.58113883, rel=1e-8)
    assert ch.mv_system_uncertainty_pct(0.05, 0.05, dt_min, 1.0, 2.0) == pytest.approx(5.0)
    assert ch.min_chw_delta_t_for_uncertainty(u_flow_pct=4.0, u_power_pct=3.0) is None
    with pytest.raises(ValueError):
        ch.mv_system_uncertainty_pct(0.05, 0.05, 0.0, 1.0, 2.0)
