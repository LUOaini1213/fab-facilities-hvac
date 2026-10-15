import numpy as np
import pytest

from fabhvac import tower, units


def test_range_approach_effectiveness_scalar():
    assert tower.scalar(tower.tower_range(37.0, 31.5)) == pytest.approx(5.5)
    assert tower.scalar(tower.tower_approach(31.5, 27.5)) == pytest.approx(4.0)
    assert tower.scalar(tower.tower_effectiveness(37.0, 31.5, 27.5)) == pytest.approx(5.5 / 9.5)


def test_effectiveness_equals_range_over_range_plus_approach():
    tin, tout, twb = 35.2, 29.9, 26.1
    rng = tower.scalar(tower.tower_range(tin, tout))
    app = tower.scalar(tower.tower_approach(tout, twb))
    assert tower.scalar(tower.tower_effectiveness(tin, tout, twb)) == pytest.approx(rng / (rng + app))


def test_vectorised_and_invalid():
    eff = tower.tower_effectiveness(np.array([37.0, 33.0]), np.array([31.5, 30.0]), np.array([27.5, 24.0]))
    assert eff == pytest.approx([5.5 / 9.5, 3.0 / 9.0])
    with pytest.raises(ValueError):
        tower.tower_effectiveness(25.0, 24.0, 26.0)
    assert isinstance(tower.scalar(np.float64(2.0)), float)


def test_unit_conversions():
    assert units.f_to_c(212.0) == pytest.approx(100.0)
    assert units.f_to_c(42.0) == pytest.approx(5.5555555556)
    assert units.c_to_f(units.f_to_c(51.4)) == pytest.approx(51.4)
    assert units.delta_f_to_delta_c(9.0) == pytest.approx(5.0)
    assert units.kw_to_rt(3516.853) == pytest.approx(1000.0)
    assert units.rt_to_kw(300.0) == pytest.approx(1055.0559)
    assert units.GPM_TO_M3_S * 1000 * 60 == pytest.approx(3.785412, rel=1e-6)  # 1 US gal = 3.785412 L
    assert units.FPM_TO_M_S == pytest.approx(0.3048 / 60)
    assert units.CFM_TO_M3_S == pytest.approx(0.3048 ** 3 / 60, rel=1e-6)
