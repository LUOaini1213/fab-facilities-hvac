"""Cleanroom airborne-particle calculations.

ISO 14644-1 class limit:  Cn = 10**N * (0.1 / D) ** 2.08
  Cn  maximum permitted concentration (particles/m3) of particles >= D
  N   ISO class number, D particle size in micrometres.
See docs/sources.md for where this formula and the published table were verified.

Well-mixed (non-unidirectional) model -- assumptions, stated once here:
  * the room air is perfectly mixed, so the return/exhaust concentration equals
    the room concentration C (particles/m3, for particles >= the size considered);
  * supply airflow Q (m3/s) is a mix of recirculated room air (fraction 1-f) and
    outdoor/make-up air (fraction f) at concentration C_out, the make-up air is
    pre-filtered with single-pass efficiency eta_oa before mixing, and the mix then
    passes a final filter with single-pass efficiency eta (same particle size);
  * room particle generation G (particles/s) is constant; surface deposition,
    re-entrainment and leakage are neglected; steady state.
  Mass balance:  0 = G + Q*Cs - Q*C,   Cs = (1-eta)*[(1-f)*C + f*(1-eta_oa)*C_out]
"""

from __future__ import annotations

import math

ISO_EXPONENT = 2.08
ISO_REF_SIZE_UM = 0.1
ISO_MIN_SIZE_UM = 0.1
ISO_MAX_SIZE_UM = 5.0


def _check_size(d_um: float) -> None:
    if not (ISO_MIN_SIZE_UM <= d_um <= ISO_MAX_SIZE_UM):
        raise ValueError(f"particle size {d_um} um outside 0.1-5 um classification range")


def iso_class_limit(n_class: float, d_um: float) -> float:
    """Unrounded ISO 14644-1 concentration limit (particles/m3 >= d_um)."""
    if not (1.0 <= n_class <= 9.0):
        raise ValueError("ISO class number must be between 1 and 9")
    _check_size(d_um)
    return 10.0 ** n_class * (ISO_REF_SIZE_UM / d_um) ** ISO_EXPONENT


def round_sig(x: float, sig: int) -> float:
    if x == 0:
        return 0.0
    return round(x, sig - 1 - int(math.floor(math.log10(abs(x)))))


def iso_table_value(n_class: float, d_um: float) -> int:
    """Limit as printed in the classification table: 3 significant figures, whole particles."""
    return int(round(round_sig(iso_class_limit(n_class, d_um), 3)))


def iso_class_from_concentration(conc_per_m3: float, d_um: float) -> float:
    """Inverse of iso_class_limit: the (decimal) class number whose limit equals conc."""
    if conc_per_m3 <= 0:
        raise ValueError("concentration must be positive")
    _check_size(d_um)
    return math.log10(conc_per_m3) - ISO_EXPONENT * math.log10(ISO_REF_SIZE_UM / d_um)


# ---------------------------------------------------------------- unidirectional flow

def unidirectional_airflow_m3s(face_velocity_m_s: float, filtered_area_m2: float) -> float:
    """Airflow through a unidirectional (laminar) ceiling: Q = v * A."""
    if face_velocity_m_s <= 0 or filtered_area_m2 <= 0:
        raise ValueError("velocity and area must be positive")
    return face_velocity_m_s * filtered_area_m2


def ffu_count(room_area_m2: float, ceiling_coverage: float, ffu_face_area_m2: float) -> int:
    """Number of fan-filter units to cover `ceiling_coverage` (0-1] of the ceiling."""
    if not (0 < ceiling_coverage <= 1):
        raise ValueError("coverage must be in (0, 1]")
    if room_area_m2 <= 0 or ffu_face_area_m2 <= 0:
        raise ValueError("areas must be positive")
    # small tolerance so 10.000000001 does not become 11 through float noise
    return int(math.ceil(room_area_m2 * ceiling_coverage / ffu_face_area_m2 - 1e-9))


def air_changes_per_hour(q_m3s: float, room_volume_m3: float) -> float:
    if room_volume_m3 <= 0:
        raise ValueError("room volume must be positive")
    return q_m3s * 3600.0 / room_volume_m3


# ---------------------------------------------------------------- well-mixed model

def _penetration(eta: float) -> float:
    if not (0.0 <= eta < 1.0):
        raise ValueError("filter efficiency must be in [0, 1)")
    return 1.0 - eta


def well_mixed_concentration(gen_per_s: float, q_m3s: float, eta: float,
                             oa_fraction: float = 0.0, c_out_per_m3: float = 0.0,
                             eta_oa: float = 0.0) -> float:
    """Steady-state room concentration (particles/m3) for the model in the module docstring."""
    if q_m3s <= 0:
        raise ValueError("airflow must be positive")
    if not (0.0 <= oa_fraction <= 1.0):
        raise ValueError("outdoor-air fraction must be in [0, 1]")
    if gen_per_s < 0 or c_out_per_m3 < 0:
        raise ValueError("generation and outdoor concentration must be >= 0")
    p = _penetration(eta)
    p_oa = _penetration(eta_oa)
    num = gen_per_s / q_m3s + p * oa_fraction * p_oa * c_out_per_m3
    den = 1.0 - p * (1.0 - oa_fraction)
    return num / den


def required_airflow_well_mixed(gen_per_s: float, c_target_per_m3: float, eta: float,
                                oa_fraction: float = 0.0, c_out_per_m3: float = 0.0,
                                eta_oa: float = 0.0) -> float:
    """Supply airflow (m3/s) that holds the room at c_target. Raises if unreachable."""
    if c_target_per_m3 <= 0:
        raise ValueError("target concentration must be positive")
    if gen_per_s < 0 or c_out_per_m3 < 0:
        raise ValueError("generation and outdoor concentration must be >= 0")
    if not (0.0 <= oa_fraction <= 1.0):
        raise ValueError("outdoor-air fraction must be in [0, 1]")
    p = _penetration(eta)
    p_oa = _penetration(eta_oa)
    den = c_target_per_m3 * (1.0 - p * (1.0 - oa_fraction)) - p * oa_fraction * p_oa * c_out_per_m3
    if den <= 0:
        raise ValueError("target unreachable: filtered make-up air alone exceeds the target")
    return gen_per_s / den
