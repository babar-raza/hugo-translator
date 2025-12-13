@echo off
call C:\Users\prora\anaconda3\Scripts\activate.bat hugo-translator
cd /d c:\Users\prora\OneDrive\Documents\GitHub\hugo-translator
python -m pytest tests/unit/validation/test_file_placement_validator.py -v --tb=short --cov=src.translation_engine.validation.file_placement_validator --cov-report=term-missing
