# SABA 부서 PC 설치·이전 절차 (D-068, 초안)

> D-082 (2026-10-15): 2026-10-16 다른 PC 시험 실행에 필요한 설치 초안과 절차만 사용한다. 정식 패키지·부서 PC 이전은 로드맵 3단계다. 실행 파일 빌드·예약 등록·기존 PC 해제 자동화는 이번 승인에 포함되지 않는다.

기존 PC 에서 회사가 제공하는 부서 전용 PC 로 SABA 를 옮길 때 사용한다.
모든 명령은 SABA 폴더에서 PowerShell 로 실행한다. 스크립트 사용법은 `scripts\saba.ps1 help` 로 볼 수 있다.

```
powershell -ExecutionPolicy Bypass -File scripts\saba.ps1 <명령>
```

## 1. 기존 PC 에서

1. 백업: `scripts\saba.ps1 backup` → `backups\saba_backup_YYYYMMDD_HHMM.zip`
   - 담기는 것: `data\` 전체 (기사·분석·시사점 DB, AI 사용량 기록, 본문 캐시), `config\`
   - 포함 확인: config/sources.json, config/admin.json, config/departments.json, config/public_api.json, data/admin_users.json. Git 제외 여부와 관계없이 data/·config/ 안의 파일을 백업한다 (admin.pid 제외).
   - 담기지 않는 것: Windows 환경 변수의 Secret 6개, 코드·서명·템플릿, logs/·output/. 새 PC 관리 페이지 설정에서 Secret을 입력한다. 기존 발송 원본 .eml이 없으면 과거 재발송은 불가능하며 시험에서는 재발송하지 않는다.
   - 백업에는 계정 비밀번호 해시·수신자 개인정보·기사 DB가 들어간다. 암호화 zip이 아니므로 승인된 저장 위치와 전송 경로만 사용하고 접근 권한을 제한한다. .env나 Secret 파일을 data/·config/에 두지 않는다 (백업은 임의 파일의 비밀 값을 자동 제거하지 않음).
   - 일관된 DB 백업을 위해 실행·설정 변경이 없는 시간에 사용자가 관리 페이지를 종료한 뒤 백업한다. 실행 중이거나 DB 변경 여부를 모르면 백업을 미루고 확인한다. 이번 작업이 기존 PC 프로세스나 스케줄러를 변경하지 않는다.
2. SABA 폴더 (소스) 와 백업 zip 을 새 PC 로 복사한다. `.venv\` 는 복사하지 않아도 된다 (새 PC 에서 다시 만든다).

## 2. 부서 PC 에서

1. Python 3.12 이상 설치 (python.org, "Add python.exe to PATH" 선택 또는 py 런처 사용)
2. Secret은 아래 시험 절차처럼 관리 페이지 설정에서 입력한다. Windows 환경 변수 창에서 직접 입력할 필요가 없다.
3. 설치: `scripts\saba.ps1 install`
   - `.venv` 생성, 의존성 설치 (인터넷 필요), 폴더 준비, 환경 변수 있음·없음 표시, 바탕화면 바로가기 2개 (관리 페이지 시작·종료)
4. 복원: `scripts\saba.ps1 restore -Path <백업 zip>`
   - 새 PC 에 이미 있던 `data\`·`config\` 는 `data_before_restore_시각` 처럼 이름을 바꿔 보관한다.
5. 확인: 바탕화면 "SABA 관리 페이지 시작" → 관리자 로그인 → 설정에서 Secret 6개 저장 → 테스트 화면의 설정 파일 점검. 실제 외부 점검은 별도 승인 범위만 수행한다.
6. 자동 실행 등록 (정식 이전 시 별도 승인 후, 시험 PC에서는 금지)
   - 확인: `scripts\saba.ps1 register -Unattended` (명령만 출력)
   - 등록: `scripts\saba.ps1 register -Unattended -Apply` → Windows 계정 비밀번호 입력 창 (저장하지 않음)
   - `-Unattended`: 로그인하지 않아도 실행, PC 가 08:00 에 꺼져 있었으면 켜진 뒤 실행 (놓친 실행 보완)
   - 등록 후 `scripts\saba.ps1 status` 로 로그온 방식 `Password`, 놓친 실행 보완 `True` 확인
7. 첫 실행 확인: 다음 평일 아침 관리 페이지 대시보드와 TEST 메일 도착 확인. 로그인하지 않은 상태에서도 환경 변수를 읽는지 첫 실행 로그로 확인한다.

## 3. 기존 PC 정리 (정식 이전 승인·부서 PC 정상 확인 후, 시험에서는 수행하지 않음)

- 같은 메일이 두 번 가지 않게 기존 PC 자동 실행을 해제한다: `scripts\saba.ps1 unregister -Apply`
- 완전히 제거: `scripts\saba.ps1 uninstall -Apply` (자동 실행 해제, 관리 페이지 종료, `.venv`·바로가기 삭제, `data\`·`config\` 는 남김)

## 명령 요약

| 명령 | 내용 | 실제 변경 |
|---|---|---|
| install | .venv·의존성·폴더·바로가기, 환경 변수 확인 | 있음 |
| start / stop | 관리 컨트롤 페이지 시작·종료 | 프로세스·실행 표시 변경 |
| status | 자동 실행 상태·로그온 방식·환경 변수 있음·없음 | 없음 |
| register [-Unattended] [-Apply] | 자동 실행 등록 | -Apply 일 때만 |
| unregister [-Apply] | 자동 실행 해제 | -Apply 일 때만 |
| backup | data\·config\ zip 백업 | backups\ 에 파일 생성 |
| restore -Path zip | 백업 복원 (기존 폴더 보관) | 있음 |
| uninstall [-Apply] | 제거 (data\ 유지) | -Apply 일 때만 |

## 다른 PC 시험 실행 (D-082, 2026-10-16 사용자 수행)

1. 기존 PC의 코드 폴더를 복사하거나 같은 버전을 Git으로 준비한다. .venv는 복사하지 않고 새 PC에서 만든다. Git만 사용하면 로컬 전용 설정·계정·운영 데이터가 같다는 보장이 없으므로 승인된 백업 zip도 준비한다. 서명·템플릿 파일이 빠지지 않았는지 확인한다.
2. 새 PC에서 Python 3.12 이상을 준비하고 SABA 폴더에서 `powershell -ExecutionPolicy Bypass -File scripts\saba.ps1 install`을 실행한다. 의존성 설치는 인터넷 또는 별도로 준비한 설치 자료가 필요하다. 이 작업 환경에서는 설치·다운로드를 실행하지 않았다. install은 예약을 등록하지 않는다.
3. 복원할 경우 관리 페이지를 열기 전에 `powershell -ExecutionPolicy Bypass -File scripts\saba.ps1 restore -Path <백업 zip 경로>`를 실행한다. restore는 프로젝트 Python이 필요하므로 install 다음에 수행한다. 기존 data/·config/는 이름을 바꿔 보관하며, 다른 용도의 기존 데이터가 있으면 먼저 확인한다. 신뢰하는 이 프로젝트의 백업만 사용한다.
4. config/admin.json의 login이 true인지 확인한다. 예전 백업을 복원하면 false가 될 수 있으므로 다른 값은 유지하고 true로 맞춘 뒤 시작한다. 바탕화면 관리 페이지 시작 또는 `powershell -ExecutionPolicy Bypass -File scripts\saba.ps1 start`를 사용한다. 127.0.0.1 전용을 유지한다.
5. 계정을 복원했으면 기존 admin 계정과 사용자가 알고 있는 비밀번호로 로그인한다. 계정이 없으면 첫 관리자 만들기 화면에서 생성한다. 계정이 있는데 비밀번호를 모르는 경우 data/admin_users.json을 삭제해 우회하지 말고 기존 관리자를 통해 해결한다.
6. 설정 화면에서 아래 Secret을 하나씩 선택해 저장한다. 값은 다시 보이지 않으며 있음·없음만 확인한다. 조회자는 저장할 수 없다. 값은 문서·채팅·명령줄·백업 파일에 적지 않는다.

   | 이름 | 용도 |
   |---|---|
   | OPENAI_API_KEY | AI 분석 |
   | SABA_SMTP_HOST | 회사 메일 서버 |
   | SABA_SMTP_USER | SMTP 계정 (메일 주소 @ 앞부분) |
   | SABA_SMTP_PASSWORD | SMTP 비밀번호 |
   | SABA_DATA_GO_KR_KEY | 나라장터·K-Startup 공공 API |
   | SABA_LAW_OC | 국가법령정보 OC |

7. 입력은 관리 페이지를 실행한 Windows 계정의 HKCU\\Environment에 저장된다. 해당 관리 페이지에서 시작하는 실행에는 즉시 반영된다. 이미 열려 있던 PowerShell·VS Code 등 다른 프로그램은 새 값을 못 읽을 수 있어 다시 시작한다. 다른 Windows 계정으로 실행하면 값이 공유되지 않는다. 암호화 저장소가 아니며 DPAPI 파일·이전 암호 내보내기·가져오기는 3단계까지 미구현이다.
8. 먼저 테스트 화면의 "설정 파일 점검"을 실행한다 (외부 연결 없음). 발송 준비 점검도 메일 파일이 있을 때만 사용하며 SMTP에 접속하지 않는다. 복원 직후 output에 원본이 없으면 메일 없음은 예상된 상태다. 설정 점검 성공은 API 인증·수집·AI·메일 성공의 증거가 아니다.
9. 실제 수집·AI가 필요한 발송 없는 시험은 그 호출·비용의 별도 승인 후에만 새 PowerShell에서 `.\.venv\Scripts\python.exe -m saba.daily --run --no-send --manual`로 수행한다. 두 PC의 호출 기록·하루 상한은 자동 동기화되지 않는다. 이번 문서 작성으로 실제 실행·호출·발송을 승인하지 않는다. 즉시 테스트 발송·시각 지정 테스트 발송·지금 발송·재발송은 누르지 않는다.
10. 시험 PC에서는 register와 예약 토글·일정 변경을 사용하지 않는다. 이미 같은 작업이 등록돼 있다면 시험을 멈추고 확인한다. 기존 PC는 같은 날 정상 운영할 수 있으므로 자동·수동 중복 발송을 피한다. GROUP_SEND_APPROVED=False를 유지하며 기존 PC 작업 해제도 하지 않는다.
11. 공공데이터포털·국가법령정보의 기업 가입 명의와 서비스별 등록 IP 제한을 사용자가 확인한다. 새 PC의 외부 IP가 다르면 변경·추가 등록 필요 여부를 확인한다. 기존 PC도 사용 중이면 그 접근을 끊지 않도록 제공 기관의 정책을 확인한다.
12. 시험 후 새 PC 관리 페이지를 종료한다. 계속 보관할지 결정하고, 승인된 절차로 시험 PC에 입력한 사용자 환경 변수 6개·복사한 개인정보·백업 zip·복원 전 폴더를 정리한다. uninstall만으로 Secret·data/·config/·백업은 지워지지 않는다. 기존 PC의 Secret이나 운영 기록은 삭제하지 않는다.

## 실행 파일 묶음 (Python 설치 없이, D-069, 3단계에서 재검토)

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
- [ ] 외부 접속 허용: OpenAI API (api.openai.com, HTTPS 443), 현재 설정의 출처 47곳 (RSS·공개 목록·공공 API, 실제 설정을 다시 확인), 회사 메일 SMTP (465 SSL/TLS)
- [ ] 부서 PC 에서 개인 메일 계정 대신 부서 공용 계정 사용 여부 (3단계 전사 발송 전 결정)
- [ ] 관리 페이지는 127.0.0.1 전용이므로 방화벽 예외 불필요 (사내망 접속은 3단계에서 별도 검토)
