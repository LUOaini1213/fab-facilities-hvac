"""Cooling load of a cleanroom bay: make-up air unit (MAU) + recirculation sensible load.

System model (common fab arrangement, stated as an assumption, not a standard):
  * The MAU cools and dehumidifies all outdoor air to a coil-leaving state, then
    optionally reheats it to the MAU supply temperature. All room latent load is
    removed by the MAU (the recirculation dry cooling coils are sensible-only).
  * Recirculation air (FFUs + dry cooling coils, DCC) removes the room sensible
    gains: process-tool heat released to air, FFU fan power (all fan power ends up
    as heat in the air stream), lighting, minus the sensible "cooling credit" of
    MAU air supplied below room temperature.
  * Condensate enthalpy leaving the MAU coil is neglected (coil load = m_da*(h_in-h_out)).

All psychrometric properties come from fabhvac.psychro (PsychroLib, SI).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from . import psychro
from .units import RT_TO_KW


@dataclass(frozen=True)
class MauResult:
    m_da_kg_s: float
    w_out: float
    w_coil: float
    total_kw: float
    sensible_kw: float
    latent_kw: float
    reheat_kw: float
    total_rt: float

    def as_dict(self):
        return asdict(self)


def required_supply_hum_ratio(room_tdb_c: float, room_rh: float, p_pa: float,
                              moisture_gain_kg_s: float, m_da_kg_s: float) -> float:
    """Highest MAU supply humidity ratio that still holds the room at its RH set point."""
    if m_da_kg_s <= 0:
        raise ValueError("make-up air mass flow must be positive")
    w_room = psychro.hum_ratio_from_rh(room_tdb_c, room_rh, p_pa)
    return w_room - moisture_gain_kg_s / m_da_kg_s


def mau_coil_leaving_state(room_tdb_c: float, room_rh: float, p_pa: float, moisture_gain_kg_s: float,
                           oa_flow_m3s_at_coil_leaving: float, db_above_dp_k: float,
                           iterations: int = 50) -> dict:
    """Coil-leaving state that removes the room moisture gain.

    Solved by fixed-point iteration because the dry-air mass flow depends on the
    coil-leaving specific volume, which depends on the humidity ratio being solved for.
    Coil-leaving dry bulb = required dew point + db_above_dp_k (an input assumption).
    """
    if db_above_dp_k < 0:
        raise ValueError("coil-leaving dry bulb cannot be below its dew point")
    w_room = psychro.hum_ratio_from_rh(room_tdb_c, room_rh, p_pa)
    w = w_room
    for _ in range(iterations):
        tdp = psychro.AirState(room_tdb_c, w, p_pa).tdp_c
        t_coil = tdp + db_above_dp_k
        m = oa_flow_m3s_at_coil_leaving / psychro.AirState(t_coil, w, p_pa).v_m3_kg
        w_new = required_supply_hum_ratio(room_tdb_c, room_rh, p_pa, moisture_gain_kg_s, m)
        if w_new <= 0:
            raise ValueError("moisture gain too large for this make-up airflow")
        if abs(w_new - w) < 1e-13:
            w = w_new
            break
        w = w_new
    tdp = psychro.AirState(room_tdb_c, w, p_pa).tdp_c
    return {"w": w, "tdp_c": tdp, "tdb_c": tdp + db_above_dp_k, "w_room": w_room}


def mau_coil_load(oa: psychro.AirState, coil_leaving_tdb_c: float, coil_leaving_w: float,
                  mau_supply_tdb_c: float, oa_flow_m3s_at_coil_leaving: float) -> MauResult:
    """MAU cooling-coil load from outdoor state `oa` to the coil-leaving state.

    Sensible/latent split (enthalpy based, sums exactly to the total):
      latent   = m * [h(T_out, W_out) - h(T_out, W_coil)]
      sensible = m * [h(T_out, W_coil) - h(T_coil, W_coil)]
    """
    p = oa.p_pa
    if coil_leaving_w > oa.w:
        raise ValueError("coil-leaving humidity ratio above outdoor: coil would humidify")
    if coil_leaving_tdb_c > oa.tdb_c:
        raise ValueError("coil-leaving temperature above outdoor")
    w_sat = psychro.hum_ratio_from_rh(coil_leaving_tdb_c, 1.0, p)
    if coil_leaving_w > w_sat * (1 + 1e-12):
        raise ValueError("coil-leaving state is supersaturated")
    coil = psychro.AirState(coil_leaving_tdb_c, coil_leaving_w, p)
    m = oa_flow_m3s_at_coil_leaving / coil.v_m3_kg
    h_out = oa.h_j_kg
    h_out_dry = psychro.enthalpy(oa.tdb_c, coil_leaving_w)
    h_coil = coil.h_j_kg
    latent = m * (h_out - h_out_dry) / 1000.0
    sensible = m * (h_out_dry - h_coil) / 1000.0
    total = latent + sensible
    reheat = 0.0
    if mau_supply_tdb_c > coil_leaving_tdb_c:
        reheat = m * (psychro.enthalpy(mau_supply_tdb_c, coil_leaving_w) - h_coil) / 1000.0
    return MauResult(m_da_kg_s=m, w_out=oa.w, w_coil=coil_leaving_w, total_kw=total, sensible_kw=sensible,
                     latent_kw=latent, reheat_kw=reheat, total_rt=total / RT_TO_KW)


def recirculation_sensible_load_kw(tool_heat_to_air_kw: float, ffu_count: int, ffu_power_w: float,
                                   lighting_w_m2: float, floor_area_m2: float,
                                   m_da_mau_kg_s: float, mau_supply_tdb_c: float,
                                   mau_supply_w: float, room_tdb_c: float) -> dict:
    """Sensible load on the recirculation dry cooling coils (kW)."""
    for name, v in (("tool heat", tool_heat_to_air_kw), ("FFU power", ffu_power_w),
                    ("lighting", lighting_w_m2), ("area", floor_area_m2)):
        if v < 0:
            raise ValueError(f"{name} must be >= 0")
    fan_kw = ffu_count * ffu_power_w / 1000.0
    light_kw = lighting_w_m2 * floor_area_m2 / 1000.0
    internal = tool_heat_to_air_kw + fan_kw + light_kw
    mau_credit = m_da_mau_kg_s * (psychro.enthalpy(room_tdb_c, mau_supply_w)
                                  - psychro.enthalpy(mau_supply_tdb_c, mau_supply_w)) / 1000.0
    dcc = internal - mau_credit
    return {"tool_kw": tool_heat_to_air_kw, "ffu_fan_kw": fan_kw, "lighting_kw": light_kw,
            "internal_sensible_kw": internal, "mau_supply_credit_kw": mau_credit,
            "dcc_kw": dcc, "dcc_rt": dcc / RT_TO_KW}
