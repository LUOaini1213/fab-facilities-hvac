"""Mutation pass: apply deliberate bugs one at a time and require the test suite to fail.

The byte-for-byte golden-output test is excluded, so each mutant must be killed by a
unit test rather than by "results changed". Every source file is restored after each run
(also on Ctrl-C). Output: results/mutation_report.json

    python scripts/mutate.py            # all mutants
    python scripts/mutate.py --only fdd # mutants whose id starts with 'fdd'
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fabhvac.results_io import write_json  # noqa: E402

# (id, file, original snippet, mutated snippet[, "EQUIVALENT"]). Snippets must occur exactly once.
# A mutant marked EQUIVALENT cannot change behaviour (reason given in a comment); it is run
# and reported separately, not counted in killed/total.
MUTANTS = [
    ("iso_exponent", "fabhvac/cleanroom.py", "ISO_EXPONENT = 2.08", "ISO_EXPONENT = 2.0"),
    ("iso_ratio_inverted", "fabhvac/cleanroom.py", "(ISO_REF_SIZE_UM / d_um) ** ISO_EXPONENT", "(d_um / ISO_REF_SIZE_UM) ** ISO_EXPONENT"),
    ("iso_max_class", "fabhvac/cleanroom.py", "1.0 <= n_class <= 9.0", "1.0 <= n_class <= 10.0"),
    ("round_sig_off_by_one", "fabhvac/cleanroom.py", "round(x, sig - 1 - int(", "round(x, sig - int("),
    ("ffu_no_float_guard", "fabhvac/cleanroom.py", "/ ffu_face_area_m2 - 1e-9))", "/ ffu_face_area_m2))"),
    ("ffu_floor", "fabhvac/cleanroom.py", "return int(math.ceil(room_area_m2", "return int(math.floor(room_area_m2"),
    ("ach_minutes", "fabhvac/cleanroom.py", "q_m3s * 3600.0 / room_volume_m3", "q_m3s * 60.0 / room_volume_m3"),
    ("wm_recirc_fraction", "fabhvac/cleanroom.py", "den = 1.0 - p * (1.0 - oa_fraction)\n", "den = 1.0 - p * oa_fraction\n"),
    ("wm_ignore_prefilter", "fabhvac/cleanroom.py", "num = gen_per_s / q_m3s + p * oa_fraction * p_oa * c_out_per_m3", "num = gen_per_s / q_m3s + p * oa_fraction * c_out_per_m3"),
    ("wm_required_sign", "fabhvac/cleanroom.py", "- p * oa_fraction * p_oa * c_out_per_m3\n    if den <= 0", "+ p * oa_fraction * p_oa * c_out_per_m3\n    if den <= 0"),
    ("wm_eta_upper_bound", "fabhvac/cleanroom.py", "if not (0.0 <= eta < 1.0):", "if not (0.0 <= eta <= 1.0):"),
    ("rt_nea_rounded", "fabhvac/units.py", "RT_TO_KW = 3.516853", "RT_TO_KW = 3.517"),
    ("f_to_c_factor", "fabhvac/units.py", "return (t_f - 32.0) / 1.8", "return (t_f - 32.0) / 1.6"),
    ("cp_chw", "fabhvac/units.py", "NEA_CP_CHW_KJ_KGK = 4.19", "NEA_CP_CHW_KJ_KGK = 4.18"),
    ("kwrt_conv_inverted", "fabhvac/chiller.py", "return kw_per_rt / RT_TO_KW", "return kw_per_rt * RT_TO_KW"),
    ("mees_round_nearest", "fabhvac/chiller.py", "return int(math.ceil(round(chws_c, 9)))", "return int(round(chws_c))"),
    ("mees_no_noise_guard", "fabhvac/chiller.py", "return int(math.ceil(round(chws_c, 9)))", "return int(math.ceil(chws_c))"),
    ("mees_step", "fabhvac/chiller.py", "MEES_GENERAL_STEP_ABOVE_9 = 0.003", "MEES_GENERAL_STEP_ABOVE_9 = 0.002"),
    # Equivalent: at t = 9 the progressive formula 0.185 - 0.003*(9-9) equals the table value.
    ("mees_table_edge", "fabhvac/chiller.py", "    if t <= 9:\n", "    if t < 9:\n", "EQUIVALENT"),
    ("mees_table_edge_10", "fabhvac/chiller.py", "    if t <= 9:\n", "    if t <= 10:\n"),
    ("mees_space_tail", "fabhvac/chiller.py", "MEES_SPACE_COOLING_NEW_BLDG_7_PLUS = 0.179", "MEES_SPACE_COOLING_NEW_BLDG_7_PLUS = 0.182"),
    ("mees_table_typo", "fabhvac/chiller.py", "7: 0.191, 8: 0.188", "7: 0.191, 8: 0.185"),
    ("mees_scope_strict", "fabhvac/chiller.py", "installed_capacity_kw >= MEES_SCOPE_MIN_CAPACITY_KW", "installed_capacity_kw > MEES_SCOPE_MIN_CAPACITY_KW"),
    ("mees_scope_glycol", "fabhvac/chiller.py", "and not brine_or_glycol_only)", ")"),
    ("mees_pass_strict", "fabhvac/chiller.py", "\"PASS\" if kwe_per_kwc <= lim", "\"PASS\" if kwe_per_kwc < lim"),
    ("hb_denominator", "fabhvac/chiller.py", "- q_c) / q_c * 100.0", "- q_c) / np.asarray(cooling_kw, dtype=float) * 100.0"),
    ("hb_tolerance_strict", "fabhvac/chiller.py", "np.abs(hb) <= tol_pct", "np.abs(hb) < tol_pct"),
    ("hb_fraction_strict", "fabhvac/chiller.py", "\"passes\": frac >= required_fraction", "\"passes\": frac > required_fraction"),
    ("hb_keep_nonfinite", "fabhvac/chiller.py", "    hb = hb[np.isfinite(hb)]\n", ""),
    ("mv_linear_sum", "fabhvac/chiller.py", "return math.sqrt(d_ut ** 2 + u_flow_pct ** 2 + u_power_pct ** 2)", "return d_ut + u_flow_pct + u_power_pct"),
    ("motor_eff_dropped", "fabhvac/chiller.py", "* motor_eff * vsd_eff", "* vsd_eff"),
    ("ct_eff_denominator", "fabhvac/tower.py", "denom = t_in - t_wb_", "denom = np.asarray(t_water_out, dtype=float) - t_wb_"),
    ("ct_approach_swapped", "fabhvac/tower.py", "return np.asarray(t_water_out, dtype=float) - np.asarray(t_wb, dtype=float)", "return np.asarray(t_wb, dtype=float) - np.asarray(t_water_out, dtype=float)"),
    ("mau_mass_at_outdoor", "fabhvac/loads.py", "m = oa_flow_m3s_at_coil_leaving / coil.v_m3_kg", "m = oa_flow_m3s_at_coil_leaving / oa.v_m3_kg"),
    ("mau_split_wrong_temp", "fabhvac/loads.py", "h_out_dry = psychro.enthalpy(oa.tdb_c, coil_leaving_w)", "h_out_dry = psychro.enthalpy(coil_leaving_tdb_c, oa.w)"),
    ("mau_reheat_wrong_w", "fabhvac/loads.py", "reheat = m * (psychro.enthalpy(mau_supply_tdb_c, coil_leaving_w) - h_coil) / 1000.0", "reheat = m * (psychro.enthalpy(mau_supply_tdb_c, oa.w) - h_coil) / 1000.0"),
    ("mau_no_supersat_check", "fabhvac/loads.py", "    if coil_leaving_w > w_sat * (1 + 1e-12):\n", "    if False:\n"),
    ("supply_w_sign", "fabhvac/loads.py", "return w_room - moisture_gain_kg_s / m_da_kg_s", "return w_room + moisture_gain_kg_s / m_da_kg_s"),
    ("coil_db_below_dp", "fabhvac/loads.py", "        t_coil = tdp + db_above_dp_k\n", "        t_coil = tdp - db_above_dp_k\n"),
    ("fan_kw_units", "fabhvac/loads.py", "fan_kw = ffu_count * ffu_power_w / 1000.0", "fan_kw = ffu_count * ffu_power_w / 100.0"),
    ("mau_credit_sign", "fabhvac/loads.py", "dcc = internal - mau_credit", "dcc = internal + mau_credit"),
    ("airstate_tdp_from_twb", "fabhvac/psychro.py", "return _psy.GetTDewPointFromHumRatio(self.tdb_c, self.w, self.p_pa)", "return _psy.GetTWetBulbFromHumRatio(self.tdb_c, self.w, self.p_pa)"),
    ("state_twb_uses_rh", "fabhvac/psychro.py", "return AirState(tdb_c, hum_ratio_from_twb(tdb_c, twb_c, p_pa), p_pa)", "return AirState(tdb_c, hum_ratio_from_tdp(twb_c, p_pa), p_pa)"),
    ("fdd_wb_db_unswapped", "fabhvac/fdd/data.py", 'out["t_wb_c"] = f_to_c(df["OA_TEMP"])', 'out["t_wb_c"] = f_to_c(df["OA_TEMP_WB"])'),
    ("fdd_cp_evap", "fabhvac/fdd/data.py", "qe = m_chw * NEA_CP_CHW_KJ_KGK * dt_chw", "qe = m_chw * NEA_CP_CDW_KJ_KGK * dt_chw"),
    ("fdd_cond_dt_sign", "fabhvac/fdd/data.py", 'dt_cdw = (df[f"CHL_SWCD_TEMP_{i}"] - df[f"CHL_RWCD_TEMP_{i}"]) / 1.8', 'dt_cdw = (df[f"CHL_RWCD_TEMP_{i}"] - df[f"CHL_SWCD_TEMP_{i}"]) / 1.8'),
    ("fdd_plant_no_tower", "fabhvac/fdd/data.py", 'out["cdw_pump_kw"] + out["tower_kw"]', 'out["cdw_pump_kw"]'),
    ("fdd_no_secondary_pumps", "fabhvac/fdd/data.py", '+ df["CWL_SEC_PM_POW_1"] + df["CWL_SEC_PM_POW_2"])', ')'),
    ("fdd_hb_denominator", "fabhvac/fdd/data.py", '- out["q_cond_kw"]) / out["q_cond_kw"] * 100', '- out["q_cond_kw"]) / out["q_evap_kw"] * 100'),
    ("fdd_gpm_factor", "fabhvac/fdd/data.py", "GPM_TO_KG_S = GPM_TO_M3_S * 1000.0", "GPM_TO_KG_S = GPM_TO_M3_S * 1000.0 * 1.05"),
    ("fdd_std_ddof", "fabhvac/fdd/data.py", "std = g.std(ddof=0)", "std = g.std(ddof=1)"),
    ("fdd_hb_tol_strict", "fabhvac/fdd/data.py", '"fraction_within": float(np.mean(np.abs(hb) <= tol_pct))', '"fraction_within": float(np.mean(np.abs(hb) < tol_pct))'),
    ("fdd_parse_pct_sign", "fabhvac/fdd/data.py", "            val = float(sev)\n", "            val = abs(float(sev))\n"),
    ("fdd_split_parity", "fabhvac/fdd/models.py", "train = (month % 2 == 1)", "train = (month % 2 == 0)"),
    ("fdd_split_no_buffer", "fabhvac/fdd/models.py", "    test = test & ~near\n", ""),
    ("fdd_far_ceil", "fabhvac/fdd/models.py", "k = int(np.floor(far * n))", "k = int(np.ceil(far * n)) + 1"),
    ("fdd_alarm_ge", "fabhvac/fdd/models.py", "return float(np.mean(np.asarray(scores) > threshold))", "return float(np.mean(np.asarray(scores) >= threshold))"),
    ("fdd_mad_constant", "fabhvac/fdd/models.py", "* 1.4826", "* 1.0"),
    ("fdd_tail_scale_median", "fabhvac/fdd/models.py", "sc = np.nanquantile(dev, self.tail_q, axis=0)", "sc = np.nanmedian(dev, axis=0)"),
    ("fdd_stat_mean", "fabhvac/fdd/models.py", "return np.max(np.abs(self.zscores(df)), axis=1)", "return np.mean(np.abs(self.zscores(df)), axis=1)"),
    ("fdd_diag_include_normal", "fabhvac/fdd/models.py", "faults = self.classes_ != NORMAL", "faults = self.classes_ == self.classes_"),
    ("fdd_signature_ignore_alarm", "fabhvac/fdd/models.py", "                sel = sel & alarm\n", ""),
    ("fdd_diag_argmax", "fabhvac/fdd/models.py", "return self.classes_[np.argmin(d, axis=1)]", "return self.classes_[np.argmax(d, axis=1)]"),
    ("fdd_confusion_transposed", "fabhvac/fdd/models.py", "m[idx[t], idx[p]] += 1", "m[idx[p], idx[t]] += 1"),
    ("fdd_features_leak_labels", "fabhvac/fdd/models.py", "if c not in NON_FEATURES and pd.api", "if pd.api"),
    ("fdd_score_inverted", "fabhvac/fdd/models.py", "return 1.0 - proba[:, idx]", "return proba[:, idx]"),
    # Equivalent here: with early_stopping=False, max_features=1.0 and < 200 000 training rows
    # (above that, bin edges come from a random subsample) sklearn's HistGradientBoosting
    # draws no random numbers, so the seed has no effect in the tests or in fdd_run.py.
    ("fdd_classifier_seed", "fabhvac/fdd/models.py", "random_state=seed)", "random_state=None)", "EQUIVALENT"),
    ("fdd_season_swap", "fabhvac/fdd/models.py", "train = first if train_first_half else ~first", "train = ~first if train_first_half else first"),
    ("fdd_season_no_buffer", "fabhvac/fdd/models.py", "    return np.asarray(train), np.asarray(test & ~near)\n", "    return np.asarray(train), np.asarray(test)\n"),
    ("fdd_season_end_offset", "fabhvac/fdd/models.py", "hrs_to_end = (half_end - t) / np.timedelta64(1, \"h\") - 1", "hrs_to_end = (half_end - t) / np.timedelta64(1, \"h\")"),
    ("fdd_season_june_second_half", "fabhvac/fdd/models.py", "first = month <= 6", "first = month < 6"),
    ("fdd_two_stage_ge", "fabhvac/fdd/models.py", "return np.where(score > threshold, best, NORMAL)", "return np.where(score >= threshold, best, NORMAL)"),
    ("fdd_two_stage_argmax_all", "fabhvac/fdd/models.py", "best = classes[fault][np.argmax(proba[:, fault], axis=1)]", "best = classes[np.argmax(proba, axis=1)]"),
    ("fdd_diag_normal_recall_all", "fabhvac/fdd/models.py", "\"normal_recall\": float(np.mean(y_pred[norm] == NORMAL))", "\"normal_recall\": float(np.mean(y_pred == NORMAL))"),
    ("fdd_diag_fault_incl_normal", "fabhvac/fdd/models.py", "float(np.mean(y_pred[~norm] == y_true[~norm]))", "float(np.mean(y_pred == y_true))"),
    ("fdd_daily_mean_not_max", "fabhvac/fdd/models.py", "return s.groupby(index.normalize()).max()", "return s.groupby(index.normalize()).mean()"),
    ("psychro_h_units", "fabhvac/psychro.py", "w = _psy.GetHumRatioFromEnthalpyAndTDryBulb(h_j_kg, tdb_c)", "w = _psy.GetHumRatioFromEnthalpyAndTDryBulb(h_j_kg / 1000.0, tdb_c)"),
    ("psychro_h_no_sat_check", "fabhvac/psychro.py", "    if w > hum_ratio_from_rh(tdb_c, 1.0, p_pa):\n", "    if False:\n"),
    ("vba_ref_mees_space_flag", "fabhvac/vba_reference.py", "return chiller.mees_check(eff, chws, cap, space)[\"verdict\"]", "return chiller.mees_check(eff, chws, cap)[\"verdict\"]"),
    # ---------------- Part D: fabhvac/maintenance
    ("maint_wb_profile_sign", "fabhvac/maintenance/weibull.py", "- 1.0 / beta - np.mean(lt[d]))", "- 1.0 / beta + np.mean(lt[d]))"),
    ("maint_wb_bisect_dir", "fabhvac/maintenance/weibull.py", "if _profile_score(math.exp(mid), lt, d) > 0:", "if _profile_score(math.exp(mid), lt, d) < 0:"),
    ("maint_wb_eta_no_r", "fabhvac/maintenance/weibull.py", "- math.log(r)) / beta + shift)", ") / beta + shift)"),
    ("maint_wb_ll_cens_as_fail", "fabhvac/maintenance/weibull.py", "np.sum(d * (math.log(beta)", "np.sum((math.log(beta)"),
    ("maint_wb_hessian_cross", "fabhvac/maintenance/weibull.py", "h_bu = -r + float(np.sum(w)) + beta * float(np.sum(w * x))", "h_bu = 0.0"),
    ("maint_wb_ci_z", "fabhvac/maintenance/weibull.py", "zq = 1.959963984540054", "zq = 1.6448536269514722"),
    ("maint_wb_lr_df", "fabhvac/maintenance/weibull.py", "p = math.erfc(math.sqrt(lr / 2.0))", "p = math.exp(-lr / 2.0)"),
    ("maint_wb_ar_cost_swap", "fabhvac/maintenance/weibull.py", "return (c_f * (1.0 - R) + c_p * R) / integral", "return (c_p * (1.0 - R) + c_f * R) / integral"),
    ("maint_wb_ar_target", "fabhvac/maintenance/weibull.py", "target = c_p / (c_f - c_p)", "target = c_p / c_f"),
    ("maint_wb_ar_equal_cost", "fabhvac/maintenance/weibull.py", "if beta <= 1.0 or c_f <= c_p:", "if beta <= 1.0 or c_f < c_p:"),
    ("maint_wb_gl_half", "fabhvac/maintenance/weibull.py", "np.sum(0.5 * (b - a) * _GL_W[None, :]", "np.sum((b - a) * _GL_W[None, :]"),
    ("maint_wb_mean_life", "fabhvac/maintenance/weibull.py", "eta * math.gamma(1.0 + 1.0 / beta)", "eta * math.gamma(1.0 / beta)"),
    ("maint_wb_minrep", "fabhvac/maintenance/weibull.py", "(c_overhaul / (c_repair * (beta - 1.0)))", "(c_overhaul / (c_repair * beta))"),
    ("maint_wb_boot_rows", "fabhvac/maintenance/weibull.py", "idx = np.concatenate([members[k] for k in pick])", "idx = rng.integers(0, t.size, t.size)"),
    ("maint_wb_boot_level", "fabhvac/maintenance/weibull.py", "a = (1.0 - level) / 2.0", "a = 1.0 - level"),
    ("maint_rel_per_year_8760", "fabhvac/maintenance/reliability.py", "HOURS_PER_YEAR = 8766.0", "HOURS_PER_YEAR = 8760.0"),
    ("maint_tc_abstain_strict", "fabhvac/maintenance/textclass.py", "return np.where(top >= threshold, lab, ABSTAIN)", "return np.where(top > threshold, lab, ABSTAIN)"),
    ("maint_tc_abstain_min_proba", "fabhvac/maintenance/textclass.py", "top = proba.max(axis=1)", "top = proba.min(axis=1)"),
    ("maint_tc_thr_target_strict", "fabhvac/maintenance/textclass.py", "if cov.any() and ok[cov].mean() >= target_accuracy:", "if cov.any() and ok[cov].mean() > target_accuracy:"),
    ("maint_tc_thr_cover_strict", "fabhvac/maintenance/textclass.py", "        cov = top >= t\n", "        cov = top > t\n"),
    ("maint_tc_wilson_centre", "fabhvac/maintenance/textclass.py", "centre = (p + z * z / (2 * n)) / den", "centre = (p + z * z / n) / den"),
    ("maint_tc_wilson_den", "fabhvac/maintenance/textclass.py", "den = 1.0 + z * z / n", "den = 1.0"),
    ("maint_wo_dup_first", "fabhvac/maintenance/workorder.py", "duplicated(keep=False)", "duplicated(keep=\"first\")"),
    ("maint_wo_downtime_eq", "fabhvac/maintenance/workorder.py", "df[\"downtime_hours\"] > el + 1e-9", "df[\"downtime_hours\"] >= el"),
    ("maint_wo_closed_before", "fabhvac/maintenance/workorder.py", "f[\"closed_before_opened\"] = el < 0", "f[\"closed_before_opened\"] = el < -1"),
    ("maint_wo_path_order", "fabhvac/maintenance/workorder.py", "return out[::-1]", "return out"),
    ("maint_rel_merge_strict", "fabhvac/maintenance/reliability.py", "if start is not None and o <= end:", "if start is not None and o < end:"),
    ("maint_rel_window_end", "fabhvac/maintenance/reliability.py", "e = e[(e[\"start\"] >= e[\"w0\"]) & (e[\"start\"] < e[\"w1\"])]", "e = e[(e[\"start\"] >= e[\"w0\"])]"),
    ("maint_rel_availability", "fabhvac/maintenance/reliability.py", "\"availability\": mtbf / (mtbf + mttr)", "\"availability\": mttr / (mtbf + mttr)"),
    ("maint_rel_repeat_strict", "fabhvac/maintenance/reliability.py", "flag = gap.notna() & (gap <= within_days)", "flag = gap.notna() & (gap < within_days)"),
    ("maint_rel_pareto_vital", "fabhvac/maintenance/reliability.py", "out[\"vital_few\"] = prev < vital_share - 1e-12", "out[\"vital_few\"] = out[\"cum_share\"] <= vital_share + 1e-12"),
    ("maint_rel_uptime_from_start", "fabhvac/maintenance/reliability.py", "(starts[k + 1] - ends[k])", "(starts[k + 1] - starts[k])"),
    ("maint_tc_accuracy_covered", "fabhvac/maintenance/textclass.py", "\"accuracy\": float(np.mean(y_true == y_pred))", "\"accuracy\": float(np.mean(y_true[y_pred != ABSTAIN] == y_pred[y_pred != ABSTAIN]))"),
    ("maint_tc_unseen_raw", "fabhvac/maintenance/textclass.py", "seen = {normalise(t) for t in train_texts}", "seen = set(train_texts)"),
    ("maint_tc_split_overlap", "fabhvac/maintenance/textclass.py", "te = (d >= test_start).to_numpy()", "te = (d >= train_end).to_numpy()"),
    ("maint_tc_macro_absent", "fabhvac/maintenance/textclass.py", "present = [c for c in labels if per[c][\"support\"] > 0]", "present = list(labels)"),
    ("maint_cond_two_sided", "fabhvac/maintenance/condition.py", "return self.daily_score(df) > self.threshold_", "return self.daily_score(df).abs() > self.threshold_"),
    ("maint_cond_quantile", "fabhvac/maintenance/condition.py", "np.quantile(self.oof_daily_.to_numpy(), self.quantile)", "np.quantile(self.oof_daily_.to_numpy(), 0.5)"),
    ("maint_llm_accept_any", "fabhvac/maintenance/llm.py", "return lab if isinstance(lab, str) and lab in set(labels) else ABSTAIN", "return lab if isinstance(lab, str) else ABSTAIN"),
    ("maint_llm_temperature", "fabhvac/maintenance/llm.py", "\"options\": {\"temperature\": 0, \"seed\": 0, \"num_predict\": 40}", "\"options\": {\"temperature\": 0.7, \"seed\": 0, \"num_predict\": 40}"),
    ("maint_llm_batch_misaligned", "fabhvac/maintenance/llm.py", "if not isinstance(labs, list) or len(labs) != n:", "if not isinstance(labs, list):"),
    ("maint_amps_brkd_not_cm", "fabhvac/maintenance/amps.py", "\"BRKD\": \"CM\", ", ""),
    ("maint_amps_ppm_ignored", "fabhvac/maintenance/amps.py", "return t.where(evt_type != \"PPM\", \"PM\")", "return t"),
    ("maint_amps_gt_completed", "fabhvac/maintenance/amps.py", "STATUS_CLOSED = {\"Completed\", \"GT Completed\"}", "STATUS_CLOSED = {\"Completed\"}"),
    ("maint_amps_mode_any_type", "fabhvac/maintenance/amps.py", "code.isin(MEP_MODES) & (out[\"wo_type\"] == \"CM\")", "code.isin(MEP_MODES)"),
    ("maint_amps_opened_created", "fabhvac/maintenance/amps.py", "out[\"opened_at\"] = rep.fillna(_ts(w[\"evt_created\"]))", "out[\"opened_at\"] = _ts(w[\"evt_created\"])"),
    ("maint_amps_closed_any", "fabhvac/maintenance/amps.py", "out[\"closed_at\"] = _ts(w[\"evt_completed\"]).where(out[\"status\"] == \"closed\")", "out[\"closed_at\"] = _ts(w[\"evt_completed\"])"),
    ("maint_amps_no_blowdown", "fabhvac/maintenance/amps.py", "r\"\\bbl[eo]w ?down\\b|\\bwater treatment", "r\"\\bwater treatment"),
    ("maint_amps_no_clog_rule", "fabhvac/maintenance/amps.py", "(\"Clogged\", r\"\\bclog\\w*|", "(\"Clogged\", r\""),
    ("maint_amps_least_frequent", "fabhvac/maintenance/amps.py", "ascending=[True, False, True]", "ascending=[True, True, True]"),
]

TEST_CMD = [sys.executable, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider", "-p", "no:warnings",
            "--deselect", "tests/test_golden_results.py::test_results_reproduce_byte_for_byte"]


def run_tests(timeout: int) -> bool:
    """True if the suite passes."""
    p = subprocess.run(TEST_CMD, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    return p.returncode == 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--report", default=str(ROOT / "results" / "mutation_report.json"))
    a = ap.parse_args()
    mutants = [m for m in MUTANTS if m[0].startswith(a.only)]
    if not run_tests(a.timeout):
        print("baseline test suite fails; fix it before mutation testing")
        return 2
    results = []
    for mid, rel, old, new, *flag in mutants:
        equivalent = bool(flag) and flag[0] == "EQUIVALENT"
        path = ROOT / rel
        orig = path.read_bytes()
        text = orig.decode("utf-8")
        n = text.count(old)
        if n != 1:
            results.append({"id": mid, "file": rel, "status": f"SNIPPET_COUNT_{n}"})
            print(f"{mid:28s} snippet found {n} times -> not applied")
            continue
        t0 = time.time()
        try:
            path.write_bytes(text.replace(old, new).encode("utf-8"))
            passed = run_tests(a.timeout)
        finally:
            path.write_bytes(orig)
        status = "survived" if passed else "killed"
        if equivalent:
            status = "equivalent_survived" if passed else "equivalent_killed"
        results.append({"id": mid, "file": rel, "status": status})
        print(f"{mid:28s} {status:9s} ({time.time() - t0:.0f}s)")
    applied = [r for r in results if r["status"] in ("killed", "survived")]
    killed = sum(r["status"] == "killed" for r in applied)
    report = {"killed": killed, "total_applied": len(applied),
              "not_applied": [r["id"] for r in results if r["status"].startswith("SNIPPET")],
              "survivors": [r["id"] for r in applied if r["status"] == "survived"],
              "equivalent": [r for r in results if r["status"].startswith("equivalent")],
              "mutants": results}
    if not a.only:
        write_json(a.report, report)
    else:
        print(json.dumps(report, indent=1))
    print(f"killed {killed}/{len(applied)}")
    return 0 if killed == len(applied) and not report["not_applied"] else 1


if __name__ == "__main__":
    sys.exit(main())
