@echo off
REM ==========================================================================
REM FixGenie daily outreach + follow-up runner (for Windows Task Scheduler).
REM Sends due first emails AND follow-ups (step 2 after 3 days, step 3 after 7),
REM logs every send to the "Outreach Log" tab, and appends a local run log.
REM ==========================================================================
cd /d "C:\Users\hs978\CodeSpace\FixGenie\FixGenie Email Outreach Automation"
echo ---- run started %DATE% %TIME% ---- >> "data\outreach_cron.log"
python -m fixgenie.cli outreach >> "data\outreach_cron.log" 2>&1
echo ---- run finished %DATE% %TIME% ---- >> "data\outreach_cron.log"
