"""Check the Python reference against VBA outputs captured from Excel (results/vba_parity.csv).

The CSV is produced on Windows by scripts/vba_parity.py; CI has no Excel and only replays it.
"""

import csv
import json
import math
from pathlib import Path

import pytest

from fabhvac.vba_reference import ERR, FUNCTIONS, grid, python_value

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "results" / "vba_parity.csv"


def _rows():
    if not GOLDEN.exists():
        return []
    with GOLDEN.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


ROWS = _rows()


@pytest.mark.skipif(not ROWS, reason="results/vba_parity.csv not generated (needs Excel)")
def test_golden_covers_every_vba_function_and_the_full_grid():
    assert {r["function"] for r in ROWS} == set(FUNCTIONS)
    assert len(ROWS) == len(grid())


@pytest.mark.skipif(not ROWS, reason="results/vba_parity.csv not generated (needs Excel)")
@pytest.mark.parametrize("i", range(len(ROWS)))
def test_python_matches_recorded_vba(i):
    row = ROWS[i]
    args = json.loads(row["args_json"])
    py = python_value(row["function"], args)
    vba = row["vba_value"]
    if vba == ERR or py == ERR:
        assert vba == py
        return
    try:
        vba_f = float(vba)
    except ValueError:
        assert vba == str(py)
        return
    assert math.isclose(float(py), vba_f, rel_tol=1e-9, abs_tol=1e-12)
