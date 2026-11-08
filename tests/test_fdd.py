"""FDD unit tests on synthetic data (no raw LBNL data needed) plus optional data checks."""

import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("sklearn")

from fabhvac.fdd import data as fd  # noqa: E402
from fabhvac.fdd import models as fm  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- scenario parsing
@pytest.mark.parametrize("name,ft,sev,val", [
    ("ChillerPlant.csv", "normal", "", None),
    ("ChillerPlant_chiller_bias_-2.csv", "chiller_bias", "-2", -2.0),
    ("ChillerPlant_coolingtower_bias_1.csv", "coolingtower_bias", "1", 1.0),
    ("ChillerPlant_secondary_chilled_water_pressure_bias_-010.csv", "secondary_chilled_water_pressure_bias", "-010", -10.0),
    ("ChillerPlant_bypass_leakage_075.csv", "bypass_leakage", "075", 75.0),
    ("ChillerPlant_bypass_stuck_050.csv", "bypass_stuck", "050", 50.0),
    ("ChillerPlant_coolingtower_fouling_065.csv", "coolingtower_fouling", "065", 65.0),
    ("ChillerPlant_chiller_fouling_095.csv", "chiller_fouling", "095", 95.0),
    ("ChillerPlant_coolingtower_PI.csv", "coolingtower_PI", "PI", None),
])
def test_parse_scenario(name, ft, sev, val):
    s = fd.parse_scenario(name)
    assert (s.fault_type, s.severity) == (ft, sev)
    if val is None:
        assert np.isnan(s.severity_value)
    else:
        assert s.severity_value == val


@pytest.mark.parametrize("bad", ["Other.csv", "ChillerPlant_unknown_1.csv", "ChillerPlant_chiller_bias_x.csv"])
def test_parse_scenario_rejects(bad):
    with pytest.raises(ValueError):
        fd.parse_scenario(bad)


def test_undocumented_fault_is_flagged():
    assert "chiller_fouling" in fd.UNDOCUMENTED_FAULTS and "chiller_fouling" not in fd.DOCUMENTED_FAULTS


# ---------------------------------------------------------------- derived signals
def _row(**over):
    base = {c: 0.0 for c in ["CWL_SEC_LOAD", "CWL_PRI_SW_TEMPSPT", "CT_SW_TEMPSPT", "CWL_PRI_SW_TEMP",
                              "CT_SW_TEMP_1", "CT_RW_TEMP_1", "CDWL_SW_TEMP", "CWL_SEC_DP", "TWV_CTRL",
                              "CT_FAN_SPD_1", "CWL_SEC_PM_SPD_1", "CWL_SEC_PM_POW_1", "CWL_SEC_PM_POW_2",
                              "CHL_COMP_SPD_CTRL_1"]}
    base.update({"OA_TEMP": 68.0, "OA_TEMP_WB": 86.0, "CWL_SEC_DPSPT": 960.0, "CWL_SEC_DP": 912.0,
                 "CWL_SEC_LOAD": 500000.0, "CWL_PRI_SW_TEMPSPT": 44.6, "CWL_PRI_SW_TEMP": 46.4,
                 "CT_SW_TEMPSPT": 76.0, "CT_SW_TEMP_1": 77.8, "CT_RW_TEMP_1": 87.7, "CDWL_SW_TEMP": 78.7})
    for i in (1, 2, 3):
        base.update({f"CHL_STA_{i}": 1.0 if i == 1 else 0.0, f"CHL_CW_FLOW_{i}": 300.0 if i == 1 else 0.0,
                     f"CHL_CD_FLOW_{i}": 350.0 if i == 1 else 0.0, f"CHL_RW_TEMP_{i}": 55.0, f"CHL_SW_TEMP_{i}": 45.1,
                     f"CHL_SWCD_TEMP_{i}": 92.0, f"CHL_RWCD_TEMP_{i}": 83.0, f"CHL_POW_{i}": 100.0 if i == 1 else 0.0,
                     f"CWL_PRI_PM_POW_{i}": 10.0 if i == 1 else 0.0, f"CDWL_PM_POW_{i}": 20.0 if i == 1 else 0.0,
                     f"CT_POW_{i}": 3.0 if i == 1 else 0.0})
    base.update(over)
    return pd.DataFrame([base])


def test_derive_signals_hand_values():
    d = fd.derive_signals(_row(CWL_SEC_PM_POW_1=15.0)).iloc[0]
    kg = 300.0 * 6.309020e-5 * 1000
    assert d["q_evap_1_kw"] == pytest.approx(kg * 4.19 * (55.0 - 45.1) / 1.8)
    kg_c = 350.0 * 6.309020e-5 * 1000
    assert d["q_cond_kw"] == pytest.approx(kg_c * 4.18 * 9.0 / 1.8)
    assert d["plant_kw"] == pytest.approx(100 + 10 + 15 + 20 + 3)
    assert d["plant_kw_per_rt"] == pytest.approx(148 / (d["q_evap_kw"] / 3.516853))
    assert d["heat_balance_pct"] == pytest.approx((d["q_evap_kw"] + 100 - d["q_cond_kw"]) / d["q_cond_kw"] * 100)
    # outdoor columns are swapped in the data set: OA_TEMP is the wet bulb
    assert d["t_wb_c"] == pytest.approx(20.0) and d["t_db_c"] == pytest.approx(30.0)
    assert d["ct1_approach_k"] == pytest.approx((77.8 - 32) / 1.8 - 20.0)
    assert d["ct1_range_k"] == pytest.approx(5.5)
    assert d["ct1_minus_spt_k"] == pytest.approx(1.0)
    assert d["chw_supply_err_k"] == pytest.approx(1.0)
    assert d["sec_dp_err_pct"] == pytest.approx(-5.0)
    assert d["sec_load_kw"] == pytest.approx(500.0)
    assert d["n_chillers_on"] == 1
    assert d["chiller1_cop"] == pytest.approx(d["q_evap_1_kw"] / 100.0)
    assert d["chl1_lift_k"] == pytest.approx((92.0 - 45.1) / 1.8)
    assert d["cdw_supply_minus_ct1_k"] == pytest.approx(0.5)
    assert d["chl1_sw_minus_pri_sw_k"] == pytest.approx((45.1 - 46.4) / 1.8)


def test_window_aggregate_and_heat_balance_fraction():
    rows = pd.concat([_row(CHL_POW_1=1.0 + 0.5 * k, CT_FAN_SPD_1=k / 200) for k in range(120)], ignore_index=True)
    rows.insert(0, "Datetime", pd.date_range("2018-03-01 01:00", periods=120, freq="1min"))
    agg = fd.window_aggregate(rows, "1h")
    assert len(agg) == 2 and list(agg["n_minutes"]) == [60, 60]
    assert agg["CHL_POW_1"].iloc[0] == pytest.approx(1.0 + 0.5 * 29.5)
    assert agg["CT_FAN_SPD_1__std"].iloc[1] == pytest.approx(np.std(np.arange(60, 120) / 200))
    hb = fd.heat_balance_fraction(rows)
    d = fd.derive_signals(rows)
    assert hb["n_points"] == 120
    assert hb["fraction_within"] == pytest.approx(np.mean(np.abs(d["heat_balance_pct"]) <= 5.0))
    assert 0.0 < hb["fraction_within"] < 1.0
    # tolerance boundary is inclusive: use an observed |hb| value as the tolerance
    v = float(np.abs(d["heat_balance_pct"]).iloc[50])
    hb_edge = fd.heat_balance_fraction(rows, tol_pct=v)
    assert hb_edge["fraction_within"] == pytest.approx(np.mean(np.abs(d["heat_balance_pct"]) <= v))
    assert hb_edge["fraction_within"] > np.mean(np.abs(d["heat_balance_pct"]) < v)


def test_heat_balance_fraction_agrees_with_the_nea_heat_balance_test():
    """heat_balance_fraction re-implements the +/-5 % fraction for 1-minute rows without
    heat_balance_test's input guards (which raise on any negative heat rate); on physical,
    non-negative operating points the two must give the same numbers."""
    from fabhvac import chiller
    rows = pd.concat([_row(CHL_POW_1=1.0 + 0.004 * k ** 2) for k in range(120)], ignore_index=True)
    rows.insert(0, "Datetime", pd.date_range("2018-03-01 01:00", periods=120, freq="1min"))
    d = fd.derive_signals(rows)
    op = (d["q_cond_kw"] > 1.0) & (d["chiller_kw"] > 0)
    assert op.all() and (d.loc[op, "q_evap_kw"] >= 0).all()
    ref = chiller.heat_balance_test(d.loc[op, "q_evap_kw"].to_numpy(), d.loc[op, "chiller_kw"].to_numpy(),
                                    d.loc[op, "q_cond_kw"].to_numpy(), tol_pct=5.0)
    hb = fd.heat_balance_fraction(rows, tol_pct=5.0)
    assert hb["n_points"] == ref["n_points"]
    assert hb["fraction_within"] == pytest.approx(ref["fraction_within"], abs=0)
    assert hb["median_pct"] == pytest.approx(ref["median_pct"], rel=1e-12)
    assert 0 < hb["fraction_within"] < 1  # rows on both sides of the +/-5 % band


# ---------------------------------------------------------------- splits and metrics
def test_month_split_buffer_and_disjoint():
    idx = pd.date_range("2018-01-01 01:00", "2018-12-31 23:00", freq="1h")
    tr, te = fm.month_split(idx, buffer_hours=24)
    assert not np.any(tr & te)
    assert set(idx[tr].month) == {1, 3, 5, 7, 9, 11}
    assert set(idx[te].month) == {2, 4, 6, 8, 10, 12}
    t = idx[te]
    assert not np.any((t.day == 1)) and not np.any(t.day == t.days_in_month)
    assert te.sum() == sum(((pd.Timestamp(2018, m, 1).days_in_month - 2) * 24) for m in (2, 4, 6, 8, 10, 12))


@pytest.mark.parametrize("first,train_months,n_test_days,first_test,last_test", [
    (True, {1, 2, 3, 4, 5, 6}, 184 - 2, "2018-07-02 00:00", "2018-12-30 23:00"),
    (False, {7, 8, 9, 10, 11, 12}, 181 - 2, "2018-01-02 00:00", "2018-06-29 23:00"),
])
def test_season_split_blocks_and_buffer(first, train_months, n_test_days, first_test, last_test):
    idx = pd.date_range("2018-01-01 00:00", "2018-12-31 23:00", freq="1h")
    tr, te = fm.season_split(idx, train_first_half=first, buffer_hours=24)
    assert not np.any(tr & te)
    assert set(idx[tr].month) == train_months
    assert set(idx[te].month).isdisjoint(train_months)
    assert te.sum() == n_test_days * 24
    assert idx[te][0] == pd.Timestamp(first_test) and idx[te][-1] == pd.Timestamp(last_test)
    _, te0 = fm.season_split(idx, train_first_half=first, buffer_hours=0)
    assert te0.sum() == (n_test_days + 2) * 24


def test_two_stage_labels():
    classes = np.array(["f1", "normal", "f2"], dtype=object)
    proba = np.array([[0.10, 0.85, 0.05],     # score 0.15
                      [0.30, 0.20, 0.50],     # score 0.80 -> f2
                      [0.60, 0.30, 0.10],     # score 0.70 -> f1
                      [0.25, 0.45, 0.30]])    # score 0.55: normal is the argmax, but a fault is reported
    assert fm.two_stage_labels(proba, classes, 0.5).tolist() == ["normal", "f2", "f1", "f2"]
    assert fm.two_stage_labels(proba, classes, 0.75).tolist() == ["normal", "f2", "normal", "normal"]
    assert fm.two_stage_labels(proba, classes, 0.8).tolist() == ["normal"] * 4     # strictly above alarms


def test_diagnosis_metrics_hand_values():
    y = ["normal", "normal", "normal", "f1", "f1", "f2"]
    p = ["normal", "f1", "normal", "f1", "normal", "f1"]
    m = fm.diagnosis_metrics(y, p, ["normal", "f1", "f2"])
    assert m["accuracy_9class"] == pytest.approx(3 / 6)
    assert m["normal_recall"] == pytest.approx(2 / 3)
    assert m["fault_windows_correct_type"] == pytest.approx(1 / 3)
    assert m["macro_f1_9class"] == pytest.approx(fm.macro_f1(fm.confusion(y, p, ["normal", "f1", "f2"])))


def test_daily_max_any_hour_rule():
    idx = pd.date_range("2018-03-01 00:00", periods=48, freq="1h")
    s = np.zeros(48)
    s[5] = 0.9
    s[30] = 0.4
    d = fm.daily_max(s, idx)
    assert d.index.tolist() == [pd.Timestamp("2018-03-01"), pd.Timestamp("2018-03-02")]
    assert d.tolist() == [0.9, 0.4]
    assert (d > 0.5).tolist() == [True, False]


def test_threshold_at_far_exact():
    s = np.arange(1000, dtype=float)
    t = fm.threshold_at_far(s, 0.01)
    assert fm.alarm_rate(s, t) == pytest.approx(0.01)
    assert fm.threshold_at_far(s, 0.0) == 999.0
    rng = np.random.default_rng(3)
    s2 = rng.normal(size=777)
    assert fm.alarm_rate(s2, fm.threshold_at_far(s2, 0.05)) <= 0.05
    assert fm.alarm_rate(s2, fm.threshold_at_far(s2, 0.05)) > 0.04


def test_confusion_and_macro_f1():
    cm = fm.confusion(["a", "a", "b", "b", "b", "c"], ["a", "b", "b", "b", "c", "c"], ["a", "b", "c"])
    assert cm.tolist() == [[1, 1, 0], [0, 2, 1], [0, 0, 1]]
    f1a, f1b, f1c = 2 / 3, 2 * (2 / 3) * (2 / 3) / (4 / 3), 2 * 0.5 * 1 / 1.5
    assert fm.macro_f1(cm) == pytest.approx((f1a + f1b + f1c) / 3)


def test_feature_columns_exclude_labels():
    df = pd.DataFrame({"a": [1.0], "file": ["x"], "fault_type": ["n"], "n_minutes": [60], "month": [1], "b": [2]})
    assert fm.feature_columns(df) == ["a", "b"]


# ---------------------------------------------------------------- baseline on synthetic plant
def _synthetic(n, rng, shift=None):
    t_db = rng.uniform(15, 35, n)
    t_wb = t_db - rng.uniform(3, 8, n)
    load = rng.uniform(100, 1200, n)
    df = pd.DataFrame({"t_db_c": t_db, "t_wb_c": t_wb, "sec_load_kw": load,
                       "chw_spt_c": rng.uniform(6, 11, n), "n_chillers_on": rng.integers(1, 4, n).astype(float)})
    df["y1"] = 50 + 0.3 * load + 2.0 * t_wb + rng.normal(0, 3, n)
    df["y2"] = 4.0 + 0.1 * (t_db - t_wb) + rng.normal(0, 0.2, n)
    if shift:
        for k, v in shift.items():
            df[k] += v
    return df


def test_residual_baseline_detects_and_diagnoses():
    rng = np.random.default_rng(0)
    normal = _synthetic(2400, rng)
    groups = np.repeat(np.arange(6), 400)
    b = fm.ResidualBaseline(targets=["y1", "y2"]).fit(normal, groups, quantile=0.99)
    test_normal = _synthetic(2000, rng)
    far = np.mean(b.statistic(test_normal) > b.threshold_)
    assert 0.002 < far < 0.03          # close to the 1 % design point
    f1 = _synthetic(500, rng, {"y1": 25.0})     # ~8 sigma on y1
    f2 = _synthetic(500, rng, {"y2": -1.5})     # ~7.5 sigma on y2 (other direction)
    assert np.mean(b.statistic(f1) > b.threshold_) > 0.95
    assert np.mean(b.statistic(f2) > b.threshold_) > 0.95
    z = np.vstack([b.zscores(normal[:500]), b.zscores(f1), b.zscores(f2)])
    lab = np.array(["normal"] * 500 + ["f1"] * 500 + ["f2"] * 500)
    b.fit_signatures(z, lab)
    zt = np.vstack([b.zscores(_synthetic(300, rng, {"y1": 25.0})), b.zscores(_synthetic(300, rng, {"y2": -1.5}))])
    pred = b.diagnose(zt)
    assert np.mean(pred[:300] == "f1") > 0.95 and np.mean(pred[300:] == "f2") > 0.95
    # two-stage rule: normal below the threshold, otherwise nearest fault signature
    zn = b.zscores(_synthetic(1000, rng))
    p2 = b.diagnose(np.vstack([zn, zt]), threshold=b.threshold_)
    assert 0.95 < np.mean(p2[:1000] == "normal") < 1.0
    assert np.mean(p2[1000:1300] == "f1") > 0.95 and np.mean(p2[1300:] == "f2") > 0.95
    assert "normal" not in set(b.diagnose(zt, threshold=-1.0))
    # signatures from alarming windows only: a fault class diluted by invisible windows
    zd = np.vstack([b.zscores(normal[:500]), b.zscores(f1),
                    b.zscores(_synthetic(1500, rng)), b.zscores(f2)])        # f2 mostly invisible
    lab2 = np.array(["normal"] * 500 + ["f1"] * 500 + ["f2"] * 2000)
    b.fit_signatures(zd, lab2, threshold=b.threshold_)
    sig_f2 = b.signatures_[list(b.classes_).index("f2")]
    assert sig_f2[1] < -2.0                       # y2 shift visible in the signature
    b.fit_signatures(zd, lab2)
    assert abs(b.signatures_[list(b.classes_).index("f2")][1]) < 1.0   # diluted without threshold


def test_baseline_scale_uses_out_of_fold_residuals():
    rng = np.random.default_rng(1)
    normal = _synthetic(1200, rng)
    groups = np.repeat(np.arange(4), 300)
    b = fm.ResidualBaseline(targets=["y1"]).fit(normal, groups)
    # default "tail" scale: 99th percentile of |N(0, 3)| = 2.576 * 3
    assert b.scale_[0] == pytest.approx(2.576 * 3.0, rel=0.15)
    m = fm.ResidualBaseline(targets=["y1"], scale="mad").fit(normal, groups)
    assert m.scale_[0] == pytest.approx(3.0, rel=0.15)     # MAD * 1.4826 estimates the sd
    with pytest.raises(ValueError):
        fm.ResidualBaseline(scale="iqr")


# ---------------------------------------------------------------- optional: real-data cache
CACHE = os.environ.get("LBNL_FDD_CACHE")


@pytest.mark.skipif(not CACHE or not Path(CACHE).exists(), reason="LBNL hourly cache not available")
def test_cache_consistent_with_committed_scenario_table():
    sc = pd.read_csv(ROOT / "results" / "fdd_scenarios.csv").set_index("file")
    h = pd.read_parquet(Path(CACHE) / "ChillerPlant.parquet")
    kwh = float((h["plant_kw"] * h["n_minutes"] / 60).sum())
    assert kwh == pytest.approx(sc.loc["ChillerPlant.csv", "plant_kwh"], rel=1e-6)


def test_fault_score_and_classifier_determinism():
    rng = np.random.default_rng(5)
    x = np.vstack([rng.normal(0, 1, (300, 3)), rng.normal(3, 1, (300, 3))])
    y = np.array(["normal"] * 300 + ["f1"] * 300)
    c1 = fm.make_classifier().fit(x, y)
    c2 = fm.make_classifier().fit(x, y)
    s = fm.fault_score(c1, x)
    assert np.array_equal(s, fm.fault_score(c2, x))
    assert s[:300].mean() < 0.2 and s[300:].mean() > 0.8
    p_normal = c1.predict_proba(x)[:, list(c1.classes_).index("normal")]
    assert s == pytest.approx(1 - p_normal)
