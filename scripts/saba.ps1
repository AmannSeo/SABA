# SABA 설치·실행 스크립트 (D-068). 부서 PC 등 새 PC 에서 명령 하나로 설치·실행·종료한다.
#
#   powershell -ExecutionPolicy Bypass -File scripts\saba.ps1 <명령> [옵션]
#
#   install                     .venv 구성, 의존성 설치, 폴더 준비, 환경 변수 확인, 바탕화면 바로가기
#   start / stop                관리 컨트롤 페이지 시작 (브라우저) / 종료
#   status                      자동 실행 상태와 환경 변수 있음·없음
#   register [-Unattended] [-Apply]   자동 실행 등록 (기본은 명령 확인만, -Apply 일 때 실제 등록)
#                                     -Unattended: 로그인 없이 실행 + 놓친 실행 보완 (부서 PC)
#   unregister [-Apply]         자동 실행 해제 (기본은 확인만)
#   backup                      data\ 와 config\ 를 backups\ 에 zip 으로 저장
#   restore -Path <zip>         백업 zip 복원 (기존 폴더는 이름을 바꿔 보관)
#   uninstall [-Apply]          자동 실행 해제, 관리 페이지 종료, .venv·바로가기 삭제 (data\ 는 남김)
#   reset-password              계정 비밀번호 초기화 (비밀번호를 잊었을 때, 이 PC 에서만)
#   create-admin                계정이 없을 때 첫 관리자 계정 만들기 (설치 때 자동 실행)
#
# Secret(API Key, SMTP 비밀번호) 은 이 스크립트가 받거나 저장하지 않는다. 있음·없음만 확인한다.

param(
    [Parameter(Position = 0)]
    [ValidateSet("install", "start", "stop", "status", "register", "unregister", "backup", "restore", "uninstall", "reset-password", "create-admin", "help")]
    [string]$Command = "help",
    [switch]$Apply,
    [switch]$Unattended,
    [string]$Path
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Exe = Join-Path $Root "SABA.exe"  # 실행 파일 묶음 (D-069) 이면 Python 설치 없이 이것을 쓴다
$Packaged = Test-Path $Exe
$Python = if ($Packaged) { $Exe } else { Join-Path $Root ".venv\Scripts\python.exe" }
$TaskName = "SABA_Daily_Briefing"
$SecretNames = "OPENAI_API_KEY", "SABA_SMTP_HOST", "SABA_SMTP_USER", "SABA_SMTP_PASSWORD", "SABA_DATA_GO_KR_KEY", "SABA_LAW_OC"
$Desktop = [Environment]::GetFolderPath("Desktop")
$Shortcuts = @{ "SABA 관리 페이지 시작.lnk" = "start"; "SABA 관리 페이지 종료.lnk" = "stop" }
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
Set-Location $Root

function Invoke-Saba([string[]]$Arguments) {
    if (-not (Test-Path $Python)) { throw "설치되지 않았습니다. 먼저 install 을 실행하세요." }
    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) { throw "명령 실패 (종료 코드 $LASTEXITCODE)" }
}

function Show-Secrets {
    foreach ($name in $SecretNames) {
        $value = [Environment]::GetEnvironmentVariable($name, "User")
        if (-not $value) { $value = [Environment]::GetEnvironmentVariable($name, "Process") }
        $state = if ($value) { "있음" } else { "없음" }
        Write-Output "  $name : $state"
    }
    Write-Output "관리 페이지에 관리자 계정으로 로그인한 뒤 설정 화면에서 Secret 6개를 입력·수정하세요 (값은 다시 표시하지 않음)."
}

function Find-Python {
    foreach ($candidate in @(@("py", "-3.12"), @("python"))) {
        $exe = $candidate[0]
        if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
        $extra = @($candidate | Select-Object -Skip 1)
        $version = & $exe @extra -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $version -and [version]$version -ge [version]"3.12") { return $candidate }
    }
    throw "Python 3.12 이상을 찾지 못했습니다. python.org 에서 Python 3.12 를 설치한 뒤 다시 실행하세요."
}

switch ($Command) {
    "install" {
        if ($Packaged) {
            Write-Output "실행 파일 묶음: Python·의존성 설치를 건너뜁니다."
        } elseif (-not (Test-Path $Python)) {
            $base = Find-Python
            $extra = @($base | Select-Object -Skip 1)
            Write-Output "가상 환경 만들기 (.venv)"
            & $base[0] @extra -m venv (Join-Path $Root ".venv")
            if ($LASTEXITCODE -ne 0) { throw ".venv 생성 실패" }
        }
        if (-not $Packaged) {
            Write-Output "의존성 설치"
            Invoke-Saba @("-m", "pip", "install", "--disable-pip-version-check", "-q", "-e", $Root)
        }
        foreach ($folder in "data", "logs", "output", "backups") {
            New-Item -ItemType Directory -Force (Join-Path $Root $folder) | Out-Null
        }
        $shell = New-Object -ComObject WScript.Shell
        foreach ($name in $Shortcuts.Keys) {
            # -NoExit: 시작 실패 (예: 스마트 앱 컨트롤 차단) 때 창이 바로 닫히지 않고 오류가 보인다 (2026-10-16 새 PC).
            $link = $shell.CreateShortcut((Join-Path $Desktop $name))
            $link.TargetPath = "powershell.exe"
            $link.Arguments = "-NoExit -ExecutionPolicy Bypass -WindowStyle Minimized -File `"$PSCommandPath`" $($Shortcuts[$name])"
            $link.WorkingDirectory = $Root
            $link.Save()
        }
        Write-Output "설치 완료. 바탕화면에 관리 페이지 시작·종료 바로가기를 만들었습니다."
        Write-Output "환경 변수:"
        Show-Secrets
        Write-Output "install: 예약을 등록하지 않습니다. 새 PC 무인 등록은 docs\DEPLOY.md 의 확인 절차를 마친 뒤 register -Unattended -Apply 로 수행하세요."
    }
    "start" { Invoke-Saba @("-m", "saba.admin") }
    "reset-password" { Invoke-Saba @("-m", "saba.auth", "--reset-password") }  # 비밀번호를 잊었을 때 이 PC 에서 초기화
    "create-admin" { Invoke-Saba @("-m", "saba.auth", "--create-admin") }  # 설치 때 첫 관리자 계정 (이미 있으면 건너뜀)
    "stop" { Invoke-Saba @("-m", "saba.admin", "--stop") }
    "status" {
        $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if ($task) {
            $info = $task | Get-ScheduledTaskInfo
            Write-Output "자동 실행: $($task.State) · 로그온 방식 $($task.Principal.LogonType) · 놓친 실행 보완 $($task.Settings.StartWhenAvailable) · 다음 실행 $($info.NextRunTime)"
        } else {
            Write-Output "자동 실행: 등록 안 됨"
        }
        Write-Output "환경 변수:"
        Show-Secrets
    }
    "register" {
        $arguments = @("-m", "saba.daily", "--register")
        if ($Unattended) { $arguments += "--unattended" }
        if ($Apply) { $arguments += "--apply" } else { Write-Output "확인만 합니다 (실제 등록은 -Apply):" }
        Invoke-Saba $arguments
    }
    "unregister" {
        if (-not $Apply) { Write-Output "확인만 합니다: Unregister-ScheduledTask -TaskName $TaskName (실제 해제는 -Apply)"; break }
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
        Write-Output "자동 실행을 해제했습니다."
    }
    "backup" { Invoke-Saba @("-m", "saba.deploy", "--backup") }
    "restore" {
        if (-not $Path) { throw "restore 는 -Path <백업 zip> 이 필요합니다." }
        Invoke-Saba @("-m", "saba.deploy", "--restore", (Resolve-Path $Path).Path)
    }
    "uninstall" {
        if (-not $Apply) {
            Write-Output "확인만 합니다. -Apply 로 실행하면: 자동 실행 해제, 관리 페이지 종료, .venv 와 바탕화면 바로가기 삭제."
            Write-Output "data\ (기사·분석 DB, 사용량 기록) 와 config\ 는 남깁니다. 필요하면 먼저 backup 을 실행하세요."
            break
        }
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
        if (Test-Path $Python) { & $Python -m saba.admin --stop }
        foreach ($name in $Shortcuts.Keys) { Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $Desktop $name) }
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Join-Path $Root ".venv")
        Write-Output "제거 완료. data\ 와 config\ 는 남겨 두었습니다."
    }
    default { Get-Content $PSCommandPath -Encoding UTF8 | Select-Object -Skip 1 -First 14 | ForEach-Object { $_.TrimStart("# ") } }
}
