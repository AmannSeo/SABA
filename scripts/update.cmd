@echo off
rem SABA 패치 적용 (2026-10-16). 패치 zip 을 설치 폴더에 덮어써서 푼 뒤 실행한다.
rem 패치에는 프로그램 파일만 있다 (config, data, .venv 는 그대로). 관리 페이지를 다시 시작해 새 코드를 쓴다.
setlocal
set "ROOT=%~dp0"
if not exist "%ROOT%scripts\saba.ps1" set "ROOT=%~dp0..\"
cd /d "%ROOT%"
if not exist ".venv\Scripts\python.exe" if not exist "SABA.exe" (
  echo [실패] 설치된 SABA 폴더가 아닙니다. 먼저 "SABA 설치.cmd" 로 설치하세요.
  goto end
)
echo [1/2] 관리 페이지 종료
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\saba.ps1 stop
echo [2/2] 관리 페이지 다시 시작 (브라우저가 열립니다. 이 창은 닫지 마세요)
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\saba.ps1 start
:end
pause
