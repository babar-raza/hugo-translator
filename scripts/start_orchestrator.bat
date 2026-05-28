@echo off
REM Worker Orchestrator - Startup Script
REM Trigger-based launcher for oneshot workers.
REM Replaces blind periodic scheduling with intelligent trigger evaluation.
REM Designed for Windows Task Scheduler execution.

echo ================================================================================
echo Starting Worker Orchestrator
echo ================================================================================
echo Timestamp: %date% %time%
echo Working Directory: %~dp0..
echo.

REM Change to project root directory
cd /d "%~dp0.."

REM Activate virtual environment
call .venv\Scripts\activate.bat

REM Set content repository paths (required by content_worker and git_context)
set ASPOSE_NET_CONTENT=C:\Users\prora\OneDrive\Documents\GitHub\aspose.net\content
set ASPOSE_ORG_CONTENT=C:\Users\prora\OneDrive\Documents\GitHub\aspose.org\content

REM Start orchestrator in daemon mode (default 15-minute check interval)
echo Starting orchestrator...
echo - Check interval: 900 seconds (15 minutes)
echo - Config: config/workers.yaml
echo - Workers are launched as oneshot subprocesses when triggers fire
echo.

python -m src.workers.worker_orchestrator ^
    --config config/workers.yaml ^
    --check-interval 900 ^
    --log-level INFO

REM Capture exit code
set EXITCODE=%ERRORLEVEL%

echo.
echo ================================================================================
echo Orchestrator exited with code: %EXITCODE%
echo Timestamp: %date% %time%
echo ================================================================================

REM Exit with same code
exit /b %EXITCODE%
