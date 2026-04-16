@echo off
cd /d "%~dp0"
echo Starting TM Improvement Worker in daemon mode...
echo Process will run in background and self-schedule 4 runs per day.
echo.
.venv\Scripts\python.exe -m src.workers.tm_improvement_worker --mode daemon --runs-per-day 4 --window-start 08:00 --window-end 23:00 --device cuda --max-gpu-memory-percent 50 --llm-provider ollama --llm-model llama2 --log-level INFO
