@echo off
REM Test TM cache override system with slides/en files for Bulgarian locale

echo Activating conda environment...
call C:\Users\prora\anaconda3\Scripts\activate.bat llm

echo.
echo Testing TM Cache Override System
echo =================================
echo.
echo Input: D:\onedrive\Documents\GitHub\aspose.net\content\products.aspose.net\slides\en
echo Output: output\slides-bg-test
echo Target: bg (Bulgarian)
echo Override Mode: refresh
echo.

python scripts/batch_translate.py ^
    --input "D:\onedrive\Documents\GitHub\aspose.net\content\products.aspose.net\slides\en" ^
    --output "output\slides-bg-test" ^
    --site-id products.aspose.net ^
    --langs bg ^
    --override-mode refresh ^
    --report "output\slides-bg-test-report.json"

echo.
echo Test complete.
pause
