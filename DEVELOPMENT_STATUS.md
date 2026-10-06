# SABA DEVELOPMENT STATUS

## 목적
SABA의 실제 구현 상태와 다음 작업을 저장소 기준으로 추적한다. 작업 시작 전 `PROJECT_RULES.md`, `TESTING_RULES.md`와 함께 확인한다.

## 현재 확인된 상태
### 완료/구현 확인
- Python 실행 골격
- 공통 Article Schema 및 JSON 검증
- SQLite 저장·조회
- Source 조사 및 수집 구조 설계
- CERT-EU Security Advisories RSS 수집 코드
- RSS 재수집 동일 원문 생략 및 변경 충돌 방지 구조
- AI 분석 결과 Schema/검증 구조

### 현재 AI 상태
- `analysis.py`는 실제 AI API 호출 기능이 아니다.
- 현재는 합성 분석 결과의 형식, 입력 연결, 근거 연결을 검증하는 구조다.
- 실제 AI Provider/API 연결, 실제 기사 분석 실행 및 저장은 별도 승인 대상이다.

### 미구현/별도 승인 대상
- 실제 AI API 연결
- 추가 Source 수집
- 필요한 Source의 Web Crawling
- 사건 단위 중복 통합
- 관련 부서 자동 분류
- 최종 뉴스레터 분석 필드 확정
- 동적 Newsletter Template
- 회사 메일 연동 및 TEST/PRODUCTION 모드
- Scheduler
- 관리자 UI
- 서버/Cloud 배포
- 운영 ON/OFF 및 운영 로그 화면

## 수집 구조 원칙
Source와 Newsletter Category를 분리한다.

여러 승인 Source → 수집 → 공통 Article Schema → 정규화/중복 판단 → AI 분석·분류 → 뉴스레터 Category 배치 → 중요 기사 재선별 → Newsletter 생성

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
4. 각 구현 단계는 `TESTING_RULES.md`를 반드시 적용한다.
5. 필수 테스트 실패를 숨기거나 다음 단계로 넘어가지 않는다.
6. 단계 완료 후 실제 검증 결과에 맞는 문서 갱신안을 제시하고 사용자 승인 후 반영한다.
7. 다음 단계 프롬프트 작성 자체는 다음 단계 실행 승인이 아니다.
