"""Reliability metrics from corrective work orders.

Definitions (calendar time; the source systems used here record no running hours):

  failure episode   corrective (CM) orders on one asset whose open intervals overlap are one
                    episode (duplicate tickets for the same breakdown); start = first opened_at,
                    end = last closed_at
  restore time      episode end - start, in hours. Without a downtime field this is the time
                    the order was open (reporting, waiting, travel and repair), not wrench time
  exposure          per asset, the length of its observation window
  episodes per asset-year   number of episodes / (total exposure in years): the recorded
                    corrective-episode rate. Where few failures are logged against the
                    equipment (recording practice), this is not a failure rate, and its
                    inverse is not a meaningful MTBF
  MTBF              total exposure / number of episodes starting inside the windows
  MTTR              mean restore time of those episodes
  availability      MTBF / (MTBF + MTTR)   (inherent-availability form)
  repeat failure    an episode that starts within `within_days` after the previous episode on
                    the same asset ended (optionally: with the same failure mode)
  uptime interval   time from the end of one episode to the start of the next (an observed
                    failure), or to the end of the window (right-censored) -- input to the
                    Weibull fit under the as-good-as-new-after-repair assumption
"""

from __future__ import annotations

import numpy as np
import pandas as pd

HOUR = pd.Timedelta(hours=1)
DAY = pd.Timedelta(days=1)
HOURS_PER_YEAR = 8766.0        # 365.25 days


def failure_episodes(cm: pd.DataFrame) -> pd.DataFrame:
    """Merge overlapping CM orders per asset. Input needs asset_id, opened_at, closed_at,
    failure_mode; rows with no closed_at are dropped (still open: no restore time)."""
    d = cm.dropna(subset=["opened_at", "closed_at"]).sort_values(["asset_id", "opened_at", "closed_at"])
    rows = []
    for asset, g in d.groupby("asset_id", sort=True):
        start = end = None
        n = 0
        mode = None
        for o, c, m in zip(g["opened_at"], g["closed_at"], g["failure_mode"]):
            if start is not None and o <= end:          # overlaps the current episode
                end = max(end, c)
                n += 1
                continue
            if start is not None:
                rows.append((asset, start, end, n, mode))
            start, end, n, mode = o, c, 1, m
        if start is not None:
            rows.append((asset, start, end, n, mode))
    ep = pd.DataFrame(rows, columns=["asset_id", "start", "end", "n_orders", "failure_mode"])
    ep["restore_hours"] = (ep["end"] - ep["start"]) / HOUR
    return ep


def reliability_table(episodes: pd.DataFrame, windows: pd.DataFrame, by: str | None = None) -> pd.DataFrame:
    """MTBF / MTTR / availability per group of assets.

    windows: one row per asset with asset_id, start, end (and the `by` column). Assets with no
    failure still contribute exposure. Episodes outside an asset's window are ignored."""
    w = windows.copy()
    w["exposure_h"] = (w["end"] - w["start"]) / HOUR
    if (w["exposure_h"] < 0).any():
        raise ValueError("window end before start")
    e = episodes.merge(w[["asset_id", "start", "end"]].rename(columns={"start": "w0", "end": "w1"}), on="asset_id")
    e = e[(e["start"] >= e["w0"]) & (e["start"] < e["w1"])]
    key = by if by is not None else "_all"
    if by is None:
        w["_all"] = "all"
        e = e.assign(_all="all")
    else:   # the group always comes from the windows table (episodes may carry a stale copy)
        e = e.drop(columns=[by], errors="ignore").merge(w[["asset_id", by]], on="asset_id")
    out = []
    for k, wg in w.groupby(key, sort=True):
        eg = e[e[key] == k]
        n = int(len(eg))
        expo = float(wg["exposure_h"].sum())
        mtbf = expo / n if n else np.nan
        mttr = float(eg["restore_hours"].mean()) if n else np.nan
        out.append({key if by else "group": k, "assets": int(wg["asset_id"].nunique()), "failures": n,
                    "exposure_h": expo, "episodes_per_asset_year": n / (expo / HOURS_PER_YEAR) if expo > 0 else np.nan,
                    "mtbf_h": mtbf, "mttr_h": mttr,
                    "median_restore_h": float(eg["restore_hours"].median()) if n else np.nan,
                    "availability": mtbf / (mtbf + mttr) if n else np.nan})
    return pd.DataFrame(out)


def repeat_flags(episodes: pd.DataFrame, within_days: float = 30.0, same_mode: bool = False) -> pd.Series:
    """True for an episode starting within `within_days` of the end of the previous episode
    on the same asset (and the same failure mode if `same_mode`)."""
    keys = ["asset_id", "failure_mode"] if same_mode else ["asset_id"]
    e = episodes.sort_values(keys + ["start"])
    prev_end = e.groupby(keys, sort=False)["end"].shift(1)
    gap = (e["start"] - prev_end) / DAY
    flag = gap.notna() & (gap <= within_days)
    return flag.reindex(episodes.index)


def pareto(df: pd.DataFrame, by: str, value: str, vital_share: float = 0.8) -> pd.DataFrame:
    """Sum of `value` per `by`, descending, with share, cumulative share and the 'vital few'
    (the smallest set of top groups whose cumulative share reaches `vital_share`)."""
    s = df.groupby(by, sort=True)[value].sum()
    s = s.sort_values(ascending=False, kind="mergesort")   # stable: ties keep alphabetical order
    tot = float(s.sum())
    out = pd.DataFrame({by: s.index, value: s.to_numpy()})
    out["share"] = out[value] / tot
    out["cum_share"] = out["share"].cumsum()
    prev = out["cum_share"].shift(1, fill_value=0.0)
    out["vital_few"] = prev < vital_share - 1e-12
    return out


def uptime_intervals(episodes: pd.DataFrame, windows: pd.DataFrame) -> pd.DataFrame:
    """Uptime between episodes (failed=True) plus the final censored interval to the window
    end (failed=False), in days. The interval before an asset's first episode is not used
    (the asset's age or last repair before the window is unknown)."""
    w = windows.set_index("asset_id")
    rows = []
    for asset, g in episodes.sort_values(["asset_id", "start"]).groupby("asset_id", sort=True):
        if asset not in w.index:
            continue
        w0, w1 = w.at[asset, "start"], w.at[asset, "end"]
        g = g[(g["start"] >= w0) & (g["start"] < w1)]
        if g.empty:
            continue
        ends = g["end"].to_numpy()
        starts = g["start"].to_numpy()
        for k in range(len(g) - 1):
            rows.append((asset, (starts[k + 1] - ends[k]) / np.timedelta64(1, "D"), True))
        if ends[-1] < np.datetime64(w1):
            rows.append((asset, (np.datetime64(w1) - ends[-1]) / np.timedelta64(1, "D"), False))
    out = pd.DataFrame(rows, columns=["asset_id", "t_days", "failed"])
    return out[out["t_days"] > 0].reset_index(drop=True)
