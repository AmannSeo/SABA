# SABA 부서 PC 이전 (실행 파일 묶음)

2026-10-16 사용자 결정: 파일럿 전에 로드맵 3단계를 시작한다. 이 순서 변경은 DECISIONS 기록 승인 대기이며 이번에는 DEVELOPMENT_STATUS.md에만 기록한다. 새 PC는 Python 없이 실행 파일 묶음을 사용하고, 로그인 없이 실행과 놓친 실행 보완을 선택한다. Secret은 관리 페이지에서 재입력하며 DPAPI·이전 암호·새 의존성은 추가하지 않는다.

## 1. 개발 PC의 오프라인 빌드

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_exe.ps1
```

- 기존 .venv의 PyInstaller를 사용한다. 없으면 다운로드하지 않고 오류로 멈춘다.
- 결과는 dist\SABA\다. SABA.exe 하나만 복사하면 안 된다. _internal\까지 폴더 전체가 필요하다.
- 포함: SABA.exe, _internal\, templates\, sign\, config\의 admin·daily·departments·public_api·sources.json, scripts\saba.ps1, docs\DEPLOY.md·ADMIN.md.
- 제외: 운영 data\·logs\·output\·backups\, 계정 파일·DB·사용량·발송 이력, 환경 변수·Secret. 승인된 설정 파일 자체는 들어간다. 비밀 값을 설정 파일에 직접 넣지 않는다.
- _internal\saba\모듈.py의 parents[2]가 SABA.exe 옆 폴더를 가리키도록 PyInstaller의 _internal 배치를 고정한다. 실행 위치가 다른 폴더여도 운영 데이터·정적 파일 기준은 묶음 폴더다.
- 배포 묶음의 data·logs·output·backups 폴더가 이미 있으면 빌드를 거부한다. 운영 중인 배포 폴더 위에 재빌드하지 않는다.
- 서명 없는 실행 파일과 회사 백신·실행 정책은 IT·보안 담당자에게 먼저 확인한다. 무조건 백신 예외를 적용하지 않는다.

## 2. 기존 PC에서 복사 준비 (사용자 수행)

1. 실행·예약 시각과 겹치지 않는 시간에 관리 페이지를 종료하고 다른 실행이 없는지 확인한다. 이번 개발 작업은 기존 관리 페이지나 스케줄러를 종료하지 않는다.
2. SABA 폴더에서 백업한다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\saba.ps1 backup
```

3. dist\SABA\ 전체와 backups\saba_backup_날짜_시각.zip을 새 PC에 안전하게 전달한다. 현재 운영 data를 배포 묶음에 직접 섞지 않는다.
4. 백업은 data\·config\ 전체 (admin.pid 제외)를 담는다. 관리자 비밀번호 해시·수신자 개인정보·기사·분석·발송 이력이 포함된다. 암호화 zip이 아니므로 접근 권한과 전송 경로·보관 기간을 제한한다.
5. Windows 환경 변수 6개는 백업되지 않는다. .env나 Secret 파일을 data\·config\에 두면 백업이 자동 제거해 주지 않는다.
6. logs\·output\은 백업되지 않는다. 과거 .eml 원본이 없으면 재발송은 거부되는 것이 정상이다. 그룹 잠금도 그대로 False로 유지한다. 기존 파일 이전·운영 이력 수정은 이번 절차에 포함하지 않는다.

## 3. 새 PC 설치·복원·로그인

1. 쓰기 권한이 있는 폴더 (예: C:\SABA)에 묶음 전체를 복사한다. Program Files 등 일반 사용자가 쓸 수 없는 위치는 피한다. 아래 명령은 이 폴더의 PowerShell에서 실행한다.
2. 설치한다. Python·pip·인터넷 다운로드를 사용하지 않는다. 폴더와 관리 페이지 시작·종료 바로가기만 만들며 예약은 등록하지 않는다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\saba.ps1 install
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\saba.ps1 restore -Path C:\보관위치\saba_backup_날짜_시각.zip
```

3. 복원은 관리 페이지를 시작하기 전에 한다. 기존 data\·config\는 *_before_restore_시각 폴더로 보관한다. 신뢰하는 프로젝트 백업만 사용한다. 새 PC에 기존 운영 데이터가 있으면 덮어쓰기를 진행하지 말고 먼저 확인한다.
4. config\admin.json의 login이 true인지 확인한다. 예전 백업이 false로 되돌렸다면 다른 값은 유지하고 true로 맞춘다. 127.0.0.1 전용은 유지한다.
5. start를 실행하거나 바탕화면 바로가기를 연다. 계정을 복원했으면 기존 admin과 사용자가 알고 있는 비밀번호로 로그인한다. 계정이 없으면 첫 관리자 화면에서 만든다. 기존 계정의 비밀번호를 모른다고 계정 파일을 삭제하지 않는다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\saba.ps1 start
```

6. 설정 화면에서 관리자가 아래 6개를 한 개씩 저장한다. 값은 다시 보이지 않고 있음·없음만 표시한다. 조회자·로그인하지 않은 사용자는 변경할 수 없다.

| 이름 | 용도 |
|---|---|
| OPENAI_API_KEY | AI 분석·시사점 |
| SABA_SMTP_HOST | 회사 메일 서버 |
| SABA_SMTP_USER | SMTP 계정 |
| SABA_SMTP_PASSWORD | SMTP 비밀번호 |
| SABA_DATA_GO_KR_KEY | 나라장터·K-Startup |
| SABA_LAW_OC | 국가법령정보 OC |

- 설정은 이 Windows 계정의 HKCU\Environment에 저장된다. 관리 페이지와 예약 실행은 같은 Windows 계정을 사용한다. 관리자 권한으로 다른 계정을 사용하는 것은 별개다.
- 실행 파일의 관리 페이지·일일 실행은 시작할 때 HKCU의 6개 값을 프로세스에 반영한다. help·예약 명령 출력·백업/복원은 Secret을 읽지 않는다. 이미 실행 중인 프로세스는 사용자 재시작이 필요하다.
- DPAPI 암호화 보관소가 아니다. Windows 계정·폴더 ACL·디스크 보안과 회사 보관 정책을 적용한다. 값은 문서·명령줄·로그·채팅에 남기지 않는다.
- 실제 공공 API 호출 전에 기업 가입 명의·허용된 등록 IP를 확인한다. 새 PC의 외부 IP 변경 시 변경/추가 등록 필요 여부는 서비스별 정책에 따른다. 기존 PC도 운영 중이면 기존 접근을 끊지 않도록 확인한다.

## 4. 점검과 발송 없는 첫 실행

1. 테스트 화면에서 설정 파일 점검을 수행한다. 메일 원본이 있을 때의 발송 준비 점검도 외부 접속·발송 없이 확인한다. SMTP 로그인 점검·RSS 점검·즉시 테스트 발송과 혼동하지 않는다.
2. 새 PC의 예약 발송 설정에서 발송 여부를 끈다. 대상 그룹 잠금 False는 유지한다. 첫 자동 실행 확인도 발송 없이 수행해 기존 PC와 같은 날 두 번 보내지 않게 한다.
3. 사용자 비용·실제 수집 승인 후에만 발송 없는 수동 실행을 한 번 한다.

```powershell
.\SABA.exe -m saba.daily --run --manual --no-send
```

4. 메일 생성·분석 결과·게재 제외·실패 Source·사용량을 확인한다. --no-send는 RSS·API·AI 호출까지 막는 옵션이 아니다. 두 PC의 DB와 하루 상한은 자동 동기화되지 않으므로 중복 호출과 월 상한을 함께 관리한다.
5. 이 문서를 작성한 개발 작업은 실제 수집·AI·SMTP·메일 실행을 하지 않는다. 무인 실행 성공은 새 PC에서 아래 실제 확인 후에만 판정한다.

## 5. 새 PC 무인 예약 등록 (사용자 수행)

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\saba.ps1 register -Unattended
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\saba.ps1 register -Unattended -Apply
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\saba.ps1 status
```

- 첫 명령은 출력만 한다. -Apply만 실제 등록한다. Windows 로그인 암호는 Get-Credential 입력 창에만 입력한다. PIN과 계정 비밀번호는 다를 수 있다. SABA 파일·설정·로그에는 저장하지 않지만 Windows 작업 스케줄러의 자격 증명 보관은 회사 정책에 따른다.
- 관리 페이지에서 Secret을 입력한 동일 Windows 계정을 선택한다. 비밀번호 변경 시 재등록이 필요할 수 있다.
- StartWhenAvailable 켬: PC가 꺼져 놓친 실행은 켜진 뒤 보완한다. WakeToRun·배터리 조건 해제도 포함된다. Windows 전원·절전 해제 타이머·회사 정책에 따라 실제 깨우기는 달라질 수 있다.
- 다음 평일 첫 자동 실행은 로그아웃 상태와 발송 꺼짐 상태로 확인한다. 새 PC가 꺼져 있었으면 켠 뒤 보완 실행을 확인한다. 실제 수집·AI 호출 비용 승인도 포함해 운영 시간을 정한다.
- 로그·실행 결과 코드·기사/분석·메일 파일이 SABA.exe 옆에 만들어지고 인증이 정상인지 확인한다. 설정 화면의 있음 표시만으로 무인 인증 성공을 판단하지 않는다.
- 무인 등록 뒤 일정 (시각·요일·주기) 은 관리 페이지에서 바꾸지 않는다. 화면 재등록은 Windows 비밀번호 입력 창이 없어 일반 예약으로 바뀌므로 거부된다. config\daily.json 의 일정을 고친 뒤 register -Unattended -Apply 로 다시 등록한다. 발송 켜기·끄기, AI 상한, 보관 기간은 화면에서 바꿔도 된다 (재등록 없음).
- 이 확인 전에는 기존 PC 예약을 해제하지 않는다. 두 PC의 발송 여부를 동시에 켜지 않는다.

## 6. 전환과 되돌리기

1. 새 PC의 발송 없는 무인 실행 성공을 확인한 뒤, 기존 PC의 SABA 폴더에서 사용자가 예약을 해제한다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\saba.ps1 unregister -Apply
```

2. 기존 PC가 오늘 이미 발송했으면 같은 날 새 PC에서 수동 발송하지 않는다. 중복 발송 가능성이 없는 다음 예약부터 새 PC의 발송 여부를 켠다. 그룹 발송 잠금은 별도 회사 IT·보안 확인과 사용자 승인 전에는 풀지 않는다.
3. 새 PC에 문제가 있으면 먼저 새 PC 예약을 끄거나 해제하고 실행 중인 회차가 끝났는지 확인한다. 기존 PC 예약을 다시 사용할 때는 그날 양쪽 발송 이력을 먼저 확인하고 재등록 범위를 별도 승인한다. 한쪽만 실제 발송하게 한다.
4. 복원 실패·데이터 오류가 있으면 실행을 멈추고 백업과 *_before_restore_시각 폴더를 보존한다. 경로·데이터를 임의 삭제하거나 DB를 초기화하지 않는다. 중단 전에 발송된 메일은 취소된다고 보장하지 않는다.
5. 전환 확인 뒤 회사 정책에 따라 백업·기존 개인정보·Secret을 정리한다. uninstall은 data·config·환경 변수·백업을 모두 지워 주지 않는다. 두 PC가 같은 키를 사용한다면 정리 과정에서 운영 중인 키를 폐기하지 않도록 구분한다.

## 확인 상태

실행 파일 빌드·임시 사본 오프라인 명령 결과는 DEVELOPMENT_STATUS.md의 이번 기록을 따른다. 새 PC 설치·로그아웃 무인 인증·실제 수집/AI/메일은 별도 사용자 확인 대상이다. 사용자 승인 없이 이 PC 작업 스케줄러·관리 페이지를 바꾸지 않는다.
