@echo off
rem SABA 관리 페이지 계정 비밀번호 초기화 (2026-10-16). 이 PC 에서만 실행한다. 비밀번호는 화면에 보이지 않는다.
setlocal
set "ROOT=%~dp0"
if not exist "%ROOT%scripts\saba.ps1" set "ROOT=%~dp0..\"
cd /d "%ROOT%"
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\saba.ps1 reset-password
pause
