# SABA DEVELOPMENT STATUS

## 목적
SABA의 실제 구현 상태와 다음 작업을 저장소 기준으로 추적한다. 작업 시작 전 `PROJECT_RULES.md`, `harness/` 아래의 모든 규칙 파일, 현재 작업 경로에 적용되는 `AGENTS.md`를 읽고 적용한다.

## 현재 확인된 상태
### 현재 단계와 승인 상태
- 공식 개발 단계: 12단계 — Newsletter Template 및 Preview
- 완료된 하위 작업: 12-C — v09 시각적 일치 및 Preview 오류 수정
- 12-C 구현·검증 기록: UTF-8 한글 보존, v09 기반 Template, 부서당 최대 3건, AI SAMPLE 및 비AI Preview 생성
- 직전 12-C 검증 기록: Newsletter 테스트 27개와 전체 unittest 139개 통과, 실패·오류·Skip 0개, 종료 코드 0. 현재 문서 갱신에서는 테스트를 다시 실행하지 않음
- 최신 사용자 결정: 추가 수정 없음. 수정 Preview 승인 및 공식 12단계 완료 기록 승인됨. 실제 이메일 호환성·발송 검증 완료를 의미하지 않음
- DEVELOPMENT_STATUS.md와 DECISIONS.md에 현재 결정 및 직전 검증 기록 반영은 사용자 승인됨
- 다음 공식 단계: 13단계 — OpenAI 선택적 AI 보강 계층 설계. 설계 프롬프트 작성만 승인됐으며 해당 단계 실행·API 구현·호출은 아직 미승인

### 완료/구현 확인
- Python 실행 골격
- 공통 Article Schema 및 JSON 검증
- SQLite 저장·조회
- Source 조사 및 수집 구조 설계
- CERT-EU Security Advisories RSS 수집 코드
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
- `analysis.py`는 실제 AI API 호출 기능이 아니다.
- 현재는 합성 분석 결과의 형식, 입력 연결, 근거 연결을 검증하는 구조다.
- 분석 결과 저장·조회 기능은 구현됐으며 현재 저장 검증은 합성 결과 기반이다.
- 실제 AI API는 연결하지 않았고 Provider/Model도 확정하지 않았다.
- 현재 승인 상태: AI Provider 미확정, AI Model 미확정, 유료 AI API 사용 미승인.
- 개인 비용 부담을 전제로 하지 않으며 무료 API를 우선 검토한다. 무료라는 이유만으로 사용을 승인하지 않는다.
- 회사 데이터 외부 전송 적합성은 확인이 필요하다. 이전 특정 Provider/Model 및 실제 연결 제안은 현재 실행 승인이 아니다.
- 실제 기사 AI 분석 실행과 그 결과의 저장은 별도 승인 대상이다.
- Article 수집·정규화·저장은 AI와 독립적이다. AI는 선택적 보강 계층이며 AI 없이도 가능한 Core Pipeline 완성을 목표로 한다.
- 실제 AI API 구현·호출은 미승인이다. 기존 Analysis Schema·검증·Storage·관련 테스트와 Fixture는 보존한다.

### 미구현/별도 승인 대상
- 실제 AI API 연결
- 추가 Source 수집
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
