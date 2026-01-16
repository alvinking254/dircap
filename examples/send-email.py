#!/usr/bin/env python3
"""
examples/send-email.py

Send a single "summary" email for a dircap run.

How it's intended to be used:
- Scheduler script runs `dircap check ...` and writes:
  - a text log (dircap-last.txt)
  - a JSON file (dircap-last.json)
- If the exit code is WARN(1) or OVER(2), the scheduler calls this script ONCE:
    python send-email.py <log_txt_path> <log_json_path>

SMTP + encryption:
- Port 465 typically uses implicit SSL/TLS (SMTP_SSL).
- Port 587 typically uses STARTTLS (SMTP + starttls()).

We do NOT force any mode. You can control via env vars:
  DIRCAP_EMAIL_TO            required
  DIRCAP_EMAIL_FROM          optional (defaults to DIRCAP_SMTP_USER)
  DIRCAP_SMTP_SERVER         required
  DIRCAP_SMTP_PORT           optional (default 465)
  DIRCAP_SMTP_USER           required
  DIRCAP_SMTP_PASS           required

  EMAIL_USE_SSL              optional true/false (default: true if port==465 else false)
  EMAIL_USE_TLS              optional true/false (default: true if port==587 else false)
"""

from __future__ import annotations

import json
import os
import smtplib
import sys
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any


def _env(name: str, default: str | None = None) -> str | None:
    v = os.getenv(name)
    if v is None:
        return default
    v = v.strip()
    return v if v else default


def _env_bool(name: str, default: bool) -> bool:
    v = _env(name)
    if v is None:
        return default
    return v.lower() in {"1", "true", "yes", "y", "on"}


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _summarize(payload: Any) -> tuple[dict[str, int], list[str], list[dict[str, Any]]]:
    """
    Supports two JSON shapes:
    1) verbose dict:
       {"summary": {"ok":..,"warn":..,"over":..}, "warnings":[...], "results":[...]}
    2) flat list:
       [ {"name":..,"status":..}, ... ]
    """
    summary = {"ok": 0, "warn": 0, "over": 0}
    warnings: list[str] = []
    results: list[dict[str, Any]] = []

    if isinstance(payload, dict):
        s = payload.get("summary")
        if isinstance(s, dict):
            summary["ok"] = int(s.get("ok", 0) or 0)
            summary["warn"] = int(s.get("warn", 0) or 0)
            summary["over"] = int(s.get("over", 0) or 0)

        w = payload.get("warnings")
        if isinstance(w, list):
            warnings = [str(x) for x in w if str(x).strip()]

        r = payload.get("results")
        if isinstance(r, list):
            results = [x for x in r if isinstance(x, dict)]

    elif isinstance(payload, list):
        results = [x for x in payload if isinstance(x, dict)]

    # If summary wasn't present (flat list), compute it.
    if (summary["ok"], summary["warn"], summary["over"]) == (0, 0, 0) and results:
        ok = sum(1 for r in results if str(r.get("status")) == "OK")
        warn = sum(1 for r in results if str(r.get("status")) == "WARN")
        over = sum(1 for r in results if str(r.get("status")) == "OVER")
        summary = {"ok": ok, "warn": warn, "over": over}

    return summary, warnings, results


def _fmt_row(r: dict[str, Any]) -> str:
    name = str(r.get("name", ""))
    path = str(r.get("path", ""))
    pct = str(r.get("pct_used", ""))
    status = str(r.get("status", ""))

    # JSON writes bytes. We'll keep it readable by showing pct + status
    # and include used_bytes/limit_bytes when present.
    used_b = r.get("used_bytes", None)
    limit_b = r.get("limit_bytes", None)

    used_part = f"{used_b}B" if isinstance(used_b, int) else ""
    limit_part = f"{limit_b}B" if isinstance(limit_b, int) else ""

    # Keep it compact and consistent.
    extra = ""
    if used_part and limit_part:
        extra = f" ({used_part}/{limit_part})"

    return f"- {status:4} {pct:>4}%  {name}  |  {path}{extra}"


def _build_message(
    *,
    summary: dict[str, int],
    warnings: list[str],
    results: list[dict[str, Any]],
    log_txt: Path,
    log_json: Path,
) -> tuple[str, str]:
    # Only list WARN/OVER rows. OK rows are noise for alert emails.
    affected = [r for r in results if str(r.get("status")) in {"WARN", "OVER"}]

    subject = f"dircap alert: OVER={summary['over']} WARN={summary['warn']}"

    lines: list[str] = []
    lines.append("dircap detected a cap breach.")
    lines.append("")
    lines.append(f"Summary: OK={summary['ok']}  WARN={summary['warn']}  OVER={summary['over']}")
    lines.append(f"Time:    {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")

    if affected:
        lines.append("Affected folders (WARN/OVER):")
        for r in affected:
            # pct_used is an int; status is OK/WARN/OVER
            lines.append(_fmt_row(r))
        lines.append("")
    else:
        # In case JSON parsing failed but exit code indicated alert, still provide logs.
        lines.append("Affected folders: (could not parse details from JSON)")
        lines.append("")

    if warnings:
        lines.append("Warnings:")
        for w in warnings:
            lines.append(f"- {w}")
        lines.append("")

    lines.append("Logs:")
    lines.append(f"- Text: {str(log_txt)}")
    lines.append(f"- JSON: {str(log_json)}")
    lines.append("")
    lines.append("Tip: Open the text log for the full Rich table output.")

    return subject, "\n".join(lines)


def _send_email(*, subject: str, body: str) -> int:
    to = _env("DIRCAP_EMAIL_TO")
    smtp_server = _env("DIRCAP_SMTP_SERVER")
    smtp_user = _env("DIRCAP_SMTP_USER")
    smtp_pass = _env("DIRCAP_SMTP_PASS")

    if not to or not smtp_server or not smtp_user or not smtp_pass:
        print(
            "Missing env vars. Required: DIRCAP_EMAIL_TO, DIRCAP_SMTP_SERVER, DIRCAP_SMTP_USER, DIRCAP_SMTP_PASS",
            file=sys.stderr,
        )
        return 1

    from_addr = _env("DIRCAP_EMAIL_FROM", smtp_user)

    port_str = _env("DIRCAP_SMTP_PORT", "465")
    try:
        port = int(port_str)
    except ValueError:
        print(f"Invalid DIRCAP_SMTP_PORT: {port_str}", file=sys.stderr)
        return 1

    # Defaults that match common SMTP practice.
    use_ssl_default = port == 465
    use_tls_default = port == 587

    # User-overrides (we do NOT force anything).
    use_ssl = _env_bool("EMAIL_USE_SSL", use_ssl_default)
    use_tls = _env_bool("EMAIL_USE_TLS", use_tls_default)

    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        if use_ssl:
            with smtplib.SMTP_SSL(smtp_server, port, timeout=30) as s:
                s.login(smtp_user, smtp_pass)
                s.send_message(msg)
        else:
            with smtplib.SMTP(smtp_server, port, timeout=30) as s:
                s.ehlo()
                if use_tls:
                    s.starttls()
                    s.ehlo()
                s.login(smtp_user, smtp_pass)
                s.send_message(msg)

        print(f"Email sent to {to}")
        return 0
    except Exception as e:
        print(f"Email failed: {e}", file=sys.stderr)
        return 2


def main(argv: list[str]) -> int:
    #   send-email.py <log_txt_path> <log_json_path>
    if len(argv) != 3:
        print("Usage: send-email.py <log_txt_path> <log_json_path>", file=sys.stderr)
        return 2

    log_txt = Path(argv[1])
    log_json = Path(argv[2])

    payload = _load_json(log_json) if log_json.exists() else None
    summary, warnings, results = _summarize(payload)

    subject, body = _build_message(
        summary=summary,
        warnings=warnings,
        results=results,
        log_txt=log_txt,
        log_json=log_json,
    )

    return _send_email(subject=subject, body=body)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
