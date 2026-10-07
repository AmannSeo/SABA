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
| D-009 | 2026-10-07 | 12-C 수정 Preview는 추가 수정한다. 공식 12단계 완료 승인 전이며 구체적인 수정 항목은 확인 대기한다. | superseded | 이후 추가 수정 없음 및 완료 기록 승인으로 D-011이 대체함. | |
| D-010 | 2026-10-07 | DEVELOPMENT_STATUS.md와 DECISIONS.md에 현재 결정 및 직전 12-C 검증 기록을 반영한다. | approved | 현재 세션 사용자 답변: 승인 기록 반영. 13단계 작성·실행 또는 실제 AI 호출 승인을 의미하지 않음. | |
| D-011 | 2026-10-07 | 추가 수정 없음. 수정 Preview 승인 및 공식 12단계 완료를 기록한다. | approved | 현재 세션 사용자 답변: 12단계 완료 기록·13단계 프롬프트 작성 승인. 실제 이메일 호환성·발송 검증 승인은 아님. | D-009 |
| D-012 | 2026-10-07 | 13단계 — OpenAI 선택적 AI 보강 계층 설계의 실행용 프롬프트를 작성한다. | approved | 프롬프트 작성만 승인. 단계 실행·Provider/Model 확정·API 구현·호출·비용·외부 기사 전송 승인은 아님. | |
| D-013 | 2026-10-07 | AI 분석 Provider: OpenAI. | approved | 사용자 결정 2026-10-07. 실제 API 호출·과금 승인은 아님. | |
| D-014 | 2026-10-07 | AI 분석 모델: gpt-4o-mini. 모델 변경 시 재승인 필요. | approved | 사용자 결정 2026-10-07. 실제 API 호출·과금 승인은 아님. | |
| D-015 | 2026-10-07 | 월 최대 API 비용 한도: $3/월. 한도 초과 시 API 호출 중단. 실제 한도 설정은 OpenAI 계정 대시보드에서 별도 구성. | approved | 사용자 결정 2026-10-07. | |
| D-016 | 2026-10-07 | AI API 전송 데이터 범위: 기사 제목(original_title) + RSS 발췌문(feed_excerpt)만. 전사 내부 정보·개인정보 포함 금지. OpenAI API 기본 정책: 학습 사용 안 함, 최대 30일 후 삭제. | approved | 사용자 결정 2026-10-07. extracted_text 포함 여부는 별도 승인 필요. | |
| D-017 | 2026-10-07 | 실제 API 연결 첫 TEST 호출 범위: 5건. 예상 비용 $0.001 미만. 이후 운영 호출은 별도 승인. | approved | 사용자 결정 2026-10-07. | |
| D-018 | 2026-10-07 | 16단계 보완 검증용 추가 실제 호출: fictional-live-005·006 2건을 2회 승인 (총 4건, D-017 포함 누적 9건). 모델 gpt-4o-mini, 전송 범위 D-016 동일. 모두 사용 완료. 이후 추가 호출은 별도 승인. | approved | 사용자 결정 2026-10-07 (보완 1회차·2회차 실행 중 승인). 누적 비용 약 $0.003. | |
| D-019 | 2026-10-07 | 16단계 보완 검증용 추가 실제 호출: fictional-live-006 1건 (누적 10건). 모델 gpt-4o-mini, 전송 범위 D-016 동일. 사용 완료. 005 category 품질 문제는 별도 품질 검토 작업으로 보류. | approved | 사용자 결정 2026-10-07 (보완 3회차 실행 중 승인). 누적 비용 약 $0.0036. | |
| D-020 | 2026-10-07 | AI Provider/Model 확장성 원칙: 현재 OpenAI와 gpt-4o-mini는 SABA MVP의 최초 실제 Provider/Model이며 영구적인 단일 Provider/Model 종속을 의미하지 않는다. SABA의 AI 공통 계층은 Provider 독립 구조를 유지하고, 향후 사용자 승인에 따라 다른 Provider/Model 추가, 역할 분담, Fallback, 복수 AI 결과 비교·검증 및 Multi-AI 구조로 확장할 수 있어야 한다. 새로운 Provider도 가능한 한 공통 AnalysisResult 계약을 사용하고 Provider별 차이는 Adapter 계층에서 처리한다. 현재 단계에서는 Multi-AI 기능을 구현하지 않으며 새로운 Provider/Model 추가 및 Multi-AI 실제 구현은 별도 사용자 승인이 필요하다. | approved | 사용자 결정 2026-10-07. 현재 MVP 범위를 확대하는 승인이 아니라 향후 확장성을 보호하는 아키텍처 원칙 승인. | |
| D-021 | 2026-10-07 | 프롬프트 주입 대조 실험용 추가 실제 호출 2건: fictional-live-006 원본 1건, 주입 문장 제거 가상 기사 fictional-live-006-control 1건 (누적 12건). 모델 gpt-4o-mini, 전송 범위 D-016 동일. 사용 완료. | approved | 사용자 결정 2026-10-07. 누적 비용 약 $0.0048. | |
| D-022 | 2026-10-07 | AI 분석 품질 기준: (1) 근거 대상 3개 이상이 모두 같은 인용 위치를 쓰면 "근거 다양성 낮음" 경고를 남기고 거절하지 않으며 사람이 근거 의미를 검토한다. (2) 지시문에 category 6개 정의를 추가한다 (Category 목록 유지). (3) 실제 호출 테스트는 환경변수 SABA_OPENAI_LIVE_MAX_CALLS로 승인 누적 건수를 명시해야만 실행한다. (4) AI importance는 참고값이며 Newsletter 반영 전 사람이 확정한다. 지시문에 importance는 기사 사실로만 판단하는 규칙을 추가한다. | approved | 사용자 결정 2026-10-07. 주입 대조 실험(D-021)에서 importance가 주입 문장 유무에 따라 달라진 1회 관찰에 근거. 반복 대조 실험은 운영 전환 전 별도 승인. | |
| D-023 | 2026-10-07 | 추가 Source 수집 설계: 다음 개발 방향은 추가 Source 수집. 채택 후보는 보호나라 보안공지, CISA Advisories, The Hacker News, 보안뉴스. 수집 구조는 rss.py를 Source 설정 표로 일반화 (Factory·Plugin 없음). 형식은 RSS 2.0 + UTF-8 유지, Atom·다른 인코딩은 별도 승인. --collect-rss는 승인 Source 전체 수집, 한 Source 실패 시 나머지 계속, --source 필터 제공. 형식 확인용 Feed GET 1회씩 승인 (저장 없음, 사용 완료). | approved | 사용자 결정 2026-10-07. 구현은 형식 확인 결과 보고와 최종 설계 승인 후. | |
| D-024 | 2026-10-07 | 17단계 — 추가 Source 수집. 1차 구현 Source: KISA 보호나라 보안공지, CISA Advisories, The Hacker News (CERT-EU 유지). 보호나라의 날짜만 있는 pubDate는 Source 설정으로 한국 시간 0시로 해석. 보안뉴스는 Feed 주소 확인 전까지 보류. CISA 긴 description은 그대로 저장하고 표시 길이는 Newsletter 단계에서 확인 (D-003 자동 절단 금지 유지). 테스트는 가상 Fixture 사용. 구현 후 승인 Source --dry-run 1회씩 (저장 없음). | approved | 사용자 결정 2026-10-07. | |
| D-025 | 2026-10-07 | 17단계 수집 규칙: 날짜만 있는 pubDate Source(보호나라)는 발행일을 한국 시간 0시로 두고 기본 수집 기간만 48시간으로 보정. 보안뉴스는 웹 검색 1회로 확인한 https://www.boannews.com/rss/allArticle.xml 을 GET 1회 확인(RSS 2.0·UTF-8·Redirect 없음)하여 채택, pubDate(YYYY-MM-DD HH:MM:SS)는 한국 시간으로 해석. 첫 실제 저장 수집 --collect-rss --bootstrap 1회 승인 (data/saba.db 신규). DEVELOPMENT_STATUS.md·SABA_NEWS_SOURCES.md 상태 갱신 승인. 다음 Source 확대 순서: 공식 RSS 묶음 → 언론 묶음(중복 처리 설계 후) → 공식 데이터 API(CISA KEV, NVD). | approved | 사용자 결정 2026-10-07. 저장 수집 결과 5개 Source 105건. | |
| D-026 | 2026-10-07 | 공식 RSS 묶음 형식 확인 결과에 따른 채택: KISA 보호나라 보고서·가이드 (https://www.boho.or.kr/kr/rss.do?bbsId=B0000127, 날짜만 있는 발행일, 한국 시간) 채택. 보호나라 취약점 정보 (B0000302)는 형식은 수집 가능하나 최근 글이 2026-02-27로 게시 빈도가 낮아 미채택. MSRC Security Update Guide RSS는 응답이 2MiB 상한 초과, Google Security Blog는 Atom 형식이라 현재 구조로 수집 불가. Intel·AMD·NVIDIA Product Security는 공식 RSS 주소 미확인 (NVIDIA는 GitHub CSAF, Intel은 CSAF 제공). 수집 불가 후보는 상태만 기록하고 Atom 지원·크기 상한 조정은 별도 승인. | approved | 사용자 결정 2026-10-07. 웹 검색 5회, Feed GET 4회, --dry-run 1회 (후보 0건, 최근 글이 기간 밖). | |
| D-027 | 2026-10-07 | 같은 사건 중복 처리: 다음 작업으로 중복 처리 설계 선택, boho-report-guide 저장 수집 1회 허용 (실행, 신규 0건). 규칙: (1) 제목·Feed 발췌에서 추출한 CVE 번호를 공유하는 기사는 자동으로 한 이슈로 묶음 (언어 무관, 연쇄 연결 포함). (2) 고정 제품 키워드(제목 기준, Microsoft 등 넓은 이름 제외)를 공유하고 발행일 3일 이내인 이슈는 같은 사건 후보로만 표시하고 사람이 확정 (자동 병합 없음). (3) 제목에 요약 표지(Weekly Recap, 주간 등)가 있는 기사는 묶지 않음. (4) 대표 기사는 공식 출처(CERT-EU, CISA, KISA 보호나라) 우선, 같은 등급이면 먼저 발행, 나머지는 관련 보도. (5) 결과는 저장하지 않고 호출 시점에 계산하는 순수 함수 (Schema·DB 변경 없음). 사람 확정 결과 보관은 Newsletter 반영 단계에서 별도 설계. | approved | 사용자 결정 2026-10-07. 저장 기사 105건 기준 이슈 102개, 자동 묶음 3개, 후보 5쌍, 요약 기사 1건 제외. | |
| D-028 | 2026-10-07 | 다음 작업: 실제 수집 기사(data/saba.db, 읽기 전용)를 같은 사건 묶음(group_issues)으로 정리해 비AI Newsletter Preview로 연결 (발송 없음). 선별 규칙은 설계안을 먼저 사용자에게 제시하고 확정 후 구현. | approved | 사용자 결정 2026-10-07. 설계 단계만 승인, 구현은 설계 확정 후. | |
| D-029 | 2026-10-07 | 실제 수집 기사 비AI Preview 선별 규칙: (1) 국내·해외는 Source 설정의 출처 국가 기준 (보호나라·보안뉴스 국내, CERT-EU·CISA·The Hacker News 해외), Preview용 기사 사본에만 적용하고 DB 불변. (2) 기간은 생성 시각 기준 24시간, 날짜만 있는 Source 48시간. (3) 정렬은 공식 출처 우선 → 최신 발행, Source별 최대 5건·섹션별 최대 10건 (중요도 선별 아님, 실제 Preview 확인 후 조정). (4) 같은 사건은 대표 기사 카드 1개, 묶인 기사는 "출처 · 관련 기사" 목록에 추가, 후보는 병합하지 않고 생성 스크립트 출력에만 표시. (5) output/build_collected_preview.py 로 data/saba.db 읽기 전용 생성, 출력 output/newsletter_preview_collected.html, Template 변경 없음. | approved | 사용자 결정 2026-10-07. 기준 시각 2026-10-07 09:41 UTC 생성 결과 이슈 19건 (국내 9, 해외 10). | |
| D-030 | 2026-10-07 | 실제 기사 Preview 사용자 확인 후 보완: (1) 600자를 넘는 Feed 발췌는 자르지 않고 접기·펼치기(details)로 표시 (D-003 유지, 기본 접힘, details 미지원 메일 앱은 전체 표시). (2) AI 분석 결과가 하나도 없으면 AI & Tech 빈 섹션에 "AI 분석 전이라 분류된 기사가 없습니다." 표시. (3) 상한 Source별 5건·섹션별 10건 유지. Template 구조 변경 없음 (카드 HTML만 변경). | approved | 사용자 결정 2026-10-07. 재생성 결과 카드 19건 중 5건 접힘, 발췌 내용 변경 전후 동일. | |
| D-031 | 2026-10-07 | 다음 작업: 회사 메일 TEST 발송 설계 (메일 앱 호환 HTML, 발송 방식, TEST 수신자 제한, Secret 관리, 필요한 회사 환경 정보 목록). 설계 단계만 승인, 실제 발송·메일 서버 접근·Secret 사용은 별도 승인. | approved | 사용자 결정 2026-10-07. | |
| D-032 | 2026-10-07 | 메일 호환 HTML 변환 (발송 없음): 회사 메일 환경 정보는 아직 없음, 설계안 1만 진행. 표준 라이브러리만 사용 (새 패키지 없음). 외부 CSS를 style 블록으로 포함 (완전 inline은 실제 표시 확인 후 별도 승인), script·보기 전환 제거와 자세히 보기 고정, 로고는 원본 SAMPLE/Codex/v09/LOGO.png를 CID 첨부 (축소본은 사용자 제공 시 교체), 서명은 templates/email_signature.html (원본 sign.html·sign.css 내용 그대로, 이미지 CID). .eml 은 보낸 사람·받는 사람 없이 생성. | approved | 사용자 결정 2026-10-07. 실제 발송·메일 서버 접근·Secret 사용은 여전히 미승인. | |
| D-033 | 2026-10-07 | .eml 사용자 확인 결과 보완: (1) 메일에서 오늘의 브리핑은 간략 보기와 자세히 보기를 차례로 표시 (메일 앱은 script 미실행). (2) 오늘의 브리핑 분야당 최대 5건 (공식 출처 우선 → 최신). (3) 실제 기사 AI 분석 승인: 표시 이슈 대표 기사만 gpt-4o-mini로 분석 (D-016 제목·발췌만 전송, 1회 생성당 최대 20건, 예상 $0.02 미만), 결과는 data/analysis.db 에 저장해 같은 입력은 재호출하지 않음, 보안 심층 뉴스는 AI 한국어 제목·요약(최대 2문장 300자 ≈ 3~4줄)과 핵심 사실로 표시, "대상 밖" 판정 기사는 제외, 중요도는 D-022에 따라 표시하지 않음, 분석 실패·발췌 없음은 원문 발췌로 대체. (4) 출처·관련 기사 목록은 한 줄 말줄임(...) 표시, 서명은 뉴스레터 폭 안 가운데 배치. templates/newsletter.html 과 메일 변환에 보완 CSS 추가 (SAMPLE 원본 불변). | approved | 사용자 결정 2026-10-07. 사용자 .eml 확인 문제 7건 기반. D-003·D-004의 실제 기사 표시 범위를 이 결정으로 확장. | |
| D-034 | 2026-10-07 | 실제 기사 AI 요약 보완: (1) 근거는 문장 번호 방식. 어댑터가 제목·발췌를 문장 단위로 나눠 번호를 붙여 전송하고 (중복 문장은 다음 문장과 이어 붙여 유일하게), 모델은 sentence_ids만 반환, 어댑터가 원문 문장으로 v1 근거(input_field, quote)를 로컬 생성. v1 검증 규칙 불변. (2) 모든 출력은 한국어. (3) openai_adapter 응답 대기 30초 → 60초. (4) 보완 후 실제 재분석 1회 승인 (최대 20건, 예상 $0.02 미만). | approved | 사용자 결정 2026-10-07. 직전 실행 15건 중 13건이 근거 인용 불일치로 실패. | |
| D-035 | 2026-10-07 | 실제 기사 AI 요약 보완 2: (1) 항목별 근거 번호 필수 Schema(newsletter_title_ids 등, tags·key_points 는 {text, sentence_ids})와 필드별 연속 구간 분할 변환으로 실제 재분석 1회 승인 (기준 시각 2026-10-07T09:41:30+00:00, 저장 결과 재사용, 신규 최대 20건, 예상 $0.02 미만). 결과가 낮으면 원인 보고 후 추가 호출 없이 종료. (2) 발췌 없는 보호나라 공지는 제목만 표시 유지 (본문 수집·Web Crawling 은 별도 단계에서 검토). | approved | 사용자 결정 2026-10-07. D-034 재분석에서 남은 실패 11건이 구조 문제로 확인됨. | |
| D-036 | 2026-10-07 | 사용자 확인 문제 보완: (1) 오늘의 브리핑 간략·자세히 보기는 script 없는 CSS(radio) 탭 전환. 지원하지 않는 메일 앱은 간략 보기만 표시. 내용은 SAMPLE 형식 (간략: 분야별 한 줄, 자세히: 제목 링크 + AI 요약 첫 문장), 기사 없는 분야는 숨김. (2) AnalysisResult v1 요약 상한 2문장·300자 → 최대 5문장·600자, 지시문은 3~5문장·550자 이내. 기존 2문장 결과는 data/analysis_v1_2sentence_backup.db 로 보관하고 실제 재분석 1회 승인 (최대 20건, 예상 $0.02 미만). (3) 원문 발췌·펼치기 버튼 제거, 본문은 AI 한국어 요약만 표시. SAMPLE에 없는 "핵심 사실" 상자 제거. (4) 브라우저 확인용 HTML은 이미지를 원본 파일 경로로 표시 (.eml 은 CID 유지), 서명 이미지는 실제 형식(PNG)으로 첨부. | approved | 사용자 결정 2026-10-08. 브라우저로 .html 을 열어 확인한 결과 기반. | |
