# fab-facilities-hvac

Engineering calculations for cleanroom HVAC and chilled-water plants, the same core
calculations as a VBA module whose Python/VBA parity check is scripted but has not yet been run
in Excel, fault detection and diagnosis (FDD) on a public simulated chiller-plant dataset, and
maintenance analytics on public work orders.

Every number below is read from a file in `results/` written by a script in `scripts/`.
External constants (standard limits, design conditions, conversion factors) are listed with
their source pages and retrieval date in [`docs/sources.md`](docs/sources.md).

| Part | Code | What it does |
|---|---|---|
| A | `fabhvac/` | psychrometrics (PsychroLib, cross-checked with CoolProp); ISO 14644-1 class limits; unidirectional and well-mixed cleanroom airflow; make-up-air + recirculation cooling load; chiller-plant kW/RT ↔ kWe/kWc, Singapore NEA MEES check, NEA M&V heat-balance test; cooling-tower range/approach/effectiveness |
| B | `excel/FabHvac.bas`, `scripts/build_xlsm.py`, `scripts/vba_parity.py` | worksheet UDFs + a macro that builds a calculator sheet; a VBA-vs-Python parity grid that is scripted but has not yet been run in Excel (see Part B status) |
| C | `fabhvac/fdd/`, `scripts/fdd_prepare.py`, `scripts/fdd_run.py` | detection and diagnosis of 8 chiller-plant fault types on the LBNL FDD dataset; residual baseline vs gradient boosting; time-blocked splits (interleaved months, plus a season-block check); energy effect per fault |
| D | `fabhvac/maintenance/`, `scripts/maint_*.py`, `docs/8D_chiller_example.md` | facilities maintenance analytics on 2.2 million public work orders (NYC Parks AMPS): work-order model and validation, boiler MTBF / restore time / availability, repeat failures, Pareto, censored Weibull fit with a by-boiler bootstrap and PM-interval model, text classification of failure modes with an abstain option; an 8D report on cooling-tower fouling in the LBNL data |

## Reproduce

```bash
python -m venv .venv && . .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev,fdd]"                          # add ",excel" on Windows for pywin32
pytest                                               # unit tests, golden outputs (VBA replay skips: not yet run)
python scripts/run_calcs.py                          # Part A -> results/*.csv|json
python scripts/psychro_crosscheck.py                 # PsychroLib vs CoolProp grid
python scripts/mutate.py                             # mutation pass -> results/mutation_report.json

# Part B (Windows + Excel; needs "Trust access to the VBA project object model")
python scripts/build_xlsm.py && python scripts/vba_parity.py

# Part C (raw data not included; see "Data")
export LBNL_FDD_DIR=/path/to/extracted/csvs LBNL_FDD_CACHE=/path/to/cache
python scripts/fdd_prepare.py && python scripts/fdd_run.py   # --skip-loso skips the 22 LOSO fits

# Part D (python scripts/maint_calcs.py is data-free; the rest needs the downloaded snapshot)
export NYC_AMPS_DIR=/path/to/amps/cache
python scripts/maint_fetch.py && python scripts/maint_run.py
python scripts/maint_8d.py          # needs LBNL_FDD_CACHE
python scripts/maint_llm.py         # optional; needs a local Ollama server, skips otherwise
```

The data-free outputs (`run_calcs.py`, `psychro_crosscheck.py`, `maint_calcs.py`) were checked
byte-identical on Windows (Python 3.11) and Linux (WSL Ubuntu 24.04, Python 3.12): floats are
rounded to 10 significant digits before writing, and `tests/test_golden_results.py` re-runs the
scripts and compares bytes. CI (`.github/workflows/ci.yml`, ubuntu-latest, Python 3.11 and 3.12)
runs the tests and then `git diff --exit-code results/` after regenerating them.

## Part A — engineering calculations

### ISO 14644-1 class limits
`Cn = 10^N × (0.1/D)^2.08` reproduces every non-blank cell of the classification table as
printed in Xu (book © 2014, chapter online 2013) when rounded to three significant figures and whole particles
(`results/iso_class_limits.csv`, `tests/test_cleanroom.py`).

### Psychrometrics cross-check
PsychroLib (ASHRAE 2017 ideal-gas equations) vs CoolProp `HAPropsSI` (real-gas, with
enhancement factor) on 72 states (5–42.5 °C, 10–100 % RH, 101.325 and 95 kPa),
`results/psychro_crosscheck_summary.json`:

| Property | max abs diff | max rel diff |
|---|---|---|
| humidity ratio | 0.000326 kg/kg | 0.55 % |
| enthalpy | 701 J/kg | 0.35 % |
| wet bulb | 0.024 K | — |
| dew point | 0.014 K | — |

For every published ASHRAE 2021 Singapore Changi (dew point, humidity ratio) pair, the
humidity-ratio interval PsychroLib gives for the dew point's rounding interval (±0.05 °C)
overlaps the published humidity ratio's rounding interval (±0.05 g/kg).

### Worked example — a cleanroom bay in Singapore
Inputs are **illustrative** (`examples/bay_example.json`): 40 m × 15 m bay, 4 m clear height,
ISO class 5 at 0.5 µm, full FFU ceiling at 0.40 m/s, 0.72 m² FFUs at 150 W, room 22 °C / 45 % RH,
3.0 m³/s make-up air, 150 kW tool heat to air, 15 W/m² lighting. Outdoor states are the ASHRAE
2021 Changi 0.4 % design points at the station's standard pressure (101.24 kPa). Output (inputs
echoed under `inputs`): `results/bay_example.json`.

| Quantity | Value |
|---|---|
| ISO 5 limit at 0.5 µm | 3 516.8 particles/m³ (formula value, before table rounding) |
| Unidirectional supply airflow / FFUs / air changes | 240 m³/s / 834 / 360 h⁻¹ |
| MAU supply dew point needed to absorb 0.2 g/s room moisture | 9.43 °C (7.34 g/kg) |

The FFU count is rounded up, so 834 × 0.72 m² = 600.5 m² of filter face slightly exceeds the
600 m² floor; with a full-coverage ceiling this only shows the method (a real ceiling grid leaves
room for lights, sprinklers and the grid itself).

| Outdoor design case (0.4 %) | MAU coil kW (RT) | of which latent kW | recirculation coil kW | total kW (RT) |
|---|---|---|---|---|
| cooling DB/MCWB 33.2/26.3 °C | 194.1 (55.2) | 108.5 | 269.1 | 463.2 (131.7) |
| dehumidification DP/MCDB 27.1/29.4 °C | 217.5 (61.9) | **146.2** | 269.1 | 486.6 (138.4) |
| enthalpy h/MCDB 88.8 kJ/kg / 31.0 °C | **220.5 (62.7)** | 143.2 | 269.1 | **489.6 (139.2)** |

The enthalpy design point governs the MAU coil's total load and therefore the total cooling
(`governing_case_total_cooling`); the dehumidification point gives the largest latent load
(`governing_case_mau_latent`). The two differ by 3.0 kW (1.4 %) in MAU load. MAU reheat to 18 °C
is 28.5 kW in all cases. FFU fan heat (125.1 kW) is close to the tool heat (150 kW).

`results/well_mixed_sweep.csv` gives the supply airflow a well-mixed ISO 7 support area
(1 200 m³, 99.97 % final filter, 10 % outdoor air) needs as a function of particle generation
rate; the generation rates are a sweep, not measured values.

### Chiller plant and NEA MEES
`results/mees_table.csv` reproduces the NEA table (general industrial and the space-cooling row
effective 1 Apr 2026) and the bracketed kW/RT figures to two decimals. The illustrative plant
(4 000 kW cooling, 755 kW total input, CHWS 6.5 °C → 7 °C after NEA's round-up rule) is
0.18875 kWe/kWc = 0.664 kW/RT against a limit of 0.191: PASS (`results/bay_example.json`).
With NEA's instrument limits (±0.05 K, ±1 % flow, ±2 % power) the overall M&V uncertainty stays
within 5 % only when the chilled-water ΔT is at least 1.58 K.

## Part B — Excel VBA

`excel/FabHvac.bas` implements worksheet functions (`FH_*`) for the ISO class limit and inverse,
unidirectional airflow, FFU count, ACH, well-mixed concentration and required airflow, kW/RT ↔
kWe/kWc, COP, plant efficiency, MEES limit and check, heat balance, M&V uncertainty, cooling-tower
range/approach/effectiveness, and PsychroLib-equivalent saturation pressure, humidity ratio
(from RH, wet bulb, dew point), enthalpy, dew point and wet bulb — plus `FillCalcSheet`, which
builds a labelled "Calculator" sheet that uses them. The functions are written to return
`#VALUE!` where Python raises `ValueError`; the parity grid includes those cases. The
psychrometric functions port PsychroLib's coefficients and algorithms (MIT licence; notice in
the `.bas` header and in `THIRD_PARTY_NOTICES.md`).

**Status: the parity check is scripted but has not yet been run in Excel; the workbook has not
been built and the `.bas` code has not been executed.** `scripts/build_xlsm.py` only reads the
"Trust access to the VBA project object model" setting (`AccessVBOM`) and stops if it is off;
it was off when this repository was prepared, so `excel/fab_hvac_calculator.xlsm`,
`results/vba_parity.csv` and `results/vba_parity_summary.json` do not exist yet and the two
VBA golden tests skip. Once the setting is enabled:

```bash
python scripts/build_xlsm.py     # imports the .bas into a private Excel instance, runs FillCalcSheet,
                                 # blanks author metadata and strips the saved-folder path
python scripts/vba_parity.py     # fixed grid over all FH_* functions (incl. invalid inputs) through
                                 # Application.Run vs Python; reads back the Calculator sheet
```

`tests/test_vba_golden.py` then replays the recorded VBA outputs against Python in CI
(rel. tolerance 1e-9; invalid inputs must be rejected by both). Without Excel, CI already checks
that every `Public Function FH_*` in the `.bas` has a Python reference (`tests/test_vba_reference.py`).

## Part C — fault detection and diagnosis

Data: LBNL FDD chiller-plant set — a simulated plant serving a large
office in Chicago, three chillers, primary/secondary chilled-water loops, three cooling towers,
1-minute data for one year. Faults by file name: cooling-tower leaving-water sensor bias (±1, ±2 °C),
chiller-1 leaving-water sensor bias (±1, ±2 °C), secondary-loop differential-pressure (DP) sensor
bias (±10, ±20 %), condenser three-way-valve leakage (25/50/75 %) and stuck (50/75 %), cooling-tower
fouling (heat-transfer multiplier 0.95/0.80/0.65), mis-tuned tower PI loop, and chiller fouling
(0.95/0.65). Windows are 1-hour aggregates (means, plus standard deviations of eight control
signals).

### What the data look like (`results/fdd_data_checks.json`, `results/fdd_scenarios.csv`)

* The archive has 24 files; the documentation lists 22. `chiller_fouling_065/095` are not in the
  documentation and are labelled from the file name.
* `OA_TEMP_WB` is never below `OA_TEMP`, and the tower set point matches max(`OA_TEMP` + 8 °F, 60 °F)
  (the documented wet-bulb reset; 90th-percentile error 0.70 °F, versus 11.2 °F using `OA_TEMP_WB`).
  The two outdoor columns are therefore treated as swapped: `OA_TEMP` = wet bulb.
* The chilled-water set point spans 44.0–54.0 °F; the documentation says 42–52 °F.
* The chillers do not close an energy balance: over the fault-free year, evaporator heat plus
  chiller electric input is 1.278 × condenser heat; median chiller-1 COP is 2.46. As a result only
  **1.0 %** of 1-minute operating points in the fault-free file are within the NEA ±5 % heat
  balance (median imbalance +28.8 %), and 0.05–5.9 % in the faulted files, so the NEA test
  (≥ 80 % of points) fails for every file and cannot certify this simulated instrumentation.
  Chiller-sensor bias does move the median imbalance to between −2 991 % and +3 082 %.
* Fault-free efficiency on delivered (primary-loop) cooling is 4.91 kW/RT = 1.397 kWe/kWc,
  7.5 times the NEA MEES general limit at the plant's load-weighted chilled-water supply
  temperature (8.32 °C → 0.185 kWe/kWc) (`results/fdd_summary.json`). Absolute kW/RT from this
  simulation is not comparable with a real plant, so only relative changes are used below.
* Valve leakage and valve stuck at the same opening produce nearly the same plant: annual plant
  energy 819 188 vs 819 194 kWh at 75 %.

### Energy effect of each fault (`results/fdd_energy.csv`)

kW/RT is computed on cooling delivered by the primary loop (sensors on which no fault is imposed).
The simulated plant is pump-dominated: of its 1 236 MWh fault-free annual energy, pumps (primary,
secondary and condenser) use 67.5 %, chillers 31.0 % and tower fans 1.5 %
(`fdd_summary.json`, `fault_free_energy_split`) — a split specific to this simulation (its
fault-free efficiency is also 7.5 times the MEES limit, see above). Relative penalties from this
plant are therefore not transferred onto a real plant or onto the MEES line; instead the last
three columns show where each fault's energy change comes from, in percent of fault-free plant
energy (they sum to the plant column; `*_kwh_delta_pct_of_plant`).

| Fault (severity) | plant kWh | delivered cooling | kW/RT | hours CHWS > set point + 1 K | chillers | pumps | tower fans |
|---|---|---|---|---|---|---|---|
| valve leakage 25 % | −1.2 % | −30.6 % | +42.4 % | 26.0 % | +4.5 | −4.3 | −1.4 |
| valve leakage 75 % | −33.7 % | −83.3 % | +298 % | 45.6 % | −21.1 | −11.3 | −1.3 |
| valve stuck 50 % | −21.2 % | −66.6 % | +136 % | 35.8 % | −12.0 | −7.8 | −1.4 |
| chiller sensor bias −2 °C | +22.7 % | −9.1 % | +35.0 % | 90.9 % | −2.9 | +25.7 | −0.1 |
| chiller sensor bias +2 °C | −25.5 % | +3.1 % | −27.8 % | 0 % | +2.6 | −28.2 | +0.1 |
| chiller fouling 0.65 | +6.7 % | −4.1 % | +11.2 % | 8.1 % | +11.6 | −5.0 | +0.1 |
| tower PI mis-tuned | +2.0 % | −1.1 % | +3.2 % | 1.6 % | +1.8 | +0.8 | −0.5 |
| tower sensor bias −2 °C | +0.9 % | −0.005 % | +0.9 % | 0 % | +1.1 | +0.2 | −0.5 |
| tower fouling 0.65 | +1.9 % | −0.007 % | +1.9 % | 0 % | +0.6 | +0.6 | +0.6 |
| DP sensor bias −20 % | +6.6 % | +0.005 % | +6.6 % | 0 % | 0.0 | +6.6 | 0.0 |
| DP sensor bias +20 % | −12.1 % | +0.6 % | −12.6 % | 0 % | +0.1 | −12.2 | 0.0 |

Most of the large swings are pump energy (chiller-sensor bias and DP-sensor bias change pump
staging and speed); only chiller fouling and the valve faults move chiller energy by more than a
few percent of the plant.

The condenser-valve faults cut energy use because the plant stops delivering cooling. The
apparent improvements from positive chiller-sensor bias and positive DP-sensor bias come with
changed operation; for chiller bias +2 °C the largest change is secondary pump 2 running 15 % of
the time instead of 64 % (`sec_pump2_on_frac`). These are properties of this simulated control
sequence, not general claims.

### Detection (`results/fdd_detection_by_type.csv`, `results/fdd_detection.csv`)

Main split: odd months train, even months test, 24 h removed from the test side of each month
boundary; 105 960 training and 97 344 test windows. Training and test months interleave, so they
share seasons and weather regimes; the season-block check below tests the other case.
Baseline = 16 physics residuals (plant and chiller power, chiller-1 COP, tower approach, tower-minus-set-point, condenser-supply-minus-tower,
chiller-1-minus-header supply, chilled-water supply error, lift, heat balance, DP error, valve
position, fan and pump speed, two variability signals) from degree-2 ridge models of outdoor dry
and wet bulb, building load, set point and chillers on, fitted on fault-free training months only.
ML = HistGradientBoosting on 119 window features, trained on all classes in the training months.

Hourly recall at two operating points. *Deployable*: threshold fixed in advance as the 99th
percentile of out-of-fold fault-free *training* scores. *1 % FAR (test)*: threshold set so that
1 % of held-out fault-free test windows alarm — an ROC point that uses test data, for comparing
the methods at equal false-alarm rate, not a setting one could deploy.

| Fault type | residual baseline, deployable | residual baseline, 1 % FAR (test) | gradient boosting, deployable | gradient boosting, 1 % FAR (test) |
|---|---|---|---|---|
| *fault-free windows alarming (FAR)* | *0.0059* | *0.0099* | *0* | *0.0099* |
| valve leakage | 0.643 | 0.657 | 1.000 | 1.000 |
| valve stuck | 0.781 | 0.803 | 0.977 | 1.000 |
| chiller sensor bias | 0.943 | 0.948 | 0.998 | 1.000 |
| chiller fouling | 0.030 | 0.040 | 0.938 | 0.990 |
| tower PI mis-tuned | 0.052 | 0.064 | 0.598 | 0.930 |
| tower sensor bias | 0.368 | 0.410 | 0.848 | 0.985 |
| tower fouling | 0.006 | 0.010 | 0.024 | 0.328 |
| DP sensor bias | 0.005 | 0.009 | 0.035 | 0.575 |

At the deployable thresholds gradient boosting raises no false alarm on the test months but its
recall drops sharply for the subtle faults (tower PI, tower fouling, DP bias). The residual
baseline does not separate tower fouling, DP-sensor bias, chiller fouling 0.95 or tower bias
±1 °C from normal (recall ≈ FAR). Tower fouling 0.95 is the hardest case for the ML model (0.155
at 1 % FAR). Day-level rates per file (a day alarms if any hour does) are in
`results/fdd_detection_daily.csv`.

### Season-block check (`results/fdd_season_split.csv`, `fdd_summary.json` → `season_block_splits`)

The main split interleaves months. As a harder test, the models were refitted on one half-year
and tested on the other (24 h removed at both ends of the test half; deployable thresholds
re-derived from the training half). Gradient-boosting hourly recall at 1 % FAR on test, and the
false-alarm rate its deployable threshold actually produces:

| | main split (odd/even months) | train Jan–Jun, test Jul–Dec | train Jul–Dec, test Jan–Jun |
|---|---|---|---|
| valve leakage | 1.000 | 0.953 | 1.000 |
| valve stuck | 1.000 | 0.999 | 0.232 |
| chiller sensor bias | 1.000 | 0.939 | 0.951 |
| chiller fouling | 0.990 | 0.160 | 0.895 |
| tower PI mis-tuned | 0.930 | 0.208 | 0.015 |
| tower sensor bias | 0.985 | 0.840 | 0.295 |
| tower fouling | 0.328 | 0.023 | 0.001 |
| DP sensor bias | 0.575 | 0.343 | 0.015 |
| realised FAR at the deployable threshold | 0 % | 0.78 % | **39.1 %** |
| argmax classifier: normal-class recall / 9-class accuracy | 0.589 / 0.956 | 0.448 / 0.837 | 0.089 / 0.717 |

The main-split figures for gradient boosting are therefore an in-season estimate: when the test
season was not in training, recall at 1 % FAR collapses for the subtle faults (tower PI, tower
fouling, DP bias, and in one direction chiller fouling and valve stuck), and a threshold set on
July–December training data raises false alarms in 39 % of January–June fault-free hours. The
residual baseline, fitted on fault-free data only, changes less (realised deployable FAR 0.59 %,
1.33 %, 1.61 %; valve-leakage recall at 1 % FAR 0.657, 0.716, 0.703) but stays weak on the same
subtle faults. With one simulated year there is no way to test on an unseen year.

### Diagnosis (`results/fdd_summary.json`, `results/fdd_confusion_*.csv`)

All 97 344 test windows, 9 classes including normal. The plain classifier (argmax over the 9
classes) has no detection threshold; to compare like with like, both methods are also scored
**two-stage**: below the method's detection threshold a window is *normal*, above it the most
likely fault (gradient boosting) or the nearest fault signature (baseline, the median residual
vector of alarming training windows).

| | normal-class recall (4 056 fault-free windows) | 9-class accuracy | 9-class macro-F1 | faulted windows given the right fault type |
|---|---|---|---|---|
| gradient boosting, argmax (no threshold) | **0.589** | 0.956 | 0.931 | 0.972 |
| gradient boosting, two-stage at deployable threshold | 1.000 | 0.667 | 0.657 | 0.652 |
| gradient boosting, two-stage at 1 % FAR (test) | 0.990 | 0.835 | 0.829 | 0.828 |
| residual baseline, two-stage at deployable threshold | 0.994 | 0.210 | 0.202 | 0.176 |
| residual baseline, two-stage at 1 % FAR (test) | 0.990 | 0.213 | 0.204 | 0.179 |

The argmax classifier's 0.956 accuracy hides that it leaves only 2 389 of the 4 056 fault-free
test windows as normal: 1 667 (41.1 %) are flagged as faults — 1 316 as tower fouling, 284 as
DP-sensor bias, 58 as tower PI — because the mildest fault levels are close to normal operation
(`fdd_confusion_ml.csv`). With its deployable detection threshold in front, no fault-free window
is flagged, but 11 879 of 12 168 tower-fouling and 15 652 of 16 224 DP-bias windows are then
called normal (`fdd_confusion_ml_deployable.csv`). Most of the baseline's errors are faulted
windows below its threshold (`fdd_confusion_baseline.csv`); metrics in `fdd_summary.json`
(`diagnosis`).

### Unseen severities (`results/fdd_loso.csv`)

Each severity of each multi-severity fault was removed from training in turn (22 runs). ML recall
at 1 % FAR on the held-out severity:

* mild levels drop sharply when not seen in training — tower fouling 0.95: 0.029 (0.155 when seen),
  DP bias −10 %/+10 %: 0.105/0.136 (0.406/0.427), tower bias −1/+1 °C: 0.221/0.525 (0.983/0.962);
* strong levels transfer — tower bias ±2 °C ≥ 0.995, chiller bias ±2 °C 1.000, DP bias −20 %: 0.825;
* held-out valve leakage 75 % and stuck 75 % are detected (1.000) but never labelled with their
  own type (0.000), because the remaining training data contain the other, nearly identical,
  valve fault.

The baseline's detection does not use fault data, so its LOSO recall equals its main-split recall;
its type accuracy on unseen severities is at most 0.472.

Development note: the residual baseline was revised twice after its first test results were seen
(MAD scaling → per-residual 99th-percentile scaling, because heavy-tailed residuals dominated
max|z|; one-stage nearest-centroid → threshold, then nearest fault signature). Both changes are
fitted on training data only, but the test months had been looked at before making them.

## Part D — facilities maintenance analytics

**Data.** No facility work-order set with a stated open licence could be obtained from MaintNet
(Akhbardeh et al. 2020; its facility data are no longer distributed, see `docs/sources.md`).
Part D uses the NYC Parks *Asset Management Parks System* (AMPS) tables on NYC Open Data, which
NYC's Open Data Law makes available "without any registration requirement, license requirement
or restrictions on their use": 2 224 030 work orders (2009 to 29 Sep 2026), 148 450 assets and
booked labour for 1 060 487 orders, downloaded 2 Oct 2026 (row counts and SHA-256 in
`results/maintenance_data_checks.json`). These are real records of a city parks department —
buildings, pools, plumbing, electrical, heating plant — not a fab. Raw data and free text are not
in the repository; `results/` holds aggregates only. No synthetic work orders are used.

**Work-order model** (`workorder.py`, `amps.py`). Canonical CMMS fields (site → system → asset,
asset class, PM / CM / INSP, status, failure mode, opened / closed, labour, downtime) and 13
row-level validation rules. Findings on AMPS (`maintenance_data_checks.json`): 440 orders closed
before they were reported, 76 917 without a maintenance district, 35 337 closed orders open for
more than a year; the source records **no equipment downtime**, so restore time below is the
time an order was open (reporting, waiting, travel, repair), not wrench time. Of 7 626
corrective orders on HVAC-class equipment, 76 % are routine water-treatment, blowdown, start-up
or inspection tasks logged as corrective; 365 of 1 621 HVAC-class assets carry a 1900-01-01
placeholder commissioning date (asset age unknown) and none has a parent link; the class `EXTHD`
holds 285 external hard drives, not exhaust hoods.

**Reliability, 2021-01-01 to 2026-09-29** (`maintenance_reliability_by_class.csv`,
`maintenance_boiler_modes.csv`, `maintenance_repeats.json`). Failures = closed corrective orders
on HVAC equipment that are not routine or new work (658 orders); overlapping orders on one asset
are one episode. Calendar time (a year = 8 766 h).

| asset class | assets | failure episodes | MTBF (years) | restore time mean / median (h) | availability (mean / median restore) |
|---|---|---|---|---|---|
| BOILER | 346 | 433 | 4.36 | 2 600 / 104 | 0.936 / 0.997 |

MTBF is given for boilers only. The other classes have very few recorded failure episodes (17 on
247 HVAC units, 13 on 328 pumps in 5.7 years); inverted into an MTBF these would describe how
rarely failures are logged against these assets, not how reliable they are: 76 % of corrective orders on HVAC-class
equipment are routine tasks, building-wide requests are often filed against a building or a fuel
tank rather than the unit, and no asset has a parent link. They are therefore reported only as
**recorded corrective episodes per asset-year** (`episodes_per_asset_year`): HVAC units 0.012,
pumps 0.0069, hot-water heaters 0.0041, cooling towers 0.020 (2 episodes on 18 towers), against
0.23 for boilers.

**Failure modes are mostly model output.** 90 of the 658 failure orders (13.7 %) carry one of the
seven building-services problem codes. For the other 568 the text classifier below assigns a mode
only if its top probability is at least 0.87 (the threshold at which validation-year orders it
labels are right 95 % of the time); 130 orders get a predicted mode and 438 (77 %) are left as
"(none)": most equipment-failure texts do not clearly match any of the seven codes, which were
designed for building-services requests (`maintenance_data_checks.json`,
`equipment_failure_funnel`). For boilers (`maintenance_boiler_modes.csv`):

| boiler episodes | n | *No Heat* | *Leaking* | electrical | other coded modes | "(none)" |
|---|---|---|---|---|---|---|
| mode from the problem code | 54 | 40 (74 %) | 8 (15 %) | 1 | 5 | — |
| mode predicted by the text model (model output) | 93 | 86 | 4 | 3 | 0 | — |
| model abstained | 286 | — | — | — | — | 286 |

The predicted modes inherit the model's reliability caveat: its 0.84 test accuracy was measured on
coded building-services orders, not on equipment-failure orders (HVAC-trade orders in that
test set: macro-F1 0.61), and no equipment-failure order was hand-labelled to check it. Only the
54 coded episodes are direct evidence that *No Heat* dominates boiler failures.

30.7 % of boiler episodes start within 30 days of the previous one on the same boiler (3.9 %
with the same known mode, but only 147 of 433 episodes have a known mode); 12 boilers (the top
10 % of those that failed) account for 48.0 % of episodes, one for 59.
For *No Heat* calls logged on buildings (1 338 episodes, 556 buildings) the 30-day repeat share
is 15.2 %. Across 39 013 closed building-services corrective orders (`maintenance_pareto.csv`)
there is no "vital few": five of the seven modes are needed to reach 80 % of orders (*Clogged*
25.3 %, *Leaking* 25.2 %, *No Water* 14.0 %, electrical 11.1 %, *No Heat* 8.6 %).

**Weibull and PM interval** (`weibull.py`; formulas from Nakagawa 1981, eq. 2.1/2.4/2.5, after
Barlow & Proschan 1965). The censored MLE was first checked by simulation
(`maintenance_weibull_selfcheck.json`, data-free, true β = 1.8, η = 1 000 d, 46 % censored, 400
data sets of 40 units): η bias +0.7 %, 95 % CI coverage 0.92 (β) and 0.94 (η); dropping censored
units gives η −35 %, counting them as failures η −27 %. On boiler uptimes (432 intervals, 128
censored, `maintenance_weibull_boiler.json`): **β = 0.40**, η = 486 days; ignoring censoring
would give η = 88 days. The intervals are not independent — they come from only 129 of the 346
boilers (those with at least one failure episode in the window; the interval before a boiler's
first episode is unused, so boilers that never failed contribute nothing), and the top 10 % of
those boilers supply 48 % of the intervals (one supplies 59). A bootstrap that resamples whole
boilers (2 000 resamples, `fit_cluster_bootstrap_by_boiler`) gives 95 % intervals β 0.35–0.48 and
η 223–1 257 days, against 0.36–0.44 and 366–645 days from the likelihood, which treats every
interval as independent. β < 1 holds also for uptimes that already lasted 30 days (β = 0.55,
by-boiler bootstrap 0.50–0.61). A decreasing hazard means an age-based replacement or overhaul
interval has no finite optimum for any cost ratio (checked for c_f/c_p = 1.5–50); with the
concentration above, the data point to fixing repeat offenders and repairs that do not hold
rather than to scheduled replacement. The pooled β cannot separate repairs that do not hold,
differences between boilers, and several tickets per outage. For wear-out failures (β > 1) the
data-free table `maintenance_pm_sensitivity.csv` gives the optimum: at β = 2 the optimal age is
0.51 η and saves 28 % against run-to-failure for c_f/c_p = 5, 0.34 η and 46 % for 10.

**Text classification** (`textclass.py`, `maintenance_textclass*.csv|json`). Description →
one of the seven building-services problem codes. Train: created before 2023 (87 998 orders);
validation: 2023 (7 153; the rules were revised once here; the model's regularisation is fixed
at C = 1, not tuned); test: 2024 onward (19 796). Majority-class accuracy is 0.256.

| test set | n | rules: accuracy / macro-F1 (coverage) | TF-IDF + logistic regression: accuracy / macro-F1 | same model, abstaining below p = 0.87: coverage / accuracy on labelled |
|---|---|---|---|---|
| all | 19 796 | 0.713 / 0.750 (0.848) | 0.838 / 0.820 | 0.573 / 0.949 |
| description not seen in training | 17 854 | 0.696 / 0.737 | 0.829 / 0.814 | 0.543 / 0.947 |
| HVAC trades (steamfitter, stationary engineer, thermostat repair, oiler) | 457 | 0.761 / 0.408 | 0.880 / 0.612 | 0.694 / 0.953 |

The abstain threshold (0.87) was chosen on the validation year (smallest threshold with ≥ 95 %
accuracy on the orders the model labels; validation coverage 0.549) after the test scores of the
plain model above had been seen; it was then applied to the test set and to the equipment
failure orders without further change.

Rules abstain on 15 % of orders and put 582 *Not working electrical* orders into *No Light*; the
model's weakest class is *Will not turn off* (F1 0.72): it labels 569 orders coded *Leaking* as
*Will not turn off* — in the validation errors these were typically running faucets or toilets
coded as leaks. The labels are requester-chosen codes, so part of the remaining error is label
noise.

**Local LLMs** (`scripts/maint_llm.py`, optional; qwen2.5:3b and gemma3:4b via Ollama, zero-shot,
label only, one description per request, metrics with 95 % Wilson intervals computed in Python,
output `maintenance_textclass_llm.json`). No LLM result is reported here. An earlier run sent 25
descriptions per request; its scores (about 0.33) measured answers drifting out of order, not the
models, and were discarded. The one-per-request rerun on the stratified 350-order test sample
did not complete — the local Ollama server stopped answering during the second model — so
`maintenance_textclass_llm.json` is not in `results/`.

**8D report.** `docs/8D_chiller_example.md`: cooling-tower fouling in the LBNL simulation. At the
severe level plant energy rises 1.85 % for the same cooling. At their deployable thresholds the
Part C residual baseline is blind to the fault (it alarms on 11 % of test days whether fouled or
not), while gradient boosting alarms on 24.9 / 2.4 / 0 % of test days (severe → mild) with no
fault-free day alarming. Paired fault/fault-free hours localise the cause to tower 1, and a
chiller-lift rule separates it from the tower-sensor bias that mimics it. A daily residual
indicator on tower-1 leaving water, compared day by day with the Part C detectors at thresholds
that leave no fault-free test day alarming (test-calibrated, comparison only), flags 97.6 / 89.3
/ 30.2 % of days against 55.0 / 28.4 / 2.4 % for gradient boosting; at its training-calibrated
threshold it flags 36.7 / 0 / 0 % (`maintenance_8d_*`, `fdd_detection_daily.csv`).

## Tests

`pytest` collects 256 tests: 253 run everywhere, the 2 VBA golden-replay tests skip until
`results/vba_parity.csv` exists, and 1 test checking the FDD cache against
`results/fdd_scenarios.csv` runs only when `LBNL_FDD_CACHE` is set. Test values are deliberately
asymmetric (e.g. 0.18875 kWe/kWc, 6.01 °C, 102.4 m² × 0.45 / 0.72 m² to provoke float round-up)
and include independent checks: a time-stepped integration of the particle balance, hand-computed
heat balances, the published ISO, NEA and ASHRAE tables, and CoolProp. Part D tests need no
data: the Weibull fit is checked against SciPy's censored fit and a numerical Hessian, the PM
optimum against direct minimisation and Nakagawa's eq. 2.5, the Wilson interval against SciPy's
`binomtest`, the cluster bootstrap against a hand re-computation, the metrics against
hand-computed cases.

Mutation testing (`scripts/mutate.py`, `results/mutation_report.json`): 129 deliberate bugs are
applied one at a time with the byte-for-byte golden-output test excluded, so each must be caught by
a unit test. 127 of 127 non-equivalent mutants are killed, 50 of them in `fabhvac/maintenance/`
and 32 in `fabhvac/fdd/`; they include the season split, two-stage diagnosis, day-level
aggregation, enthalpy design state, by-boiler bootstrap, abstain rule and Wilson interval added
in this revision (two of those survived their first run — the "faulted windows correct" metric
and the bootstrap's percentile level — and the tests were tightened until they failed). Two
mutants are equivalent and documented
in the script: `t <= 9` → `t < 9` in the MEES lookup (the progressive formula gives the same
0.185 at 9 °C) and removing the gradient-boosting seed (no random numbers are drawn with early
stopping off, all features used and fewer than 200 000 training rows).

## Data and attribution

Third-party notices required by licences (PsychroLib MIT text for the VBA port, CC BY 4.0
attribution) are collected in [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

LBNL FDD chiller-plant data: Granderson, Jessica, et al. *LBNL Fault Detection and Diagnostics
Datasets.* Lawrence Berkeley National Laboratory, 1 August 2022, Open Energy Data Initiative
(OEDI), https://doi.org/10.25984/1881324, licensed CC BY 4.0
(https://creativecommons.org/licenses/by/4.0/). File used:
https://fdddata.lbl.gov/data/Simulated_LBNL_FDD_Data_Sets_Chiller_Plant/LBNL_FDD_Data_Sets_Chiller_Plant.zip
(1 570 938 957 bytes, last modified 16 Jul 2025, 24 CSV files, SHA-256
`058a8cc4…7f7f1cb`, full hash in `docs/sources.md`); the LBL page still describes 21 CSV files
and 1.14 GB, so this is a later re-issue. Changes: hourly aggregation, swapped outdoor columns,
derived signals and model results. Raw data are not redistributed; `results/fdd_*.csv|json` and
`results/maintenance_8d_*` are summaries derived from them.

NYC Parks AMPS work orders, assets and labour: NYC Department of Parks and Recreation, *Asset
Management Parks System (AMPS)*, NYC Open Data (datasets 8sdw-8vja, e25p-jzfy, xzj8-i3jk),
snapshot downloaded 2 Oct 2026 (SHA-256 of the cached files in
`results/maintenance_data_checks.json`). Made available under the NYC Open Data Law (NYC Admin.
Code §23-502(d)) without licence requirement; modifications are the mapping in
`fabhvac/maintenance/amps.py`. Raw data are not redistributed; `results/maintenance_*` are
aggregates.

Singapore design conditions: ASHRAE Handbook — Fundamentals 2021 climatic design data as shown
on ashrae-meteo.info. NEA MEES values are indicative per NEA; the legally binding values are in
the Fifth Schedule of the Energy Conservation (Energy Management Practices) Regulations on
Singapore Statutes Online, which was not checked. NEA's M&V guideline PDF words the 1 Apr 2026
space-cooling limits differently from the web page used here (see `docs/sources.md`).

## Limitations

* **Example inputs are illustrative.** Room conditions, face velocity, FFU power, tool heat,
  make-up airflow and moisture gain in `examples/bay_example.json` are not taken from any
  standard or facility; the worked example shows the method, not design values.
* **Well-mixed particle model** neglects deposition, re-entrainment, leakage and
  non-ideal mixing, and uses one filter efficiency per particle size. It does not apply to
  unidirectional-flow zones.
* **MAU model** neglects condensate enthalpy and fan heat in the MAU, assumes the coil-leaving
  dry bulb is a fixed margin above the required dew point, and assigns all latent load to the MAU.
* **ISO 14644-1** was checked against a secondary source (the standard is paywalled); only the
  formula is used, not the 2015 edition's choice of blank cells.
* **NEA MEES** values are NEA's indicative web table, not the legal Fifth Schedule text (Singapore
  Statutes Online); NEA's own M&V PDF describes the 1 Apr 2026 row in different words.
* **LBNL dataset** is a simulation of a Chicago office plant, not a semiconductor fab or a
  Singapore plant. Its absolute efficiency and energy balance are not representative (see
  Part C), so only relative fault effects are interpreted.
* **FDD evaluation** uses one simulated year, one plant and one weather file; windows from the
  same month are autocorrelated, so the effective sample size is much smaller than the window
  count. The main split interleaves months; across a season block the gradient-boosting results
  degrade sharply (see the season-block check). Results say how separable these simulated faults
  are, not how a deployed system would perform.
* **AMPS work orders** come from a parks department, not a fab: few HVAC units, no chiller asset
  class, no downtime field, calendar rather than running time, and equipment links that are
  sometimes wrong (building-wide requests filed against a fuel tank). Restore times are ticket
  durations and include synchronisation delays the data dictionary mentions. Only 54 of 433
  boiler failure episodes (12.5 %) have a coded failure mode; for the rest the mode is text-model
  output (93) or unknown because the model abstained (286), and the model's accuracy was measured
  on a different population (coded building-services orders). MTBF is reported for boilers only;
  for other classes the episode rate reflects recording practice.
  The routine-task and new-work rules are keyword rules written from the equipment-order text.
* **Text-classification labels** are codes chosen by the requester; their own error rate is
  unknown, so test scores measure agreement with those codes.
* **Weibull fit** pools 129 boilers under an as-good-as-new-after-repair assumption; asset ages
  are unknown, so the interval before each boiler's first failure in the window is not used and
  the 217 boilers without a failure episode do not enter the fit. Intervals cluster by boiler;
  the by-boiler bootstrap interval, not the likelihood interval, is the one to quote.
* **8D report** is simulation-level throughout (see the report's header).
