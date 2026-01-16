# src/dircap/config.py
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except Exception:  # pragma: no cover
    tomllib = None  # type: ignore

try:
    import tomli  # Python < 3.11 (optional dependency)
except Exception:  # pragma: no cover
    tomli = None  # type: ignore

DEFAULT_EXCLUDES = [".git", "node_modules", "__pycache__", ".venv", "dist", "build"]


@dataclass(frozen=True)
class BudgetItem:
    name: str
    path: str
    limit: str
    warn_pct: int | None = None


@dataclass(frozen=True)
class Settings:
    default_warn_pct: int = 85
    follow_symlinks: bool = False
    max_depth: int = 50
    exclude_dirnames: list[str] = field(default_factory=lambda: list(DEFAULT_EXCLUDES))


@dataclass(frozen=True)
class ActionConfig:
    # Empty string means "disabled", we normalize it to None on load.
    on_warn: str | None = None
    on_over: str | None = None


@dataclass(frozen=True)
class AppConfig:
    settings: Settings
    action: ActionConfig
    budgets: list[BudgetItem]


def _default_config_dir() -> Path:
    """
    Config directory:
      Windows: %APPDATA%\\dircap
      macOS/Linux: ~/.config/dircap
    """
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA")
        if base:
            return Path(base) / "dircap"
        # Fallback if APPDATA is missing for some reason
        return Path.home() / "AppData" / "Roaming" / "dircap"
    return Path.home() / ".config" / "dircap"


def config_path() -> Path:
    return _default_config_dir() / "config.toml"


def default_config_text() -> str:
    # Keep actions empty. Users can opt-in with their own scripts.
    return """[settings]
default_warn_pct = 85
follow_symlinks = false
max_depth = 50
exclude_dirnames = [".git", "node_modules", "__pycache__", ".venv", "dist", "build"]

[action]
# Optional: run a command when WARN/OVER is detected.
# Placeholders: {name} {path} {used} {limit} {pct} {status}
#
# SECURITY NOTE:
# These commands are executed via your shell (shell=true). Only use actions you trust.
on_warn = ""
on_over = ""

[[budgets]]
name = "Downloads"
path = "~/Downloads"
limit = "5GB"
warn_pct = 80
"""


def ensure_config_exists() -> Path:
    p = config_path()
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(default_config_text(), encoding="utf-8")
    return p


def _expand_path(p: str) -> str:
    # Expand ~ and env vars, then resolve to an absolute path where possible.
    expanded = os.path.expandvars(os.path.expanduser(p))
    return str(Path(expanded).resolve())


def _loads_toml(text: str) -> dict:
    if tomllib is not None:
        return tomllib.loads(text)
    if tomli is not None:
        return tomli.loads(text)
    raise RuntimeError("TOML parser not available. Use Python 3.11+ or install tomli.")


def _normalize_action(s: object) -> str | None:
    if s is None:
        return None
    val = str(s).strip()
    return val or None


def load_config(p: Path | None = None) -> AppConfig:
    """
    Load config.toml and return a normalized AppConfig.

    Notes:
    - Budget paths are expanded (~ and env vars) and resolved.
    - Empty action strings are normalized to None (disabled).
    """
    p = p or config_path()

    if not p.exists():
        raise FileNotFoundError(f"Config not found: {p}")

    raw = _loads_toml(p.read_text(encoding="utf-8"))

    sraw = raw.get("settings", {}) or {}
    settings = Settings(
        default_warn_pct=int(sraw.get("default_warn_pct", 85)),
        follow_symlinks=bool(sraw.get("follow_symlinks", False)),
        max_depth=int(sraw.get("max_depth", 50)),
        exclude_dirnames=list(sraw.get("exclude_dirnames", DEFAULT_EXCLUDES)),
    )

    araw = raw.get("action", {}) or {}
    action = ActionConfig(
        on_warn=_normalize_action(araw.get("on_warn")),
        on_over=_normalize_action(araw.get("on_over")),
    )

    budgets_raw = raw.get("budgets", []) or []
    budgets: list[BudgetItem] = []
    for b in budgets_raw:
        # Keep name stable
        name = str(b.get("name") or b.get("path") or "Unnamed").strip() or "Unnamed"
        path = _expand_path(str(b["path"]))
        limit = str(b["limit"]).strip()

        warn_pct = None
        if "warn_pct" in b and b["warn_pct"] is not None:
            warn_pct = int(b["warn_pct"])

        budgets.append(BudgetItem(name=name, path=path, limit=limit, warn_pct=warn_pct))

    return AppConfig(settings=settings, action=action, budgets=budgets)
