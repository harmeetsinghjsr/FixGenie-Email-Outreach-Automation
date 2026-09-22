@echo off
REM ==========================================================================
REM FixGenie - DO EVERYTHING on your PC, one click.
REM   1. find new leads (Exa)
REM   2. AI-personalize each one (your gateway)  <-- every email gets this
REM   3. enrich -> validate -> push to the Google Sheet
REM   4. send today's emails + follow-ups (respects DAILY_SEND_LIMIT)
REM Everything is logged to data\run_all.log
REM Run it whenever you want (once a day / a few times a week is plenty).
REM ==========================================================================
cd /d "C:\Users\hs978\CodeSpace\FixGenie\FixGenie Email Outreach Automation"
echo ==== run_all started %DATE% %TIME% ==== >> "data\run_all.log"

echo [1/5] finding leads...        & python scripts\bulk_find.py --num 8       >> "data\run_all.log" 2>&1
echo [2/5] AI personalizing...     & python scripts\personalize.py --delay 0.3 >> "data\run_all.log" 2>&1
echo [3/5] enriching...            & python -m fixgenie.cli enrich             >> "data\run_all.log" 2>&1
echo [4/5] validating + pushing... & python -m fixgenie.cli validate           >> "data\run_all.log" 2>&1
                                     python -m fixgenie.cli push               >> "data\run_all.log" 2>&1
echo [5/5] sending outreach...     & python -m fixgenie.cli outreach           >> "data\run_all.log" 2>&1

echo ==== run_all finished %DATE% %TIME% ==== >> "data\run_all.log"
echo.
echo Done. Full details are in data\run_all.log
pause
