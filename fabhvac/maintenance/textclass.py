"""Classify free-text work-order descriptions into failure-mode codes.

* `RuleClassifier`: ordered keyword/regex rules, first match wins, otherwise ABSTAIN.
* `make_text_model`: TF-IDF (word 1-2-grams + character 3-5-grams) and multinomial
  logistic regression with balanced class weights.
* Evaluation helpers: a time-ordered split (train / validation / test by date), and the
  "unseen text" subset of a test set (normalised description never seen in training),
  because CMMS text repeats templates and exact repeats inflate scores.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

ABSTAIN = "(none)"
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalise(text) -> str:
    """Lower case, every run of non-alphanumerics -> one space, trimmed."""
    if text is None or (isinstance(text, float) and np.isnan(text)):
        return ""
    return _NON_ALNUM.sub(" ", str(text).lower()).strip()


class RuleClassifier:
    """rules: list of (label, regex) applied to the normalised text in order."""

    def __init__(self, rules):
        self.rules = [(lab, re.compile(p)) for lab, p in rules]

    def predict_one(self, text: str) -> str:
        t = normalise(text)
        for lab, rx in self.rules:
            if rx.search(t):
                return lab
        return ABSTAIN

    def predict(self, texts) -> np.ndarray:
        return np.array([self.predict_one(t) for t in texts], dtype=object)


def make_text_model(C: float = 1.0, seed: int = 0):
    """C is fixed at 1 (scripts/maint_run.py does not search over C)."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline, make_union

    feats = make_union(
        TfidfVectorizer(preprocessor=normalise, ngram_range=(1, 2), min_df=2, sublinear_tf=True),
        TfidfVectorizer(preprocessor=normalise, analyzer="char_wb", ngram_range=(3, 5), min_df=3, sublinear_tf=True))
    clf = LogisticRegression(C=C, class_weight="balanced", max_iter=3000, random_state=seed)
    return make_pipeline(feats, clf)


def predict_with_abstain(model, texts, threshold: float):
    """Labels from a probabilistic model, ABSTAIN where the top class probability is below
    `threshold` (the text does not clearly belong to any of the known codes).
    Returns (labels, top probability)."""
    texts = list(texts)
    if not texts:
        return np.array([], dtype=object), np.array([], dtype=float)
    proba = model.predict_proba(texts)
    top = proba.max(axis=1)
    lab = np.asarray(model.classes_, dtype=object)[proba.argmax(axis=1)]
    return np.where(top >= threshold, lab, ABSTAIN).astype(object), top


def abstain_threshold(top_proba, correct, target_accuracy: float, grid=None) -> dict:
    """Smallest probability threshold on a validation set at which the accuracy of the
    covered (non-abstained) predictions reaches `target_accuracy`. `correct` says whether the
    plain (non-abstaining) prediction was right. Returns the threshold, the validation
    coverage and the covered accuracy; threshold None if no grid value reaches the target."""
    top = np.asarray(top_proba, dtype=float)
    ok = np.asarray(correct, dtype=bool)
    if top.size == 0 or top.shape != ok.shape:
        raise ValueError("need equal-length, non-empty probability and correctness arrays")
    grid = np.round(np.arange(0.0, 1.0, 0.01), 2) if grid is None else np.asarray(grid, dtype=float)
    for t in grid:
        cov = top >= t
        if cov.any() and ok[cov].mean() >= target_accuracy:
            return {"threshold": float(t), "coverage": float(cov.mean()), "accuracy_on_covered": float(ok[cov].mean())}
    return {"threshold": None, "coverage": 0.0, "accuracy_on_covered": None}


def wilson_ci(k: int, n: int, z: float = 1.959963984540054) -> tuple:
    """Wilson score interval for a binomial proportion k / n (95 % by default)."""
    if n <= 0 or not (0 <= k <= n):
        raise ValueError("need 0 <= k <= n and n > 0")
    p = k / n
    den = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (float(centre - half), float(centre + half))


def time_split(dates: pd.Series, train_end, val_end, test_start=None):
    """train: date < train_end; validation: train_end <= date < val_end;
    test: date >= test_start (default val_end). Returns three boolean arrays."""
    d = pd.to_datetime(dates)
    train_end, val_end = pd.Timestamp(train_end), pd.Timestamp(val_end)
    test_start = val_end if test_start is None else pd.Timestamp(test_start)
    if not (train_end <= val_end <= test_start):
        raise ValueError("split dates must be ordered")
    tr = (d < train_end).to_numpy()
    va = ((d >= train_end) & (d < val_end)).to_numpy()
    te = (d >= test_start).to_numpy()
    return tr, va, te


def unseen_mask(train_texts, test_texts) -> np.ndarray:
    seen = {normalise(t) for t in train_texts}
    return np.array([normalise(t) not in seen for t in test_texts], dtype=bool)


def scores(y_true, y_pred, labels) -> dict:
    """Accuracy, macro-F1 over `labels` (an ABSTAIN prediction counts as wrong), coverage
    (share of non-abstained predictions), accuracy on covered rows, per-class P/R/F1."""
    y_true = np.asarray(y_true, dtype=object)
    y_pred = np.asarray(y_pred, dtype=object)
    if y_true.size == 0:
        raise ValueError("empty evaluation set")
    per = {}
    for c in labels:
        tp = int(np.sum((y_pred == c) & (y_true == c)))
        npred = int(np.sum(y_pred == c))
        ntrue = int(np.sum(y_true == c))
        p = tp / npred if npred else 0.0
        r = tp / ntrue if ntrue else 0.0
        per[c] = {"support": ntrue, "precision": p, "recall": r, "f1": 2 * p * r / (p + r) if p + r else 0.0}
    present = [c for c in labels if per[c]["support"] > 0]
    covered = y_pred != ABSTAIN
    return {"n": int(y_true.size), "accuracy": float(np.mean(y_true == y_pred)),
            "macro_f1": float(np.mean([per[c]["f1"] for c in present])) if present else 0.0,
            "coverage": float(np.mean(covered)),
            "accuracy_on_covered": float(np.mean(y_true[covered] == y_pred[covered])) if covered.any() else None,
            "per_class": per}


def confusion(y_true, y_pred, labels) -> np.ndarray:
    """Rows = true label, columns = predicted label (labels + ABSTAIN as the last column)."""
    cols = list(labels) + [ABSTAIN]
    idx_r = {c: i for i, c in enumerate(labels)}
    idx_c = {c: i for i, c in enumerate(cols)}
    m = np.zeros((len(labels), len(cols)), dtype=int)
    for t, p in zip(y_true, y_pred):
        m[idx_r[t], idx_c.get(p, len(cols) - 1)] += 1
    return m
