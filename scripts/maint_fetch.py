"""Part D step 1: download a snapshot of the NYC Parks AMPS maintenance tables.

Source: NYC Department of Parks and Recreation, "Asset Management Parks System (AMPS)"
tables on NYC Open Data (see docs/sources.md for the terms of use). Raw data are NOT in
this repository. Set NYC_AMPS_DIR to a folder outside the repository; this script writes

  <NYC_AMPS_DIR>/work_orders.parquet   selected work-order columns, all rows
  <NYC_AMPS_DIR>/assets.parquet        selected asset columns, all rows
  <NYC_AMPS_DIR>/labor_by_wo.parquet   booked labour hours summed per work order
  <NYC_AMPS_DIR>/snapshot.json         download time, row counts, SHA-256 of each file

Free-text descriptions stay in the local cache; only aggregates go to results/.

    NYC_AMPS_DIR=/path/to/cache python scripts/maint_fetch.py
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

BASE = "https://data.cityofnewyork.us/resource/"
WORK_ORDERS = "8sdw-8vja"
ASSETS = "e25p-jzfy"
LABOR = "xzj8-i3jk"
PAGE = 250_000

WO_COLUMNS = ["evt_code", "evt_desc", "evt_type", "evt_jobtype", "evt_reqm", "evt_object", "evt_obtype",
              "evt_class", "evt_standwork", "evt_priority", "evt_reported", "evt_created", "evt_start",
              "evt_completed", "evt_udfchar06", "evt_udfchar13", "evt_mrc", "evt_ppm", "evt_freq",
              "evt_perioduom", "evt_parent", "evt_reopened"]
ASSET_COLUMNS = ["obj_code", "obj_desc", "obj_class", "obj_category", "obj_obtype", "obj_parent", "obj_status",
                 "obj_commiss", "obj_withdraw", "obj_manufact", "obj_mrc"]


def out_dir() -> Path:
    d = os.environ.get("NYC_AMPS_DIR")
    if not d:
        sys.exit("set NYC_AMPS_DIR to a folder outside the repository")
    p = Path(d)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _get(url: str, tries: int = 5) -> bytes:
    for k in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=900) as r:
                return r.read()
        except Exception as e:  # network hiccups: back off and retry
            if k == tries - 1:
                raise
            print(f"  retry after {e!r}", flush=True)
            time.sleep(10 * (k + 1))
    raise RuntimeError("unreachable")


def fetch_table(dataset: str, select: str, extra: dict | None = None) -> pd.DataFrame:
    """Page through a Socrata table as CSV, ordered by the internal row id (stable paging)."""
    frames = []
    offset = 0
    while True:
        q = {"$select": select, "$order": ":id", "$limit": str(PAGE), "$offset": str(offset)}
        q.update(extra or {})
        raw = _get(BASE + dataset + ".csv?" + urllib.parse.urlencode(q))
        df = pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False, quoting=csv.QUOTE_MINIMAL)
        frames.append(df)
        print(f"  {dataset} offset {offset}: {len(df)} rows", flush=True)
        if len(df) < PAGE:
            break
        offset += PAGE
    return pd.concat(frames, ignore_index=True)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def main() -> int:
    """Each table is downloaded once; an existing file is kept (delete it to refresh), so an
    interrupted download resumes with the missing tables."""
    d = out_dir()
    log_path = d / "download_times.json"
    times = json.loads(log_path.read_text(encoding="utf-8")) if log_path.exists() else {}
    tables = [("work_orders.parquet", WORK_ORDERS, ",".join(WO_COLUMNS), None),
              ("assets.parquet", ASSETS, ",".join(ASSET_COLUMNS), None),
              # labour: booked hours summed per work order on the server (boo_hours is a text column)
              ("labor_by_wo.parquet", LABOR, "boo_event,sum(boo_hours::number) as labor_hours,count(*) as n_bookings",
               {"$group": "boo_event", "$order": "boo_event"})]
    rows = {}
    for fname, ds, select, extra in tables:
        p = d / fname
        if p.exists():
            print(f"{fname} exists; kept")
        else:
            t0 = _now()
            fetch_table(ds, select, extra).to_parquet(p, index=False)
            times[fname] = {"dataset": ds, "start_utc": t0, "end_utc": _now()}
            log_path.write_text(json.dumps(times, indent=2) + "\n", encoding="utf-8")
        rows[fname] = int(pq.ParquetFile(p).metadata.num_rows)
    snap = {"source": "NYC Open Data, NYC Parks AMPS", "download_times": times,
            "datasets": {"work_orders": WORK_ORDERS, "assets": ASSETS, "labor": LABOR},
            "rows": rows, "sha256": {f: sha256(d / f) for f, *_ in tables}}
    (d / "snapshot.json").write_text(json.dumps(snap, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(snap, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
