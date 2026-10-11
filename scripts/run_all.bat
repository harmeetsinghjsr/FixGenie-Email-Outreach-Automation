@echo off
setlocal
REM ==========================================================================
REM FixGenie - DO EVERYTHING on your PC, one click.
REM   1. find new leads (Exa)
REM   2. AI-personalize each one (your gateway)  <-- every email gets this
REM   3. enrich -> validate -> push to the Google Sheet
REM   4. send today's emails + follow-ups (respects DAILY_SEND_LIMIT)
REM
REM Every run writes its OWN log:  data\daily_run_YYYYMMDD_HHMMSS.log
REM (the same content is also appended to data\run_all.log, the master log)
REM
REM Watch the current run live in another terminal:
REM   Get-Content "data\daily_run_*.log" -Wait -Tail 30
REM ==========================================================================
cd /d "%~dp0.."

REM --- per-run timestamped log name (locale-independent) ---
for /f "delims=" %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "STAMP=%%i"
set "LOG=data\daily_run_%STAMP%.log"

echo ==== run_all started %DATE% %TIME% ==== > "%LOG%"

echo [1/5] finding leads...        & python scripts\bulk_find.py --num 8 --count 20 >> "%LOG%" 2>&1
echo [2/5] AI personalizing...     & python scripts\personalize.py --delay 0.3 >> "%LOG%" 2>&1
echo [3/5] enriching...            & python -m fixgenie.cli enrich             >> "%LOG%" 2>&1
echo [4/5] validating + pushing... & python -m fixgenie.cli validate           >> "%LOG%" 2>&1
                                     python -m fixgenie.cli push               >> "%LOG%" 2>&1
echo [5/5] sending outreach...     & python -m fixgenie.cli outreach           >> "%LOG%" 2>&1

echo ==== run_all finished %DATE% %TIME% ==== >> "%LOG%"

REM --- keep the master log as the running history ---
type "%LOG%" >> "data\run_all.log"

echo.
echo Done. This run's log: %LOG%
echo (also appended to data\run_all.log)
pause
