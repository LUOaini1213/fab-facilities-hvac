"""Verdicts require known physical inputs and correctly paired measurements."""
import math

import numpy as np
import pytest

from fabhvac import chiller as ch


@pytest.mark.parametrize("position", [0, 1, 2])
@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, True, 10 ** 400])
def test_mees_rejects_unknown_or_non_numeric_inputs_before_verdict(position, value):
    args = [0.19, 7.0, 2000.0]
    args[position] = value
    with pytest.raises(ValueError):
        ch.mees_check(*args)


@pytest.mark.parametrize("efficiency,capacity", [(-0.1, 2000), (0.19, -1), (math.nan, 0)])
def test_mees_rejects_impossible_or_missing_values_even_outside_scope(efficiency, capacity):
    with pytest.raises(ValueError):
        ch.mees_check(efficiency, 7, capacity)


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, True, 10 ** 400])
def test_scope_and_limit_entrypoints_validate_known_temperatures(value):
    with pytest.raises(ValueError):
        ch.mees_in_scope(2000, value)
    with pytest.raises(ValueError):
        ch.mees_limit_kwe_per_kwc(value)


@pytest.mark.parametrize("position", range(5))
@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, True])
def test_plant_efficiency_rejects_nonfinite_inputs(position, value):
    args = [4000, 560, 70, 80, 45]
    args[position] = value
    with pytest.raises(ValueError):
        ch.plant_efficiency_kwe_per_kwc(*args)


@pytest.mark.parametrize("args", [(1, 1e308, 1e308), (1e-308, 1e308)])
def test_plant_efficiency_cannot_publish_overflow(args):
    with pytest.raises(ValueError):
        ch.plant_efficiency_kwe_per_kwc(*args)


def test_known_valid_scope_and_zero_boundaries_are_unchanged():
    assert ch.mees_check(0.19, 7, 0)["verdict"] == "OUT_OF_SCOPE"
    assert ch.mees_check(0.19, -5, 2000)["verdict"] == "OUT_OF_SCOPE"
    assert ch.plant_efficiency_kwe_per_kwc(4000, 0) == 0
    assert ch.mees_check(0, 7, 2000)["verdict"] == "PASS"
    assert ch.mees_check(np.float64(0.19), np.float64(7), np.int64(2000))["verdict"] == "PASS"


@pytest.mark.parametrize("args", [
    ([800, 1800], [200, 200], [[1000], [2000]]),
    ([800, 1800], 200, [1000, 2000]),
    ([800, 1800], [200], [1000, 2000]),
])
def test_heat_balance_rejects_cross_broadcasting(args):
    with pytest.raises(ValueError, match="shape"):
        ch.heat_balance_test(*args)


@pytest.mark.parametrize("position", range(3))
def test_heat_balance_rejects_negative_physical_rates(position):
    args = [[800], [200], [1000]]
    args[position] = [-1]
    with pytest.raises(ValueError):
        ch.heat_balance_test(*args)
    with pytest.raises(ValueError):
        ch.heat_balance_test([-800], [-200], [-1000])


@pytest.mark.parametrize("name,value", [
    ("tol_pct", math.nan), ("tol_pct", math.inf), ("tol_pct", -1), ("tol_pct", True),
    ("required_fraction", math.nan), ("required_fraction", math.inf),
    ("required_fraction", -0.1), ("required_fraction", 1.1), ("required_fraction", True),
])
def test_heat_balance_rejects_invalid_acceptance_settings(name, value):
    with pytest.raises(ValueError):
        ch.heat_balance_test([100], [1], [10000], **{name: value})


def test_finite_overflow_is_not_silently_removed_like_missing_measurements():
    with pytest.raises(ValueError, match="overflow"):
        ch.heat_balance_test([800, 1e308], [200, 1e308], [1000, 1e308])


def test_heat_balance_keeps_paired_scalars_and_same_shape_arrays():
    expected = {"n_points": 2, "fraction_within": 1.0, "passes": True, "median_pct": 0.0}
    assert ch.heat_balance_test([800, 1800], [200, 200], [1000, 2000]) == expected
    assert ch.heat_balance_test([[800], [1800]], [[200], [200]], [[1000], [2000]]) == expected
    assert ch.heat_balance_test(800, 200, 1000, tol_pct=0, required_fraction=1)["passes"]
    assert ch.heat_balance_test(100, 1, 10000, required_fraction=0)["passes"]


def test_heat_balance_preserves_explicit_missing_and_zero_rejection_exclusion():
    result = ch.heat_balance_test([800, math.nan, 800], [200, 200, 200], [1000, 1000, 0])
    assert result == {"n_points": 1, "fraction_within": 1.0, "passes": True, "median_pct": 0.0}
    with pytest.raises(ValueError, match="no valid"):
        ch.heat_balance_test([math.nan], [200], [1000])
