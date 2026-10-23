@echo off
cd /d "%~dp0.."
python -m wqb.signboard_launcher
if errorlevel 1 pause
