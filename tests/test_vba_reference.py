"""Excel-free checks of the VBA <-> Python mapping."""

import re
from pathlib import Path

import pytest

from fabhvac.vba_reference import ERR, FUNCTIONS, grid, python_value

BAS = Path(__file__).resolve().parents[1] / "excel" / "FabHvac.bas"


def test_every_public_vba_function_has_a_python_reference():
    text = BAS.read_text(encoding="utf-8")
    public = set(re.findall(r"^Public Function (FH_\w+)\(", text, flags=re.M))
    assert public == set(FUNCTIONS)


def test_grid_uses_only_known_functions_and_has_error_cases():
    g = grid()
    assert {name for name, _ in g} == set(FUNCTIONS)
    n_err = sum(python_value(n, a) == ERR for n, a in g)
    assert 15 <= n_err < len(g) // 3


@pytest.mark.parametrize("name,args,expected", [
    ("FH_MEES_CHECK", (0.181, 6.5, 2000.0, True), "FAIL"),
    ("FH_MEES_CHECK", (0.181, 6.5, 2000.0, False), "PASS"),
    ("FH_MEES_CHECK", (0.25, 6.5, 1000.0, False), "OUT_OF_SCOPE"),
    ("FH_MEES_CHECK", (-0.1, 7.0, 2000.0, False), ERR),
    ("FH_MEES_CHECK", (0.19, 7.0, -5.0, False), ERR),
    ("FH_MEES_CHECK", (-0.1, 6.5, 500.0, False), ERR),
    ("FH_MEES_LIMIT", (6.2, True), 0.179),
    ("FH_MEES_LIMIT", (2.9, False), ERR),
    ("FH_CT_EFFECTIVENESS", (37.0, 31.5, 27.5), 5.5 / 9.5),
    ("FH_CT_RANGE", (35.2, 29.9), 35.2 - 29.9),
    ("FH_CT_APPROACH", (29.9, 26.1), 29.9 - 26.1),
    ("FH_HEAT_BALANCE_PCT", (1.0, 1.0, 0.0), ERR),
    ("FH_HEAT_BALANCE_PCT", (1000.0, 180.0, 1150.0), 30 / 11.5),
    ("FH_PSY_H", (20.0, -0.001), ERR),
    ("FH_PSY_W_RH", (25.0, 1.1, 101325.0), ERR),
    ("FH_FFU_COUNT", (600.0, 1.0, 0.72), 834),
])
def test_python_reference_values(name, args, expected):
    got = python_value(name, args)
    if isinstance(expected, float):
        assert got == pytest.approx(expected)
    else:
        assert got == expected


def _vba_body(name):
    text = BAS.read_text(encoding="utf-8")
    m = re.search(rf"^Public Function {name}\(.*?^End Function", text, flags=re.M | re.S)
    assert m, name
    return m.group(0)


def test_grid_has_the_invalid_inputs_python_rejects_in_mees_check():
    g = grid()
    rejected = [a for n, a in g if n == "FH_MEES_CHECK" and python_value(n, a) == ERR]
    assert any(a[0] < 0 for a in rejected) and any(a[2] < 0 for a in rejected)
    # a rejected case that would otherwise be OUT_OF_SCOPE (capacity < 1055 kW)
    assert any(a[0] < 0 and 0 <= a[2] < 1055 for a in rejected)


def test_vba_mees_check_rejects_negative_inputs_before_scope():
    """Text check (the .bas is not executed in CI): FH_MEES_CHECK must return ErrValue for
    negative efficiency or capacity before its OUT_OF_SCOPE branch, as chiller.mees_check
    raises ValueError for them before the scope test."""
    body = _vba_body("FH_MEES_CHECK")
    guard = re.search(r"^\s*If kwePerKwc < 0 Or installedCapacityKw < 0 Then FH_MEES_CHECK = ErrValue\(\)",
                      body, flags=re.M)
    scope = body.find('"OUT_OF_SCOPE"')
    assert guard and 0 <= guard.start() < scope
