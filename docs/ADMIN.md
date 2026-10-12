# SABA 관리자 운영 문서

SABA(Security & AI Briefing Automation)를 운영하는 관리자를 위한 문서다.
현재 운영 방법(명령어 기준)과 향후 관리자 UI 도입 계획을 함께 기록한다.
결정 근거는 `harness/rules/DECISIONS.md` 의 D 번호를 따른다.

---

## 1. 전체 흐름

```
RSS 수집 → 같은 사건 묶음·선별 → AI 분석(요약·중요도) → AI 시사점·업무 연결
→ 메일 전용 HTML 생성 → 고정 TEST 수신자 발송
```

| 단계 | 담당 코드 | 저장 위치 |
|---|---|---|
| RSS 수집 | `python -m saba --collect-rss` | `data/saba.db` |
| 보호나라 공지 본문 | `src/saba/notice_body.py` | `data/boho_bodies.json` |
| AI 분석 | `src/saba/openai_adapter.py`, `src/saba/briefing.py` | `data/analysis.db` |
| AI 시사점·업무 연결 | `src/saba/insights.py` | `data/insights.db` |
| 메일 생성 | `src/saba/mail.py`, `templates/newsletter_mail.html` | `output/daily_YYYYMMDD.eml` |
| 발송 | `src/saba/send_mail.py` | (발송 기록은 로그) |
| 매일 실행 | `src/saba/daily.py` | `logs/daily_YYYYMMDD.log` |

`data/`, `logs/`, `output/daily_*.eml` 은 Git 에 포함되지 않는다.

---

## 2. 자주 쓰는 명령

모든 명령은 프로젝트 폴더에서 프로젝트 Python 으로 실행한다.

```
.venv\Scripts\python.exe -m saba.daily --run          # 오늘 분량 실행 (수집 → 분석 → 메일 → 발송)
.venv\Scripts\python.exe -m saba.daily --register     # 작업 스케줄러 등록 명령 확인 (등록하지 않음)
.venv\Scripts\python.exe -m saba.daily --register --apply   # 작업 스케줄러에 실제 등록·갱신 (승인 후)
.venv\Scripts\python.exe -m saba.send_mail            # 발송 드라이런 (접속·발송 없음)
.venv\Scripts\python.exe -m saba.send_mail --send     # 최근 메일 .eml 을 TEST 수신자에게 1회 발송
.venv\Scripts\python.exe -m saba.admin                # 관리 컨트롤 페이지 시작 (브라우저가 열림, 11절)
.venv\Scripts\python.exe -m saba.admin --stop         # 관리 컨트롤 페이지 종료
.venv\Scripts\python.exe -m saba.deploy --backup      # data\·config\ 백업 zip (부서 PC 이전, docs/DEPLOY.md)
```

설치·이전·자동 실행 등록·제거는 `scripts\saba.ps1` 하나로 한다 (D-068, `docs/DEPLOY.md`).

작업 스케줄러 등록 상태 (2026-10-12 등록, D-063): 작업 이름 `SABA_Daily_Briefing`, 평일 08:00 + 최대 5분 지연.

작업 스케줄러 등록 상태 확인 (PowerShell):

```
Get-ScheduledTask -TaskName SABA_Daily_Briefing
```

---

## 3. 운영 설정 (`config/daily.json`)

| 항목 | 현재 값 | 설명 |
|---|---|---|
| `time` | `08:00` | 실행 시각 (HH:MM) |
| `random_delay_minutes` | `5` | 시작 시각에 더하는 최대 무작위 지연 (08:00~08:05 시작) |
| `weekdays` | 월~금 | 실행 요일 (MON~SUN) |
| `max_analysis_calls` | `20` | 하루 AI 분석 신규 호출 상한 |
| `max_insight_calls` | `20` | 하루 AI 시사점 신규 호출 상한 |
| `send` | `true` | `false` 면 메일만 만들고 발송하지 않음 |

시각·요일을 바꾼 뒤에는 `--register --apply` 를 다시 실행해야 작업 스케줄러에 반영된다.

---

## 4. 실패 처리 원칙 (D-061, D-062)

- 한 단계라도 실패하면 그날은 발송하지 않는다. 재시도하지 않는다.
- RSS Source 하나만 실패해도 발송하지 않는다 (엄격).
- 로그에는 단계, 건수, 오류 종류만 남긴다. 기사 내용과 Secret 은 남기지 않는다.
- 메일 발송 오류는 단계·오류 종류·SMTP 응답 코드·명령 응답 순서만 표시한다.

로그 예시 (`logs/daily_YYYYMMDD.log`):

```
INFO RSS 수집 완료
INFO 메일 생성 완료: daily_20261012.eml · 표시 3건 · 분석 재사용 0 · 신규 4 · 실패 0 · ...
INFO 발송 완료 1회: 받는 사람 1명 · 메시지 ... bytes · 포트 465 SSL/TLS · ...
```

---

## 5. 비용·AI 설정 (D-013~D-016)

| 항목 | 값 |
|---|---|
| Provider / Model | OpenAI / gpt-4o-mini |
| 월 비용 상한 | $3 (로컬 사용량 기록 `data/openai_usage.json` 으로 사전 차단) |
| 하루 호출 상한 | 분석 20건 + 시사점 20건 (예상 $0.02 미만) |
| 전송 데이터 | 기사 제목·RSS 발췌 (보호나라 공지는 본문 앞부분) |

---

## 6. 수집 Source

| ID | 이름 | 비고 |
|---|---|---|
| `cert-eu-security-advisories` | CERT-EU | 공식 |
| `boho-security-notice` | KISA 보호나라 | 공식, 국내, 날짜만 제공 |
| `cisa-cybersecurity-advisories` | CISA | 공식 |
| `the-hacker-news` | The Hacker News | 언론 |
| `boannews` | 보안뉴스 | 언론, 국내 |
| `boho-report-guide` | KISA 보호나라 보고서·가이드 | 공식, 국내, 날짜만 제공 |

브리핑 대상 기간은 실행 시각 기준 최근 24시간 (날짜만 제공하는 Source 는 48시간) 이다.
월요일(KST)은 주말 기사를 포함해 48시간을 더한다 (72시간, 날짜만 제공 Source 96시간, D-063).
따라서 실행 날짜마다 메일 내용이 다르다.

선별 상한: Source 당 5건, 국내·해외 섹션 각 10건 → 보안 심층 뉴스는 하루 최대 20건이다.
오늘의 브리핑 분야는 보안 뉴스·테크(Tech)·보안시장 동향만 채워진다
(일정·핫이슈·기업 소식·경제 지표는 분류 기준과 데이터 출처가 아직 없다).

---

## 7. 메일 (회사 메일: 한비로메일)

- SMTP: 포트 465, SSL/TLS, AUTH PLAIN (자동 인증 방식 선택은 서버 응답 어긋남으로 사용하지 않음, D-050)
- 보낸 사람·받는 사람: 서명 주소 1명으로 고정 (Cc·Bcc 금지)
- 한비로메일 웹메일 제약 (D-057 진단): script·style 블록 제거, 접기·펼치기 불가, 메일 안 이동 링크 불가, 외부 링크만 동작
- 그래서 메일은 780px table 레이아웃, 간략 보기만 표시, 버튼은 기사 원문 링크로 구성한다 (D-054~D-059)

### Secret (환경 변수, Windows 사용자 환경 변수)

| 이름 | 내용 |
|---|---|
| `OPENAI_API_KEY` | OpenAI API Key |
| `SABA_SMTP_HOST` | SMTP 서버명 |
| `SABA_SMTP_USER` | SMTP 아이디 (메일 주소의 @ 앞부분) |
| `SABA_SMTP_PASSWORD` | 웹메일 비밀번호 |

값은 코드·로그·문서·대화·Git 에 기록하지 않는다. 바꾼 뒤에는 실행 프로그램(VS Code, 작업 스케줄러 대상) 을 다시 시작해야 반영된다.

---

## 8. 알려진 제한과 확인 사항

- 한비로메일 32일 미로그인 시 SMTP 비활성화 안내가 있다. 웹메일에 주기적으로 로그인한다.
- 작업 스케줄러는 이 PC 가 켜져 있어야 실행된다.
- 중요도(긴급·중요·참고) 는 AI 판단이며 구체 등급 기준은 아직 정의되지 않았다.
- 부서별 업무 연결 대상: 경영전략팀, 기술개발연구소, 보안사업팀, STE본부 (STE본부 범위는 D-063 에서 사용자 제공).
- 작업 스케줄러 작업(SABA_Daily_Briefing) 은 사용자가 로그인해 있을 때만 실행된다.

---

## 9. 관리자 UI 도입 계획 (D-062, 구현은 별도 승인)

### 목적

SABA 의 주요 기능을 터미널 명령어 없이 관리한다.
관리자 UI 는 Core Pipeline 을 새로 구현하지 않고, 기존 Python 기능을 관리·제어한다.

### 기능 후보

**대시보드**
- 시스템 실행 상태, 자동 실행 ON/OFF, 마지막 실행 일시
- 최근 뉴스 수집 건수, AI 처리 성공·실패 건수
- 뉴스레터 생성 결과, 메일 발송 결과

**뉴스 및 AI 분석 관리**
- 수집 기사 목록, Source 별 수집 현황
- AI 분석 결과 조회, 중요도 확인, 관련 부서 확인, 시사점 확인

**뉴스레터 관리**
- HTML 뉴스레터 미리보기, 최근 생성 뉴스레터 조회, TEST 발송 전 내용 확인

**메일 발송 관리**
- TEST 메일 발송, TEST 수신자 확인, 발송 전 확인 절차
- 최근 발송 이력, 발송 성공·실패 확인
- 실제 전사 발송은 별도 승인 및 권한 통제를 적용한다

**스케줄 관리**
- 실행 시간·요일 변경, 자동 실행 ON/OFF
- 스케줄러 등록 상태 확인, 수동 실행
- 설정 저장 및 실제 스케줄러 반영 상태 확인

**로그 및 운영 상태**
- 뉴스 수집·AI 분석·뉴스레터 생성·메일 발송 로그
- 오류 발생 단계 및 원인 종류, 최근 실행 이력

**시스템 설정**
- AI Provider·Model 확인, AI 호출 상한 확인
- 월 AI 사용량 및 예상 비용 확인
- RSS Source 목록 및 상태 확인, 운영 설정 확인

### 원칙

- Secret 값은 관리자 UI 에 노출하지 않는다 (존재 여부만 표시).
- UI 의 모든 실행·발송·설정 변경은 위 명령과 같은 코드 경로를 사용한다.
- 현재 기능과의 대응: 대시보드·로그는 `logs/`, `data/openai_usage.json`, 스케줄은 `config/daily.json`·`--register`, 발송은 `send_mail`.

---

## 10. 운영 로드맵 (D-065, 순서 변경 D-070)

현재는 본인(고정 TEST 주소) 대상 TEST 운영이다. 추후 본사 전 인원에게 발송한다.
기능과 관리 컨트롤 페이지를 먼저 완성하고, 설치 패키지와 부서 PC 이전은 마지막에 한다 (D-070). 각 단계는 별도 승인 후 진행한다.

| 단계 | 내용 | 완료 기준 |
|---|---|---|
| 1. 관리 컨트롤 페이지 1단계 (완료, D-067) | 대시보드, 로그, 메일 미리보기, 기능별 테스트, 자동 실행 ON/OFF, 메일 로고 축소본 | 터미널 없이 상태 확인·테스트 가능, 메일 크기 축소 |
| 2. 기능 완성·테스트·관리 컨트롤 페이지 확장 (현재) | 남은 기능 구현과 품질 개선, 관리 페이지에 수동 실행·실행 시각 변경·수신자·그룹 관리·발송 전 미리보기와 승인·파일럿 발송·발송 이력·관리자 로그인과 권한 | 모든 운영 기능을 관리 페이지에서 사용·확인 가능, 파일럿 그룹 정상 운영 |
| 3. 설치·실행·종료·삭제 패키지와 부서 PC 이전 | 패키지 (설치, 실행, 종료, 자동 실행 등록·해제, 데이터 이전, 삭제), 설치 문서, 로그인 없이 실행, 놓친 실행 보완, 기존 PC 작업 해제 | 패키지로 새 PC 설치·실행 가능, 부서 PC 평일 자동 실행 1주 무사고 |
| 4. 본사 전 인원 발송 | 전체 수신자 그룹 발송 (별도 승인) | 회사 IT·보안 정책 확인 완료 |

패키지 초안 (D-068, D-069) 은 보관만 하고 3단계에서 다시 검토한다: `scripts/saba.ps1`, `src/saba/deploy.py`, `scripts/build_exe.ps1`, `scripts/saba_entry.py`, `docs/DEPLOY.md`. 그 전까지 추가 작업은 하지 않는다.

### 전사 발송 전에 확인할 것

- 회사 IT·보안 정책: 자동 발송 허용, 발신 계정 (개인 계정 또는 부서 공용 계정), 수신자 목록 관리 주체
- 한비로메일 제한: 1회 발송 수신자 수, 하루 발송량, 메일 크기 (현재 약 1.4MB, 로고 원본 약 0.9MB → 축소본 적용 예정, D-066)
- 발송 방식: 개별 발송 또는 사내 배포 그룹 주소 1개로 발송 (배포 그룹 사용 시 발송량·크기 부담이 작다)
- 수신 거부·의견 회신 처리 방법
- 개인정보: 수신자 목록(이름·메일 주소) 의 보관 위치와 접근 권한

### 관리 컨트롤 페이지 범위 (1·2단계, D-070)

- 1단계 (운영 상태): 실행 상태·이력, 단계별 결과, 비용, 로그, 메일 미리보기, 기능별 테스트, 자동 실행 ON/OFF
- 2단계 (기능 완성·전체 발송 관리): 수신자·그룹 관리, 발송 대상 선택 (TEST·파일럿·전체), 발송 전 미리보기와 승인 버튼, 발송 이력·성공·실패·재발송 기록, 관리자 로그인과 권한 (관리자·조회자)
- 공통 원칙: Secret 은 표시하지 않음 (있음·없음만), 전체 발송은 승인 절차 없이 실행되지 않음, 모든 동작은 기존 명령과 같은 코드 경로 사용
- 접속 범위: 부서 PC 운영 시 사내망 접속을 허용하면 로그인과 접속 IP 제한을 적용

### 메일 로고 크기 (D-066)

- 원본 `SAMPLE/Codex/v09/LOGO.png` (1426×1103, 약 0.9MB) 는 수정하지 않는다.
- 메일에는 표시 크기(62px) 의 2배 정도(약 124px 폭) 로 줄인 별도 파일을 CID 로 첨부한다.
- 적용 (D-067): `templates/logo_mail.png` (124×96, 약 10KB). 같은 날 같은 기사 3건 기준 메일 .eml 1,346,920 → 91,587 bytes.

### 설치·실행 패키지 (D-066, 3단계로 변경 D-070)

부서 PC 등 새 PC 로 옮길 때 명령어 없이 설치·실행·종료할 수 있게 한다.

| 기능 | 내용 |
|---|---|
| 설치 | Python 환경(.venv) 구성, 의존성 설치, 폴더 준비, 환경 변수 4개 존재 확인 (값은 사용자가 직접 입력) |
| 관리 페이지 | 시작·종료 (바탕화면 바로가기 등) |
| 자동 실행 | 작업 스케줄러 등록·해제, 상태 확인 |
| 데이터 이전 | 기존 PC `data/` 백업·복원 |
| 제거 | 작업 해제 후 프로그램 제거 (데이터는 선택 보관) |

결정 (D-068, D-069): 스크립트와 실행 파일 패키징 둘 다. 스크립트 `scripts\saba.ps1`, 실행 파일 묶음 `scriptsuild_exe.ps1` → `dist\SABA\` (PyInstaller 한 폴더 형태, Python 설치 불필요). 절차와 회사 IT·보안 정책 확인 목록은 `docs/DEPLOY.md`.

---

## 11. 관리 컨트롤 페이지 1단계 (D-067)

이 PC 에서만 여는 로컬 웹 페이지다. 새 패키지 없이 표준 라이브러리로 동작한다.

```
.venv\Scripts\python.exe -m saba.admin          # 시작: http://127.0.0.1:8765/ 이 브라우저로 열린다
.venv\Scripts\python.exe -m saba.admin --stop   # 종료 (실행 창에서 Ctrl+C 도 가능)
```

- 접속 설정 `config/admin.json` (`host`, `port`). 1단계는 `127.0.0.1`·`localhost` 만 허용하고 다른 값이면 시작하지 않는다. 사내망 접속은 로그인·IP 제한 구현 후 별도 승인 (D-070).
- 실행 중 표시: `data/admin.pid` (종료 시 삭제).

| 화면 | 내용 |
|---|---|
| 대시보드 | 마지막 실행 로그와 결과, 최근 24시간 수집 건수, 이번 달 AI 호출·상태·비용·상한, 발송 대상 (TEST 1명), 작업 스케줄러 상태·마지막 결과·다음 실행 |
| 실행 이력·로그 | `logs/daily_*.log` 목록과 내용 |
| 뉴스레터 | `output/daily_*.eml` 목록과 메일 HTML 미리보기 (첨부 이미지 포함) |
| 설정 | `config/daily.json` 과 검증 결과, RSS Source, Secret 4개 있음·없음 (값 미표시), 발송 수신자 |
| 수신자·발송 관리 | 2단계 예정 (비활성, D-070) |

| 버튼 | 외부 접속 | 동작 |
|---|---|---|
| 메일 발송 드라이런 | 없음 | 최근 .eml 로 `send_mail` 드라이런 (접속·발송 없음) |
| 설정 검증 | 없음 | `config/daily.json` 검증 |
| 메일 미리보기 재생성 | 없음 | 저장된 분석·시사점만으로 `output/daily_YYYYMMDD_preview.eml` 생성 (OpenAI 호출·본문 가져오기 없음) |
| RSS 수집 dry-run | 있음 (확인 창) | `--collect-rss --dry-run` (DB 저장 없음) |
| SMTP 연결·인증 확인 | 있음 (확인 창) | 연결과 AUTH PLAIN 235 확인 후 종료 (메일 발송 없음) |
| 자동 실행 켜기·끄기 | 없음 | `Enable-ScheduledTask` / `Disable-ScheduledTask` |

- 보호 장치: 요청 Host 가 127.0.0.1·localhost 가 아니면 거부, 버튼 요청은 페이지마다 새로 만든 토큰 필수, 외부 접속 버튼은 확인 값 필수, 오류는 종류만 표시.
- 수동 실행 (실제 수집·AI 호출·발송) 과 실행 시각 변경 저장은 2단계 이후.
