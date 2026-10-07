# SABA DEVELOPMENT STATUS

## 목적
SABA의 실제 구현 상태와 다음 작업을 저장소 기준으로 추적한다. 작업 시작 전 `PROJECT_RULES.md`, `harness/` 아래의 모든 규칙 파일, 현재 작업 경로에 적용되는 `AGENTS.md`를 읽고 적용한다.

## 현재 확인된 상태
### 현재 단계와 승인 상태
- 공식 개발 단계: 17단계 — 추가 Source 수집 (D-023~D-025)
- 17단계 구현: `src/saba/rss.py` Source 설정 표 (CERT-EU, KISA 보호나라 보안공지, CISA Advisories, The Hacker News, 보안뉴스). 시간대 없는 pubDate는 Source 설정의 한국 시간 기준 해석, 날짜만 있는 Source(보호나라)는 기본 수집 기간 48시간. `--collect-rss` 전체 Source 수집, Source별 실패·충돌 격리, `--source` 필터
- 17단계 첫 실제 저장 수집 (2026-10-07, `--collect-rss --bootstrap`, `data/saba.db` 신규): 5개 Source 모두 성공, 105건 저장 (CERT-EU 5, 보호나라 10, CISA 30, The Hacker News 30, 보안뉴스 30), 발행 시각 미확인 0건. The Hacker News·보안뉴스는 Source별 최대 30건 상한으로 각 20건 제외
- 17단계 검증: unittest 216개 중 215개 통과, 1개 Skip, 실패 0개. 테스트는 가상 Fixture 사용
- 17단계 후속 공식 RSS 묶음 (D-026): KISA 보호나라 보고서·가이드 채택 (승인 Source 6개). 취약점 정보는 게시 빈도 낮아 미채택, MSRC(2MiB 초과)·Google Security Blog(Atom)는 현재 구조로 수집 불가, Intel·AMD·NVIDIA는 공식 RSS 미확인. 검증: unittest 217개 중 216개 통과, 1개 Skip
- 같은 사건 중복 처리 (D-027): `src/saba/issues.py` group_issues() 순수 함수. CVE 공유 자동 묶음, 제품 키워드 + 3일 이내 후보 표시 (사람 확정), 요약 기사 제외, 공식 출처 우선 대표 기사. Source 설정에 official 표시 추가. 저장 기사 105건 기준 이슈 102개, 자동 묶음 3개, 후보 5쌍. Newsletter 반영·사람 확정 결과 보관은 미구현. 검증: unittest 227개 중 226개 통과, 1개 Skip
- 다음 작업 (D-028): 실제 수집 기사로 비AI Newsletter Preview 연결. 선별 규칙 설계안 제시, 구현은 설계 확정 후
- Source 이용 조건(재배포·요약 사용 범위)은 미확인. 기사 본문 수집은 하지 않으며 RSS 메타데이터와 Feed 제공 발췌만 저장
- 16단계: OpenAI API 실제 연결 및 TEST 호출 검증 (형식 기준 완료)
- 12단계 기록: Newsletter Template 및 Preview 완료 승인 (D-011). 실제 이메일 호환성·발송 검증 완료를 의미하지 않음
- 13~15단계: 선택적 AI 보강 계층 설계, Provider 독립 오프라인 어댑터와 Mock 검증 (`src/saba/ai_adapter.py`), Provider·Model·비용·데이터·TEST 범위 결정 (D-013~D-017)
- 16단계 구현: `src/saba/openai_adapter.py` (stdlib urllib, Responses API, gpt-4o-mini 고정, Structured Output strict, store=false, 재시도 없음), 사용량 기록 `data/openai_usage.json`, 월 $3 로컬 방어선, 변환 실패 진단 detail·quote_occurrences (기사 내용 미기록)
- 16단계 실제 호출: 가상 Fixture 기사 5건, 누적 10건 (D-017 5건, D-018 4건, D-019 1건), 비용 약 $0.0036 (코드 단가 기준). 보완 3회 후 5건 모두 AnalysisResult v1 변환 성공
- 16단계 검증: 2026-10-07 HEAD 753834e 기준 unittest 199개 중 198개 통과, 1개 Skip (실제 호출 테스트), 실패 0개
- 16단계 후속 품질 기준 (D-022): 근거 다양성 경고 (거절 없음, 사람 검토), 지시문 category 정의, importance 기사 사실 판단 규칙, 실제 호출 테스트 상한 환경변수 SABA_OPENAI_LIVE_MAX_CALLS
- 주입 대조 실험 (D-021): 006 원본 importance "높음", 주입 문장 제거본 "보통" (1회 비교). 주입 영향 가능성 있음. AI importance는 참고값이며 Newsletter 반영 전 사람이 확정
- 실제 호출 누적 12건 (D-017~D-019, D-021), 비용 약 $0.0048 (코드 단가 기준)
- 남은 품질 검토: 근거 의미 일치는 사람 검토, importance 지시문 강화 효과와 005 category 정의 효과는 실제 호출로 미검증. 형식 검증 통과는 분석 품질 승인을 의미하지 않음

### 완료/구현 확인
- Python 실행 골격
- 공통 Article Schema 및 JSON 검증
- SQLite 저장·조회
- Source 조사 및 수집 구조 설계
- CERT-EU Security Advisories RSS 수집 코드
- 다중 Source RSS 수집 (17단계, 승인 Source 5개)
- RSS 재수집 동일 원문 생략 및 변경 충돌 방지 구조
- Newsletter HTML Renderer·동적 Template과 SAMPLE Preview 구현 및 사용자 Preview 승인. 운영 발행 기능 완료를 의미하지 않음
- AI 분석 결과 Schema/검증 구조
- 합성 분석 결과의 별도 SQLite 저장·읽기 전용 조회 (`data/analysis.db`)
- 정규화 Analysis Input Snapshot 저장 및 Hash·출처·근거 위치 재검증
- 동일 분석 결과 생략 및 최초 저장 시각 유지
- 동일 입력의 다른 분석 결과 이력 보관 (기존 결과 불변)
- 분석 저장 전체 입력 Transaction/Rollback 및 기사 DB 읽기 전용 검증
- 분석 저장·조회 CLI: 합성 결과 3건 저장, 재입력 3건 생략, 다른 결과 1건 추가와 별도 프로세스 조회 확인
- 2026-10-07 검증: Python 3.12.14에서 unittest 전체 112개 통과. 임시 DB만 사용했고 실제 AI API는 호출하지 않음

### 현재 AI 상태
- 승인: Provider OpenAI (D-013), Model gpt-4o-mini (D-014), 월 최대 $3 (D-015), 전송 데이터 original_title + feed_excerpt만 (D-016), TEST·보완 호출 누적 10건 (D-017~D-019, 모두 소진)
- 실제 호출은 가상 Fixture 기사로만 수행했다. 실제 운영 기사 AI 분석, 분석 결과 DB 저장, Newsletter 반영은 미승인이다.
- 추가 실제 호출은 건별 사용자 승인이 필요하다. extracted_text 전송과 다른 모델 사용은 미승인이다.
- API Key는 환경변수 `OPENAI_API_KEY`로만 읽으며 코드·로그·사용량 기록에 남기지 않는다.
- Article 수집·정규화·저장은 AI와 독립적이다. AI는 선택적 보강 계층이며 AI 없이도 가능한 Core Pipeline 완성을 목표로 한다.
- 기존 Analysis Schema·검증·Storage·관련 테스트와 Fixture는 보존한다.

### 미구현/별도 승인 대상
- 실제 운영 기사 AI 분석 및 결과 저장·Newsletter 반영
- AI 분석 품질 기준 실제 효과 검증 (importance 주입 저항 반복 실험, category 정의 효과) 및 importance 사람 확정 절차 설계
- 추가 Source 확대 (순서: 공식 RSS 묶음 → 언론 묶음(중복 처리 설계 후) → 공식 데이터 API(CISA KEV, NVD), D-025)
- 필요한 Source의 Web Crawling
- 사건 단위 중복 통합
- 관련 부서 자동 분류
- 최종 뉴스레터 분석 필드 확정
- Newsletter 실제 이메일 호환성 검증 및 운영 발행 정책
- 회사 메일 연동 및 TEST/PRODUCTION 모드
- Scheduler
- 관리자 UI
- 서버/Cloud 배포
- 운영 ON/OFF 및 운영 로그 화면
- 최종 운영 DB 구조 및 DB 제품 선정
- 운영 로그 / 실행 이력 저장 구조
- 데이터·로그 보관 / Archive 정책
- DB Backup / Restore 정책

## 수집 구조 원칙
Source와 Newsletter Category를 분리한다.

Core Pipeline 목표: 승인 Source → 수집 → 공통 Article 정규화 → 저장 → 승인된 비AI 처리 → Newsletter 생성 → Mail 발송 → Scheduler

AI 분석·분류는 선택적 보강 경로다. Newsletter HTML 생성과 AI 없는 fallback은 구현됐고 Preview 사용자 승인을 받았다. 운영 기사 선별·Mail·Scheduler는 아직 구현되지 않았으며, AI 장애 격리도 현재는 설계 원칙이다. 원본에 없는 요약·중요도·부서·시사점 등을 임의 생성하지 않는다.

특정 Source를 특정 Newsletter Category에 1:1로 고정하지 않는다.
`SABA_NEWS_SOURCES.md`에 존재한다는 사실만으로 구현 또는 네트워크 접근이 승인된 것은 아니다.

## 운영 방향
최종 자동 실행은 사용자의 개인 PC가 아니라 24시간 동작 가능한 서버/Cloud 환경에서 수행한다.

향후 관리자 UI 목표:
- 시스템 상태 및 자동 실행 ON/OFF
- 발송 시간 변경
- TEST / PRODUCTION 모드
- 테스트 수신자 설정
- 수동 실행 및 테스트 메일
- Newsletter Preview
- 최근 실행 결과 및 로그

관리 UI 구현 방식과 배포 방식은 별도 설계·사용자 승인 후 확정한다.

## 단계 관리 원칙
1. 새 단계 시작 전 실제 Git 상태와 기존 테스트를 확인한다.
2. 완료된 기능을 단계 번호 때문에 다시 구현하지 않는다.
3. 설계 → 구현 → 실행 → 결과 확인 → 수정 → 사용자 확인 순으로 진행한다.
4. 각 단계는 `harness/` 아래의 모든 규칙 파일을 읽고 현재 작업에 관련된 범위에서 적용한다.
5. 필수 테스트 실패를 숨기거나 다음 단계로 넘어가지 않는다.
6. 단계 완료 후 실제 검증 결과에 맞는 문서 갱신안을 제시하고 사용자 승인 후 반영한다.
7. 다음 단계 프롬프트 작성 자체는 다음 단계 실행 승인이 아니다.
