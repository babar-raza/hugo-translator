@echo off
echo Activating llm conda environment...
call C:\Users\prora\anaconda3\Scripts\activate.bat llm

echo.
echo Changing to project directory...
cd /d "c:\Users\prora\OneDrive\Documents\GitHub\hugo-translator"

echo.
echo Verifying CUDA availability...
python -c "import torch; print('CUDA available:', torch.cuda.is_available()); print('CUDA device:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'N/A')"

echo.
echo ================================================================================
echo Starting live translation test with CUDA...
echo ================================================================================
echo.

python tests\live_translation_simple.py

echo.
echo ================================================================================
echo Test complete. Check tests\live.txt for output file locations.
echo ================================================================================
