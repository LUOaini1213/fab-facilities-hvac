# Third-party notices

This file lists third-party material that this repository copies or derives from, with the
notices its licences require. It is not a licence for the repository itself.

## PsychroLib (MIT License)

`excel/FabHvac.bas` ports coefficients and algorithms from PsychroLib 2.5.0
(https://github.com/psychrometrics/psychrolib) to VBA; the Python package uses PsychroLib as an
installed dependency (not copied). The same notice is in the header of `excel/FabHvac.bas`.

```
The MIT License (MIT)

Copyright (c) 2018-2020 The PsychroLib Contributors.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
```

PsychroLib's equations and coefficients come from ASHRAE Handbook - Fundamentals (2017), ch. 1.

## LBNL Fault Detection and Diagnostics Datasets (CC BY 4.0)

`results/fdd_*` and `results/maintenance_8d_*` are summaries derived from: Granderson, Jessica,
et al. *LBNL Fault Detection and Diagnostics Datasets.* Lawrence Berkeley National Laboratory,
1 August 2022, Open Energy Data Initiative (OEDI), https://doi.org/10.25984/1881324. Licensed
under the Creative Commons Attribution 4.0 International licence,
https://creativecommons.org/licenses/by/4.0/. Changes: the 1-minute data were aggregated to
hourly windows and annual summaries, two outdoor-temperature columns are treated as swapped,
and detection/diagnosis results were computed (see README, Part C). The raw data are not
redistributed.

## NYC Parks AMPS work orders (NYC Open Data)

`results/maintenance_*` (except the data-free `maintenance_weibull_selfcheck.json` and
`maintenance_pm_sensitivity.csv`) are aggregates derived from NYC Department of Parks and
Recreation, *Asset Management Parks System (AMPS)*, NYC Open Data datasets 8sdw-8vja,
e25p-jzfy and xzj8-i3jk, snapshot downloaded 2 Oct 2026 (SHA-256 in
`results/maintenance_data_checks.json`). Published under the NYC Open Data Law without a licence
requirement; source and version are identified here as that law allows the city to require.
Modifications: the mapping to canonical work orders in `fabhvac/maintenance/amps.py`. The raw
data are not redistributed.
