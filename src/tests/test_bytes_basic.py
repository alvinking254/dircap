# src/tests/test_human_bytes.py
from dircap.format import format_bytes


def test_bytes_basic():
    assert format_bytes(0) == "0B"
    assert format_bytes(1) == "1B"
    assert format_bytes(1023) == "1023B"
    assert format_bytes(1024) == "1.0KB"
    assert format_bytes(10 * 1024) == "10KB"
