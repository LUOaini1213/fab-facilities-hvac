"""Run the fixed parity grid through the VBA UDFs (Excel, via Application.Run on the
workbook this script opens) and through the Python reference; write

  results/vba_parity.csv            one row per call: inputs, VBA value, Python value, diffs
  results/vba_parity_summary.json   max abs / rel diff per function, error-agreement counts,
                                    and the Calculator-sheet read-back vs the Python example

The CSV is the golden file used by tests/test_vba_golden.py in CI (no Excel there).
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from excel_session import excel_app  # noqa: E402

from fabhvac.results_io import write_csv, write_json  # noqa: E402
from fabhvac.vba_reference import ERR, grid, python_value  # noqa: E402

XLSM = ROOT / "excel" / "fab_hvac_calculator.xlsm"
XL_ERR_VALUE = -2146826273  # CVErr(xlErrValue) as seen through COM


def vba_value(app, wbname, name, args):
    v = app.Run(f"'{wbname}'!{name}", *args)
    if isinstance(v, int) and v == XL_ERR_VALUE:
        return ERR
    return v


def compare(v, p):
    if v == ERR or p == ERR:
        return (v == p), None, None
    if isinstance(p, str) or isinstance(v, str):
        return (str(v) == str(p)), None, None
    v, p = float(v), float(p)
    ad = abs(v - p)
    rd = ad / abs(p) if p != 0 else ad
    return math.isclose(v, p, rel_tol=1e-9, abs_tol=1e-12), ad, rd


def main() -> int:
    if not XLSM.exists():
        print("BLOCKED: excel/fab_hvac_calculator.xlsm not built (run scripts/build_xlsm.py first)")
        return 2
    rows, per_fn = [], {}
    with excel_app() as (app, pid):
        wb = app.Workbooks.Open(str(XLSM), ReadOnly=True)
        for name, args in grid():
            v = vba_value(app, wb.Name, name, args)
            p = python_value(name, args)
            ok, ad, rd = compare(v, p)
            rows.append([name, json.dumps(list(args)), v if v == ERR or isinstance(v, str) else float(v),
                         p if p == ERR or isinstance(p, str) else float(p), ad, rd, ok])
            s = per_fn.setdefault(name, {"n": 0, "n_agree": 0, "n_error_cases": 0,
                                         "max_abs_diff": 0.0, "max_rel_diff": 0.0})
            s["n"] += 1
            s["n_agree"] += int(ok)
            s["n_error_cases"] += int(p == ERR)
            if ad is not None:
                s["max_abs_diff"] = max(s["max_abs_diff"], ad)
                s["max_rel_diff"] = max(s["max_rel_diff"], rd)
        # Calculator sheet read-back (built by the FillCalcSheet macro)
        ws = wb.Worksheets("Calculator")
        sheet = {}
        for i in range(1, 80):
            label = ws.Cells(i, 1).Value
            val = ws.Cells(i, 2).Value
            if label and val is not None:
                key = str(label)
                if key in sheet:
                    key = f"{key} [{ws.Cells(i, 3).Value}]"
                sheet[key] = val
        wb.Close(SaveChanges=False)

    # Calculator read-back vs the Python worked example (same illustrative inputs)
    ex = json.loads((ROOT / "results" / "bay_example.json").read_text(encoding="utf-8"))
    checks = {
        "FFU count": (sheet.get("FFU count"), ex["unidirectional"]["ffu_count"]),
        "Supply airflow": (sheet.get("Supply airflow"), ex["unidirectional"]["airflow_m3s"]),
        "Air changes": (sheet.get("Air changes"), ex["unidirectional"]["ach"]),
        "System efficiency": (sheet.get("System efficiency"), ex["plant"]["kwe_per_kwc"]),
        "NEA MEES verdict": (sheet.get("NEA MEES verdict"), ex["plant"]["mees"]["verdict"]),
        "Effectiveness": (sheet.get("Effectiveness"), ex["tower"]["effectiveness"]),
    }
    sheet_cmp = {}
    for k, (v, p) in checks.items():
        ok, ad, _ = compare(v, p) if not isinstance(p, str) else (v == p, None, None)
        if not isinstance(p, str):
            ok = v is not None and math.isclose(float(v), float(p), rel_tol=1e-9)  # example json is 10 s.f.
        sheet_cmp[k] = {"sheet": v, "python": p, "agree": bool(ok)}

    header = ["function", "args_json", "vba_value", "python_value", "abs_diff", "rel_diff", "agree"]
    write_csv(ROOT / "results" / "vba_parity.csv", header, rows)
    summary = {"n_calls": len(rows), "n_agree": sum(int(r[-1]) for r in rows),
               "tolerance": "rel 1e-9 or abs 1e-12; errors must match",
               "per_function": per_fn, "calculator_sheet_vs_python_example": sheet_cmp}
    write_json(ROOT / "results" / "vba_parity_summary.json", summary)
    print(json.dumps({k: summary[k] for k in ("n_calls", "n_agree")}))
    bad = [r for r in rows if not r[-1]]
    for b in bad:
        print("DISAGREE", b)
    return 0 if not bad and all(c["agree"] for c in sheet_cmp.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
