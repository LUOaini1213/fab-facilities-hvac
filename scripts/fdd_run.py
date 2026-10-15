"""Part C step 2: fault detection and diagnosis on the hourly cache built by fdd_prepare.py.

Evaluation protocol:
  * main split, time-blocked: odd calendar months train, even months test, 24 h buffer removed
    from the test side of every month boundary. Train and test months interleave, so they
    share seasons;
  * season-block check: train January-June / test July-December, and the reverse (24 h
    buffer at both ends of the test half-year), so that test weather is outside the
    training season;
  * baseline (fault-free regression residuals) is fitted on fault-free TRAIN rows only;
  * two detection operating points per method:
      deployable : threshold = 99th percentile of out-of-fold fault-free TRAIN scores
                   (folds = calendar months); realised false-alarm rate reported on test;
      far1       : threshold set so that 1 % of held-out fault-free TEST windows alarm
                   (an ROC operating point, used to compare methods at equal FAR);
  * diagnosis is reported for the plain classifier (argmax over 9 classes, no detection
    threshold) and two-stage at each operating point (below the detection threshold ->
    normal, otherwise the most likely fault), for both methods;
  * day level (main split): a day alarms when any of its hours alarms, at the deployable
    threshold and at the threshold that gives no false-alarm fault-free test day;
  * leave-one-severity-out (LOSO): for each fault type with >= 2 severities, each severity
    in turn is removed from training; recall and type-diagnosis on that unseen severity.

Outputs (results/): fdd_detection.csv, fdd_detection_by_type.csv, fdd_detection_daily.csv,
fdd_confusion_ml.csv, fdd_confusion_ml_deployable.csv, fdd_confusion_baseline.csv,
fdd_season_split.csv, fdd_loso.csv, fdd_energy.csv, fdd_summary.json
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fabhvac import chiller  # noqa: E402
from fabhvac.fdd.data import FAULT_TYPES, NORMAL  # noqa: E402
from fabhvac.fdd.models import (ResidualBaseline, alarm_rate, clean_matrix, confusion,  # noqa: E402
                                daily_max, diagnosis_metrics, fault_score, feature_columns,
                                make_classifier, month_split, season_split, threshold_at_far,
                                two_stage_labels)
from fabhvac.results_io import write_csv, write_json  # noqa: E402
from fabhvac.units import RT_TO_KW  # noqa: E402

RES = Path(os.environ.get("FABHVAC_RESULTS_DIR", ROOT / "results"))
CLASSES = [NORMAL] + sorted(FAULT_TYPES)
FAR = 0.01
METHODS = ("baseline", "ml")
POINTS = ("deployable", "far1")


def cache_dir() -> Path:
    c = os.environ.get("LBNL_FDD_CACHE")
    if c:
        return Path(c)
    d = os.environ.get("LBNL_FDD_DIR")
    if not d:
        sys.exit("set LBNL_FDD_CACHE (or LBNL_FDD_DIR) to the hourly cache from fdd_prepare.py")
    return Path(d) / "_cache"


def load() -> pd.DataFrame:
    parts = [pd.read_parquet(p) for p in sorted(cache_dir().glob("ChillerPlant*.parquet"))]
    df = pd.concat(parts)
    df["label"] = df["fault_type"]
    df["month"] = df.index.month
    return df


def ml_oof_normal_scores(df_tr, feats, groups):
    """Out-of-fold fault scores of fault-free training windows (folds = month pairs)."""
    scores = []
    ug = np.unique(groups)
    folds = [ug[i::3] for i in range(3)]
    for hold in folds:
        te = np.isin(groups, hold)
        clf = make_classifier().fit(clean_matrix(df_tr[~te], feats), df_tr["label"][~te])
        nm = te & (df_tr["label"].to_numpy() == NORMAL)
        scores.append(fault_score(clf, clean_matrix(df_tr[nm], feats)))
    return np.concatenate(scores)


def fit_and_score(tr: pd.DataFrame, te: pd.DataFrame, feats) -> dict:
    """Fit both detectors on `tr` and score `te`: scores, thresholds, predictions."""
    base = ResidualBaseline()
    ntr = tr[tr["label"] == NORMAL]
    base.fit(ntr, ntr["month"].to_numpy(), quantile=0.99)
    z_tr = base.zscores(tr)
    base.fit_signatures(z_tr, tr["label"].to_numpy(), threshold=base.threshold_)
    z_te = base.zscores(te)
    s_base = np.max(np.abs(z_te), axis=1)

    clf = make_classifier().fit(clean_matrix(tr, feats), tr["label"])
    x_te = clean_matrix(te, feats)
    proba = clf.predict_proba(x_te)
    s_ml = 1.0 - proba[:, list(clf.classes_).index(NORMAL)]
    pred_ml = np.asarray(clf.classes_, dtype=object)[np.argmax(proba, axis=1)]
    thr_ml_dep = float(np.quantile(ml_oof_normal_scores(tr, feats, tr["month"].to_numpy()), 0.99))

    is_norm = (te["label"] == NORMAL).to_numpy()
    thr = {"baseline": {"deployable": base.threshold_, "far1": threshold_at_far(s_base[is_norm], FAR)},
           "ml": {"deployable": thr_ml_dep, "far1": threshold_at_far(s_ml[is_norm], FAR)}}
    scores = {"baseline": s_base, "ml": s_ml}
    pred = {"ml_argmax": pred_ml}
    for k in POINTS:
        pred[f"ml_{k}"] = two_stage_labels(proba, clf.classes_, thr["ml"][k])
        pred[f"baseline_{k}"] = base.diagnose(z_te, threshold=thr["baseline"][k])
    return {"base": base, "z_tr": z_tr, "z_te": z_te, "clf": clf, "x_te": x_te, "is_norm": is_norm,
            "thr": thr, "scores": scores, "pred": pred,
            "realised_far": {m: {k: alarm_rate(scores[m][is_norm], v) for k, v in thr[m].items()} for m in thr}}


def by_type_rows(te: pd.DataFrame, ev: dict) -> list:
    rows = []
    for ft in CLASSES:
        sel = (te["label"] == ft).to_numpy()
        r = {"fault_type": ft, "n_test_windows": int(sel.sum())}
        for m in METHODS:
            for k in POINTS:
                r[f"{m}_{k}_alarm_rate"] = alarm_rate(ev["scores"][m][sel], ev["thr"][m][k])
        rows.append(r)
    return rows


def diagnosis_block(te: pd.DataFrame, ev: dict) -> dict:
    y = te["label"].to_numpy()
    return {name: diagnosis_metrics(y, p, CLASSES) for name, p in ev["pred"].items()}


def daily_rows(te: pd.DataFrame, ev: dict):
    """Day-level alarm rates per file (a day alarms if any hour alarms)."""
    days = {}
    for f in sorted(te["file"].unique()):
        sel = (te["file"] == f).to_numpy()
        days[f] = {m: daily_max(ev["scores"][m][sel], te.index[sel]) for m in METHODS}
    ff = [f for f in days if te.loc[te["file"] == f, "label"].iloc[0] == NORMAL]
    zero_fa = {m: float(days[ff[0]][m].max()) for m in METHODS}
    rows = []
    for f, d in days.items():
        g = te[te["file"] == f]
        r = {"file": f, "fault_type": g["fault_type"].iloc[0], "severity": g["severity"].iloc[0],
             "test_days": int(d["ml"].size)}
        for m in METHODS:
            r[f"{m}_deployable_alarm_days"] = int((d[m] > ev["thr"][m]["deployable"]).sum())
            r[f"{m}_zero_fa_test_alarm_days"] = int((d[m] > zero_fa[m]).sum())
        for m in METHODS:
            r[f"{m}_deployable_daily_alarm_rate"] = r[f"{m}_deployable_alarm_days"] / r["test_days"]
            r[f"{m}_zero_fa_test_daily_alarm_rate"] = r[f"{m}_zero_fa_test_alarm_days"] / r["test_days"]
        rows.append(r)
    return rows, zero_fa


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-loso", action="store_true",
                    help="skip the leave-one-severity-out runs (22 model fits); fdd_loso.csv is not written")
    ap.add_argument("--skip-season", action="store_true",
                    help="skip the two season-block splits; fdd_season_split.csv is not written")
    args = ap.parse_args()
    t0 = time.time()
    df = load()
    tr_mask, te_mask = month_split(df.index)
    tr, te = df[tr_mask], df[te_mask]
    feats = feature_columns(df)
    print(f"rows train {len(tr)} test {len(te)} features {len(feats)}", flush=True)

    ev = fit_and_score(tr, te, feats)
    base, z_tr, z_te, x_te = ev["base"], ev["z_tr"], ev["z_te"], ev["x_te"]
    thr, scores, is_norm_te = ev["thr"], ev["scores"], ev["is_norm"]
    s_base = scores["baseline"]
    print(f"models fitted ({time.time() - t0:.0f}s)", flush=True)

    # ---------------- detection per scenario and per fault type
    rows = []
    for f, g in te.groupby("file", sort=True):
        sel = (te["file"] == f).to_numpy()
        r = {"file": f, "fault_type": g["fault_type"].iloc[0], "severity": g["severity"].iloc[0], "n_test_windows": int(sel.sum())}
        for m in METHODS:
            for k in POINTS:
                r[f"{m}_{k}_alarm_rate"] = alarm_rate(scores[m][sel], thr[m][k])
        rows.append(r)
    det = pd.DataFrame(rows)
    write_csv(RES / "fdd_detection.csv", list(det.columns), det.itertuples(index=False))
    bt = pd.DataFrame(by_type_rows(te, ev))
    write_csv(RES / "fdd_detection_by_type.csv", list(bt.columns), bt.itertuples(index=False))
    dr, zero_fa = daily_rows(te, ev)
    dd = pd.DataFrame(dr)
    write_csv(RES / "fdd_detection_daily.csv", list(dd.columns), dd.itertuples(index=False))

    # ---------------- diagnosis (all test windows, 9 classes incl. normal)
    y_te = te["label"].to_numpy()
    cm = {"ml": confusion(y_te, ev["pred"]["ml_argmax"], CLASSES),
          "ml_deployable": confusion(y_te, ev["pred"]["ml_deployable"], CLASSES),
          "baseline": confusion(y_te, ev["pred"]["baseline_deployable"], CLASSES)}
    for m in cm:
        write_csv(RES / f"fdd_confusion_{m}.csv", ["true\\pred"] + CLASSES,
                  [[c] + list(cm[m][i]) for i, c in enumerate(CLASSES)])
    diag = diagnosis_block(te, ev)

    # ---------------- season-block splits (train one half-year, test the other)
    season_rows, season_summary = [], {}
    splits = () if args.skip_season else (("train_jan_jun_test_jul_dec", True), ("train_jul_dec_test_jan_jun", False))
    for name, first in splits:
        s_tr, s_te = season_split(df.index, train_first_half=first)
        tr_s, te_s = df[s_tr], df[s_te]
        ev_s = fit_and_score(tr_s, te_s, feats)
        for r in by_type_rows(te_s, ev_s):
            season_rows.append({"split": name, **r})
        season_summary[name] = {"n_train_windows": int(len(tr_s)), "n_test_windows": int(len(te_s)),
                                "thresholds": ev_s["thr"], "realised_false_alarm_rate_on_test_normal": ev_s["realised_far"],
                                "diagnosis": diagnosis_block(te_s, ev_s)}
        print(f"season split {name} ({time.time() - t0:.0f}s)", flush=True)
    if season_rows:
        se = pd.DataFrame(season_rows)
        write_csv(RES / "fdd_season_split.csv", list(se.columns), se.itertuples(index=False))

    # ---------------- leave-one-severity-out
    loso = []
    multi = tr.groupby("fault_type")["severity"].nunique()
    for ft in ([] if args.skip_loso else sorted(multi[multi >= 2].index)):
        for sev in sorted(tr.loc[tr["fault_type"] == ft, "severity"].unique()):
            held = (df["fault_type"] == ft) & (df["severity"] == sev)
            tr_l = tr[~held[tr_mask].to_numpy()]
            te_sel = held[te_mask].to_numpy()
            clf_l = make_classifier().fit(clean_matrix(tr_l, feats), tr_l["label"])
            s_norm = fault_score(clf_l, x_te[is_norm_te])
            s_held = fault_score(clf_l, x_te[te_sel])
            p_held = clf_l.predict(x_te[te_sel])
            base_l = ResidualBaseline()
            base_l.models_, base_l.center_, base_l.scale_ = base.models_, base.center_, base.scale_
            base_l.fit_signatures(z_tr[~held[tr_mask].to_numpy()], tr_l["label"].to_numpy(),
                                  threshold=base.threshold_)
            pb = base_l.diagnose(z_te[te_sel], threshold=base.threshold_)
            t_ml = threshold_at_far(s_norm, FAR)
            det_ml = s_held > t_ml
            det_b = s_base[te_sel] > thr["baseline"]["far1"]
            loso.append({"fault_type": ft, "held_out_severity": sev, "n_test_windows": int(te_sel.sum()),
                         "ml_recall_far1": float(det_ml.mean()),
                         "ml_type_accuracy_all": float(np.mean(p_held == ft)),
                         "ml_type_accuracy_detected": float(np.mean(p_held[det_ml] == ft)) if det_ml.any() else None,
                         "ml_predicted_normal_frac": float(np.mean(p_held == NORMAL)),
                         "baseline_recall_far1": float(det_b.mean()),
                         "baseline_type_accuracy_all": float(np.mean(pb == ft)),
                         "baseline_type_accuracy_detected": float(np.mean(pb[det_b] == ft)) if det_b.any() else None})
            print(f"LOSO {ft} {sev} ({time.time() - t0:.0f}s)", flush=True)
    if loso:
        lo = pd.DataFrame(loso)
        write_csv(RES / "fdd_loso.csv", list(lo.columns), lo.itertuples(index=False))

    # ---------------- energy effect of each fault
    # The simulated plant is pump-dominated (see fault_free_energy_split), so a relative kW/RT
    # change is NOT transferred onto a real plant here; the component columns show where each
    # fault's energy change comes from, as a share of fault-free plant energy.
    sc = pd.read_csv(RES / "fdd_scenarios.csv")
    ff = sc[sc["fault_type"] == NORMAL].iloc[0]
    chws_ff = float(ff["load_weighted_chws_c"])
    limit_ff = chiller.mees_limit_kwe_per_kwc(chws_ff)
    plant_ff = float(ff["plant_kwh"])
    mech = df.groupby("file").agg(sec_pump2_on_frac=("CWL_SEC_PM_STA_2", "mean"),
                                  mean_chillers_on=("n_chillers_on", "mean"),
                                  mean_chw_supply_c=("chw_supply_c", "mean"))
    energy = []
    for _, r in sc.iterrows():
        energy.append({"file": r["file"], "fault_type": r["fault_type"], "severity": r["severity"],
                       "plant_kwh_delta_pct": r["plant_kwh_delta_pct"],
                       "chiller_kwh_delta_pct_of_plant": (r["chiller_kwh"] - ff["chiller_kwh"]) / plant_ff * 100,
                       "pump_kwh_delta_pct_of_plant": (r["pump_kwh"] - ff["pump_kwh"]) / plant_ff * 100,
                       "tower_kwh_delta_pct_of_plant": (r["tower_kwh"] - ff["tower_kwh"]) / plant_ff * 100,
                       "delivered_cooling_delta_pct": r["delivered_cooling_delta_pct"],
                       "kw_per_rt_delivered": r["kw_per_rt_delivered"],
                       "kwe_per_kwc_delivered": r["kw_per_rt_delivered"] / RT_TO_KW,
                       "kw_per_rt_delivered_delta_pct": float(r["kw_per_rt_delivered_delta_pct"]),
                       "hours_chws_above_spt_1k_frac": r["hours_chws_above_spt_1k_frac"],
                       "sec_pump2_on_frac": mech.loc[r["file"], "sec_pump2_on_frac"],
                       "mean_chillers_on": mech.loc[r["file"], "mean_chillers_on"],
                       "hb_fraction_within_5pct": r["hb_fraction_within_5pct"],
                       "hb_median_pct": r["hb_median_pct"]})
    en = pd.DataFrame(energy)
    write_csv(RES / "fdd_energy.csv", list(en.columns), en.itertuples(index=False))

    summary = {
        "split": "train = odd months, test = even months, 24 h boundary buffer on test",
        "window": "1 hour", "n_train_windows": int(len(tr)), "n_test_windows": int(len(te)),
        "n_features_ml": len(feats), "residual_targets": base.targets, "exogenous_inputs": base.exogenous,
        "thresholds": thr, "realised_false_alarm_rate_on_test_normal": ev["realised_far"],
        "diagnosis": diag,
        "diagnosis_note": "ml_argmax: 9-class argmax, no detection threshold; <method>_<point>: two-stage, "
                          "normal below the detection threshold of that operating point, otherwise the most "
                          "likely fault (ml) or the nearest fault signature (baseline)",
        "daily": {"rule": "a test day alarms when any of its hours alarms",
                  "zero_fa_test_threshold": zero_fa,
                  "zero_fa_test_threshold_rule": "largest daily score on fault-free test days (comparison only)"},
        "season_block_splits": season_summary,
        "fault_free_plant": {"kw_per_rt_delivered": float(ff["kw_per_rt_delivered"]),
                             "kwe_per_kwc_delivered": float(ff["kw_per_rt_delivered"]) / RT_TO_KW,
                             "load_weighted_chws_c": chws_ff,
                             "mees_limit_kwe_per_kwc_at_that_chws": limit_ff,
                             "ratio_to_mees_limit": float(ff["kw_per_rt_delivered"]) / RT_TO_KW / limit_ff},
        "fault_free_energy_split": {"plant_kwh": plant_ff,
                                    "chiller_share": float(ff["chiller_kwh"]) / plant_ff,
                                    "pumps_share_chw_and_cdw": float(ff["pump_kwh"]) / plant_ff,
                                    "towers_share": float(ff["tower_kwh"]) / plant_ff},
    }
    write_json(RES / "fdd_summary.json", summary)
    print(f"done ({time.time() - t0:.0f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
