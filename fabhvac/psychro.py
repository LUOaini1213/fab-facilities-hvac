"""Psychrometrics (SI) on top of PsychroLib (ASHRAE Handbook - Fundamentals 2017, ch. 1).

Units: temperature degC, pressure Pa, humidity ratio kg_w/kg_da, enthalpy J/kg_da,
relative humidity as a fraction 0..1.
"""

from __future__ import annotations

from dataclasses import dataclass

import psychrolib as _psy

_psy.SetUnitSystem(_psy.SI)


@dataclass(frozen=True)
class AirState:
    tdb_c: float
    w: float  # humidity ratio kg/kg dry air
    p_pa: float

    @property
    def h_j_kg(self) -> float:
        return _psy.GetMoistAirEnthalpy(self.tdb_c, self.w)

    @property
    def rh(self) -> float:
        return _psy.GetRelHumFromHumRatio(self.tdb_c, self.w, self.p_pa)

    @property
    def tdp_c(self) -> float:
        return _psy.GetTDewPointFromHumRatio(self.tdb_c, self.w, self.p_pa)

    @property
    def twb_c(self) -> float:
        return _psy.GetTWetBulbFromHumRatio(self.tdb_c, self.w, self.p_pa)

    @property
    def v_m3_kg(self) -> float:
        """Specific volume, m3 per kg of dry air."""
        return _psy.GetMoistAirVolume(self.tdb_c, self.w, self.p_pa)


def sat_vap_pres(tdb_c: float) -> float:
    return _psy.GetSatVapPres(tdb_c)


def hum_ratio_from_rh(tdb_c: float, rh: float, p_pa: float) -> float:
    return _psy.GetHumRatioFromRelHum(tdb_c, rh, p_pa)


def hum_ratio_from_twb(tdb_c: float, twb_c: float, p_pa: float) -> float:
    return _psy.GetHumRatioFromTWetBulb(tdb_c, twb_c, p_pa)


def hum_ratio_from_tdp(tdp_c: float, p_pa: float) -> float:
    return _psy.GetHumRatioFromTDewPoint(tdp_c, p_pa)


def enthalpy(tdb_c: float, w: float) -> float:
    return _psy.GetMoistAirEnthalpy(tdb_c, w)


def dew_point_from_rh(tdb_c: float, rh: float) -> float:
    return _psy.GetTDewPointFromRelHum(tdb_c, rh)


def wet_bulb_from_rh(tdb_c: float, rh: float, p_pa: float) -> float:
    return _psy.GetTWetBulbFromRelHum(tdb_c, rh, p_pa)


def state_tdb_rh(tdb_c: float, rh: float, p_pa: float) -> AirState:
    return AirState(tdb_c, hum_ratio_from_rh(tdb_c, rh, p_pa), p_pa)


def state_tdb_twb(tdb_c: float, twb_c: float, p_pa: float) -> AirState:
    return AirState(tdb_c, hum_ratio_from_twb(tdb_c, twb_c, p_pa), p_pa)


def state_tdb_h(tdb_c: float, h_j_kg: float, p_pa: float) -> AirState:
    """State from dry bulb and enthalpy (e.g. the ASHRAE enthalpy design point with its
    mean coincident dry bulb)."""
    w = _psy.GetHumRatioFromEnthalpyAndTDryBulb(h_j_kg, tdb_c)
    if w > hum_ratio_from_rh(tdb_c, 1.0, p_pa):
        raise ValueError("enthalpy above saturation at this dry bulb")
    return AirState(tdb_c, w, p_pa)


def state_tdb_tdp(tdb_c: float, tdp_c: float, p_pa: float) -> AirState:
    if tdp_c > tdb_c:
        raise ValueError("dew point above dry bulb")
    return AirState(tdb_c, hum_ratio_from_tdp(tdp_c, p_pa), p_pa)
