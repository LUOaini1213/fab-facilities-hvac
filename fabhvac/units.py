"""Unit conversion constants.

Every constant here is quoted from a public source listed in docs/sources.md.
Do not add a constant without adding its source there.
"""

from __future__ import annotations

# NIST SP 811, Appendix B.9: ton of refrigeration (12 000 Btu_IT/h) = 3.516 853 E+03 W
RT_TO_KW = 3.516853

# NIST SP 811, Appendix B.9: foot per minute (ft/min) = 5.08 E-03 m/s
FPM_TO_M_S = 5.08e-3

# NIST SP 811, Appendix B.9: cubic foot per minute = 4.719 474 E-04 m^3/s
CFM_TO_M3_S = 4.719474e-4

# NIST SP 811, Appendix B.9: gallon (U.S.) per minute = 6.309 020 E-05 m^3/s
GPM_TO_M3_S = 6.309020e-5

# NIST SP 811, Appendix B.9: inch of water, conventional (inH2O) = 2.490 889 E+02 Pa
INH2O_TO_PA = 249.0889

# NEA "Requirements and Guidelines on M&V for MEES" (reference formulae, p.13):
# chilled water Cp ~ 4.19 kJ/(kg.K), condenser water Cp ~ 4.18 kJ/(kg.K),
# 1 L/s of water ~ 1 kg/s, RT = kW / 3.517.
NEA_CP_CHW_KJ_KGK = 4.19
NEA_CP_CDW_KJ_KGK = 4.18
NEA_RT_TO_KW = 3.517


def f_to_c(t_f):
    """Temperature in degF -> degC. NIST SP 811 B.9: t/degC = (t/degF - 32)/1.8."""
    return (t_f - 32.0) / 1.8


def c_to_f(t_c):
    """Temperature in degC -> degF (inverse of f_to_c)."""
    return t_c * 1.8 + 32.0


def delta_f_to_delta_c(dt_f):
    """Temperature *difference* in degF -> K. NIST SP 811 B.9: 1 degF interval = 5/9 K."""
    return dt_f / 1.8


def kw_to_rt(kw):
    return kw / RT_TO_KW


def rt_to_kw(rt):
    return rt * RT_TO_KW
