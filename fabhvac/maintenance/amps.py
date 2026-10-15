"""Adapter for the NYC Parks AMPS work-order tables (NYC Open Data) -> canonical work orders.

Field meanings are from the AMPS data dictionary and user guide linked from the dataset
page (see docs/sources.md):
  EVT_JOBTYPE  "Scheduled Work, Corrective Maintenance, Adhoc Inspection, Issue (parts)"
  EVT_TYPE     PPM = planned preventative maintenance, JOB = work order, IN = inspection
  EVT_REQM     problem code: "the problem this work order is intended to fix"
  EVT_DESC     entered by the requester; may be edited by the supervisor
  EVT_REPORTED editable date the problem was reported; EVT_CREATED creation time
  EVT_COMPLETED completion time; older mobile devices synced "days after" the work
  EVT_UDFCHAR13 status, EVT_UDFCHAR06 trade, EVT_MRC maintenance district (borough letter + number)

Choices made here (documented in README):
  * failure-mode taxonomy = the seven building-services (MEP) problem codes in MEP_MODES;
  * opened_at = EVT_REPORTED when present, else EVT_CREATED; closed_at = EVT_COMPLETED;
  * the AMPS tables record no equipment downtime, so downtime_hours stays NaN;
  * hierarchy = borough -> maintenance district -> asset (equipment rows carry no parent link).
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

from . import workorder as wo
from .textclass import normalise

MEP_MODES = ("Leaking", "Clogged", "No Water", "Will not turn off", "Not working electrical", "No Light", "No Heat")

JOBTYPE_TO_WO_TYPE = {"CM": "CM", "BRKD": "CM", "SCHD": "PM", "ADHC": "INSP", "INSP": "INSP"}
STATUS_CLOSED = {"Completed", "GT Completed"}
STATUS_CANCELLED = {"Cancelled", "Rejected", "GT Canceled", "GT Rejected", "Duplicate/Rejected", "Cancelled Inspection"}

# HVAC / heating-plant equipment classes in the AMPS asset table. EXTHD is NOT an exhaust
# hood (its rows are external hard drives) and FUELTANK rows collect building-wide requests.
HVAC_CLASSES = ("BOILER", "HVAC", "HWH", "PUMP", "COOLTOWR", "AC", "AHU", "FURNACE", "UNITHEAT",
                "WINDOWAC", "SPLITOUT", "SPLITIN", "SPLITOA", "BURNER")

BOROUGHS = {"B": "Brooklyn", "M": "Manhattan", "Q": "Queens", "R": "Staten Island", "X": "Bronx"}

# Routine tasks logged as corrective work (water treatment, blowdown, seasonal start/stop,
# planned overhaul, filter change, inspection). Written from the equipment-order text.
ROUTINE_PATTERN = re.compile(
    r"\bbl[eo]w ?down\b|\bwater treatment\b|\bchem(ical)? test\b|\btreatment readings?\b|\bsight glass\b"
    r"|\bga[u]?ge glass\b|\boverhaul\b|\bwinteriz\w*|\bde ?winteriz\w*|\bseasonal\b|\bstart ?up\b|\bshut ?down\b"
    r"|\bcommissioning\b|\binspect\w*|\bmerv\b|\bfilter (change|replacement)\b|\bevaluation\b|\btune ?up\b")
NEW_WORK_PATTERN = re.compile(r"\binstall\w*|\bnew\b.*\b(line|unit|system)\b|\brelocat\w*|\bconvert\w*")

# Rule baseline for MEP_MODES; ordered, first match wins. Written from domain knowledge and
# training-period text (created before 2023), then revised once after looking at errors on
# the validation year (2023): Clogged moved before Leaking (clogs cause flooding) and a few
# phrases added. The test period (2024 on) was not looked at. See scripts/maint_run.py.
MEP_RULES = [
    ("No Heat", r"\bno heat\b|\bno hot air\b|\bheat(ing)? (is |are )?(not|isn t|is not) working\b|\black of heat\b"),
    ("Will not turn off", r"\b(won t|wont|will not|wouldn t|doesn t|does not|cannot|can t|not) (stop|shut|turn off|shut off)\b"
                          r"|\bconstant\w*|\bcontinu\w*|\bkeeps? (running|flushing|going)\b|\bnon ?stop\b"
                          r"|\b(stuck|stays?) (on|open)\b|\brunning (toilet|urinal|faucet|water|sink)\b|\bshut ?off\b|\bturn off\b"
                          r"|\b(toilet|urinal|faucet|sink|shower|flushometer|fountain|df|valve)s? (is |are |keeps )?running\b"),
    ("Clogged", r"\bclog\w*|\bunclog\w*|\bcloged\b|\bblock(ed|age)\b|\bback(ed|ing|s)? ?up\b|\bstoppage\b|\bstopped\b"
                r"|\bsnak\w*|\bslow drain\w*|\bnot draining\b|\bdrain\w* (is |are )?slow\b|\boverflow\w*"),
    ("Leaking", r"\bleak\w*|\bdrip\w*|\bburst\b|\bbusted\b|\bflood\w*|\bgushing\b|\bwater (coming|pouring|rushing|entering)\b"),
    ("No Light", r"\blights? (are |is )?(out|not working|off|blown)\b|\bno lights?\b|\bbulbs?\b|\blamps?\b"
                 r"|\bfl[ou]{1,2}rescent\b|\bflorescent\b|\blight\w*\b"),
    ("No Water", r"\bno water\b|\bwater (is )?(off|not working|shut off)\b|\b(low|no|restore|inadequate) (water )?pressure\b"
                 r"|\bturn on\b|\bspray ?showers?\b|\bsprinkler\w*|\birrigat\w*|\bmisting\b|\bactivate\b|\bnot flushing\b"
                 r"|\brestore water\b|\b(fountain|df|cooler|bottle filler)s? (is |are )?not working\b"),
    ("Not working electrical", r"\boutlets?\b|\belectric\w*|\bpower\b|\bbreakers?\b|\bcircuit\w*|\bfuses?\b"
                               r"|\bwir(e|es|ing)\b|\bdryers?\b|\bfans?\b|\bgenerators?\b|\bsockets?\b|\breceptacles?\b"
                               r"|\bpole taps?\b|\bdetectors?\b|\bmotors?\b|\bblowers?\b|\bac unit\b|\bair condition\w*"),
    ("No Heat", r"\bheat\w*|\bboilers?\b|\bfurnaces?\b|\bradiators?\b|\bthermostats?\b|\bpilot\b|\bburners?\b|\bcold\b"),
]


def is_routine(texts) -> np.ndarray:
    return np.array([bool(ROUTINE_PATTERN.search(normalise(t))) for t in texts], dtype=bool)


def is_new_work(texts) -> np.ndarray:
    return np.array([bool(NEW_WORK_PATTERN.search(normalise(t))) for t in texts], dtype=bool)


def wo_type(jobtype: pd.Series, evt_type: pd.Series) -> pd.Series:
    t = jobtype.map(JOBTYPE_TO_WO_TYPE).fillna("OTHER")
    return t.where(evt_type != "PPM", "PM")


def status(raw: pd.Series) -> pd.Series:
    s = pd.Series("open", index=raw.index, dtype=object)
    s[raw.isin(STATUS_CLOSED)] = "closed"
    s[raw.isin(STATUS_CANCELLED)] = "cancelled"
    return s


def _ts(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s.replace("", None), errors="coerce").astype("datetime64[ns]")


def to_canonical(w: pd.DataFrame, assets: pd.DataFrame) -> pd.DataFrame:
    """AMPS work-order rows (string columns as downloaded) -> canonical work-order frame.
    failure_mode = the problem code when it is one of MEP_MODES (CM only), else empty."""
    a = assets.drop_duplicates("obj_code").set_index("obj_code")["obj_class"]
    out = pd.DataFrame(index=w.index)
    out["wo_id"] = w["evt_code"].astype(str)
    district = w["evt_mrc"].fillna("").astype(str)
    out["site"] = district.str[:1].map(BOROUGHS).fillna("")
    out["system"] = district
    out["asset_id"] = w["evt_object"].fillna("").astype(str)
    out["asset_class"] = out["asset_id"].map(a).fillna("").replace("", "(unregistered)")
    out["wo_type"] = wo_type(w["evt_jobtype"].fillna(""), w["evt_type"].fillna(""))
    out["status"] = status(w["evt_udfchar13"].fillna(""))
    code = w["evt_reqm"].fillna("")
    out["failure_mode"] = code.where(code.isin(MEP_MODES) & (out["wo_type"] == "CM"), "")
    out["description"] = w["evt_desc"].fillna("")
    rep = _ts(w["evt_reported"])
    out["opened_at"] = rep.fillna(_ts(w["evt_created"]))
    out["closed_at"] = _ts(w["evt_completed"]).where(out["status"] == "closed")
    out["labor_hours"] = np.nan
    out["downtime_hours"] = np.nan
    out["problem_code"] = code
    out["trade"] = w["evt_udfchar06"].fillna("")
    out["created_at"] = _ts(w["evt_created"])
    return out[list(wo.COLUMNS) + ["problem_code", "trade", "created_at"]]


def hierarchy(canon: pd.DataFrame) -> wo.AssetHierarchy:
    """borough -> district -> asset, using each asset's most frequent district."""
    d = canon[canon["system"] != ""]
    top = (d.groupby(["asset_id", "system"]).size().rename("n").reset_index()
           .sort_values(["asset_id", "n", "system"], ascending=[True, False, True])
           .drop_duplicates("asset_id"))
    parent = {}
    for s in sorted(top["system"].unique()):
        b = BOROUGHS.get(s[:1])
        parent[s] = b
        if b is not None:
            parent[b] = None
    parent.update(dict(zip(top["asset_id"], top["system"])))
    return wo.AssetHierarchy(parent)
