@echo off
call C:\Users\prora\anaconda3\Scripts\activate.bat hugo-translator
cd /d c:\Users\prora\OneDrive\Documents\GitHub\hugo-translator
python scripts\verify_migration.py > verify_output.txt 2>&1
echo Exit code: %ERRORLEVEL% >> verify_output.txt
