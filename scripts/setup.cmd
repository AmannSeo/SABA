@echo off
rem SABA 새 PC 설치 (2026-10-16): Python 확인·설치 -> 프로그램 설치 -> 백업 복원 -> 관리 페이지 시작.
rem 같은 폴더 (또는 상위 폴더) 에 scripts\saba.ps1 이 있어야 한다. 예약 (자동 실행) 은 등록하지 않는다.
setlocal
set "ROOT=%~dp0"
if not exist "%ROOT%scripts\saba.ps1" set "ROOT=%~dp0..\"
cd /d "%ROOT%"
set "PATH=%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts;%PATH%"

echo [1/5] Python 3.12 확인
py -3.12 -c "import sys" >nul 2>nul && goto python_ok
python -c "import sys; raise SystemExit(sys.version_info < (3, 12))" >nul 2>nul && goto python_ok
echo      Python 3.12 이 없어 설치합니다 (winget, 몇 분 걸림)...
winget install -e --id Python.Python.3.12 --scope user --silent --accept-source-agreements --accept-package-agreements
py -3.12 -c "import sys" >nul 2>nul && goto python_ok
python -c "import sys; raise SystemExit(sys.version_info < (3, 12))" >nul 2>nul && goto python_ok
echo.
echo [실패] Python 을 설치하지 못했습니다. python.org 에서 Python 3.12 를 설치한 뒤 이 파일을 다시 실행하세요.
goto fail
:python_ok

echo [2/5] SABA 설치 (인터넷 필요, 처음에는 몇 분 걸림)
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\saba.ps1 install || goto fail

echo [3/5] 백업 복원
set "BACKUP="
for %%f in (saba_backup_*.zip backups\saba_backup_*.zip) do set "BACKUP=%%f"
if not defined BACKUP (
  echo      백업 zip 이 없어 건너뜁니다. 관리 페이지에서 첫 관리자 계정을 만드세요.
) else if exist data\saba.db (
  echo      이미 데이터가 있어 복원하지 않습니다.
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\saba.ps1 restore -Path "%BACKUP%" || goto fail
)

echo [4/5] 관리자 계정 만들기 (처음 설치할 때만, 이미 있으면 건너뜀)
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\saba.ps1 create-admin

echo [5/5] 관리 페이지 시작 (브라우저가 열립니다. 이 창은 닫지 마세요)
echo      로그인 후 설정 화면에서 키 6개를 입력하세요.
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\saba.ps1 start
goto end

:fail
echo.
echo [실패] 위 오류 화면을 사진으로 찍어 보내 주세요.
:end
pause
