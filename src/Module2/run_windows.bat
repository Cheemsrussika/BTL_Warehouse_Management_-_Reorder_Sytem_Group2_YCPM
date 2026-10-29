@echo off
cd /d "%~dp0"
py demo_cli.py
if errorlevel 1 python demo_cli.py
pause
