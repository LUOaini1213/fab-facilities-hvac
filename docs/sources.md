# Sources of external constants

Every external value used by the code is listed here with the page it was read from and
the retrieval date. All pages were fetched and read on **2026-10-02**. Where a value is a
transcription of a table, the test that pins it is named.

## Singapore NEA — Minimum Energy Efficiency Standards (MEES)

URL: https://www.nea.gov.sg/our-services/climate-change-energy-efficiency/energy-efficiency/industrial-sector/minimum-energy-efficiency-standards

| Item | Value as published | Used in |
|---|---|---|
| Scope | electrically-driven water-cooled chilled-water systems in industrial facilities with total installed capacity of 1055 kW (300 RT) or more (operating + standby chillers) and chilled water at 3 °C or higher; brine/glycol-only chillers exempt | `chiller.mees_in_scope` |
| Table 1, general | CHWS 3/4/5/6/7/8/9 °C → 0.203/0.200/0.197/0.194/0.191/0.188/0.185 kWe/kWc (0.71/0.70/0.69/0.68/0.67/0.66/0.65 kW/RT) | `chiller.MEES_GENERAL`, `tests/test_chiller.py` |
| CHWS ≥ 10 °C | "to be improved from 0.185 kWe/kWc at 9 °C by 0.003 kWe/kWc for every 1 °C increase" | `chiller.mees_limit_kwe_per_kwc` |
| Table 1, second row | "(With effect from 1 Apr 2026) Only for premises comprising a new building with water-cooled chilled water systems used solely for space cooling": 3/4/5/6 °C → 0.191/0.188/0.185/0.182; 7, 8, 9 and ≥10 °C (one merged cell) → 0.179 kWe/kWc (0.63 kW/RT). The page says space cooling includes clean rooms. | `chiller.MEES_SPACE_COOLING_NEW_BLDG*` |
| Footnote 3 | chilled-water supply temperature "to be rounded up to the nearest whole number" | `chiller.mees_rounded_chws` |
| Footnote 4 | figures are indicative; the specified MEES are in the Fifth Schedule of the Energy Conservation (Energy Management Practices) Regulations | stated in README; the legally binding text is that Schedule as published on Singapore Statutes Online (https://sso.agc.gov.sg); **it was not read** |
| Footnotes 5–6 | kWe/kWc = total chilled-water-system energy (kWhe) ÷ total cooling produced (kWhc) over the assessment period; kW/RT likewise with RTh | `chiller.plant_efficiency_kwe_per_kwc` |
| M&V accuracy | heat-balance substantiating test "within 5% for 80% of the operating points" | `chiller.heat_balance_test` |

## NEA — Requirements and Guidelines on M&V for MEES (PDF)

URL: https://www.nea.gov.sg/docs/default-source/cmd-documents/energy-efficiency/requirements-and-guidelines-on-mv-for-mees_280425-3.pdf (linked from the MEES page)

| Item | Value as published | Used in |
|---|---|---|
| System heat balance (p.12) | (cooling load + work input − heat rejection) / heat rejection × 100 %, within ±5 % for ≥ 80 % of data points | `chiller.heat_balance_pct`, `heat_balance_test` |
| Work input (p.12) | hermetic: measured power × VSD rated efficiency; open-type: × motor rated efficiency × VSD rated efficiency | `chiller.compressor_work_input_kw` |
| Reference formulae (p.13) | chilled water Cp ≈ 4.19 kJ/(kg·°C); condenser water Cp ≈ 4.18; 1 L/s ≈ 1 kg/s; RT = kW / 3.517 | `units.NEA_*`, `chiller.cooling_load_kw`, `heat_rejection_kw`, FDD heat balance |
| Instrument uncertainty (p.7) | temperature ±0.05 °C, flow ±1 %, power ±2 % (end-to-end); overall √(ΔU_T² + U_F² + U_P²) ≤ 5 % with ΔU_T = √(U_T(CHWST)² + U_T(CHWRT)²)/ΔT_CHW | `chiller.mv_system_uncertainty_pct`, `min_chw_delta_t_for_uncertainty` |

The PDF words the tighter 1 Apr 2026 levels differently from the web page: it applies them to
"New Industrial Facilities (NIF) that apply for planning permission or equivalent from 1 Apr
2026 onwards and install WC-CWS dedicated for space cooling purposes" and gives them in kW/RT
only (0.67/0.66/0.65/0.64 at 3–6 °C, 0.63 at 7 °C and above), whereas the web page says
"premises comprising a new building that require Planning Permission (PP) or equivalent and
have WCCWS that is used solely for space cooling" and gives kWe/kWc with kW/RT in brackets. The
code uses the web page's kWe/kWc values; neither text is the legal one (see footnote 4).

## NIST SP 811, Appendix B.9 (conversion factors)

URL: https://www.nist.gov/pml/special-publication-811/nist-guide-si-appendix-b-conversion-factors/nist-guide-si-appendix-b9

| Conversion | Factor | Used in |
|---|---|---|
| ton of refrigeration (12 000 Btu_IT/h) → W | 3.516 853 E+03 | `units.RT_TO_KW` (NEA's 3.517 is kept separately as `NEA_RT_TO_KW` and not used for conversions) |
| ft/min → m/s | 5.08 E-03 | `units.FPM_TO_M_S` |
| ft³/min → m³/s | 4.719 474 E-04 | `units.CFM_TO_M3_S` |
| gal (U.S.)/min → m³/s | 6.309 020 E-05 | `units.GPM_TO_M3_S` (LBNL data are in GPM) |
| inch of water, conventional → Pa | 2.490 889 E+02 | `units.INH2O_TO_PA` |
| °F → °C | t/°C = (t/°F − 32)/1.8 | `units.f_to_c` |

## ISO 14644-1 class concentration limit

ISO 14644-1 itself is paywalled (the ISO preview page returned HTTP 403). The formula and
table were verified from a book chapter that is available on PubMed Central:

Xu, Zhonglin. "Classification of Air Cleanliness." In *Fundamentals of Air Cleaning Technology
and Its Application in Cleanrooms*, Springer-Verlag Berlin Heidelberg, © 2014 (chapter
published online 14 August 2013), pp. 339–376. doi:10.1007/978-3-642-39374-7_7.
URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC7498890/

* Access: PMC carries the chapter in its COVID-19 open-access subset; the PMC licence note
  grants re-use "for the duration of the World Health Organization (WHO) declaration of
  COVID-19 as a global pandemic", so this free access may be withdrawn.
* Eq. (7.1) N_D = N_d (d/D)^n with "n = 2.08 in JIS B9920 and ISO14644-1"; the table
  (Table 7.6, "Air cleanliness classification in ISO 14644-1 and GB50073-2001") lists
  10^N particles/m³ at 0.1 µm for class N. Together: Cn = 10^N × (0.1/D)^2.08.
* All 37 non-blank cells of Table 7.6 are reproduced by the formula rounded to three
  significant figures and to whole particles — `tests/test_cleanroom.py`.
* Limitation: the chapter describes the 1999 edition. The 2015 edition text was not
  available to check (e.g. which cells it leaves blank); the code uses only the formula.

## ASHRAE climatic design conditions — Singapore Changi

URL: https://ashrae-meteo.info/v3.0/index.php?lat=1.367&lng=103.983&place=%27%27&wmo=486980&ashrae_version=2021&si_ip=SI
("2021 ASHRAE Handbook - Fundamentals (SI)", SINGAPORE CHANGI INTL, WMO 486980, period 94-19,
elevation 7 m, standard pressure 101.24 kPa). Values transcribed into `fabhvac/design_data.py`:
cooling 0.4 % DB/MCWB 33.2/26.3 °C, 1 % 33.0/26.2 °C; dehumidification 0.4 % DP/HR/MCDB
27.1 °C/22.8 g/kg/29.4 °C, 1 % 26.8/22.4/29.2, 2 % 26.2/21.7/28.7; humidification 99.6 % DP/HR
20.7/15.4, 99 % 21.1/15.8; enthalpy 0.4 % 88.8 kJ/kg at MCDB 31.0 °C.
The worked example evaluates the MAU at all three 0.4 % points (cooling DB/MCWB,
dehumidification DP/MCDB, enthalpy h/MCDB). Consistency check: for each published (DP, HR) pair,
the humidity-ratio interval that PsychroLib gives at 101.24 kPa for the dew point's rounding
interval (DP ± 0.05 °C) overlaps the published humidity ratio's rounding interval
(HR ± 0.05 g/kg) — `tests/test_psychro_loads.py`.

## Psychrometric equations

PsychroLib 2.5.0 (MIT licence), https://github.com/psychrometrics/psychrolib, which implements
ASHRAE Handbook — Fundamentals (2017) ch. 1. The VBA port in `excel/FabHvac.bas` copies its
coefficients; the coefficient set in the installed package was compared with
`src/python/psychrolib/__init__.py` on the GitHub master branch (identical, 2026-10-02). As the
MIT licence requires, its copyright line ("Copyright (c) 2018-2020 The PsychroLib Contributors.")
and permission notice are reproduced in the header of `excel/FabHvac.bas` and in
`THIRD_PARTY_NOTICES.md` (licence text from the repository's `LICENSE.txt`).
Independent cross-check: CoolProp 8.0.0 `HAPropsSI` (real-gas humid-air model) —
`scripts/psychro_crosscheck.py`, `results/psychro_crosscheck_summary.json`.

## HEPA efficiency used in the illustrative example

NASA MSFC-STD-246E (2019), https://standards.nasa.gov/sites/default/files/standards/MSFC/E/0/msfc-std-246e.pdf :
"HEPA filter, 99.97% efficient for removing ≥0.3 μm particles". The example applies 0.9997 at
0.5 µm as an illustrative assumption (`examples/bay_example.json`), not as a filter rating.

## LBNL Fault Detection and Diagnostics Datasets (chiller plant)

Granderson, Jessica, et al. *LBNL Fault Detection and Diagnostics Datasets.* Lawrence Berkeley
National Laboratory, 1 August 2022, Open Energy Data Initiative (OEDI).
https://doi.org/10.25984/1881324 — submission page https://data.openei.org/submissions/5763,
licence Creative Commons Attribution 4.0 (https://creativecommons.org/licenses/by/4.0/, the
licence field of the OEDI page). Documentation: "LBNL Fault Detection and Diagnostics Data
Sets: Chiller Plant", Granderson, Lin, Chen, Casillas (LBNL), Huang, Vrabie (PNNL), September 1, 2022.
Fault list, severities, units and control sequences were taken from that PDF; where the data
disagree with it, see `results/fdd_data_checks.json`.

File actually used (downloaded 2026-10-02):
https://fdddata.lbl.gov/data/Simulated_LBNL_FDD_Data_Sets_Chiller_Plant/LBNL_FDD_Data_Sets_Chiller_Plant.zip
— 1,570,938,957 bytes, server `Last-Modified: Wed, 16 Jul 2025 20:43:22 GMT`, SHA-256
`058a8cc420dbb7772c3aa56bf118c98612fd91a64780b8a023ada4f2c7f7f1cb`, containing 24 CSV files.
The LBL dataset page (https://faultdetection.lbl.gov/dataset/simulated-chiller-plant/, read
2026-10-02) still describes this download as "21.csv files ... for 7 faults at different
severity levels and 1 fault-free case", ZIP (1.14 GB), so the file served now is a later
re-issue of the archive than the page text describes (it also contains the two
`chiller_fouling` files that the PDF does not list).

Documentation inconsistency: the text under eq. (3) gives the minimum of the condenser-water
(tower) set-point reset as 34 °F, while Table 1 of the same PDF says the water leaving the towers
"is constrained to be greater than 60 °F". The data follow max(wet bulb + 8 °F, 60 °F)
(`results/fdd_data_checks.json`, 90th-percentile error 0.70 °F); the repository follows 60 °F.

Table 1 of the PDF ("Local controllers") states: "The activation of one chiller also corresponds
to the activation of one cooling tower, one condenser water pump (constant speed), and one
primary chilled water pump (constant speed)." The 8D containment action (D3) relies on this.
The 8D example (`docs/8D_chiller_example.md`) uses Table 3 of the same PDF: "Cooling tower 1
heat exchanger | Fouling | 95%, 80%, 65% | Multiply intensity value by heat transfer
coefficient", and the note under it that for sensor-bias faults "the value of the faulty sensor
logged is the faulty value".

## Part D — maintenance work-order data: dataset search

Pages read on **2026-10-02**.

**MaintNet (not used).** Akhbardeh, Farhad, Travis Desell and Marcos Zampieri. "MaintNet: A
Collaborative Open-Source Library for Predictive Maintenance Language Resources." *Proceedings
of the 27th International Conference on Computational Linguistics* (system demonstrations)
(COLING 2020), pp. 7–11, https://aclanthology.org/2020.coling-demos.2.pdf. Table 2 of the paper
lists a facility-maintenance set of 87,276 instances whose source is "Baltimore City Maryland
Preventive Maintenance". The paper itself is CC BY 4.0, but that licence covers the paper, not
the data. The MaintNet site (https://people.rit.edu/fa3019/MaintNet/) no longer lists the
facility data and states that no further data are available on request; a GitHub repository
search for "MaintNet" found copies of the aviation set only. No facility data with a stated
licence could be obtained, so MaintNet was not used.

**NYC Parks AMPS (used).** NYC Department of Parks and Recreation, *Asset Management Parks
System (AMPS)* data collection, NYC Open Data:

| Table | Dataset id | URL |
|---|---|---|
| Work Orders | 8sdw-8vja | https://data.cityofnewyork.us/d/8sdw-8vja |
| Assets | e25p-jzfy | https://data.cityofnewyork.us/d/e25p-jzfy |
| Labor | xzj8-i3jk | https://data.cityofnewyork.us/d/xzj8-i3jk |

* Terms of use. The portal's licence field for these datasets is empty. NYC Administrative Code
  §23-502(d) (Open Data Law, as amended by Local Law 251 of 2017): "Such public data sets shall
  be made available without any registration requirement, license requirement or restrictions
  on their use provided that the department may require a third party providing to the public
  any public data set, or application utilizing such data set, to explicitly identify the source
  and version of the public data set, and a description of any modifications made to such public
  data set." The text was read from the unofficial mirror
  https://nyc-laws.readthedocs.io/en/latest/nycadmincode/t23/c05/ because the official American
  Legal Publishing page returned HTTP 403. Source and version: the snapshot (download times, row
  counts, SHA-256 of the cached files) is recorded in `results/maintenance_data_checks.json`;
  modifications: the mapping to canonical work orders in `fabhvac/maintenance/amps.py`.
* Field meanings: AMPS data dictionary and "User Guide | Asset Management Parks System (AMPS)
  Data Collection" (created and last updated April 4th, 2019), both linked from the Work Orders
  dataset page. Used: EVT_REQM "Problem Code — Indicates the problem this work order is intended
  to fix"; EVT_JOBTYPE "Scheduled Work, Corrective Maintenance, Adhoc Inspection, Issue (parts)";
  EVT_TYPE "PPM = Planned Preventative Maintenance"; EVT_DESC "entered by the person requesting
  work … can also be edited by the person overseeing the work order"; EVT_REPORTED user-editable
  report date; EVT_COMPLETED note that older mobile devices were synchronised "days after work
  has been completed"; EVT_MRC maintenance district (B, M, Q, R, X + number). The user guide
  says HVAC is maintained by citywide staff and that long-life plant such as HVAC receives
  scheduled preventive maintenance.
* Raw data are not redistributed. The local snapshot also contains personal names and phone
  numbers in some asset descriptions; nothing from the free-text or descriptive columns is
  written to `results/`.

## Part D — reliability and maintenance-policy formulas

* Age-replacement cost rate and its optimality condition, and the periodic-overhaul-with-
  minimal-repair cost rate: Nakagawa, Toshio. "A Summary of Periodic Replacement with Minimal
  Repair at Failure." *Journal of the Operations Research Society of Japan* 24(3), 1981,
  pp. 213–227, eqs. (2.1), (2.4) and (2.5), which give them with reference to Barlow, R. E. and
  F. Proschan, *Mathematical Theory of Reliability*, Wiley, 1965, pp. 85 and 96 (the book itself
  was not read). Read from https://orsj.org/wp-content/or-archives50/pdf/e_mag/Vol.24_03_213.pdf.
  Used in `fabhvac/maintenance/weibull.py`; `tests/test_maintenance.py` checks the computed
  optimum against eq. (2.5) and against direct numerical minimisation.
* Right-censored Weibull likelihood: the standard form, written out in the module docstring;
  the fit is checked against `scipy.stats.weibull_min.fit` with `CensoredData` in the tests.
