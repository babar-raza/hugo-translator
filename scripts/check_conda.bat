@echo off
call C:\Users\prora\anaconda3\Scripts\activate.bat base
conda env list > conda_envs.txt 2>&1
echo Done
