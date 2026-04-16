@echo off
REM Check Worker Status - Hugo Translator
REM Quick wrapper for check_worker_status.ps1
REM Created: 2026-01-21

powershell -ExecutionPolicy Bypass -File scripts\check_worker_status.ps1
pause
