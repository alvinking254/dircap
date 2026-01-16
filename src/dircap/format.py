# src/dircap/format.py
from __future__ import annotations

import re

_UNITS = {
    "B": 1,
    "KB": 1024,
    "MB": 1024**2,
    "GB": 1024**3,
    "TB": 1024**4,
}


def parse_bytes(s: str) -> int:
    """
    Accepts inputs like: 500MB, 5 GB, 1200, 1.5GB
    Returns bytes as an int.

    """
    s = s.strip()
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*([a-zA-Z]{0,2})\s*$", s)
    if not m:
        raise ValueError(f"Invalid size: {s}")

    num = float(m.group(1))
    unit = (m.group(2) or "B").upper()
    if unit == "":
        unit = "B"

    if unit not in _UNITS:
        raise ValueError(f"Unknown unit '{unit}' in '{s}'. Use B/KB/MB/GB/TB.")

    return int(num * _UNITS[unit])


def format_bytes(n: int) -> str:
    if n < 1024:
        return f"{n}B"

    for unit in ["KB", "MB", "GB", "TB"]:
        val = n / _UNITS[unit]
        if val < 1024:
            if val >= 10:
                return f"{val:.0f}{unit}"
            return f"{val:.1f}{unit}"

    return f"{n / _UNITS['TB']:.1f}TB"
