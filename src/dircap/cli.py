# src/dircap/cli.py
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

import dircap

from .config import config_path, ensure_config_exists, load_config
from .format import format_bytes, parse_bytes
from .scan import ScanResult, evaluate, folder_size_bytes

app = typer.Typer(
    add_completion=False,
    help="Set folder size caps and get warned when you exceed them.",
)

# Scheduler/redirected output on Windows is not a real terminal.
# Force Rich to render anyway so log files still include readable tables.
console = Console(force_terminal=True, width=120)


@app.callback(invoke_without_command=True)
def _main(
    version: bool = typer.Option(False, "--version", help="Show version and exit."),
):
    """
    Global options for the CLI.

    Notes:
    - `dircap --help` shows all commands.
    - `dircap <command> --help` shows options for that command.
    """
    if version:
        console.print(dircap.__version__)
        raise typer.Exit(code=0)


def _run_action(cmd: str, mapping: dict[str, str]) -> None:
    """
    Run user-provided action commands.

    SECURITY NOTE:
    - This uses shell=True by design (actions are OS-native scripts/commands).
    - Only configure actions you trust.
    """
    rendered = cmd.format(**mapping)
    subprocess.run(rendered, shell=True, check=False)


def _sort_results(results: list[ScanResult]) -> list[ScanResult]:
    """
    Sort so we most urgent items first.
    Priority: OVER -> WARN -> OK, then higher pct_used, then name.
    """
    order = {"OVER": 0, "WARN": 1, "OK": 2}
    return sorted(
        results,
        key=lambda r: (order.get(r.status, 9), -int(r.pct_used), r.name.lower()),
    )


def _table(results: list[ScanResult]) -> Table:
    t = Table(title="dircap")
    t.add_column("Name", style="bold")
    t.add_column("Path")
    t.add_column("Used", justify="right")
    t.add_column("Limit", justify="right")
    t.add_column("%", justify="right")
    t.add_column("Status", justify="center")

    for r in results:
        t.add_row(
            r.name,
            r.path,
            format_bytes(r.used_bytes),
            format_bytes(r.limit_bytes),
            f"{r.pct_used}%",
            r.status,
        )
    return t


def _load_config_or_exit(config_file: Path | None) -> object:
    """
    Load config, but fail gracefully (no traceback) if it doesn't exist.

    Why:
    - Users often run `dircap validate` or `dircap check` before `dircap init`.
    - We want a friendly message and a non-zero exit code, not a crash.
    """
    try:
        return load_config(config_file)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        console.print("Run: [bold]dircap init[/bold]  (or pass [bold]--config PATH[/bold])")
        raise typer.Exit(code=2) from None


def _scan_all(config_file: Path | None = None) -> tuple[object, list[ScanResult], list[str]]:
    """
    Scan all budgets and return (cfg, results, warnings).

    Robust by design:
    - Missing paths -> 0 used bytes (scan.py)
    - Invalid limits -> budget becomes OVER and a warning is emitted (no crash)
    """
    cfg = _load_config_or_exit(config_file)
    exclude = set(cfg.settings.exclude_dirnames or [])

    warnings: list[str] = []
    results: list[ScanResult] = []

    for b in cfg.budgets:
        warn_pct = b.warn_pct if b.warn_pct is not None else cfg.settings.default_warn_pct
        root = Path(b.path)

        outcome = folder_size_bytes(
            root,
            exclude_dirnames=exclude,
            follow_symlinks=cfg.settings.follow_symlinks,
            max_depth=cfg.settings.max_depth,
        )
        used = outcome.used_bytes
        if outcome.note:
            warnings.append(f"Budget '{b.name}': {outcome.note}")

        try:
            results.append(
                evaluate(
                    name=b.name,
                    path=str(root),
                    limit=b.limit,
                    warn_pct=int(warn_pct),
                    used_bytes=used,
                )
            )
        except Exception as e:
            warnings.append(f"Budget '{b.name}': invalid limit '{b.limit}' ({e}). Marked as OVER.")
            results.append(
                ScanResult(
                    name=b.name,
                    path=str(root),
                    used_bytes=used,
                    limit_bytes=0,
                    warn_pct=int(warn_pct),
                    pct_used=100,
                    status="OVER",
                )
            )

    results = _sort_results(results)
    return cfg, results, warnings


@app.command()
def init():
    """Create a default config file in user config directory (safe to run multiple times)."""
    p = ensure_config_exists()
    console.print(f"[green]Created/verified config:[/green] {p}")


@app.command()
def where():
    """Print the config file path."""
    console.print(str(config_path()))


@app.command()
def validate(
    config: Path | None = typer.Option(
        None,
        "--config",
        help="Use a specific config file path instead of the default user config.",
    ),
):
    """
    Validate the config file without scanning folders.

    Checks:
    - budgets exist
    - paths are valid strings and expand properly
    - limits are parseable (e.g., 5GB)
    - warn_pct is in 1..100 when provided
    """
    cfg = _load_config_or_exit(config)

    errors: list[str] = []
    if not cfg.budgets:
        errors.append("No budgets configured. Add at least one [[budgets]] block.")

    seen_names: set[str] = set()
    for i, b in enumerate(cfg.budgets, start=1):
        if not b.name.strip():
            errors.append(f"Budget #{i}: name is empty.")
        elif b.name in seen_names:
            errors.append(f"Budget #{i}: duplicate name '{b.name}'. Names should be unique.")
        else:
            seen_names.add(b.name)

        if not b.path.strip():
            errors.append(f"Budget #{i} ({b.name}): path is empty.")
        else:
            p = Path(b.path)
            if not p.exists():
                console.print(f"[yellow]Warning:[/yellow] path does not exist: {b.path}")

        try:
            parse_bytes(b.limit)
        except Exception as e:
            errors.append(f"Budget #{i} ({b.name}): invalid limit '{b.limit}' ({e}).")

        if b.warn_pct is not None and not (1 <= b.warn_pct <= 100):
            errors.append(f"Budget #{i} ({b.name}): warn_pct must be 1..100 (got {b.warn_pct}).")

    if errors:
        console.print("[red]Config validation failed:[/red]")
        for msg in errors:
            console.print(f" - {msg}")
        raise typer.Exit(code=2)

    console.print("[green]Config looks good.[/green]")


@app.command()
def report(
    config: Path | None = typer.Option(
        None,
        "--config",
        help="Use a specific config file path instead of the default user config.",
    ),
):
    """Show a readable table of usage vs caps (read-only)."""
    _, results, warnings = _scan_all(config)

    for w in warnings:
        console.print(f"[yellow]Warning:[/yellow] {w}")
    if warnings:
        console.print()

    console.print(_table(results))

    over = sum(1 for r in results if r.status == "OVER")
    warn = sum(1 for r in results if r.status == "WARN")
    ok = len(results) - over - warn
    console.print(f"\nOK: {ok}  WARN: {warn}  OVER: {over}")


@app.command()
def check(
    config: Path | None = typer.Option(
        None,
        "--config",
        help="Use a specific config file path instead of the default user config.",
    ),
    json_out: Path | None = typer.Option(None, "--json", help="Write results to a JSON file."),
    json_verbose: bool = typer.Option(
        False,
        "--json-verbose",
        help="Write structured JSON with summary + warnings + results (instead of a flat list).",
    ),
    summary: bool = typer.Option(False, "--summary", help="Print only a short summary line."),
    no_actions: bool = typer.Option(
        False, "--no-actions", help="Do not run on_warn/on_over actions."
    ),
):
    """
    Like report, plus exit codes for automation:
      0 = all OK
      1 = at least one WARN
      2 = at least one OVER
    """
    cfg, results, warnings = _scan_all(config)

    over = sum(1 for r in results if r.status == "OVER")
    warn = sum(1 for r in results if r.status == "WARN")
    ok = len(results) - over - warn

    if not summary:
        for w in warnings:
            console.print(f"[yellow]Warning:[/yellow] {w}")
        if warnings:
            console.print()

    if summary:
        console.print(f"OK: {ok}  WARN: {warn}  OVER: {over}")
    else:
        console.print(_table(results))
        console.print()
        console.print(f"OK: {ok}  WARN: {warn}  OVER: {over}")
        console.print()

    if json_out:
        json_out.parent.mkdir(parents=True, exist_ok=True)

        results_payload = [
            {
                "name": r.name,
                "path": r.path,
                "used_bytes": r.used_bytes,
                "limit_bytes": r.limit_bytes,
                "pct_used": r.pct_used,
                "warn_pct": r.warn_pct,
                "status": r.status,
            }
            for r in results
        ]

        if json_verbose:
            payload: object = {
                "summary": {"ok": ok, "warn": warn, "over": over},
                "warnings": warnings,
                "results": results_payload,
            }
        else:
            # Backward-compatible: keep old JSON shape (flat list).
            payload = results_payload

        json_out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        if not summary:
            console.print(f"[blue]Wrote JSON:[/blue] {json_out}")
            console.print()

    if not no_actions:
        for r in results:
            mapping = {
                "name": r.name,
                "path": r.path,
                "used": format_bytes(r.used_bytes),
                "limit": format_bytes(r.limit_bytes),
                "pct": str(r.pct_used),
                "status": r.status,
            }
            if r.status == "WARN" and cfg.action.on_warn:
                _run_action(cfg.action.on_warn, mapping)
            if r.status == "OVER" and cfg.action.on_over:
                _run_action(cfg.action.on_over, mapping)

    if over:
        raise typer.Exit(code=2)
    if warn:
        raise typer.Exit(code=1)
    raise typer.Exit(code=0)


if __name__ == "__main__":
    app()
