"""Two-parameter Weibull life model: maximum-likelihood fit with right censoring, and
preventive-maintenance interval optimisation.

Likelihood (right-censored data, t_i > 0, d_i = 1 for a failure, 0 for a censored unit):

    log L(beta, eta) = sum_i d_i [ln beta - beta ln eta + (beta - 1) ln t_i] - sum_i (t_i / eta)^beta

Censored units contribute only their survival term exp(-(t/eta)^beta); they are neither
dropped nor counted as failures. For fixed beta the MLE of eta is closed-form,
eta^beta = sum_i t_i^beta / r (r = number of failures), and beta solves the profile score

    g(beta) = sum t^beta ln t / sum t^beta - 1/beta - (1/r) sum_{failures} ln t = 0,

which is strictly increasing in beta, so bisection on ln beta always converges.

Age-replacement policy (replace at age T or at failure, whichever first), long-run cost
rate (Barlow and Proschan 1965, p. 85, as given in Nakagawa 1981, eq. 2.4):

    C(T) = [c_f F(T) + c_p R(T)] / integral_0^T R(t) dt

and the optimum T* solves (Nakagawa 1981, eq. 2.5)

    h(T) integral_0^T R(t) dt - F(T) = c_p / (c_f - c_p),

which has a finite solution only for an increasing hazard (beta > 1) and c_f > c_p.

Periodic overhaul with minimal repair between overhauls (Barlow and Proschan 1965, p. 96,
as given in Nakagawa 1981, eq. 2.1): G(T) = [c_mr H(T) + c_ov] / T with H the cumulative
hazard; for a Weibull hazard the optimum is T* = eta (c_ov / (c_mr (beta - 1)))^(1/beta).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

_GL_X, _GL_W = np.polynomial.legendre.leggauss(16)


@dataclass(frozen=True)
class WeibullFit:
    beta: float
    eta: float
    n: int
    failures: int
    loglik: float
    se_beta: float
    se_eta: float
    beta_ci95: tuple
    eta_ci95: tuple
    loglik_exponential: float
    lr_stat_beta_eq_1: float
    p_value_beta_eq_1: float

    def as_dict(self) -> dict:
        return {"beta": self.beta, "eta": self.eta, "n": self.n, "failures": self.failures,
                "censored": self.n - self.failures, "loglik": self.loglik,
                "se_beta": self.se_beta, "se_eta": self.se_eta,
                "beta_ci95": list(self.beta_ci95), "eta_ci95": list(self.eta_ci95),
                "loglik_exponential": self.loglik_exponential,
                "lr_stat_beta_eq_1": self.lr_stat_beta_eq_1, "p_value_beta_eq_1": self.p_value_beta_eq_1}


def _check(t, failed):
    t = np.asarray(t, dtype=float)
    d = np.asarray(failed, dtype=bool) if failed is not None else np.ones(t.shape, bool)
    if t.ndim != 1 or t.shape != d.shape:
        raise ValueError("times and failure flags must be 1-D arrays of equal length")
    if t.size == 0 or not np.all(np.isfinite(t)) or np.any(t <= 0):
        raise ValueError("times must be finite and > 0")
    if d.sum() < 2:
        raise ValueError("need at least two failures to fit a Weibull distribution")
    return t, d


def loglik(beta: float, eta: float, t, failed=None) -> float:
    """Right-censored Weibull log-likelihood."""
    t = np.asarray(t, dtype=float)
    d = np.asarray(failed, dtype=bool) if failed is not None else np.ones(t.shape, bool)
    z = t / eta
    return float(np.sum(d * (math.log(beta) - math.log(eta) + (beta - 1.0) * np.log(z)))
                 - np.sum(z ** beta))


def _profile_score(beta, lt, d):
    """g(beta) on log-times lt (already centred)."""
    w = np.exp(beta * (lt - lt.max()))      # stable: largest weight is 1
    return float(np.sum(w * lt) / np.sum(w) - 1.0 / beta - np.mean(lt[d]))


def _eta_given_beta(beta, lt, d, shift):
    r = int(d.sum())
    m = lt.max()
    # eta^beta = sum t^beta / r, evaluated in logs: ln eta = (m + ln(sum exp(beta (lt - m))) / beta - ln r / beta) + shift
    return math.exp(m + (math.log(np.sum(np.exp(beta * (lt - m)))) - math.log(r)) / beta + shift)


def fit_weibull(t, failed=None, tol: float = 1e-12) -> WeibullFit:
    """MLE of (beta, eta) with right censoring; Wald CIs from the observed information
    (beta and eta on the log scale); likelihood-ratio test of beta = 1 (exponential)."""
    t, d = _check(t, failed)
    if np.unique(t[d]).size < 2:
        raise ValueError("failure times are all equal; shape is not identifiable")
    lt_raw = np.log(t)
    shift = float(np.mean(lt_raw))
    lt = lt_raw - shift                       # scale-free: fit on t / geometric mean
    lo, hi = math.log(1e-3), math.log(1e3)
    if _profile_score(math.exp(lo), lt, d) > 0 or _profile_score(math.exp(hi), lt, d) < 0:
        raise ValueError("shape parameter outside [1e-3, 1e3]")
    for _ in range(200):                      # bisection on ln beta
        mid = 0.5 * (lo + hi)
        if _profile_score(math.exp(mid), lt, d) > 0:
            hi = mid
        else:
            lo = mid
        if hi - lo < tol:
            break
    beta = math.exp(0.5 * (lo + hi))
    eta = _eta_given_beta(beta, lt, d, shift)

    # observed information in (beta, u = ln eta)
    r = int(d.sum())
    u = math.log(eta)
    x = lt_raw - u
    w = np.exp(beta * x)
    h_bb = -r / beta ** 2 - float(np.sum(w * x * x))
    h_uu = -beta ** 2 * float(np.sum(w))
    h_bu = -r + float(np.sum(w)) + beta * float(np.sum(w * x))
    info = -np.array([[h_bb, h_bu], [h_bu, h_uu]])
    cov = np.linalg.inv(info)
    se_b = math.sqrt(max(cov[0, 0], 0.0))
    se_u = math.sqrt(max(cov[1, 1], 0.0))
    zq = 1.959963984540054
    b_ci = (beta * math.exp(-zq * se_b / beta), beta * math.exp(zq * se_b / beta))
    e_ci = (eta * math.exp(-zq * se_u), eta * math.exp(zq * se_u))

    ll = loglik(beta, eta, t, d)
    eta_exp = float(np.sum(t)) / r
    ll_exp = loglik(1.0, eta_exp, t, d)
    lr = max(2.0 * (ll - ll_exp), 0.0)
    p = math.erfc(math.sqrt(lr / 2.0))        # chi-square, 1 degree of freedom
    return WeibullFit(beta, eta, int(t.size), r, ll, se_b, eta * se_u, b_ci, e_ci, ll_exp, lr, p)


def cluster_bootstrap(t, failed, clusters, n_boot: int = 2000, seed: int = 0, level: float = 0.95) -> dict:
    """Percentile bootstrap CI for (beta, eta) that resamples whole clusters (e.g. assets)
    with replacement, so that several intervals from one asset are not treated as
    independent. Resamples that cannot be fitted (fewer than two distinct failure times) are
    counted and skipped."""
    t = np.asarray(t, dtype=float)
    d = np.asarray(failed, dtype=bool)
    c = np.asarray(clusters)
    if not (t.shape == d.shape == c.shape):
        raise ValueError("times, failure flags and clusters must have equal length")
    ids, inv = np.unique(c, return_inverse=True)
    members = [np.flatnonzero(inv == k) for k in range(ids.size)]
    rng = np.random.default_rng(seed)
    betas, etas, failed_fits = [], [], 0
    for _ in range(n_boot):
        pick = rng.integers(0, ids.size, ids.size)
        idx = np.concatenate([members[k] for k in pick])
        try:
            f = fit_weibull(t[idx], d[idx])
        except ValueError:
            failed_fits += 1
            continue
        betas.append(f.beta)
        etas.append(f.eta)
    if not betas:
        raise ValueError("no bootstrap resample could be fitted")
    a = (1.0 - level) / 2.0
    q = [a, 1.0 - a]
    return {"clusters": int(ids.size), "n_boot": int(n_boot), "seed": int(seed), "unfitted_resamples": failed_fits,
            "beta_ci": [float(v) for v in np.quantile(betas, q)], "eta_ci": [float(v) for v in np.quantile(etas, q)]}


def fit_weibull_fixed_beta(t, failed, beta: float) -> float:
    """MLE of eta for a known shape (beta = 1 gives the exponential total-time-on-test estimate)."""
    t, d = _check(t, failed)
    return float((np.sum(t ** beta) / d.sum()) ** (1.0 / beta))


# ---------------------------------------------------------------- life functions

def reliability(t, beta: float, eta: float):
    return np.exp(-(np.asarray(t, dtype=float) / eta) ** beta)


def hazard(t, beta: float, eta: float):
    t = np.asarray(t, dtype=float)
    return beta / eta * (t / eta) ** (beta - 1.0)


def mean_life(beta: float, eta: float) -> float:
    return eta * math.gamma(1.0 + 1.0 / beta)


def integral_reliability(T: float, beta: float, eta: float, panels: int = 64) -> float:
    """integral_0^T R(t) dt by composite 16-point Gauss-Legendre (exact to ~1e-14 here)."""
    if T <= 0:
        return 0.0
    edges = np.linspace(0.0, T, panels + 1)
    a, b = edges[:-1, None], edges[1:, None]
    x = 0.5 * (b - a) * _GL_X[None, :] + 0.5 * (a + b)
    return float(np.sum(0.5 * (b - a) * _GL_W[None, :] * reliability(x, beta, eta)))


# ---------------------------------------------------------------- age replacement

def age_replacement_cost_rate(T: float, beta: float, eta: float, c_p: float, c_f: float) -> float:
    """Long-run expected cost per unit time when replacing at age T or at failure."""
    if T == math.inf:
        return c_f / mean_life(beta, eta)
    R = float(reliability(T, beta, eta))
    return (c_f * (1.0 - R) + c_p * R) / integral_reliability(T, beta, eta)


def optimal_age_replacement(beta: float, eta: float, c_p: float, c_f: float, t_max_over_eta: float = 50.0) -> dict:
    """Minimise C(T). Returns T* (inf when no finite optimum), C(T*), C(inf) = c_f / MTTF and the
    saving relative to run-to-failure. Solves Nakagawa (1981) eq. 2.5 by bisection."""
    if not (c_p > 0 and c_f > 0):
        raise ValueError("costs must be positive")
    run_to_failure = c_f / mean_life(beta, eta)
    out = {"beta": beta, "eta": eta, "c_p": c_p, "c_f": c_f, "cost_ratio": c_f / c_p,
           "cost_rate_run_to_failure": run_to_failure}
    if beta <= 1.0 or c_f <= c_p:
        out.update({"t_opt": math.inf, "t_opt_over_eta": math.inf, "cost_rate_opt": run_to_failure,
                    "saving_vs_run_to_failure": 0.0, "finite_optimum": False})
        return out
    target = c_p / (c_f - c_p)

    def lhs(T):
        return float(hazard(T, beta, eta)) * integral_reliability(T, beta, eta) - (1.0 - float(reliability(T, beta, eta)))

    lo, hi = 0.0, t_max_over_eta * eta
    if lhs(hi) < target:     # optimum beyond the search range: practically run-to-failure
        out.update({"t_opt": math.inf, "t_opt_over_eta": math.inf, "cost_rate_opt": run_to_failure,
                    "saving_vs_run_to_failure": 0.0, "finite_optimum": False})
        return out
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if lhs(mid) < target:
            lo = mid
        else:
            hi = mid
        if hi - lo <= 1e-12 * eta:
            break
    T = 0.5 * (lo + hi)
    c = age_replacement_cost_rate(T, beta, eta, c_p, c_f)
    out.update({"t_opt": T, "t_opt_over_eta": T / eta, "cost_rate_opt": c,
                "saving_vs_run_to_failure": 1.0 - c / run_to_failure, "finite_optimum": True,
                "prob_failure_before_t_opt": 1.0 - float(reliability(T, beta, eta))})
    return out


# ---------------------------------------------------------------- periodic overhaul, minimal repair

def minimal_repair_cost_rate(T: float, beta: float, eta: float, c_overhaul: float, c_repair: float) -> float:
    return (c_repair * (T / eta) ** beta + c_overhaul) / T


def optimal_minimal_repair_interval(beta: float, eta: float, c_overhaul: float, c_repair: float) -> float:
    """T* = eta (c_ov / (c_mr (beta - 1)))^(1/beta); inf when beta <= 1."""
    if beta <= 1.0:
        return math.inf
    return eta * (c_overhaul / (c_repair * (beta - 1.0))) ** (1.0 / beta)
