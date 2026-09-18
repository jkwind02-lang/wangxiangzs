@echo off
setlocal
cd /d "%~dp0.."
py -3 -m wxq_assistant gui
if errorlevel 1 pause
