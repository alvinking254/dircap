#!/usr/bin/env sh
set -eu

# Run dircap on macOS/Linux and write logs to ~/dircap/

REPO="$HOME/path/to/dircap" # replace with your atual repor path
LOGDIR="$HOME/dircap"
LOGTXT="$LOGDIR/dircap-last.txt"
LOGJSON="$LOGDIR/dircap-last.json"

mkdir -p "$LOGDIR"

# If you're running from a src-layout repo, set PYTHONPATH so python can import it.
export PYTHONPATH="$REPO/src"

# Run dircap and capture logs + JSON (verbose for summary emails).
"$REPO/.venv/bin/python" -m dircap.cli check --json "$LOGJSON" --json-verbose > "$LOGTXT" 2>&1
RC=$?

# Send ONE email if WARN/OVER.
if [ "$RC" -ne 0 ]; then
  "$REPO/.venv/bin/python" "$REPO/examples/send-email.py" "$LOGTXT" "$LOGJSON" >> "$LOGTXT" 2>&1 || true
fi

exit "$RC"