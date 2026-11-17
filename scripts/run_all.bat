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
set "FAILED="

REM Each network-bound step is retried on failure. A dropped DNS lookup
REM mid-run used to abort the whole pipeline and lose that day's sends.
echo [1/5] finding leads...        & call :step "find"        "python scripts\bulk_find.py --num 8 --count 20"
echo [2/5] AI personalizing...     & call :step "personalize" "python scripts\personalize.py --delay 0.8"
echo [3/5] enriching...            & call :step "enrich"      "python -m fixgenie.cli enrich"
echo [4/5] validating + pushing... & call :step "validate"    "python -m fixgenie.cli validate"
                                     call :step "push"        "python -m fixgenie.cli push"
echo [5/5] sending outreach...     & call :step "outreach"    "python -m fixgenie.cli outreach"

if defined FAILED (
    echo ==== run_all finished WITH ERRORS %DATE% %TIME% - failed:%FAILED% ==== >> "%LOG%"
) else (
    echo ==== run_all finished OK %DATE% %TIME% ==== >> "%LOG%"
)

REM --- keep the master log as the running history ---
type "%LOG%" >> "data\run_all.log"

echo.
if defined FAILED (
    echo ************************************************************
    echo   RUN FINISHED WITH ERRORS. Failed steps:%FAILED%
    echo %FAILED% | findstr /c:"outreach" > nul && echo   NO EMAILS WERE SENT this run.
    echo   Details are in the log below. Re-run when the network is stable.
    echo ************************************************************
) else (
    echo All steps succeeded.
)
echo This run's log: %LOG%
echo (also appended to data\run_all.log)
pause
exit /b 0

REM --------------------------------------------------------------------------
REM Run one pipeline step, retrying up to 3 times so a transient network drop
REM does not end the run. Before each attempt it waits (up to 15 min) for DNS
REM to work again: outages here can last minutes, far longer than retry gaps.
REM The whole command goes in ONE quoted argument.
REM Usage:  call :step "label" "command to run"
REM --------------------------------------------------------------------------
:step
setlocal
set "LABEL=%~1"
set "CMD=%~2"
set /a N=0
:step_loop
set /a N+=1
python -m fixgenie.common.network --max-wait 900 >> "%LOG%" 2>&1
echo   -- %LABEL% attempt %N%: %CMD% >> "%LOG%"
cmd /c %CMD% >> "%LOG%" 2>&1
if errorlevel 1 goto step_failed
if %N% gtr 1 echo   -- %LABEL% succeeded on attempt %N% >> "%LOG%"
endlocal & exit /b 0
:step_failed
if %N% geq 3 goto step_gave_up
echo   -- %LABEL% failed (attempt %N%), retrying in 20s >> "%LOG%"
REM powershell, not timeout.exe: Git Bash's GNU `timeout` shadows it on some
REM PATHs and rejects the /t flag.
powershell -NoProfile -Command "Start-Sleep -Seconds 20" > nul
goto step_loop
:step_gave_up
echo   !! %LABEL% FAILED after %N% attempts - continuing to next step >> "%LOG%"
echo      !! %LABEL% FAILED after %N% attempts - see log
endlocal & set "FAILED=%FAILED% %LABEL%" & exit /b 1
