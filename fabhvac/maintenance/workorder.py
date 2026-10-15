"""CMMS-like work-order data model, asset hierarchy and validation.

One row per work order. Canonical columns:

  wo_id          unique id
  site           top of the asset hierarchy (e.g. a park property or a fab)
  system         intermediate level (building, zone, plant); may be empty
  asset_id       the object the work was done on
  asset_class    equipment class (BOILER, HVAC, PUMP, CHILLER, ...)
  wo_type        PM (planned/preventive), CM (corrective), INSP (inspection), OTHER
  status         open, closed, cancelled
  failure_mode   code from a failure-mode taxonomy; required for CM, empty otherwise
  description    free text
  opened_at      time the problem was reported / the order was raised
  closed_at      time the work was completed (NaT while open)
  labor_hours    booked labour (NaN if unknown)
  downtime_hours equipment downtime (NaN if the source system does not record it)

`validate` returns one boolean column per rule, so every count in a data-quality report
can be traced back to the rows that triggered it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

WO_TYPES = ("PM", "CM", "INSP", "OTHER")
STATUSES = ("open", "closed", "cancelled")
REQUIRED = ("wo_id", "site", "asset_id", "asset_class", "wo_type", "status", "opened_at", "description")
OPTIONAL = ("system", "failure_mode", "closed_at", "labor_hours", "downtime_hours")
COLUMNS = REQUIRED + OPTIONAL


def empty_frame() -> pd.DataFrame:
    df = pd.DataFrame({c: pd.Series(dtype=object) for c in COLUMNS})
    for c in ("opened_at", "closed_at"):
        df[c] = pd.Series(dtype="datetime64[ns]")
    for c in ("labor_hours", "downtime_hours"):
        df[c] = pd.Series(dtype=float)
    return df


def elapsed_hours(df: pd.DataFrame) -> pd.Series:
    """closed_at - opened_at in hours (NaN while open)."""
    return (df["closed_at"] - df["opened_at"]) / pd.Timedelta(hours=1)


def _blank(s: pd.Series) -> pd.Series:
    return s.isna() | (s.astype(str).str.strip() == "")


def validate(df: pd.DataFrame, failure_modes=None, hierarchy: "AssetHierarchy | None" = None) -> pd.DataFrame:
    """Row-level rule flags (True = rule violated)."""
    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"missing columns: {missing}")
    f = pd.DataFrame(index=df.index)
    f["missing_required"] = np.logical_or.reduce([_blank(df[c]) for c in REQUIRED])
    f["duplicate_id"] = df["wo_id"].duplicated(keep=False) & ~_blank(df["wo_id"])
    f["unknown_wo_type"] = ~df["wo_type"].isin(WO_TYPES)
    f["unknown_status"] = ~df["status"].isin(STATUSES)
    closed = df["status"] == "closed"
    f["closed_without_close_time"] = closed & df["closed_at"].isna()
    f["close_time_while_open"] = (df["status"] == "open") & df["closed_at"].notna()
    el = elapsed_hours(df)
    f["closed_before_opened"] = el < 0
    f["negative_labor"] = df["labor_hours"] < 0
    f["downtime_exceeds_elapsed"] = df["downtime_hours"] > el + 1e-9
    is_cm = df["wo_type"] == "CM"
    f["cm_without_failure_mode"] = is_cm & _blank(df["failure_mode"])
    f["failure_mode_on_non_cm"] = ~is_cm & ~_blank(df["failure_mode"])
    if failure_modes is not None:
        f["unknown_failure_mode"] = ~_blank(df["failure_mode"]) & ~df["failure_mode"].isin(list(failure_modes))
    if hierarchy is not None:
        f["asset_not_in_hierarchy"] = ~df["asset_id"].isin(list(hierarchy.parent))
    return f


def validation_summary(flags: pd.DataFrame) -> dict:
    return {"rows": int(len(flags)), "rows_with_any_issue": int(flags.any(axis=1).sum()),
            "by_rule": {c: int(flags[c].sum()) for c in flags.columns}}


class AssetHierarchy:
    """Parent links child -> parent (None at the top). `path` walks up to the root."""

    def __init__(self, parent: dict):
        self.parent = dict(parent)

    def path(self, asset, max_depth: int = 50) -> list:
        """[root, ..., asset]. Raises on a cycle or an unknown asset."""
        if asset not in self.parent:
            raise KeyError(asset)
        out = [asset]
        seen = {asset}
        p = self.parent[asset]
        while p is not None and p in self.parent:
            if p in seen or len(out) >= max_depth:
                raise ValueError(f"cycle or excessive depth above {asset!r}")
            out.append(p)
            seen.add(p)
            p = self.parent[p]
        if p is not None:          # parent named but not itself registered: keep it as the root
            out.append(p)
        return out[::-1]

    def root(self, asset):
        return self.path(asset)[0]

    def ancestor_at(self, asset, level: int):
        """Element `level` of the path (0 = root); None if the path is shorter."""
        p = self.path(asset)
        return p[level] if level < len(p) else None
