"""Part D: facilities maintenance analytics on the NYC Parks AMPS snapshot.

Needs the local snapshot written by scripts/maint_fetch.py (NYC_AMPS_DIR). Writes only
aggregates to results/ (no free text, no asset names):

  maintenance_data_checks.json            snapshot, mapping, validation-rule counts, data-quality findings
  maintenance_textclass.json              rules vs TF-IDF + logistic regression, validation and test
  maintenance_textclass_per_class.csv     per-class precision / recall / F1 on the test period
  maintenance_textclass_confusion_{rules,ml}.csv
  maintenance_reliability_by_class.csv    HVAC equipment: MTBF, MTTR, availability per asset class
  maintenance_boiler_modes.csv            boiler failure episodes by failure mode
  maintenance_pareto.csv                  building-services corrective orders: Pareto by failure mode
  maintenance_repeats.json                repeat failures (boilers; "No Heat" calls per building)
  maintenance_weibull_boiler.json         Weibull fit to boiler uptimes + PM-interval analysis

Text-classification protocol: train = created before 2023, validation = 2023 (the rules were
revised once here; C is fixed at 1; the abstain threshold is chosen here), test = created
2024-01-01 or later, evaluated with the model refitted on train + validation. Local test
predictions (with text) are written to <NYC_AMPS_DIR>/textclass_test_predictions.parquet for
scripts/maint_llm.py, not to results/.

Failure modes of HVAC equipment orders: the problem code where it is one of the seven
building-services codes; otherwise the text model's label, or "(none)" (abstained) when its
top probability is below the validation-chosen threshold. Mode counts are reported separately
for coded and predicted episodes.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fabhvac.maintenance import amps, reliability as rel, textclass as tc, weibull as wb  # noqa: E402
from fabhvac.maintenance import workorder as wo  # noqa: E402
from fabhvac.results_io import write_csv, write_json  # noqa: E402

RES = Path(os.environ.get("FABHVAC_RESULTS_DIR", ROOT / "results"))
TRAIN_END, VAL_END = "2023-01-01", "2024-01-01"
WINDOW_START = pd.Timestamp("2021-01-01")   # equipment CM logging in AMPS ramps up in 2021
REPEAT_DAYS = 30
HVAC_TRADES = ("STEAMFITTER", "STEAMFITHELP", "STAENG", "SENSTAENG", "THRMSTATREPAIR", "OILER")
COST_RATIO_BASE = 5.0                        # illustrative c_f / c_p; swept below
COST_RATIOS = [1.5, 2.0, 3.0, 5.0, 10.0, 20.0, 50.0]
LABELS = list(amps.MEP_MODES)
# abstain rule, fixed before it was applied: the smallest top-probability threshold at which the
# validation-year orders the model does label are right at least this often
ABSTAIN_TARGET_ACCURACY = 0.95
N_BOOT = 2000


def data_dir() -> Path:
    d = os.environ.get("NYC_AMPS_DIR")
    if not d:
        sys.exit("set NYC_AMPS_DIR to the snapshot folder written by scripts/maint_fetch.py")
    return Path(d)


def load():
    d = data_dir()
    w = pd.read_parquet(d / "work_orders.parquet")
    a = pd.read_parquet(d / "assets.parquet")
    lab = pd.read_parquet(d / "labor_by_wo.parquet")
    snap = json.loads((d / "snapshot.json").read_text(encoding="utf-8"))
    return w, a, lab, snap


# ---------------------------------------------------------------- data checks
def data_checks(w, a, canon, snap, end):
    h = amps.hierarchy(canon)
    flags = wo.validate(canon, failure_modes=amps.MEP_MODES, hierarchy=h)
    cm = canon["wo_type"] == "CM"
    hv = a[a["obj_class"].isin(amps.HVAC_CLASSES)]
    hv_cm = canon[cm & canon["asset_class"].isin(amps.HVAC_CLASSES)]
    routine = amps.is_routine(hv_cm["description"])
    el = wo.elapsed_hours(canon)
    return {
        "snapshot": {"rows": snap["rows"], "sha256": snap["sha256"], "download_times": snap["download_times"],
                     "last_created_day": str(end.date())},
        "mapping": {"wo_type_counts": canon["wo_type"].value_counts().sort_index().to_dict(),
                    "status_counts": canon["status"].value_counts().sort_index().to_dict(),
                    "opened_at_from_created_because_reported_blank": int((w["evt_reported"] == "").sum())},
        "validation": wo.validation_summary(flags),
        "missing_required_by_column": {c: int(((canon[c].isna()) | (canon[c].astype(str).str.strip() == "")).sum())
                                       for c in wo.REQUIRED},
        "validation_notes": {
            "cm_without_failure_mode": "CM orders whose problem code is not one of the 7 building-services codes "
                                       "(includes park-structure codes such as Structural Damage)",
            "cm_with_blank_problem_code": int((cm & (canon["problem_code"] == "")).sum()),
            "asset_not_in_hierarchy": "asset never appears with a maintenance district"},
        "elapsed_hours_closed": {"p50": float(el.median()), "p90": float(el.quantile(0.9)),
                                 "over_365_days": int((el > 365 * 24).sum())},
        "assets": {"rows": int(len(a)), "duplicate_obj_code_rows": int(a["obj_code"].duplicated(keep=False).sum()),
                   "hvac_class_assets": hv["obj_class"].value_counts().sort_index().to_dict(),
                   "hvac_commission_date_is_1900_placeholder": int(hv["obj_commiss"].str.contains("1900").sum()),
                   "hvac_with_parent_link": int((hv["obj_parent"] != "").sum()),
                   "class_EXTHD_is_hard_drives_not_hvac": int((a["obj_class"] == "EXTHD").sum())},
        "hvac_equipment_cm": {"orders": int(len(hv_cm)), "routine_task_text": int(routine.sum()),
                              "routine_share": float(routine.mean()),
                              "with_mep_problem_code": int((hv_cm["failure_mode"] != "").sum()),
                              "with_any_problem_code_other_than_blank_or_non_applicable": int(
                                  (~hv_cm["problem_code"].isin(["", "Non applicable"])).sum())},
    }


# ---------------------------------------------------------------- text classification
def text_classification(canon):
    d = canon[(canon["wo_type"] == "CM") & canon["problem_code"].isin(LABELS) & (canon["description"].str.strip() != "")]
    d = d.sort_values("created_at", kind="mergesort")
    tr, va, te = tc.time_split(d["created_at"], TRAIN_END, VAL_END)
    X, y = d["description"].tolist(), d["problem_code"].to_numpy()
    Xa = np.array(X, dtype=object)
    rules = tc.RuleClassifier(amps.MEP_RULES)
    pr = rules.predict(X)
    t0 = time.time()
    m_tr = tc.make_text_model().fit(list(Xa[tr]), y[tr])
    pv_ml = m_tr.predict(list(Xa[va]))
    _, pv_top = tc.predict_with_abstain(m_tr, list(Xa[va]), 0.0)
    abst = tc.abstain_threshold(pv_top, pv_ml == y[va], ABSTAIN_TARGET_ACCURACY)
    if abst["threshold"] is None:
        sys.exit("abstain target not reachable on the validation year")
    m_final = tc.make_text_model().fit(list(Xa[tr | va]), y[tr | va])
    pt_ml = m_final.predict(list(Xa[te]))
    pt_ab, _ = tc.predict_with_abstain(m_final, list(Xa[te]), abst["threshold"])
    fit_s = time.time() - t0
    unseen = tc.unseen_mask(Xa[tr | va], Xa[te])
    hvac = d.loc[te, "trade"].isin(HVAC_TRADES).to_numpy()
    hvac_va = d.loc[va, "trade"].isin(HVAC_TRADES).to_numpy()
    yt, pt_r = y[te], pr[te]

    def both(mask):
        r = {"n": int(mask.sum()), "rules": tc.scores(yt[mask], pt_r[mask], LABELS),
             "ml": tc.scores(yt[mask], pt_ml[mask], LABELS),
             "ml_with_abstain": tc.scores(yt[mask], pt_ab[mask], LABELS)}
        k = int(np.sum(yt[mask] == pt_ml[mask]))
        r["ml"]["accuracy_ci95_wilson"] = list(tc.wilson_ci(k, int(mask.sum())))
        return r

    out = {"labels": LABELS,
           "population": "corrective (CM) orders whose problem code is one of the labels, non-empty description",
           "split": {"train": f"created < {TRAIN_END}", "validation": f"{TRAIN_END} <= created < {VAL_END}",
                     "test": f"created >= {VAL_END}", "n_train": int(tr.sum()), "n_validation": int(va.sum()),
                     "n_test": int(te.sum())},
           "label_counts": {"train": pd.Series(y[tr]).value_counts().to_dict(),
                            "test": pd.Series(yt).value_counts().to_dict()},
           "model": "TF-IDF word 1-2-grams + char_wb 3-5-grams, multinomial logistic regression, balanced class "
                    "weights, C = 1 (fixed, not searched)",
           "fit_seconds": fit_s,
           "abstain": {"rule": f"smallest top-probability threshold (grid 0.00-0.99) at which validation-year "
                               f"accuracy on the labelled orders is >= {ABSTAIN_TARGET_ACCURACY}; model trained "
                               f"on the training years; threshold then applied to the refitted model",
                       "target_accuracy": ABSTAIN_TARGET_ACCURACY, **abst,
                       "validation_hvac_trades": {"n": int(hvac_va.sum()),
                                                  "coverage": float(np.mean(pv_top[hvac_va] >= abst["threshold"]))
                                                  if hvac_va.any() else None}},
           "validation": {"rules": tc.scores(y[va], pr[va], LABELS), "ml_trained_on_train": tc.scores(y[va], pv_ml, LABELS)},
           "test": {"all": both(np.ones(te.sum(), bool)),
                    "unseen_text": both(unseen),
                    "hvac_trades": both(hvac)},
           "test_unseen_share": float(unseen.mean()),
           "majority_class_test_accuracy": float(pd.Series(yt).value_counts(normalize=True).iloc[0])}
    # local, with text, for the optional LLM comparison (never written to results/)
    pd.DataFrame({"wo_id": d.loc[te, "wo_id"].to_numpy(), "description": Xa[te], "label": yt, "rules": pt_r,
                  "ml": pt_ml, "unseen": unseen, "hvac_trade": hvac}).to_parquet(
        data_dir() / "textclass_test_predictions.parquet", index=False)
    per = []
    for c in LABELS:
        r_, m_ = out["test"]["all"]["rules"]["per_class"][c], out["test"]["all"]["ml"]["per_class"][c]
        per.append([c, r_["support"], r_["precision"], r_["recall"], r_["f1"], m_["precision"], m_["recall"], m_["f1"]])
    write_csv(RES / "maintenance_textclass_per_class.csv",
              ["label", "test_support", "rules_precision", "rules_recall", "rules_f1", "ml_precision", "ml_recall", "ml_f1"], per)
    for name, p in (("rules", pt_r), ("ml", pt_ml)):
        cmx = tc.confusion(yt, p, LABELS)
        write_csv(RES / f"maintenance_textclass_confusion_{name}.csv", ["true\\pred"] + LABELS + [tc.ABSTAIN],
                  [[c] + list(cmx[i]) for i, c in enumerate(LABELS)])
    for k in ("all", "unseen_text", "hvac_trades"):          # keep the JSON small: per-class only in the CSV
        for mth in ("rules", "ml", "ml_with_abstain"):
            out["test"][k][mth].pop("per_class")
    for mth in ("rules", "ml_trained_on_train"):
        out["validation"][mth].pop("per_class")
    write_json(RES / "maintenance_textclass.json", out)
    return m_final, abst["threshold"]


# ---------------------------------------------------------------- equipment reliability
def windows_for(a, end):
    hv = a[a["obj_class"].isin(amps.HVAC_CLASSES)].drop_duplicates("obj_code")
    comm = pd.to_datetime(hv["obj_commiss"].replace("", None), format="%b %d %Y %I:%M%p", errors="coerce")
    wd = pd.to_datetime(hv["obj_withdraw"].replace("", None), format="%b %d %Y %I:%M%p", errors="coerce")
    start = comm.where((comm.dt.year >= 2000) & (comm > WINDOW_START), WINDOW_START)
    stop = wd.where(wd.notna() & (wd < end), end)
    w = pd.DataFrame({"asset_id": hv["obj_code"].to_numpy(), "asset_class": hv["obj_class"].to_numpy(),
                      "start": start.to_numpy(), "end": stop.to_numpy()})
    return w[w["end"] > w["start"]].reset_index(drop=True)


def equipment(canon, a, labor, end, model, abstain_threshold):
    win = windows_for(a, end)
    eq = canon[(canon["wo_type"] == "CM") & canon["asset_class"].isin(amps.HVAC_CLASSES)].copy()
    eq["routine"] = amps.is_routine(eq["description"])
    eq["new_work"] = amps.is_new_work(eq["description"])
    in_win = (eq["opened_at"] >= WINDOW_START) & (eq["opened_at"] < end)
    fail = eq[in_win & (eq["status"] == "closed") & ~eq["routine"] & ~eq["new_work"]
              & eq["closed_at"].notna() & (eq["closed_at"] >= eq["opened_at"])].copy()
    pred, _ = tc.predict_with_abstain(model, fail["description"].tolist(), abstain_threshold)
    coded = (fail["failure_mode"] != "").to_numpy()
    fail["mode_source"] = np.where(coded, "problem_code", np.where(pred == tc.ABSTAIN, "abstained", "predicted"))
    fail["failure_mode"] = np.where(coded, fail["failure_mode"], pred)
    fail["labor_hours"] = fail["wo_id"].map(labor)
    funnel = {"cm_orders_on_hvac_assets": int(len(eq)), "in_window": int(in_win.sum()),
              "closed": int((in_win & (eq["status"] == "closed")).sum()),
              "routine_excluded": int((in_win & (eq["status"] == "closed") & eq["routine"]).sum()),
              "new_work_excluded": int((in_win & (eq["status"] == "closed") & ~eq["routine"] & eq["new_work"]).sum()),
              "failure_orders": int(len(fail)),
              "failure_mode_from_problem_code": int((fail["mode_source"] == "problem_code").sum()),
              "failure_mode_predicted_from_text": int((fail["mode_source"] == "predicted").sum()),
              "failure_mode_model_abstained": int((fail["mode_source"] == "abstained").sum()),
              "abstain_threshold": abstain_threshold}
    ep = rel.failure_episodes(fail)
    ep = ep.merge(win[["asset_id", "asset_class"]], on="asset_id", how="left")
    funnel["episodes"] = int(len(ep))
    funnel["episodes_on_assets_without_window"] = int(ep["asset_class"].isna().sum())
    tab = rel.reliability_table(ep.dropna(subset=["asset_class"]), win, by="asset_class")
    # robustness: restore times are heavy-tailed (orders left open for months), so also show
    # the availability implied by the median restore time
    tab["availability_with_median_restore"] = tab["mtbf_h"] / (tab["mtbf_h"] + tab["median_restore_h"])
    lab = fail.groupby("asset_class")["labor_hours"].agg(["median", "count"])
    tab["median_labor_h_per_order"] = tab["asset_class"].map(lab["median"])
    tab["orders_with_labor"] = tab["asset_class"].map(lab["count"]).fillna(0).astype(int)
    write_csv(RES / "maintenance_reliability_by_class.csv", list(tab.columns), tab.itertuples(index=False))
    return win, fail, ep, funnel


def boiler_modes(fail, ep):
    b = ep[ep["asset_class"] == "BOILER"]
    src = fail.drop_duplicates(["asset_id", "opened_at"]).set_index(["asset_id", "opened_at"])["mode_source"]
    b = b.assign(mode_source=[src.get((x, s), "") for x, s in zip(b["asset_id"], b["start"])])
    g = b.groupby("failure_mode", sort=True)
    t = pd.DataFrame({"episodes": g.size(), "mean_restore_h": g["restore_hours"].mean(),
                      "median_restore_h": g["restore_hours"].median(),
                      "restore_h_total": g["restore_hours"].sum(),
                      # the source of the mode is reported separately: a problem code chosen in the
                      # CMMS, or the text model's label (model output, see maintenance_textclass.json)
                      "episodes_mode_from_problem_code": g["mode_source"].apply(lambda s: int((s == "problem_code").sum())),
                      "episodes_mode_predicted": g["mode_source"].apply(lambda s: int((s == "predicted").sum())),
                      "episodes_model_abstained": g["mode_source"].apply(lambda s: int((s == "abstained").sum()))})
    t = t.sort_values("episodes", ascending=False, kind="mergesort").reset_index()
    t["share_of_episodes"] = t["episodes"] / t["episodes"].sum()
    t["share_of_coded_episodes"] = t["episodes_mode_from_problem_code"] / t["episodes_mode_from_problem_code"].sum()
    n_model = t["episodes_mode_predicted"] + t["episodes_model_abstained"]
    t["share_of_model_episodes"] = n_model / n_model.sum()
    write_csv(RES / "maintenance_boiler_modes.csv", list(t.columns), t.itertuples(index=False))
    return b


def pareto_mep(canon, end):
    d = canon[(canon["wo_type"] == "CM") & (canon["failure_mode"] != "") & (canon["status"] == "closed")
              & (canon["opened_at"] >= WINDOW_START) & (canon["opened_at"] < end)].copy()
    d["restore_h"] = wo.elapsed_hours(d)
    d = d[d["restore_h"] >= 0]
    d["orders"] = 1
    rows = []
    for metric in ("orders", "restore_h"):
        p = rel.pareto(d, "failure_mode", metric)
        for r in p.itertuples(index=False):
            rows.append([metric, r.failure_mode, getattr(r, metric), r.share, r.cum_share, bool(r.vital_few)])
    med = d.groupby("failure_mode")["restore_h"].median()
    for m in LABELS:
        rows.append(["median_restore_h", m, float(med.get(m, np.nan)), None, None, None])
    write_csv(RES / "maintenance_pareto.csv", ["metric", "failure_mode", "value", "share", "cum_share", "vital_few"], rows)
    return d


def repeats(b_ep, mep):
    out = {"definition": f"episode starting within {REPEAT_DAYS} days after the previous episode on the same asset ended"}
    f = rel.repeat_flags(b_ep, REPEAT_DAYS)
    # same mode only counts when the mode is known (an abstained "(none)" is not a mode)
    fm = rel.repeat_flags(b_ep, REPEAT_DAYS, same_mode=True) & (b_ep["failure_mode"] != tc.ABSTAIN)
    per_boiler = b_ep.groupby("asset_id").size().sort_values(ascending=False)
    out["boilers"] = {"episodes": int(len(b_ep)), "repeat_any_mode": int(f.sum()), "repeat_any_mode_share": float(f.mean()),
                      "repeat_same_known_mode": int(fm.sum()), "repeat_same_known_mode_share": float(fm.mean()),
                      "episodes_with_known_mode": int((b_ep["failure_mode"] != tc.ABSTAIN).sum()),
                      "assets_with_episodes": int(b_ep["asset_id"].nunique()),
                      "share_of_episodes_in_top_10pct_of_boilers_with_episodes": float(
                          per_boiler.iloc[:max(1, len(per_boiler) // 10)].sum() / per_boiler.sum()),
                      "max_episodes_one_boiler": int(per_boiler.iloc[0])}
    nh = mep[(mep["failure_mode"] == "No Heat") & (mep["asset_class"] == "BUILDING")]
    ep = rel.failure_episodes(nh)
    f7 = rel.repeat_flags(ep, 7)
    f30 = rel.repeat_flags(ep, REPEAT_DAYS)
    top = ep.groupby("asset_id").size().sort_values(ascending=False)
    out["no_heat_calls_per_building"] = {
        "orders": int(len(nh)), "episodes": int(len(ep)), "buildings": int(ep["asset_id"].nunique()),
        "repeat_within_7_days_share": float(f7.mean()), "repeat_within_30_days_share": float(f30.mean()),
        "share_of_episodes_in_top_10pct_buildings": float(top.iloc[:max(1, len(top) // 10)].sum() / top.sum())}
    write_json(RES / "maintenance_repeats.json", out)


def weibull_boilers(b_ep, win):
    bw = win[win["asset_class"] == "BOILER"]
    u = rel.uptime_intervals(b_ep, bw)
    f = wb.fit_weibull(u["t_days"].to_numpy(), u["failed"].to_numpy())
    per = u.groupby("asset_id").size()
    out = {"data": "uptime from the end of one boiler failure episode to the start of the next (failed) or to "
                   "the end of the observation window (censored), days; as-good-as-new after repair assumed",
           "intervals": int(len(u)), "boilers": int(u["asset_id"].nunique()),
           "selection": {"boilers_with_observation_window": int(len(bw)),
                         "boilers_with_at_least_one_episode": int(b_ep["asset_id"].nunique()),
                         "boilers_contributing_intervals": int(u["asset_id"].nunique()),
                         "max_intervals_one_boiler": int(per.max()),
                         "share_of_intervals_from_top_10pct_boilers": float(
                             per.sort_values(ascending=False).iloc[:max(1, len(per) // 10)].sum() / per.sum()),
                         "note": "only boilers with at least one failure episode in the window contribute (the interval "
                                 "before the first episode is not used), so boilers that never failed are absent"},
           "fit": f.as_dict(), "mean_uptime_days": wb.mean_life(f.beta, f.eta),
           "fit_cluster_bootstrap_by_boiler": wb.cluster_bootstrap(u["t_days"].to_numpy(), u["failed"].to_numpy(),
                                                                    u["asset_id"].to_numpy(), n_boot=N_BOOT, seed=0),
           "naive_drop_censored": wb.fit_weibull(u.loc[u["failed"], "t_days"].to_numpy(), None).as_dict()}
    # the same fit with quick re-calls (< 30 days, i.e. the repair did not hold) removed:
    # a conditional view of the boilers whose repair lasted at least 30 days
    long_ = u[u["t_days"] >= REPEAT_DAYS].copy()
    long_["t_days"] = long_["t_days"] - REPEAT_DAYS
    long_ = long_[long_["t_days"] > 0]
    g = wb.fit_weibull(long_["t_days"].to_numpy(), long_["failed"].to_numpy())
    out["conditional_on_surviving_30_days"] = {
        "intervals": int(len(long_)), "boilers": int(long_["asset_id"].nunique()), "fit": g.as_dict(),
        "fit_cluster_bootstrap_by_boiler": wb.cluster_bootstrap(long_["t_days"].to_numpy(), long_["failed"].to_numpy(),
                                                                 long_["asset_id"].to_numpy(), n_boot=N_BOOT, seed=0)}
    pm = []
    for name, fit in (("all_intervals", f), ("conditional_on_surviving_30_days", g)):
        for r in COST_RATIOS:
            o = wb.optimal_age_replacement(fit.beta, fit.eta, 1.0, r)
            pm.append({"fit": name, "cost_ratio": r, "finite_optimum": o["finite_optimum"],
                       "t_opt_days": o["t_opt"] if o["finite_optimum"] else None,
                       "saving_vs_run_to_failure": o["saving_vs_run_to_failure"]})
    out["age_replacement"] = {"cost_ratio_base_illustrative": COST_RATIO_BASE, "sweep": pm,
                              "source": "Barlow & Proschan (1965) via Nakagawa (1981) eq. 2.4-2.5"}
    out["minimal_repair_overhaul_interval_days_at_ratio_base"] = {
        name: (wb.optimal_minimal_repair_interval(fit.beta, fit.eta, COST_RATIO_BASE, 1.0)
               if fit.beta > 1 else None) for name, fit in (("all_intervals", f), ("conditional_on_surviving_30_days", g))}
    write_json(RES / "maintenance_weibull_boiler.json", out)
    return out


def main() -> int:
    t0 = time.time()
    w, a, labor, snap = load()
    canon = amps.to_canonical(w, a)
    end = canon["created_at"].max().normalize()
    lab = pd.Series(labor["labor_hours"].astype(float).to_numpy(), index=labor["boo_event"].astype(str))
    canon["labor_hours"] = canon["wo_id"].map(lab)
    checks = data_checks(w, a, canon, snap, end)
    print(f"canonical {len(canon)} rows ({time.time() - t0:.0f}s)", flush=True)
    model, abstain_thr = text_classification(canon)
    print(f"text classification done ({time.time() - t0:.0f}s)", flush=True)
    win, fail, ep, funnel = equipment(canon, a, lab, end, model, abstain_thr)
    checks["equipment_failure_funnel"] = funnel
    write_json(RES / "maintenance_data_checks.json", checks)
    b_ep = boiler_modes(fail, ep)
    mep = pareto_mep(canon, end)
    repeats(b_ep, mep)
    wbo = weibull_boilers(b_ep, win)
    print(json.dumps(wbo["fit"], indent=1))
    print(f"done ({time.time() - t0:.0f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
