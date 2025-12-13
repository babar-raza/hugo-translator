@echo off
call C:\Users\prora\anaconda3\Scripts\activate.bat hugo-translator
cd /d c:\Users\prora\OneDrive\Documents\GitHub\hugo-translator
python validate_configs.py
