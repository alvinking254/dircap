# src/dircap/scan.py
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .format import parse_bytes


@dataclass(frozen=True)
class ScanResult:
    name: str
    path: str
    used_bytes: int
    limit_bytes: int
    warn_pct: int
    pct_used: int
    status: str  # OK / WARN / OVER


@dataclass(frozen=True)
class ScanOutcome:
    """
    Result of trying to measure usage for a configured path.

    - used_bytes: best-effort usage
    - note: optional friendly message (warnings, edge cases)
    """

    used_bytes: int
    note: str | None = None


def folder_size_bytes(
    root: Path,
    *,
    exclude_dirnames: set[str],
    follow_symlinks: bool,
    max_depth: int,
) -> ScanOutcome:
    """
    Fast directory traversal using os.scandir.

    Behavior (best practice for schedulers):
    - Missing paths -> used_bytes=0 + note (not fatal)
    - File paths -> file size + note (not fatal)
    - Permission/Not-a-directory errors -> used_bytes=0 + note (not fatal)
    - Exclusions are by directory *name* (fast)
    - Depth limit prevents runaway scans
    """
    try:
        if not root.exists():
            return ScanOutcome(used_bytes=0, note=f"path does not exist: {root}")

        # If user accidentally configured a file instead of a folder, don't crash.
        if root.is_file():
            try:
                sz = int(root.stat().st_size)
            except (FileNotFoundError, PermissionError, OSError):
                return ScanOutcome(used_bytes=0, note=f"file is not accessible: {root}")
            return ScanOutcome(
                used_bytes=sz,
                note=f"path is a file (not a folder); using file size: {root}",
            )

    except (PermissionError, OSError):
        # exists()/is_file() can throw if the path is not accessible
        return ScanOutcome(used_bytes=0, note=f"path is not accessible: {root}")

    total = 0

    def walk(p: Path, depth: int) -> None:
        nonlocal total
        if depth > max_depth:
            return

        try:
            with os.scandir(p) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=follow_symlinks):
                            if entry.name in exclude_dirnames:
                                continue
                            walk(Path(entry.path), depth + 1)
                        else:
                            st = entry.stat(follow_symlinks=follow_symlinks)
                            total += int(st.st_size)
                    except (FileNotFoundError, PermissionError, NotADirectoryError, OSError):
                        # Race conditions and access issues are normal in real file systems.
                        continue
        except (FileNotFoundError, PermissionError, NotADirectoryError, OSError):
            return

    walk(root, 0)
    return ScanOutcome(used_bytes=total, note=None)


def evaluate(*, name: str, path: str, limit: str, warn_pct: int, used_bytes: int) -> ScanResult:
    limit_bytes = parse_bytes(limit)

    if limit_bytes <= 0:
        # Treat invalid/zero limits as "OVER" so automation catches it.
        return ScanResult(
            name=name,
            path=path,
            used_bytes=used_bytes,
            limit_bytes=limit_bytes,
            warn_pct=warn_pct,
            pct_used=100,
            status="OVER",
        )

    pct_used = int(round((used_bytes / limit_bytes) * 100))

    if pct_used >= 100:
        status = "OVER"
    elif pct_used >= warn_pct:
        status = "WARN"
    else:
        status = "OK"

    return ScanResult(
        name=name,
        path=path,
        used_bytes=used_bytes,
        limit_bytes=limit_bytes,
        warn_pct=warn_pct,
        pct_used=pct_used,
        status=status,
    )
