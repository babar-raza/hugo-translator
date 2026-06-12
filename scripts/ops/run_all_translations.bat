@echo off
setlocal enabledelayedexpansion

echo ================================================================
echo  Hugo Translator - Bulk Translation Run
echo  Started: %date% %time%
echo ================================================================

cd /d "%~dp0"

REM Activate virtual environment
call .venv\Scripts\activate.bat
if errorlevel 1 (
    echo ERROR: Failed to activate virtual environment
    exit /b 1
)

REM --- aspose.net sites (ordered smallest to largest) ---
set SITES=www.aspose.net about.aspose.net blog.aspose.net kb.aspose.net docs.aspose.net products.aspose.net websites.aspose.net

for %%S in (%SITES%) do (
    echo(
    echo ================================================================
    echo  Site: %%S
    echo  Started: %date% %time%
    echo ================================================================

    REM Clear stale lock if present
    if exist ".translation_progress\locks\%%S.lock" (
        del /f ".translation_progress\locks\%%S.lock" 2>nul
        echo  Cleared stale lock for %%S
    )

    echo  Logging to: data\logs\%%S.log
    translate-hugo --site %%S --parallel-languages 3 >> "data\logs\%%S.log" 2>&1
    set EC=!errorlevel!

    echo  Exit code: !EC!
    echo  Finished: %date% %time%

    if !EC! neq 0 (
        echo  WARNING: %%S exited with code !EC! - check data\logs\%%S.log
    )
)

echo(
echo ================================================================
echo  All sites processed
echo  Finished: %date% %time%
echo ================================================================

endlocal
