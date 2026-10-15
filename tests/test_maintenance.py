"""Part D unit tests: work-order model, reliability metrics, Weibull/PM, text classification,
condition indicator, LLM wrapper (no network), AMPS mapping. No external data needed."""

import math

import numpy as np
import pandas as pd
import pytest

from fabhvac.maintenance import reliability as rel
from fabhvac.maintenance import weibull as wb
from fabhvac.maintenance import workorder as wo

T = pd.Timestamp


# ================================================================ Weibull
def _sample(seed=11, n=57, beta=2.3, eta=800.0, cens=900.0):
    rng = np.random.default_rng(seed)
    life = eta * (-np.log(rng.random(n))) ** (1 / beta)
    return np.minimum(life, cens), life <= cens


def test_weibull_mle_matches_scipy_censored_fit():
    stats = pytest.importorskip("scipy.stats")
    t, d = _sample()
    assert 0 < (~d).sum() < d.sum()                    # really censored data
    f = wb.fit_weibull(t, d)
    c, _, s = stats.weibull_min.fit(stats.CensoredData(uncensored=t[d], right=t[~d]), floc=0)
    assert f.beta == pytest.approx(c, rel=2e-5)
    assert f.eta == pytest.approx(s, rel=2e-5)
    assert (f.n, f.failures) == (57, int(d.sum()))


def test_cluster_bootstrap_resamples_whole_clusters():
    rng = np.random.default_rng(4)
    # 30 assets; each asset's intervals share an asset-specific scale (frailty), so intervals
    # within an asset are correlated and the naive Wald CI is too narrow
    t, d, c = [], [], []
    for a in range(30):
        scale = 300.0 * math.exp(rng.normal(0, 1.0))
        k = int(rng.integers(2, 12))
        life = scale * (-np.log(rng.random(k))) ** (1 / 1.5)
        t.extend(life)
        d.extend([True] * (k - 1) + [False])
        c.extend([a] * k)
    t, d, c = np.array(t), np.array(d), np.array(c)
    fit = wb.fit_weibull(t, d)
    b = wb.cluster_bootstrap(t, d, c, n_boot=400, seed=1)
    assert b["clusters"] == 30 and b["unfitted_resamples"] == 0
    assert b["beta_ci"][0] < fit.beta < b["beta_ci"][1]
    assert b["eta_ci"][0] < fit.eta < b["eta_ci"][1]
    # clustering widens the interval relative to the i.i.d. Wald interval
    assert (b["beta_ci"][1] - b["beta_ci"][0]) > (fit.beta_ci95[1] - fit.beta_ci95[0])
    assert wb.cluster_bootstrap(t, d, c, n_boot=50, seed=3) == wb.cluster_bootstrap(t, d, c, n_boot=50, seed=3)
    # one interval per cluster: the cluster bootstrap is the ordinary bootstrap; check the
    # resampling unit by giving every interval of an asset an identical copy -- duplicating
    # whole clusters must not narrow the interval the way duplicating rows would
    dup = wb.cluster_bootstrap(np.concatenate([t, t]), np.concatenate([d, d]), np.concatenate([c, c]), n_boot=400, seed=1)
    w0, w1 = b["beta_ci"][1] - b["beta_ci"][0], dup["beta_ci"][1] - dup["beta_ci"][0]
    assert w1 == pytest.approx(w0, rel=0.25)
    # percentile interval re-computed by hand from the same resamples (seed 3, 40 resamples)
    rng = np.random.default_rng(3)
    ids = np.unique(c)
    bs = []
    for _ in range(40):
        pick = rng.integers(0, ids.size, ids.size)
        idx = np.concatenate([np.flatnonzero(c == ids[k]) for k in pick])
        bs.append(wb.fit_weibull(t[idx], d[idx]).beta)
    ref = wb.cluster_bootstrap(t, d, c, n_boot=40, seed=3, level=0.9)
    assert ref["beta_ci"] == pytest.approx(list(np.quantile(bs, [0.05, 0.95])), rel=1e-12)
    with pytest.raises(ValueError):
        wb.cluster_bootstrap(t, d, c[:-1])


def test_weibull_mle_is_a_stationary_point_and_se_from_numerical_hessian():
    t, d = _sample(seed=4, n=43, beta=1.6, eta=1200.0, cens=1000.0)
    f = wb.fit_weibull(t, d)
    h = 1e-5
    lb = lambda b, e: wb.loglik(b, e, t, d)  # noqa: E731
    gb = (lb(f.beta * (1 + h), f.eta) - lb(f.beta * (1 - h), f.eta)) / (2 * h * f.beta)
    ge = (lb(f.beta, f.eta * (1 + h)) - lb(f.beta, f.eta * (1 - h))) / (2 * h * f.eta)
    assert abs(gb) < 1e-4 and abs(ge) < 1e-6
    # observed information by finite differences in (beta, eta)
    hb, he = 1e-4 * f.beta, 1e-4 * f.eta

    def H(i, j):
        def ll(db, de):
            return lb(f.beta + db, f.eta + de)
        if i == j == 0:
            return (ll(hb, 0) - 2 * ll(0, 0) + ll(-hb, 0)) / hb ** 2
        if i == j == 1:
            return (ll(0, he) - 2 * ll(0, 0) + ll(0, -he)) / he ** 2
        return (ll(hb, he) - ll(hb, -he) - ll(-hb, he) + ll(-hb, -he)) / (4 * hb * he)

    info = -np.array([[H(0, 0), H(0, 1)], [H(1, 0), H(1, 1)]])
    cov = np.linalg.inv(info)
    assert f.se_beta == pytest.approx(math.sqrt(cov[0, 0]), rel=1e-3)
    assert f.se_eta == pytest.approx(math.sqrt(cov[1, 1]), rel=1e-3)
    assert f.beta_ci95[0] < f.beta < f.beta_ci95[1]
    assert f.beta_ci95[1] / f.beta == pytest.approx(f.beta / f.beta_ci95[0], rel=1e-12)  # log-symmetric
    assert f.eta_ci95[0] < f.eta < f.eta_ci95[1]
    # 95 % Wald interval on the log scale: half-width = 1.96 * se / estimate
    z95 = 1.959963985
    assert math.log(f.beta_ci95[1] / f.beta) == pytest.approx(z95 * math.sqrt(cov[0, 0]) / f.beta, rel=1e-3)
    assert math.log(f.eta_ci95[1] / f.eta) == pytest.approx(z95 * math.sqrt(cov[1, 1]) / f.eta, rel=1e-3)


def test_weibull_lr_test_against_chi2():
    stats = pytest.importorskip("scipy.stats")
    t, d = _sample(seed=2, n=40, beta=1.3, eta=500.0, cens=700.0)
    f = wb.fit_weibull(t, d)
    eta1 = wb.fit_weibull_fixed_beta(t, d, 1.0)
    assert f.loglik_exponential == pytest.approx(wb.loglik(1.0, eta1, t, d))
    assert f.lr_stat_beta_eq_1 == pytest.approx(2 * (f.loglik - f.loglik_exponential))
    assert f.p_value_beta_eq_1 == pytest.approx(stats.chi2.sf(f.lr_stat_beta_eq_1, 1), rel=1e-9)


def test_exponential_total_time_on_test():
    t = np.array([120.0, 340.0, 75.5, 600.0, 610.0])
    d = np.array([True, True, True, False, False])
    assert wb.fit_weibull_fixed_beta(t, d, 1.0) == pytest.approx(t.sum() / 3)


def test_censoring_is_neither_dropped_nor_counted_as_failure():
    t, d = _sample(seed=9, n=60, beta=2.0, eta=1000.0, cens=800.0)
    full = wb.fit_weibull(t, d)
    dropped = wb.fit_weibull(t[d], None)
    as_failures = wb.fit_weibull(t, None)
    assert full.eta > as_failures.eta > dropped.eta
    # log-likelihood uses the survival term for censored units
    ll_manual = (np.sum(np.log(full.beta / full.eta) + (full.beta - 1) * np.log(t[d] / full.eta))
                 - np.sum((t / full.eta) ** full.beta))
    assert full.loglik == pytest.approx(ll_manual)


@pytest.mark.parametrize("t,d", [([1.0, 2.0, 3.0], [True, False, False]),
                                 ([0.0, 2.0, 3.0], None), ([-1.0, 2.0, 3.0], None),
                                 ([5.0, 5.0, 9.0], [True, True, False])])
def test_weibull_rejects_bad_input(t, d):
    with pytest.raises(ValueError):
        wb.fit_weibull(np.array(t), d)


def test_life_functions_closed_forms():
    assert wb.reliability(700.0, 2.7, 700.0) == pytest.approx(math.exp(-1))
    assert wb.mean_life(1.0, 640.0) == pytest.approx(640.0)
    assert wb.mean_life(2.0, 640.0) == pytest.approx(640.0 * math.sqrt(math.pi) / 2)
    assert wb.hazard(300.0, 1.0, 640.0) == pytest.approx(1 / 640.0)
    assert wb.hazard(300.0, 2.0, 640.0) == pytest.approx(2 * 300.0 / 640.0 ** 2)
    assert wb.integral_reliability(900.0, 1.0, 640.0) == pytest.approx(640.0 * (1 - math.exp(-900 / 640)), rel=1e-12)
    assert wb.integral_reliability(900.0, 2.0, 640.0) == pytest.approx(
        640.0 * math.sqrt(math.pi) / 2 * math.erf(900 / 640), rel=1e-12)
    assert wb.integral_reliability(0.0, 2.0, 640.0) == 0.0


def test_age_replacement_optimum_against_direct_minimisation():
    opt = pytest.importorskip("scipy.optimize")
    beta, eta, cp, cf = 2.4, 1500.0, 1.0, 7.0
    o = wb.optimal_age_replacement(beta, eta, cp, cf)
    res = opt.minimize_scalar(lambda T: wb.age_replacement_cost_rate(T, beta, eta, cp, cf),
                              bounds=(1.0, 6000.0), method="bounded", options={"xatol": 1e-8})
    assert o["finite_optimum"]
    assert o["t_opt"] == pytest.approx(res.x, rel=1e-5)
    assert o["cost_rate_opt"] == pytest.approx(res.fun, rel=1e-10)
    assert o["cost_rate_run_to_failure"] == pytest.approx(cf / wb.mean_life(beta, eta))
    assert o["saving_vs_run_to_failure"] == pytest.approx(1 - res.fun / o["cost_rate_run_to_failure"], rel=1e-6)
    assert o["prob_failure_before_t_opt"] == pytest.approx(1 - math.exp(-(o["t_opt"] / eta) ** beta))
    # optimality condition, Nakagawa (1981) eq. 2.5
    T = o["t_opt"]
    lhs = wb.hazard(T, beta, eta) * wb.integral_reliability(T, beta, eta) - (1 - wb.reliability(T, beta, eta))
    assert lhs == pytest.approx(cp / (cf - cp), rel=1e-9)
    # cost rate formula by hand at an arbitrary age
    R = math.exp(-(900 / eta) ** beta)
    assert wb.age_replacement_cost_rate(900.0, beta, eta, cp, cf) == pytest.approx(
        (cf * (1 - R) + cp * R) / wb.integral_reliability(900.0, beta, eta))
    # a larger failure/planned cost ratio means replacing earlier
    assert wb.optimal_age_replacement(beta, eta, cp, 20.0)["t_opt"] < T


@pytest.mark.parametrize("beta,cp,cf", [(1.0, 1.0, 10.0), (0.8, 1.0, 10.0), (2.0, 5.0, 5.0), (2.0, 6.0, 5.0)])
def test_age_replacement_no_finite_optimum(beta, cp, cf):
    o = wb.optimal_age_replacement(beta, 1000.0, cp, cf)
    assert not o["finite_optimum"] and o["t_opt"] == math.inf and o["saving_vs_run_to_failure"] == 0.0


def test_age_replacement_rejects_nonpositive_cost():
    with pytest.raises(ValueError):
        wb.optimal_age_replacement(2.0, 1000.0, 0.0, 5.0)


def test_minimal_repair_closed_form():
    opt = pytest.importorskip("scipy.optimize")
    beta, eta, cov, cmr = 2.6, 900.0, 8.0, 1.5
    t = wb.optimal_minimal_repair_interval(beta, eta, cov, cmr)
    res = opt.minimize_scalar(lambda T: wb.minimal_repair_cost_rate(T, beta, eta, cov, cmr),
                              bounds=(10.0, 20000.0), method="bounded", options={"xatol": 1e-6})
    assert t == pytest.approx(res.x, rel=1e-5)
    assert wb.optimal_minimal_repair_interval(1.0, eta, cov, cmr) == math.inf


# ================================================================ work-order model
def _wo(**over):
    base = {"wo_id": "W1", "site": "S1", "system": "B1", "asset_id": "A1", "asset_class": "BOILER",
            "wo_type": "CM", "status": "closed", "failure_mode": "No Heat", "description": "no heat",
            "opened_at": T("2024-01-05 08:00"), "closed_at": T("2024-01-05 20:00"),
            "labor_hours": 3.0, "downtime_hours": 10.0}
    base.update(over)
    return base


def test_validate_flags_each_rule_once():
    rows = [_wo(),                                                         # clean
            _wo(wo_id="W2", site=""),                                      # missing_required
            _wo(wo_id="W3"), _wo(wo_id="W3"),                              # duplicate_id (both)
            _wo(wo_id="W4", wo_type="BREAKDOWN", failure_mode=""),      # unknown_wo_type
            _wo(wo_id="W5", status="done"),                                # unknown_status
            _wo(wo_id="W6", closed_at=pd.NaT, downtime_hours=np.nan),      # closed_without_close_time
            _wo(wo_id="W7", status="open"),                                # close_time_while_open
            _wo(wo_id="W8", closed_at=T("2024-01-05 07:00"), downtime_hours=np.nan),  # closed_before_opened
            _wo(wo_id="W9", labor_hours=-1.0),                             # negative_labor
            _wo(wo_id="W10", downtime_hours=12.5),                         # downtime_exceeds_elapsed
            _wo(wo_id="W11", failure_mode=""),                             # cm_without_failure_mode
            _wo(wo_id="W12", wo_type="PM"),                                # failure_mode_on_non_cm
            _wo(wo_id="W13", failure_mode="Exploded"),                     # unknown_failure_mode
            _wo(wo_id="W14", asset_id="A9")]                               # asset_not_in_hierarchy
    df = pd.DataFrame(rows)
    h = wo.AssetHierarchy({"S1": None, "B1": "S1", "A1": "B1"})
    f = wo.validate(df, failure_modes=["No Heat", "Leaking"], hierarchy=h)
    expect = {"missing_required": ["W2"], "duplicate_id": ["W3", "W3"], "unknown_wo_type": ["W4"],
              "unknown_status": ["W5"], "closed_without_close_time": ["W6"], "close_time_while_open": ["W7"],
              "closed_before_opened": ["W8"], "negative_labor": ["W9"], "downtime_exceeds_elapsed": ["W10"],
              "cm_without_failure_mode": ["W11"], "failure_mode_on_non_cm": ["W12"],
              "unknown_failure_mode": ["W13"], "asset_not_in_hierarchy": ["W14"]}
    for rule, ids in expect.items():
        assert sorted(df.loc[f[rule], "wo_id"]) == ids, rule
    assert not f.iloc[0].any()
    s = wo.validation_summary(f)
    assert s["rows"] == 15 and s["rows_with_any_issue"] == 14 and s["by_rule"]["duplicate_id"] == 2
    # downtime equal to the elapsed time is allowed
    ok = wo.validate(pd.DataFrame([_wo(downtime_hours=12.0)]))
    assert not ok["downtime_exceeds_elapsed"].any()
    with pytest.raises(ValueError):
        wo.validate(df.drop(columns=["downtime_hours"]))


def test_elapsed_hours():
    df = pd.DataFrame([_wo(), _wo(closed_at=pd.NaT)])
    e = wo.elapsed_hours(df)
    assert e.iloc[0] == 12.0 and np.isnan(e.iloc[1])


def test_asset_hierarchy_paths_and_cycles():
    h = wo.AssetHierarchy({"Q": None, "Q015": "Q", "BLG1": "Q015", "BOILER1": "BLG1", "PUMP7": "BLG9"})
    assert h.path("BOILER1") == ["Q", "Q015", "BLG1", "BOILER1"]
    assert h.root("BOILER1") == "Q" and h.ancestor_at("BOILER1", 1) == "Q015"
    assert h.ancestor_at("Q015", 3) is None
    assert h.path("PUMP7") == ["BLG9", "PUMP7"]      # unregistered parent becomes the root
    with pytest.raises(KeyError):
        h.path("nope")
    with pytest.raises(ValueError):
        wo.AssetHierarchy({"a": "b", "b": "a"}).path("a")


def test_empty_frame_has_canonical_columns():
    e = wo.empty_frame()
    assert list(e.columns) == list(wo.COLUMNS) and len(e) == 0


# ================================================================ reliability
def _cm(asset, o, c, mode="No Heat"):
    return {"asset_id": asset, "opened_at": T(o), "closed_at": T(c) if c else pd.NaT, "failure_mode": mode}


def test_failure_episodes_merge_overlaps():
    cm = pd.DataFrame([_cm("A", "2024-01-01 00:00", "2024-01-02 00:00"),
                       _cm("A", "2024-01-01 12:00", "2024-01-03 06:00"),       # overlaps -> merged
                       _cm("A", "2024-01-03 06:00", "2024-01-03 08:00"),       # touches end -> merged
                       _cm("A", "2024-02-01 00:00", "2024-02-01 05:00", "Leaking"),
                       _cm("B", "2024-01-10 00:00", "2024-01-10 10:00"),
                       _cm("B", "2024-03-01 00:00", None)])                     # still open -> dropped
    ep = rel.failure_episodes(cm)
    assert ep[["asset_id", "n_orders"]].values.tolist() == [["A", 3], ["A", 1], ["B", 1]]
    assert ep["restore_hours"].tolist() == [56.0, 5.0, 10.0]
    assert ep["failure_mode"].tolist() == ["No Heat", "Leaking", "No Heat"]


def test_reliability_table_hand_values():
    ep = pd.DataFrame({"asset_id": ["A", "A", "B", "A"],
                       "start": [T("2024-01-10"), T("2024-03-01"), T("2024-02-01"), T("2025-06-01")],
                       "end": [T("2024-01-10 10:00"), T("2024-03-01 20:00"), T("2024-02-02"), T("2025-06-02")],
                       "failure_mode": ["x"] * 4})
    ep["restore_hours"] = (ep["end"] - ep["start"]) / pd.Timedelta(hours=1)
    win = pd.DataFrame({"asset_id": ["A", "B", "C"], "start": [T("2024-01-01")] * 3,
                        "end": [T("2025-01-01")] * 3, "cls": ["BOILER", "BOILER", "PUMP"]})
    t = rel.reliability_table(ep, win, by="cls").set_index("cls")
    hours = 366 * 24
    assert t.loc["BOILER", "failures"] == 3            # the 2025 episode is outside the window
    assert t.loc["BOILER", "exposure_h"] == 2 * hours
    assert t.loc["BOILER", "mtbf_h"] == pytest.approx(2 * hours / 3)
    assert t.loc["BOILER", "mttr_h"] == pytest.approx((10 + 20 + 24) / 3)
    assert t.loc["BOILER", "median_restore_h"] == 20.0
    assert t.loc["BOILER", "availability"] == pytest.approx((2 * hours / 3) / (2 * hours / 3 + 18))
    assert t.loc["PUMP", "failures"] == 0 and np.isnan(t.loc["PUMP", "mtbf_h"])
    assert t.loc["BOILER", "episodes_per_asset_year"] == pytest.approx(3 / (2 * hours / 8766.0))
    assert t.loc["PUMP", "episodes_per_asset_year"] == 0.0
    # episodes that already carry the group column (with a stale value) give the same table
    t2 = rel.reliability_table(ep.assign(cls="PUMP"), win, by="cls").set_index("cls")
    assert t2.loc["BOILER", "failures"] == 3 and t2.loc["PUMP", "failures"] == 0
    allg = rel.reliability_table(ep, win)
    assert allg["failures"].iloc[0] == 3 and allg["exposure_h"].iloc[0] == 3 * hours
    with pytest.raises(ValueError):
        rel.reliability_table(ep, win.assign(end=T("2023-01-01")))


def test_repeat_flags_boundary_and_mode():
    ep = pd.DataFrame({"asset_id": ["A", "A", "A", "B", "A"],
                       "start": [T("2024-01-01"), T("2024-01-31 12:00"), T("2024-03-15"), T("2024-01-05"), T("2024-03-20")],
                       "end": [T("2024-01-01 12:00"), T("2024-02-01"), T("2024-03-16"), T("2024-01-06"), T("2024-03-21")],
                       "failure_mode": ["m1", "m1", "m2", "m1", "m1"]})
    f = rel.repeat_flags(ep, within_days=30)
    # 2nd: exactly 30.0 days after the 1st ended -> repeat; 3rd: 42 days -> no; 5th: 4 days -> yes
    assert f.tolist() == [False, True, False, False, True]
    g = rel.repeat_flags(ep, within_days=30, same_mode=True)
    # same mode: 5th (m1) follows the 2nd m1 (ended 2024-02-01) by 48 days -> not a repeat
    assert g.tolist() == [False, True, False, False, False]


def test_pareto_vital_few():
    df = pd.DataFrame({"mode": ["a", "b", "c", "d", "a", "e"], "h": [30.0, 25.0, 20.0, 15.0, 0.0, 10.0]})
    p = rel.pareto(df, "mode", "h")
    assert p["mode"].tolist() == ["a", "b", "c", "d", "e"]
    assert p["cum_share"].tolist() == pytest.approx([0.3, 0.55, 0.75, 0.9, 1.0])
    assert p["vital_few"].tolist() == [True, True, True, True, False]
    q = rel.pareto(df, "mode", "h", vital_share=0.75)
    assert q["vital_few"].tolist() == [True, True, True, False, False]


def test_uptime_intervals_with_censoring():
    ep = pd.DataFrame({"asset_id": ["A", "A", "A", "B", "C"],
                       "start": [T("2024-01-10"), T("2024-03-01"), T("2024-06-01"), T("2024-05-01"), T("2023-05-01")],
                       "end": [T("2024-01-11"), T("2024-03-03"), T("2024-06-02"), T("2024-05-02"), T("2023-05-02")]})
    win = pd.DataFrame({"asset_id": ["A", "B", "C"], "start": [T("2024-01-01")] * 3, "end": [T("2024-12-31")] * 3})
    u = rel.uptime_intervals(ep, win)
    assert u.values.tolist() == [["A", 50.0, True], ["A", 90.0, True], ["A", 212.0, False], ["B", 243.0, False]]


# ================================================================ data-free outputs are self-consistent
def test_pm_sensitivity_monotone_in_cost_ratio():
    prev = math.inf
    for ratio in (2.0, 3.0, 5.0, 10.0, 20.0):
        t = wb.optimal_age_replacement(2.5, 1.0, 1.0, ratio)["t_opt_over_eta"]
        assert t < prev
        prev = t


# ================================================================ text classification
from fabhvac.maintenance import textclass as tc  # noqa: E402


def test_normalise():
    assert tc.normalise("  No-HEAT in Bldg #4!! ") == "no heat in bldg 4"
    assert tc.normalise(None) == "" and tc.normalise(float("nan")) == ""


def test_rule_classifier_first_match_wins_and_abstains():
    r = tc.RuleClassifier([("Leaking", r"\bleak"), ("No Heat", r"\bno heat\b|\bcold\b")])
    assert list(r.predict(["Leak at boiler, no heat", "NO HEAT in office", "paint door"])) == \
        ["Leaking", "No Heat", tc.ABSTAIN]


def test_scores_hand_values():
    y = ["a", "a", "b", "b", "c"]
    p = ["a", tc.ABSTAIN, "b", "a", "c"]
    s = tc.scores(y, p, ["a", "b", "c"])
    assert s["n"] == 5 and s["accuracy"] == pytest.approx(3 / 5)
    assert s["coverage"] == pytest.approx(4 / 5) and s["accuracy_on_covered"] == pytest.approx(3 / 4)
    f1a = 2 * 0.5 * 0.5 / 1.0
    f1b = 2 * 1.0 * 0.5 / 1.5
    assert s["per_class"]["a"]["precision"] == 0.5 and s["per_class"]["b"]["recall"] == 0.5
    assert s["macro_f1"] == pytest.approx((f1a + f1b + 1.0) / 3)
    # a class with no true examples does not enter the macro average
    s2 = tc.scores(["a", "a"], ["a", "b"], ["a", "b"])
    assert s2["macro_f1"] == pytest.approx(2 * 1 * 0.5 / 1.5)
    with pytest.raises(ValueError):
        tc.scores([], [], ["a"])


def test_confusion_has_abstain_column():
    m = tc.confusion(["a", "b", "b"], ["b", tc.ABSTAIN, "b"], ["a", "b"])
    assert m.tolist() == [[0, 1, 0], [0, 1, 1]]


def test_time_split_and_unseen():
    d = pd.Series(pd.to_datetime(["2020-05-01", "2022-12-31", "2023-01-01", "2023-06-30", "2024-01-01", "2024-02-01"]))
    tr, va, te = tc.time_split(d, "2023-01-01", "2023-07-01", "2024-01-01")
    assert tr.tolist() == [True, True, False, False, False, False]
    assert va.tolist() == [False, False, True, True, False, False]
    assert te.tolist() == [False, False, False, False, True, True]
    tr2, va2, te2 = tc.time_split(d, "2023-01-01", "2023-07-01")
    assert te2.tolist() == [False, False, False, False, True, True] and not np.any(tr2 & te2)
    with pytest.raises(ValueError):
        tc.time_split(d, "2024-01-01", "2023-01-01")
    m = tc.unseen_mask(["No heat!", "leak"], ["no  HEAT", "leak at sink", "LEAK"])
    assert m.tolist() == [False, True, False]


class _FakeProba:
    classes_ = np.array(["Leaking", "No Heat"], dtype=object)

    def predict_proba(self, texts):
        return np.array([[0.9, 0.1] if "leak" in t else [0.45, 0.55] for t in texts])


def test_predict_with_abstain():
    lab, top = tc.predict_with_abstain(_FakeProba(), ["leak", "cold room"], 0.6)
    assert lab.tolist() == ["Leaking", tc.ABSTAIN] and top.tolist() == [0.9, 0.55]
    lab, _ = tc.predict_with_abstain(_FakeProba(), ["leak", "cold room"], 0.55)   # threshold is inclusive
    assert lab.tolist() == ["Leaking", "No Heat"]
    assert tc.predict_with_abstain(_FakeProba(), [], 0.5)[0].size == 0


def test_abstain_threshold_hand_values():
    top = [0.9, 0.8, 0.6, 0.4]
    ok = [True, True, False, False]
    r = tc.abstain_threshold(top, ok, 0.99)
    assert r == {"threshold": 0.61, "coverage": 0.5, "accuracy_on_covered": 1.0}
    r = tc.abstain_threshold(top, ok, 0.6)
    assert r["threshold"] == 0.41 and r["coverage"] == 0.75 and r["accuracy_on_covered"] == pytest.approx(2 / 3)
    assert tc.abstain_threshold(top, ok, 0.5)["threshold"] == 0.0
    assert tc.abstain_threshold(top, [False] * 4, 0.5)["threshold"] is None
    with pytest.raises(ValueError):
        tc.abstain_threshold(top, ok[:3], 0.9)


@pytest.mark.parametrize("k,n", [(0, 10), (3, 35), (29, 35), (175, 350), (350, 350)])
def test_wilson_ci_against_scipy(k, n):
    stats = pytest.importorskip("scipy.stats")
    lo, hi = tc.wilson_ci(k, n)
    ref = stats.binomtest(k, n).proportion_ci(confidence_level=0.95, method="wilson")
    assert lo == pytest.approx(ref.low, abs=1e-9) and hi == pytest.approx(ref.high, abs=1e-9)
    with pytest.raises(ValueError):
        tc.wilson_ci(5, 4)


def test_text_model_learns_and_is_deterministic():
    pytest.importorskip("sklearn")
    rng = np.random.default_rng(0)
    words = {"Leaking": ["leak", "dripping", "water on floor", "pipe burst"],
             "No Heat": ["no heat", "cold", "boiler down", "radiator cold"],
             "Clogged": ["clogged", "blocked drain", "toilet backed up", "sink stopped"]}
    texts, labels = [], []
    for lab, ws in words.items():
        for _ in range(40):
            texts.append(f"{rng.choice(['bldg', 'office', 'comfort station'])} {rng.choice(ws)} {rng.integers(1, 9)}")
            labels.append(lab)
    m1 = tc.make_text_model().fit(texts, labels)
    m2 = tc.make_text_model().fit(texts, labels)
    test = ["office pipe burst", "radiator cold in bldg", "toilet backed up"]
    assert list(m1.predict(test)) == ["Leaking", "No Heat", "Clogged"]
    assert np.array_equal(m1.predict_proba(test), m2.predict_proba(test))


# ================================================================ condition indicator
def test_residual_indicator_daily_threshold_and_alarms():
    pytest.importorskip("sklearn")
    from fabhvac.maintenance.condition import ResidualIndicator, daily_mean
    rng = np.random.default_rng(7)
    idx = pd.date_range("2018-01-01", periods=24 * 120, freq="1h")
    x1 = 10 + 8 * np.sin(np.arange(idx.size) * 2 * np.pi / 24) + rng.normal(0, 1, idx.size)
    x2 = rng.uniform(0, 1, idx.size)
    y = 20 + 0.5 * x1 + 3 * x2 + rng.normal(0, 0.5, idx.size)
    df = pd.DataFrame({"x1": x1, "x2": x2, "y": y}, index=idx)
    ind = ResidualIndicator("y", ["x1", "x2"]).fit(df, df.index.month.to_numpy())
    # daily mean of N(0, 0.5) hourly noise has sd ~0.1; the 99th percentile sits near 0.24
    assert 0.1 < ind.threshold_ < 0.5
    assert ind.oof_daily_.size == 120
    hot = df.copy()
    hot["y"] += 0.8
    assert ind.alarms(hot).mean() > 0.95
    cold = df.copy()
    cold["y"] -= 0.8          # one-sided: a lower signal never alarms
    assert ind.alarms(cold).mean() == 0.0
    assert ind.alarms(df).mean() < 0.05
    # daily mean drops days with too few hours
    v = np.ones(30)
    s = daily_mean(v, pd.date_range("2018-01-01 00:00", periods=30, freq="1h"), min_hours=12)
    assert s.size == 1 and s.iloc[0] == 1.0


# ================================================================ LLM wrapper (no network)
from fabhvac.maintenance import llm  # noqa: E402


def test_llm_request_is_label_only_and_deterministic():
    req = llm.build_request("no heat in rec center", ["Leaking", "No Heat"], "some-model", {"No Heat": "space not heated"})
    assert req["format"]["properties"]["label"]["enum"] == ["Leaking", "No Heat"]
    assert req["options"]["temperature"] == 0 and req["stream"] is False
    assert "space not heated" in req["prompt"] and "no heat in rec center" in req["prompt"]


@pytest.mark.parametrize("raw,expect", [('{"label": "No Heat"}', "No Heat"), ('{"label": "Exploded"}', tc.ABSTAIN),
                                        ("No Heat", tc.ABSTAIN), ('{"label": 3}', tc.ABSTAIN), ("[1]", tc.ABSTAIN)])
def test_llm_parse_label(raw, expect):
    assert llm.parse_label(raw, ["Leaking", "No Heat"]) == expect


def test_llm_batch_request_and_parse():
    req = llm.build_batch_request(["no heat", "sink clogged", "lights out"], ["Clogged", "No Heat", "No Light"], "m")
    arr = req["format"]["properties"]["labels"]
    assert arr["minItems"] == arr["maxItems"] == 3 and arr["items"]["enum"] == ["Clogged", "No Heat", "No Light"]
    assert "1. 'no heat'" in req["prompt"] and "3. 'lights out'" in req["prompt"]
    labs = ["Clogged", "No Heat"]
    assert llm.parse_batch('{"labels": ["No Heat", "Clogged"]}', labs, 2) == ["No Heat", "Clogged"]
    assert llm.parse_batch('{"labels": ["No Heat", "Boom"]}', labs, 2) == ["No Heat", tc.ABSTAIN]
    assert llm.parse_batch('{"labels": ["No Heat"]}', labs, 2) == [tc.ABSTAIN, tc.ABSTAIN]   # misaligned
    assert llm.parse_batch("not json", labs, 2) == [tc.ABSTAIN, tc.ABSTAIN]


def test_llm_available_without_server():
    assert llm.available("http://127.0.0.1:9", timeout=0.5) == []


# ================================================================ AMPS adapter
from fabhvac.maintenance import amps  # noqa: E402


def _amps_rows():
    cols = ["evt_code", "evt_desc", "evt_type", "evt_jobtype", "evt_reqm", "evt_object", "evt_mrc",
            "evt_reported", "evt_created", "evt_completed", "evt_udfchar13", "evt_udfchar06"]
    rows = [
        ["1", "No heat in rec center", "JOB", "CM", "No Heat", "B1", "Q-05", "2024-01-03T08:00:00.000",
         "2024-01-03T09:00:00.000", "2024-01-04T08:00:00.000", "Completed", "STEAMFITTER"],
        ["2", "Repair bench", "JOB", "CM", "Structural Damage", "PARK9", "X-02", "",
         "2024-02-01T10:00:00.000", "2024-02-02T10:00:00.000", "GT Completed", "CARPENTER"],
        ["3", "Annual boiler inspection", "PPM", "CM", "No Heat", "B1", "Q-05", "2024-03-01T07:00:00.000",
         "2024-03-01T07:00:00.000", "2024-03-01T12:00:00.000", "Completed", ""],
        ["4", "Pump leaking", "JOB", "BRKD", "Leaking", "P7", "Q-05", "2024-04-01T07:00:00.000",
         "2024-04-01T07:00:00.000", "2024-04-02T07:00:00.000", "Cancelled", "PLUMBER"],
        ["5", "Check filter plant", "JOB", "ADHC", "", "P7", "Q-07", "2024-05-01T07:00:00.000",
         "2024-05-01T07:00:00.000", "", "Open", ""],
        ["6", "Issue parts", "JOB", "IS", "", "", "*", "", "2024-06-01T07:00:00.000", "", "Work Request", ""],
        ["7", "Schedule", "JOB", "SCHD", "", "B1", "Q-05", "", "2024-06-02T07:00:00.000", "", "Rejected", ""],
    ]
    w = pd.DataFrame(rows, columns=cols)
    a = pd.DataFrame({"obj_code": ["B1", "P7", "P7"], "obj_class": ["BOILER", "PUMP", "PUMP"]})
    return w, a


def test_amps_to_canonical_mapping():
    w, a = _amps_rows()
    c = amps.to_canonical(w, a)
    assert c["wo_type"].tolist() == ["CM", "CM", "PM", "CM", "INSP", "OTHER", "PM"]
    assert c["status"].tolist() == ["closed", "closed", "closed", "cancelled", "open", "open", "cancelled"]
    # failure mode only for CM orders with one of the seven building-services codes
    assert c["failure_mode"].tolist() == ["No Heat", "", "", "Leaking", "", "", ""]
    assert c["asset_class"].tolist() == ["BOILER", "(unregistered)", "BOILER", "PUMP", "PUMP", "(unregistered)", "BOILER"]
    assert c["site"].tolist() == ["Queens", "Bronx", "Queens", "Queens", "Queens", "", "Queens"]
    # opened = reported when present, else created; closed only when the status is closed
    assert c.loc[0, "opened_at"] == T("2024-01-03 08:00") and c.loc[1, "opened_at"] == T("2024-02-01 10:00")
    assert c.loc[0, "closed_at"] == T("2024-01-04 08:00") and pd.isna(c.loc[3, "closed_at"])
    assert c["downtime_hours"].isna().all()
    assert list(c.columns[:len(wo.COLUMNS)]) == list(wo.COLUMNS)
    f = wo.validate(c, failure_modes=amps.MEP_MODES)
    assert f["cm_without_failure_mode"].tolist() == [False, True, False, False, False, False, False]


def test_amps_hierarchy_uses_most_frequent_district():
    w, a = _amps_rows()
    c = amps.to_canonical(w, a)
    h = amps.hierarchy(c)
    assert h.path("B1") == ["Queens", "Q-05", "B1"]
    assert h.path("P7") == ["Queens", "Q-05", "P7"]       # Q-05 once, Q-07 once: tie -> alphabetical
    c2 = pd.concat([c, c.iloc[[4, 4]]], ignore_index=True)
    assert amps.hierarchy(c2).path("P7") == ["Queens", "Q-07", "P7"]
    assert h.path("X-02")[0] == "Bronx"


@pytest.mark.parametrize("text,routine", [
    ("Blewdown boiler sight glass and bottom blowdown", True), ("Bottom blowdown on boiler 2", True),
    ("Perform boiler water treatment readings", True),
    ("Perform chem test of condenser water system", True), ("Annual boiler overhaul", True),
    ("Winterize spray shower", True), ("Repair boiler - no heat", False), ("Pump leaking badly", False)])
def test_amps_routine_rule(text, routine):
    assert amps.is_routine([text])[0] == routine


def test_amps_new_work_rule():
    assert amps.is_new_work(["Install circulator pump", "Relocate desk", "Repair circulator"]).tolist() == [True, True, False]


@pytest.mark.parametrize("text,label", [
    ("No heat in building", "No Heat"), ("Boiler not working", "No Heat"),
    ("Faucet won't stop running", "Will not turn off"), ("Toilet clogged and flooding the floor", "Clogged"),
    ("Pipe leaking under sink", "Leaking"), ("3 lights out in mens room", "No Light"),
    ("Low water pressure at fountain", "No Water"), ("Outlet not working in office", "Not working electrical"),
    ("Paint the bench", tc.ABSTAIN)])
def test_amps_mep_rules(text, label):
    assert tc.RuleClassifier(amps.MEP_RULES).predict_one(text) == label
