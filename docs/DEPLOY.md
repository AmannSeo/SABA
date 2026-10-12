# SABA 부서 PC 설치·이전 절차 (D-068, 초안)

> 초안 (D-070): 패키지와 부서 PC 이전은 모든 기능과 관리 컨트롤 페이지 완성 후 로드맵 3단계에서 다시 검토한다. 지금은 사용하지 않는다.

기존 PC 에서 회사가 제공하는 부서 전용 PC 로 SABA 를 옮길 때 사용한다.
모든 명령은 SABA 폴더에서 PowerShell 로 실행한다. 스크립트 사용법은 `scripts\saba.ps1 help` 로 볼 수 있다.

```
powershell -ExecutionPolicy Bypass -File scripts\saba.ps1 <명령>
```

## 1. 기존 PC 에서

1. 백업: `scripts\saba.ps1 backup` → `backups\saba_backup_YYYYMMDD_HHMM.zip`
   - 담기는 것: `data\` 전체 (기사·분석·시사점 DB, AI 사용량 기록, 본문 캐시), `config\`
   - 담기지 않는 것: 환경 변수 (API Key, SMTP 정보). 새 PC 에서 직접 입력한다.
2. SABA 폴더 (소스) 와 백업 zip 을 새 PC 로 복사한다. `.venv\` 는 복사하지 않아도 된다 (새 PC 에서 다시 만든다).

## 2. 부서 PC 에서

1. Python 3.12 이상 설치 (python.org, "Add python.exe to PATH" 선택 또는 py 런처 사용)
2. 환경 변수 4개를 Windows 사용자 환경 변수에 직접 입력: `OPENAI_API_KEY`, `SABA_SMTP_HOST`, `SABA_SMTP_USER` (메일 주소 @ 앞부분), `SABA_SMTP_PASSWORD`
   - 값은 문서·채팅·파일에 적지 않는다. 입력 후 PowerShell 창을 새로 연다.
3. 설치: `scripts\saba.ps1 install`
   - `.venv` 생성, 의존성 설치 (인터넷 필요), 폴더 준비, 환경 변수 있음·없음 표시, 바탕화면 바로가기 2개 (관리 페이지 시작·종료)
4. 복원: `scripts\saba.ps1 restore -Path <백업 zip>`
   - 새 PC 에 이미 있던 `data\`·`config\` 는 `data_before_restore_시각` 처럼 이름을 바꿔 보관한다.
5. 확인: 바탕화면 "SABA 관리 페이지 시작" → 설정 검증, 발송 드라이런, SMTP 연결·인증 확인 (발송 없음)
6. 자동 실행 등록 (승인 후)
   - 확인: `scripts\saba.ps1 register -Unattended` (명령만 출력)
   - 등록: `scripts\saba.ps1 register -Unattended -Apply` → Windows 계정 비밀번호 입력 창 (저장하지 않음)
   - `-Unattended`: 로그인하지 않아도 실행, PC 가 08:00 에 꺼져 있었으면 켜진 뒤 실행 (놓친 실행 보완)
   - 등록 후 `scripts\saba.ps1 status` 로 로그온 방식 `Password`, 놓친 실행 보완 `True` 확인
7. 첫 실행 확인: 다음 평일 아침 관리 페이지 대시보드와 TEST 메일 도착 확인. 로그인하지 않은 상태에서도 환경 변수를 읽는지 첫 실행 로그로 확인한다.

## 3. 기존 PC 정리 (부서 PC 정상 확인 후)

- 같은 메일이 두 번 가지 않게 기존 PC 자동 실행을 해제한다: `scripts\saba.ps1 unregister -Apply`
- 완전히 제거: `scripts\saba.ps1 uninstall -Apply` (자동 실행 해제, 관리 페이지 종료, `.venv`·바로가기 삭제, `data\`·`config\` 는 남김)

## 명령 요약

| 명령 | 내용 | 실제 변경 |
|---|---|---|
| install | .venv·의존성·폴더·바로가기, 환경 변수 확인 | 있음 |
| start / stop | 관리 컨트롤 페이지 시작·종료 | 없음 |
| status | 자동 실행 상태·로그온 방식·환경 변수 있음·없음 | 없음 |
| register [-Unattended] [-Apply] | 자동 실행 등록 | -Apply 일 때만 |
| unregister [-Apply] | 자동 실행 해제 | -Apply 일 때만 |
| backup | data\·config\ zip 백업 | backups\ 에 파일 생성 |
| restore -Path zip | 백업 복원 (기존 폴더 보관) | 있음 |
| uninstall [-Apply] | 제거 (data\ 유지) | -Apply 일 때만 |

## 실행 파일 묶음 (Python 설치 없이, D-069)

개발 PC 에서 만든 `dist\SABA\` 폴더를 통째로 부서 PC 에 복사하면 Python 을 설치하지 않아도 된다.

1. 개발 PC: `powershell -ExecutionPolicy Bypass -File scripts\build_exe.ps1` → `dist\SABA\` (약 36MB)
   - PyInstaller 는 개발 PC 의 `.venv` 에만 설치된다 (pyproject `build` 선택 의존성).
   - 묶음 내용: `SABA.exe`, `_internal\`, `templates\`, `sign\`, `config\`, `scripts\saba.ps1`, `docs\DEPLOY.md`. `data\` 와 Secret 은 들어가지 않는다.
2. 부서 PC: `dist\SABA\` 를 원하는 위치 (예: `C:\SABA`) 에 복사한 뒤, 위 2절 절차를 그대로 따른다.
   - 1번 (Python 설치) 은 건너뛴다. `install` 은 Python·의존성 설치를 건너뛰고 폴더·바로가기만 만든다.
   - 자동 실행 대상은 `SABA.exe -m saba.daily --run` 이 된다 (등록 명령이 자동으로 실행 파일 경로를 쓴다).
3. 직접 실행 예: `SABA.exe -m saba.admin`, `SABA.exe -m saba.daily --register`, `SABA.exe -m saba.deploy --backup`

폴더 위치를 옮기면 자동 실행을 다시 등록해야 한다 (등록 명령에 실행 파일 경로가 들어 있다).

## 부서 PC 설치 전 회사 IT·보안 정책 확인 목록 (D-069)

- [ ] 서명 없는 실행 파일(`SABA.exe`) 실행 허용 여부, 백신 예외 등록 필요 여부 (필요하면 `SABA` 폴더 경로로 요청)
- [ ] 작업 스케줄러 "사용자 로그온 여부와 관계없이 실행" 허용 여부 (계정 비밀번호 저장 정책, 비밀번호 변경 시 재등록 필요)
- [ ] 외부 접속 허용: OpenAI API (api.openai.com, HTTPS 443), RSS Source 6곳 (HTTPS), 회사 메일 SMTP (465 SSL/TLS)
- [ ] 부서 PC 에서 개인 메일 계정 대신 부서 공용 계정 사용 여부 (3단계 전사 발송 전 결정)
- [ ] 관리 페이지는 127.0.0.1 전용이므로 방화벽 예외 불필요 (사내망 접속은 3단계에서 별도 검토)
