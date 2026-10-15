"""Deterministic result writers (byte-identical on Windows and Linux).

Floats are rounded to 10 significant digits and printed with repr-free formatting;
files are UTF-8 with LF line endings.
"""

from __future__ import annotations

import csv
import io
import json
import math
from pathlib import Path

SIG = 10


def r(x, sig: int = SIG):
    """Round a float to `sig` significant digits; pass through non-floats."""
    if isinstance(x, bool) or x is None:
        return x
    if isinstance(x, int):
        return x
    try:
        xf = float(x)
    except (TypeError, ValueError):
        return x
    if math.isnan(xf) or math.isinf(xf):
        return None
    if xf == 0.0:
        return 0.0
    v = float(f"{xf:.{sig}g}")
    return 0.0 if v == 0 else v


def _clean(obj):
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if hasattr(obj, "item") and callable(obj.item):  # numpy scalar
        obj = obj.item()
    if isinstance(obj, float):
        return r(obj)
    return obj


def write_json(path, obj) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(_clean(obj), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    path.write_bytes(text.encode("utf-8"))


def fmt(x) -> str:
    v = _clean(x)
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.{SIG}g}"
    return str(v)


def write_csv(path, header, rows) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    for row in rows:
        w.writerow([fmt(v) for v in row])
    path.write_bytes(buf.getvalue().encode("utf-8"))
