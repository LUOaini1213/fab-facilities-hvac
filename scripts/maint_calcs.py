"""Part D (data-free): Weibull estimator self-check and PM-interval sensitivity.

Outputs (byte-identical on Windows and Linux; covered by tests/test_golden_results.py)
  results/maintenance_weibull_selfcheck.json   simulation study: censored MLE vs two naive fits
  results/maintenance_pm_sensitivity.csv       age-replacement optimum vs Weibull shape and cost ratio

Simulation design (fixed before running): true beta = 1.8, eta = 1000 days; 400 data sets of
40 units; each unit is observed from installation for a censoring time drawn uniformly from
300-1500 days (staggered entry, single end date), so about half the units are still running
at the end. Estimators:
  * censored MLE (fabhvac.maintenance.weibull.fit_weibull) -- the method used on real data;
  * "drop censored": fit only the failed units (a common spreadsheet shortcut);
  * "censored as failures": treat every observation end as a failure.
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fabhvac.maintenance import weibull as wb  # noqa: E402
from fabhvac.results_io import r, write_csv, write_json  # noqa: E402

RES = Path(os.environ.get("FABHVAC_RESULTS_DIR", ROOT / "results"))
# Estimates come from bisection with a 1e-12 tolerance; a last-bit difference in exp/log
# between C libraries could move the 10th digit, so solver outputs are written to 8.
SIG_SOLVER = 8
SEED = 20261002
BETA, ETA = 1.8, 1000.0
N_UNITS, N_SETS = 40, 400
C_LOW, C_HIGH = 300.0, 1500.0
SHAPES = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5]
RATIOS = [1.5, 2.0, 3.0, 5.0, 10.0, 20.0, 50.0]


def simulate():
    rng = np.random.default_rng(SEED)
    est = {"censored_mle": [], "drop_censored": [], "censored_as_failures": []}
    cover_b = cover_e = 0
    cens_frac = []
    lr_reject = 0
    for _ in range(N_SETS):
        u = rng.random(N_UNITS)
        life = ETA * (-np.log(u)) ** (1.0 / BETA)
        cens = C_LOW + (C_HIGH - C_LOW) * rng.random(N_UNITS)
        t = np.minimum(life, cens)
        failed = life <= cens
        cens_frac.append(1.0 - failed.mean())
        f = wb.fit_weibull(t, failed)
        est["censored_mle"].append((f.beta, f.eta))
        cover_b += f.beta_ci95[0] <= BETA <= f.beta_ci95[1]
        cover_e += f.eta_ci95[0] <= ETA <= f.eta_ci95[1]
        lr_reject += f.p_value_beta_eq_1 < 0.05
        g = wb.fit_weibull(t[failed], None)
        est["drop_censored"].append((g.beta, g.eta))
        h = wb.fit_weibull(t, None)
        est["censored_as_failures"].append((h.beta, h.eta))
    out = {"design": {"true_beta": BETA, "true_eta_days": ETA, "units_per_set": N_UNITS, "data_sets": N_SETS,
                      "censoring_time_days": [C_LOW, C_HIGH], "seed": SEED},
           "mean_censored_fraction": float(np.mean(cens_frac))}
    for k, v in est.items():
        a = np.array(v)
        b, e = a[:, 0], a[:, 1]
        # B10 life: age by which 10 % of units have failed
        b10 = e * (-math.log(0.9)) ** (1.0 / b)
        out[k] = {"beta_mean": float(b.mean()), "beta_median": float(np.median(b)),
                  "eta_mean": float(e.mean()), "eta_median": float(np.median(e)),
                  "beta_bias_pct": float((b.mean() / BETA - 1) * 100),
                  "eta_bias_pct": float((e.mean() / ETA - 1) * 100),
                  "b10_median_days": float(np.median(b10))}
    out["true_b10_days"] = ETA * (-math.log(0.9)) ** (1.0 / BETA)
    out["censored_mle"].update({"beta_ci95_coverage": cover_b / N_SETS, "eta_ci95_coverage": cover_e / N_SETS,
                                "lr_test_rejects_beta_eq_1_frac": lr_reject / N_SETS})
    return out


def sensitivity():
    rows = []
    for beta in SHAPES:
        for ratio in RATIOS:
            o = wb.optimal_age_replacement(beta, 1.0, 1.0, ratio)
            rows.append([beta, ratio, o["finite_optimum"],
                         o["t_opt_over_eta"] if o["finite_optimum"] else None,
                         o.get("prob_failure_before_t_opt"),
                         o["cost_rate_opt"] / o["cost_rate_run_to_failure"],
                         o["saving_vs_run_to_failure"]])
    return rows


def _round(obj):
    if isinstance(obj, dict):
        return {k: _round(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round(v) for v in obj]
    return r(obj, SIG_SOLVER) if isinstance(obj, float) else obj


def main() -> int:
    write_json(RES / "maintenance_weibull_selfcheck.json", _round(simulate()))
    write_csv(RES / "maintenance_pm_sensitivity.csv",
              ["beta", "cost_ratio_cf_over_cp", "finite_optimum", "t_opt_over_eta", "prob_failure_before_t_opt",
               "cost_rate_relative_to_run_to_failure", "saving_vs_run_to_failure"],
              [_round(row) for row in sensitivity()])
    return 0


if __name__ == "__main__":
    sys.exit(main())
