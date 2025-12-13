@echo off
REM Scheduled backup script for Windows
REM Run via Task Scheduler

setlocal enabledelayedexpansion

REM Configuration
set SCRIPT_DIR=%~dp0
set PROJECT_DIR=%SCRIPT_DIR%..
set BACKUP_DIR=%PROJECT_DIR%\backups
set TM_DATA_DIR=%PROJECT_DIR%\data\tm
set CONFIG_DIR=%PROJECT_DIR%\config
set KEEP_BACKUPS=7
set LOG_FILE=%PROJECT_DIR%\data\logs\backup.log

REM Create backup directory if needed
if not exist "%BACKUP_DIR%" mkdir "%BACKUP_DIR%"
if not exist "%PROJECT_DIR%\data\logs" mkdir "%PROJECT_DIR%\data\logs"

REM Generate backup filename with timestamp
for /f "tokens=1-5 delims=/: " %%a in ("%date% %time%") do (
    set TIMESTAMP=%%c%%a%%b_%%d%%e
)
set TIMESTAMP=%TIMESTAMP: =0%
set BACKUP_FILE=%BACKUP_DIR%\tm_%TIMESTAMP%.tar.gz

REM Log function
set LOG_PREFIX=[%date% %time%]

echo %LOG_PREFIX% ========== Starting scheduled backup ========== >> "%LOG_FILE%"
echo %LOG_PREFIX% Backup file: %BACKUP_FILE% >> "%LOG_FILE%"
echo %LOG_PREFIX% TM data: %TM_DATA_DIR% >> "%LOG_FILE%"
echo %LOG_PREFIX% Config: %CONFIG_DIR% >> "%LOG_FILE%"
echo %LOG_PREFIX% Keep: %KEEP_BACKUPS% backups >> "%LOG_FILE%"

echo %LOG_PREFIX% Starting scheduled backup...
echo %LOG_PREFIX% Backup file: %BACKUP_FILE%

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo %LOG_PREFIX% ERROR: Python not found >> "%LOG_FILE%"
    exit /b 1
)

REM Run backup
echo %LOG_PREFIX% Running backup... >> "%LOG_FILE%"
python "%SCRIPT_DIR%backup_tm.py" ^
    --output "%BACKUP_FILE%" ^
    --tm-data "%TM_DATA_DIR%" ^
    --config "%CONFIG_DIR%" ^
    --rotate %KEEP_BACKUPS% >> "%LOG_FILE%" 2>&1

if errorlevel 1 (
    echo %LOG_PREFIX% ERROR: Backup failed >> "%LOG_FILE%"
    exit /b 1
) else (
    echo %LOG_PREFIX% Backup completed successfully >> "%LOG_FILE%"
)

REM Verify backup
echo %LOG_PREFIX% Verifying backup... >> "%LOG_FILE%"
python "%SCRIPT_DIR%restore_tm.py" ^
    --backup "%BACKUP_FILE%" ^
    --verify ^
    --dry-run >> "%LOG_FILE%" 2>&1

if errorlevel 1 (
    echo %LOG_PREFIX% WARNING: Backup verification failed >> "%LOG_FILE%"
) else (
    echo %LOG_PREFIX% Backup verification successful >> "%LOG_FILE%"
)

echo %LOG_PREFIX% ========== Backup completed ========== >> "%LOG_FILE%"
echo Backup completed successfully: %BACKUP_FILE%
