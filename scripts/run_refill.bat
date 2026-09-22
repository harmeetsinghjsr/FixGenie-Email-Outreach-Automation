@echo off
REM ==========================================================================
REM FixGenie LOCAL lead refill: find new leads -> AI personalize -> push to
REM the Google Sheet. Run this on YOUR PC (Exa + the LLM gateway work here but
REM not on GitHub's servers). The cloud job then emails them ~30/day.
REM Run it whenever you want fresh leads (e.g. once a week), or point Windows
REM Task Scheduler at it.
REM ==========================================================================
cd /d "C:\Users\hs978\CodeSpace\FixGenie\FixGenie Email Outreach Automation"
echo ---- refill started %DATE% %TIME% ---- >> "data\refill.log"
python scripts\bulk_find.py --num 8            >> "data\refill.log" 2>&1
python scripts\personalize.py --delay 0.3      >> "data\refill.log" 2>&1
python -m fixgenie.cli enrich                  >> "data\refill.log" 2>&1
python -m fixgenie.cli validate                >> "data\refill.log" 2>&1
python -m fixgenie.cli push                    >> "data\refill.log" 2>&1
echo ---- refill finished %DATE% %TIME% ---- >> "data\refill.log"
