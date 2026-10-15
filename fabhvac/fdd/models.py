"""Fault detection and diagnosis models and time-blocked evaluation helpers.

Baseline ("physics residuals"): fault-free regression models predict physically meaningful
indicators (plant power, tower approach, chilled-water supply error, ...) from exogenous
operating conditions; each residual is scaled by its own 99th-percentile absolute deviation
in out-of-fold fault-free training data ("tail" scale; the first version used MAD scaling,
which let heavy-tailed residuals dominate max|z|). Detection statistic = max |z|;
diagnosis = below the detection threshold -> normal, otherwise the nearest fault signature
(median z-vector of the alarming training windows of each fault class).

ML: sklearn HistGradientBoostingClassifier on all hourly features (multi-class incl. normal).
Detection score = 1 - P(normal).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import PolynomialFeatures, StandardScaler

from .data import NORMAL

EXOGENOUS = ["t_db_c", "t_wb_c", "sec_load_kw", "chw_spt_c", "n_chillers_on"]
RESIDUAL_TARGETS = ["plant_kw", "chiller_kw", "chiller1_cop", "ct1_approach_k", "ct1_minus_spt_k",
                    "cdw_supply_minus_ct1_k", "chl1_sw_minus_pri_sw_k", "chw_supply_err_k", "chl1_lift_k",
                    "heat_balance_pct", "sec_dp_err_pct", "twv_ctrl", "ct1_fan_spd", "sec_pump_spd",
                    "CT_FAN_SPD_1__std", "TWV_CTRL__std"]
NON_FEATURES = {"file", "fault_type", "severity", "n_minutes", "month", "label"}


# ---------------------------------------------------------------- splits

def month_split(index: pd.DatetimeIndex, buffer_hours: int = 24):
    """Odd months -> train, even months -> test. Test rows within `buffer_hours` of a
    month boundary are dropped so no test window sits next to a training window."""
    month = index.month
    train = (month % 2 == 1)
    test = ~train
    start = index.to_period("M").to_timestamp()
    hrs_from_start = (index - start) / pd.Timedelta(hours=1)
    days_in_month = index.days_in_month
    hrs_to_end = days_in_month * 24 - hrs_from_start - 1
    near = (hrs_from_start < buffer_hours) | (hrs_to_end < buffer_hours)
    test = test & ~near
    return np.asarray(train), np.asarray(test)


def season_split(index: pd.DatetimeIndex, train_first_half: bool = True, buffer_hours: int = 24):
    """Season-block split: January-June vs July-December of the simulated year.
    train_first_half=True trains on Jan-Jun and tests on Jul-Dec; False is the reverse.
    Test rows within `buffer_hours` of either end of the test half-year are dropped (the
    1 July boundary touches the training half; 1 January / 31 December touch it when the
    weather year is read as cyclic)."""
    month = np.asarray(index.month)
    first = month <= 6
    train = first if train_first_half else ~first
    test = ~train
    year_start = index.to_period("Y").to_timestamp()
    july = year_start + pd.DateOffset(months=6)
    next_year = year_start + pd.DateOffset(years=1)
    half_start = np.where(first, year_start.to_numpy(), july.to_numpy())
    half_end = np.where(first, july.to_numpy(), next_year.to_numpy())
    t = index.to_numpy()
    hrs_from_start = (t - half_start) / np.timedelta64(1, "h")
    hrs_to_end = (half_end - t) / np.timedelta64(1, "h") - 1
    near = (hrs_from_start < buffer_hours) | (hrs_to_end < buffer_hours)
    return np.asarray(train), np.asarray(test & ~near)


def clean_matrix(df: pd.DataFrame, cols) -> np.ndarray:
    x = np.array(df[list(cols)].to_numpy(dtype=float), copy=True)
    x[~np.isfinite(x)] = np.nan
    return x


def feature_columns(df: pd.DataFrame):
    return [c for c in df.columns if c not in NON_FEATURES and pd.api.types.is_numeric_dtype(df[c])]


# ---------------------------------------------------------------- baseline

class ResidualBaseline:
    """Fault-free regression residuals -> robust z-scores -> max|z| detection."""

    def __init__(self, targets=None, exogenous=None, alpha: float = 1.0, degree: int = 2,
                 scale: str = "tail", tail_q: float = 0.99):
        if scale not in ("tail", "mad"):
            raise ValueError("scale must be 'tail' or 'mad'")
        self.scale = scale
        self.tail_q = tail_q
        self.targets = list(targets or RESIDUAL_TARGETS)
        self.exogenous = list(exogenous or EXOGENOUS)
        self.alpha = alpha
        self.degree = degree

    def _model(self):
        return make_pipeline(StandardScaler(), PolynomialFeatures(self.degree), Ridge(alpha=self.alpha))

    def _fit_models(self, x, y):
        models = []
        for j in range(y.shape[1]):
            ok = np.isfinite(y[:, j]) & np.all(np.isfinite(x), axis=1)
            m = self._model()
            m.fit(x[ok], y[ok, j])
            models.append(m)
        return models

    @staticmethod
    def _predict(models, x):
        x = np.where(np.isfinite(x), x, 0.0)
        return np.column_stack([m.predict(x) for m in models])

    def fit(self, normal_df: pd.DataFrame, groups: np.ndarray, quantile: float = 0.99):
        """Fit on fault-free rows; robust scale and threshold from out-of-fold residuals
        (folds = `groups`, e.g. calendar month)."""
        x = clean_matrix(normal_df, self.exogenous)
        y = clean_matrix(normal_df, self.targets)
        oof = np.full_like(y, np.nan)
        for g in np.unique(groups):
            tr, te = groups != g, groups == g
            oof[te] = y[te] - self._predict(self._fit_models(x[tr], y[tr]), x[te])
        self.center_ = np.nanmedian(oof, axis=0)
        dev = np.abs(oof - self.center_)
        if self.scale == "mad":
            sc = np.nanmedian(dev, axis=0) * 1.4826
        else:  # tail scale: residual j is in units of its own fault-free 99th-percentile deviation
            sc = np.nanquantile(dev, self.tail_q, axis=0)
        self.scale_ = np.where(sc > 1e-9, sc, np.nanstd(oof, axis=0) + 1e-9)
        self.models_ = self._fit_models(x, y)
        self.threshold_ = float(np.quantile(self.statistic_from_residuals(oof), quantile))
        return self

    def zscores(self, df: pd.DataFrame) -> np.ndarray:
        x = clean_matrix(df, self.exogenous)
        y = clean_matrix(df, self.targets)
        r = y - self._predict(self.models_, x)
        return self._z(r)

    def _z(self, r):
        z = (r - self.center_) / self.scale_
        return np.where(np.isfinite(z), z, 0.0)

    def statistic_from_residuals(self, r):
        return np.max(np.abs(self._z(r)), axis=1)

    def statistic(self, df: pd.DataFrame) -> np.ndarray:
        return np.max(np.abs(self.zscores(df)), axis=1)

    def fit_signatures(self, z: np.ndarray, labels: np.ndarray, threshold: float | None = None):
        """Median z-vector per class. With a threshold, fault-class signatures use only the
        training windows that alarm (what the fault looks like when it is visible); classes
        with no alarming window fall back to all their windows."""
        labels = np.asarray(labels)
        self.classes_ = np.array(sorted(set(labels)))
        alarm = np.max(np.abs(z), axis=1) > threshold if threshold is not None else np.ones(len(z), bool)
        sigs = []
        for c in self.classes_:
            sel = labels == c
            if c != NORMAL and threshold is not None and np.any(sel & alarm):
                sel = sel & alarm
            sigs.append(np.median(z[sel], axis=0))
        self.signatures_ = np.vstack(sigs)
        return self

    def diagnose(self, z: np.ndarray, threshold: float | None = None) -> np.ndarray:
        """Two-stage rule: max|z| <= threshold -> NORMAL; otherwise the nearest FAULT signature.
        With threshold=None every window is assigned to the nearest signature (incl. normal)."""
        zc = np.clip(z, -50, 50)  # keep one exploding residual from dominating the distance
        sig = np.clip(self.signatures_, -50, 50)
        d = ((zc[:, None, :] - sig[None, :, :]) ** 2).sum(axis=2)
        if threshold is None:
            return self.classes_[np.argmin(d, axis=1)]
        faults = self.classes_ != NORMAL
        pred = self.classes_[faults][np.argmin(d[:, faults], axis=1)]
        return np.where(np.max(np.abs(z), axis=1) > threshold, pred, NORMAL)


# ---------------------------------------------------------------- ML

def make_classifier(seed: int = 0) -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(max_iter=200, learning_rate=0.1, max_leaf_nodes=31,
                                          class_weight="balanced", early_stopping=False,
                                          random_state=seed)


def fault_score(clf, x) -> np.ndarray:
    proba = clf.predict_proba(x)
    idx = list(clf.classes_).index(NORMAL)
    return 1.0 - proba[:, idx]


def two_stage_labels(proba: np.ndarray, classes, threshold: float) -> np.ndarray:
    """Diagnosis with a detection threshold, as for the residual baseline: fault score
    1 - P(normal) <= threshold -> NORMAL; otherwise the most probable FAULT class."""
    classes = np.asarray(classes, dtype=object)
    proba = np.asarray(proba, dtype=float)
    k = list(classes).index(NORMAL)
    score = 1.0 - proba[:, k]
    fault = np.flatnonzero(classes != NORMAL)
    best = classes[fault][np.argmax(proba[:, fault], axis=1)]
    return np.where(score > threshold, best, NORMAL).astype(object)


def diagnosis_metrics(y_true, y_pred, classes) -> dict:
    """9-class accuracy and macro-F1, recall of the normal class (fault-free windows left
    as normal), and the share of faulted windows given their true fault type."""
    y_true = np.asarray(y_true, dtype=object)
    y_pred = np.asarray(y_pred, dtype=object)
    cm = confusion(y_true, y_pred, classes)
    norm = y_true == NORMAL
    return {"accuracy_9class": float(np.trace(cm) / cm.sum()),
            "macro_f1_9class": macro_f1(cm),
            "normal_recall": float(np.mean(y_pred[norm] == NORMAL)) if norm.any() else None,
            "fault_windows_correct_type": float(np.mean(y_pred[~norm] == y_true[~norm])) if (~norm).any() else None}


def daily_max(scores: np.ndarray, index: pd.DatetimeIndex) -> pd.Series:
    """Largest hourly score per calendar day: a day alarms when any of its hours alarms."""
    s = pd.Series(np.asarray(scores, dtype=float), index=index)
    return s.groupby(index.normalize()).max()


# ---------------------------------------------------------------- metrics

def threshold_at_far(normal_scores: np.ndarray, far: float) -> float:
    """Smallest threshold such that the share of normal scores strictly above it is <= far."""
    s = np.sort(np.asarray(normal_scores, dtype=float))
    n = s.size
    k = int(np.floor(far * n))          # number of normal windows allowed to alarm
    if k <= 0:
        return float(s[-1])
    return float(s[n - k - 1])


def alarm_rate(scores: np.ndarray, threshold: float) -> float:
    return float(np.mean(np.asarray(scores) > threshold))


def confusion(y_true, y_pred, classes):
    idx = {c: i for i, c in enumerate(classes)}
    m = np.zeros((len(classes), len(classes)), dtype=int)
    for t, p in zip(y_true, y_pred):
        m[idx[t], idx[p]] += 1
    return m


def macro_f1(cm: np.ndarray) -> float:
    tp = np.diag(cm).astype(float)
    prec = np.divide(tp, cm.sum(axis=0), out=np.zeros_like(tp), where=cm.sum(axis=0) > 0)
    rec = np.divide(tp, cm.sum(axis=1), out=np.zeros_like(tp), where=cm.sum(axis=1) > 0)
    f1 = np.divide(2 * prec * rec, prec + rec, out=np.zeros_like(tp), where=(prec + rec) > 0)
    present = cm.sum(axis=1) > 0
    return float(f1[present].mean())
