"""Cooling-tower performance indicators (definitions, no empirical constants).

  range         = T_water_in - T_water_out          (water cooled across the tower)
  approach      = T_water_out - T_wet_bulb_entering  (how close the cold water gets to wet bulb)
  effectiveness = range / (range + approach) = (T_in - T_out) / (T_in - T_wb)
                  i.e. actual cooling over the ideal cooling to the wet-bulb limit.
"""

from __future__ import annotations

import numpy as np


def tower_range(t_water_in, t_water_out):
    return np.asarray(t_water_in, dtype=float) - np.asarray(t_water_out, dtype=float)


def tower_approach(t_water_out, t_wb):
    return np.asarray(t_water_out, dtype=float) - np.asarray(t_wb, dtype=float)


def tower_effectiveness(t_water_in, t_water_out, t_wb):
    t_in = np.asarray(t_water_in, dtype=float)
    t_wb_ = np.asarray(t_wb, dtype=float)
    denom = t_in - t_wb_
    if np.any(denom <= 0):
        raise ValueError("entering water must be warmer than the wet bulb")
    return (t_in - np.asarray(t_water_out, dtype=float)) / denom


def scalar(x):
    """Unwrap 0-d numpy results to float (keeps the API friendly for scalars)."""
    a = np.asarray(x)
    return float(a) if a.ndim == 0 else a
