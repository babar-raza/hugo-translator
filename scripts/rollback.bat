@echo off
REM Hugo Translation System - Rollback Script (Windows)
REM
REM Usage:
REM   scripts\rollback.bat [legacy|backup] [backup_path]
REM
REM Examples:
REM   scripts\rollback.bat legacy
REM   scripts\rollback.bat backup backups\20251121_120000

setlocal enabledelayedexpansion

REM Get timestamp
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value') do set datetime=%%I
set TIMESTAMP=%datetime:~0,8%_%datetime:~8,6%

REM Parse arguments
set ACTION=%1
set BACKUP_PATH=%2

if "%ACTION%"=="" (
    echo ERROR: Must specify action: legacy or backup
    echo Usage: scripts\rollback.bat [legacy^|backup] [backup_path]
    exit /b 1
)

echo ============================================================
echo   Hugo Translation System - Rollback
echo ============================================================
echo.

REM Show warning
echo WARNING: This will rollback the system
if "%ACTION%"=="legacy" (
    echo   Target: Legacy system
) else (
    echo   Target: Backup at %BACKUP_PATH%
)
echo.

set /p CONFIRM="Are you sure you want to proceed? (yes/no): "
if not "%CONFIRM%"=="yes" (
    echo Rollback cancelled
    exit /b 0
)
echo.

echo [INFO] Creating pre-rollback backup...
set BACKUP_DIR=backups\pre_rollback_%TIMESTAMP%
mkdir "%BACKUP_DIR%" 2>nul

REM Backup current state
if exist "data\tm" (
    echo   Backing up Translation Memory...
    xcopy /E /I /Y data\tm "%BACKUP_DIR%\tm" >nul
)

if exist "config" (
    echo   Backing up configuration...
    xcopy /E /I /Y config "%BACKUP_DIR%\config" >nul
)

if exist ".env.production" (
    echo   Backing up environment...
    copy /Y .env.production "%BACKUP_DIR%\" >nul
)

echo Pre-rollback backup created: %BACKUP_DIR%
echo.

echo [INFO] Stopping new system...

REM Stop Docker services if running
where docker-compose >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo   Stopping Docker services...
    docker-compose down >nul 2>&1
)

REM Stop Python processes (requires manual intervention on Windows)
echo   Note: Please manually stop any running Python processes
echo.

if "%ACTION%"=="legacy" (
    REM Rollback to legacy system
    echo [INFO] Rolling back to legacy system...

    REM Archive new system
    set ARCHIVE_DIR=archive\new_system_%TIMESTAMP%
    mkdir "%ARCHIVE_DIR%" 2>nul

    echo   Archiving new system to: %ARCHIVE_DIR%

    if exist "src" (
        xcopy /E /I /Y src "%ARCHIVE_DIR%\src" >nul
    )

    if exist "data\tm" (
        xcopy /E /I /Y data\tm "%ARCHIVE_DIR%\tm" >nul
    )

    REM Restore legacy cache if exists
    if exist "backups\legacy_cache\translation" (
        echo   Restoring legacy cache...
        xcopy /E /I /Y backups\legacy_cache\translation translation >nul
    )

    echo.
    echo Rollback to legacy complete
    echo.
    echo Legacy scripts available in: .\legacy\
    echo New system archived in: %ARCHIVE_DIR%
    echo.
    echo To use legacy system:
    echo   python legacy\ast-creator.py --input .\content
    echo   python legacy\ast-translator.py --target_languages de,es,fr
) else (
    REM Restore from backup
    if "%BACKUP_PATH%"=="" (
        echo ERROR: Backup path required for backup restore
        exit /b 1
    )

    if not exist "%BACKUP_PATH%" (
        echo ERROR: Backup directory not found: %BACKUP_PATH%
        exit /b 1
    )

    echo [INFO] Restoring from backup: %BACKUP_PATH%

    REM Restore TM data
    if exist "%BACKUP_PATH%\tm" (
        echo   Restoring Translation Memory...
        rmdir /S /Q data\tm 2>nul
        xcopy /E /I /Y "%BACKUP_PATH%\tm" data\tm >nul
    )

    REM Restore configuration
    if exist "%BACKUP_PATH%\config" (
        echo   Restoring configuration...
        xcopy /E /I /Y "%BACKUP_PATH%\config" config >nul
    )

    REM Restore environment
    if exist "%BACKUP_PATH%\.env.production" (
        echo   Restoring environment...
        copy /Y "%BACKUP_PATH%\.env.production" . >nul
    )

    echo.
    echo Restore from backup complete
    echo.

    REM Restart Docker services
    where docker-compose >nul 2>&1
    if %ERRORLEVEL% EQU 0 (
        if exist "docker-compose.yml" (
            echo [INFO] Starting Docker services...
            docker-compose up -d

            timeout /t 5 >nul

            echo   Checking service health...
            docker-compose ps
        )
    )
)

echo.
echo ============================================================
echo   Rollback Complete
echo ============================================================
echo.
echo Pre-rollback backup: %BACKUP_DIR%
echo.

endlocal
