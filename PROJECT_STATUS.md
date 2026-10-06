# SABA 진행 상태

최종 확인일: 2026-10-06 / 현재 작업: 8단계 프롬프트 검토·개선

## 지금 어디까지 됐는가

| 단계 | 종류 | 상태 | 확인할 산출물 |
|---|---|---|---|
| 2 Python 실행 골격 | 구현 | 완료 | pyproject.toml, src/saba/__main__.py |
| 3 기사 Schema·JSON 검증 | 구현 | 완료 | schema.py, test_schema.py, news_valid.json |
| 4 SQLite 저장·조회 | 구현 | 완료 | storage.py, test_storage.py |
| 5 Source 조사 | 조사·설계 | 완료 | 세션 조사 결과, SABA_NEWS_SOURCES.md는 후보 문서 |
| 6 CERT-EU RSS 수집 | 구현 | 완료 | rss.py, test_rss.py, cert_eu_rss.xml |
| 7 분석·분류 기준 | 설계 | 완료 | 사용자 승인 MVP 기준, 아래 결정 기록 |
| 8 분석 결과 형식·오프라인 검증 | 구현 예정 | 미착수 | NEXT_STEP_PROMPT.md는 실행할 요청 문서이며 구현물이 아님 |

현재 코드로 되는 일: 기본 실행, 기사 JSON 검증, SQLite 저장·조회, CERT-EU RSS 메타데이터 수집.
현재 코드로 안 되는 일: AI 분석, 분석 결과 검증 CLI, 본문 수집, 뉴스레터 생성, 메일 발송, Scheduler.
7단계에서 코드가 바뀌지 않은 이유: 사용자 승인 범위가 조사·설계만이었음.
전체 프로젝트의 완료 비율은 정의된 최종 범위가 없으므로 임의로 계산하지 않는다.

## 결정과 미확정

- 승인 Source: CERT-EU Security Advisories 한 개.
- 수집: 24시간 / 최초 검증 30일 / 복구 6시간 겹침·최대 7일 / 요청 1회 / 최대 30건 / 2MiB / 소켓 타임아웃 15초 / 재시도 없음.
- 저장: 최초 수집 시각·전체 기존 정보 유지, 동일 생략, 변경 충돌·입력 전체 보류, DB 실패 Rollback.
- 분석 MVP: 주분류 6개·주분류 1개·태그 최대 5개, 중요도 3단계 또는 미평가, 출처 귀속 요약 2문장·300자 이하, 핵심 사실 최대 3개, 업무 미확인 부서 미배정, 사람 검토.
- 다음 범위 선택: 8단계 오프라인 검증. 프롬프트 입력 또는 명시적 실행 승인 전 구현하지 않음.
- 미확정: 영구 분석 저장 방향, AI 제공자·모델·비용·API, 부서 업무, 발송 정책.

## 검증 근거

- 2026-10-06 현재 문서 개선 작업에서 전체 unittest 67개 통과, 종료 코드 0.
- 이전 6단계 실제 연결: Feed 요청 2회, 최초 검증용 4건 임시 저장·별도 프로세스 조회 성공, 24시간 정상 0건. 이번에 재요청하지 않음.
- 현재 디자인: v09/layout_review_v9.html → 같은 폴더 style_review_v9.css, LOGO.png.
- 이번 문서 개선 작업의 기존 코드·테스트·규칙·원본 등 52개 파일 목록·SHA-256 비교: 일치.
- 이번 변경은 PROMPT_VALIDATION.md, PROJECT_STATUS.md, NEXT_STEP_PROMPT.md 세 문서 생성뿐.
- 8단계 신규 기능 검증과 실제 AI 품질 평가는 미수행.

## VS Code에서 직접 확인

프로젝트 루트의 PowerShell에서 실행한다. 아래 명령은 외부 Source에 요청하지 않는다.

```powershell
git status --short
.\.venv\Scripts\python.exe -X utf8 -m saba --help
.\.venv\Scripts\python.exe -X utf8 -m saba
.\.venv\Scripts\python.exe -X utf8 -m saba --validate-json tests/fixtures/news_valid.json
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -v
```

현재 --help에 --collect-rss는 있고 --validate-analysis는 없다.
8단계 완료 후에는 --validate-analysis, analysis.py, test_analysis.py와 실제 검증 결과가 있어야 한다.
Git 변경은 작업 여부를 보여줄 뿐 성공을 증명하지 않는다. 실행 결과·테스트·원본 비교를 함께 확인한다.

## 매 단계 보고 방식

시작: 현재 단계·구현/설계 여부·목표·허용 변경·미승인 항목.
진행: 확인한 사실·완료한 작업·남은 작업·장애를 60초 이내 간격으로 간결히 알림.
종료: 실제 생성·수정 파일, 명령·출력·종료 코드, 기존/신규 테스트, Mock/실제 연결 구분, 원본·Git 확인, 미완료, 다음 승인 대상을 기록.
체크리스트만 체크하지 말고 파일·명령·결과 근거를 붙인다.
실패·미실행은 완료로 표시하지 않는다. 미래 기능은 예정으로 표시한다.
