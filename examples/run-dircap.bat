@echo off
setlocal

REM Run dircap on Windows and write logs to %USERPROFILE%\dircap\
REM SET repo path here.

set "REPO=your-repo-path\dircap"
set "PY=%REPO%\.venv\Scripts\python.exe"
set "LOGDIR=%USERPROFILE%\dircap"
set "LOGTXT=%LOGDIR%\dircap-last.txt"
set "LOGJSON=%LOGDIR%\dircap-last.json"

REM Ensure we are in the repo (Task Scheduler may start elsewhere)
cd /d "%REPO%" || (echo REPO path not found: "%REPO%" & exit /b 99)

REM Ensure log dir exists
if not exist "%LOGDIR%" mkdir "%LOGDIR%" 2>nul

REM If mkdir failed (rare), bail with a clear message
if not exist "%LOGDIR%" (
  echo Could not create log directory: "%LOGDIR%"
  exit /b 98
)

REM Make the src layout importable when running via python -m
set "PYTHONPATH=%REPO%\src"

REM Verify python exists (better error than "path not found")
if not exist "%PY%" (
  echo Python not found: "%PY%"
  exit /b 97
)

REM Run and capture stdout+stderr to a text log, plus a JSON snapshot (verbose for summary emails).
"%PY%" -m dircap.cli check --json "%LOGJSON%" --json-verbose > "%LOGTXT%" 2>&1
set "RC=%ERRORLEVEL%"

REM If WARN(1) or OVER(2), send ONE email that points to the logs.
if %RC% NEQ 0 (
  "%PY%" "%REPO%\examples\send-email.py" "%LOGTXT%" "%LOGJSON%" >> "%LOGTXT%" 2>&1
)

endlocal & exit /b %RC%