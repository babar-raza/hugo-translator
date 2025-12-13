@echo off
REM Run GPU/CUDA translation test with hugo-translator environment

echo ================================================================================
echo  GPU TRANSLATION TEST - M2M100 with CUDA
echo ================================================================================
echo.
echo Environment: hugo-translator
echo Model: m2m100_418m (Facebook M2M100 418M parameters)
echo Device: CUDA
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
echo Checking CUDA availability...
python -c "import torch; print('CUDA available:', torch.cuda.is_available()); print('CUDA device:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'N/A')"

echo.
echo ================================================================================
echo Running GPU translation test...
echo ================================================================================
echo.

python tests\live_translation_gpu.py

echo.
echo ================================================================================
echo Test complete!
echo ================================================================================
pause
