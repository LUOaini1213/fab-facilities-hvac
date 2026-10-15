"""External design data used by the example calculations (sources in docs/sources.md).

Singapore outdoor design conditions: ASHRAE Handbook - Fundamentals 2021 climatic design
conditions for SINGAPORE CHANGI INTL (WMO 486980), period 1994-2019, as displayed by
ashrae-meteo.info (retrieved 2026-10-02).
"""

CHANGI_2021 = {
    "station": "SINGAPORE CHANGI INTL (WMO 486980)",
    "period": "1994-2019",
    "elevation_m": 7,
    "std_pressure_kpa": 101.24,
    # Annual cooling design conditions: DB / mean coincident WB (degC)
    "cooling_0p4_db_c": 33.2,
    "cooling_0p4_mcwb_c": 26.3,
    "cooling_1p0_db_c": 33.0,
    "cooling_1p0_mcwb_c": 26.2,
    # Annual dehumidification design conditions: DP / HR (g/kg) / mean coincident DB
    "dehum_0p4_dp_c": 27.1,
    "dehum_0p4_hr_g_kg": 22.8,
    "dehum_0p4_mcdb_c": 29.4,
    "dehum_1p0_dp_c": 26.8,
    "dehum_1p0_hr_g_kg": 22.4,
    "dehum_1p0_mcdb_c": 29.2,
    "dehum_2p0_dp_c": 26.2,
    "dehum_2p0_hr_g_kg": 21.7,
    "dehum_2p0_mcdb_c": 28.7,
    # Humidification design (coldest conditions) DP / HR -- used only as a psychrometric check
    "humid_99p6_dp_c": 20.7,
    "humid_99p6_hr_g_kg": 15.4,
    "humid_99p0_dp_c": 21.1,
    "humid_99p0_hr_g_kg": 15.8,
    # Annual enthalpy design condition 0.4%: kJ/kg and MCDB
    "enth_0p4_kj_kg": 88.8,
    "enth_0p4_mcdb_c": 31.0,
}
