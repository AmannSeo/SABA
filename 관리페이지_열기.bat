@echo off
cd /d "%~dp0"
echo SABA admin page: http://127.0.0.1:8765/
echo Close this window to stop the admin page.
".venv\Scripts\python.exe" -m saba.admin
pause
