"""The README's headline numbers must match the committed results files.

Each entry is (literal as written in the README's "At a glance" block, results file,
value getter, formatter). The test fails if the literal is missing from the block or if
the formatted value read from the file differs from it, so a rerun that changes a result
(or an edit to the README) cannot leave the two out of step. The README's test count is
checked against `pytest --collect-only`.
"""

from __future__ import annotations

import csv
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
RESULTS = ROOT / "results"


def _json(name):
    return json.loads((RESULTS / name).read_text(encoding="utf-8"))


def _csv_cell(name, value_col, **match):
    with (RESULTS / name).open(encoding="utf-8", newline="") as f:
        rows = [r for r in csv.DictReader(f) if all(r[k] == v for k, v in match.items())]
    assert len(rows) == 1, (name, match, len(rows))
    return float(rows[0][value_col])


def _bay(*keys):
    x = _json("bay_example.json")
    for k in keys:
        x = x[k]
    return x


def _weibull(*keys):
    x = _json("maintenance_weibull_boiler.json")
    for k in keys:
        x = x[k]
    return x


def _tc(*keys):
    x = _json("maintenance_textclass.json")
    for k in keys:
        x = x[k]
    return x


def pct1(v):
    return f"{100 * v:.1f} %"


ENTRY = "enthalpy_0p4_h_mcdb"

CHECKS = [
    # Part A worked example
    ("600 m²", lambda: _bay("floor_area_m2"), lambda v: f"{v:.0f} m²"),
    ("834 FFUs", lambda: _bay("unidirectional", "ffu_count"), lambda v: f"{v} FFUs"),
    ("489.6 kW (139.2 RT)", lambda: (_bay("cases", ENTRY, "total_cooling_kw"), _bay("cases", ENTRY, "total_cooling_rt")),
     lambda v: f"{v[0]:.1f} kW ({v[1]:.1f} RT)"),
    ("(enthalpy) design point", lambda: _bay("governing_case_total_cooling"),
     lambda v: "(enthalpy) design point" if v == ENTRY else v),
    ("0.18875 kWe/kWc", lambda: _bay("plant", "kwe_per_kwc"), lambda v: f"{v:.5f} kWe/kWc"),
    ("0.664 kW/RT", lambda: _bay("plant", "kw_per_rt"), lambda v: f"{v:.3f} kW/RT"),
    ("passes the NEA MEES limit of 0.191", lambda: (_bay("plant", "mees", "verdict"), _bay("plant", "mees", "limit_kwe_per_kwc")),
     lambda v: f"{'passes' if v[0] == 'PASS' else v[0]} the NEA MEES limit of {v[1]:.3f}"),
    # Part C detection, main split, deployable thresholds
    ("chiller fouling in 0.938", lambda: _csv_cell("fdd_detection_by_type.csv", "ml_deployable_alarm_rate", fault_type="chiller_fouling"),
     lambda v: f"chiller fouling in {v:.3f}"),
    ("against 0.030 for the physics-residual baseline",
     lambda: _csv_cell("fdd_detection_by_type.csv", "baseline_deployable_alarm_rate", fault_type="chiller_fouling"),
     lambda v: f"against {v:.3f} for the physics-residual baseline"),
    ("tower fouling only 0.024", lambda: _csv_cell("fdd_detection_by_type.csv", "ml_deployable_alarm_rate", fault_type="coolingtower_fouling"),
     lambda v: f"tower fouling only {v:.3f}"),
    ("0 fault-free test hours", lambda: _csv_cell("fdd_detection_by_type.csv", "ml_deployable_alarm_rate", fault_type="normal"),
     lambda v: f"{v:.0f} fault-free test hours"),
    # Part C season block
    ("39.1 % of fault-free hours",
     lambda: _csv_cell("fdd_season_split.csv", "ml_deployable_alarm_rate", split="train_jul_dec_test_jan_jun", fault_type="normal"),
     lambda v: f"{pct1(v)} of fault-free hours"),
    # Part D boiler Weibull
    ("β = 0.40", lambda: _weibull("fit", "beta"), lambda v: f"β = {v:.2f}"),
    ("bootstrap 0.35–0.48", lambda: _weibull("fit_cluster_bootstrap_by_boiler", "beta_ci"),
     lambda v: f"bootstrap {v[0]:.2f}–{v[1]:.2f}"),
    ("over 432 uptime intervals", lambda: _weibull("intervals"), lambda v: f"over {v} uptime intervals"),
    # Part D text classifier
    ("0.838 accuracy on 19 796 test orders", lambda: (_tc("test", "all", "ml", "accuracy"), _tc("test", "all", "n")),
     lambda v: f"{v[0]:.3f} accuracy on {v[1]:,} test orders".replace(",", " ")),
    ("majority class 0.256", lambda: _tc("majority_class_test_accuracy"), lambda v: f"majority class {v:.3f}"),
    ("below p = 0.87", lambda: _tc("abstain", "threshold"), lambda v: f"below p = {v:.2f}"),
    ("labels 57.3 % of them at 0.949 accuracy",
     lambda: (_tc("test", "all", "ml_with_abstain", "coverage"), _tc("test", "all", "ml_with_abstain", "accuracy_on_covered")),
     lambda v: f"labels {pct1(v[0])} of them at {v[1]:.3f} accuracy"),
]


def _glance():
    text = README.read_text(encoding="utf-8")
    m = re.search(r"^## At a glance\n(.*?)^## ", text, flags=re.M | re.S)
    assert m, "README has no '## At a glance' section"
    return " ".join(m.group(1).split())


def _mutation_literal():
    r = _json("mutation_report.json")
    return f"{r['killed']} of {r['total_applied']} non-equivalent mutants"


@pytest.mark.parametrize("literal,getter,fmt", CHECKS, ids=[c[0] for c in CHECKS])
def test_glance_number_matches_results(literal, getter, fmt):
    assert literal in _glance(), f"README 'At a glance' no longer contains {literal!r}"
    assert fmt(getter()) == literal, f"results file gives {fmt(getter())!r}, README says {literal!r}"


def test_glance_block_is_short():
    text = README.read_text(encoding="utf-8")
    block = re.search(r"^## At a glance\n(.*?)^## ", text, flags=re.M | re.S).group(1)
    bullets = [ln for ln in block.splitlines() if ln.startswith("- ")]
    assert 5 <= len(bullets) <= 8


def test_mutation_count_in_readme_matches_report():
    text = " ".join(README.read_text(encoding="utf-8").split())
    lit = _mutation_literal()
    assert lit in text, f"README should say {lit!r} (results/mutation_report.json)"
    r = _json("mutation_report.json")
    assert not r["survivors"] and not r["not_applied"]


def test_guard_mutation_count_in_readme_matches_report():
    r = _json("mutation_report_guards.json")
    assert r["only"] == "guard" and not r["survivors"] and not r["not_applied"]
    lit = f"{r['killed']} of {r['total_applied']} guard mutants are killed"
    assert lit in " ".join(README.read_text(encoding="utf-8").split()), lit
    import importlib.util
    spec = importlib.util.spec_from_file_location("mutate", ROOT / "scripts" / "mutate.py")
    mutate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mutate)
    ids = [m[0] for m in mutate.MUTANTS]
    assert sorted(m["id"] for m in r["mutants"]) == sorted(i for i in ids if i.startswith("guard"))
    full = _json("mutation_report.json")
    assert len(full["mutants"]) + r["total_applied"] == len(ids)
    assert f"all {len(ids)} mutants" in " ".join(README.read_text(encoding="utf-8").split())


def test_readme_test_count_matches_collection():
    text = " ".join(README.read_text(encoding="utf-8").split())
    m = re.search(r"`pytest` collects (\d+) tests: (\d+) run everywhere", text)
    assert m, "README test-count sentence not found"
    # addopts adds -q; override it so the output is one node id per line
    out = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-o", "addopts=",
                          "-p", "no:cacheprovider"],
                         cwd=ROOT, capture_output=True, text=True, timeout=300).stdout
    collected = sum(1 for ln in out.splitlines() if "::" in ln)
    assert collected > 0, out[-500:]
    # 3 tests are conditional: 2 VBA golden-replay tests (need results/vba_parity.csv) and the LBNL cache test
    assert (int(m.group(1)), int(m.group(2))) == (collected, collected - 3), (
        f"README says {m.group(1)} collected / {m.group(2)} everywhere; pytest collects {collected}")
