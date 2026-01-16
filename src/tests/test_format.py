# src/tests/test_format.py
from dircap.format import parse_bytes


def test_parse_bytes_units():
    assert parse_bytes("1KB") == 1024
    assert parse_bytes("1 MB") == 1024 * 1024
    assert parse_bytes("1.5GB") == int(1.5 * 1024**3)
    assert parse_bytes("100") == 100
