@echo off
REM Inspect L3 Index Metadata Structure

echo ================================================================================
echo  L3 Metadata Structure Inspector
echo ================================================================================
echo.
echo Environment: hugo-translator
echo Index: data\tm\l3.faiss
echo.
echo ================================================================================
echo.

echo Activating hugo-translator environment...
call C:\Users\prora\anaconda3\Scripts\activate.bat hugo-translator

if errorlevel 1 (
    echo [ERROR] Failed to activate hugo-translator environment
    pause
    exit /b 1
)

echo.
echo ================================================================================
echo Running inspection script...
echo ================================================================================
echo.

python scripts\inspect_l3_metadata.py

echo.
echo ================================================================================
echo Inspection complete!
echo ================================================================================
pause
