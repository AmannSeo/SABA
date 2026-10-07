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