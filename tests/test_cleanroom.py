import math

import pytest

from fabhvac import cleanroom as cr

# ISO 14644-1 classification table as reproduced in Xu Z. (2013), Table 7.6
# (see docs/sources.md). Blank cells of the published table are omitted.
PUBLISHED = {
    1: {0.1: 10, 0.2: 2},
    2: {0.1: 100, 0.2: 24, 0.3: 10, 0.5: 4},
    3: {0.1: 1000, 0.2: 237, 0.3: 102, 0.5: 35, 1.0: 8},
    4: {0.1: 10000, 0.2: 2370, 0.3: 1020, 0.5: 352, 1.0: 83},
    5: {0.1: 100000, 0.2: 23700, 0.3: 10200, 0.5: 3520, 1.0: 832, 5.0: 29},
    6: {0.1: 1000000, 0.2: 237000, 0.3: 102000, 0.5: 35200, 1.0: 8320, 5.0: 293},
    7: {0.5: 352000, 1.0: 83200, 5.0: 2930},
    8: {0.5: 3520000, 1.0: 832000, 5.0: 29300},
    9: {0.5: 35200000, 1.0: 8320000, 5.0: 293000},
}


@pytest.mark.parametrize("n,d,expected", [(n, d, v) for n, row in PUBLISHED.items() for d, v in row.items()])
def test_formula_reproduces_published_table(n, d, expected):
    assert cr.iso_table_value(n, d) == expected


def test_unrounded_limit_values():
    assert cr.iso_class_limit(5, 0.5) == pytest.approx(3516.757246, rel=1e-9)
    assert cr.iso_class_limit(6.5, 0.3) == pytest.approx(10 ** 6.5 * (1 / 3) ** 2.08, rel=1e-12)
    # 0.1 um is the reference size: limit is exactly 10^N
    assert cr.iso_class_limit(4, 0.1) == pytest.approx(10000.0, rel=1e-15)


@pytest.mark.parametrize("n,d", [(3.7, 0.2), (6.5, 0.5), (8.1, 5.0), (1.0, 0.1)])
def test_class_from_concentration_inverts_limit(n, d):
    assert cr.iso_class_from_concentration(cr.iso_class_limit(n, d), d) == pytest.approx(n, abs=1e-12)


def test_class_from_concentration_ordering():
    # more particles -> higher (dirtier) class number
    assert cr.iso_class_from_concentration(3520, 0.5) < cr.iso_class_from_concentration(3521, 0.5)
    assert cr.iso_class_from_concentration(3516.757246, 0.5) == pytest.approx(5.0, abs=1e-9)


@pytest.mark.parametrize("args", [(0.9, 0.5), (9.01, 0.5), (5, 0.09), (5, 5.01)])
def test_limit_rejects_out_of_range(args):
    with pytest.raises(ValueError):
        cr.iso_class_limit(*args)


def test_class_from_concentration_rejects_nonpositive():
    with pytest.raises(ValueError):
        cr.iso_class_from_concentration(0.0, 0.5)
    with pytest.raises(ValueError):
        cr.iso_class_from_concentration(100.0, 7.0)


def test_round_sig():
    assert cr.round_sig(23651.44, 3) == 23700
    assert cr.round_sig(0.0123456, 2) == pytest.approx(0.012)
    assert cr.round_sig(0.0, 3) == 0.0


def test_unidirectional_airflow_and_ffu():
    assert cr.unidirectional_airflow_m3s(0.45, 123.4) == pytest.approx(55.53)
    assert cr.ffu_count(600.0, 1.0, 0.72) == 834      # 833.33 -> 834
    assert cr.ffu_count(72.0, 1.0, 0.72) == 100       # exact multiple must not round up
    assert 102.4 * 0.45 / 0.72 > 64                   # float noise: 64.00000000000001 ...
    assert cr.ffu_count(102.4, 0.45, 0.72) == 64      # ... must still give 64 units, not 65
    assert cr.ffu_count(250.0, 0.35, 0.72) == 122     # 121.53 -> 122
    with pytest.raises(ValueError):
        cr.ffu_count(100.0, 1.2, 0.72)
    with pytest.raises(ValueError):
        cr.ffu_count(100.0, 0.0, 0.72)
    with pytest.raises(ValueError):
        cr.unidirectional_airflow_m3s(0.0, 10.0)
    with pytest.raises(ValueError):
        cr.unidirectional_airflow_m3s(0.4, -1.0)


def test_ach():
    assert cr.air_changes_per_hour(240.0, 2400.0) == pytest.approx(360.0)
    assert cr.air_changes_per_hour(1.37, 950.0) == pytest.approx(5.191578947, rel=1e-9)
    with pytest.raises(ValueError):
        cr.air_changes_per_hour(1.0, 0.0)


def test_well_mixed_hand_value():
    # G=2e5 /s, Q=3.1 m3/s, eta=0.9997, f=0.1, Cout=3e7, eta_oa=0.9
    p = 1 - 0.9997
    expected = (2e5 / 3.1 + p * 0.1 * 0.1 * 3e7) / (1 - p * 0.9)
    assert cr.well_mixed_concentration(2e5, 3.1, 0.9997, 0.1, 3e7, 0.9) == pytest.approx(expected, rel=1e-12)
    assert expected == pytest.approx(64623.5774, rel=1e-8)


def test_well_mixed_matches_transient_integration():
    """Independent check: integrate dC/dt to steady state and compare with the closed form."""
    g, q, eta, f, c_out, eta_oa, vol = 5.0e4, 0.8, 0.95, 0.3, 1.0e7, 0.5, 40.0
    c, dt = 0.0, 0.05
    for _ in range(40000):
        cs = (1 - eta) * ((1 - f) * c + f * (1 - eta_oa) * c_out)
        c += dt * (g + q * cs - q * c) / vol
    assert cr.well_mixed_concentration(g, q, eta, f, c_out, eta_oa) == pytest.approx(c, rel=1e-6)


def test_required_airflow_roundtrip_and_monotonic():
    target = cr.iso_class_limit(7, 0.5)
    q = cr.required_airflow_well_mixed(3.3e6, target, 0.995, 0.25, 2.0e7, 0.6)
    assert cr.well_mixed_concentration(3.3e6, q, 0.995, 0.25, 2.0e7, 0.6) == pytest.approx(target, rel=1e-12)
    q_better = cr.required_airflow_well_mixed(3.3e6, target, 0.9997, 0.25, 2.0e7, 0.6)
    assert q_better < q
    q_dirtier = cr.required_airflow_well_mixed(6.6e6, target, 0.995, 0.25, 2.0e7, 0.6)
    assert q_dirtier > q


def test_required_airflow_no_outdoor_term_is_linear():
    # with f=0 the model reduces to Q = G / (C * eta)
    assert cr.required_airflow_well_mixed(1.0e5, 2.0e4, 0.9, 0.0) == pytest.approx(1.0e5 / (2.0e4 * 0.9))


def test_required_airflow_unreachable():
    with pytest.raises(ValueError):
        cr.required_airflow_well_mixed(1.0e5, 100.0, 0.9, 1.0, 1.0e8, 0.0)


@pytest.mark.parametrize("kw", [dict(eta=1.0), dict(eta=-0.1), dict(oa_fraction=1.5), dict(eta_oa=1.0)])
def test_well_mixed_rejects_bad_inputs(kw):
    args = dict(gen_per_s=1e5, q_m3s=2.0, eta=0.99, oa_fraction=0.2, c_out_per_m3=1e7, eta_oa=0.5)
    args.update(kw)
    with pytest.raises(ValueError):
        cr.well_mixed_concentration(**args)


def test_well_mixed_rejects_zero_flow_and_negative_generation():
    with pytest.raises(ValueError):
        cr.well_mixed_concentration(1e5, 0.0, 0.99)
    with pytest.raises(ValueError):
        cr.required_airflow_well_mixed(-1.0, 1000.0, 0.99)
    with pytest.raises(ValueError):
        cr.required_airflow_well_mixed(1.0, 0.0, 0.99)
    assert math.isfinite(cr.well_mixed_concentration(0.0, 1.0, 0.5))
