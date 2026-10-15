"""Part A: run the engineering calculations and write results/ files (no external data needed).

Outputs
  results/iso_class_limits.csv        ISO 14644-1 limits, formula vs table rounding
  results/mees_table.csv              NEA MEES limits by CHWS temperature (kWe/kWc and kW/RT)
  results/singapore_design_states.json psychrometric states at ASHRAE 2021 Changi design points
  results/bay_example.json            worked example: airflow, FFUs, MAU + recirculation load, plant, tower
  results/well_mixed_sweep.csv        required airflow / ACH vs particle generation (well-mixed model)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fabhvac import chiller, cleanroom, loads, psychro, tower  # noqa: E402
from fabhvac.design_data import CHANGI_2021  # noqa: E402
from fabhvac.results_io import write_csv, write_json  # noqa: E402
from fabhvac.units import RT_TO_KW  # noqa: E402

RES = Path(os.environ.get("FABHVAC_RESULTS_DIR", ROOT / "results"))
SIZES = [0.1, 0.2, 0.3, 0.5, 1.0, 5.0]


def iso_table():
    rows = []
    for n in range(1, 10):
        for d in SIZES:
            rows.append([n, d, cleanroom.iso_class_limit(n, d), cleanroom.iso_table_value(n, d)])
    write_csv(RES / "iso_class_limits.csv", ["iso_class", "size_um", "formula_per_m3", "table_rounded_per_m3"], rows)


def mees_table():
    rows = []
    for t in [3, 4, 5, 6, 7, 8, 9, 10, 11, 12]:
        g = chiller.mees_limit_kwe_per_kwc(t)
        s = chiller.mees_limit_kwe_per_kwc(t, space_cooling_new_building=True)
        rows.append([t, g, chiller.kwe_per_kwc_to_kw_per_rt(g), s, chiller.kwe_per_kwc_to_kw_per_rt(s)])
    write_csv(RES / "mees_table.csv",
              ["chws_c", "general_kwe_per_kwc", "general_kw_per_rt", "space_new_bldg_kwe_per_kwc",
               "space_new_bldg_kw_per_rt"], rows)


def design_states():
    p = CHANGI_2021["std_pressure_kpa"] * 1000.0
    cool = psychro.state_tdb_twb(CHANGI_2021["cooling_0p4_db_c"], CHANGI_2021["cooling_0p4_mcwb_c"], p)
    dehum = psychro.state_tdb_tdp(CHANGI_2021["dehum_0p4_mcdb_c"], CHANGI_2021["dehum_0p4_dp_c"], p)
    enth = psychro.state_tdb_h(CHANGI_2021["enth_0p4_mcdb_c"], CHANGI_2021["enth_0p4_kj_kg"] * 1000.0, p)
    out = {}
    for name, s in (("cooling_0p4_db_mcwb", cool), ("dehum_0p4_dp_mcdb", dehum), ("enthalpy_0p4_h_mcdb", enth)):
        out[name] = {"tdb_c": s.tdb_c, "w_g_kg": s.w * 1000, "h_kj_kg": s.h_j_kg / 1000,
                     "rh": s.rh, "tdp_c": s.tdp_c, "twb_c": s.twb_c, "v_m3_kg": s.v_m3_kg}
    out["pressure_pa"] = p
    out["source"] = "ASHRAE Handbook-Fundamentals 2021, " + CHANGI_2021["station"]
    write_json(RES / "singapore_design_states.json", out)
    return {"cooling_0p4_db_mcwb": cool, "dehum_0p4_dp_mcdb": dehum, "enthalpy_0p4_h_mcdb": enth}


def bay_example(design):
    ex = json.loads((ROOT / "examples" / "bay_example.json").read_text(encoding="utf-8"))
    room = ex["room"]
    area = room["length_m"] * room["width_m"]
    vol = area * room["clear_height_m"]
    p = design["cooling_0p4_db_mcwb"].p_pa

    ud = ex["unidirectional"]
    n_ffu = cleanroom.ffu_count(area, ud["ceiling_coverage"], ud["ffu_face_area_m2"])
    q_ud = cleanroom.unidirectional_airflow_m3s(ud["face_velocity_m_s"], area * ud["ceiling_coverage"])
    cls = ex["cleanliness"]
    limit = cleanroom.iso_class_limit(cls["iso_class"], cls["particle_size_um"])

    # MAU: supply humidity ratio needed to absorb the room moisture gain
    mau = ex["mau"]
    coil = loads.mau_coil_leaving_state(room["tdb_c"], room["rh"], p, mau["moisture_gain_kg_s"],
                                        mau["oa_flow_m3s_at_coil_leaving"], mau["coil_leaving_db_above_dp_k"])
    w_req, tdp_req, t_coil = coil["w"], coil["tdp_c"], coil["tdb_c"]

    cases = {}
    for name, oa in design.items():
        m = loads.mau_coil_load(oa, t_coil, w_req, mau["mau_supply_tdb_c"], mau["oa_flow_m3s_at_coil_leaving"])
        rc = loads.recirculation_sensible_load_kw(
            ex["recirculation"]["tool_heat_to_air_kw"], n_ffu, ud["ffu_power_w"],
            ex["recirculation"]["lighting_w_m2"], area, m.m_da_kg_s, mau["mau_supply_tdb_c"], w_req, room["tdb_c"])
        total_kw = m.total_kw + rc["dcc_kw"]
        cases[name] = {"mau": m.as_dict(), "recirculation": rc,
                       "total_cooling_kw": total_kw, "total_cooling_rt": total_kw / RT_TO_KW,
                       "mau_share_of_total": m.total_kw / total_kw}
    # the recirculation load is the same in every case, so the outdoor point with the largest MAU
    # total load governs total cooling; the largest latent load is reported separately
    governing = max(cases, key=lambda k: cases[k]["total_cooling_kw"])
    governing_latent = max(cases, key=lambda k: cases[k]["mau"]["latent_kw"])

    pl = ex["plant_example"]
    eff = chiller.plant_efficiency_kwe_per_kwc(pl["cooling_kw"], pl["chiller_kw"], pl["chw_pump_kw"],
                                               pl["cdw_pump_kw"], pl["tower_kw"])
    mees = chiller.mees_check(eff, pl["chws_c"], pl["installed_capacity_kw"])
    tw = ex["tower_example"]

    out = {
        "inputs_file": "examples/bay_example.json (illustrative inputs)",
        "inputs": {k: v for k, v in ex.items() if not k.startswith("_")},
        "floor_area_m2": area, "room_volume_m3": vol,
        "iso_limit_per_m3": limit,
        "unidirectional": {"airflow_m3s": q_ud, "ffu_count": n_ffu,
                           "ach": cleanroom.air_changes_per_hour(q_ud, vol)},
        "mau_supply_w_required_g_kg": w_req * 1000, "mau_supply_dp_required_c": tdp_req,
        "mau_coil_leaving_tdb_c": t_coil,
        "cases": cases, "governing_case_total_cooling": governing, "governing_case_mau_latent": governing_latent,
        "plant": {"kwe_per_kwc": eff, "kw_per_rt": chiller.kwe_per_kwc_to_kw_per_rt(eff),
                  "cop": chiller.cop_from_kwe_per_kwc(eff), "mees": mees},
        "tower": {"range_k": tower.scalar(tower.tower_range(tw["t_water_in_c"], tw["t_water_out_c"])),
                  "approach_k": tower.scalar(tower.tower_approach(tw["t_water_out_c"], tw["t_wb_c"])),
                  "effectiveness": tower.scalar(tower.tower_effectiveness(tw["t_water_in_c"], tw["t_water_out_c"], tw["t_wb_c"]))},
        "mv_min_chw_delta_t_k_at_sensor_limits": chiller.min_chw_delta_t_for_uncertainty(),
    }
    write_json(RES / "bay_example.json", out)

    wm = ex["well_mixed_support_area"]
    target = cleanroom.iso_class_limit(wm["iso_class"], wm["particle_size_um"])
    rows = []
    for g in wm["generation_sweep_per_s"]:
        try:
            q = cleanroom.required_airflow_well_mixed(g, target, wm["final_filter_efficiency"], wm["oa_fraction"],
                                                      wm["outdoor_conc_per_m3"], wm["oa_prefilter_efficiency"])
            rows.append([g, target, q, cleanroom.air_changes_per_hour(q, wm["room_volume_m3"]), "ok"])
        except ValueError:
            rows.append([g, target, None, None, "unreachable"])
    write_csv(RES / "well_mixed_sweep.csv",
              ["generation_per_s", "target_per_m3", "required_supply_m3s", "required_ach", "status"], rows)


def main():
    RES.mkdir(parents=True, exist_ok=True)
    iso_table()
    mees_table()
    bay_example(design_states())
    print("Part A results written to", RES)


if __name__ == "__main__":
    main()
