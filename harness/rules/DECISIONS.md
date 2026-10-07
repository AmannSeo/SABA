# SABA DECISIONS

사용자 결정과 승인 상태를 기록하는 파일이다.
`harness/rules/PROMPT_VALIDATION.md` 5절은 **이 파일의 `approved` 항목**과
현재 프롬프트에 적힌 사용자의 최신 결정만 승인으로 인정한다.

## 규칙

- 사용자가 결정하고 기록을 승인한 내용만 `approved` 로 적는다.
- 제안, 추천, 후보는 `proposed` 로 적는다. `proposed` 는 승인이 아니다.
- 결정이 바뀌면 기존 항목을 지우지 않고 `superseded` 로 바꾸고, 새 항목을 추가한다.
- ID 는 한 번 정하면 바꾸지 않는다.

상태 값: `approved` / `proposed` / `rejected` / `superseded`

## 기록

| ID | 날짜 | 결정 내용 | 상태 | 근거 또는 비고 | 대체한 ID |
|----|------|-----------|------|----------------|-----------|
| D-001 | YYYY-MM-DD | (예시, 승인 아님) 실제 Mail 발송은 본인 주소로만 시험 발송 | proposed | 예시 행입니다. 실제 결정으로 교체하세요. | |
| D-002 | 2026-10-07 | 다음 개발 우선순위: 비AI Newsletter Template 먼저 구현. 추가 Source 수집은 이번 범위 제외. | approved | 사용자 결정 2026-10-07 | |
| D-003 | 2026-10-07 | 기사 요약 정책: feed_excerpt 있으면 표시, 없으면 요약 영역 미표시. extracted_text 앞 N자 자동 절단 요약 금지. Source 원문과 시스템 생성 내용 혼동 금지. | approved | 사용자 결정 2026-10-07 | |
| D-004 | 2026-10-07 | AI 미승인 상태에서 importance·departments·summary·implications·hook·why_read·context·newsletter_title 임의 생성 금지. AI 데이터 없어도 Newsletter 생성 자체는 가능해야 함. 빈 공간을 위해 가짜 AI 데이터 생성 금지. | approved | 사용자 결정 2026-10-07. AI_RULES.md 17절 동일 방향. | |
| D-005 | 2026-10-07 | 부서 분류 정책: 임의 부서 배정 금지. STE본 업무 범위 추측 금지. departments=[] 상태의 처리 방식은 설계 확정 후 구현. | approved | 사용자 결정 2026-10-07. PROJECT_RULES.md 10절 동일 방향. | |
| D-006 | 2026-10-07 | 중요도 정책: 비AI 중요도 판단 규칙 미승인. 임의 중요도 생성 금지. importance=None 상태의 처리 방식은 설계 확정 후 구현. | approved | 사용자 결정 2026-10-07 | |
| D-007 | 2026-10-07 | Newsletter Template 위치: templates/newsletter.html 신규 생성. SAMPLE/Codex/ 원본 직접 수정 금지. 작업 시작 시 최고 버전 폴더 재확인. 현재 기준 v09. | approved | 사용자 결정 2026-10-07. PROJECT_RULES.md 5-6절 적용. | |
| D-008 | 2026-10-07 | Newsletter 구현 순서: HTML Template 구현 전 비AI 데이터 및 표시 정책 확정 먼저. 사용자 결정 필요 항목은 선택지·추천·이유 제시 후 승인 대기. | approved | 사용자 결정 2026-10-07 | |