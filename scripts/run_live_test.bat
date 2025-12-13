@echo off
REM Activate conda environment and run live translation test

echo Activating conda environment...
call C:\Users\prora\anaconda3\Scripts\activate.bat llm

echo.
echo Installing sentencepiece if missing...
python -m pip install sentencepiece --quiet

echo.
echo Running live translation test...
python tests\live_translation_simple.py

echo.
echo Test complete.
pause
