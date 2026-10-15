# 8D example: cooling-tower fouling in the LBNL chiller-plant simulation

**What this is.** A worked 8D / 5-Why report on a fault that exists in the public LBNL
chiller-plant data set used in Part C. All evidence is **simulation-level**: the "plant" is a
simulated three-chiller, three-tower plant for a Chicago office, and the fault is imposed by the
simulation (documentation Table 3: "Cooling tower 1 heat exchanger | Fouling | 95%, 80%, 65% |
Multiply intensity value by heat transfer coefficient"). Each faulted file is the same simulated
year with the same weather and building model as the fault-free file, so an hour of a faulted
file can be compared with the same hour of the fault-free file ("paired" comparison): the
difference is caused by the fault and by the plant controls' response to it. Nothing here was
observed on a real plant; real-world causes of fouling (scale, biofilm, debris, water treatment) are not in the data and appear only where
marked as *not from the data*.

Numbers come from `scripts/maint_8d.py` → `results/maintenance_8d_tower_fouling.json` (paired
effects, indicator, Part C detection per hour and per day) and
`results/maintenance_8d_indicator.csv` (alarm rates for every file), and from the Part C files
`results/fdd_detection.csv`, `results/fdd_detection_daily.csv` and `results/fdd_energy.csv`.
Severities are written as the heat-transfer multiplier: 0.95 (mild), 0.80, 0.65 (severe).

## D0 — Scope

One plant-level problem: higher plant energy with unchanged delivered cooling, which the Part C
detectors catch poorly at their deployable thresholds: the residual baseline not at all, the
gradient-boosting model on about a quarter of days at the severe level only. Out of scope: costs
(no tariff in the data), real-plant maintenance history (none exists for this simulated plant).

## D1 — Team

A desk study; the roles an 8D on a real plant would need are a plant/facilities engineer
(owner), a controls engineer (tower and condenser-water loop sequences), the water-treatment
contractor, and whoever maintains the FDD rules.

## D2 — Problem description

| | 0.95 | 0.80 | 0.65 |
|---|---|---|---|
| plant energy change, year | +0.16 % (+2 028 kWh) | +0.84 % (+10 356 kWh) | +1.85 % (+22 862 kWh) |
| plant kW/RT on delivered cooling | +0.16 % | +0.84 % | +1.86 % |
| measured chiller evaporator heat, year (`evaporator_heat_kwh_delta`) | +2 kWh | −41 kWh | −127 kWh¹ |
| tower-1 fan at full speed, share of hours (fault-free 2.2 %) | 2.9 % | 7.4 % | 14.6 % |
| tower-1 leaving water > set point + 0.5 K, share of hours (fault-free 1.6 %) | 2.4 % | 5.8 % | 13.7 % |
| Part C detection, deployable threshold, hourly alarm rate: residual baseline / gradient boosting | 0.6 % / 0 % | 0.7 % / 0.2 % | 0.6 % / 6.9 % |
| same, test days with at least one alarming hour: residual baseline / gradient boosting (fault-free test days: 11.8 % / 0 %) | 10.7 % / 0 % | 13.0 % / 2.4 % | 11.2 % / 24.9 % |

¹ Delivered (primary-loop) cooling changes by −0.007 % at 0.65 (`results/fdd_energy.csv`): the
cooling delivered is effectively unchanged.

Where the extra energy goes at 0.65 (paired, kWh/year): chiller +7 906, tower fans +7 446,
condenser-water pumps +7 013, chilled-water pumps +496. The condenser three-way valve sends more
water through tower 1 under the fault (mean valve signal −0.067, tower-1 water flow +10.2 gpm);
the data do not show the mechanism behind the pump-energy increase beyond that.

Problem statement: *with tower 1 at 65 % of its clean heat-transfer coefficient the plant uses
1.85 % more energy for the same cooling and the tower-1 fan runs at full speed 6.6 times as often.
At their deployable settings the residual baseline is blind to it (it alarms on fault-free days
as often as on faulted ones), and the gradient-boosting model alarms on 42 of 169 test days
(24.9 %) at this severity, 4 days (2.4 %) at 0.80 and none at 0.95.*

## D3 — Containment (proposed, not simulated)

The data set has no scenario in which an operator acts, so containment can only be proposed:

1. Until the root cause is confirmed, trend the tower-1 approach and fan speed daily (the
   signals in D2 that move first) instead of waiting for an FDD alarm.
2. When tower 1 sits at full fan speed and above set point, bring a second tower on line. This
   needs a control change: the documented sequence ties towers to chillers ("The activation of
   one chiller also corresponds to the activation of one cooling tower", documentation Table 1),
   and in the data tower 2's status equals chiller 2's in every hour. Tower 2 runs 12.4 % of
   hours in the fault-free year (`fault_free_operation` in the JSON). Spare tower capacity exists, but
   using it means decoupling tower staging from chiller staging; whether that is acceptable, and
   what it would save, is **not** in the data.

## D4 — Root cause

### 5-Why (each answer is a paired difference, fault minus fault-free, same hour)

1. **Why does plant energy rise with unchanged cooling?** Chiller, tower-fan and condenser-pump
   energy all rise (D2 breakdown); the chilled-water side barely changes (+496 kWh).
2. **Why does chiller energy rise?** Chiller-1 lift (condenser-water leaving minus chilled-water
   supply) is higher: +0.28 K on average at 0.65 (+0.11 K at 0.80, +0.02 K at 0.95).
3. **Why is the lift higher?** The water leaving tower 1 is warmer: median +0.68 K, 95th
   percentile +1.43 K, maximum +3.22 K at 0.65. Tower 2's leaving water, in the 995 hours it runs
   in both files, does not change (median −0.0005 K): the change is **local to tower 1**.
4. **Why is tower 1's water warmer when the fan works harder?** The fan already runs faster
   (+0.044 mean speed fraction) and saturates in 14.6 % of hours, yet the leaving water is still
   warmer: the tower rejects less heat for the same air and water flow, i.e. its heat-transfer
   effectiveness has dropped. In most hours the fan is off (median tower-1 fan speed 0 in the
   fault-free year) and the leaving water is below its set point (85 % of fault-free hours;
   both in `fault_free_operation`), so the controller has nothing to correct and the warmer
   water simply passes to the chillers.
5. **Why has the effectiveness dropped?** In the simulation, because the heat-transfer
   coefficient of tower 1 is multiplied by 0.65 (documentation Table 3) — the data reproduce
   the documented cause. *Not from the data:* on a real tower, fill fouling, scale or biofilm
   would be examined next; nothing in this data set can distinguish those.

### Differential check — could something else produce the same symptoms?

Paired medians/means for the files that also make tower-1 water look warmer or change tower
energy (`differential_signatures`):

| file | logged tower-1 leaving water | chiller-1 lift (mean) | tower-fan kWh | chiller kWh |
|---|---|---|---|---|
| tower fouling 0.65 | +0.68 K | **+0.28 K** | +41 % | **+2.1 %** |
| tower-1 sensor bias +2 °C | +1.61 K | **−0.22 K** | +43 % | **−1.5 %** |
| tower-1 sensor bias −2 °C | −2.00 K | +0.41 K | −31 % | +3.7 % |
| condenser valve leakage 25 % | 0.00 K | +6.09 K | −95 % | +14.4 % |
| tower PI mis-tuned | 0.00 K | +0.87 K | −34 % | +5.6 % |

A positive tower-1 sensor bias looks like fouling on the tower sensor and on fan energy, but the
fan then over-cools the real water, so the chillers' own sensors show a *lower* lift and chiller
energy falls. Fouling raises both. **Rule:** a warm-tower-1 signal with a rising chiller lift
points to the tower; with a falling lift, check the tower-1 sensor first. (The documentation
confirms that bias files log the faulty sensor value.)

### Escape point — why did the existing FDD miss it?

* The effect is small per hour: a +0.08 K (0.95) to +0.68 K (0.65) median shift in one sensor,
  with no change in delivered cooling and no chilled-water excursion
  (`hours_chws_above_spt_1k_frac` 0.0002 at 0.65).
* The Part C residual baseline takes the maximum of 16 scaled residuals, so one small shift is
  diluted; its tower-fouling recall equals its false-alarm rate (0.6–0.7 % of hours; 10.7–13.0 %
  of days against 11.8 % of fault-free days). It is blind to this fault.
* The gradient-boosting model separates fouling from normal only partly (hourly recall 15.5 %,
  27.6 %, 55.2 % at a 1 % false-alarm rate set on test data). At its deployable threshold it
  alarms in 0 %, 0.2 % and 6.9 % of hours, which is 0, 4 and 42 of 169 test days (0 %, 2.4 %,
  24.9 %) with no alarm on any fault-free test day: it does catch the severe level, on about a
  quarter of days, but not the milder ones.

## D5 — Chosen corrective actions

1. **Physical (root cause):** restore tower-1 heat transfer (clean / treat tower 1). In the
   simulation this corresponds to returning to the fault-free file.
2. **Detection (escape point):** a targeted condition indicator
   (`fabhvac/maintenance/condition.py`): a fault-free ridge regression of tower-1 leaving water
   temperature on weather, load, set points, staging, tower-1 fan speed and water flow; the
   hourly residual is averaged per day and compared with a one-sided threshold. The model,
   inputs, aggregation and deployable threshold rule were fixed before the test months were
   scored; the second, test-calibrated threshold in D6 was added afterwards, when the first
   evaluation showed the deployable threshold far above every fault-free test-day score.

## D6 — Implementation and verification

**Physical action (simulation-level).** The fault-free file is the plant after the action: plant
energy is lower by the D2 amounts (22 862 kWh at 0.65), tower-1 full-fan hours return to 2.2 %
and set-point excursions to 1.6 %. This only shows what the simulation says a clean tower does;
how far a real cleaning restores the coefficient is not in the data.

**Detection action**, verified on the held-out even months (169 test days per file; training:
fault-free odd months only). All rows are **day-level** alarm rates on the same 169 test days, so
the methods are compared on one basis; a Part C detector's day alarms when any of its hours
alarms. Two operating points per method: the deployable threshold (fixed from training months
only) and, for comparison only, the threshold that leaves no fault-free test day alarming
(calibrated on test data, an ROC point, not a setting one could deploy).

| test days alarming | fault-free | fouling 0.95 | fouling 0.80 | fouling 0.65 |
|---|---|---|---|---|
| **new indicator**, deployable (0.698 K, 99th pct of out-of-fold training days) | 0 / 169 | 0 % | 0 % | 36.7 % |
| Part C gradient boosting, deployable | 0 / 169 | 0 % | 2.4 % | 24.9 % |
| Part C residual baseline, deployable | 20 / 169 | 10.7 % | 13.0 % | 11.2 % |
| **new indicator**, no fault-free test day alarming (0.098 K) | 0 / 169 | 30.2 % | 89.3 % | 97.6 % |
| Part C gradient boosting, no fault-free test day alarming | 0 / 169 | 2.4 % | 28.4 % | 55.0 % |
| Part C residual baseline, no fault-free test day alarming | 0 / 169 | 1.8 % | 0.6 % | 1.2 % |

* **Separability improved, on a matched basis:** with each method's threshold set so that no
  fault-free test day alarms, the daily indicator flags 97.6 / 89.3 / 30.2 % of fouled days
  (severe → mild) against 55.0 / 28.4 / 2.4 % for gradient boosting and about 1 % for the
  residual baseline (`part_c_detection_daily_any_hour` in the JSON, from
  `results/fdd_detection_daily.csv`).
* **At deployable settings the gain is small:** 36.7 % against 24.9 % of days at 0.65, and the
  indicator misses the 4 days at 0.80 that gradient boosting catches. The indicator's
  training-calibrated threshold is about seven times the largest fault-free test-day score.
  Out-of-fold scoring leaves a whole month out at a time, so each training day is scored by a
  model that never saw that season, which overstates the noise.
* **Not specific:** the indicator also alarms on tower-1 sensor bias +1/+2 °C (58.0 % / 93.5 % of
  days at the deployable threshold), condenser-valve leakage and stuck valve (47–100 %) and the
  mis-tuned tower PI loop (17 %) (`results/maintenance_8d_indicator.csv`). It never alarms on
  negative tower bias, chiller bias, chiller fouling or DP-sensor bias at the deployable
  threshold. An alarm therefore needs the D4 differential check before a crew is sent.

Verdict: corrective action 1 is verified at simulation level; action 2 is **partially
effective** — at its deployable threshold it detects the severe level on 37 % of days with no
false-alarm day (gradient boosting: 25 %), and it separates the milder levels far better than
either Part C detector, but only with a threshold that has not yet been calibrated without
using test data.

## D7 — Prevent recurrence

* Recalibrate the indicator threshold on a full fault-free year (here only six training months
  exist), re-check the false-alarm rate, then add it to the FDD rule set with the D4
  differential check (sign of the chiller lift) in the alarm text.
* Put tower-1 cleaning / water-treatment checks on a planned-maintenance schedule. The interval
  cannot be derived from this data set: the simulation holds each fouling level constant for a
  year and contains no fouling *rate*. With field records (cleaning dates, approach before and
  after), the Weibull/age-replacement tools in `fabhvac/maintenance/weibull.py` could set it.
* Record the work in the CMMS with an asset (tower 1) and a failure mode ("fouling") so that
  repeats and time between cleanings can be measured (`fabhvac/maintenance/workorder.py`).

## D8 — Closure and limits

At severity 0.65 the documented fault costs 1.85 % plant energy and pushes tower 1 to full fan
speed in one hour in seven. At deployable settings the residual baseline is blind to it and the
gradient-boosting model catches it on about a quarter of test days (24.9 %), the milder levels
hardly at all. The paired data show a cause local to tower 1 that matches the documented fault,
and a differential rule (chiller lift sign) separates it from the tower-sensor bias that mimics
it. Compared day by day at matched (zero false-alarm-day) thresholds, a daily residual indicator
is far more sensitive than either Part C detector (89 % vs 28 % of days at 0.80), but its
deployable threshold needs a longer calibration period before it can run unattended.

All detection numbers here use the interleaved odd/even-month split; on a season-block split the
Part C gradient-boosting model degrades sharply (README, season-block check), and the indicator
was not evaluated that way. Limits: one simulated plant and year, Chicago weather, an office
load (not a fab or a tropical climate), fixed fault severities, no real maintenance actions.
