# src/tests/test_evaluate.py
from dircap.scan import evaluate


def test_evaluate_ok_warn_over_boundaries():
    r_ok = evaluate(name="x", path=".", limit="100B", warn_pct=80, used_bytes=79)
    assert r_ok.status == "OK"

    r_warn = evaluate(name="x", path=".", limit="100B", warn_pct=80, used_bytes=80)
    assert r_warn.status == "WARN"

    r_over = evaluate(name="x", path=".", limit="100B", warn_pct=80, used_bytes=100)
    assert r_over.status == "OVER"


def test_evaluate_zero_limit_is_over():
    r = evaluate(name="x", path=".", limit="0B", warn_pct=80, used_bytes=1)
    assert r.status == "OVER"
