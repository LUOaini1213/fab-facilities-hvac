"""Cross-check PsychroLib (ASHRAE 2017 ideal-gas equations) against CoolProp HAPropsSI
(real-gas humid-air formulation with enhancement factor) over a grid of states.

Output: results/psychro_crosscheck.csv (every grid point) and
        results/psychro_crosscheck_summary.json (max abs / rel differences per property).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
RES = Path(os.environ.get("FABHVAC_RESULTS_DIR", ROOT / "results"))

from importlib import metadata  # noqa: E402

import CoolProp  # noqa: E402
from CoolProp.HumidAirProp import HAPropsSI  # noqa: E402

from fabhvac import psychro  # noqa: E402
from fabhvac.results_io import write_csv, write_json  # noqa: E402

TDB = [5.0, 12.5, 20.0, 27.5, 35.0, 42.5]
RH = [0.10, 0.30, 0.50, 0.70, 0.90, 1.00]
P = [101325.0, 95000.0]


def grid():
    rows = []
    for p in P:
        for t in TDB:
            for rh in RH:
                s = psychro.state_tdb_rh(t, rh, p)
                tk = t + 273.15
                w_cp = HAPropsSI("W", "T", tk, "R", rh, "P", p)
                h_cp = HAPropsSI("H", "T", tk, "R", rh, "P", p)  # J/kg dry air
                twb_cp = HAPropsSI("Twb", "T", tk, "R", rh, "P", p) - 273.15
                tdp_cp = HAPropsSI("Tdp", "T", tk, "R", rh, "P", p) - 273.15
                rows.append({"p_pa": p, "tdb_c": t, "rh": rh,
                             "w_psy": s.w, "w_cp": w_cp,
                             "h_psy": s.h_j_kg, "h_cp": h_cp,
                             "twb_psy": s.twb_c, "twb_cp": twb_cp,
                             "tdp_psy": s.tdp_c, "tdp_cp": tdp_cp})
    return rows


def main():
    rows = grid()
    header = list(rows[0].keys())
    write_csv(RES / "psychro_crosscheck.csv", header, [[r[k] for k in header] for r in rows])
    summ = {"n_points": len(rows), "coolprop_version": CoolProp.__version__,
            "psychrolib_version": metadata.version("PsychroLib")}
    for prop, unit in (("w", "kg/kg"), ("h", "J/kg"), ("twb", "K"), ("tdp", "K")):
        diffs = [r[f"{prop}_psy"] - r[f"{prop}_cp"] for r in rows]
        entry = {"max_abs_diff": max(abs(d) for d in diffs), "unit": unit,
                 "mean_diff": sum(diffs) / len(diffs)}
        if prop in ("w", "h"):
            entry["max_rel_diff"] = max(abs(r[f"{prop}_psy"] - r[f"{prop}_cp"]) / abs(r[f"{prop}_cp"]) for r in rows)
        summ[prop] = entry
    write_json(RES / "psychro_crosscheck_summary.json", summ)
    print(summ)


if __name__ == "__main__":
    main()
