"""Re-run the data-free scripts into a temp dir and require byte-identical output to the
committed results/ files (catches both code drift and Windows/Linux float differences)."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

PART_A_FILES = ["iso_class_limits.csv", "mees_table.csv", "singapore_design_states.json",
                "bay_example.json", "well_mixed_sweep.csv"]
CROSSCHECK_FILES = ["psychro_crosscheck.csv", "psychro_crosscheck_summary.json"]
MAINT_FILES = ["maintenance_weibull_selfcheck.json", "maintenance_pm_sensitivity.csv"]


def _run(script, out_dir):
    env = dict(os.environ, FABHVAC_RESULTS_DIR=str(out_dir))
    subprocess.run([sys.executable, str(ROOT / "scripts" / script)], check=True, env=env,
                   cwd=ROOT, capture_output=True)


@pytest.mark.parametrize("script,files", [("run_calcs.py", PART_A_FILES),
                                          ("psychro_crosscheck.py", CROSSCHECK_FILES),
                                          ("maint_calcs.py", MAINT_FILES)])
def test_results_reproduce_byte_for_byte(tmp_path, script, files):
    if script == "psychro_crosscheck.py":
        pytest.importorskip("CoolProp")
    _run(script, tmp_path)
    for f in files:
        committed = (ROOT / "results" / f).read_bytes()
        fresh = (tmp_path / f).read_bytes()
        assert fresh == committed, f"{f} differs from committed results/"


def test_no_backspace_or_cr_in_sources():
    """Guard against heredoc corruption (chr(8)) and stray CR in text sources (except .bas)."""
    for p in list(ROOT.glob("fabhvac/**/*.py")) + list(ROOT.glob("scripts/*.py")) + list(ROOT.glob("tests/*.py")):
        data = p.read_bytes()
        assert b"\x08" not in data, p
        assert b"\r" not in data, p
