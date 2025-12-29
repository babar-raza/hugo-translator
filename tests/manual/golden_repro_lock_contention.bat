@echo off
REM Golden Repro Harness - Lock Contention Fix Validation (Windows)
REM Tests that multi-language translation completes without cascading timeouts

setlocal enabledelayedexpansion

REM Configuration
set SITE=test.golden.repro.net
set LANGS=ar,bg,cs
set TIMEOUT_SECONDS=90
set TIMESTAMP=%date:~-4,4%%date:~-10,2%%date:~-7,2%_%time:~0,2%%time:~3,2%%time:~6,2%
set TIMESTAMP=%TIMESTAMP: =0%
set REPORT_DIR=reports\golden_repro
set REPORT_FILE=%REPORT_DIR%\execution_%TIMESTAMP%.log

REM Create report directory
if not exist "%REPORT_DIR%" mkdir "%REPORT_DIR%"

REM Start logging
call :main 2>&1 | tee "%REPORT_FILE%"
goto :eof

:main
echo ==========================================
echo GOLDEN REPRO HARNESS - LOCK CONTENTION FIX
echo ==========================================
echo.
echo Timestamp: %TIMESTAMP%
echo Site: %SITE%
echo Languages: %LANGS%
echo Timeout: %TIMEOUT_SECONDS%s
echo.

REM Check 1: Environment
echo ==========================================
echo CHECK 1: Environment Setup
echo ==========================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [FAIL] Python not found
    exit /b 1
)
echo [PASS] Python found

if not exist "src\cli.py" (
    echo [FAIL] Not in project root
    exit /b 1
)
echo [PASS] Project root confirmed

REM Create test corpus
set TEST_SOURCE=tests\fixtures\repro\source
if not exist "%TEST_SOURCE%" mkdir "%TEST_SOURCE%"

(
echo # Test Document 1
echo.
echo This is a test document.
echo.
echo ## Section 1
echo.
echo Hello world.
) > "%TEST_SOURCE%\test1.md"

(
echo # Test Document 2
echo.
echo Another test document.
echo.
echo - Item 1
echo - Item 2
echo.
echo Testing lock contention fix.
) > "%TEST_SOURCE%\test2.md"

echo [PASS] Test corpus created
echo.

REM Check 2: Clean state
echo ==========================================
echo CHECK 2: Clean State
echo ==========================================
echo.

set TEST_OUTPUT=tests\fixtures\repro\output
if exist "%TEST_OUTPUT%" (
    rd /s /q "%TEST_OUTPUT%"
    echo [PASS] Removed old output
) else (
    echo [PASS] No old output
)

set LOCK_FILE=.translation_progress\locks\%SITE%.lock
if exist "%LOCK_FILE%" (
    del /f "%LOCK_FILE%"
)
echo [PASS] No lock file present
echo.

REM Check 3: Run translation
echo ==========================================
echo CHECK 3: Multi-Language Translation
echo ==========================================
echo.

echo Starting translation...
echo Expected: Complete in ^<60s
echo.

set START_TIME=%time%

python -m src.cli --site "%SITE%" --source "%TEST_SOURCE%" --output "%TEST_OUTPUT%" --target-langs "%LANGS%" --skip-tm > "%REPORT_DIR%\translation_output_%TIMESTAMP%.txt" 2>&1

if errorlevel 1 (
    echo [FAIL] Translation failed
    type "%REPORT_DIR%\translation_output_%TIMESTAMP%.txt"
    exit /b 1
)

echo [PASS] Translation completed
echo.

REM Check 4: Verify logs
echo ==========================================
echo CHECK 4: Log Verification
echo ==========================================
echo.

findstr /C:"Site lock acquired by parent process" "%REPORT_DIR%\translation_output_%TIMESTAMP%.txt" >nul
if errorlevel 1 (
    echo [FAIL] Parent lock message not found
    exit /b 1
)
echo [PASS] Parent lock confirmed

findstr /C:"Skipping site lock acquisition" "%REPORT_DIR%\translation_output_%TIMESTAMP%.txt" >nul
if errorlevel 1 (
    echo [FAIL] Child skip messages not found
    exit /b 1
)
echo [PASS] Child skip messages found

findstr /C:"Still waiting for lock" "%REPORT_DIR%\translation_output_%TIMESTAMP%.txt" >nul
if not errorlevel 1 (
    echo [FAIL] Cascading timeout detected
    exit /b 1
)
echo [PASS] No cascading timeouts

echo.

REM Check 5: Output completeness
echo ==========================================
echo CHECK 5: Output Completeness
echo ==========================================
echo.

for %%L in (ar,bg,cs) do (
    if not exist "%TEST_OUTPUT%\%SITE%\%%L\test1.md" (
        echo [FAIL] Missing output for %%L
        exit /b 1
    )
    echo [PASS] %%L: output complete
)
echo.

REM Check 6: Lock cleanup
echo ==========================================
echo CHECK 6: Lock Cleanup
echo ==========================================
echo.

if exist "%LOCK_FILE%" (
    echo [FAIL] Lock file still exists
    exit /b 1
)
echo [PASS] Lock file cleaned up
echo.

echo ==========================================
echo FINAL SUMMARY
echo ==========================================
echo.
echo [SUCCESS] ALL CHECKS PASSED
echo.
echo Report saved to: %REPORT_FILE%
echo.
echo ==========================================
echo GOLDEN REPRO HARNESS: SUCCESS
echo ==========================================

exit /b 0
