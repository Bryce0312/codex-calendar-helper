@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
    py -3 -B "%~dp0launch_schedule.pyw" %*
    goto done
)
for /f "delims=" %%I in ('where conda 2^>nul') do (
    if exist "%%~dpI..\python.exe" (
        "%%~dpI..\python.exe" -B "%~dp0launch_schedule.pyw" %*
        goto done
    )
)
python -B "%~dp0launch_schedule.pyw" %*
:done
if errorlevel 1 pause
