@echo off
cd /d "%~dp0"
echo Starting Content Translation Worker in daemon mode...
echo Process will run in background and self-schedule 4 runs per day.
echo.
.venv\Scripts\python.exe -m src.workers.autonomous_content_translation_worker --mode daemon --runs-per-day 4 --window-start 08:00 --window-end 23:00 --device cuda --max-gpu-memory-percent 50 --log-level INFO
