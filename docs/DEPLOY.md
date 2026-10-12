# SABA 부서 PC 설치·이전 절차 (D-068)

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

실행 파일 패키지 (Python 설치 없이 실행, D-068 B) 는 다음 단계에서 설계·승인 후 추가한다.
