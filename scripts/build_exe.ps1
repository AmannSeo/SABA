# SABA 실행 파일 묶음 만들기 (D-069). 개발 PC 에서 실행한다. 결과: dist\SABA\ (폴더째 부서 PC 로 복사)
#
#   powershell -ExecutionPolicy Bypass -File scripts\build_exe.ps1
#
# PyInstaller 는 개발 도구로 .venv 에만 설치한다 (pyproject build 선택 의존성). data\ 와 Secret 은 넣지 않는다.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Dist = Join-Path $Root "dist\SABA"
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
Set-Location $Root

& $Python -c "import PyInstaller"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 가 없습니다. 승인된 개발 환경에서 준비하세요. 이 빌드는 다운로드하지 않습니다." }
foreach ($folder in "data", "logs", "output", "backups") {
    if (Test-Path (Join-Path $Dist $folder)) { throw "기존 묶음에 운영 폴더가 있습니다 ($folder). 먼저 안전하게 보관하고 새 빌드 위치를 준비하세요." }
}

# 한 폴더 형태 (D-069): 파일 하나 형태보다 시작이 빠르고 백신 오탐이 적다.
& $Python -m PyInstaller --noconfirm --clean --onedir --contents-directory _internal --name SABA --console `
    --collect-submodules saba --distpath (Join-Path $Root "dist") --workpath (Join-Path $Root "build") `
    --specpath (Join-Path $Root "build") (Join-Path $PSScriptRoot "saba_entry.py")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 빌드 실패" }

# 프로그램이 SABA.exe 옆 폴더에서 읽는 파일 (경로 기준은 src\saba 의 parents[2] = dist\SABA).
foreach ($folder in "templates", "sign") {
    Copy-Item -Recurse -Force (Join-Path $Root $folder) (Join-Path $Dist $folder)
}
New-Item -ItemType Directory -Force (Join-Path $Dist "config"), (Join-Path $Dist "scripts"), (Join-Path $Dist "docs") | Out-Null
foreach ($name in "admin.json", "daily.json", "departments.json", "public_api.json", "sources.json") {
    Copy-Item -Force (Join-Path $Root "config\$name") (Join-Path $Dist "config\$name")
}
Copy-Item -Force (Join-Path $PSScriptRoot "saba.ps1") (Join-Path $Dist "scripts\saba.ps1")
Copy-Item -Force (Join-Path $Root "docs\DEPLOY.md") (Join-Path $Dist "docs\DEPLOY.md")
Copy-Item -Force (Join-Path $Root "docs\ADMIN.md") (Join-Path $Dist "docs\ADMIN.md")

$size = (Get-ChildItem -Recurse $Dist | Measure-Object -Sum Length).Sum
Write-Output ("빌드 완료: {0} ({1:N1} MB)" -f $Dist, ($size / 1MB))
