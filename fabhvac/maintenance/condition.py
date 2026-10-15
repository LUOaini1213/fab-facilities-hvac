"""Targeted condition indicator: a fault-free regression residual of ONE signal, averaged
per day, with a one-sided threshold taken from out-of-fold fault-free training days.

Used in the 8D example (docs/8D_chiller_example.md) as the corrective action for a fault
that the generic detectors of Part C miss: a slow, persistent degradation (cooling-tower
fouling) is small in any single hour but does not average out over a day, whereas
hour-to-hour noise does.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import PolynomialFeatures, StandardScaler


def _model(alpha, degree):
    return make_pipeline(StandardScaler(), PolynomialFeatures(degree), Ridge(alpha=alpha))


def _xy(df, inputs, target):
    x = df[list(inputs)].to_numpy(dtype=float)
    y = df[target].to_numpy(dtype=float)
    ok = np.all(np.isfinite(x), axis=1) & np.isfinite(y)
    return x, y, ok


def daily_mean(values: np.ndarray, index: pd.DatetimeIndex, min_hours: int = 12) -> pd.Series:
    """Mean of hourly values per calendar day; days with fewer than `min_hours` finite values are dropped."""
    s = pd.Series(np.asarray(values, dtype=float), index=index)
    g = s.groupby(index.normalize())
    m, n = g.mean(), g.count()
    return m[n >= min_hours]


class ResidualIndicator:
    """score(day) = mean over the day's hours of (measured - predicted) `target`;
    alarm when score > threshold (one-sided: the degradation makes the signal larger)."""

    def __init__(self, target: str, inputs, alpha: float = 1.0, degree: int = 2,
                 quantile: float = 0.99, min_hours: int = 12):
        self.target = target
        self.inputs = list(inputs)
        self.alpha = alpha
        self.degree = degree
        self.quantile = quantile
        self.min_hours = min_hours

    def fit(self, normal: pd.DataFrame, groups: np.ndarray):
        """Fit on fault-free rows. The threshold is the `quantile` of daily scores computed
        from out-of-fold residuals (fold = `groups`, e.g. calendar month), so the training
        days are scored by a model that did not see them."""
        x, y, ok = _xy(normal, self.inputs, self.target)
        groups = np.asarray(groups)
        oof = np.full(y.shape, np.nan)
        for g in np.unique(groups):
            tr, te = ok & (groups != g), ok & (groups == g)
            m = _model(self.alpha, self.degree).fit(x[tr], y[tr])
            oof[te] = y[te] - m.predict(x[te])
        self.model_ = _model(self.alpha, self.degree).fit(x[ok], y[ok])
        self.oof_daily_ = daily_mean(oof, normal.index, self.min_hours)
        self.threshold_ = float(np.quantile(self.oof_daily_.to_numpy(), self.quantile))
        return self

    def hourly_residual(self, df: pd.DataFrame) -> np.ndarray:
        x, y, ok = _xy(df, self.inputs, self.target)
        r = np.full(y.shape, np.nan)
        r[ok] = y[ok] - self.model_.predict(x[ok])
        return r

    def daily_score(self, df: pd.DataFrame) -> pd.Series:
        return daily_mean(self.hourly_residual(df), df.index, self.min_hours)

    def alarms(self, df: pd.DataFrame) -> pd.Series:
        return self.daily_score(df) > self.threshold_
