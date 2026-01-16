# src/tests/test_config_actions.py
from pathlib import Path

from dircap.config import load_config


def test_empty_actions_normalize_to_none(tmp_path: Path):
    cfg_text = """
[settings]
default_warn_pct = 85
follow_symlinks = false
max_depth = 50
exclude_dirnames = [".git"]

[action]
on_warn = ""
on_over = "   "

[[budgets]]
name = "X"
path = "."
limit = "1GB"
"""
    p = tmp_path / "config.toml"
    p.write_text(cfg_text, encoding="utf-8")

    cfg = load_config(p)
    assert cfg.action.on_warn is None
    assert cfg.action.on_over is None
